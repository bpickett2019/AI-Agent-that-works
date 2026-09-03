#!/opt/homebrew/opt/python@3.11/bin/python3.11
"""One Browser Use operator connected only to the app's persistent Chrome."""
from __future__ import annotations
import argparse, asyncio, json, os, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from browser_gate import action
from browser_runtime import load as load_runtime, local_probe

ROOT=Path(__file__).resolve().parent
CURRENT=ROOT/'data'/'current'
DANGEROUS=re.compile(r'(^|\b)(publish|go live|send( now)?|send invitation|delete|archive|launch event)(\b|$)',re.I)
DISCOVERY_MUTATION=re.compile(r'(^|\b)(save|edit|create|add|new event|copy|duplicate|enable|disable)(\b|$)',re.I)
SEARCH_CONTROL=re.compile(r'(search|find|filter|event name|event code)',re.I)
GLOBAL=re.compile(r'/(account|organization|admin|global)(/|\?|$)',re.I)
AUTH_HOSTS=('login.microsoftonline.com','login.live.com','login.windows.net','microsoft.com','okta.com','auth0.com')
AUTHORIZED_EVENT_NAME='(C+D) Medtrade Clone 2'
AUTHORIZED_TARGET=CURRENT/'authorized-target.json'

def now(): return datetime.now(timezone.utc).isoformat()
def append_log(msg):
    CURRENT.mkdir(parents=True,exist_ok=True)
    with (CURRENT/'activity.log').open('a') as f: f.write(f'{now()}  {msg}\n')
def patch_state(**changes):
    p=CURRENT/'state.json'
    try: state=json.loads(p.read_text())
    except Exception: state={}
    state.update(changes); state['updated_at']=now()
    tmp=p.with_suffix('.tmp'); tmp.write_text(json.dumps(state,indent=2)); tmp.replace(p)
def event_key(url):
    try:
        u=urlparse(url); q=parse_qs(u.query)
        for k in ('evtstub','eventId','eventid','event'):
            if q.get(k): return q[k][0].lower()
        m=re.search(r'/events/([0-9a-f-]{20,})',u.path,re.I)
        return m.group(1).lower() if m else None
    except Exception: return None
def login_page(url,title,text=''):
    host=urlparse(url).hostname or ''
    hay=f'{title} {text}'.lower()
    path=urlparse(url).path.lower()
    return ('login' in path and host.endswith('cvent.com')) or title.strip().lower() in ('log in','sign in') or any(host==h or host.endswith('.'+h) for h in AUTH_HOSTS) or any(x in hay for x in ('sign in to your account','enter password','verify your identity','approve sign in request','multi-factor authentication'))
def action_data(action):
    d=action.model_dump(exclude_none=True,exclude_unset=True)
    return next(iter(d.items())) if d else ('',{})
def node_text(node):
    try: return ' '.join([node.get_meaningful_text_for_llm(),*node.attributes.values()])
    except Exception: return ''

