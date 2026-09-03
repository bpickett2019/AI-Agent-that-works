#!/opt/homebrew/opt/python@3.11/bin/python3.11
"""Ego router pinned to the canonical Steel Chromium."""
from __future__ import annotations
import argparse,json,os,re,subprocess,sys,urllib.error,urllib.parse,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import parse_qs,urlparse
from browser_gate import action
from browser_runtime import load,local_probe
from scope_manifest import SCOPE_MANIFEST as DEFAULT_SCOPE_MANIFEST, SCOPE_WORKBOOK as DEFAULT_SCOPE_WORKBOOK, load_manifest as load_scope_manifest
ROOT=Path(__file__).resolve().parent;CURRENT=Path(os.environ.get('CVENT_JOB_DIR',ROOT/'data'/'current'));SCOPE_MANIFEST=DEFAULT_SCOPE_MANIFEST;SCOPE_WORKBOOK=DEFAULT_SCOPE_WORKBOOK
EGO={'probe','authorizeTarget','openAuthorizedEvent','snapshotText','controlInventory','pageInfo','scanEventList','scroll','click','activate','fill','type','navigate','wait','hover','selectOption','setChecked','press','search','selectText','drag'}
INTENT_REQUIRED={'click','activate','fill','type','hover','selectOption','setChecked','press','search','selectText','drag'}
def event_key(url):
    try:
        q={key.lower():value for key,value in parse_qs(urlparse(url).query).items()}
        for k in ('evtstub','eventid','event'):
            if q.get(k):return q[k][0].lower()
        match=re.search(r'/events/([0-9a-f-]{20,})',urlparse(url).path,re.I)
        if match:return match.group(1).lower()
    except Exception:pass
    return None
def target_lock():
    try:return json.loads((CURRENT/'authorized-target.json').read_text())
    except Exception:return {}
def emit(data):print('BROWSER_ROUTER_RESULT='+json.dumps(data,ensure_ascii=False))
def audit_scope_write(operation,params,current,result,error=None):
    record={'at':datetime.now(timezone.utc).isoformat(),'operation':operation,'scopeIds':params.get('scopeIds',[]),'eventKey':event_key(current.get('url','')),'url':current.get('url'),'result':result}
    if error:record['error']=str(error)[-800:]
    with (CURRENT/'scope-write-audit.jsonl').open('a') as output:output.write(json.dumps(record,ensure_ascii=False)+'\n')
def mark_mutation_uncertain(operation,params,current,error):
    marker=CURRENT/'browser-mutation-uncertain.json';tmp=marker.with_suffix('.tmp')
    tmp.write_text(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'operation':operation,'scopeIds':params.get('scopeIds',[]),'eventKey':event_key(current.get('url','')),'url':current.get('url'),'error':str(error)[-800:]},indent=2));tmp.replace(marker)
def child_result(proc):
    marker='BROWSER_TOOL_RESULT=';index=proc.stdout.rfind(marker)
    if index>=0:
        try:return json.loads(proc.stdout[index+len(marker):].strip())
        except json.JSONDecodeError:pass
    return {'ok':False,'error':(proc.stderr or proc.stdout)[-1200:]}
def lease_is_valid(url,job_id,token,event_id):
    query=urllib.parse.urlencode({'job_id':job_id,'event_id':event_id})
    request=urllib.request.Request(url+'?'+query,headers={'X-CVENT-Lease-Token':token})
    try:
        with urllib.request.urlopen(request,timeout=5) as response:return response.status==204
    except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError):return False
def assert_event_lease(runtime):
    job_id=os.environ.get('CVENT_JOB_ID');token=os.environ.get('CVENT_LEASE_TOKEN');url=os.environ.get('CVENT_LEASE_VALIDATE_URL');event_id=runtime.get('authorizedEventId')
    if not job_id and os.environ.get('CVENT_ENV','development')!='production':return
    if not job_id or not token or not url or not event_id:raise RuntimeError('Write blocked: job event-lease context is absent')
    if not lease_is_valid(url,job_id,token,event_id):raise RuntimeError('Write blocked: canonical event lease is absent, stale, mismatched, or owned by another job')
