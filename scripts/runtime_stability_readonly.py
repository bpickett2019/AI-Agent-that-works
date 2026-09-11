#!/usr/bin/env python3
"""Operator-only USER 1 runtime diagnostic. No Pi, RR preparation, writes, or login reset.

Run on staging from a reviewed candidate checkout. Uses the existing uncertain
job's read-only lease, preserving its state and evidence. Fails on the first
browser error: never retries a crashed renderer or asks a model to recover it.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['CVENT_DATA_ROOT'] = '/var/lib/cvent-agent'
from control_store import ControlStore, iso
from runtime_config import browser_profile_dir, browser_cache_dir
from scripts.reconcile_registration_readonly import JOB_ID, EVENT_KEY, EVENT_NAME, readonly_lease

# This Node program samples OS/container resources only; it never connects CDP.
SAMPLE = r"""
const fs=require('fs');const read=p=>fs.readFileSync(p,'utf8');
const kv=t=>Object.fromEntries(t.trim().split('\n').map(x=>x.trim().split(/\s+/)).map(([k,v])=>[k,Number(v)]));
const base='/sys/fs/cgroup/';const shm=fs.statfsSync('/dev/shm');const processes=[];
for(const pid of fs.readdirSync('/proc').filter(x=>/^\d+$/.test(x))){try{const t=read('/proc/'+pid+'/status');const rss=t.match(/^VmRSS:\s+(\d+)/m);if(rss)processes.push({pid:Number(pid),name:t.match(/^Name:\s+(.+)/m)[1],rssBytes:Number(rss[1])*1024})}catch{}}
console.log(JSON.stringify({memoryBytes:Number(read(base+'memory.current')),peakBytes:Number(read(base+'memory.peak')),memoryMax:read(base+'memory.max').trim(),events:kv(read(base+'memory.events')),cpu:kv(read(base+'cpu.stat')),cpuMax:read(base+'cpu.max').trim(),shmBytes:shm.blocks*shm.bsize,shmUsedBytes:(shm.blocks-shm.bfree)*shm.bsize,processes}));
"""


def main():
    if not Path('/opt/cvent-one-shot/current').is_dir():
        raise RuntimeError('This diagnostic is restricted to staging')
    data = Path('/var/lib/cvent-agent')
    store = ControlStore(data / 'control.db')
    job = store.get_job(JOB_ID)
    assert job['event_key'] == EVENT_KEY and job['event_name'] == EVENT_NAME
    original = data / 'workspaces' / job['workspace_id'] / 'jobs' / JOB_ID
    folder = original / 'reconciliation' / ('runtime-' + uuid.uuid4().hex[:12])
    folder.mkdir(parents=True, mode=0o700)
    protected = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in original.iterdir()
                 if p.is_file() and p.name in {'input.xlsx', 'scope-write-audit.jsonl', 'browser-mutation-uncertain.json',
                                              'browser-runtime.json', 'configuration-plan.json', 'rr-validation.json'}}
    result = {'startedAt': iso(), 'mode': 'READ_ONLY_RUNTIME_STABILITY', 'jobId': JOB_ID,
              'benchmarkRuns': 0, 'modelCalls': 0, 'configurationWrites': 0, 'reads': [], 'pass': False}
    stop = threading.Event()
    samples = []
    sample_errors = []
    def sample_once():
        p = subprocess.run(['docker', 'exec', 'cvent-agent-steel-1', 'node', '-e', SAMPLE],
                           capture_output=True, text=True, timeout=10, check=True)
        row = {'at': iso(), 'monotonic': time.monotonic(), **json.loads(p.stdout)}
        samples.append(row)
        with (folder / 'resources.jsonl').open('a') as f:
            f.write(json.dumps(row) + '\n')
    def sample():
        while not stop.is_set():
            try:
                sample_once()
            except Exception as exc:
                sample_errors.append(str(exc))
                return
            stop.wait(2)
    def save():
        result['finishedAt'] = iso()
        (folder / 'result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps({'evidenceDirectory': str(folder), **result}), flush=True)
    print(json.dumps({'evidenceDirectory': str(folder), 'pid': os.getpid(), 'mode': result['mode']}), flush=True)
    try:
        with readonly_lease(store, JOB_ID, EVENT_KEY) as (token, lost):
            env = {k: os.environ[k] for k in ('PATH', 'LANG', 'TZ') if k in os.environ}
            env.update(CVENT_ENV='staging', CVENT_DATA_ROOT=str(data), CVENT_JOB_DIR=str(folder), CVENT_JOB_ID=JOB_ID,
                       CVENT_WORKSPACE_ID=job['workspace_id'], CVENT_WORKER_SLOT='1',
                       CVENT_BROWSER_PROFILE_DIR=str(browser_profile_dir(job['workspace_id'], 1)),
                       CVENT_BROWSER_CACHE_DIR=str(browser_cache_dir(job['workspace_id'], 1)),
                       CVENT_AUTHORIZED_EVENT_ID=job['event_id'], CVENT_AUTHORIZED_EVENT_KEY=EVENT_KEY,
                       CVENT_AUTHORIZED_EVENT_NAME=EVENT_NAME, CVENT_LEASE_TOKEN=token,
                       CVENT_LEASE_VALIDATE_URL='http://127.0.0.1:8877/internal/leases/validate')
            def steel(operation):
                p = subprocess.run([sys.executable, str(ROOT / 'steel_session.py'), operation], env=env, cwd=ROOT,
                                   capture_output=True, text=True, timeout=180)
                if p.returncode:
                    raise RuntimeError(p.stdout[-3000:] + p.stderr[-1000:])
            def browser(operation, **params):
                if operation not in {'navigate', 'authStatus', 'scanEventList', 'openAuthorizedEvent', 'authorizeTarget', 'sectionState', 'actions'}:
                    raise RuntimeError('Diagnostic operation is not read-only')
                if lost.is_set() or (folder / 'stop-requested.json').exists():
                    raise RuntimeError('Read-only diagnostic stopped or lease lost')
                params.update(intent='read', timeoutSeconds=60)
                start = time.monotonic()
                p = subprocess.run([sys.executable, str(ROOT / 'browser_tool.py'), '--runtime', str(folder / 'browser-runtime.json'),
                                    '--operation', operation, '--params', json.dumps(params)],
                                   env=env, cwd=ROOT, capture_output=True, text=True, timeout=70)
                text = p.stdout.rsplit('BROWSER_ROUTER_RESULT=', 1)[-1].strip()
                row = {'operation': operation, 'at': iso(), 'seconds': round(time.monotonic() - start, 3), 'exitCode': p.returncode}
                result['reads'].append(row)
                if p.returncode:
                    raise RuntimeError(f'{operation}: {text[-4000:]} {p.stderr[-1000:]}')
                reply = json.loads(text)
                if not reply.get('ok'):
                    raise RuntimeError(f'{operation}: {reply}')
                if operation == 'actions':
                    assert reply['writesAttempted'] == 0
                    row['completedActions'] = [a['operation'] for a in reply['actions']]
                (folder / f'read-{len(result["reads"]):03}.json').write_text(json.dumps(reply, indent=2))
                return reply
            thread = None
            try:
                steel('ensure')
                thread = threading.Thread(target=sample, daemon=True)
                thread.start()
                os.environ.update(env)
                import browser_runtime
                from browser_gate import BrowserGate
                runtime = browser_runtime.initialize(job_dir=folder, slot_id=1, authorized_name=EVENT_NAME,
                          authorized_event_id=job['event_id'], authorized_event_key=EVENT_KEY,
                          profile_path=env['CVENT_BROWSER_PROFILE_DIR'])
                runtime['accessMode'] = 'read_only_reconciliation'
                (folder / 'browser-runtime.json').write_text(json.dumps(runtime))
                BrowserGate(folder).initialize()
                browser('navigate', url='https://app.cvent.com/Subscribers/Events2/EventSelection')
                time.sleep(3)
                auth = browser('authStatus')
                result['auth'] = {k: auth.get(k) for k in ('authenticated', 'persistedProfile', 'profileMatch', 'accountContextMatch', 'workerSlot')}
                if not auth.get('authenticated'):
                    raise RuntimeError('Existing USER 1 authentication was not reused; no login or profile reset attempted')
                inventory = browser('scanEventList', exactName=EVENT_NAME, maxScrolls=60)
                assert len(inventory.get('exactMatches', [])) == 1
                result['event'] = inventory['exactMatches'][0]
                browser('openAuthorizedEvent', eventName=EVENT_NAME, eventKey=EVENT_KEY)
                browser('authorizeTarget', eventName=EVENT_NAME)
                overview = browser('sectionState')
                # Registration View is the previously verified route in the
                # reviewed reconciliation reader, not an Edit endpoint.
                urls = [overview['url'], 'https://app.cvent.com/Subscribers/Events2/Details/RegistrationTypes/Index/View?evtstub=' + EVENT_KEY]
                result['heavyPageUrls'] = urls
                # Ten cycles exercise DOM extraction and full-page screenshots
                # through the real coherent action path. Never an Edit/Save step.
                for cycle in range(10):
                    for url in urls[:3]:
                        browser('navigate', url=url)
                        browser('actions', objective=f'Read-only stability cycle {cycle + 1}', commitMode='read_only',
                                steps=[{'operation': op, 'intent': 'read', **extra} for op, extra in (
                                    ('wait', {'ms': 500}), ('snapshotText', {}), ('sectionState', {}),
                                    ('screenshot', {'fullPage': True}), ('pageInfo', {}))])
                    time.sleep(2)
                result['gateAfter'] = BrowserGate(folder).read()['activeActor']
                assert result['gateAfter'] == 'NONE'
                assert not sample_errors, sample_errors
                assert samples and not any(s['events'].get('oom_kill', 0) or s['events'].get('oom', 0) for s in samples)
                result['pass'] = True
            finally:
                stop.set()
                if thread:
                    thread.join(timeout=12)
                try:
                    inspect = subprocess.run(['docker', 'inspect', 'cvent-agent-steel-1'], capture_output=True, text=True, timeout=10)
                    if inspect.returncode == 0:
                        state = json.loads(inspect.stdout)[0]
                        if state['State']['Running']:
                            sample_once()  # Read memory.peak through the end of the diagnostic.
                        gate_path = folder / 'browser-gate.json'
                        if gate_path.exists():
                            result['gateAfter'] = json.loads(gate_path.read_text())['activeActor']
                        result['containerState'] = state['State']
                        result['containerLimits'] = {k: state['HostConfig'][k] for k in ('Memory', 'MemorySwap', 'NanoCpus', 'ShmSize')}
                        logs = subprocess.run(['docker', 'logs', '--timestamps', 'cvent-agent-steel-1'], capture_output=True, text=True, timeout=10)
                        (folder / 'steel.log').write_text(logs.stdout + logs.stderr)
                        assert not state['State']['OOMKilled']
                        assert 'Page crashed!' not in logs.stdout + logs.stderr
                finally:
                    steel('release')
    except Exception as exc:
        result['pass'] = False
        result['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        result['samples'] = len(samples)
        result['sampleErrors'] = sample_errors
        if samples:
            result['peakMemoryBytes'] = max(s['peakBytes'] for s in samples)
            result['peakShmUsedBytes'] = max(s['shmUsedBytes'] for s in samples)
            cpu = [(b['cpu']['usage_usec'] - a['cpu']['usage_usec']) / 1e6 / (b['monotonic'] - a['monotonic'])
                   for a, b in zip(samples, samples[1:])]
            result['peakCpuCoresSampled'] = max(cpu, default=0)
        result['originalEvidenceUnchanged'] = all(hashlib.sha256((original / n).read_bytes()).hexdigest() == h for n, h in protected.items())
        result['writeAuditAbsent'] = not (folder / 'scope-write-audit.jsonl').exists()
        result['pass'] &= result['originalEvidenceUnchanged'] and result['writeAuditAbsent']
        save()
    return 0 if result['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
