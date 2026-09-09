"""Execute fixed browser-side expressions, not just the enclosing MJS syntax."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TrustedSectionRegressionTests(unittest.TestCase):
    def node(self, source):
        result = subprocess.run(["node", "--input-type=module", "-e", source], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_section_state_expression_compiles_and_reads_75_rows(self):
        self.node(r"""
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const src = fs.readFileSync('ego_direct.mjs', 'utf8');
const block = src.split("case 'sectionState': {")[1].split("case 'controlInventory': {")[0];
const literal = block.slice(block.indexOf('result=await ego.evaluate(') + 'result=await ego.evaluate('.length, block.lastIndexOf(');break;'));
const expression = vm.runInNewContext(literal);
const rows = Array.from({length:75}, (_,i) => ({innerText:`Fee ${i}`, querySelectorAll(selector) {
  if (selector === 'th,td,[role=cell],[role=columnheader]') return [{innerText:`Fee ${i}`}];
  if (selector === 'a[href]') return [{innerText:`Fee ${i}`,href:`https://app.cvent.com/fee/${i}`}];
  throw Error(selector);
}}));
const document = {title:'Pricing',querySelectorAll(selector) {
 if (selector === 'table tr,[role=row]') return rows;
 if (selector === 'h1,h2,h3,[role=heading]') return [{innerText:'Pricing'}];
 if (selector === 'button,[role=button],input[type=submit]') return [{innerText:'Edit',disabled:false}];
 if (selector === 'input,select,textarea,[role=combobox]') return [];
 throw Error(selector);
}};
const result = new vm.Script(expression).runInNewContext({document,location:{href:'https://app.cvent.com/pricing'}});
assert.equal(result.rows.length,75);
assert.equal(result.rows[74].cells[0],'Fee 74');
assert.equal(result.headings[0],'Pricing');
assert.equal(result.buttons[0].text,'Edit');
""")

    def test_pricing_reader_waits_for_render_or_fails_closed(self):
        self.node(r"""
import fs from 'node:fs';
import assert from 'node:assert/strict';
const src=fs.readFileSync('ego_direct.mjs','utf8');
const block=src.split("case 'sectionState': {")[1].split("case 'controlInventory': {")[0];
const ready=block.slice(0,block.indexOf('result=await ego.evaluate('));
const run=new Function('ego','params','return (async()=>{'+ready+'})()');
let probes=0,waits=0;
await run({evaluate:async()=>++probes>=3,waitForTimeout:async()=>waits++},{domain:'pricing'});
assert.equal(probes,3);assert.equal(waits,2);
await assert.rejects(()=>run({evaluate:async()=>false,waitForTimeout:async()=>{}},{domain:'pricing'}),/unavailable, not empty/);
await run({evaluate:async()=>{throw Error('unexpected probe')}},{domain:'registration_types'});
""")

    def test_admission_evtstub_case_and_exact_event_relation(self):
        self.node(r"""
import assert from 'node:assert/strict';
import {eventKeyFromUrl,safeDetailHref} from './trusted_cvent_procedures.mjs';
const key='e712e34c-6117-4d13-bf4c-8ed54cf2b495';
const base='https://app.cvent.com/subscribers/events2/AgendaAndFees/AdmissionItemDetails';
const good=base+'?evtStub='+key+'&prodstub=item-one';
assert.equal(eventKeyFromUrl(good),key);
assert.equal(safeDetailHref({links:[{href:good}]},key,'admissionitem'),good);
for(const name of ['evtstub','evtStub','EVTSTUB','EventId','event']) {
 assert.equal(eventKeyFromUrl(base+'?'+name+'='+key),key);
}
for(const href of [base+'?prodstub=item-one',base+'?evtStub=other',good+'&event=other',good+'&evtstub=',
 good.replace('app.cvent.com','evilcvent.com'),good.replace('https:','http:'),
 good.replace('app.cvent.com','user@app.cvent.com'),good.replace('app.cvent.com','app.cvent.com:444'),
 good.replace('AdmissionItemDetails','AdmissionItemDetails/Delete'),good.replace('AdmissionItemDetails','AdmissionItemGrid'),
 good.replace('&prodstub=item-one',''),good+'&prodStub=item-two']) {
 assert.equal(safeDetailHref({links:[{href}]},key,'admissionitem'),null,href);
}
assert.equal(safeDetailHref({links:[{href:good},{href:good.replace('item-one','item-two')}]},key,'admissionitem'),null);
assert.equal(eventKeyFromUrl(good+'&event=other'),'');
const registration='https://app.cvent.com/Subscribers/Events2/Details/RegistrationTypeDetail/Index/View?evtstub='+key+'&registrationtypestub=type-one';
assert.equal(safeDetailHref({links:[{href:registration}]},key,'registrationtype'),registration);
""")

    def test_rr_boolean_projection_preserves_y_and_unspecified(self):
        self.node(r"""
import fs from 'node:fs';
import {stripTypeScriptTypes} from 'node:module';
import assert from 'node:assert/strict';
const src=fs.readFileSync('extensions/cvent-job-tools.ts','utf8');
const block=src.slice(src.indexOf('function booleanValue('),src.indexOf('async function assertDomainEvidenceVerified('));
const project=new Function('cleanText',stripTypeScriptTypes(block)+';return trustedProcedureRecords;')(value=>String(value??'').trim());
const item=(group,active='ACTIVATE')=>({fields:{registration_code:{value:'ATT'},registration_name:{value:'Attendee'},active:{value:active},group_registration:{value:group}}});
const items=['Y','N',undefined,null,'',true,false,'yes','no'].map(x=>item(x));
const projected=project('registration_types',{domains:{registration_types:{items}}});
assert.deepEqual(projected.map(x=>x.groupRegistration),[true,false,null,null,null,true,false,true,false]);
assert.deepEqual(projected.map(x=>x.activationDirective),Array(items.length).fill('ACTIVATE'));
assert.throws(()=>project('registration_types',{domains:{registration_types:{items:[item('maybe')]}}}),/refusing to guess/);
assert.throws(()=>project('registration_types',{domains:{registration_types:{items:[item('Y','')]}}}),/activation directive is unsupported/);
""")

    def test_registration_readback_is_observed_not_desired_or_substring(self):
        self.node(r"""
