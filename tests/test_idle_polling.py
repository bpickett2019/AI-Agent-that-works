"""Idle pages never poll or trigger model/browser work; active jobs still update."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class IdlePollingTests(unittest.TestCase):
    def test_shipped_polling_lifecycle_without_network(self):
        result = subprocess.run(['node', '--input-type=module', '-e', r'''
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const html=fs.readFileSync('templates/index.html','utf8');
const script=html.split('<script>')[1].split('</script>')[0];
new vm.Script(script);
const polling=script.slice(script.indexOf('// Empty/draft/finished'),script.indexOf('async function loadSteelViewer'));
const poll=script.slice(script.indexOf('async function poll()'),script.indexOf('async function loadAuthorizedEvents()'));
const binding=script.slice(script.indexOf('function withJob('),script.indexOf('// Empty/draft/finished'));
const timers=new Map(),calls=[],elements=new Map(); let id=0,nextState={},pending=null;
const $=name=>{if(!elements.has(name))elements.set(name,{textContent:'',value:'',classList:{add(){},toggle(){}},blur(){},removeAttribute(){}});return elements.get(name)};
const context={$,state:{},selectedJob:null,jobsCache:[],workspaceEpoch:0,selectedWorker:1,workbookChanges:new Map(),loadedRRVersion:null,
  browserLoaded:false,viewerRetry:null,request:async url=>{calls.push(url);return pending?await pending:nextState},
  setInterval:fn=>{timers.set(++id,fn);return id},clearInterval:i=>timers.delete(i),clearTimeout(){},
  duration:()=>'',friendlyStatus:()=>'',renderWorkbookIdentity(){},renderCompletion(){},syncWorkbookEditor(){},renderSteps(){},
  loadWorkbook:async()=>{},loadSteelViewer(){},refreshJobs:async()=>{calls.push('/api/jobs')}};
vm.createContext(context);vm.runInContext(polling+'\n'+binding+'\n'+poll,context);
// No job: local idle rendering only, no requests or timers, no fallback to latest job.
await context.poll();context.syncPolling();assert.equal(calls.length,0);assert.equal(timers.size,0);
assert.equal($('error').textContent,'');assert.equal($('stage').textContent,'UPLOAD');assert.equal($('startbtn').disabled,true);
assert.throws(()=>context.withJob('/api/start'),/upload an RR/);
// Incomplete binding must not activate polling even if marked running.
context.selectedJob='job';context.jobsCache=[{id:'job',state:'running',event_id:'event'}];
context.syncPolling();assert.equal(timers.size,0);
const job={id:'job',state:'draft',original_filename:'RR.xlsx',event_id:'event'};
context.jobsCache=[job];context.syncPolling();assert.equal(timers.size,0);
// Explicit Start activates updates; blank new-upload fields do not stop a bound run.
job.state='running';context.syncPolling();assert.equal(timers.size,2);
context.syncPolling();assert.equal(timers.size,2);
nextState={job:{...job},status:'running',agent_process_running:true,automation_scope:{valid:true},rr_version:null,rr_file:'RR.xlsx',authorized_event_name:'Approved event'};
await context.poll();assert.deepEqual(calls,['/api/status?job_id=job']);assert.equal(timers.size,2);
assert.equal($('rrname').textContent,'Loaded: RR.xlsx');
assert.match($('target').textContent,/Approved event/);
// Terminal response stops both timers despite a stale running jobs cache.
nextState={...nextState,job:{...job,state:'completed'},status:'completed',agent_process_running:false,browser:{running:false}};
await context.poll();assert.equal(timers.size,0);
// Switching to an empty workspace cancels updates and does not fetch empty status.
context.stopPolling();context.selectedJob=null;context.state={};context.workspaceEpoch++;
const count=calls.length;await context.poll();assert.equal(calls.length,count);assert.equal(timers.size,0);
// A late response for another workspace cannot resurrect polling or its state.
context.selectedJob='job';context.jobsCache=[job];
let resolve;pending=new Promise(r=>resolve=r);const old=context.poll();
context.stopPolling();context.workspaceEpoch++;context.selectedWorker=2;context.selectedJob=null;context.state={};
resolve({job:{...job},status:'running',agent_process_running:true});await old;
assert.equal(context.state.status,'waiting_for_rr');assert.equal(timers.size,0);
// Boot no longer registers unconditional timers.
const boot=script.slice(script.indexOf('async function boot()'));
assert.ok(!boot.includes('setInterval('));
console.log('Idle/active/terminal polling and workspace races verified');
'''], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
