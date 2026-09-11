#!/usr/bin/env node
/** Ego direct-tool adapter pinned to the canonical Steel Chromium target. */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { inspectRegistrationTypeCapabilities, runTrustedCventProcedure } from './trusted_cvent_procedures.mjs';
const argv=process.argv.slice(2);const arg=n=>argv[argv.indexOf(n)+1];
const runtimePath=arg('--runtime');const operation=arg('--operation');const params=JSON.parse(arg('--params')||'{}');
function output(value,ok=true){return new Promise((resolve,reject)=>{const failed=typeof value==='object'&&value?value:{error:String(value)};process.stdout.write('BROWSER_TOOL_RESULT='+JSON.stringify(ok?{ok:true,tool:'ego',operation,...value}:{ok:false,tool:'ego',operation,...failed,error:String(failed.error??value)})+'\n',error=>error?reject(error):resolve())})}
function roleRequest(target){
  const match=String(target||'').match(/^role:([a-z][a-z0-9_-]*)\[name=(?:"([^"]+)"|'([^']+)'|([^\]]+))\]$/i);
  return match?{role:match[1].toLowerCase(),name:(match[2]??match[3]??match[4]??'').trim()}:null;
}
const snapshotCachePath=runtimePath?path.join(path.dirname(path.resolve(runtimePath)),'browser-snapshot-cache.json'):null;
function readSnapshotCache(){
  try{const info=fs.lstatSync(snapshotCachePath);if(!info.isFile()||info.isSymbolicLink()||info.size>3*1024*1024)return null;return JSON.parse(fs.readFileSync(snapshotCachePath,'utf8'))}catch{return null}
}
function writeSnapshotCache(value){
  const temporary=`${snapshotCachePath}.${process.pid}.tmp`;fs.writeFileSync(temporary,JSON.stringify(value),{encoding:'utf8',mode:0o600,flag:'wx'});fs.renameSync(temporary,snapshotCachePath);fs.chmodSync(snapshotCachePath,0o600);
}
if(snapshotCachePath&&['script','actions','click','activate','visualClick','visualDoubleClick','fill','type','typeText','navigate','selectOption','setChecked','press','drag','visualDrag','uploadDiscountImport','recover','openAuthorizedEvent','inspectRegistrationTypeCapabilities','configureAdmissionItems','configureRegistrationTypes'].includes(operation)){try{fs.unlinkSync(snapshotCachePath)}catch(error){if(error?.code!=='ENOENT')throw error}}
if(!runtimePath||!operation){await output('Explicit --runtime and --operation are required',false);process.exit(2)}
const runtime=JSON.parse(fs.readFileSync(runtimePath,'utf8'));
const cdpOrigin=new URL(runtime.cdpHttpOrigin);process.env.EGO_BROWSER_CDP_HOST=cdpOrigin.hostname;process.env.EGO_BROWSER_CDP_PORT=cdpOrigin.port;
// Failure reporting lives outside try: startup, action, and postflight errors
// must retain their original cause and every successfully completed action.
const completedActions=[];
let writesAttempted=0,actionIndex=-1,dirty=false,saved=false,saves=0,readbacks=0;
try{
  const ego=await import('./vendor/ego-browser-linux/dist/src/helpers.js');
  const tabs=await ego.listTabs();
  const wanted=runtime.targetBrowserIdentity.targetId;
  const tab=tabs.find(t=>(t.targetId||t.id)===wanted);
  if(!tab)throw new Error('Canonical BrowserRuntime target is not available');
  await ego.switchTab(wanted);
  const marker=await ego.evaluate("window.__CVENT_BROWSER_RUNTIME_ID || (window.name.startsWith('cvent-runtime-') ? window.name : null)");
  if(marker!==runtime.browserRuntimeId)throw new Error('Ego marker mismatch — cross-browser routing blocked');
  const normalize=value=>String(value??'').replace(/\s+/g,' ').trim();
  async function dispatch(step,callback){
    if(step.intent!=='write')return callback();
    try{const value=await callback();writesAttempted++;return value}
    catch(error){writesAttempted++;throw error}
  }
  const eventKey=url=>{try{const parsed=new URL(url),query=parsed.searchParams,keys=['evtstub','eventid','event'].map(name=>query.get(name)?.trim().toLowerCase()).filter(Boolean);if(keys.length)return keys.every(key=>key===keys[0])?keys[0]:null;return parsed.pathname.match(/\/events\/([0-9a-f-]{20,})/i)?.[1]?.toLowerCase()??null}catch{return null}};
  async function assertLease(){
    const endpoint=process.env.CVENT_LEASE_VALIDATE_URL,jobId=process.env.CVENT_JOB_ID,token=process.env.CVENT_LEASE_TOKEN,eventId=runtime.authorizedEventId;
    if(!jobId&&process.env.CVENT_ENV!=='production')return;
    if(!endpoint||!jobId||!token||!eventId)throw new Error('Write blocked: action round lease context is absent');
    const url=new URL(endpoint);if(!['127.0.0.1','localhost','::1'].includes(url.hostname)||!['http:','https:'].includes(url.protocol))throw new Error('Write blocked: lease validator is not loopback');
    url.searchParams.set('job_id',jobId);url.searchParams.set('event_id',eventId);
    const response=await fetch(url,{headers:{'X-CVENT-Lease-Token':token},signal:AbortSignal.timeout(5000)});
    if(response.status!==204)throw new Error('Write blocked: canonical event lease is no longer active');
  }
  async function assertAuthorizedPage(){
    const info=await ego.pageInfo(),url=new URL(info.url),host=url.hostname.toLowerCase(),key=eventKey(info.url),expected=String(runtime.authorizedEventKey||'').toLowerCase();
    if(url.protocol!=='https:'||!(host==='cvent.com'||host.endsWith('.cvent.com'))||!key||key!==expected)throw new Error('Write blocked: Ego left the exact authorized event');
    if(/\/(?:attendees?|invitees?|contacts?|contact[-_]?types?|account(?:settings)?|organization|admin|global|library|profiles?)(?:\/|$)/i.test(url.pathname))throw new Error('Write blocked: protected Cvent area');
  }
  async function resolveTarget(request){
    let target=request.target,descriptor,fallbackUsed=false;
    try{descriptor=await ego.evaluateLocator(target,(element)=>{const id=element.id,label=id?document.querySelector('label[for="'+CSS.escape(id)+'"]'):element.closest('label');return {tag:element.tagName,role:element.getAttribute('role'),text:(element.innerText||element.textContent||'').trim().slice(0,500),label:(label?.innerText||label?.textContent||'').trim().slice(0,500),aria:element.getAttribute('aria-label'),title:element.getAttribute('title'),name:element.getAttribute('name'),href:element instanceof HTMLAnchorElement?element.href:null,disabled:'disabled' in element?Boolean(element.disabled):false,connected:element.isConnected}})}
    catch(originalError){
      const requested=roleRequest(target);if(!requested)throw originalError;const token=`cvent-round-target-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      const found=await ego.evaluate(`(() => {const requested=${JSON.stringify(requested)},token=${JSON.stringify(token)},context=${JSON.stringify(String(request.targetContext||''))},index=${JSON.stringify(Number.isInteger(request.targetIndex)?request.targetIndex:null)},norm=v=>String(v||'').toLowerCase().replace(/[\\s:*]+/g,' ').trim(),role=e=>e.getAttribute('role')||(e.tagName==='BUTTON'?'button':e.tagName==='A'&&e.href?'link':e.tagName==='SELECT'?'combobox':e.matches('input,textarea')?'textbox':''),all=[...document.querySelectorAll('*')].filter(e=>role(e).toLowerCase()===requested.role&&e.isConnected),matches=all.filter(e=>{const id=e.id,label=id?document.querySelector('label[for="'+CSS.escape(id)+'"]'):null,names=[e.getAttribute('aria-label'),e.getAttribute('title'),e.getAttribute('name'),label?.innerText,e.closest('label')?.innerText,e.innerText].filter(Boolean).map(norm),box=e.getBoundingClientRect(),style=getComputedStyle(e);if(!names.includes(norm(requested.name))||box.width<=0||box.height<=0||style.display==='none'||style.visibility==='hidden'||e.disabled)return false;if(!context)return true;let p=e.parentElement;for(let d=0;p&&d<10;d++,p=p.parentElement)if(norm(p.innerText||p.textContent).includes(norm(context)))return true;return false}),chosen=index!==null?matches[index]:matches.length===1?matches[0]:null;if(!chosen)return {count:matches.length};chosen.setAttribute('data-cvent-round-target',token);const id=chosen.id,label=id?document.querySelector('label[for="'+CSS.escape(id)+'"]'):chosen.closest('label');return {count:1,descriptor:{tag:chosen.tagName,role:role(chosen),text:(chosen.innerText||chosen.textContent||'').trim().slice(0,500),label:(label?.innerText||label?.textContent||'').trim().slice(0,500),aria:chosen.getAttribute('aria-label'),title:chosen.getAttribute('title'),name:chosen.getAttribute('name'),href:chosen instanceof HTMLAnchorElement?chosen.href:null,disabled:Boolean(chosen.disabled),connected:chosen.isConnected}}})()`);
      if(found.count!==1)throw new Error(`Target resolution found ${found.count} exact accessible-name matches`);target=`[data-cvent-round-target="${token}"]`;descriptor=found.descriptor;fallbackUsed=true;
    }
    return {target,descriptor,fallbackUsed};
  }
  async function pointDescriptor(x,y){return ego.evaluate(`(() => {let e=document.elementFromPoint(${JSON.stringify(x)},${JSON.stringify(y)});if(!e)return null;e=e.closest('button,a,input,select,textarea,[role],[contenteditable=true]')||e;return {tag:e.tagName,role:e.getAttribute('role'),text:(e.innerText||e.textContent||'').trim().slice(0,500),label:e.getAttribute('aria-label')||e.getAttribute('title')||'',aria:e.getAttribute('aria-label'),title:e.getAttribute('title'),name:e.getAttribute('name'),href:e instanceof HTMLAnchorElement?e.href:null,disabled:Boolean(e.disabled),connected:e.isConnected}})()`)}
  async function compactControlInventory(){return ego.evaluate(`(() => {const norm=value=>String(value||'').replace(/\\s+/g,' ').trim(),selectorFor=element=>element.id?'#'+CSS.escape(element.id):(element.getAttribute('name')?'[name="'+CSS.escape(element.getAttribute('name'))+'"]':element.getAttribute('data-cvent-id')?'[data-cvent-id="'+CSS.escape(element.getAttribute('data-cvent-id'))+'"]':element.getAttribute('data-testid')?'[data-testid="'+CSS.escape(element.getAttribute('data-testid'))+'"]':null),controls=[],seen=new Set();for(const element of document.querySelectorAll('input,select,textarea,button,[role=combobox],[contenteditable=true]')){if(seen.has(element))continue;seen.add(element);const type=(element.getAttribute('type')||'').toLowerCase(),style=getComputedStyle(element),box=element.getBoundingClientRect();if(type==='hidden'||!element.isConnected||box.width<=0||box.height<=0||style.display==='none'||style.visibility==='hidden')continue;const id=element.id,label=id?document.querySelector('label[for="'+CSS.escape(id)+'"]'):element.closest('label'),selector=selectorFor(element),name=norm(element.getAttribute('aria-label')||label?.innerText||element.getAttribute('title')||element.getAttribute('name')||element.innerText);if(!selector&&!name)continue;controls.push({tag:element.tagName,role:element.getAttribute('role'),label:name.slice(0,300),selector,type:type||null,value:type==='password'?null:('value' in element?String(element.value).slice(0,500):null),checked:'checked' in element?Boolean(element.checked):null,disabled:'disabled' in element?Boolean(element.disabled):null,options:element.tagName==='SELECT'?[...element.options].map(option=>({label:norm(option.textContent).slice(0,200),value:option.value,selected:option.selected,disabled:option.disabled})).slice(0,250):undefined});if(controls.length>=400)break}return {url:location.href,title:document.title,controls}})()`)}
  async function authorizeInteractive(step,descriptor){
    if(!descriptor||!descriptor.connected||descriptor.disabled)throw new Error('Action target is missing, disconnected, or disabled');
    const labels=['text','label','aria','title','name'].map(key=>normalize(descriptor[key])).filter(Boolean),target=normalize(step.target);
    const identity=/(?:event[-_ ]?(?:name|title|code)|evtstub|eventid|contact[-_ ]?type[-_ ]?(?:name|code))/i;
    const protectedControl=/^(?:publish(?:\s|$)|go live(?:\s|$)|send(?:\s|$)|test[-\s]*(?:send|email)(?:\s|$)|schedule(?:\s|$)|delete(?:\s|$)|remove(?:\s|$)|archive(?:\s|$)|(?:create|new|copy|duplicate|clone)\s+(?:an?\s+)?(?:new\s+)?event(?:\s|$)|create\s+contact\s+type(?:\s|$)|attendees?$|invitees?$|contacts?$)/i;
    const mutating=/^(?:save(?:\s|$)|save\s*(?:&|and)\s*close(?:\s|$)|create(?:\s|$)|add(?:\s|$)|update(?:\s|$)|apply(?:\s|$)|confirm(?:\s|$)|submit(?:\s|$))/i;
    if(identity.test(target)||labels.some(label=>identity.test(label)))throw new Error('Write blocked: selected event identity is immutable');
    if(labels.some(label=>protectedControl.test(label))||descriptor.href&&/\/(?:attendees?|invitees?|contacts?|contact[-_]?types?|account|organization|admin|global|library|profiles?)(?:\/|$)/i.test(new URL(descriptor.href).pathname))throw new Error('Action blocked: protected Cvent control');
    if(descriptor.href){const url=new URL(descriptor.href),key=eventKey(url.href);if(url.protocol!=='https:'||!(url.hostname==='cvent.com'||url.hostname.endsWith('.cvent.com'))||key&&key!==String(runtime.authorizedEventKey).toLowerCase())throw Error('Navigation outside exact authorized event blocked');}
    if(step.intent!=='write'&&(labels.some(label=>mutating.test(label))||['checkbox','radio','switch'].includes(String(descriptor.role).toLowerCase())||descriptor.tag==='INPUT'&&['click','activate'].includes(step.operation)))throw new Error('Mutating control requires write intent and RR evidence');
    if(step.intent==='write'){await assertLease();await assertAuthorizedPage();}
  }
  async function runAdaptive(step){
    const op=step.operation;let resolved;
    if(step.target&&['readTarget','click','activate','fill','type','hover','selectOption','setChecked','press','search','selectText','drag','uploadDiscountImport'].includes(op)){resolved=await resolveTarget(step);step={...step,target:resolved.target};if(op!=='readTarget')await authorizeInteractive(step,resolved.descriptor)}
    if(['visualClick','visualDoubleClick','visualDrag'].includes(op))await authorizeInteractive(step,await pointDescriptor(step.x,step.y));
    if(['typeText','press'].includes(op)&&!step.target&&step.intent==='write'){
      const focused=await ego.evaluate(`(() => {const e=document.activeElement;if(!e)return null;const label=e.id?document.querySelector('label[for="'+CSS.escape(e.id)+'"]'):e.closest('label');return {tag:e.tagName,role:e.getAttribute('role'),name:e.getAttribute('name'),aria:e.getAttribute('aria-label'),label:label?.innerText||'',title:e.getAttribute('title'),connected:e.isConnected,disabled:Boolean(e.disabled)}})()`);
      await authorizeInteractive(step,focused);
    }
    if(step.intent==='write'&&!['click','activate','fill','type','hover','selectOption','setChecked','press','search','selectText','drag','uploadDiscountImport','visualClick','visualDoubleClick','visualDrag'].includes(op)){await assertLease();await assertAuthorizedPage();}
    switch(op){
      case 'pageInfo':return {page:await ego.pageInfo()};
      case 'snapshotText':return {snapshot:await ego.snapshot()};
      case 'screenshot':return {screenshotPath:await ego.screenshot({path:step.filePath,fullPage:step.fullPage===true})};
      case 'readTarget':return {target:step.target,...await ego.evaluateLocator(step.target,(element)=>{const type=(element.getAttribute('type')||'').toLowerCase();return {text:(element.innerText||element.textContent||'').trim(),value:type==='password'?null:('value' in element?String(element.value):null),checked:'checked' in element?Boolean(element.checked):null}})};
      case 'controlInventory':return {snapshotKind:'controlInventory',snapshot:JSON.stringify(await compactControlInventory(),null,2)};
      case 'sectionState':return await ego.evaluate(`(() => {const norm=v=>String(v||'').replace(/\\s+/g,' ').trim();return {url:location.href,title:document.title,rows:[...document.querySelectorAll('table tr,[role=row]')].slice(0,2000).map(r=>({text:norm(r.innerText||r.textContent).slice(0,5000),cells:[...r.querySelectorAll('th,td,[role=cell],[role=columnheader]')].map(c=>norm(c.innerText||c.textContent).slice(0,2000)),links:[...r.querySelectorAll('a[href]')].map(a=>({text:norm(a.innerText||a.textContent),href:a.href})).slice(0,20)})).filter(r=>r.text),headings:[...document.querySelectorAll('h1,h2,h3,[role=heading]')].map(e=>norm(e.innerText||e.textContent)).filter(Boolean),buttons:[...document.querySelectorAll('button,[role=button],input[type=submit]')].map(e=>norm(e.innerText||e.value||e.getAttribute('aria-label'))).filter(Boolean)}})()`);
      case 'scroll':await ego.wheel(0,Number(step.deltaY??700));await ego.waitForTimeout(step.settleMs??500);return {scrolledBy:step.deltaY??700};
      case 'click':await dispatch(step,()=>ego.click(step.target,{label:step.label}));return {clicked:true};
      case 'activate':return {activated:await dispatch(step,()=>ego.evaluateLocator(step.target,(element)=>{element.click();return true}))};
      case 'visualClick':await dispatch(step,()=>ego.click([step.x,step.y],{label:step.label}));return {clicked:[step.x,step.y]};
      case 'visualDoubleClick':await dispatch(step,()=>ego.dblclick([step.x,step.y],{label:step.label}));return {doubleClicked:[step.x,step.y]};
      case 'fill':await dispatch(step,()=>ego.fill(step.target,step.text??''));return {filled:true};
      case 'type':await dispatch(step,async()=>{await ego.focus(step.target);await ego.insertText(step.text??'')});return {typed:true};
      case 'typeText':await dispatch(step,()=>ego.insertText(step.text??''));return {typed:true};
      case 'hover':await dispatch(step,()=>ego.hover(step.target));return {hovered:true};
      case 'selectOption':{const d=await ego.evaluateLocator(step.target,e=>({tag:e.tagName,options:e.tagName==='SELECT'?[...e.options].map(o=>({label:String(o.textContent||'').replace(/\s+/g,' ').trim(),value:o.value,disabled:o.disabled})):[]}));if(d.tag==='SELECT'){const key=step.optionBy==='value'?'value':'label',matches=d.options.filter(option=>option[key]===String(step.option)&&!option.disabled);if(matches.length!==1)throw new Error(`Native Cvent combobox found ${matches.length} exact ${key} matches`);await dispatch(step,()=>ego.selectOption(step.target,{[key]:step.option}));return {selected:step.option}}if(step.optionBy==='value')throw new Error('Custom combobox requires exact option label');await ego.click(step.target);await ego.waitForTimeout(250);const option=await resolveTarget({target:`role:option[name="${String(step.option).replaceAll('"','\\"')}"]`});await dispatch(step,()=>ego.click(option.target));return {selected:step.option}}
      case 'setChecked':await dispatch(step,()=>ego.setChecked(step.target,Boolean(step.checked)));return {checked:Boolean(step.checked)};
      case 'press':await dispatch(step,async()=>{if(step.target)await ego.focus(step.target);await ego.press(step.key)});return {pressed:step.key};
      case 'search':await dispatch(step,async()=>{await ego.fill(step.target,step.text??'');if(step.submit!==false)await ego.press('Enter')});return {query:step.text??''};
      case 'selectText':return {selected:await ego.evaluateLocator(step.target,(element)=>{const range=document.createRange(),selection=getSelection();range.selectNodeContents(element);selection.removeAllRanges();selection.addRange(range);element.closest('[contenteditable=true]')?.focus();return selection.toString()})};
      case 'drag':await dispatch(step,()=>ego.drag([step.target,step.destination],{delay:75}));return {dragged:true};
      case 'visualDrag':await dispatch(step,()=>ego.drag([[step.x,step.y],[step.toX,step.toY]],{delay:75,label:step.label}));return {dragged:[[step.x,step.y],[step.toX,step.toY]]};
      case 'uploadDiscountImport':await dispatch(step,()=>ego.setInputFiles(step.target,step.filePath));return {uploadedArtifact:'discount-import.xlsx'};
      case 'navigate':{const url=new URL(step.url),key=eventKey(url.href),expected=String(runtime.authorizedEventKey||'').toLowerCase();if(url.protocol!=='https:'||!(url.hostname==='cvent.com'||url.hostname.endsWith('.cvent.com'))||key!==expected||/\/(?:attendees?|invitees?|contacts?|account|organization|admin|global|library|profiles?)(?:\/|$)/i.test(url.pathname))throw new Error('Navigation outside exact authorized event blocked');await ego.goto(url.href,{waitUntil:step.waitUntil||'domcontentloaded',timeout:Math.max(1000,Math.min(Number(step.timeoutSeconds??30),180)*1000)});await assertAuthorizedPage();return {navigated:url.href}}
      case 'wait':if(step.target)await ego.waitForSelector(step.target,{timeout:step.ms??30000});else if(step.loadState)await ego.waitForLoadState(step.loadState,{timeout:step.ms??30000});else await ego.waitForTimeout(step.ms??1000);return {waitedMs:step.ms??1000};
      default:throw new Error(`Unsupported coherent Ego action: ${op}`);
    }
  }
  let result;
  switch(operation){
    case '__preflightTarget': {const resolved=await resolveTarget({target:params.target,targetContext:params.context,targetIndex:params.index});result={resolved:resolved.descriptor,resolvedTarget:resolved.target,fallbackUsed:resolved.fallbackUsed};break;}
    case 'probe': {const info=await ego.pageInfo();result={marker,targetId:wanted,url:info.url,title:info.title};break}
    case 'snapshotText': {
      const identity=await ego.evaluate(`(() => {if(!window.__CVENT_SNAPSHOT_DOCUMENT_ID){Object.defineProperty(window,'__CVENT_SNAPSHOT_DOCUMENT_ID',{value:crypto.randomUUID(),configurable:false});window.__CVENT_SNAPSHOT_GENERATION=0;new MutationObserver(()=>window.__CVENT_SNAPSHOT_GENERATION++).observe(document.documentElement,{subtree:true,childList:true,attributes:true,characterData:true})}return {documentId:window.__CVENT_SNAPSHOT_DOCUMENT_ID,generation:window.__CVENT_SNAPSHOT_GENERATION,url:location.href}})()`);
      const cached=readSnapshotCache();
      if(cached&&cached.browserRuntimeId===runtime.browserRuntimeId&&cached.targetId===wanted&&cached.documentId===identity.documentId&&cached.generation===identity.generation&&cached.url===identity.url&&Date.now()-cached.savedAt<60000){
        result={snapshot:cached.snapshot,snapshotCacheHit:true};
      }else{
        const snapshot=await ego.snapshot();const after=await ego.evaluate(`({documentId:window.__CVENT_SNAPSHOT_DOCUMENT_ID,generation:window.__CVENT_SNAPSHOT_GENERATION,url:location.href})`);
        if(identity.documentId===after.documentId&&identity.generation===after.generation&&identity.url===after.url)writeSnapshotCache({browserRuntimeId:runtime.browserRuntimeId,targetId:wanted,...after,savedAt:Date.now(),snapshot});
        result={snapshot,snapshotCacheHit:false};
      }
      break;
    }
    case 'readTarget': {
      const state=await ego.evaluateLocator(params.target,(element)=>{const rect=element.getBoundingClientRect(),style=getComputedStyle(element),type=(element.getAttribute('type')||'').toLowerCase();return {text:(element.innerText||element.textContent||'').trim(),value:type==='password'?null:('value' in element?String(element.value):null),checked:'checked' in element?Boolean(element.checked):null,enabled:!(('disabled' in element&&element.disabled)||element.getAttribute('aria-disabled')==='true'),visible:element.isConnected&&rect.width>0&&rect.height>0&&style.display!=='none'&&style.visibility!=='hidden'}});
      result={target:params.target,...state};
      break;
    }
    case 'sectionState': {
      if(params.domain==='pricing'){
        // The planner SPA navigates before its fee tables render. Never turn a
        // loading shell into a complete-but-empty RR reconciliation result.
        let ready=false;
        for(let attempt=0;attempt<60;attempt++){
          ready=await ego.evaluate(`Boolean([...document.querySelectorAll('h1,h2,h3,[role=heading]')].some(element=>String(element.innerText||element.textContent||'').trim()==='Pricing')&&document.querySelector('table tr,[role=row]'))`);
          if(ready)break;
          await ego.waitForTimeout(500);
        }
        if(!ready)throw new Error('Pricing fee tables did not render; section state is unavailable, not empty');
      }
      result=await ego.evaluate(`(() => {const norm=v=>String(v||'').replace(/\\s+/g,' ').trim(),labelFor=element=>{const id=element.id,label=id?document.querySelector('label[for="'+CSS.escape(id)+'"]'):null;return norm(element.getAttribute('aria-label')||label?.innerText||element.closest('label')?.innerText||element.getAttribute('name')||element.getAttribute('placeholder'))},selectorFor=element=>element.id?'#'+CSS.escape(element.id):(element.getAttribute('name')?'[name="'+CSS.escape(element.getAttribute('name'))+'"]':null),rows=[...document.querySelectorAll('table tr,[role=row]')].slice(0,2000).map(row=>({text:norm(row.innerText||row.textContent).slice(0,5000),cells:[...row.querySelectorAll('th,td,[role=cell],[role=columnheader]')].map(cell=>norm(cell.innerText||cell.textContent).slice(0,2000)),links:[...row.querySelectorAll('a[href]')].map(link=>({text:norm(link.innerText||link.textContent).slice(0,1000),href:link.href})).slice(0,20)})).filter(row=>row.text),controls=[...document.querySelectorAll('input,select,textarea,[role=combobox]')].slice(0,500).map(element=>{const type=(element.getAttribute('type')||'').toLowerCase();return {selector:selectorFor(element),label:labelFor(element),type:type||element.tagName.toLowerCase(),value:type==='password'?null:('value' in element?String(element.value).slice(0,5000):null),checked:'checked' in element?Boolean(element.checked):null,disabled:'disabled' in element?Boolean(element.disabled):null,options:element.tagName==='SELECT'?[...element.options].map(option=>({label:norm(option.textContent),value:option.value,selected:option.selected})).slice(0,500):undefined}}),headings=[...document.querySelectorAll('h1,h2,h3,[role=heading]')].map(element=>norm(element.innerText||element.textContent)).filter(Boolean).slice(0,100),buttons=[...document.querySelectorAll('button,[role=button],input[type=submit]')].map(element=>({text:norm(element.innerText||element.value||element.getAttribute('aria-label')),disabled:Boolean(element.disabled)})).filter(item=>item.text).slice(0,200);return {url:location.href,title:document.title,rows,controls,headings,buttons}})()`);break;
    }
    case 'controlInventory': {
      result={snapshotKind:'controlInventory',snapshot:JSON.stringify(await compactControlInventory(),null,2)};break;
    }
    case 'pageInfo': result={page:await ego.pageInfo()};break;
    case 'scroll': {
      const delta=Number(params.deltaY??params.y??Math.max(500,Math.round((await ego.evaluate('window.innerHeight'))*.8)));
      result={scroll:await ego.evaluate(`(() => { window.scrollBy(0,${JSON.stringify(delta)}); return {beforeY:scrollY,height:innerHeight,scrollHeight:document.documentElement.scrollHeight} })()`)};
      await ego.waitForTimeout(params.settleMs??500);
      result.scroll.afterY=await ego.evaluate('scrollY');break;
    }
    case 'scanEventList': {
      const exactName=String(params.exactName||'').trim();if(!exactName)throw new Error('scanEventList requires exactName');
      const seen=new Map(),passes=[];const maxScrolls=Math.max(1,Math.min(Number(params.maxScrolls??30),100));
      await ego.evaluate('window.scrollTo(0,0)');await ego.waitForTimeout(params.settleMs??350);
      for(let i=0;i<maxScrolls;i++){
        const view=await ego.evaluate(`(() => {const clean=v=>String(v||'').replace(/\\s+/g,' ').trim().toLowerCase(),rows=[];for(const table of document.querySelectorAll('table')){const headers=[...table.querySelectorAll('thead th')];const effective=headers.length?headers:[...(table.querySelector('tr')?.querySelectorAll('th')||[])],names=effective.map(cell=>clean(cell.innerText||cell.textContent).replace(/[\\uE000-\\uF8FF]/g,'')),codeIndex=names.findIndex(name=>name==='code'||name==='event code'),statusIndex=names.findIndex(name=>name==='status'||name==='event status');for(const row of table.querySelectorAll('tr')){const r=row.getBoundingClientRect();if(r.bottom<0||r.top>innerHeight)continue;const cells=[...row.querySelectorAll('td')].map(x=>(x.innerText||'').trim()),link=row.querySelector('td a');if(link&&cells.length)rows.push({name:(link.innerText||'').trim(),code:codeIndex>=0?cells[codeIndex]||'':'',status:statusIndex>=0?cells[statusIndex]||'':'',inventoryColumnsTrusted:codeIndex>=0&&statusIndex>=0,href:link.href||'',top:Math.round(r.top)})}}return {y:scrollY,height:innerHeight,scrollHeight:document.documentElement.scrollHeight,rows} })()`);
        for(const row of view.rows)seen.set(`${row.name}\u0000${row.code}`,row);
        passes.push({y:view.y,visibleRows:view.rows.length});
        if(view.y+view.height>=view.scrollHeight-2)break;
        await ego.evaluate(`window.scrollBy(0,Math.max(500,Math.round(innerHeight*.8)))`);await ego.waitForTimeout(params.settleMs??500);
      }
      const rows=[...seen.values()],exactMatches=rows.filter(row=>row.name===exactName);
      result={exactName,exactMatches,observedRows:rows,passes,finalY:await ego.evaluate('scrollY'),scrollHeight:await ego.evaluate('document.documentElement.scrollHeight')};break;
    }
    case 'openAuthorizedEvent': {
      const exactName=String(params.eventName||'').trim(),expectedKey=String(params.eventKey||'').trim().toLowerCase();
      if(!exactName||!expectedKey)throw new Error('Server-authorized event identity is required');
      const before=await ego.pageInfo(),beforeUrl=new URL(before.url);
      if(!beforeUrl.hostname.toLowerCase().endsWith('cvent.com')||!/\/events2\/eventselection/i.test(beforeUrl.pathname))throw new Error('Authorized event opening requires the authenticated Cvent event inventory');
      await ego.evaluate('window.scrollTo(0,0)');await ego.waitForTimeout(350);
      const candidates=new Map(),passes=[];const maxScrolls=Math.max(1,Math.min(Number(params.maxScrolls??30),60));
      for(let i=0;i<maxScrolls;i++){
        const view=await ego.evaluate(`(() => {const clean=v=>String(v||'').replace(/\\s+/g,' ').trim().toLowerCase(),found=[];for(const table of document.querySelectorAll('table')){const headers=[...table.querySelectorAll('thead th')],effective=headers.length?headers:[...(table.querySelector('tr')?.querySelectorAll('th')||[])],names=effective.map(cell=>clean(cell.innerText||cell.textContent).replace(/[\\uE000-\\uF8FF]/g,'')),codeIndex=names.findIndex(name=>name==='code'||name==='event code'),statusIndex=names.findIndex(name=>name==='status'||name==='event status');for(const row of table.querySelectorAll('tr')){const box=row.getBoundingClientRect();if(box.bottom<0||box.top>innerHeight)continue;const link=row.querySelector('td a');if(!link)continue;const name=(link.innerText||link.textContent||'').trim();if(name!==${JSON.stringify(exactName)})continue;const cells=[...row.querySelectorAll('td')].map(cell=>(cell.innerText||cell.textContent||'').trim()),rect=link.getBoundingClientRect(),x=Math.max(0,Math.min(innerWidth-1,rect.left+rect.width/2)),y=Math.max(0,Math.min(innerHeight-1,rect.top+rect.height/2)),cover=document.elementFromPoint(x,y);found.push({name,code:codeIndex>=0?cells[codeIndex]||'':'',status:statusIndex>=0?cells[statusIndex]||'':'',inventoryColumnsTrusted:codeIndex>=0&&statusIndex>=0,href:link.href||'',tag:link.tagName,connected:link.isConnected,visible:rect.width>0&&rect.height>0&&rect.bottom>=0&&rect.top<=innerHeight,pointerEvents:getComputedStyle(link).pointerEvents,coveredBy:cover?cover.tagName:null,linkContainsCover:Boolean(cover&&(cover===link||link.contains(cover))),bounds:{left:Math.round(rect.left),top:Math.round(rect.top),width:Math.round(rect.width),height:Math.round(rect.height)}})}}return {y:scrollY,height:innerHeight,scrollHeight:document.documentElement.scrollHeight,found}})()`);
        passes.push({y:view.y,matches:view.found.length});for(const item of view.found)candidates.set(item.href,item);
        if(view.found.length||view.y+view.height>=view.scrollHeight-2)break;
        await ego.evaluate('window.scrollBy(0,Math.max(500,Math.round(innerHeight*.8)))');await ego.waitForTimeout(500);
      }
      const authorized=[...candidates.values()].filter(item=>{try{const url=new URL(item.href);const query=new URLSearchParams(url.search);const key=(query.get('evtstub')||query.get('eventid')||query.get('event')||'').toLowerCase();return item.name===exactName&&item.inventoryColumnsTrusted&&item.status&&item.connected&&item.visible&&key===expectedKey&&url.hostname.toLowerCase().endsWith('cvent.com')}catch{return false}});
      if(authorized.length!==1)throw new Error(`Visible exact authorized event navigation target count was ${authorized.length}, expected 1`);
      const chosen=authorized[0],timeout=Math.max(1000,Math.min(Number(params.timeoutSeconds??60),180)*1000);
      await ego.goto(chosen.href,{waitUntil:'domcontentloaded',timeout});
      const afterPage=await ego.pageInfo(),afterUrl=new URL(afterPage.url),afterQuery=new URLSearchParams(afterUrl.search),afterKey=(afterQuery.get('evtstub')||afterQuery.get('eventid')||afterQuery.get('event')||'').toLowerCase();
      if(!afterUrl.hostname.toLowerCase().endsWith('cvent.com')||afterKey!==expectedKey||/\/events2\/eventselection/i.test(afterUrl.pathname))throw new Error('Bounded event navigation did not enter the exact authorized event');
      // Do not request a full AX tree while the modern event shell is still
      // loading hundreds of chunks. That added no identity evidence and could
      // crash Chromium before target authorization. The next domain observation
      // takes one native snapshot after the landing page has settled.
      await ego.waitForTimeout(1000);
      const landing=await ego.evaluate(`(() => ({ready:document.readyState,title:document.title,headings:[...document.querySelectorAll('h1,h2,h3,[role=heading]')].map(element=>String(element.innerText||element.textContent||'').replace(/\\s+/g,' ').trim()).filter(Boolean).slice(0,20)}))()`);
      result={openedEventKey:expectedKey,activation:'exact-visible-inventory-href',inventoryUrl:before.url,navigationTarget:{name:chosen.name,code:chosen.code,status:chosen.status,href:chosen.href,diagnostics:chosen,passes},landing};break;
    }
    case 'script': {
      // The same Ego executor and target/lease checks, now with coherent native
      // helper scripts. No shell, network, process, filesystem or raw CDP API is exposed.
      const logs=[];
      const validation=JSON.parse(fs.readFileSync(path.join(path.dirname(runtimePath),'rr-validation.json'),'utf8'));
      const verified=new Set(validation.items.filter(item=>item.domain===params.domain&&item.status==='VERIFIED').map(item=>`${item.sourceEvidence.sheet}!${item.sourceEvidence.range}`));
      const target=value=>typeof value==='string'?value.replace(/^loc=role:/,'role:').replace(/^loc=css:/,''):value;
      const readOps=new Set(['pageInfo','snapshotText','screenshot','readTarget','scroll','wait','navigate','hover']);
      const run=async(op,args={},options={})=>{
        if(completedActions.length>=200)throw Error('Ego round exceeded 200 actions; continue in another coherent round');
        actionIndex=completedActions.length;
        let intent=readOps.has(op)?'read':params.intent;
        if(options.intent==='read')intent='read';
        const source=options.rrSource??(params.rrSources.length===1?params.rrSources[0]:undefined);
        if(intent==='read'&&(['fill','typeText','selectOption','setChecked','visualDrag','drag'].includes(op)||op==='press'&&!['Escape','Tab','PageUp','PageDown'].includes(args.key)))throw Error('Read-only Ego action cannot edit/commit controls');
        if(op==='navigate'&&dirty)throw Error('Save and verify current changes before navigation');
        await assertLease();await assertAuthorizedPage();
        if((await ego.evaluate("window.__CVENT_BROWSER_RUNTIME_ID || window.name"))!==runtime.browserRuntimeId)throw Error('Runtime identity lost during Ego round');
        let isSave=false;
        if(['click','visualClick'].includes(op)){
          const d=op==='click'?(await resolveTarget({target:args.target})).descriptor:await pointDescriptor(args.x,args.y);
          isSave=['text','label','aria','title'].some(key=>/^save(?:\s|$)/i.test(normalize(d?.[key])));
          if(['text','label','aria','title'].some(key=>/^edit$/i.test(normalize(d?.[key]))))intent='read';
        }
        if(intent==='write'&&(!source||!verified.has(source)||!params.rrSources.includes(source)))throw Error('Item held: this action needs an exact VERIFIED rrSource from the round header');
        if(op==='screenshot')args.filePath=path.join(path.dirname(runtimePath),`browser-visual-${Date.now()}-${actionIndex}.png`);
        const step={operation:op,...args,intent,rrSource:source};
        const started=performance.now(),before=writesAttempted;
        if(intent==='write')dirty=true; // contain a dispatched failure, too
        const value=await runAdaptive(step);
        if(writesAttempted>before){dirty=true;saved=isSave||params.commitMode==='autosave';}
        if(isSave){saves++;saved=true;}
        if(dirty&&saved&&['snapshotText','readTarget','screenshot'].includes(op)){readbacks++;dirty=false;saved=false;}
        completedActions.push({index:actionIndex,operation:op,intent,rrSource:source,durationMs:Math.round(performance.now()-started),result:op==='snapshotText'?{snapshotCaptured:true,bytes:Buffer.byteLength(value.snapshot)}:value});
        return value;
      };
      const point=(value)=>Array.isArray(value)?{x:value[0],y:value[1]}:{x:value.x,y:value.y};
      const context=vm.createContext({
        cliLog:value=>logs.push(value),
        useOrCreateTaskSpace:async()=>({id:runtime.browserRuntimeId}),
        pageInfo:async()=> (await run('pageInfo')).page,
        snapshotText:async()=> (await run('snapshotText')).snapshot,
        captureScreenshot:async()=> (await run('screenshot')).screenshotPath,
        readTarget:async value=>run('readTarget',{target:target(value)}),
        gotoAndWait:async url=>run('navigate',{url}),
        openOrReuseTab:async url=>run('navigate',{url}),
        click:async(value,options={})=>typeof value==='string'?run('click',{target:target(value)},options):run('visualClick',point(value),options),
        doubleClick:async(value,options={})=>run('visualDoubleClick',point(value),options),
        fillInput:async(value,text,options={})=>run('fill',{target:target(value),text},options),
        typeText:async(text,options={})=>run('typeText',{text},options),
        pressKey:async(key,options={})=>run('press',{key,target:options.target?target(options.target):undefined},options),
        selectOption:async(value,option,options={})=>run('selectOption',{target:target(value),option,optionBy:options.optionBy},options),
        setChecked:async(value,checked,options={})=>run('setChecked',{target:target(value),checked},options),
        hover:async value=>run('hover',{target:target(value)}),
        scrollBy:async dy=>run('scroll',{deltaY:dy}),
        scroll:async({dy})=>run('scroll',{deltaY:dy}),
        wait:async seconds=>run('wait',{ms:Math.max(50,Math.min(seconds*1000,30000))}),
        waitForElement:async value=>run('wait',{target:target(value),ms:30000}),
        dragMouse:async(points,options={})=>run('visualDrag',{...point(points[0]),toX:point(points[1]).x,toY:point(points[1]).y},options),
      },{codeGeneration:{strings:false,wasm:false}});
      await new vm.Script(`(async()=>{${params.script}\n})()`).runInContext(context,{timeout:10000});
      if(dirty)throw Error('Ego round ended with changes lacking Save and fresh readback');
      result={actions:completedActions,actionCount:completedActions.length,writesAttempted,saves,readbacks,logs,unresolvedWrites:false};break;
    }
    case 'actions': {
      const actions=completedActions;
      for(let index=0;index<params.steps.length;index++){
        actionIndex=index;
        const step=params.steps[index],started=performance.now();
        const actionResult=await runAdaptive(step);
        actions.push({index,operation:step.operation,intent:step.intent,durationMs:Math.round((performance.now()-started)*10)/10,result:actionResult});
      }
      result={objective:params.objective,commitMode:params.commitMode,actions,writesAttempted,actionCount:actions.length};break;
    }
    case 'screenshot': result={screenshotPath:await ego.screenshot({path:params.filePath,fullPage:params.fullPage===true})};break;
    case 'visualClick': await authorizeInteractive(params,await pointDescriptor(params.x,params.y));result={result:await ego.click([params.x,params.y],{label:params.label})};break;
    case 'visualDoubleClick': await authorizeInteractive(params,await pointDescriptor(params.x,params.y));result={result:await ego.dblclick([params.x,params.y],{label:params.label})};break;
    case 'click': result={result:await ego.click(params.target)};break;
    case 'activate': result={result:await ego.evaluateLocator(params.target,(element)=>{if(!(element instanceof HTMLElement))throw new Error('activate target must be an HTML element');element.click();return true})};break;
    case 'fill': result={result:await ego.fill(params.target,params.text??'')};break;
    case 'type': await ego.focus(params.target);result={result:await ego.insertText(params.text??'')};break;
    case 'typeText': if(params.intent==='write'){await assertLease();await assertAuthorizedPage();writesAttempted++}result={result:await ego.insertText(params.text??'')};break;
    case 'hover': result={result:await ego.hover(params.target)};break;
    case 'selectOption': {
      const descriptor=await ego.evaluateLocator(params.target,(element)=>({tag:element.tagName,role:element.getAttribute('role')||''}));
      if(descriptor.tag==='SELECT')result={selected:await ego.selectOption(params.target,{[params.optionBy==='value'?'value':'label']:params.option}),controlKind:'native'};
      else{
        if(params.optionBy==='value')throw new Error('Custom Cvent combobox options must be selected by exact label');
        await ego.click(params.target);await ego.waitForTimeout(250);
        const selected=await ego.evaluate(`(() => {const wanted=${JSON.stringify(String(params.option??''))},normalize=value=>String(value||'').replace(/\\s+/g,' ').trim(),roots=[document],matches=[];for(let i=0;i<roots.length;i++){for(const element of roots[i].querySelectorAll('*')){if(element.shadowRoot)roots.push(element.shadowRoot);if(!element.matches('[role="option"],li,[data-cvent-id*="option"],[data-testid*="option"]'))continue;const rect=element.getBoundingClientRect(),style=getComputedStyle(element);if(normalize(element.innerText||element.textContent)===normalize(wanted)&&element.isConnected&&rect.width>0&&rect.height>0&&style.display!=='none'&&style.visibility!=='hidden')matches.push(element)}}if(matches.length!==1)return {count:matches.length};matches[0].click();return {count:1,text:normalize(matches[0].innerText||matches[0].textContent)}})()`);
        if(selected.count!==1)throw new Error(`Custom Cvent combobox found ${selected.count} exact option-label matches`);
        result={selected:selected.text,controlKind:'custom'};
      }
      break;
    }
    case 'inspectRegistrationTypeCapabilities': result=await inspectRegistrationTypeCapabilities(ego,runtime,params);break;
    case 'configureAdmissionItems':
    case 'configureRegistrationTypes': result=await runTrustedCventProcedure(ego,runtime,operation,params);break;
    case 'setChecked': result={result:await ego.setChecked(params.target,Boolean(params.checked)),checked:Boolean(params.checked)};break;
    case 'press': await ego.focus(params.target);await ego.press(params.key);result={pressed:params.key};break;
    case 'search': {
      const descriptor=await ego.evaluateLocator(params.target,(element)=>({
        tag:element.tagName,type:element.getAttribute('type')||'',role:element.getAttribute('role')||'',
        name:element.getAttribute('name')||'',placeholder:element.getAttribute('placeholder')||'',
        aria:element.getAttribute('aria-label')||'',
      }));
      const searchable=descriptor.tag==='INPUT'&&(/search/i.test(`${descriptor.type} ${descriptor.role} ${descriptor.name} ${descriptor.placeholder} ${descriptor.aria}`));
      if(!searchable)throw new Error('search target is not an identified search/filter input');
      await ego.fill(params.target,params.text??'');if(params.submit!==false)await ego.press('Enter');
      result={query:params.text??'',submitted:params.submit!==false};break;
    }
    case 'selectText': result={selected:await ego.evaluateLocator(params.target,(element)=>{const range=document.createRange();range.selectNodeContents(element);const selection=getSelection();selection.removeAllRanges();selection.addRange(range);element.closest('[contenteditable=true]')?.focus();return selection.toString()})};break;
    case 'drag': result={result:await ego.drag([params.target,params.destination],{delay:75})};break;
    case 'visualDrag': await authorizeInteractive(params,await pointDescriptor(params.x,params.y));result={result:await ego.drag([[params.x,params.y],[params.toX,params.toY]],{delay:75,label:params.label})};break;
    case 'uploadDiscountImport': await ego.setInputFiles(params.target,params.filePath);result={uploadedArtifact:'discount-import.xlsx'};break;
    case 'navigate': result={result:await ego.goto(params.url,{waitUntil:params.waitUntil||'domcontentloaded',timeout:Math.max(1000,Math.min(Number(params.timeoutSeconds??30),180)*1000)})};break;
    case 'wait': {
      let ready=true;
      if(params.target)ready=await ego.waitForSelector(params.target,{timeout:params.ms??30000});
      else if(params.loadState)ready=await ego.waitForLoadState(params.loadState,{timeout:params.ms??30000});
      else await ego.waitForTimeout(params.ms??params.timeout??1000);
      result={waitedMs:params.ms??params.timeout??1000,ready};break;
    }
    default:throw new Error('Unsupported Ego operation: '+operation);
  }
  const after=await ego.evaluate("window.__CVENT_BROWSER_RUNTIME_ID || (window.name.startsWith('cvent-runtime-') ? window.name : null)");
  if(after!==runtime.browserRuntimeId)throw new Error('Runtime marker changed after Ego action');
  const page=await ego.pageInfo();
  await output({marker:after,targetId:wanted,observedAt:new Date().toISOString(),page,...result});process.exit(0);
}catch(e){await output({error:e?.stack||e?.message||String(e),actionIndex,writesAttempted,completedActions,...(operation==='script'?{saves,readbacks,unresolvedWrites:dirty||writesAttempted>0}: {})},false);process.exit(1)}