async def run(args):
    from browser_use import Agent, Browser, ChatAnthropic, Tools
    started=time.monotonic()
    discovery=bool(args.discover)
    fast_mode=os.getenv('BROWSER_USE_FAST','1').lower() not in ('0','false','no')
    model=os.getenv('BROWSER_USE_MODEL', 'claude-haiku-4-5' if fast_mode else 'claude-sonnet-4-5')
    append_log(f'Browser Use started — {"FAST" if fast_mode else "BALANCED"} mode')
    landing='https://app.cvent.com/' if discovery else args.target
    target_key=event_key(args.target or '')
    violation=[]; actions=[]; pages=[]
    if not discovery:
        try: lock=json.loads(AUTHORIZED_TARGET.read_text())
        except Exception: return {'status':'BLOCKED','message':'No authorized mock target lock exists; run exact-name discovery first','chrome_alive':True}
        locked_key=event_key(lock.get('url',''))
        if lock.get('name')!=AUTHORIZED_EVENT_NAME or not target_key or target_key!=locked_key:
            append_log('BLOCKED: requested target does not match the authorized Medtrade Clone 2 lock')
            return {'status':'BLOCKED','message':f'Only {AUTHORIZED_EVENT_NAME} is authorized','chrome_alive':True}
    resolved_cdp=load_runtime(Path(args.runtime))['cdpEndpoint']
    browser=Browser(cdp_url=resolved_cdp,is_local=False,keep_alive=True)
    await browser.start()
    try:
        await browser.navigate_to(landing)
        await asyncio.sleep(1.25)
        initial=await browser.get_browser_state_summary(include_screenshot=False)
        text=initial.dom_state.llm_representation()[:5000]
        if login_page(initial.url,initial.title,text):
            append_log('MFA REQUIRED — manual login needed in persistent Chrome')
            patch_state(status='login_required',current_stage='login',current_action='MFA REQUIRED — log in once, then press CONTINUE')
            return {'status':'LOGIN_REQUIRED','message':'MFA REQUIRED','url':initial.url,'title':initial.title,'chrome_alive':True}

        async def on_step(state,output,step):
            pages.append({'step':step,'url':state.url,'title':state.title})
            current_key=event_key(state.url)
            host=urlparse(state.url).hostname or ''
            if host.endswith('cvent.com') and current_key and target_key and current_key != target_key:
                violation.append(f'Blocked another event at {state.url}')
                return
            if host.endswith('cvent.com') and GLOBAL.search(urlparse(state.url).path):
                violation.append(f'Blocked account-global page at {state.url}')
                return
            for action in output.action or []:
                name,params=action_data(action); actions.append(name)
                if name=='navigate':
                    url=(params or {}).get('url','') if isinstance(params,dict) else ''
                    new_host=urlparse(url).hostname or ''
                    new_key=event_key(url)
                    allowed=new_host.endswith('cvent.com') or any(new_host==h or new_host.endswith('.'+h) for h in AUTH_HOSTS)
                    if not allowed or (new_key and target_key and new_key != target_key) or GLOBAL.search(urlparse(url).path):
                        violation.append(f'Blocked navigation outside authorized event: {url}')
                        return
                if name in ('click','input','select_dropdown') and isinstance(params,dict):
                    idx=params.get('index'); node=state.dom_state.selector_map.get(idx) if idx is not None else None
                    label=node_text(node) if node else ''
                    if DANGEROUS.search(label):
                        violation.append(f'Blocked prohibited control: {label[:160]}')
                        return
                    if discovery and name=='click' and DISCOVERY_MUTATION.search(label):
                        violation.append(f'Discovery is read-only; blocked control: {label[:160]}')
                        return
                    if discovery and name in ('input','select_dropdown') and not SEARCH_CONTROL.search(label):
                        violation.append(f'Discovery input is limited to event search/filter controls: {label[:160]}')
                        return

        async def should_stop(): return bool(violation)
        if discovery:
            prompt=f"""You are Browser Use in STRICT READ-ONLY Cvent target-discovery mode.
ONLY AUTHORIZED EVENT NAME: {AUTHORIZED_EVENT_NAME}
MISSION FROM PI: {args.mission}

This is a mock run. Ignore every event name, code, date, and location from the uploaded RR when selecting a target. From the Cvent event list, search only for the exact literal name `{AUTHORIZED_EVENT_NAME}`. Do not assume a fuzzy result is correct. There must be exactly one exact-name matching event. You may use event-list search/filter controls and open that one event's Overview/Details page solely to verify visible identity. Make NO edits and click no Save/Create/Add/Edit control. If zero, multiple, or uncertain matches exist, return REVIEW REQUIRED without opening an arbitrary event. If login/MFA appears, enter no credentials and return exactly MFA REQUIRED. If one exact match is verified, leave the browser on that event and return its visible event name, code/ID, dates, and URL. Do not close Chrome.
Do not open any event with a different visible name. NEVER publish/go live, send/test/schedule communications, delete, archive, create, edit, save, access attendee/contact data, or alter any configuration."""
        else:
            prompt=f"""You are Browser Use, the computer operator for one authorized Cvent draft event.
ONLY AUTHORIZED EVENT NAME: {AUTHORIZED_EVENT_NAME}
AUTHORIZED TARGET URL: {args.target}
AUTHORIZED EVENT KEY: {target_key or 'MISSING — DO NOT OPERATE'}
MISSION FROM PI: {args.mission}

This is a mock run using RR requirements as test data. First confirm the visible event name is exactly `{AUTHORIZED_EVENT_NAME}` and the event belongs to the exact locked target URL. If the name differs by even one character, stop with BLOCKED. Preserve the event name, event code/ID, URL identity, and unpublished state. Never navigate to the real event described by the RR. Operate dynamically and safely. Inspect current state before every mutation; if already correct, do nothing. Never blindly duplicate. Make only the minimum unambiguous draft edits. Save after meaningful writes, wait for Cvent to stabilize (it may redirect Edit to View), then re-read to verify persistence. If login or MFA appears, do not enter credentials: finish with exactly MFA REQUIRED. If uncertain or conflicting, report REVIEW REQUIRED and do not make that ambiguous change; continue independent safe work when the mission permits.
NEVER publish/go live, send/test/schedule email or invitations, delete, archive, mutate another event, open attendee/contact data, or alter reusable/account-global fields. Event-local questions are allowed; global/profile/reusable field mutation is forbidden. Names such as NAICS36D and AGES may collide: compare semantics, never overwrite a global field. Do not close Chrome. Return a concise factual result with observed identity, reads, writes, and verification."""
        tools=Tools(exclude_actions=['evaluate','close','search','read_file','write_file','replace_file','upload_file'])
        agent=Agent(task=prompt,llm=ChatAnthropic(model=model),
          browser=browser,tools=tools,register_new_step_callback=on_step,
          register_should_stop_callback=should_stop,use_vision='auto',vision_detail_level='low',max_failures=2,
          max_actions_per_step=8,use_thinking=not fast_mode,flash_mode=fast_mode,max_history_items=8,
          llm_timeout=45 if fast_mode else 90,step_timeout=75 if fast_mode else 120,
          generate_gif=False,calculate_cost=False,directly_open_url=False,initial_actions=[])
        history=await agent.run(max_steps=args.max_steps)
        final=history.final_result() or ''
        try:
            state=await browser.get_browser_state_summary(include_screenshot=False)
            final_url, final_title = state.url, state.title
        except Exception:
            # Persistent Steel can briefly drop the CDP websocket after the agent's
            # successful final action. Preserve the last callback-observed page
            # instead of discarding a completed, verified mission.
            last=pages[-1] if pages else {'url':landing,'title':''}
            final_url, final_title = last['url'], last['title']
        identity_text=f'{final_title} {final}'
        exact_name_seen=AUTHORIZED_EVENT_NAME.lower() in identity_text.lower()
        discovered_url=final_url if discovery and event_key(final_url) and exact_name_seen else None
        if violation: status='BLOCKED'
        elif login_page(final_url,final_title,final) or 'MFA REQUIRED' in final.upper(): status='LOGIN_REQUIRED'
        elif discovery: status='DISCOVERED' if discovered_url and 'REVIEW REQUIRED' not in final.upper() else 'REVIEW_REQUIRED'
        else: status='FAILED' if history.has_errors() else 'COMPLETE'
        if status=='LOGIN_REQUIRED':
            append_log('MFA REQUIRED — manual login needed in persistent Chrome')
            patch_state(status='login_required',current_stage='login',current_action='MFA REQUIRED — log in once, then press CONTINUE')
        elif violation: append_log(violation[0])
        if status=='DISCOVERED':
            lock={'name':AUTHORIZED_EVENT_NAME,'url':discovered_url,'event_key':event_key(discovered_url),'locked_at':now(),'mode':'mock'}
            tmp=AUTHORIZED_TARGET.with_suffix('.tmp'); tmp.write_text(json.dumps(lock,indent=2)); tmp.replace(AUTHORIZED_TARGET)
            runtime_path=Path(args.runtime); runtime=json.loads(runtime_path.read_text()); runtime['targetBrowserIdentity'].update({'url':discovered_url,'title':final_title}); runtime_tmp=runtime_path.with_suffix('.tmp'); runtime_tmp.write_text(json.dumps(runtime,indent=2)); runtime_tmp.replace(runtime_path)
            append_log(f'Authorized mock target locked: {AUTHORIZED_EVENT_NAME}')
        duration=round(time.monotonic()-started,1)
        append_log(f'Browser Use finished — {status} in {duration}s')
        return {'status':status,'final':final,'url':final_url,'title':final_title,'discovered_target_url':discovered_url,'observed_identity':(final_title+' — '+final)[:2500] if discovery else None,'violations':violation,'actions':actions,'pages':pages,'performance':{'mode':'fast' if fast_mode else 'balanced','model':model,'seconds':duration,'steps':len(pages)},'chrome_alive':True}
    finally:
        try: await browser.stop()
        except Exception: pass

if __name__=='__main__':
    p=argparse.ArgumentParser(); mode=p.add_mutually_exclusive_group(required=True); mode.add_argument('--target'); mode.add_argument('--discover',action='store_true')
    p.add_argument('--runtime',required=True); p.add_argument('--identity'); p.add_argument('--mission',required=True); p.add_argument('--max-steps',type=int,default=35)
    a=p.parse_args()
    if a.discover and not a.identity: p.error('--identity is required with --discover')
    try:
        runtime=load_runtime(Path(a.runtime));local_probe(runtime)
        with action(runtime['browserRuntimeId'],'BROWSER_USE_AGENT'):result=asyncio.run(run(a))
        print('\nCVENT_BROWSER_RESULT='+json.dumps(result,ensure_ascii=False))
    except Exception as e:
        result={'status':'FAILED','error':f'{type(e).__name__}: {e}','chrome_alive':True}; append_log('Browser Use failed: '+result['error']); print('\nCVENT_BROWSER_RESULT='+json.dumps(result))
        sys.exit(1)
