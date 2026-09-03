#!/usr/bin/env node
/** Empirical complete-snapshot transport acceptance using an archived real Cvent page. */
import { copyFile, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { createHash, randomUUID } from 'node:crypto';
import { dirname, join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { mkdtemp } from 'node:fs/promises';

const root=resolve(dirname(new URL(import.meta.url).pathname),'..');
const source=join(root,'data/runs/20260903-062426/snapshots/discount-filter-PPCTESTFREE-3.txt');
const extensionSource=join(root,'extensions/cvent-job-tools.ts');
const extensionHarness=join(root,'extensions',`.capability-harness-${process.pid}.mts`);
const temp=await mkdtemp(join(root,'data','capability-acceptance-'));
const jobDir=join(temp,'workspace-a','job-a');
await mkdir(jobDir,{recursive:true});
Object.assign(process.env,{
  CVENT_JOB_DIR:jobDir,CVENT_REPO_ROOT:root,CVENT_JOB_ID:'job-a',CVENT_WORKSPACE_ID:'workspace-a',
  CVENT_WORKER_SLOT:'2',CVENT_AUTHORIZED_EVENT_NAME:'Synthetic Event A',CVENT_AUTHORIZED_EVENT_ID:'event-a',
  CVENT_AUTHORIZED_EVENT_KEY:'event-a',CVENT_LEASE_VALIDATE_URL:'http://127.0.0.1:1',CVENT_LEASE_TOKEN:'synthetic-token',
});
const runtime={browserRuntimeId:'runtime-worker-2',targetBrowserIdentity:{targetId:'target-worker-2'}};
await writeFile(join(jobDir,'browser-runtime.json'),JSON.stringify(runtime));
await copyFile(extensionSource,extensionHarness);
try{
  const mod=await import(pathToFileURL(extensionHarness).href+`?v=${Date.now()}`);
  const tools=[];
  mod.default({on(){},setActiveTools(){},registerTool(tool){tools.push(tool)}});
  const byName=Object.fromEntries(tools.map(tool=>[tool.name,tool]));
  const archived=await readFile(source,'utf8');
  // Make the real Cvent snapshot substantially larger and Unicode-heavy while preserving exact content.
  const large=[archived,'\n<!-- deterministic boundary 😀 -->\n',archived,'\n',archived].join('');
  const started=performance.now();
  const result=await mod.__capabilityTest.saveLargeSnapshot({
    snapshot:large,browserRuntimeId:runtime.browserRuntimeId,marker:runtime.browserRuntimeId,
    targetId:runtime.targetBrowserIdentity.targetId,observedAt:new Date().toISOString(),
    page:{url:'https://app.cvent.com/events/synthetic?evtstub=event-a',title:'Cvent Discounts'},
  });
  const creationMs=performance.now()-started;
  const first=result.completeSnapshot;
  const pieces=[first.chunkText];
  const chunkLatencies=[];
  let orderingRejected=false;
  try{await byName.cvent_snapshot_chunk.execute('order',{snapshotId:first.snapshotId,chunkIndex:2});}
  catch{orderingRejected=true;}
  for(let index=1;index<first.totalChunks;index++){
    const before=performance.now();
    const reply=await byName.cvent_snapshot_chunk.execute(`chunk-${index}`,{snapshotId:first.snapshotId,chunkIndex:index});
    chunkLatencies.push(performance.now()-before);
    pieces.push(JSON.parse(reply.content[0].text).chunkText);
  }
  let duplicateRejected=false;
  try{await byName.cvent_snapshot_chunk.execute('duplicate',{snapshotId:first.snapshotId,chunkIndex:first.totalChunks-1});}
  catch{duplicateRejected=true;}
  const reconstructed=pieces.join('');
  const expectedHash=createHash('sha256').update(Buffer.from(large)).digest('hex');

  const second=await mod.__capabilityTest.saveLargeSnapshot({
    snapshot:large+'tail',browserRuntimeId:runtime.browserRuntimeId,targetId:runtime.targetBrowserIdentity.targetId,
    observedAt:new Date().toISOString(),page:{url:'https://app.cvent.com/events/synthetic?evtstub=event-a',title:'Cvent Discounts'},
  });
  await byName.cvent_snapshot_chunk.execute('partial',{snapshotId:second.completeSnapshot.snapshotId,chunkIndex:1});
  let missingTailBlocksBrowser=false;
  try{await byName.cvent_browser.execute('blocked',{operation:'pageInfo',intent:'read'},new AbortController().signal);}
  catch(error){missingTailBlocksBrowser=String(error).includes('not fully consumed');}
  // A changed runtime/target must invalidate delivery before another chunk is returned.
  const changed={browserRuntimeId:'runtime-other-worker',targetBrowserIdentity:{targetId:'target-other'}};
  await writeFile(join(jobDir,'browser-runtime.json'),JSON.stringify(changed));
  let crossBrowserRejected=false;
  try{await byName.cvent_snapshot_chunk.execute('cross',{snapshotId:second.completeSnapshot.snapshotId,chunkIndex:2});}
  catch(error){crossBrowserRejected=String(error).includes('identity mismatch');}

  const evidence={
    schemaVersion:1,recordedAt:new Date().toISOString(),
    scope:'capability and complete-snapshot transport; archived real Cvent DOM, no live Cvent navigation or mutation',
    toolCount:tools.length,tools:tools.map(tool=>tool.name),
    source:{path:'data/runs/20260903-062426/snapshots/discount-filter-PPCTESTFREE-3.txt',archivedBytes:Buffer.byteLength(archived),largeBytes:Buffer.byteLength(large)},
    transport:{
      chunks:first.totalChunks,chunkBytesMaximum:36*1024,declaredBytes:first.bytes,
      declaredSha256:first.sha256,expectedSha256:expectedHash,reconstructedSha256:createHash('sha256').update(Buffer.from(reconstructed)).digest('hex'),
      exactReconstruction:reconstructed===large,orderingRejected,duplicateRejected,missingTailBlocksBrowser,crossBrowserRejected,
      workerSlot:first.workerSlot,browserRuntimeId:first.browserRuntimeId,targetId:first.targetId,jobId:first.jobId,workspaceId:first.workspaceId,
    },
    performance:{creationMilliseconds:Number(creationMs.toFixed(3)),chunkReadMilliseconds:chunkLatencies.map(v=>Number(v.toFixed(3))),totalChunkReadMilliseconds:Number(chunkLatencies.reduce((a,b)=>a+b,0).toFixed(3))},
  };
  evidence.passed=evidence.toolCount===10&&evidence.transport.exactReconstruction&&orderingRejected&&duplicateRejected&&missingTailBlocksBrowser&&crossBrowserRejected;
  process.stdout.write(JSON.stringify(evidence,null,2)+'\n');
  if(!evidence.passed)process.exitCode=1;
}finally{
  await rm(extensionHarness,{force:true});
  await rm(temp,{recursive:true,force:true});
}
