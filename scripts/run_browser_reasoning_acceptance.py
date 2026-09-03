#!/usr/bin/env python3
"""Run capability-only Pi against a large synthetic Cvent-like page in real Steel/Ego."""
from __future__ import annotations
import http.server,json,os,re,subprocess,sys,tempfile,threading,time
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from browser_gate import BrowserGate
from browser_runtime import initialize
from runtime_config import slot_by_id

ROWS=''.join(f'<tr data-code="ROW-{i:04d}"><td>Discount {i} '+('bounded Cvent row evidence ' * 8)+f'</td><td>ROW-{i:04d}</td><td><button aria-label="Edit ROW-{i:04d}">Edit</button></td></tr>' for i in range(80))
HTML=f'''<!doctype html><html><head><title>Synthetic Cvent Capability Acceptance</title><style>body{{font:15px system-ui;min-height:5000px}} table{{border-collapse:collapse}}td{{padding:2px 8px}}#hover-action{{display:none}}#hover-zone:hover #hover-action{{display:block}}#drop{{margin-top:20px;padding:30px;border:2px dashed}}dialog{{padding:20px}}</style></head><body>
<h1>Synthetic Cvent Event A</h1><label>Venue Name <input id="venue" aria-label="Venue Name" value="Old Venue"></label>
<label>State <select id="state" aria-label="State"><option value="NY">New York</option><option value="FL">Florida</option></select></label>
<label><input id="browse" type="checkbox"> Browse Sessions visible</label><output id="browse-result">Browse unchecked</output>
<label>Discount search <input id="search" type="search" placeholder="Search discounts" aria-label="Discount search"></label><output id="search-result">No search yet</output>
<button id="open-modal" aria-label="Open settings">Open settings</button><output id="modal-result">Modal closed</output><dialog id="modal"><h2>Settings Modal</h2><button id="dynamic" aria-label="Dynamic modal control">Dynamic modal control</button><button id="close-modal">Close</button></dialog>
<div id="hover-zone" tabindex="0">Hover tools<button id="hover-action">Hover action revealed</button></div><output id="hover-result">Hover pending</output>
<div contenteditable="true" aria-label="Footer editor"><span id="rich-link">Browse Sessions</span><span> FAQ</span></div>
<button id="drag-source">Countdown Timer</button><div id="drop">Landing Page Drop Zone</div><output id="drag-result">Not dropped</output>
<div style="margin-top:1400px" id="long-page-tail">COMPLETE PAGE TAIL SENTINEL</div>
<table aria-label="Discount list"><thead><tr><th>Name</th><th>Code</th><th>Action</th></tr></thead><tbody>{ROWS}</tbody></table>
<script>
document.querySelector('#browse').onchange=()=>document.querySelector('#browse-result').textContent=document.querySelector('#browse').checked?'Browse checked':'Browse unchecked';
document.querySelector('#open-modal').onclick=()=>{{document.querySelector('#modal').showModal();document.querySelector('#modal-result').textContent='Modal opened'}};document.querySelector('#close-modal').onclick=()=>document.querySelector('#modal').close();
document.querySelector('#hover-zone').onmouseover=()=>document.querySelector('#hover-result').textContent='Hover revealed';
document.querySelector('#search').oninput=()=>{{const search=document.querySelector('#search');const q=search.value.toUpperCase();let found='';document.querySelectorAll('tbody tr').forEach(r=>{{const hit=!q||r.dataset.code.includes(q);r.hidden=!hit;if(hit&&q)found=r.dataset.code}});document.querySelector('#search-result').textContent=found?'Found '+found:'No matching discount'}};
const source=document.querySelector('#drag-source'),drop=document.querySelector('#drop');source.draggable=true;source.addEventListener('dragstart',e=>e.dataTransfer.setData('text/plain','Countdown Timer'));drop.addEventListener('dragover',e=>e.preventDefault());drop.addEventListener('drop',e=>{{e.preventDefault();document.querySelector('#drag-result').textContent='Dropped '+e.dataTransfer.getData('text/plain')}});drop.addEventListener('pointerup',()=>document.querySelector('#drag-result').textContent='Dropped Countdown Timer');
</script></body></html>'''

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/validate'):
            self.send_response(204);self.end_headers();return
        body=HTML.encode();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*args):pass

def steel(command,env,timeout=180,url=None):
    args=[sys.executable,str(ROOT/'steel_session.py'),command]
    if url:args+=['--url',url]
    run=subprocess.run(args,cwd=ROOT,env=env,text=True,capture_output=True,timeout=timeout)
    line=next((x for x in reversed(run.stdout.splitlines()) if x.startswith('STEEL_RESULT=')),None)
    result=json.loads(line.split('=',1)[1]) if line else {'running':False,'error':(run.stderr or run.stdout)[-1000:]}
    if run.returncode and command!='release':raise RuntimeError(result)
    return result

