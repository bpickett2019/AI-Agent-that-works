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
    case 'click': result={result:await ego.click(params.target)};break;
    case 'fill': result={result:await ego.fill(params.target,params.text??'')};break;
    case 'type': await ego.focus(params.target);result={result:await ego.insertText(params.text??'')};break;
    case 'navigate': result={result:await ego.goto(params.url,{waitUntil:params.waitUntil||'domcontentloaded',timeout:params.timeout||30000})};break;
    case 'js': result={value:await ego.evaluate(params.expression)};break;
    case 'cdp': result={value:await ego.cdp(params.method,params.params||{})};break;
    case 'wait': await ego.waitForTimeout(params.ms??params.timeout??1000);result={waitedMs:params.ms??params.timeout??1000};break;
    case 'tabs': result={tabs:await ego.listTabs()};break;
    case 'switchTab': if(params.targetId!==wanted)throw new Error('Cannot switch away from canonical runtime target');result={tab:await ego.switchTab(wanted)};break;
    default:throw new Error('Unsupported Ego operation: '+operation);
  }
  const after=await ego.evaluate("window.__CVENT_BROWSER_RUNTIME_ID || (window.name.startsWith('cvent-runtime-') ? window.name : null)");
  if(after!==runtime.browserRuntimeId)throw new Error('Runtime marker changed after Ego action');
  output({marker:after,targetId:wanted,...result});process.exit(0);
}catch(e){output(e?.stack||e?.message||String(e),false);process.exit(1)}
