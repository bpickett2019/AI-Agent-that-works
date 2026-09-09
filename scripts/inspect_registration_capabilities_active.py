#!/usr/bin/env python3
"""Continue only registration capability reads in an active read-only runtime.

This does not start Steel, restart a job, run Pi, repeat item reconciliation, or dispatch a
configuration operation. It is reusable for an explicitly selected uncertain
job whose read-only coordinator already owns USER 1 and the canonical event.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import parse_qsl, urlsplit

os.environ.setdefault('CVENT_DATA_ROOT', '/var/lib/cvent-agent')
ROOT = Path(os.environ.get('CVENT_REPO_ROOT', '/opt/cvent-one-shot/current')).resolve()
sys.path.insert(0, str(ROOT))
from browser_gate import BrowserGate
from control_store import ControlStore
from readonly_session import private_json, resolve_readonly_session

OPERATIONS = {'pageInfo', 'snapshotText', 'authorizeTarget', 'inspectRegistrationTypeCapabilities'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--job-id', required=True)
    args = parser.parse_args()
    data = Path(os.environ['CVENT_DATA_ROOT'])
    store = ControlStore(data/'control.db')
    job = store.get_job(args.job_id)
    if not job or job['state'] != 'failed_uncertain' or job['uncertain'] != 1:
        raise RuntimeError('Capability continuation requires the retained uncertain job')
    if job['preferred_slot'] != 1 or job['pid'] is not None or job['slot_id'] is not None:
        raise RuntimeError('Capability continuation is restricted to stopped USER 1 jobs')
    original = data/'workspaces'/job['workspace_id']/'jobs'/job['id']
    active = resolve_readonly_session(store, job, original)
    if not active:
        raise RuntimeError('No valid active read-only runtime and canonical leases')
    folder = active.runtime_dir
    gate = BrowserGate(folder).read()
    if gate['ownership'] != 'AGENT' or gate['desiredOwnership'] != 'AGENT':
        raise RuntimeError('Human still owns the read-only browser')
    runtime = json.loads((folder/'browser-runtime.json').read_text())
    if runtime.get('accessMode') != 'read_only_reconciliation' or runtime.get('workerSlot') != 1:
        raise RuntimeError('Runtime is not the fixed USER 1 read-only mode')
    with store.connect() as connection:
        lease = connection.execute(
            'SELECT token FROM event_leases WHERE holder_job_id=? AND event_id=?',
            (job['id'], job['event_id'])).fetchone()
    if not lease or not store.valid_event_lease(job['id'], lease['token'], job['event_id']):
        raise RuntimeError('Canonical event lease is unavailable')
    expected = json.loads((original/'expected-domains.json').read_text())
    validation = json.loads((original/'rr-validation.json').read_text())
    digest = hashlib.sha256((original/'input.xlsx').read_bytes()).hexdigest()
    if digest != expected['rr']['sha256'] or digest != validation['rrSha256']:
        raise RuntimeError('Compiled RR binding changed')
    if expected['target']['eventId'] != job['event_id'] or expected['target']['eventKey'] != job['event_key']:
        raise RuntimeError('Compiled target binding changed')
    items = expected['domains']['registration_types']['items']
    identities = [{'code':item['fields']['registration_code']['value'],
                   'name':item['fields']['registration_name']['value']} for item in items]
    if not identities or len({item['code'] for item in identities}) != len(identities):
        raise RuntimeError('RR registration identities are absent or duplicated')
    verified = [item for item in validation['items'] if item.get('domain') == 'registration_types']
    if not verified or any(item.get('status') != 'VERIFIED' for item in verified):
        raise RuntimeError('Registration RR evidence is not independently verified')
    env = {key:os.environ[key] for key in ('PATH','LANG','LC_ALL','TZ') if key in os.environ}
    env.update(CVENT_ENV='staging', CVENT_DATA_ROOT=str(data), CVENT_JOB_DIR=str(folder),
               CVENT_JOB_ID=job['id'], CVENT_WORKSPACE_ID=job['workspace_id'],
               CVENT_WORKER_SLOT='1', CVENT_BROWSER_PROFILE_DIR=runtime['profilePath'],
               CVENT_AUTHORIZED_EVENT_ID=job['event_id'],
               CVENT_AUTHORIZED_EVENT_KEY=job['event_key'],
               CVENT_AUTHORIZED_EVENT_NAME=job['event_name'], CVENT_LEASE_TOKEN=lease['token'],
               CVENT_LEASE_VALIDATE_URL='http://127.0.0.1:8877/internal/leases/validate')

    def browser(operation, **params):
        if operation not in OPERATIONS:
            raise RuntimeError('Non-capability read operation prohibited')
        if not store.valid_event_lease(job['id'], lease['token'], job['event_id']):
            raise RuntimeError('Read lease lost')
        timeout = 180 if operation == 'inspectRegistrationTypeCapabilities' else 90
        params.update(intent='read', timeoutSeconds=timeout)
        process = subprocess.run(
            [sys.executable, str(ROOT/'browser_tool.py'), '--runtime', str(folder/'browser-runtime.json'),
             '--operation', operation, '--params', json.dumps(params)],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout+15)
        if process.returncode:
            raise RuntimeError('Fixed capability read failed: '+operation)
        line = next(value for value in reversed(process.stdout.splitlines())
                    if value.startswith('BROWSER_ROUTER_RESULT='))
        result = json.loads(line.split('=', 1)[1])
        if not result.get('ok'):
            raise RuntimeError('Fixed capability read returned invalid output: '+operation)
        return result

    # The coordinator already opened the exact event. Wait for its modern home
    # banner instead of repeating inventory, login, or prior item reconciliation.
    page = browser('pageInfo')['page']
    parsed = urlsplit(page['url'])
    keys = [value.lower() for name,value in parse_qsl(parsed.query)
            if name.lower() in ('evtstub','eventid','event')]
    if not keys or any(value != job['event_key'] for value in keys):
        raise RuntimeError('Current browser no longer has the exact authorized event key')
    overview = None
    for _ in range(20):
        overview = browser('snapshotText')
        if job['event_name'] in str(overview.get('snapshot','')):
            break
        time.sleep(1)
    else:
        raise RuntimeError('Visible exact event banner did not render')
    browser('authorizeTarget', eventName=job['event_name'])
    result = browser('inspectRegistrationTypeCapabilities', records=identities,
                     probeCode=identities[0]['code'])
    evidence = {
        'mode':'READ_ONLY_CAPABILITY_INSPECTION', 'jobId':job['id'],
        'eventId':job['event_id'], 'eventKey':job['event_key'], 'eventName':job['event_name'],
        'rrSha256':digest, 'result':result, 'configurationWrites':0, 'saveCalls':0,
        'attedReadRepeated':False,
    }
    private_json(folder/'registration-capability-readback.json', evidence)
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