def parse_browser_result(text):
    line=next((x for x in reversed(text.splitlines()) if x.startswith('BROWSER_ROUTER_RESULT=')),None)
    return json.loads(line.split('=',1)[1]) if line else {}

def parse_session(sessions):
    file=next(sessions.glob('*.jsonl'));calls=[];results={};final=''
    for line in file.read_text(errors='replace').splitlines():
        try:item=json.loads(line)
        except json.JSONDecodeError:continue
        m=item.get('message',{});content=m.get('content',[]) if isinstance(m.get('content'),list) else []
        if m.get('role')=='assistant':
            for part in content:
                if part.get('type')=='toolCall':calls.append({'id':part.get('id'),'operation':part.get('arguments',{}).get('operation'),'name':part.get('name'),'at':m.get('timestamp'),'arguments':part.get('arguments',{})})
                elif part.get('type')=='text':final+=part.get('text','')
        elif m.get('role')=='toolResult':results[m.get('toolCallId')]={'at':m.get('timestamp'),'error':bool(m.get('isError'))}
    durations=[]
    for call in calls:
        result=results.get(call['id'])
        if result and call['at'] and result['at']:durations.append({'operation':call['operation'] or call['name'],'milliseconds':result['at']-call['at'],'error':result['error']})
    return calls,durations,final

