#!/opt/homebrew/opt/python@3.11/bin/python3.11
"""Ego router pinned to the canonical Steel Chromium."""
from __future__ import annotations
import argparse,json,os,re,subprocess,sys,time,urllib.error,urllib.parse,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import parse_qs,urlparse
from browser_gate import action
from browser_runtime import command as browser_command, load, local_probe, pages as browser_pages, select_page
from runtime_config import browser_auth_metadata_path, browser_profile_dir
ROOT=Path(__file__).resolve().parent;CURRENT=Path(os.environ.get('CVENT_JOB_DIR',ROOT/'data'/'current'))
TRUSTED_PROCEDURES={'configureAdmissionItems','configureRegistrationTypes'}
TRUSTED_INSPECTIONS={'inspectRegistrationTypeCapabilities'}
EGO={'probe','recover','authStatus','authorizeTarget','openAuthorizedEvent','snapshotText','readTarget','sectionState','controlInventory','pageInfo','scanEventList','scroll','click','activate','fill','type','navigate','wait','hover','selectOption','setChecked','press','search','selectText','drag','uploadDiscountImport',*TRUSTED_INSPECTIONS,*TRUSTED_PROCEDURES}
INTENT_REQUIRED={'click','activate','fill','type','hover','selectOption','setChecked','press','search','selectText','drag',*TRUSTED_INSPECTIONS,*TRUSTED_PROCEDURES}
def event_key(url):
    try:
        pairs=parse_qs(urlparse(url).query,keep_blank_values=True)
        keys=[value.strip().lower() for name,values in pairs.items() if name.lower() in ('evtstub','eventid','event') for value in values]
        if keys:return keys[0] if keys[0] and all(value==keys[0] for value in keys) else None
        match=re.search(r'/events/([0-9a-f-]{20,})',urlparse(url).path,re.I)
        if match:return match.group(1).lower()
    except Exception:pass
    return None
def target_lock():
    try:return json.loads((CURRENT/'authorized-target.json').read_text())
    except Exception:return {}
def selected_event_inventory():
    try:return json.loads((CURRENT/'selected-event-inventory.json').read_text())
    except Exception:return {}
def canonical_lifecycle_status(value):
    return re.sub(r'\s+',' ',str(value or '').strip().lower())
def writable_event_statuses():
    values={canonical_lifecycle_status(value) for value in os.environ.get('CVENT_WRITABLE_EVENT_STATUSES','draft,active,open,completed').split(',') if value.strip()}
    if not values:raise RuntimeError('Write blocked: product policy defines no writable Cvent event statuses')
    return values
def atomic_private_json(path,value):
    temporary=path.with_name(path.name+f'.{os.getpid()}.tmp')
    with temporary.open('x') as output:json.dump(value,output,indent=2)
    temporary.chmod(0o600);temporary.replace(path)
def emit(data):print('BROWSER_ROUTER_RESULT='+json.dumps(data,ensure_ascii=False))
def audit_scope_write(operation,params,current,result,error=None):
    record={'at':datetime.now(timezone.utc).isoformat(),'operation':operation,'rrSource':params.get('rrSource'),'eventKey':event_key(current.get('url','')),'url':current.get('url'),'result':result}
    if error:record['error']=str(error)[-800:]
    with (CURRENT/'scope-write-audit.jsonl').open('a') as output:output.write(json.dumps(record,ensure_ascii=False)+'\n')
def mark_mutation_uncertain(operation,params,current,error):
    marker=CURRENT/'browser-mutation-uncertain.json';tmp=marker.with_suffix('.tmp')
    tmp.write_text(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'operation':operation,'rrSource':params.get('rrSource'),'eventKey':event_key(current.get('url','')),'url':current.get('url'),'error':str(error)[-800:]},indent=2));tmp.replace(marker)
def child_result(proc):
    marker='BROWSER_TOOL_RESULT=';index=proc.stdout.rfind(marker)
    if index>=0:
        try:return json.loads(proc.stdout[index+len(marker):].strip())
        except json.JSONDecodeError:pass
    return {'ok':False,'error':(proc.stderr or proc.stdout)[-1200:]}
