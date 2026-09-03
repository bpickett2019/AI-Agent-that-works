#!/opt/homebrew/opt/python@3.11/bin/python3.11
"""Ego router pinned to the canonical Steel Chromium."""
from __future__ import annotations
import argparse,json,re,subprocess,sys
from pathlib import Path
from urllib.parse import parse_qs,urlparse
from browser_gate import action
from browser_runtime import load,local_probe
ROOT=Path(__file__).resolve().parent;CURRENT=ROOT/'data'/'current'
EGO={'probe','authorizeTarget','snapshotText','pageInfo','scanEventList','scroll','click','fill','type','navigate','js','cdp','wait','tabs','switchTab'}
INTENT_REQUIRED={'click','fill','type','js','cdp'}
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
def child_result(proc):
    marker='BROWSER_TOOL_RESULT=';index=proc.stdout.rfind(marker)
    if index>=0:
        try:return json.loads(proc.stdout[index+len(marker):].strip())
        except json.JSONDecodeError:pass
    return {'ok':False,'error':(proc.stderr or proc.stdout)[-1200:]}
def guard(runtime,operation,params):
    current=local_probe(runtime);lock=target_lock()
    locked=event_key(lock.get('url',''));current_key=event_key(current.get('url',''))
    valid_lock=lock.get('name')==runtime['authorizedEventName'] and bool(locked) and lock.get('event_key')==locked
    intent=params.get('intent')
    if operation in INTENT_REQUIRED and intent not in ('read','write'):
        raise RuntimeError(f'{operation} requires explicit read or write intent')
    if intent=='write' and (not valid_lock or current_key!=locked):
        raise RuntimeError('Write blocked: exact authorized event lock is absent or not currently open')
    if operation in ('navigate','browser_navigate'):
        url=params.get('url','');parsed=urlparse(url);host=(parsed.hostname or '').lower();key=event_key(url)
        if host and not (host=='cvent.com' or host.endswith('.cvent.com')):raise RuntimeError('Navigation outside Cvent is blocked')
        if re.search(r'/(account|organization|admin|global)(/|$)',parsed.path,re.I):raise RuntimeError('Navigation to account-global Cvent settings is blocked')
        if key and (not valid_lock or key!=locked):raise RuntimeError('Navigation to a non-authorized Cvent event blocked')
def run_direct(runtime_path,runtime,tool,operation,params):
    executable=['node','ego_direct.mjs']
    with action(runtime['browserRuntimeId'],'PI_EGO'):
        guard(runtime,operation,params)
        if operation=='authorizeTarget':
            probe=subprocess.run(['node','ego_direct.mjs','--runtime',str(runtime_path),'--operation','snapshotText','--params','{}'],cwd=ROOT,text=True,capture_output=True,timeout=90);observed=child_result(probe)
            info=local_probe(runtime);key=event_key(info.get('url',''))
            host=(urlparse(info.get('url','')).hostname or '').lower()
            if params.get('eventName')!=runtime['authorizedEventName'] or runtime['authorizedEventName'].lower() not in json.dumps(observed).lower() or not key or not host.endswith('cvent.com'):raise RuntimeError('Exact visible authorized event identity was not proven')
            lock={'name':runtime['authorizedEventName'],'url':info['url'],'event_key':key,'locked_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),'mode':'mock','source':'ego-direct'}
            target=CURRENT/'authorized-target.json';tmp=target.with_suffix('.tmp');tmp.write_text(json.dumps(lock,indent=2));tmp.replace(target)
            runtime['targetBrowserIdentity'].update({'url':info['url'],'title':info['title']});tmp=runtime_path.with_suffix('.tmp');tmp.write_text(json.dumps(runtime,indent=2));tmp.replace(runtime_path)
            return {'ok':True,'tool':'ego','operation':operation,'authorizedTarget':lock,'router':'ego'}
        proc=subprocess.run(executable+['--runtime',str(runtime_path),'--operation',operation,'--params',json.dumps(params)],cwd=ROOT,text=True,capture_output=True,timeout=params.get('timeoutSeconds',90))
    result=child_result(proc);result['router']=tool
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
