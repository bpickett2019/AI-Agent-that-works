import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire, stripTypeScriptTypes } from 'node:module';
import { pathToFileURL } from 'node:url';
const root=process.cwd(), directory=fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()),'simple-offline-'));
try {
  const helperRoot=path.join(directory,'helper');fs.mkdirSync(helperRoot);
  Object.assign(process.env,{CVENT_EXECUTION_MODE:'simple',CVENT_JOB_DIR:directory,CVENT_REPO_ROOT:helperRoot,
    CVENT_AUTHORIZED_EVENT_ID:'event',CVENT_AUTHORIZED_EVENT_KEY:'event',CVENT_AUTHORIZED_EVENT_NAME:'Event',
    CVENT_LEASE_VALIDATE_URL:'http://unused.invalid',CVENT_LEASE_TOKEN:'offline',CVENT_WORKER_SLOT:'1'});
  const save=(name,value)=>fs.writeFileSync(path.join(directory,name),JSON.stringify(value));
  const load=name=>JSON.parse(fs.readFileSync(path.join(directory,name),'utf8'));
  save('browser-runtime.json',{browserRuntimeId:'runtime',executionMode:'simple'});
  save('state.json',{completed:['first'],pending:['second'],current_stage:'second'});
  save('browser-snapshot-pending.json',{complete:false,nextChunk:99}); // legacy gates must be irrelevant
  save('domain-results.json',{domains:{event_settings:{checkpoint:'COMPLETE'}}});
  const helper=path.join(helperRoot,'browser_tool.py');
  fs.writeFileSync(helper,'print(\'BROWSER_ROUTER_RESULT={"ok":true,"actionCount":10,"writesAttempted":3,"saves":1,"readbacks":1,"logs":["native result"]}\')');
  const require=createRequire(import.meta.url);
  let source=stripTypeScriptTypes(fs.readFileSync(path.join(root,'extensions/cvent-job-tools.ts'),'utf8'));
  source=source.replace('"typebox"',JSON.stringify(pathToFileURL(require.resolve('typebox')).href))
    .replace('"./prewrite-orchestration.mjs"',JSON.stringify(pathToFileURL(path.join(root,'extensions/prewrite-orchestration.mjs')).href))
    .replace('"../ego_round_validation.mjs"',JSON.stringify(pathToFileURL(path.join(root,'ego_round_validation.mjs')).href));
  const extension=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
  const tools=new Map(),hooks=new Map();let active=[];
  extension.default({on:(name,fn)=>hooks.set(name,fn),registerTool:tool=>tools.set(tool.name,tool),setActiveTools:names=>active=names,getActiveTools:()=>active});
  await hooks.get('session_start')();
  assert.deepEqual(active,['read','bash','cvent_open_event','cvent_login_handoff','cvent_job_update','cvent_finish']);
  assert.equal(await hooks.get('context')({messages:[]}),undefined);
  const native={command:"ego-browser nodejs <<'JS'\nconst x='RR intent'; await page.fill('@1',x);\nJS"};
  await tools.get('bash').execute('normal-no-compiler-no-metadata',native);
  assert.equal(load('browser-last-script-result.json').actionCount,10);
  assert.equal(await hooks.get('tool_call')({toolName:'bash',input:native}),undefined);
  await tools.get('cvent_job_update').execute('own-checklist',{stage:'A Pi chosen custom section',completed:['second'],pending:['third'],action:'Continuing'});
  assert.deepEqual(load('state.json').completed,['first','second']);
  assert.equal(load('state.json').current_stage,'A Pi chosen custom section');
  const at='2026-01-01T00:00:00.000Z';
  const attempt={at,operation:'click#one',rrSource:'uploaded RR',eventKey:'event',result:'attempted'};
  fs.writeFileSync(path.join(directory,'scope-write-audit.jsonl'),JSON.stringify(attempt)+'\n');
  save('browser-write-readback-required.json',{executionMode:'simple',browserRuntimeId:'runtime',attempts:[attempt]});
  await assert.rejects(tools.get('cvent_job_update').execute('not-observed',{verification:'Saved'}),/fresh observation/);
  save('browser-last-atomic-readback.json',{executionMode:'simple',browserRuntimeId:'runtime',eventKey:'event',observedAt:'2026-01-01T00:00:01.000Z',evidence:{snapshot:'persisted value'}});
  await tools.get('cvent_job_update').execute('pi-verifies',{verification:'Reopened persisted configuration and the requested value matches.'});
  assert(!fs.existsSync(path.join(directory,'browser-write-readback-required.json')));
  assert(fs.readFileSync(path.join(directory,'scope-write-audit.jsonl'),'utf8').includes('"resolvedBy":"pi"'));
  // Many ordinary browser failures remain tool errors, never a controller terminal.
  fs.writeFileSync(helper,'import sys\nprint(\'BROWSER_ROUTER_RESULT={"ok":false,"error":"stale ref: page changed"}\')\nsys.exit(1)');
  for(let i=0;i<4;i++){
    await assert.rejects(tools.get('bash').execute('recoverable',native),/stale ref/);
    assert.equal(await hooks.get('tool_call')({toolName:'bash',input:native}),undefined);
  }
  assert(!fs.readdirSync(directory).some(n=>n.startsWith('controller-failure')));
  const final={status:'REVIEW_REQUIRED',unresolvedItems:['One RR item ambiguous; independent work completed'],realReads:['Persisted verification'],realWrites:['Changed value'],guardrails:{published:0,emailsSent:0,deletes:0,globalMutations:0}};
  assert.equal((await tools.get('cvent_finish').execute('finish',final)).terminate,true);
  assert.equal(load('final-report.json').status,'REVIEW_REQUIRED');
  assert.equal(load('final-report.json').reported_by,'pi');
  assert.deepEqual(load('state.json').completed,['first','second']);
  console.log('Simple extension: native script, normal errors, own checklist, Pi verification, review completion PASS');
} finally {fs.rmSync(directory,{recursive:true,force:true})}