def lease_is_valid(url,job_id,token,event_id):
    query=urllib.parse.urlencode({'job_id':job_id,'event_id':event_id})
    request=urllib.request.Request(url+'?'+query,headers={'X-CVENT-Lease-Token':token})
    try:
        with urllib.request.urlopen(request,timeout=5) as response:return response.status==204
    except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError):return False
def assert_event_lease(runtime):
    job_id=os.environ.get('CVENT_JOB_ID');token=os.environ.get('CVENT_LEASE_TOKEN');url=os.environ.get('CVENT_LEASE_VALIDATE_URL');event_id=runtime.get('authorizedEventId')
    if not job_id and os.environ.get('CVENT_ENV','development')!='production':return
    if not job_id or not token or not url or not event_id:raise RuntimeError('Write blocked: job event-lease context is absent')
    if not lease_is_valid(url,job_id,token,event_id):raise RuntimeError('Write blocked: canonical event lease is absent, stale, mismatched, or owned by another job')
PROTECTED_PAGE=re.compile(r'/(?:attendees?|invitees?|contacts?|contact[-_]?types?|account(?:settings)?|organization|admin|global|library|profiles?)(?:/|$)',re.I)
PROTECTED_CONTROL=re.compile(r'^(?:publish(?:\s|$)|go live(?:\s|$)|send(?:\s|$)|test[-\s]*(?:send|email)(?:\s|$)|schedule(?:\s|$)|delete(?:\s|$)|remove(?:\s|$)|archive(?:\s|$)|(?:create|new|copy|duplicate|clone)\s+(?:an?\s+)?(?:new\s+)?event(?:\s|$)|create\s+contact\s+type(?:\s|$)|attendees?$|invitees?$|contacts?$)',re.I)
MUTATING_CONTROL=re.compile(r'^(?:save(?:\s|$)|save\s*(?:&|and)\s*close(?:\s|$)|create(?:\s|$)|add(?:\s|$)|update(?:\s|$)|apply(?:\s|$)|confirm(?:\s|$)|submit(?:\s|$))',re.I)
PROTECTED_IDENTITY=re.compile(r'(?:event[-_ ]?(?:name|title|code)|evtstub|eventid|contact[-_ ]?type[-_ ]?(?:name|code))',re.I)

def assert_safe_write_target(operation,params,descriptor):
    target=str(params.get('target','')).strip()
    role=str(descriptor.get('role') or descriptor.get('tag') or '').lower()
    labels=[descriptor.get(key) for key in ('text','label','aria','title','name')]
    labels=[re.sub(r'\s+',' ',str(value)).strip() for value in labels if value]
    if PROTECTED_IDENTITY.search(target) or any(PROTECTED_IDENTITY.search(value) for value in labels):
        raise RuntimeError('Write blocked: selected event identity is immutable')
    if role in {'button','link','menuitem','tab','a'} and any(PROTECTED_CONTROL.search(value) for value in labels):
        raise RuntimeError('Write blocked: publish, communications, attendee/contact, delete, and archive controls are protected')
    href=str(descriptor.get('href') or '')
    if href and PROTECTED_PAGE.search(urlparse(href).path):
        raise RuntimeError('Write blocked: attendee/contact and communications areas are protected')

