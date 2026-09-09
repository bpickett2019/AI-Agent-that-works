"""Operator-only continuation of ATTED reads in an already leased read-only browser.
No login, new runtime, RR restart, ownership change, or configuration operation.
Event lifecycle status is evidence, not a reason to omit authorized readback.
"""
import os
os.environ['CVENT_DATA_ROOT']='/var/lib/cvent-agent'
import sys
from pathlib import Path
ROOT=Path('/opt/cvent-one-shot/current')
sys.path.insert(0,str(ROOT))
import json
import hashlib
import subprocess
import time
from urllib.parse import urlsplit,parse_qsl
from control_store import ControlStore
from readonly_session import resolve_readonly_session
from browser_gate import BrowserGate
from scripts.reconcile_registration_readonly import JOB_ID, EVENT_KEY, EVENT_NAME, READ_ACTIONS, verified_detail


def main():
    store=ControlStore(Path('/var/lib/cvent-agent/control.db'))
    job=store.get_job(JOB_ID)
    original=Path('/var/lib/cvent-agent/workspaces')/job['workspace_id']/'jobs'/JOB_ID
    active=resolve_readonly_session(store,job,original)
    if not active:raise RuntimeError('No valid existing read-only reconciliation lease')
    folder=active.runtime_dir
    gate=BrowserGate(folder).read()
    if gate['ownership']!='AGENT' or gate['desiredOwnership']!='AGENT':
        raise RuntimeError('Human owns the browser; no read attempted')
    runtime=json.loads((folder/'browser-runtime.json').read_text())
    with store.connect() as c:
        lease=c.execute('SELECT token FROM event_leases WHERE holder_job_id=? AND event_id=?',(JOB_ID,job['event_id'])).fetchone()
    token=lease['token']
    assert job['event_key']==EVENT_KEY and job['event_name']==EVENT_NAME
    expected=json.loads((original/'expected-domains.json').read_text())
    digest=hashlib.sha256((original/'input.xlsx').read_bytes()).hexdigest()
    assert digest==expected['rr']['sha256']==json.loads((original/'rr-validation.json').read_text())['rrSha256']
    protected={name:hashlib.sha256((original/name).read_bytes()).hexdigest() for name in
               ('browser-mutation-uncertain.json','scope-write-audit.jsonl','browser-runtime.json')}
    env={k:os.environ[k] for k in ('PATH','LANG','TZ') if k in os.environ}
    env.update(CVENT_ENV='staging',CVENT_DATA_ROOT='/var/lib/cvent-agent',CVENT_JOB_DIR=str(folder),
               CVENT_JOB_ID=JOB_ID,CVENT_WORKSPACE_ID=job['workspace_id'],CVENT_WORKER_SLOT='1',
               CVENT_BROWSER_PROFILE_DIR=runtime['profilePath'],CVENT_AUTHORIZED_EVENT_ID=job['event_id'],
               CVENT_AUTHORIZED_EVENT_KEY=EVENT_KEY,CVENT_AUTHORIZED_EVENT_NAME=EVENT_NAME,
               CVENT_LEASE_TOKEN=token,CVENT_LEASE_VALIDATE_URL='http://127.0.0.1:8877/internal/leases/validate')
    reads=[]
    def browser(operation,**params):
        if operation not in READ_ACTIONS:raise RuntimeError('Non-read operation prohibited')
        if not store.valid_event_lease(JOB_ID,token,job['event_id']) or (folder/'stop-requested.json').exists():
            raise RuntimeError('Read lease unavailable or stopped')
        params.update(intent='read',timeoutSeconds=90)
        p=subprocess.run([sys.executable,str(ROOT/'browser_tool.py'),'--runtime',str(folder/'browser-runtime.json'),
                          '--operation',operation,'--params',json.dumps(params)],env=env,cwd=ROOT,capture_output=True,text=True,timeout=100)
        if p.returncode:raise RuntimeError('Read failed: '+operation)
        r=json.loads(next(l.split('=',1)[1] for l in reversed(p.stdout.splitlines()) if l.startswith('BROWSER_ROUTER_RESULT=')))
        if not r.get('ok'):raise RuntimeError('Invalid read result: '+operation)
        reads.append(operation);return r
    def save(name,value):
        path=folder/name;path.write_text(json.dumps(value,indent=2));path.chmod(0o600)
        owner=folder.stat();os.chown(path,owner.st_uid,owner.st_gid)
    # Verify authentication on the supported inventory origin. Event opening
    # can legitimately redirect to events.app.cvent.com; the following exact
    # key/banner lock still has to be proved on that destination.
    browser('navigate',url='https://app.cvent.com/Subscribers/Events2/EventSelection')
    for _ in range(8):
        time.sleep(1)
        auth=browser('authStatus')
        if auth.get('authenticated'):break
    if not auth.get('authenticated'):
        page=browser('pageInfo')['page'];url=urlsplit(page['url'])
        query=parse_qsl(url.query)
        keys=[v.lower() for k,v in query if k.lower() in ('evtstub','eventid','event')]
        print(json.dumps({'auth':auth,'pageHost':url.hostname,'pagePath':url.path,'title':page['title'],
                          'queryNames':[k for k,v in query],'eventKeys':keys}))
        if keys and all(k==EVENT_KEY for k in keys) and url.hostname=='events.app.cvent.com':
            snapshot=browser('snapshotText')
            save('modern-event-home-readback.json',snapshot)
            print(json.dumps({'selectedEventLines':[line for line in str(snapshot.get('snapshot','')).splitlines()
                        if EVENT_NAME in line or 'Draft' in line or 'Completed' in line or 'Event Status' in line]}))
        raise RuntimeError('Fresh authentication not established')
    inventory=browser('scanEventList',exactName=EVENT_NAME,maxScrolls=60)
    matches=inventory.get('exactMatches',[])
    assert len(matches)==1
    u=urlsplit(matches[0]['href']); keys=[v.lower() for k,v in parse_qsl(u.query) if k.lower() in ('evtstub','eventid','event')]
    assert u.scheme=='https' and u.hostname=='app.cvent.com' and keys and all(k==EVENT_KEY for k in keys)
    result={'mode':'READ_ONLY','rrSha256':digest,'eventInventory':matches[0],
            'writesPermitted':False,'configurationWrites':0,'saveCalls':0}
    # A Completed label prevents write eligibility, not inspection of the
    # same explicitly authorized event. No lifecycle status is modified.
    browser('openAuthorizedEvent',eventName=EVENT_NAME,eventKey=EVENT_KEY)
    for _ in range(12):
        time.sleep(1)
        overview=browser('snapshotText')
        if EVENT_NAME in str(overview):break
    save('fresh-overview-readback.json',overview)
    browser('authorizeTarget',eventName=EVENT_NAME)
    grid_url='https://app.cvent.com/Subscribers/Events2/Details/RegistrationTypes/Index/View?evtstub='+EVENT_KEY
    browser('navigate',url=grid_url);time.sleep(1)
    grid=browser('sectionState')
    save('fresh-registration-grid.json',{'url':grid['url'],'rows':grid['rows'],'headings':grid['headings']})
    import re
    clean=lambda s:re.sub('[\uE000-\uF8FF]','',s).strip().lower()
    columns={i for row in grid['rows'] if any(clean(c)=='name' for c in row['cells'])
             for i,c in enumerate(row['cells']) if clean(c)=='code'}
    assert len(columns)==1
    column=next(iter(columns));deltas=[];atted=None
    for requirement in expected['domains']['registration_types']['items']:
        fields=requirement['fields'];code=fields['registration_code']['value']
        found=[r for r in grid['rows'] if len(r['cells'])>column and r['cells'][column].strip()==code]
        record={'code':code,'exactMatches':len(found),'expectedName':fields['registration_name']['value']}
        if len(found)==1:
            link=verified_detail(found[0],EVENT_KEY)
            record.update(actualName=link['text'],nameStatus='MATCH' if link['text']==record['expectedName'] else 'MISMATCH')
            if code=='ATTED':atted=(requirement,link)
        else:record['nameStatus']='AMBIGUOUS' if found else 'NOT_READABLE'
        deltas.append(record)
    result['registrationInventoryDelta']=deltas
    save('fresh-reconciliation-result.json',result)
    if not atted:raise RuntimeError('ATTED exact identity unavailable')
    requirement,link=atted
    browser('navigate',url=link['href']);time.sleep(1)
    detail=browser('sectionState')
    assert any(k.lower()=='evtstub' and v.lower()==EVENT_KEY for k,v in parse_qsl(urlsplit(detail['url']).query))
    snapshot=browser('snapshotText')
    save('fresh-atted-snapshot.json',snapshot)
    wanted={'name','code','active','isactive','registrationcode','registrationtypecode','registrationtypename',
            'groupregistration','allowgroupregistration','openforregistration','isopenforregistration'}
    controls=[item for item in detail.get('controls',[]) if re.sub('[^a-z]','',str(item.get('label','')).lower()) in wanted]
    result['atted']={'url':detail['url'],'title':detail['title'],'name':link['text'],
                     'desired':requirement['fields'],'rrPropertyControls':controls,'headings':detail['headings'],'buttons':detail['buttons']}
    result['eventTitleUnchanged']=EVENT_NAME in str(snapshot)
    result['reads']=reads
    result['originalEvidenceUnchanged']=all(hashlib.sha256((original/n).read_bytes()).hexdigest()==v for n,v in protected.items())
    result['writeAuditAbsent']=not (folder/'scope-write-audit.jsonl').exists()
    assert result['originalEvidenceUnchanged'] and result['writeAuditAbsent']
    save('fresh-reconciliation-result.json',result)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
