#!/usr/bin/env node
/** Deterministic invocation of the production capability extension for acceptance. */
import {copyFile,rm} from 'node:fs/promises';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
const root=process.env.CVENT_REPO_ROOT,job=process.env.CVENT_JOB_DIR;
if(!root||!job)throw new Error('Controlled CVENT environment required');
const source=join(root,'extensions/cvent-job-tools.ts'),copy=join(root,'extensions',`.direct-browser-harness-${process.pid}.mts`);
await copyFile(source,copy);
try{
 const mod=await import(pathToFileURL(copy).href+`?v=${Date.now()}`),tools=[];
 mod.default({on(){},setActiveTools(){},registerTool(tool){tools.push(tool)}});
 const byName=Object.fromEntries(tools.map(tool=>[tool.name,tool])),timings=[],snapshots=[];
 async function browser(params){const start=performance.now();try{const reply=await byName.cvent_browser.execute(crypto.randomUUID(),params,new AbortController().signal);timings.push({operation:params.operation,milliseconds:+(performance.now()-start).toFixed(3),error:false});return JSON.parse(reply.content[0].text)}catch(error){timings.push({operation:params.operation,milliseconds:+(performance.now()-start).toFixed(3),error:true,errorText:String(error).slice(-500)});throw error}}
 async function snapshot(operation='snapshotText'){const result=await browser({operation,intent:'read',timeoutSeconds:90});let text=result.snapshot||'';if(result.completeSnapshot){text=result.completeSnapshot.chunkText;for(let index=1;index<result.completeSnapshot.totalChunks;index++){const start=performance.now();const reply=await byName.cvent_snapshot_chunk.execute(crypto.randomUUID(),{snapshotId:result.completeSnapshot.snapshotId,chunkIndex:index});timings.push({operation:'snapshotChunk',milliseconds:+(performance.now()-start).toFixed(3),error:false});text+=JSON.parse(reply.content[0].text).chunkText}}snapshots.push(text);return text}
 const initial=await snapshot();await browser({operation:'recover',intent:'read',timeoutSeconds:30});const inventory=await snapshot('controlInventory');
 await browser({operation:'fill',intent:'write',scopeIds:['scope-007'],target:'role:textbox[name="Venue Name"]',text:'New Capability Venue'});await snapshot();
 await browser({operation:'selectOption',intent:'write',scopeIds:['scope-009'],target:'#state',option:'Florida',optionBy:'label'});await snapshot();
 await browser({operation:'setChecked',intent:'write',scopeIds:['scope-027'],target:'#browse',checked:true});await snapshot();
 await browser({operation:'search',intent:'read',target:'#search',text:'ROW-0077',submit:true});await snapshot();
 await browser({operation:'activate',intent:'read',target:'#open-modal'});
 await browser({operation:'wait',intent:'read',target:'#dynamic',ms:5000});
 await browser({operation:'click',intent:'read',target:'role:button[name="Dynamic modal control"]'});
 await browser({operation:'press',intent:'read',target:'#close-modal',key:'Escape'});
 await browser({operation:'hover',intent:'read',target:'#hover-zone'});await snapshot();
 await browser({operation:'selectText',intent:'read',target:'#rich-link'});
 await browser({operation:'scroll',intent:'read',deltaY:5000,settleMs:100});
 await browser({operation:'scroll',intent:'read',deltaY:-5000,settleMs:100});
 await browser({operation:'drag',intent:'write',scopeIds:['scope-033'],target:'#drag-source',destination:'#drop'});const final=await snapshot();
 const checks={initialTail:initial.includes('COMPLETE PAGE TAIL SENTINEL'),inventoryComplete:inventory.includes('drag-source')&&inventory.includes('ROW-0079'),venue:final.includes('New Capability Venue'),stateFlorida:/State[\s\S]*Florida/.test(final),browseChecked:final.includes('Browse checked'),searchFound:final.includes('Found ROW-0077'),modalControl:final.includes('Modal opened'),hoverControl:final.includes('Hover revealed'),dragged:final.includes('Dropped Countdown Timer')};
 const evidence={toolCount:tools.length,operations:timings.map(x=>x.operation),timings,checks,snapshotBytes:snapshots.map(x=>Buffer.byteLength(x)),snapshotCount:snapshots.length,chunkCalls:timings.filter(x=>x.operation==='snapshotChunk').length};
 evidence.passed=Object.values(checks).every(Boolean)&&timings.every(x=>!x.error)&&evidence.chunkCalls>0;
 console.log('DIRECT_CAPABILITY_EVIDENCE='+JSON.stringify(evidence));if(!evidence.passed)process.exitCode=1;
}finally{await rm(copy,{force:true})}
