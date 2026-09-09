#!/usr/bin/env python3
"""Operator-only ATTED readback. No Pi, RR restart, configuration write or Save.

Borrows the original job's canonical leases without making it startable or
clearing uncertainty. Uses a separate runtime/evidence directory and USER 1's
existing profile. This script is not exposed as a model-programmable tool.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import timedelta
from urllib.parse import urlsplit, parse_qsl
import uuid

ROOT = Path(os.environ.get('CVENT_REPO_ROOT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
from control_store import ControlStore, utcnow, iso

JOB_ID = 'job_03e7e3467f4244ea84bb39b72d9e19e9'
EVENT_KEY = 'e712e34c-6117-4d13-bf4c-8ed54cf2b495'
EVENT_NAME = '(C+D) Medtrade Testing Clone 2'
READ_ACTIONS = {'pageInfo', 'authStatus', 'navigate', 'scanEventList', 'openAuthorizedEvent',
                'authorizeTarget', 'sectionState', 'snapshotText', 'controlInventory',
                'inspectRegistrationTypeCapabilities'}


@contextmanager
def readonly_lease(store, job_id, event_key, slot=1):
    """Reserve without reserve_now(), which would reset the job's uncertainty."""
    if slot != 1:
        raise ValueError('This reviewed reconciliation is restricted to USER 1')
    token = uuid.uuid4().hex
    now = iso(); expires = iso(utcnow() + timedelta(seconds=store.lease_seconds))
    with store.immediate() as c:
        row = c.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not row or row['state'] != 'failed_uncertain' or row['uncertain'] != 1 or row['pid'] is not None:
            raise RuntimeError('Readback requires the stopped uncertain job')
        if row['event_key'] != event_key or row['preferred_slot'] != slot or row['slot_id'] is not None:
            raise RuntimeError('Readback job/event/worker binding mismatch')
        if c.execute('SELECT 1 FROM event_leases WHERE event_id=?', (row['event_id'],)).fetchone():
            raise RuntimeError('Event already leased; readback did not start')
        if c.execute('SELECT 1 FROM worker_leases WHERE slot_id=?', (slot,)).fetchone():
            raise RuntimeError('USER 1 already leased; readback did not start')
        values = (job_id, token, now, now, expires)
        c.execute('INSERT INTO event_leases VALUES(?,?,?,?,?,?)', (row['event_id'], *values))
        c.execute('INSERT INTO worker_leases VALUES(?,?,?,?,?,?)', (slot, *values))
        store._audit(c, 'operator', 'reconciliation.read_lease_acquired', job_id, {'slot_id':slot})
    stop = threading.Event(); lost = threading.Event()
    def beat():
        while not stop.wait(max(1, store.lease_seconds // 3)):
            try:
                if not store.heartbeat(job_id, token):
                    lost.set(); return
            except Exception:
                lost.set(); return
    thread = threading.Thread(target=beat, daemon=True); thread.start()
    try:
        yield token, lost
    finally:
        stop.set(); thread.join(timeout=10)
        with store.immediate() as c:
            for table in ('event_leases', 'worker_leases'):
                c.execute(f'DELETE FROM {table} WHERE holder_job_id=? AND token=?', (job_id, token))
            store._audit(c, 'operator', 'reconciliation.read_lease_released', job_id, {})


def verified_detail(row, key):
    links = []
    for item in row.get('links', []):
        u = urlsplit(item['href'])
        query = parse_qsl(u.query, keep_blank_values=True)
        event_keys = [v.lower() for k,v in query if k.lower() in ('evtstub','eventid','event')]
        ids = [v for k,v in query if k.lower() == 'registrationtypestub']
        if (u.scheme == 'https' and u.hostname == 'app.cvent.com' and not u.username and not u.password
                and u.port in (None,443) and event_keys and all(v == key for v in event_keys)
                and len(ids) == 1 and ids[0]
                and re.fullmatch(r'/Subscribers/Events2/Details/RegistrationTypeDetail/Index/View/?',u.path,re.I)):
            links.append(item)
    if len(links) != 1:
        raise RuntimeError('Exact event-local registration detail is not unique')
    return links[0]


def private_json(path, value):
    owner = path.parent.stat()
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('x') as output:
        json.dump(value, output, indent=2)
    temporary.chmod(0o600)
    os.chown(temporary, owner.st_uid, owner.st_gid)
    temporary.replace(path)


def main():
    # Fixed staging/job boundary, not a generic browser or credential surface.
    data = Path('/var/lib/cvent-agent')
    if hashlib.sha256((ROOT/'trusted_cvent_procedures.mjs').read_bytes()).hexdigest() != 'e2b7d5a0282c3ae0f5cf162e4c8369241e2deb736a6e1cda5e5a68ebbaa0014f':
        raise RuntimeError('Review this reader against the current trusted procedure before using it')
    os.environ['CVENT_DATA_ROOT'] = str(data)
    from runtime_config import browser_profile_dir, browser_cache_dir
    store = ControlStore(data/'control.db')
    job = store.get_job(JOB_ID)
    assert job['event_name'] == EVENT_NAME and job['event_key'] == EVENT_KEY
    original = data/'workspaces'/job['workspace_id']/'jobs'/JOB_ID
    expected = json.loads((original/'expected-domains.json').read_text())
    validation = json.loads((original/'rr-validation.json').read_text())
    plan = json.loads((original/'configuration-plan.json').read_text())
    digest = hashlib.sha256((original/'input.xlsx').read_bytes()).hexdigest()
    assert digest == expected['rr']['sha256'] == validation['rrSha256'] == plan['rrSha256']
    assert expected['target']['eventKey'] == EVENT_KEY and expected['target']['eventId'] == job['event_id']
    assert all(x['status'] == 'VERIFIED' for x in validation['items'] if x.get('domain') == 'registration_types')
    desired = expected['domains']['registration_types']['items']
    wanted = [r for r in desired if r['fields']['registration_code']['value'] == 'ATTED']
    assert len(wanted) == 1
    protected = {name:hashlib.sha256((original/name).read_bytes()).hexdigest() for name in
                 ('input.xlsx','rr-validation.json','expected-domains.json','configuration-plan.json',
                  'browser-mutation-uncertain.json','scope-write-audit.jsonl','browser-runtime.json')}
    folder = original/'reconciliation'/('atted-'+uuid.uuid4().hex[:12]); folder.mkdir(parents=True,mode=0o700)
    owner = original.stat()
    os.chown(folder, owner.st_uid, owner.st_gid)
    # Retain a write veto even though the dispatcher below only accepts reads.
    (folder/'browser-mutation-uncertain.json').write_bytes((original/'browser-mutation-uncertain.json').read_bytes())
    result = {'jobId':JOB_ID,'mode':'READ_ONLY','rrSha256':digest,'desired':wanted[0],
              'configurationMutations':0,'saveCalls':0,'readOperations':[]}
    try:
        with readonly_lease(store, JOB_ID, EVENT_KEY) as (token, lost):
            env = {k:os.environ[k] for k in ('PATH','LANG','LC_ALL','TZ') if k in os.environ}
            env.update({'CVENT_ENV':'staging','CVENT_REPO_ROOT':str(ROOT),'CVENT_DATA_ROOT':str(data),
                        'CVENT_JOB_DIR':str(folder),'CVENT_JOB_ID':JOB_ID,'CVENT_WORKSPACE_ID':job['workspace_id'],
                        'CVENT_WORKER_SLOT':'1','CVENT_BROWSER_PROFILE_DIR':str(browser_profile_dir(job['workspace_id'],1)),
                        'CVENT_BROWSER_CACHE_DIR':str(browser_cache_dir(job['workspace_id'],1)),
                        'CVENT_AUTHORIZED_EVENT_ID':job['event_id'],'CVENT_AUTHORIZED_EVENT_KEY':EVENT_KEY,
                        'CVENT_AUTHORIZED_EVENT_NAME':EVENT_NAME,'CVENT_LEASE_TOKEN':token,
                        'CVENT_LEASE_VALIDATE_URL':'http://127.0.0.1:8877/internal/leases/validate'})
            def steel(operation):
                p = subprocess.run([sys.executable,str(ROOT/'steel_session.py'),operation],env=env,cwd=ROOT,
                                   capture_output=True,text=True,timeout=180)
                if p.returncode: raise RuntimeError('Steel lifecycle operation failed: '+operation)
                return json.loads(next(l.split('=',1)[1] for l in p.stdout.splitlines() if l.startswith('STEEL_RESULT=')))
            def browser(operation, **params):
                if operation not in READ_ACTIONS: raise RuntimeError('Non-read operation denied')
                if (folder/'stop-requested.json').exists(): raise RuntimeError('Operator stopped read-only reconciliation')
                if lost.is_set() or not store.valid_event_lease(JOB_ID,token,job['event_id']):
                    raise RuntimeError('Read lease lost')
                params.update(intent='read',timeoutSeconds=90)
                started = time.monotonic()
                p = subprocess.run([sys.executable,str(ROOT/'browser_tool.py'),'--runtime',str(folder/'browser-runtime.json'),
                                    '--operation',operation,'--params',json.dumps(params)],env=env,cwd=ROOT,
                                   capture_output=True,text=True,timeout=100)
                if p.returncode: raise RuntimeError('Bounded read failed: '+operation)
                r = json.loads(next(l.split('=',1)[1] for l in reversed(p.stdout.splitlines()) if l.startswith('BROWSER_ROUTER_RESULT=')))
                if not r.get('ok'): raise RuntimeError('Read did not return a valid result: '+operation)
                result['readOperations'].append({'operation':operation,'seconds':round(time.monotonic()-started,3)})
                return r
            try:
                steel('ensure')
                os.environ.update(env)
                import browser_runtime
                from browser_gate import BrowserGate
                runtime=browser_runtime.initialize(job_dir=folder,slot_id=1,authorized_name=EVENT_NAME,
                    authorized_event_id=job['event_id'],authorized_event_key=EVENT_KEY,
                    profile_path=env['CVENT_BROWSER_PROFILE_DIR'])
                runtime['accessMode']='read_only_reconciliation'
                private_json(folder/'browser-runtime.json',runtime)
                BrowserGate(folder).initialize()
                # The service must be able to read this runtime and lock its
                # gate even when the operator coordinator was launched by root.
                for file in folder.iterdir():
                    if file.is_file() and not file.is_symlink():
                        os.chown(file, owner.st_uid, owner.st_gid)
                private_json(original/'read-only-reconciliation.json',{
                    'jobId':JOB_ID,'directory':folder.name,'browserRuntimeId':runtime['browserRuntimeId'],
                    'leaseFingerprint':hashlib.sha256(token.encode()).hexdigest()})
                browser('navigate',url='https://app.cvent.com/Subscribers/Events2/EventSelection')
                auth = None
                for _ in range(10):
                    auth = browser('authStatus')
                    if auth.get('authenticated'): break
                    time.sleep(1)
                result['auth'] = {k:auth.get(k) for k in ('authenticated','persistedProfile','profileMatch','accountContextMatch','workerSlot')}
                if not auth.get('authenticated'):
                    page=browser('pageInfo')['page']; url=urlsplit(page['url'])
                    result['auth'].update(pageHost=url.hostname,pagePath=url.path)
                    gate=BrowserGate(folder)
                    with gate.lock_file():
                        value=gate.read();value.update(ownership='USER',desiredOwnership='USER',activeActor='USER',agentPaused=True)
                        gate.write(value)
                    print(json.dumps({'handoffRequired':True,'jobId':JOB_ID,'evidenceDirectory':str(folder),'auth':result['auth']}),flush=True)
                    deadline=time.monotonic()+1800
                    while time.monotonic()<deadline:
                        if lost.is_set() or (folder/'stop-requested.json').exists():
                            raise RuntimeError('Read-only handoff stopped; no write attempted')
                        current=gate.read()
                        if current.get('ownership')=='AGENT' and current.get('desiredOwnership')=='AGENT':break
                        time.sleep(1)
                    else:raise RuntimeError('Read-only login handoff timed out; no write attempted')
                    auth=browser('authStatus')
                    if not auth.get('authenticated'):raise RuntimeError('Returned browser did not pass fresh authentication')
                    result['auth']={k:auth.get(k) for k in ('authenticated','persistedProfile','profileMatch','accountContextMatch','workerSlot')}
                # Login can return to a dashboard rather than the event inventory.
                # Navigate to the previously proven inventory route before scanning.
                browser('navigate',url='https://app.cvent.com/Subscribers/Events2/EventSelection')
                time.sleep(1)
                inventory = browser('scanEventList',exactName=EVENT_NAME,maxScrolls=60)
                matches = inventory.get('exactMatches',[])
                result['eventInventoryMatches']=matches
                result['inventoryObservedRows']=len(inventory.get('observedRows',[]))
                if len(matches)!=1:
                    raise RuntimeError('Unique exact event inventory match not established')
                result['eventInventory'] = matches[0]
                result['eventLifecycleStatusObserved'] = matches[0].get('status')
                browser('openAuthorizedEvent',eventName=EVENT_NAME,eventKey=EVENT_KEY)
                browser('authorizeTarget',eventName=EVENT_NAME)
                identities=[{'code':item['fields']['registration_code']['value'],
                             'name':item['fields']['registration_name']['value']} for item in desired]
                capabilities=browser('inspectRegistrationTypeCapabilities',records=identities,probeCode='ATTED')
                private_json(folder/'registration-capability-readback.json',capabilities)
                result['registrationCapabilities']=capabilities
                grid_url='https://app.cvent.com/Subscribers/Events2/Details/RegistrationTypes/Index/View?evtstub='+EVENT_KEY
                browser('navigate',url=grid_url); time.sleep(1)
                grid=browser('sectionState')
                header=lambda s: re.sub('[\uE000-\uF8FF]','',s).strip().lower()
                columns={i for row in grid['rows'] if any(header(c)=='name' for c in row['cells'])
                         for i,c in enumerate(row['cells']) if header(c)=='code'}
                if len(columns)!=1: raise RuntimeError('Exact Code column not established')
                code_column=next(iter(columns))
                deltas=[];atted_row=None
                for requirement in desired:
                    code=requirement['fields']['registration_code']['value']
                    found=[r for r in grid['rows'] if len(r['cells'])>code_column and r['cells'][code_column].strip()==code]
                    d={'code':code,'exactMatches':len(found),'desiredName':requirement['fields']['registration_name']['value']}
                    if len(found)==1:
                        link=verified_detail(found[0],EVENT_KEY); d.update(actualName=link['text'],nameStatus='MATCH' if link['text']==d['desiredName'] else 'MISMATCH')
                        if code=='ATTED':atted_row=found[0]
                    else:d['nameStatus']='AMBIGUOUS' if found else 'NOT_READABLE'
                    deltas.append(d)
                result['registrationTypeInventoryDelta']=deltas
                private_json(folder/'registration-grid-readback.json',{'url':grid['url'],'rows':grid['rows'],'headings':grid.get('headings'), 'buttons':grid.get('buttons')})
                if not atted_row: raise RuntimeError('ATTED exact identity is not unique')
                link=verified_detail(atted_row,EVENT_KEY)
                browser('navigate',url=link['href']); time.sleep(1)
                detail=browser('sectionState'); snapshot=browser('snapshotText').get('snapshot','')
                # Only RR property controls, never framework/security token values.
                allowed={'name','code','active','isactive','registrationcode','registrationtypecode',
                         'registrationtypename','groupregistration','allowgroupregistration',
                         'openforregistration','isopenforregistration'}
                controls=[]
                for item in detail.get('controls',[]):
                    label=re.sub(r'[^a-z]','',str(item.get('label','')).lower())
                    if label in allowed:controls.append(item)
                result['actual']={'url':detail['url'],'pageTitle':detail['title'],'gridName':link['text'],
                                  'headings':detail.get('headings'),'buttons':detail.get('buttons'),
                                  'rrPropertyControls':controls}
                result['eventTitleUnchanged']=EVENT_NAME in snapshot
                snap_path=folder/'atted-fresh-readback.txt';snap_path.write_text(snapshot);snap_path.chmod(0o600)
                private_json(folder/'atted-readback.json',result)
                print(json.dumps({'evidenceDirectory':str(folder),'auth':result['auth'],
                    'eventTitleUnchanged':result['eventTitleUnchanged'],'actual':result['actual'],
                    'registrationTypeInventoryDelta':deltas},indent=2))
            except RuntimeError as error:
                result['readError']=str(error)
                private_json(folder/'atted-readback.json',result)
                if result.get('auth',{}).get('authenticated') and not lost.is_set() and not (folder/'stop-requested.json').exists():
                    print(json.dumps({'readPaused':True,'error':str(error),'evidenceDirectory':str(folder),
                        'eventInventoryMatches':result.get('eventInventoryMatches'),
                        'inventoryObservedRows':result.get('inventoryObservedRows')}),flush=True)
                    # Retain an authenticated read-only browser for diagnosis
                    # rather than forcing another login after an inventory error.
                    deadline=time.monotonic()+1800
                    while time.monotonic()<deadline and not lost.is_set() and not (folder/'stop-requested.json').exists():
                        time.sleep(1)
                raise
            finally:
                released=steel('release')
                if not released.get('released'): raise RuntimeError('Browser resource did not release cleanly')
    finally:
        pointer=original/'read-only-reconciliation.json'
        if pointer.exists() and json.loads(pointer.read_text()).get('directory')==folder.name:
            pointer.unlink()
        result['finishedAt']=iso()
        result['originalEvidenceUnchanged']=all(hashlib.sha256((original/name).read_bytes()).hexdigest()==value for name,value in protected.items())
        result['writeAuditAbsent']=not (folder/'scope-write-audit.jsonl').exists()
        private_json(folder/'atted-readback.json',result)
        print(json.dumps({'evidenceDirectory':str(folder),'originalEvidenceUnchanged':result['originalEvidenceUnchanged'],
                          'writeAuditAbsent':result['writeAuditAbsent']}))
        assert result['originalEvidenceUnchanged'] and result['writeAuditAbsent']


if __name__ == '__main__':
    main()