def guard(runtime,operation,params):
    current=local_probe(runtime);lock=target_lock()
    locked=event_key(lock.get('url',''));current_key=event_key(current.get('url',''))
    valid_lock=lock.get('name')==runtime['authorizedEventName'] and bool(locked) and lock.get('event_key')==locked and (not runtime.get('authorizedEventId') or lock.get('event_id')==runtime['authorizedEventId']) and lock.get('browser_runtime_id')==runtime.get('browserRuntimeId')
    intent=params.get('intent')
    if operation=='openAuthorizedEvent':
        assert_event_lease(runtime)
        current_host=(urlparse(current.get('url','')).hostname or '').lower()
        if not current_host.endswith('cvent.com') or '/events2/eventselection' not in urlparse(current.get('url','')).path.lower():
            raise RuntimeError('Authorized event opening requires the authenticated Cvent event inventory')
        if params.get('eventName')!=runtime.get('authorizedEventName') or params.get('eventKey')!=runtime.get('authorizedEventKey'):
            raise RuntimeError('Authorized event opening identity does not match BrowserRuntime')
    if operation in INTENT_REQUIRED and intent not in ('read','write'):
        raise RuntimeError(f'{operation} requires explicit read or write intent')
    if intent=='write':
        if (CURRENT/'browser-mutation-uncertain.json').exists():
            raise RuntimeError('Write blocked: a prior browser mutation timed out with uncertain outcome; fresh human review is required')
        if not valid_lock or current_key!=locked:
            raise RuntimeError('Write blocked: exact authorized event lock is absent or not currently open')
        if runtime.get('authorizedEventKey') and locked!=runtime['authorizedEventKey']:
            raise RuntimeError('Write blocked: visible event key does not match the server-authorized event')
        assert_event_lease(runtime)
        refs=params.get('scopeIds',[])
        if isinstance(refs,str):refs=[refs]
        if not isinstance(refs,list) or not refs or any(not isinstance(ref,str) for ref in refs):
            raise RuntimeError('Write blocked: at least one confirmed Forge Intake scopeId is required')
        manifest=load_scope_manifest(SCOPE_WORKBOOK,SCOPE_MANIFEST);entries={entry['id']:entry for entry in manifest['entries']}
        blocked=[ref for ref in refs if ref not in entries or entries[ref].get('status')!='confirmed']
        if blocked:raise RuntimeError('Write blocked by Forge Intake scope: '+', '.join(blocked))
    if operation in ('navigate','browser_navigate'):
        url=params.get('url','');parsed=urlparse(url);host=(parsed.hostname or '').lower();key=event_key(url)
        if host and not (host=='cvent.com' or host.endswith('.cvent.com')):raise RuntimeError('Navigation outside Cvent is blocked')
        if re.search(r'/(account|organization|admin|global)(/|$)',parsed.path,re.I):raise RuntimeError('Navigation to account-global Cvent settings is blocked')
        if key and (not valid_lock or key!=locked):raise RuntimeError('Navigation to a non-authorized Cvent event blocked')
    return current
def run_direct(runtime_path,runtime,tool,operation,params):
    executable=['node','ego_direct.mjs']
    with action(runtime['browserRuntimeId'],'PI_EGO'):
        current=guard(runtime,operation,params)
        if operation=='authorizeTarget':
            probe=subprocess.run(['node','ego_direct.mjs','--runtime',str(runtime_path),'--operation','snapshotText','--params','{}'],cwd=ROOT,text=True,capture_output=True,timeout=90);observed=child_result(probe)
            info=local_probe(runtime);key=event_key(info.get('url',''))
            host=(urlparse(info.get('url','')).hostname or '').lower()
            if params.get('eventName')!=runtime['authorizedEventName'] or runtime['authorizedEventName'].lower() not in json.dumps(observed).lower() or not key or not host.endswith('cvent.com'):raise RuntimeError('Exact visible authorized event identity was not proven')
            if runtime.get('authorizedEventKey') and key!=runtime['authorizedEventKey']:raise RuntimeError('Visible event key is not the server-authorized event')
            lock={'name':runtime['authorizedEventName'],'event_id':runtime.get('authorizedEventId'),'url':info['url'],'event_key':key,'browser_runtime_id':runtime['browserRuntimeId'],'locked_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),'mode':'mock','source':'ego-direct'}
            target=CURRENT/'authorized-target.json';tmp=target.with_suffix('.tmp');tmp.write_text(json.dumps(lock,indent=2));tmp.replace(target)
            runtime['targetBrowserIdentity'].update({'url':info['url'],'title':info['title']});tmp=runtime_path.with_suffix('.tmp');tmp.write_text(json.dumps(runtime,indent=2));tmp.replace(runtime_path)
            return {'ok':True,'tool':'ego','operation':operation,'authorizedTarget':lock,'router':'ego'}
        is_write=params.get('intent')=='write'
        if is_write:audit_scope_write(operation,params,current,'attempted')
        try:
            proc=subprocess.run(executable+['--runtime',str(runtime_path),'--operation',operation,'--params',json.dumps(params)],cwd=ROOT,text=True,capture_output=True,timeout=params.get('timeoutSeconds',90))
        except subprocess.TimeoutExpired as error:
            if is_write:
                audit_scope_write(operation,params,current,'uncertain_timeout',error)
                mark_mutation_uncertain(operation,params,current,error)
            raise RuntimeError('Browser mutation outcome is uncertain after helper timeout; automatic replay is blocked') from error
    result=child_result(proc);result['router']=tool
    if params.get('intent')=='write':
        if proc.returncode or not result.get('ok'):
            audit_scope_write(operation,params,current,'uncertain_error',result.get('error'))
            mark_mutation_uncertain(operation,params,current,result.get('error','browser helper failed after write attempt'))
        else:audit_scope_write(operation,params,current,'succeeded')
    if proc.returncode or not result.get('ok'):raise RuntimeError(result.get('error','browser tool failed'))
    return result
def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime',required=True);p.add_argument('--tool',choices=['auto','ego'],default='auto');p.add_argument('--operation',required=True);p.add_argument('--params',default='{}');a=p.parse_args()
    try:
        path=Path(a.runtime).resolve();runtime=load(path);params=json.loads(a.params);tool='ego'
        if a.operation not in EGO:raise RuntimeError('Operation is not supported by Ego in the canonical Steel runtime')
        result=run_direct(path,runtime,tool,a.operation,params)
        emit({'ok':True,'browserRuntimeId':runtime['browserRuntimeId'],**result})
    except Exception as e:emit({'ok':False,'error':f'{type(e).__name__}: {e}'});raise SystemExit(1)
if __name__=='__main__':main()
