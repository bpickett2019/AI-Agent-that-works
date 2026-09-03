#!/usr/bin/env python3
"""Three-way harmless Anthropic/Pi concurrency and one-worker failure isolation."""
from __future__ import annotations
import concurrent.futures, json, os, subprocess, tempfile, time
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def parse_session(directory:Path):
    files=list((directory/'sessions').glob('*.jsonl'))
    messages=[]
    if files:
        for line in files[0].read_text(errors='replace').splitlines():
            try:item=json.loads(line)
            except json.JSONDecodeError:continue
            message=item.get('message',{})
            if message.get('role')=='assistant':messages.append(message)
    usage={'input':0,'output':0,'cacheRead':0,'cacheWrite':0,'totalTokens':0}
    apis=set();models=set();providers=set()
    for message in messages:
        providers.add(message.get('provider'));models.add(message.get('model'));apis.add(message.get('api'))
        for key in usage:usage[key]+=int((message.get('usage') or {}).get(key,0) or 0)
    return {'requests':len(messages),'usage':usage,'providers':sorted(x for x in providers if x),'models':sorted(x for x in models if x),'apis':sorted(x for x in apis if x)}

def invoke(base:Path,name:str,valid_key:bool=True):
    directory=base/name;config=directory/'config';sessions=directory/'sessions'
    config.mkdir(parents=True);sessions.mkdir();(config/'auth.json').write_text('{}\n')
    (config/'settings.json').write_text(json.dumps({'defaultProvider':'anthropic','defaultModel':'claude-sonnet-4-6','defaultThinkingLevel':'off','defaultProjectTrust':'never','retry':{'enabled':True,'maxRetries':3,'baseDelayMs':2000,'provider':{'timeoutMs':3600000,'maxRetries':0,'maxRetryDelayMs':60000}}}))
    env=os.environ.copy();env.update({'PI_CODING_AGENT_DIR':str(config),'PI_CODING_AGENT_SESSION_DIR':str(sessions),'PI_SKIP_VERSION_CHECK':'1','PI_TELEMETRY':'0'})
    if not valid_key:env['ANTHROPIC_API_KEY']='intentionally-invalid-isolation-probe'
    marker=f'{name}_OK'
    command=['pi','-p','--approve','--provider','anthropic','--model','claude-sonnet-4-6','--thinking','off','--no-tools','--session-dir',str(sessions),f'Respond with exactly {marker} and nothing else.']
    started=time.perf_counter();run=subprocess.run(command,cwd=directory,env=env,text=True,capture_output=True,timeout=90);seconds=time.perf_counter()-started
    combined=(run.stdout+'\n'+run.stderr)
    session=parse_session(directory)
    return {'worker':name,'returncode':run.returncode,'success':run.returncode==0 and marker in run.stdout,'latencySeconds':round(seconds,3),'429Count':combined.lower().count('429')+combined.lower().count('rate limit'),'retryNotices':combined.lower().count('retry'),'stderrPresent':bool(run.stderr.strip()),**session}

def phase(base:Path,names,validity):
    started=time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(names)) as pool:
        futures=[pool.submit(invoke,base,name,validity[name]) for name in names]
        results=[future.result() for future in futures]
    return {'wallSeconds':round(time.perf_counter()-started,3),'workers':results}

def main():
    if not os.environ.get('ANTHROPIC_API_KEY'):raise SystemExit('ANTHROPIC_API_KEY is absent; no test run')
    with tempfile.TemporaryDirectory(prefix='anthropic-concurrency-',dir=ROOT/'data') as temp:
        base=Path(temp)
        healthy=phase(base/'healthy',['A','B','C'],{'A':True,'B':True,'C':True})
        isolated=phase(base/'failure-isolation',['A','B','C'],{'A':True,'B':False,'C':True})
        evidence={'schemaVersion':1,'recordedAt':datetime.now(timezone.utc).isoformat(),'scope':'harmless bounded Pi prompts; no tools, browser, or Cvent access','provider':'anthropic','model':'claude-sonnet-4-6','healthyConcurrency':healthy,'providerFailureIsolation':isolated}
        good_apis=all(w['providers']==['anthropic'] and w['models']==['claude-sonnet-4-6'] and w['apis']==['anthropic-messages'] for w in healthy['workers'])
        healthy_ok=all(w['success'] for w in healthy['workers'])
        failed={w['worker']:w for w in isolated['workers']}
        isolated_ok=failed['A']['success'] and not failed['B']['success'] and failed['C']['success']
        evidence['summary']={'healthyRequests':sum(w['requests'] for w in healthy['workers']),'429Count':sum(w['429Count'] for w in healthy['workers']),'failures':sum(not w['success'] for w in healthy['workers']),'apiVerified':good_apis,'workerBFailureDidNotBlockAOrC':isolated_ok,'browserMutationReplayPossibleInProbe':False,'reason':'All probe sessions ran with --no-tools; browser writes additionally record attempted/uncertain timeout and block replay.'}
        evidence['passed']=healthy_ok and good_apis and isolated_ok
        print(json.dumps(evidence,indent=2))
        if not evidence['passed']:raise SystemExit(1)
if __name__=='__main__':main()