def guard(runtime,operation,params):
    if runtime.get('accessMode')=='read_only_reconciliation':
        readonly={'probe','pageInfo','authStatus','navigate','scanEventList','openAuthorizedEvent','authorizeTarget','sectionState','snapshotText','controlInventory','readTarget','recover','wait','scroll',*TRUSTED_INSPECTIONS}
        if params.get('intent')=='write' or operation not in readonly:
            raise RuntimeError('Read-only reconciliation cannot dispatch configuration writes')
    current=local_probe(runtime);lock=target_lock()
    locked=event_key(lock.get('url',''));current_key=event_key(current.get('url',''))
    valid_lock=lock.get('name')==runtime['authorizedEventName'] and bool(locked) and lock.get('event_key')==locked and (not runtime.get('authorizedEventId') or lock.get('event_id')==runtime['authorizedEventId']) and lock.get('browser_runtime_id')==runtime.get('browserRuntimeId')
    intent=params.get('intent')
    if operation=='openAuthorizedEvent':
        assert_event_lease(runtime)
        current_host=(urlparse(current.get('url','')).hostname or '').lower()
        if not current_host.endswith('cvent.com') or '/events2/eventselection' not in urlparse(current.get('url','')).path.lower():
            raise RuntimeError('Authorized event opening requires the authenticated Cvent event inventory')
        if params.get('eventName')!=runtime.get('authorizedEventName') or params.get('eventKey')!=runtime.get('authorizedEventKey'):
            raise RuntimeError('Authorized event opening identity does not match BrowserRuntime')
    if operation in INTENT_REQUIRED and intent not in ('read','write'):
        raise RuntimeError(f'{operation} requires explicit read or write intent')
    target=str(params.get('target',''))
    if target and re.search(r':(?:contains|has-text)\s*\(',target,re.I):
        raise RuntimeError('Unsupported selector syntax rejected before browser action; use an exact Ego role locator such as role:button[name="Edit"] or a selector from controlInventory')
    if intent=='write':
        origin=urlparse(current.get('url',''));host=(origin.hostname or '').lower()
        if origin.scheme!='https' or not (host=='cvent.com' or host.endswith('.cvent.com')) or origin.username or origin.password or origin.port not in (None,443):
            raise RuntimeError('Write blocked: current page is not a trusted Cvent HTTPS origin')
        if (CURRENT/'browser-mutation-uncertain.json').exists():
            raise RuntimeError('Write blocked: a prior browser mutation timed out with uncertain outcome; fresh human review is required')
        if not valid_lock or current_key!=locked:
            raise RuntimeError('Write blocked: exact authorized event lock is absent or not currently open')
        if runtime.get('authorizedEventKey') and locked!=runtime['authorizedEventKey']:
            raise RuntimeError('Write blocked: visible event key does not match the server-authorized event')
        status=canonical_lifecycle_status(lock.get('event_status'))
        if status not in writable_event_statuses():
            raise RuntimeError(f'Write blocked: selected event lifecycle status {status or "UNPROVEN"} is not writable under approved product policy')
        assert_event_lease(runtime)
        if PROTECTED_PAGE.search(urlparse(current.get('url','')).path):
            raise RuntimeError('Write blocked: attendee/contact and communications areas are protected')
    if operation in ('navigate','browser_navigate'):
        url=params.get('url','');parsed=urlparse(url);host=(parsed.hostname or '').lower();key=event_key(url)
        if host and not (host=='cvent.com' or host.endswith('.cvent.com')):raise RuntimeError('Navigation outside Cvent is blocked')
        if re.search(r'/(account|organization|admin|global)(/|$)',parsed.path,re.I):raise RuntimeError('Navigation to account-global Cvent settings is blocked')
        if PROTECTED_PAGE.search(parsed.path):raise RuntimeError('Navigation to attendee/contact and communications areas is blocked')
        if key and (not valid_lock or key!=locked):raise RuntimeError('Navigation to a non-authorized Cvent event blocked')
    return current
def supported_authenticated_origin(runtime,url):
    parsed=urlparse(url);host=(parsed.hostname or '').lower()
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.port not in (None,443):return False
    if host=='app.cvent.com':return True
    return host=='events.app.cvent.com' and bool(runtime.get('authorizedEventKey')) and event_key(url)==str(runtime['authorizedEventKey']).lower()
def visible_authenticated_context(runtime,url,ui):
    return (urlparse(url).hostname or '').lower()!='events.app.cvent.com' or ui.get('hasAuthorizedEvent') is True