def main():
    server=http.server.ThreadingHTTPServer(('0.0.0.0',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start();port=server.server_port
    base=Path(tempfile.mkdtemp(prefix='browser-reasoning-',dir=ROOT/'data'));job=base/'workspace-reasoning'/'job-reasoning';job.mkdir(parents=True);os.chmod(job,0o700)
    slot=slot_by_id(2);env=os.environ.copy();env.update({'CVENT_REPO_ROOT':str(ROOT),'CVENT_JOB_DIR':str(job),'CVENT_JOB_ID':'job-reasoning','CVENT_WORKSPACE_ID':'workspace-reasoning','CVENT_WORKER_SLOT':'2','CVENT_STEEL_API_ORIGIN':slot.api_origin,'CVENT_CDP_ORIGIN':slot.cdp_origin,'CVENT_VIEWER_URL':'/api/jobs/job-reasoning/viewer','CVENT_LEASE_VALIDATE_URL':f'http://127.0.0.1:{port}/validate','CVENT_LEASE_TOKEN':'synthetic-reasoning-lease','CVENT_AUTHORIZED_EVENT_ID':'event-a','CVENT_AUTHORIZED_EVENT_KEY':'event-a','CVENT_AUTHORIZED_EVENT_NAME':'Synthetic Cvent Event A','CVENT_AUTHORIZED_EVENT_CODE':'SYNA','CVENT_PYTHON':sys.executable,'PI_CODING_AGENT_DIR':str(job/'pi-config'),'PI_CODING_AGENT_SESSION_DIR':str(job/'pi-sessions'),'PI_SKIP_VERSION_CHECK':'1','PI_TELEMETRY':'0'})
    for secret in ('ENTRA_CLIENT_SECRET','CVENT_SESSION_SECRET','AZURE_CLIENT_SECRET','AZURE_CLIENT_CERTIFICATE_PATH','AZURE_FEDERATED_TOKEN_FILE'):env.pop(secret,None)
    try:
        steel('ensure',env);BrowserGate(job).initialize()
        runtime=initialize(job,2,'Synthetic Cvent Event A','event-a','event-a','/api/jobs/job-reasoning/viewer')
        steel('page',env,url=f'http://host.docker.internal:{port}/?evtstub=event-a')
        # Re-probe ensures the injected canonical marker survived navigation.
        from browser_runtime import local_probe
        local_probe(runtime)
        lock={'name':'Synthetic Cvent Event A','event_id':'event-a','url':f'http://host.docker.internal:{port}/?evtstub=event-a','event_key':'event-a','browser_runtime_id':runtime['browserRuntimeId'],'locked_at':datetime.now(timezone.utc).isoformat(),'mode':'synthetic','source':'acceptance'}
        (job/'authorized-target.json').write_text(json.dumps(lock,indent=2))
        direct_run=subprocess.run(['node',str(ROOT/'scripts/direct_browser_capability_harness.mjs')],cwd=job,env=env,text=True,capture_output=True,timeout=240)
        direct_line=next((line for line in reversed(direct_run.stdout.splitlines()) if line.startswith('DIRECT_CAPABILITY_EVIDENCE=')),None)
        direct=json.loads(direct_line.split('=',1)[1]) if direct_line else {'passed':False,'error':(direct_run.stderr or direct_run.stdout)[-1000:]}
        if '--direct-only' in sys.argv:
            evidence={'schemaVersion':1,'recordedAt':datetime.now(timezone.utc).isoformat(),'scope':'deterministic production capability extension in real isolated Steel/Ego against large synthetic Cvent-like DOM; no live Cvent navigation or mutation','runtime':{'slot':2,'runtimeId':runtime['browserRuntimeId'],'targetId':runtime['targetBrowserIdentity']['targetId']},'directCapabilityExecution':direct,'passed':direct.get('passed') is True}
            print(json.dumps(evidence,indent=2))
            if not evidence['passed']:raise SystemExit(1)
            return
        # Reload the complete large page so Pi must reason from an unfiltered, chunked observation.
        pi_url=f'http://host.docker.internal:{port}/?evtstub=event-a&phase=pi'
        steel('page',env,url=pi_url);lock['url']=pi_url;(job/'authorized-target.json').write_text(json.dumps(lock,indent=2))
        config=job/'pi-config';config.mkdir();(config/'auth.json').write_text('{}\n');(config/'settings.json').write_text(json.dumps({'defaultProvider':'anthropic','defaultModel':'claude-sonnet-4-6','defaultThinkingLevel':'low','defaultProjectTrust':'never','retry':{'enabled':True,'maxRetries':3,'baseDelayMs':2000,'provider':{'timeoutMs':3600000,'maxRetries':0,'maxRetryDelayMs':60000}}}))
        sessions=job/'pi-sessions';sessions.mkdir()
        prompt='''Execute one capability-only reasoning loop. The browser is already on the synthetic Cvent page; do not navigate. Call cvent_browser operation snapshotText with read intent. If chunked, read every cvent_snapshot_chunk exactly once in strict order. Confirm the COMPLETE PAGE TAIL SENTINEL and inspect the Venue Name value. Then call cvent_browser operation fill with write intent, scopeIds [scope-007], the observed Venue Name target, and text Pi Reasoned Venue. Call snapshotText again, consume all chunks, and report whether Pi Reasoned Venue persisted. Use no other tools and never call JavaScript or CDP.'''
        command=['pi','-p','--approve','--provider','anthropic','--model','claude-sonnet-4-6','--thinking','low','--no-extensions','--extension',str(ROOT/'extensions/cvent-job-tools.ts'),'--no-skills','--no-prompt-templates','--no-context-files','--no-builtin-tools','--tools','cvent_browser,cvent_snapshot_chunk','--session-dir',str(sessions),prompt]
        started=time.perf_counter();run=subprocess.run(command,cwd=job,env=env,text=True,capture_output=True,timeout=180);wall=time.perf_counter()-started
        # Final evidence read uses the same guarded browser router, not raw CDP/JS.
        read=subprocess.run([sys.executable,str(ROOT/'browser_tool.py'),'--runtime',str(job/'browser-runtime.json'),'--tool','ego','--operation','snapshotText','--params','{"intent":"read"}'],cwd=ROOT,env=env,text=True,capture_output=True,timeout=90)
        snapshot=parse_browser_result(read.stdout).get('snapshot','')
        calls,durations,final=parse_session(sessions)
        operations=[call['operation'] for call in calls if call['name']=='cvent_browser']
        chunks=[call for call in calls if call['name']=='cvent_snapshot_chunk']
        required={'snapshotText','fill'}
        state={'venue':'Pi Reasoned Venue' in snapshot,'tail':'COMPLETE PAGE TAIL SENTINEL' in snapshot}
        values=[item['milliseconds'] for item in durations if not item['error']]
        evidence={'schemaVersion':1,'recordedAt':datetime.now(timezone.utc).isoformat(),'scope':'real production capability extension and capability-only Pi reasoning loop in isolated Steel/Ego against large synthetic Cvent-like DOM; no live Cvent navigation or mutation','provider':'anthropic','model':'claude-sonnet-4-6','api':'anthropic-messages','returncode':run.returncode,'wallSeconds':round(wall,3),'runtime':{'slot':2,'runtimeId':runtime['browserRuntimeId'],'targetId':runtime['targetBrowserIdentity']['targetId'],'profilePath':str(job/'chromium-profile'),'sessionPath':str(sessions)},'directCapabilityExecution':direct,'operations':operations,'requiredOperationsCovered':sorted(required.intersection(operations)),'missingOperations':sorted(required-set(operations)),'snapshotChunkCalls':len(chunks),'toolDurations':durations,'toolLatencyMilliseconds':{'minimum':min(values) if values else None,'maximum':max(values) if values else None,'mean':round(sum(values)/len(values),3) if values else None},'finalState':state,'piFinal':final[-2000:],'stderrPresent':bool(run.stderr.strip())}
        evidence['passed']=direct.get('passed') is True and run.returncode==0 and required.issubset(operations) and len(chunks)>0 and all(state.values()) and any(item['operation']=='fill' and not item['error'] for item in durations)
        print(json.dumps(evidence,indent=2))
        if not evidence['passed']:raise SystemExit(1)
    finally:
        try:steel('release',env,60)
        except Exception:pass
        server.shutdown();server.server_close();import shutil;shutil.rmtree(base,ignore_errors=True)
if __name__=='__main__':main()
