#!/usr/bin/env python3
import json, os, subprocess, sys, time, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parent
PROFILE=ROOT/'data'/'chrome-profile'
PORT=int(os.getenv('CVENT_CDP_PORT','9333'))
CDP=f'http://127.0.0.1:{PORT}'
CHROME=Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')

def status():
    try:
        with urllib.request.urlopen(CDP+'/json/version',timeout=1) as r: return json.load(r)
    except Exception: return None

def launch(url='https://app.cvent.com/'):
    live=status()
    if live: return {"running":True,"started":False,"cdp":CDP,"browser":live.get('Browser')}
    PROFILE.mkdir(parents=True,exist_ok=True)
    log=open(ROOT/'data'/'chrome.log','ab',buffering=0)
    proc=subprocess.Popen([str(CHROME),f'--user-data-dir={PROFILE}',f'--remote-debugging-port={PORT}',
      '--remote-debugging-address=127.0.0.1','--remote-allow-origins=*','--no-first-run',
      '--no-default-browser-check','--new-window',url],stdout=log,stderr=log,start_new_session=True)
    for _ in range(60):
        time.sleep(.25); live=status()
        if live: return {"running":True,"started":True,"pid":proc.pid,"cdp":CDP,"browser":live.get('Browser')}
    return {"running":False,"pid":proc.pid,"error":"Chrome CDP did not become ready","cdp":CDP}

if __name__=='__main__': print(json.dumps(launch(sys.argv[1] if len(sys.argv)>1 else 'https://app.cvent.com/'),indent=2))