def authenticated_profile_status(runtime):
    current=local_probe(runtime);slot=int(runtime.get('workerSlot',0));workspace=os.environ.get('CVENT_WORKSPACE_ID','')
    expected=browser_profile_dir(workspace,slot) if workspace and slot else None
    path=browser_auth_metadata_path(workspace,slot) if workspace and slot else None
    try:metadata=json.loads(path.read_text()) if path else {}
    except Exception:metadata={}
    profile_match=bool(expected and Path(runtime.get('profilePath','')).resolve()==expected.resolve() and expected.is_dir())
    url=current.get('url','')
    page=select_page(browser_pages(runtime['cdpHttpOrigin']),runtime['targetBrowserIdentity']['targetId'])
    organization='';ui={}
    if page:
        cookies=browser_command(page['webSocketDebuggerUrl'],'Network.getAllCookies',{},runtime['cdpHttpOrigin']).get('cookies',[])
        organization=next((str(c.get('value','')) for c in cookies if c.get('name')=='org-id' and str(c.get('domain','')).endswith('cvent.com')),'')
        expected=json.dumps(str(runtime.get('authorizedEventName') or ''))
        expression=f"(() => {{ const text=(document.body?.innerText||'').slice(0,50000), expected={expected}; return {{ready:document.readyState,hasUi:/(?:event management|my events|event details|registration|cvent)/i.test(text),hasLogin:/(?:sign in|log in|enter your password|verify your identity|authenticator)/i.test(text),hasAuthorizedEvent:Boolean(expected)&&text.includes(expected)}} }})()"
        ui=browser_command(page['webSocketDebuggerUrl'],'Runtime.evaluate',{'expression':expression,'returnByValue':True},runtime['cdpHttpOrigin']).get('result',{}).get('value',{})
    context_match=bool(organization and metadata.get('organizationId')==organization)
    visible_context=visible_authenticated_context(runtime,url,ui)
    authenticated=bool(metadata.get('authenticated') is True and metadata.get('workerSlot')==slot and profile_match and context_match and visible_context and supported_authenticated_origin(runtime,url) and not re.search(r'(?:login|signin|authenticate|sso)',url,re.I) and ui.get('ready')=='complete' and ui.get('hasUi') and not ui.get('hasLogin'))
    return {'ok':True,'operation':'authStatus','authenticated':authenticated,'persistedProfile':bool(metadata),'workerSlot':slot,'profileMatch':profile_match,'accountContextMatch':context_match,'loginRequired':not authenticated}

def recover_browser(runtime_path,runtime,tool,params):
    deadline=time.monotonic()+max(10,min(int(params.get('timeoutSeconds',240)),300));last='renderer did not respond'
    while time.monotonic()<deadline:
        try:
            with action(runtime['browserRuntimeId'],'PI_EGO'):
                current=local_probe(runtime)
                proc=subprocess.run(['node','ego_direct.mjs','--runtime',str(runtime_path),'--operation','probe','--params','{}'],cwd=ROOT,text=True,capture_output=True,timeout=25)
                result=child_result(proc)
                if not proc.returncode and result.get('ok'):
                    return {'ok':True,'tool':tool,'operation':'recover','recovered':True,'page':result.get('page'),'url':current.get('url'),'title':current.get('title'),'router':tool}
                last=result.get('error',last)
        except Exception as error:last=str(error)
        time.sleep(3)
    raise RuntimeError(f'Browser renderer did not recover within the bounded wait: {last[-500:]}')
def preflight_action_target(runtime_path,operation,params):
    keys=['target']
    if operation=='drag':keys.append('destination')
    resolved=dict(params)
    for key in keys:
        target=params.get(key)
        if not target:continue
        probe=subprocess.run(['node','ego_direct.mjs','--runtime',str(runtime_path),'--operation','__preflightTarget','--params',json.dumps({'target':target,'context':params.get('targetContext'),'index':params.get('targetIndex')})],cwd=ROOT,text=True,capture_output=True,timeout=30)
        result=child_result(probe)
        if probe.returncode or not result.get('ok'):
            raise RuntimeError('Write rejected before browser dispatch: '+result.get('error','target could not be resolved')[-800:])
        descriptor=result.get('resolved') or {}
        if not descriptor.get('connected') or descriptor.get('disabled'):
            raise RuntimeError('Write rejected before browser dispatch: target is disconnected or disabled')
        assert_safe_write_target(operation,params,descriptor)
        labels=[descriptor.get(key) for key in ('text','label','aria','title','name')]
        if params.get('intent')!='write' and any(MUTATING_CONTROL.search(re.sub(r'\s+',' ',str(value)).strip()) for value in labels if value):
            raise RuntimeError('Action rejected before browser dispatch: mutating control requires write intent and RR source evidence')
        resolved[key]=result.get('resolvedTarget') or target
    return resolved
