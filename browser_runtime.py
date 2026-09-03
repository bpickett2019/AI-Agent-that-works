#!/opt/homebrew/opt/python@3.11/bin/python3.11
"""Canonical identity for the one Steel Chromium used by every browser tool."""
from __future__ import annotations
import argparse, asyncio, json, os, subprocess, urllib.request, uuid
from datetime import datetime, timezone
from pathlib import Path
import websockets

ROOT=Path(__file__).resolve().parent
CURRENT=ROOT/'data'/'current'
RUNTIME=CURRENT/'browser-runtime.json'
CDP_HTTP='http://127.0.0.1:9334'
AUTHORIZED_NAME='(C+D) Medtrade Clone 2'

def now():return datetime.now(timezone.utc).isoformat()
def get_json(url):
    with urllib.request.urlopen(url,timeout=5) as r:return json.load(r)
def ws_local(url):
    return url.replace('ws://127.0.0.1/','ws://127.0.0.1:9334/').replace('ws://localhost/','ws://127.0.0.1:9334/')
def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,indent=2));tmp.replace(path)

async def page_command(ws_url,method,params=None):
    async with websockets.connect(ws_local(ws_url),origin='http://127.0.0.1:9334',open_timeout=10,max_size=16*1024*1024) as ws:
        await ws.send(json.dumps({'id':1,'method':method,'params':params or {}}))
        while True:
            reply=json.loads(await asyncio.wait_for(ws.recv(),10))
            if reply.get('id')==1:
                if reply.get('error'):raise RuntimeError(reply['error'].get('message','CDP error'))
                return reply.get('result',{})
def command(ws_url,method,params=None):return asyncio.run(page_command(ws_url,method,params))

def pages():return [x for x in get_json(CDP_HTTP+'/json/list') if x.get('type')=='page']
def select_page(items,preferred=None):
    if preferred:
        found=next((x for x in items if x.get('id')==preferred),None)
        if found:return found
    return next((x for x in items if 'cvent.com' in (x.get('url') or '')),items[-1] if items else None)
def evaluate(page,expression):
    result=command(page['webSocketDebuggerUrl'],'Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
    return result.get('result',{}).get('value')
def marker_script(marker):
    value=json.dumps(marker)
    return f"window.name={value};Object.defineProperty(window,'__CVENT_BROWSER_RUNTIME_ID',{{value:{value},configurable:false,writable:false}});"
def initialize():
    version=get_json(CDP_HTTP+'/json/version'); items=pages(); page=select_page(items)
    if not page:raise RuntimeError('Steel has no page target; refusing to create a second browser')
    marker='cvent-runtime-'+uuid.uuid4().hex
    script=marker_script(marker)
    command(page['webSocketDebuggerUrl'],'Page.addScriptToEvaluateOnNewDocument',{'source':script})
    evaluate(page,script+'window.__CVENT_BROWSER_RUNTIME_ID')
    browser_ws=ws_local(version['webSocketDebuggerUrl'])
    runtime={
      'browserRuntimeId':marker,'steelWorkspaceId':'cvent-one-shot','providerSessionId':'cvent-one-shot-steel',
      'apiOrigin':'http://127.0.0.1:3005','cdpEndpoint':browser_ws,'cdpHttpOrigin':CDP_HTTP,
      'viewerUrl':'http://127.0.0.1:8877/steel-viewer','authorizedEventName':AUTHORIZED_NAME,
      'targetBrowserIdentity':{'browser':version.get('Browser'),'browserWebSocketId':browser_ws.rsplit('/',1)[-1],
        'targetId':page['id'],'marker':marker,'url':page.get('url'),'title':page.get('title')},
      'createdAt':now(),'verifiedAt':None}
    atomic(RUNTIME,runtime);os.chmod(RUNTIME,0o600)
    return runtime

def load(path=RUNTIME):
    data=json.loads(Path(path).read_text())
    required=('browserRuntimeId','providerSessionId','cdpEndpoint','viewerUrl','targetBrowserIdentity')
    if any(not data.get(x) for x in required):raise RuntimeError('Invalid BrowserRuntime')
    return data

def local_probe(runtime):
    version=get_json(CDP_HTTP+'/json/version')
    if ws_local(version['webSocketDebuggerUrl'])!=runtime['cdpEndpoint']:raise RuntimeError('Steel browser identity changed')
    items=pages(); page=select_page(items,runtime['targetBrowserIdentity']['targetId'])
    if not page or page['id']!=runtime['targetBrowserIdentity']['targetId']:raise RuntimeError('Canonical target tab changed')
    marker=evaluate(page,"window.__CVENT_BROWSER_RUNTIME_ID || (window.name.startsWith('cvent-runtime-') ? window.name : null)")
    # Microsoft SSO may clear window.name at a cross-origin boundary. Rebind only
    # after the immutable browser WebSocket ID and target ID both match.
    if marker is None:
        evaluate(page,marker_script(runtime['browserRuntimeId'])+'window.__CVENT_BROWSER_RUNTIME_ID');marker=runtime['browserRuntimeId']
    if marker!=runtime['browserRuntimeId']:raise RuntimeError('Runtime marker mismatch')
    return {'marker':marker,'targetId':page['id'],'url':page.get('url'),'title':page.get('title')}
def tool_probe(runtime,script):
    p=subprocess.run(script,cwd=ROOT,text=True,capture_output=True,timeout=45)
    lines=p.stdout.splitlines()
    result=next((json.loads(x.split('=',1)[1]) for x in reversed(lines) if x.startswith('BROWSER_TOOL_RESULT=')),None)
    if p.returncode or not result:return {'ok':False,'error':(p.stderr or p.stdout)[-800:]}
    return result
def probe(path=RUNTIME,full=True):
    runtime=load(path); viewer=local_probe(runtime)
    result={'ok':True,'browserRuntimeId':runtime['browserRuntimeId'],'viewer':viewer}
    if full:
        ego=tool_probe(runtime,['node','ego_direct.mjs','--runtime',str(path),'--operation','probe','--params','{}'])
        bu=tool_probe(runtime,['./browser_use_direct.py','--runtime',str(path),'--operation','probe','--params','{}'])
        result.update({'ego':ego,'browserUse':bu})
        markers=[viewer.get('marker'),ego.get('marker'),bu.get('marker')]
        targets=[viewer.get('targetId'),ego.get('targetId'),bu.get('targetId')]
        result['sameBrowserVerified']=len(set(markers))==1 and markers[0]==runtime['browserRuntimeId'] and len(set(targets))==1
        if not result['sameBrowserVerified']:raise RuntimeError('Cross-browser identity probe failed closed')
    runtime['targetBrowserIdentity'].update({'url':viewer['url'],'title':viewer['title']});runtime['verifiedAt']=now();runtime['identityProbe']=result
    atomic(Path(path),runtime);os.chmod(path,0o600)
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['init','probe','status']);p.add_argument('--runtime',default=str(RUNTIME));a=p.parse_args()
    try:
        result=initialize() if a.command=='init' else (probe(Path(a.runtime)) if a.command=='probe' else load(Path(a.runtime)))
        print('BROWSER_RUNTIME_RESULT='+json.dumps(result,ensure_ascii=False))
    except Exception as e:
        print('BROWSER_RUNTIME_RESULT='+json.dumps({'ok':False,'error':f'{type(e).__name__}: {e}'}));raise SystemExit(1)
if __name__=='__main__':main()
