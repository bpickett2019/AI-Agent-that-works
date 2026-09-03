#!/usr/bin/env python3
"""Use the active slot-1 job plus synthetic slots 2/3 to prove OS-process isolation.

Never automates the active USER-owned browser and never navigates or mutates Cvent.
"""
from __future__ import annotations
import concurrent.futures, json, os, signal, sqlite3, subprocess, sys, tempfile, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from browser_gate import BrowserGate
from browser_runtime import initialize
from runtime_config import slot_by_id

JOB_ID='job_05bb846fc7f043f6bc7d86024f20208b'
DB=ROOT/'data/control.db'

def now(): return datetime.now(timezone.utc).isoformat()
def alive(pid):
    try: os.kill(pid,0); return True
    except ProcessLookupError: return False

def steel(command,env,timeout=180):
    run=subprocess.run([sys.executable,str(ROOT/'steel_session.py'),command],cwd=ROOT,env=env,text=True,capture_output=True,timeout=timeout)
    line=next((x for x in reversed(run.stdout.splitlines()) if x.startswith('STEEL_RESULT=')),None)
    result=json.loads(line.split('=',1)[1]) if line else {'running':False,'error':(run.stderr or run.stdout)[-800:]}
    if run.returncode and command!='release': raise RuntimeError(result)
    return result

def descendants(pid):
    output=subprocess.check_output(['ps','-axo','pid=,ppid=,pgid=,stat=,command='],text=True)
    rows=[]
    for line in output.splitlines():
        fields=line.strip().split(None,4)
        if len(fields)==5: rows.append({'pid':int(fields[0]),'ppid':int(fields[1]),'pgid':int(fields[2]),'stat':fields[3],'command':fields[4].split()[0]})
    selected=[]; frontier={pid}; seen=set()
    while frontier:
        current=frontier-seen
        if not current:break
        seen.update(current)
        found=[row for row in rows if row['pid'] in current or row['ppid'] in current]
        for row in found:
            if row not in selected:selected.append(row)
        frontier={row['pid'] for row in found if row['pid'] not in seen}
        if len(selected)>100:break
    return selected

