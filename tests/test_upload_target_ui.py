"""Exercise the shipped upload JavaScript without network or Cvent access."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UploadTargetUITests(unittest.TestCase):
    def test_authorization_loading_matching_and_workspace_races(self):
        result = subprocess.run(['node', '--input-type=module', '-e', r'''
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const html=fs.readFileSync('templates/index.html','utf8');
const script=html.split('<script>')[1].split('</script>')[0];
new vm.Script(script); // Syntax-check the entire shipped script as well.
const source=script.slice(script.indexOf('async function loadAuthorizedEvents()'),script.indexOf("$('rr').onchange="));
const event={event_id:'e712e34c-6117-4d13-bf4c-8ed54cf2b495',name:'(C+D) Medtrade Testing Clone 2',event_code:'NLNMYJD28PH'};
function setup({events=[event],error=null,input=event.name,change=null}={}){
  const elements=new Map();
  const $=id=>{if(!elements.has(id))elements.set(id,{value:'',textContent:'',appendChild(){}});return elements.get(id)};
  $('event-target-input').value=input;
  const calls=[];
  const context={$,document:{createElement:()=>({})},eventsCache:[event],workbookChanges:new Map(),workspaceEpoch:0,selectedWorker:1,selectedJob:null,FormData,
    request:async(url,opts)=>{calls.push({url,opts});if(url==='/api/events'){if(change)change(context,$);if(error)throw new Error(error);return events}assert.equal(url,'/api/upload');return {job_id:'new-draft'}},
    renderWorkbookIdentity(){},refreshJobs:async()=>{},loadWorkbook:async()=>{},poll:async()=>{}};
  vm.createContext(context);vm.runInContext(source,context);
  return {context,$,calls,upload:()=>context.uploadRR({name:'RR.xlsx'})};
}
// Failed /api/events must neither claim the name is wrong nor use a stale cache.
let t=setup({error:'Invalid server-authorized target list'});await t.upload();
assert.match(t.$('error').textContent,/Authorized event list unavailable: Invalid server-authorized target list/);
assert.equal(t.calls.length,1);assert.equal(t.context.eventsCache.length,0);
// Recovery requires no reload: intake fetches the list again after failed boot.
for(const input of [event.name,`  ${event.name.toUpperCase()}  `,event.event_code,event.event_id]){
  t=setup({input});t.context.eventsCache=[];await t.upload();
  assert.deepEqual(t.calls.map(x=>x.url),['/api/events','/api/upload']);
  assert.equal(t.calls[1].opts.body.get('event_id'),event.event_id);
  assert.equal(t.calls[1].opts.body.get('worker_slot'),'1');
  assert.equal(t.context.selectedJob,'new-draft');assert.equal(t.$('error').textContent,'');
}
for(const input of ['', 'BDNY 2026', 'Medtrade Testing Clone 2', 'unknown-id']){
  t=setup({input});await t.upload();assert.match(t.$('error').textContent,/No exact authorized match/);assert.equal(t.calls.length,1);
}
t=setup({events:[event,{...event,event_id:'11111111-1111-4111-8111-111111111111'}]});await t.upload();
assert.match(t.$('error').textContent,/multiple authorized events/);assert.equal(t.calls.length,1);
t=setup({change:c=>{c.workspaceEpoch++;c.selectedWorker=2}});await t.upload();assert.equal(t.calls.length,1);
t=setup({change:(c,$)=>{$('event-target-input').value='Other event'}});await t.upload();
assert.match(t.$('error').textContent,/Target changed/);assert.equal(t.calls.length,1);
console.log('Upload target UI regression checks passed');
'''], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
