#!/usr/bin/env node
/** Ego direct-tool adapter pinned to the canonical Steel Chromium target. */
import fs from 'node:fs';
import path from 'node:path';
import { inspectRegistrationTypeCapabilities, runTrustedCventProcedure } from './trusted_cvent_procedures.mjs';
const argv=process.argv.slice(2);const arg=n=>argv[argv.indexOf(n)+1];
const runtimePath=arg('--runtime');const operation=arg('--operation');const params=JSON.parse(arg('--params')||'{}');
function output(value,ok=true){return new Promise((resolve,reject)=>{process.stdout.write('BROWSER_TOOL_RESULT='+JSON.stringify(ok?{ok:true,tool:'ego',operation,...value}:{ok:false,tool:'ego',operation,error:String(value)})+'\n',error=>error?reject(error):resolve())})}
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
if(snapshotCachePath&&['click','activate','fill','type','navigate','selectOption','setChecked','press','drag','uploadDiscountImport','recover','openAuthorizedEvent','inspectRegistrationTypeCapabilities','configureAdmissionItems','configureRegistrationTypes'].includes(operation)){try{fs.unlinkSync(snapshotCachePath)}catch(error){if(error?.code!=='ENOENT')throw error}}
if(!runtimePath||!operation){await output('Explicit --runtime and --operation are required',false);process.exit(2)}
const runtime=JSON.parse(fs.readFileSync(runtimePath,'utf8'));
const cdpOrigin=new URL(runtime.cdpHttpOrigin);process.env.EGO_BROWSER_CDP_HOST=cdpOrigin.hostname;process.env.EGO_BROWSER_CDP_PORT=cdpOrigin.port;
try{
  const ego=await import('./vendor/ego-browser-linux/dist/src/helpers.js');
  const tabs=await ego.listTabs();
  const wanted=runtime.targetBrowserIdentity.targetId;
  const tab=tabs.find(t=>(t.targetId||t.id)===wanted);
  if(!tab)throw new Error('Canonical BrowserRuntime target is not available');
  await ego.switchTab(wanted);
  const marker=await ego.evaluate("window.__CVENT_BROWSER_RUNTIME_ID || (window.name.startsWith('cvent-runtime-') ? window.name : null)");
  if(marker!==runtime.browserRuntimeId)throw new Error('Ego marker mismatch — cross-browser routing blocked');
  let result;
  switch(operation){
    case '__preflightTarget': {
      let resolvedTarget=params.target,descriptor,fallbackUsed=false;
      try{
        descriptor=await ego.evaluateLocator(params.target,(element)=>{const id=element.id,label=id?document.querySelector('label[for="'+CSS.escape(id)+'"]'):element.closest('label');return {tag:element.tagName,role:element.getAttribute('role'),text:(element.innerText||element.textContent||'').trim().slice(0,500),label:(label?.innerText||label?.textContent||'').trim().slice(0,500),aria:element.getAttribute('aria-label'),title:element.getAttribute('title'),name:element.getAttribute('name'),href:element instanceof HTMLAnchorElement?element.href:null,disabled:'disabled' in element?Boolean(element.disabled):false,connected:element.isConnected}});
      }catch(originalError){
        const requested=roleRequest(params.target);if(!requested)throw originalError;
        const token=`cvent-agent-target-${Date.now()}-${Math.random().toString(16).slice(2)}`;
        const fallback=await ego.evaluate(`(() => {const requested=${JSON.stringify(requested)},token=${JSON.stringify(token)},context=${JSON.stringify(String(params.context||''))},index=${JSON.stringify(Number.isInteger(params.index)?params.index:null)},normalize=value=>String(value||'').toLowerCase().replace(/[\\s:*]+/g,' ').trim(),implicitRole=element=>{const tag=element.tagName;const type=(element.getAttribute('type')||'').toLowerCase();if(tag==='SELECT')return 'combobox';if(tag==='TEXTAREA')return 'textbox';if(tag==='INPUT')return ['checkbox','radio','button','submit'].includes(type)?type:(type==='search'?'searchbox':'textbox');if(tag==='BUTTON')return 'button';if(tag==='A'&&element.hasAttribute('href'))return 'link';return ''},roots=[document],elements=[];for(let i=0;i<roots.length;i++){const root=roots[i];for(const element of root.querySelectorAll('*')){if(element.shadowRoot)roots.push(element.shadowRoot);const role=(element.getAttribute('role')||implicitRole(element)).toLowerCase();if(role!==requested.role||!element.isConnected)continue;const id=element.id,label=id?document.querySelector('label[for="'+CSS.escape(id)+'"]'):null,groupLabel=element.closest('label')||element.parentElement?.querySelector(':scope > label'),names=[element.getAttribute('aria-label'),element.getAttribute('title'),element.getAttribute('name'),label?.innerText,groupLabel?.innerText].filter(Boolean).map(normalize);if(!names.includes(normalize(requested.name)))continue;if(context){let ancestor=element.parentElement,matched=false;for(let depth=0;ancestor&&depth<10;depth++,ancestor=ancestor.parentElement){if(normalize(ancestor.innerText||ancestor.textContent).includes(normalize(context))){matched=true;break}}if(!matched)continue}const rect=element.getBoundingClientRect(),style=getComputedStyle(element);if(rect.width<=0||rect.height<=0||style.visibility==='hidden'||style.display==='none'||('disabled' in element&&element.disabled))continue;elements.push(element)}}const candidates=index!==null&&index>=0&&index<elements.length?[elements[index]]:elements;if(candidates.length!==1)return {count:candidates.length,available:elements.length};const element=candidates[0],id=element.id,label=id?document.querySelector('label[for="'+CSS.escape(id)+'"]'):null,groupLabel=element.closest('label')||element.parentElement?.querySelector(':scope > label');element.setAttribute('data-cvent-agent-target',token);return {count:1,descriptor:{tag:element.tagName,role:element.getAttribute('role')||implicitRole(element),text:(element.innerText||element.textContent||'').trim().slice(0,500),label:(label?.innerText||groupLabel?.innerText||'').trim().slice(0,500),aria:element.getAttribute('aria-label'),title:element.getAttribute('title'),name:element.getAttribute('name'),href:element instanceof HTMLAnchorElement?element.href:null,disabled:'disabled' in element?Boolean(element.disabled):false,connected:element.isConnected}}})()`);
        if(fallback.count!==1)throw new Error(`Write target preflight found ${fallback.count} exact accessible-name matches after the original locator failed`);
        resolvedTarget=`[data-cvent-agent-target="${token}"]`;descriptor=fallback.descriptor;fallbackUsed=true;
      }
      result={resolved:descriptor,resolvedTarget,fallbackUsed};break;
    }
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
      const locator=ego.locator(params.target);
      const optional=async(fn)=>{try{return await fn()}catch{return null}};
      result={target:params.target,text:await optional(()=>locator.innerText()),value:await optional(()=>locator.inputValue()),checked:await optional(()=>locator.isChecked()),enabled:await optional(()=>locator.isEnabled()),visible:await optional(()=>locator.isVisible())};
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
      const inventory=await ego.evaluate(`(() => {const controls=[],seen=new Set();const walk=(root,path)=>{for(const element of root.querySelectorAll('*')){if(element.shadowRoot)walk(element.shadowRoot,path+' > '+element.tagName.toLowerCase()+(element.id?'#'+element.id:''));if(!element.matches('a,button,input,select,textarea,[role],[contenteditable=true]')||seen.has(element))continue;seen.add(element);const type=(element.getAttribute('type')||'').toLowerCase();controls.push({path,tag:element.tagName,role:element.getAttribute('role'),text:(element.innerText||element.textContent||'').trim().slice(0,500),id:element.id||null,name:element.getAttribute('name'),aria:element.getAttribute('aria-label'),title:element.getAttribute('title'),testId:element.getAttribute('data-cvent-id')||element.getAttribute('data-testid'),href:element instanceof HTMLAnchorElement?element.href:null,type:type||null,value:type==='password'?null:('value' in element?String(element.value).slice(0,500):null),checked:'checked' in element?Boolean(element.checked):null,disabled:'disabled' in element?Boolean(element.disabled):null})}};walk(document,'document');return {url:location.href,title:document.title,controls}})()`);
      result={snapshotKind:'controlInventory',snapshot:JSON.stringify(inventory,null,2)};break;
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
        const view=await ego.evaluate(`(() => { const rows=[...document.querySelectorAll('table tr')].map(row=>{const r=row.getBoundingClientRect();if(r.bottom<0||r.top>innerHeight)return null;const cells=[...row.querySelectorAll('td')].map(x=>(x.innerText||'').trim());const link=row.querySelector('td a');return link&&cells.length?{name:(link.innerText||'').trim(),code:cells[1]||'',status:cells[2]||'',href:link.href||'',top:Math.round(r.top)}:null}).filter(Boolean);return {y:scrollY,height:innerHeight,scrollHeight:document.documentElement.scrollHeight,rows} })()`);
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
        const view=await ego.evaluate(`(() => {const found=[];for(const row of document.querySelectorAll('table tr')){const box=row.getBoundingClientRect();if(box.bottom<0||box.top>innerHeight)continue;const link=row.querySelector('td a');if(!link)continue;const name=(link.innerText||link.textContent||'').trim();if(name!==${JSON.stringify(exactName)})continue;const rect=link.getBoundingClientRect(),x=Math.max(0,Math.min(innerWidth-1,rect.left+rect.width/2)),y=Math.max(0,Math.min(innerHeight-1,rect.top+rect.height/2)),cover=document.elementFromPoint(x,y);found.push({name,href:link.href||'',tag:link.tagName,connected:link.isConnected,visible:rect.width>0&&rect.height>0&&rect.bottom>=0&&rect.top<=innerHeight,pointerEvents:getComputedStyle(link).pointerEvents,coveredBy:cover?cover.tagName:null,linkContainsCover:Boolean(cover&&(cover===link||link.contains(cover))),bounds:{left:Math.round(rect.left),top:Math.round(rect.top),width:Math.round(rect.width),height:Math.round(rect.height)}})}return {y:scrollY,height:innerHeight,scrollHeight:document.documentElement.scrollHeight,found}})()`);
        passes.push({y:view.y,matches:view.found.length});for(const item of view.found)candidates.set(item.href,item);
        if(view.found.length||view.y+view.height>=view.scrollHeight-2)break;
        await ego.evaluate('window.scrollBy(0,Math.max(500,Math.round(innerHeight*.8)))');await ego.waitForTimeout(500);
      }
      const authorized=[...candidates.values()].filter(item=>{try{const url=new URL(item.href);const query=new URLSearchParams(url.search);const key=(query.get('evtstub')||query.get('eventid')||query.get('event')||'').toLowerCase();return item.name===exactName&&item.connected&&item.visible&&key===expectedKey&&url.hostname.toLowerCase().endsWith('cvent.com')}catch{return false}});
      if(authorized.length!==1)throw new Error(`Visible exact authorized event navigation target count was ${authorized.length}, expected 1`);
      const chosen=authorized[0],timeout=Math.max(1000,Math.min(Number(params.timeoutSeconds??60),180)*1000);
      await ego.goto(chosen.href,{waitUntil:'domcontentloaded',timeout});
      const afterPage=await ego.pageInfo(),afterUrl=new URL(afterPage.url),afterQuery=new URLSearchParams(afterUrl.search),afterKey=(afterQuery.get('evtstub')||afterQuery.get('eventid')||afterQuery.get('event')||'').toLowerCase();
      if(!afterUrl.hostname.toLowerCase().endsWith('cvent.com')||afterKey!==expectedKey||/\/events2\/eventselection/i.test(afterUrl.pathname))throw new Error('Bounded event navigation did not enter the exact authorized event');
      const snapshot=await ego.snapshot();
      result={openedEventKey:expectedKey,activation:'exact-visible-inventory-href',inventoryUrl:before.url,navigationTarget:{name:chosen.name,href:chosen.href,diagnostics:chosen,passes},snapshot};break;
    }
    case 'click': result={result:await ego.click(params.target)};break;
    case 'activate': result={result:await ego.evaluateLocator(params.target,(element)=>{if(!(element instanceof HTMLElement))throw new Error('activate target must be an HTML element');element.click();return true})};break;
    case 'fill': result={result:await ego.fill(params.target,params.text??'')};break;
    case 'type': await ego.focus(params.target);result={result:await ego.insertText(params.text??'')};break;
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
}catch(e){await output(e?.stack||e?.message||String(e),false);process.exit(1)}
