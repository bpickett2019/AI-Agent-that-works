#!/opt/homebrew/opt/python@3.11/bin/python3.11
"""Pi's simple browser router: Ego fast path, Browser Use direct, bounded fallback."""
from __future__ import annotations
import argparse,json,subprocess,sys
from pathlib import Path
from urllib.parse import parse_qs,urlparse
from browser_gate import action
from browser_runtime import load,local_probe
ROOT=Path(__file__).resolve().parent;CURRENT=ROOT/'data'/'current'
EGO={'probe','authorizeTarget','snapshotText','pageInfo','click','fill','type','navigate','openOrReuseTab','js','cdp','wait','tabs','switchTab'}
BU={'probe','browser_get_state','browser_navigate','browser_click','browser_type','browser_scroll','browser_extract_content','tabs','wait','send_keys'}
WRITES={'click','fill','type','browser_click','browser_type','send_keys'}
def event_key(url):
    try:
        q=parse_qs(urlparse(url).query)
        for k in ('evtstub','eventId','eventid','event'):
            if q.get(k):return q[k][0].lower()
    except Exception:pass
    return None
def target_lock():
    try:return json.loads((CURRENT/'authorized-target.json').read_text())
    except Exception:return {}
def emit(data):print('BROWSER_ROUTER_RESULT='+json.dumps(data,ensure_ascii=False))
def child_result(proc):
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith('BROWSER_TOOL_RESULT='):return json.loads(line.split('=',1)[1])
    return {'ok':False,'error':(proc.stderr or proc.stdout)[-1200:]}
def guard(runtime,operation,params):
    local_probe(runtime)
    if operation in WRITES and params.get('intent','write')!='read':
        lock=target_lock()
        if lock.get('name')!=runtime['authorizedEventName'] or event_key(lock.get('url',''))!=event_key(runtime['targetBrowserIdentity'].get('url','')):
            raise RuntimeError('Write blocked: exact authorized event lock is absent or not currently open')
    if operation in ('navigate','browser_navigate'):
        key=event_key(params.get('url',''));locked=event_key(target_lock().get('url',''))
        if key and key!=locked:raise RuntimeError('Navigation to a non-authorized Cvent event blocked')
def run_direct(runtime_path,runtime,tool,operation,params):
    executable=['node','ego_direct.mjs'] if tool=='ego' else ['./browser_use_direct.py']
    actor='CVENT_EGO' if tool=='ego' else 'CVENT_BROWSER_USE'
    with action(runtime['browserRuntimeId'],actor):
        guard(runtime,operation,params)
        if operation=='authorizeTarget':
            probe=subprocess.run(['node','ego_direct.mjs','--runtime',str(runtime_path),'--operation','snapshotText','--params','{}'],cwd=ROOT,text=True,capture_output=True,timeout=90);observed=child_result(probe)
            info=local_probe(runtime);key=event_key(info.get('url',''))
            if params.get('eventName')!=runtime['authorizedEventName'] or runtime['authorizedEventName'].lower() not in json.dumps(observed).lower() or not key:raise RuntimeError('Exact visible authorized event identity was not proven')
            lock={'name':runtime['authorizedEventName'],'url':info['url'],'event_key':key,'locked_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),'mode':'mock','source':'ego-direct'}
            target=CURRENT/'authorized-target.json';tmp=target.with_suffix('.tmp');tmp.write_text(json.dumps(lock,indent=2));tmp.replace(target)
            runtime['targetBrowserIdentity'].update({'url':info['url'],'title':info['title']});tmp=runtime_path.with_suffix('.tmp');tmp.write_text(json.dumps(runtime,indent=2));tmp.replace(runtime_path)
            return {'ok':True,'tool':'ego','operation':operation,'authorizedTarget':lock,'router':'ego'}
        proc=subprocess.run(executable+['--runtime',str(runtime_path),'--operation',operation,'--params',json.dumps(params)],cwd=ROOT,text=True,capture_output=True,timeout=params.get('timeoutSeconds',90))
    result=child_result(proc);result['router']=tool
    if proc.returncode or not result.get('ok'):raise RuntimeError(result.get('error','browser tool failed'))
    return result
def fallback(runtime_path,runtime,params):
    required=('eventId','eventName','resourceDomain','expectedState','allowedActions','prohibitedActions','successCriteria')
    missing=[x for x in required if not params.get(x)]
    if missing:raise RuntimeError('Fallback contract missing: '+', '.join(missing))
    lock=target_lock();target=lock.get('url','')
    if params['eventName']!=runtime['authorizedEventName'] or not target or params['eventId']!=event_key(target):raise RuntimeError('Fallback target does not match authorization lock')
    mission=f"""RESOURCE DOMAIN: {params['resourceDomain']}
EXPECTED STATE: {params['expectedState']}
ALLOWED ACTIONS: {params['allowedActions']}
PROHIBITED ACTIONS: {params['prohibitedActions']}
SUCCESS CRITERIA: {params['successCriteria']}
Return structured observations, actions, and verification. Pi will independently verify afterward."""
    proc=subprocess.run(['./browser_use_operator.py','--runtime',str(runtime_path),'--target',target,'--mission',mission,'--max-steps',str(params.get('maxSteps',20))],cwd=ROOT,text=True,capture_output=True,timeout=params.get('timeoutSeconds',900))
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith('CVENT_BROWSER_RESULT='):
            result=json.loads(line.split('=',1)[1]);return {'ok':proc.returncode==0,'tool':'browser-use-agent','requiresPiVerification':True,'result':result}
    raise RuntimeError((proc.stderr or proc.stdout)[-1200:])
def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime',required=True);p.add_argument('--tool',choices=['auto','ego','browser-use','fallback'],default='auto');p.add_argument('--operation',required=True);p.add_argument('--params',default='{}');a=p.parse_args()
    try:
        path=Path(a.runtime).resolve();runtime=load(path);params=json.loads(a.params)
        tool=a.tool
        if tool=='auto':tool='ego' if a.operation in EGO else ('browser-use' if a.operation in BU else 'fallback')
        if tool=='ego' and a.operation not in EGO:raise RuntimeError('Operation is not supported by Ego direct')
        if tool=='browser-use' and a.operation not in BU:raise RuntimeError('Operation is not supported by Browser Use direct')
        result=fallback(path,runtime,params) if tool=='fallback' else run_direct(path,runtime,tool,a.operation,params)
        emit({'ok':True,'browserRuntimeId':runtime['browserRuntimeId'],**result})
    except Exception as e:emit({'ok':False,'error':f'{type(e).__name__}: {e}'});raise SystemExit(1)
if __name__=='__main__':main()
