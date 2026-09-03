"""Single cross-process browser action gate and explicit human ownership state."""
from __future__ import annotations
import fcntl, json, os
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent
CURRENT=ROOT/'data'/'current'; GATE=CURRENT/'browser-gate.json'; LOCK=CURRENT/'browser-gate.lock'
ACTORS={'CVENT_EGO','CVENT_BROWSER_USE','BROWSER_USE_AGENT','USER','NONE'}
def now():return datetime.now(timezone.utc).isoformat()
def read():
    try:
        data=json.loads(GATE.read_text())
        if 'piPaused' in data:data['agentPaused']=data.pop('piPaused')
        if data.get('activeActor')=='PI_EGO':data['activeActor']='CVENT_EGO'
        if data.get('activeActor')=='PI_BROWSER_USE':data['activeActor']='CVENT_BROWSER_USE'
        return data
    except Exception:return {'ownership':'AGENT','desiredOwnership':'AGENT','activeActor':'NONE','agentPaused':False,'updatedAt':now()}
def write(data):
    GATE.parent.mkdir(parents=True,exist_ok=True);data['updatedAt']=now();tmp=GATE.with_suffix('.tmp');tmp.write_text(json.dumps(data,indent=2));tmp.replace(GATE)
def initialize():
    data={'ownership':'AGENT','desiredOwnership':'AGENT','activeActor':'NONE','agentPaused':False,'transition':None,'updatedAt':now()};write(data);LOCK.touch();return data
def request_user():
    data=read();data.update({'desiredOwnership':'USER','transition':'WAITING_FOR_SAFE_BOUNDARY'});write(data);return data
def shield_agent():
    data=read();data.update({'desiredOwnership':'AGENT','transition':'VERIFYING_AFTER_USER'});write(data);return data
@contextmanager
def lock_file():
    LOCK.parent.mkdir(parents=True,exist_ok=True)
    with LOCK.open('a+') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        try:yield
        finally:fcntl.flock(handle,fcntl.LOCK_UN)
@contextmanager
def action(runtime_id,actor):
    if actor not in ACTORS or actor in ('USER','NONE'):raise RuntimeError('Invalid automation actor')
    with lock_file():
        data=read()
        if data.get('ownership')!='AGENT' or data.get('desiredOwnership')!='AGENT':raise RuntimeError('Browser is not agent-owned; action paused')
        if data.get('activeActor') not in (None,'NONE'):raise RuntimeError('Browser action gate is occupied')
        data.update({'activeActor':actor,'browserRuntimeId':runtime_id});write(data)
        try:yield
        finally:
            data=read();data['activeActor']='NONE';write(data)