# Backward-compatible name; all interactive targets now share this preflight.
preflight_write_target=preflight_action_target
def validate_trusted_inspection(operation,params):
    if operation not in TRUSTED_INSPECTIONS or set(params)-{'intent','records','probeCode','timeoutSeconds'}:raise RuntimeError('Trusted inspection accepts only exact RR identities')
    records=params.get('records');probe=params.get('probeCode')
    if not isinstance(records,list) or not 1<=len(records)<=100:raise RuntimeError('Trusted inspection RR identities are invalid')
    codes=[]
    for record in records:
        if not isinstance(record,dict) or set(record)!={'code','name'} or not isinstance(record.get('code'),str) or not record['code'].strip() or len(record['code'])>200 or not isinstance(record.get('name'),str) or not record['name'].strip() or len(record['name'])>1000:raise RuntimeError('Trusted inspection RR identity is invalid')
        codes.append(record['code'])
    if len(set(codes))!=len(codes):raise RuntimeError('Trusted inspection RR identities are duplicated')
    if probe is not None and (not isinstance(probe,str) or probe not in codes):raise RuntimeError('Trusted inspection probe identity is invalid')
    timeout=params.get('timeoutSeconds',300)
    if not isinstance(timeout,int) or not 30<=timeout<=900:raise RuntimeError('Trusted inspection timeout is invalid')

def validate_trusted_procedure(operation,params):
    allowed={'intent','rrSource','records','timeoutSeconds'}
    if set(params)-allowed:raise RuntimeError('Trusted procedure accepts only typed RR configuration records')
    records=params.get('records')
    if not isinstance(records,list) or not 1<=len(records)<=50:raise RuntimeError('Trusted procedure RR record count is invalid')
    for record in records:
        if not isinstance(record,dict):raise RuntimeError('Trusted procedure record must be an object')
        common={'code','name','source'}
        expected=common|({'registrationTypes','knownRegistrationTypes'} if operation=='configureAdmissionItems' else {'activationDirective','groupRegistration','reprintFee'})
        if set(record)-expected:raise RuntimeError('Trusted procedure record contains an unsupported field')
        if not isinstance(record.get('code'),str) or not record['code'].strip() or len(record['code'])>200:raise RuntimeError('Trusted procedure code is invalid')
        if not isinstance(record.get('name'),str) or not record['name'].strip() or len(record['name'])>1000:raise RuntimeError('Trusted procedure name is invalid')
        if not isinstance(record.get('source'),str) or len(record['source'])>500:raise RuntimeError('Trusted procedure source evidence is invalid')
        if operation=='configureAdmissionItems':
            values=record.get('registrationTypes');known=record.get('knownRegistrationTypes')
            if not isinstance(values,list) or len(values)>100 or not isinstance(known,list) or not 1<=len(known)<=100:raise RuntimeError('Admission registration-type associations are invalid')
            for item in values+known:
                if not isinstance(item,dict) or set(item)-{'code','name'} or not isinstance(item.get('code'),str) or not isinstance(item.get('name'),str):raise RuntimeError('Admission registration-type association is invalid')
        else:
            if record.get('activationDirective') not in ('ACTIVATE','REQUIRED') or (record.get('groupRegistration') is not None and not isinstance(record['groupRegistration'],bool)):raise RuntimeError('Registration-type directives are invalid')
            if record.get('reprintFee') is not None and (not isinstance(record['reprintFee'],(int,float)) or not 0<=record['reprintFee']<=100000):raise RuntimeError('Registration-type reprint fee is invalid')
    timeout=params.get('timeoutSeconds',600)
    if not isinstance(timeout,int) or not 30<=timeout<=900:raise RuntimeError('Trusted procedure timeout is invalid')


def fixed_upload_artifact(params):
    if params.get('artifact')!='discount-import.xlsx':raise RuntimeError('Only the compiled RR discount import artifact may be uploaded')
    candidate=CURRENT/'discount-import.xlsx';info=candidate.lstat()
    if candidate.is_symlink() or not candidate.is_file() or info.st_size>25*1024*1024:raise RuntimeError('Discount import artifact is invalid')
    path=candidate.resolve()
    if path.parent!=CURRENT.resolve():raise RuntimeError('Upload artifact escaped the private job workspace')
    return path

