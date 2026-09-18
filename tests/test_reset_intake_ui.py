"""Execute the complete shipped UI with mock DOM/network; never start a model."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ResetIntakeUITests(unittest.TestCase):
    def test_reset_preserves_jobs_and_blocks_active_runs(self):
        result = subprocess.run(['node', '--input-type=module', '-e', r'''
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const script=fs.readFileSync('templates/index.html','utf8').split('<script>')[1].split('</script>')[0].replace(/\nboot\(\);\s*$/, '');
class Element {
  constructor(){this.value='';this._text='';this.options=[];this.dataset={};this.classList={add(){},remove(){},toggle(){},contains(){return false}}}
  set textContent(v){this._text=v;this.options=[]} get textContent(){return this._text}
  appendChild(v){this.options.push(v);if(this.options.length===1)this.value=v.value}
  replaceChildren(){} removeAttribute(){} addEventListener(){} blur(){} setAttribute(){}
}
const elements=new Map(),document={body:{dataset:{}},getElementById:id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id)},
 createElement:()=>new Element(),createDocumentFragment:()=>new Element(),querySelectorAll:()=>[],addEventListener(){}};
let allowConfirm=true,timerId=0;const calls=[],timers=new Map(),job={id:'draft',event_id:'event',event_name:'Approved event',original_filename:'RR.xlsx',state:'draft',preferred_slot:1};
let jobs=[job],status={job,status:'draft',rr_file:'RR.xlsx',authorized_event_name:'Approved event',automation_scope:{valid:true},rr_version:null,browser:{running:false}};
const context={document,URL,URLSearchParams,location:new URL('http://localhost/?worker=1'),history:{replaceState(_a,_b,url){context.location=new URL(url,'http://localhost')}},
 confirm:()=>allowConfirm,clearTimeout(){},setTimeout(){},setInterval:fn=>{timers.set(++timerId,fn);return timerId},clearInterval:id=>timers.delete(id),
 mockRequest:async(url,opts={})=>{calls.push([url,opts.method||'GET']);if(url==='/api/jobs')return jobs;if(url.startsWith('/api/status'))return status;
 if(url.startsWith('/api/workbook?'))return {version:null,sheets:[]};if(url.startsWith('/api/stop-agent')){status={...status,status:'stopping',stop_requested:true,browser:{running:true}};return {ok:true}};throw new Error('Unexpected request: '+url)}};
vm.createContext(context);vm.runInContext(script+'\nrequest=mockRequest;selectedJob="draft";',context);
const run=source=>vm.runInContext(source,context),$=document.getElementById;
await run('refreshJobs();');await run('poll();');
assert.equal($('rrname').textContent,'Loaded: RR.xlsx');
$('event-target-input').value='Approved event';
await $('reset-intake').onclick();
assert.equal(run('selectedJob'),null);assert.equal(run('newRunMode'),true);
assert.equal($('event-target-input').value,'');assert.equal($('rr').value,'');
assert.equal($('startbtn').disabled,true);assert.equal($('sheet-select').options.length,0);
assert.equal($('sheet-body').textContent,'');assert.equal($('steel-frame').src,'about:blank');
assert.equal(timers.size,0);assert.equal(context.location.search,'?worker=1&new=1');
assert.ok(calls.every(([,method])=>method==='GET'));
assert.equal($('job-select').options[1].value,'draft'); // Saved RR remains available.
await run('refreshJobs();');assert.equal(run('selectedJob'),null); // No auto-reselection.
$('job-select').value='draft';await $('job-select').onchange();
assert.equal(run('selectedJob'),'draft');assert.equal(run('newRunMode'),false);
assert.equal(context.location.search,'?worker=1');assert.equal($('rrname').textContent,'Loaded: RR.xlsx');
// A cancelled discard confirmation changes nothing.
run('workbookChanges.set("cell",{});');allowConfirm=false;const count=calls.length;
await $('reset-intake').onclick();assert.equal(calls.length,count);assert.equal(run('selectedJob'),'draft');
allowConfirm=true;run('workbookChanges.clear();');
// Cannot hide a still-running run, even if the currently selected RR is a draft.
jobs=[job,{...job,id:'active',state:'running'}];await $('reset-intake').onclick();
assert.equal(run('selectedJob'),'draft');assert.match($('error').textContent,/Stop the active run/);
// Stop stays disabled while cleanup runs; stale USER gate isn't offered for a closed browser.
jobs=[{...job,state:'running'}];status={...status,job:jobs[0],status:'running',agent_process_running:true,browser:{running:true}};
await run('poll();');await $('stopbtn').onclick();
assert.equal($('stopbtn').textContent,'STOPPING…');assert.equal($('stopbtn').disabled,true);
status={...status,job:{...job,state:'failed_prewrite'},status:'failed_prewrite',stop_requested:false,agent_process_running:false,browser:{running:false},browser_gate:{ownership:'USER',desiredOwnership:'USER'}};
await run('poll();');assert.equal($('continue').textContent,'RESTART BUILD');assert.equal($('continue').disabled,false);
assert.equal($('return-control').hidden,true);assert.equal(timers.size,0);
status={...status,job:{...job,state:'login_required'},status:'login_required'};
await run('poll();');assert.equal($('continue').textContent,'REOPEN & CONTINUE');assert.match($('banner').textContent,/RUN STOPPED/);
assert.ok(!calls.some(([url])=>url.startsWith('/api/start')||url.startsWith('/api/continue')));
console.log('Reset/reselect, active-run protection and Stop/Restart controls verified');
'''], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