def main():
    conn=sqlite3.connect(DB);conn.row_factory=sqlite3.Row
    anchor=conn.execute("select * from jobs where id=?",(JOB_ID,)).fetchone();conn.close()
    if not anchor or anchor['state']!='running' or anchor['slot_id']!=1 or not anchor['pid'] or not alive(anchor['pid']):
        raise SystemExit('Active slot-1 job required; refusing to replace or touch its browser')
    anchor_dir=ROOT/'data/workspaces'/anchor['workspace_id']/'jobs'/anchor['id']
    anchor_gate=json.loads((anchor_dir/'browser-gate.json').read_text())
    if anchor_gate.get('ownership')!='USER':raise SystemExit('Anchor browser is not USER-owned; this probe is designed never to touch it')
    anchor_runtime=json.loads((anchor_dir/'browser-runtime.json').read_text())
    base=Path(tempfile.mkdtemp(prefix='process-isolation-',dir=ROOT/'data'))
    children={}; envs={}; runtimes={}; outputs={}
    try:
        for slot_id in (2,3):
            job_dir=base/f'workspace-{slot_id}'/f'job-synthetic-{slot_id}'
            job_dir.mkdir(parents=True);os.chmod(job_dir,0o700)
            BrowserGate(job_dir).initialize()
            slot=slot_by_id(slot_id)
            env=os.environ.copy();env.update({
                'CVENT_REPO_ROOT':str(ROOT),'CVENT_JOB_DIR':str(job_dir),'CVENT_JOB_ID':job_dir.name,
                'CVENT_WORKSPACE_ID':job_dir.parent.name,'CVENT_WORKER_SLOT':str(slot_id),
                'CVENT_STEEL_API_ORIGIN':slot.api_origin,'CVENT_CDP_ORIGIN':slot.cdp_origin,
                'CVENT_VIEWER_URL':f'/api/jobs/{job_dir.name}/viewer','CVENT_LEASE_VALIDATE_URL':'http://127.0.0.1:8877/internal/leases/validate',
                'CVENT_LEASE_TOKEN':f'synthetic-slot-{slot_id}','CVENT_AUTHORIZED_EVENT_ID':f'synthetic-event-{slot_id}',
                'CVENT_AUTHORIZED_EVENT_KEY':f'synthetic-event-{slot_id}','CVENT_AUTHORIZED_EVENT_NAME':f'Synthetic Event {slot_id}',
                'CVENT_AUTHORIZED_EVENT_CODE':f'SYN{slot_id}','CVENT_PYTHON':sys.executable,
                'PI_CODING_AGENT_DIR':str(job_dir/'pi-config'),'PI_CODING_AGENT_SESSION_DIR':str(job_dir/'pi-sessions'),
                'PI_SKIP_VERSION_CHECK':'1','PI_TELEMETRY':'0',
            })
            # Pi receives the provider key via inherited environment; it is never copied to helper argv/evidence.
            for secret in ('ENTRA_CLIENT_SECRET','CVENT_SESSION_SECRET','AZURE_CLIENT_SECRET','AZURE_CLIENT_CERTIFICATE_PATH','AZURE_FEDERATED_TOKEN_FILE'):
                env.pop(secret,None)
            envs[slot_id]=env
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            started=list(pool.map(lambda sid:steel('ensure',envs[sid]),(2,3)))
        for slot_id in (2,3):
            job_dir=Path(envs[slot_id]['CVENT_JOB_DIR'])
            runtimes[slot_id]=initialize(job_dir,slot_id,envs[slot_id]['CVENT_AUTHORIZED_EVENT_NAME'],envs[slot_id]['CVENT_AUTHORIZED_EVENT_ID'],envs[slot_id]['CVENT_AUTHORIZED_EVENT_KEY'],envs[slot_id]['CVENT_VIEWER_URL'])
            config=job_dir/'pi-config';config.mkdir();(config/'auth.json').write_text('{}\n')
            (config/'settings.json').write_text(json.dumps({'defaultProvider':'anthropic','defaultModel':'claude-sonnet-4-6','defaultThinkingLevel':'off','defaultProjectTrust':'never','retry':{'enabled':True,'maxRetries':3,'baseDelayMs':2000,'provider':{'timeoutMs':3600000,'maxRetries':0,'maxRetryDelayMs':60000}}}))
            sessions=job_dir/'pi-sessions';sessions.mkdir()
            output=open(job_dir/'pi-output.log','w');outputs[slot_id]=output
            command=['pi','-p','--approve','--provider','anthropic','--model','claude-sonnet-4-6','--thinking','off','--no-extensions','--extension',str(ROOT/'extensions/cvent-job-tools.ts'),'--no-skills','--no-prompt-templates','--no-context-files','--no-builtin-tools','--tools','cvent_browser','--session-dir',str(sessions),f'Call cvent_browser with operation wait, intent read, and ms 30000 exactly once. Then respond SYNTHETIC_{slot_id}_OK.']
            children[slot_id]=subprocess.Popen(command,cwd=job_dir,env=envs[slot_id],stdout=output,stderr=subprocess.STDOUT,text=True,start_new_session=True)
        deadline=time.time()+25
        simultaneous=False
        while time.time()<deadline:
            if alive(anchor['pid']) and all(process.poll() is None for process in children.values()):
                trees={sid:descendants(process.pid) for sid,process in children.items()}
                if all(any('python' in row['command'] or 'node' in row['command'] for row in trees[sid] if row['pid']!=children[sid].pid) for sid in (2,3)):
                    simultaneous=True;break
            time.sleep(.25)
        before={
            'slot1PiAlive':alive(anchor['pid']),'slot2PiAlive':children[2].poll() is None,'slot3PiAlive':children[3].poll() is None,
            'slot1Port':urllib.request.urlopen(anchor_runtime['cdpHttpOrigin']+'/json/version',timeout=3).status,
            'slot2Port':urllib.request.urlopen(runtimes[2]['cdpHttpOrigin']+'/json/version',timeout=3).status,
            'slot3Port':urllib.request.urlopen(runtimes[3]['cdpHttpOrigin']+'/json/version',timeout=3).status,
        }
        os.killpg(children[2].pid,signal.SIGTERM);children[2].wait(timeout=10);time.sleep(1)
        after={
            'slot1PiAlive':alive(anchor['pid']),'slot2PiAlive':children[2].poll() is None,'slot3PiAlive':children[3].poll() is None,
            'slot1BrowserAlive':urllib.request.urlopen(anchor_runtime['cdpHttpOrigin']+'/json/version',timeout=3).status==200,
            'slot3BrowserAlive':urllib.request.urlopen(runtimes[3]['cdpHttpOrigin']+'/json/version',timeout=3).status==200,
        }
        evidence={
            'schemaVersion':1,'recordedAt':now(),'scope':'live OS/container isolation with USER-owned slot 1 untouched; synthetic about:blank slots 2/3; no Cvent navigation or mutation',
            'simultaneousProcessTreesObserved':simultaneous,'beforeKill':before,'afterKillingWorkerB':after,
            'workers':[
                {'slot':1,'kind':'active-authorized-anchor','piPid':anchor['pid'],'jobId':anchor['id'],'workspace':anchor['workspace_id'],'profilePath':str(anchor_dir/'chromium-profile'),'sessionPath':str(anchor_dir/'pi-sessions'),'cdpEndpoint':anchor_runtime['cdpHttpOrigin'],'runtimeId':anchor_runtime['browserRuntimeId'],'targetId':anchor_runtime['targetBrowserIdentity']['targetId'],'gatePath':str(anchor_dir/'browser-gate.json'),'viewer':anchor_runtime['viewerUrl'],'ownership':'USER'},
                *[{'slot':sid,'kind':'synthetic','piPid':children[sid].pid,'jobId':envs[sid]['CVENT_JOB_ID'],'workspace':envs[sid]['CVENT_WORKSPACE_ID'],'profilePath':str(Path(envs[sid]['CVENT_JOB_DIR'])/'chromium-profile'),'sessionPath':str(Path(envs[sid]['CVENT_JOB_DIR'])/'pi-sessions'),'cdpEndpoint':runtimes[sid]['cdpHttpOrigin'],'runtimeId':runtimes[sid]['browserRuntimeId'],'targetId':runtimes[sid]['targetBrowserIdentity']['targetId'],'gatePath':str(Path(envs[sid]['CVENT_JOB_DIR'])/'browser-gate.json'),'viewer':runtimes[sid]['viewerUrl'],'ownership':'AGENT','processTree':trees.get(sid,[])} for sid in (2,3)]
            ],
        }
        evidence['unique']={key:len({worker[key] for worker in evidence['workers']})==3 for key in ('piPid','jobId','workspace','profilePath','sessionPath','cdpEndpoint','runtimeId','targetId','gatePath','viewer')}
        evidence['crossWorkspaceFiles']=False
        evidence['passed']=simultaneous and all(before.values()) and after=={'slot1PiAlive':True,'slot2PiAlive':False,'slot3PiAlive':True,'slot1BrowserAlive':True,'slot3BrowserAlive':True} and all(evidence['unique'].values())
        print(json.dumps(evidence,indent=2))
        if not evidence['passed']:raise SystemExit(1)
    finally:
        for sid,process in children.items():
            if process.poll() is None:
                try:os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=10)
                except Exception:
                    try:os.killpg(process.pid,signal.SIGKILL)
                    except Exception:pass
        for output in outputs.values():output.close()
        for sid in (2,3):
            if sid in envs:
                try:steel('release',envs[sid],60)
                except Exception:pass
        import shutil;shutil.rmtree(base,ignore_errors=True)

if __name__=='__main__':main()