import assert from 'node:assert/strict';
import {registrationFacts} from './trusted_cvent_procedures.mjs';
const desired={code:'ATT',name:'Attendee',activationDirective:'ACTIVATE',groupRegistration:null,reprintFee:null};
const check=body=>registrationFacts({evaluate:async()=>({title:'Attendee',body,controls:[]})},desired);
const missing=await check('Attendee\nAdmission codes\nATTED\n');
assert.equal(missing.matches.activationDirective,true);
assert.equal(missing.matches.code,false);
assert.equal(missing.observed.openForRegistration,null);
assert.equal(missing.all,false);
const closed=await check('Open for registration:\nNo\nCode:\nATT');
assert.equal(closed.all,true);assert.equal(closed.observed.openForRegistration,false);
const open=await check('Open for registration:\nYes\nCode:\nATT');
assert.equal(open.all,true);assert.equal(open.observed.openForRegistration,true);
""")

    def test_registration_capability_inspection_never_adds_or_saves(self):
        self.node(r"""
import assert from 'node:assert/strict';
import {inspectRegistrationTypeCapabilities} from './trusted_cvent_procedures.mjs';
const key='e712e34c-6117-4d13-bf4c-8ed54cf2b495';
const grid='https://app.cvent.com/Subscribers/Events2/Details/RegistrationTypes/Index/View?evtstub='+key;
const detail=grid.replace('RegistrationTypes/Index/View','RegistrationTypeDetail/Index/View')+'&registrationtypestub=att';
let url=grid,mode='view';const clicks=[];
const ego={
 goto:async next=>{url=next;mode=next===grid?'view':mode},waitForTimeout:async()=>{},pageInfo:async()=>({url,title:'Registration Types'}),
 click:async selector=>{clicks.push(selector);if(selector==='#edit')mode=url===grid?'association':'detail';if(selector==='#add-contacts')mode='candidates'},
 evaluate:async expression=>{
  if(expression.includes('table tr,[role=row]')){
   if(mode==='candidates')return [{header:true,cells:['Name','Code'],links:[]},{header:false,cells:['Sponsor | Complimentary','SPONCOMP'],links:[]}];
   return [{header:true,cells:['Name','Code'],links:[]},{header:false,cells:['Attendee','ATT'],links:[{text:'Attendee',href:detail}]}];
  }
  if(expression.includes('getBoundingClientRect')&&expression.includes('readOnly'))return mode==='detail' ? [{label:'Open for registration',tag:'INPUT',type:'radio',value:'Yes',checked:true,disabled:false,readOnly:false}] : [];
  if(expression.includes('document.body?.innerText'))return {title:'Registration Types',body:mode==='detail'?'Open for registration:\nYes':'',controls:[],buttons:mode==='association'?['Save','Add from Contact Types','Create Contact Type']:mode==='candidates'?['Add','Cancel']:['Save']};
  if(expression.includes('const wanted=')){
   if(expression.includes('add from contact types'))return mode==='association'?{count:1,selector:'#add-contacts'}:{count:0};
   if(expression.includes('save and close'))return {count:1,selector:'#save'};
   if(expression.includes('["edit"]'))return {count:1,selector:'#edit'};
  }
  throw Error('Unexpected expression '+expression.slice(0,80));
 }
};
const result=await inspectRegistrationTypeCapabilities(ego,{authorizedEventKey:key},{records:[{code:'ATT',name:'Attendee'},{code:'SPONCOMP',name:'Sponsor | Complimentary'}],probeCode:'ATT'});
assert.equal(result.status,'INSPECTED');
assert.equal(result.configurationWrites,0);assert.equal(result.saveCalls,0);
assert.deepEqual(clicks,['#edit','#edit','#add-contacts']);
assert.equal(result.detailEditor.eventLocalNameEditor,false);
assert.equal(result.detailEditor.groupRegistrationEditor,false);
assert.equal(result.detailEditor.openForRegistrationEditor,true);
assert.equal(result.associationEditor.addFromContactTypes,true);
assert.equal(result.associationEditor.createContactTypeObserved,true);
assert.equal(result.associationEditor.eventLocalCreationProven,false);
assert.equal(result.associationEditor.candidateInventory[1].exactCandidateMatches,1);
assert.equal(result.associationEditor.candidateInventory[1].name,'Sponsor | Complimentary');
assert.equal(result.associationEditor.candidateInventory[1].literalNameMatches,true);
""")

    def test_large_adapter_result_is_flushed_before_process_exit(self):
        output = self.node(r"""
import fs from 'node:fs';
const src=fs.readFileSync('ego_direct.mjs','utf8');
const declaration=src.slice(src.indexOf('function output('),src.indexOf('function roleRequest('));
const fn=new Function('process','operation',declaration+';return output;')(process,'snapshotText');
await fn({snapshot:'x'.repeat(2*1024*1024)});
process.exit(0);
""")
        self.assertTrue(output.startswith('BROWSER_TOOL_RESULT='))
        result = json.loads(output.split('=', 1)[1])
        self.assertEqual(len(result['snapshot']), 2 * 1024 * 1024)


if __name__ == '__main__':
    unittest.main()
