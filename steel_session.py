#!/opt/homebrew/opt/python@3.11/bin/python3.11
"""Lifecycle for one localhost-only, open-source Steel Browser container."""
from __future__ import annotations
import argparse, json, subprocess, sys, time, urllib.request
from pathlib import Path
from browser_runtime import command, pages, select_page

ROOT=Path(__file__).resolve().parent
API='http://127.0.0.1:3005'
CDP='http://127.0.0.1:9334'
VIEWER='http://127.0.0.1:8877/steel-viewer'
CONTAINER='cvent-one-shot-steel'
PROFILE=ROOT/'data'/'steel-profile-local'

def clear_stale_profile_locks():
    # Chromium leaves hostname-specific singleton symlinks when Docker is killed
    # or force-recreated. Removing them is safe only while Steel is stopped.
    if container_running(): return
    for name in ('SingletonLock','SingletonSocket','SingletonCookie'):
        try:(PROFILE/name).unlink()
        except FileNotFoundError:pass

def get_json(url,timeout=2):
    with urllib.request.urlopen(url,timeout=timeout) as r:return json.load(r)
def container_running():
    r=subprocess.run(['docker','inspect','-f','{{.State.Running}}',CONTAINER],text=True,capture_output=True)
    return r.returncode==0 and r.stdout.strip()=='true'
def status():
    running=container_running(); browser=None
    if running:
        try:browser=get_json(CDP+'/json/version').get('Browser')
        except Exception:running=False
    return {'provider':'steel-oss','running':running,'status':'live' if running else 'stopped','id':CONTAINER,
      'profile_id':'data/steel-profile-local','viewer_url':VIEWER,'api_url':API,'cdp_url':CDP,'browser':browser}
def ensure():
    if not container_running():
        clear_stale_profile_locks()
        r=subprocess.run(['docker','compose','up','-d','steel'],cwd=ROOT,text=True,capture_output=True,timeout=180)
        if r.returncode:raise RuntimeError((r.stderr or r.stdout)[-1500:])
    for _ in range(120):
        s=status()
        if s['running']:return s
        time.sleep(.5)
    raise RuntimeError('Open-source Steel CDP did not become ready')
def release():
    r=subprocess.run(['docker','compose','stop','steel'],cwd=ROOT,text=True,capture_output=True,timeout=60)
    if r.returncode==0:clear_stale_profile_locks()
    return {'released':r.returncode==0,'provider':'steel-oss','error':None if r.returncode==0 else (r.stderr or r.stdout)[-1000:]}
def cdp_url():
    ensure(); ws=get_json(CDP+'/json/version')['webSocketDebuggerUrl']
    return ws.replace('ws://127.0.0.1/','ws://127.0.0.1:9334/').replace('ws://localhost/','ws://127.0.0.1:9334/')
def auth_status(url,title):
    value=(url or '').lower(); host=value.split('/')[2] if '://' in value else ''
    name=(title or '').strip().lower()
    microsoft=any(x in host for x in ('login.microsoftonline.com','login.live.com','login.windows.net','account.activedirectory.windowsazure.com'))
    if microsoft:return 'microsoft_sso'
    if 'cvent.com' in host and ('login' in value or name in {'log in','sign in'}):return 'login_required'
    if 'cvent.com' in host:return 'authenticated'
    return 'unknown'
def page(url=None):
    ensure(); target=select_page(pages())
    if not target:raise RuntimeError('Steel has no page target')
    def live_state():
        reply=command(target['webSocketDebuggerUrl'],'Runtime.evaluate',{'expression':'({url:location.href,title:document.title,ready:document.readyState})','returnByValue':True})
        return reply.get('result',{}).get('value',{})
    current=live_state()
    if url and current.get('url')!=url:
        command(target['webSocketDebuggerUrl'],'Page.navigate',{'url':url})
        for _ in range(60):
            time.sleep(.25);current=live_state()
            if current.get('ready')=='complete' and current.get('url')!='about:blank':break
    auth=auth_status(current.get('url'),current.get('title'))
    return {**status(),'url':current.get('url'),'title':current.get('title'),'auth_status':auth,'login_required':auth!='authenticated'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['ensure','status','release','cdp','page']);p.add_argument('--url');a=p.parse_args()
    try:
        result=page(a.url) if a.command=='page' else {'ensure':ensure,'status':status,'release':release,'cdp':lambda:{'cdp_url':cdp_url()}}[a.command]()
        print('STEEL_RESULT='+json.dumps(result))
    except Exception as e:
        print('STEEL_RESULT='+json.dumps({'provider':'steel-oss','running':False,'error':f'{type(e).__name__}: {e}'}));sys.exit(1)
