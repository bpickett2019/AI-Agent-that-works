#!/usr/bin/env node
/** Ego direct-tool adapter pinned to the canonical Steel Chromium target. */
import fs from 'node:fs';
const argv=process.argv.slice(2);const arg=n=>argv[argv.indexOf(n)+1];
const runtimePath=arg('--runtime');const operation=arg('--operation');const params=JSON.parse(arg('--params')||'{}');
function output(value,ok=true){process.stdout.write('BROWSER_TOOL_RESULT='+JSON.stringify(ok?{ok:true,tool:'ego',operation,...value}:{ok:false,tool:'ego',operation,error:String(value)})+'\n')}
if(!runtimePath||!operation){output('Explicit --runtime and --operation are required',false);process.exit(2)}
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
    case 'probe': {const info=await ego.pageInfo();result={marker,targetId:wanted,url:info.url,title:info.title};break}
    case 'snapshotText': result={snapshot:await ego.snapshot()};break;
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
      const exactName=String(params.eventName||''),expectedKey=String(params.eventKey||'').toLowerCase();
      if(!exactName||!expectedKey)throw new Error('Server-authorized event identity is required');
      const matches=await ego.evaluate(`(() => [...document.querySelectorAll('a')].filter(a=>(a.textContent||'').trim()===${JSON.stringify(exactName)}).map(a=>a.href).filter(Boolean))()`);
      const authorized=[...new Set(matches)].filter(href=>{try{const url=new URL(href);const query=new URLSearchParams(url.search);const key=(query.get('evtstub')||query.get('eventid')||query.get('event')||'').toLowerCase();return key===expectedKey&&url.hostname.toLowerCase().endsWith('cvent.com')}catch{return false}});
      if(authorized.length!==1)throw new Error(`Exact authorized event link count was ${authorized.length}, expected 1`);
      result={openedEventKey:expectedKey,result:await ego.goto(authorized[0],{waitUntil:'domcontentloaded',timeout:Math.max(1000,Math.min(Number(params.timeoutSeconds??60),180)*1000)})};break;
    }
    case 'click': result={result:await ego.click(params.target)};break;
    case 'activate': result={result:await ego.evaluateLocator(params.target,(element)=>{if(!(element instanceof HTMLElement))throw new Error('activate target must be an HTML element');element.click();return true})};break;
    case 'fill': result={result:await ego.fill(params.target,params.text??'')};break;
    case 'type': await ego.focus(params.target);result={result:await ego.insertText(params.text??'')};break;
    case 'hover': result={result:await ego.hover(params.target)};break;
    case 'selectOption': result={selected:await ego.selectOption(params.target,{[params.optionBy==='value'?'value':'label']:params.option})};break;
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
  output({marker:after,targetId:wanted,observedAt:new Date().toISOString(),page,...result});process.exit(0);
}catch(e){output(e?.stack||e?.message||String(e),false);process.exit(1)}