def run_direct(runtime_path,runtime,tool,operation,params):
    executable=['node','ego_direct.mjs']
    if operation=='recover':return recover_browser(runtime_path,runtime,tool,params)
    with action(runtime['browserRuntimeId'],'PI_EGO'):
        current=guard(runtime,operation,params)
        if operation=='authStatus':
            return {'tool':'ego','router':'ego',**authenticated_profile_status(runtime)}
        if operation=='authorizeTarget':
            probe=subprocess.run(['node','ego_direct.mjs','--runtime',str(runtime_path),'--operation','snapshotText','--params','{}'],cwd=ROOT,text=True,capture_output=True,timeout=90);observed=child_result(probe)
            info=local_probe(runtime);key=event_key(info.get('url',''));inventory=selected_event_inventory()
            host=(urlparse(info.get('url','')).hostname or '').lower()
            if params.get('eventName')!=runtime['authorizedEventName'] or runtime['authorizedEventName'].lower() not in json.dumps(observed).lower() or not key or not host.endswith('cvent.com'):raise RuntimeError('Exact visible authorized event identity was not proven')
            if runtime.get('authorizedEventKey') and key!=runtime['authorizedEventKey']:raise RuntimeError('Visible event key is not the server-authorized event')
            if inventory.get('name')!=runtime['authorizedEventName'] or inventory.get('event_key')!=key or inventory.get('browser_runtime_id')!=runtime['browserRuntimeId'] or not str(inventory.get('status') or '').strip():raise RuntimeError('Exact selected-event lifecycle status was not proven from inventory')
            lock={'name':runtime['authorizedEventName'],'event_id':runtime.get('authorizedEventId'),'url':info['url'],'event_key':key,'event_status':inventory['status'],'browser_runtime_id':runtime['browserRuntimeId'],'locked_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),'mode':'mock','source':'ego-direct'}
            target=CURRENT/'authorized-target.json';atomic_private_json(target,lock)
            runtime['targetBrowserIdentity'].update({'url':info['url'],'title':info['title']});tmp=runtime_path.with_suffix('.tmp');tmp.write_text(json.dumps(runtime,indent=2));tmp.replace(runtime_path)
            return {'ok':True,'tool':'ego','operation':operation,'authorizedTarget':lock,'router':'ego'}
        is_write=params.get('intent')=='write'
        if operation in TRUSTED_INSPECTIONS:validate_trusted_inspection(operation,params)
        if operation in TRUSTED_PROCEDURES:validate_trusted_procedure(operation,params)
        if params.get('target') and operation in {'click','activate','fill','type','hover','selectOption','setChecked','press','search','selectText','drag'}:
            params=preflight_action_target(runtime_path,operation,params)
        if is_write:
            if operation=='uploadDiscountImport':params['filePath']=str(fixed_upload_artifact(params))
            audit_scope_write(operation,params,current,'attempted')
        try:
            proc=subprocess.run(executable+['--runtime',str(runtime_path),'--operation',operation,'--params',json.dumps(params)],cwd=ROOT,text=True,capture_output=True,timeout=params.get('timeoutSeconds',90))
        except subprocess.TimeoutExpired as error:
            if is_write:
                audit_scope_write(operation,params,current,'uncertain_timeout',error)
                mark_mutation_uncertain(operation,params,current,error)
            raise RuntimeError('Browser mutation outcome is uncertain after helper timeout; automatic replay is blocked') from error
    result=child_result(proc);result['router']=tool
    if operation=='openAuthorizedEvent' and not proc.returncode and result.get('ok'):
        selected=result.get('navigationTarget') or {};selected_key=event_key(str(selected.get('href') or ''))
        if selected.get('name')!=runtime.get('authorizedEventName') or selected_key!=runtime.get('authorizedEventKey') or not str(selected.get('status') or '').strip():
            raise RuntimeError('Opened event inventory evidence omitted exact identity or lifecycle status')
        atomic_private_json(CURRENT/'selected-event-inventory.json',{'name':selected['name'],'event_key':selected_key,
            'event_id':runtime.get('authorizedEventId'),'code':selected.get('code'),'status':selected['status'],
            'href':selected.get('href'),'browser_runtime_id':runtime['browserRuntimeId'],'observed_at':datetime.now(timezone.utc).isoformat()})
    if params.get('intent')=='write':
        if proc.returncode or not result.get('ok'):
            audit_scope_write(operation,params,current,'uncertain_error',result.get('error'))
            mark_mutation_uncertain(operation,params,current,result.get('error','browser helper failed after write attempt'))
        else:audit_scope_write(operation,params,current,'succeeded')
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
