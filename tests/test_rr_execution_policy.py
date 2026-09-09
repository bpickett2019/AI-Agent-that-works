import json
import subprocess
import unittest
from pathlib import Path

import browser_tool
from completion_state import verified_completed_stages

ROOT = Path(__file__).resolve().parents[1]


class RRExecutionPolicyTests(unittest.TestCase):
    def node(self, code):
        result = subprocess.run(['node', '--input-type=module', '-e', code], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unspecified_group_setting_passes_gateway_without_becoming_false(self):
        record = dict(code='ATT', name='Attendee', source='RR!A5', active=True,
                      groupRegistration=None, reprintFee=None)
        params = dict(intent='write', records=[record], timeoutSeconds=600)
        browser_tool.validate_trusted_procedure('configureRegistrationTypes', params)
        for invalid in ('false', 0, [], {}):
            with self.assertRaisesRegex(RuntimeError, 'flags are invalid'):
                browser_tool.validate_trusted_procedure('configureRegistrationTypes',
                    dict(params, records=[dict(record, groupRegistration=invalid)]))

    def test_event_query_alias_conflicts_fail_closed(self):
        base = 'https://app.cvent.com/item?evtStub=selected'
        self.assertEqual(browser_tool.event_key(base), 'selected')
        self.assertEqual(browser_tool.event_key(base+'&EVTSTUB=selected'), 'selected')
        for extra in ('&event=other', '&evtstub=other', '&evtstub='):
            self.assertIsNone(browser_tool.event_key(base+extra))

    def test_permanent_denials_include_new_event_and_test_send(self):
        for label in ('Delete', 'Remove', 'Archive', 'Publish', 'Go Live',
                      'Send Email', 'Test-Send', 'Test Send Email', 'Schedule Email',
                      'Create Event', 'Create a new event', 'New Event'):
            with self.assertRaisesRegex(RuntimeError, 'protected'):
                browser_tool.assert_safe_write_target('click', {}, {'role':'button', 'text':label})
        for route in ('/Subscribers/AccountSettings/RegistrationTypes', '/admin/',
                      '/contacts/', '/attendees/', '/library/'):
            self.assertTrue(browser_tool.PROTECTED_PAGE.search(route), route)
        for label in ('Save', 'Create Admission Item', 'Edit', 'Create Registration Type'):
            browser_tool.assert_safe_write_target('click', {}, {'role':'button', 'text':label})

    def test_code_column_not_similar_name_controls_identity(self):
        self.node(r"""
import assert from 'node:assert/strict';
import {exactRow,partitionRegistrationFields,itemOutcome} from './trusted_cvent_procedures.mjs';
const header={header:true,cells:['Name','Code \uea80'],links:[]};
const similar={header:false,cells:['SPONCOMP','OTHER'],links:[{text:'SPONCOMP',href:'detail-other'}]};
const exact={header:false,cells:['Sponsor | Complimentary','SPONCOMP'],links:[{href:'detail-exact'}]};
assert.equal(exactRow([header,similar],'SPONCOMP').count,0);
assert.equal(exactRow([header,similar,exact],'SPONCOMP').row,exact);
assert.equal(exactRow([header,exact,{...exact}],'SPONCOMP').count,2);
assert.equal(exactRow([similar,exact],'SPONCOMP').identityUnavailable,true);
const plan=partitionRegistrationFields([
 {field:'name',marked:{selector:'reviewed'},value:'Correct name'},
 {field:'groupRegistration',marked:null,value:'Yes'}],{active:true,code:true});
assert.deepEqual(plan.actionable.map(x=>x.field),['name']);
assert.equal(plan.fieldGaps.length,1);
assert.equal(plan.fieldGaps[0].field,'groupRegistration');
assert.equal(plan.fieldGaps[0].status,'CONTROL_NOT_AVAILABLE');
assert.equal(itemOutcome('CONFIGURED'),'EXACT_MATCH_UPDATED');
assert.equal(itemOutcome('ALREADY_CORRECT'),'EXACT_MATCH_ALREADY_CORRECT');
assert.equal(itemOutcome('CREATED'),'NOT_FOUND_CREATED');
assert.equal(itemOutcome('AMBIGUOUS'),'MATCH_UNCERTAIN_HUMAN_REVIEW');
assert.throws(()=>itemOutcome('probably okay'));
""")

    def test_verification_requires_explicit_item_evidence(self):
        self.node(r"""
import fs from 'node:fs';
import {stripTypeScriptTypes} from 'node:module';
import assert from 'node:assert/strict';
const src=fs.readFileSync('extensions/cvent-job-tools.ts','utf8');
const block=src.slice(src.indexOf('function verificationItemResults('),src.indexOf('async function assertDomainEvidenceVerified('));
const verify=new Function(stripTypeScriptTypes(block)+';return verificationItemResults;')();
const rr=[{itemId:'one',status:'VERIFIED'},{itemId:'two',status:'VERIFIED'},{itemId:'three',status:'AMBIGUOUS'}];
assert.deepEqual(verify(rr,[],[]).map(x=>x.status),['NOT_CONFIGURED','NOT_CONFIGURED','AMBIGUOUS']);
const match={itemId:'one',cventEvidence:['Fresh exact code readback']};
assert.deepEqual(verify(rr,[match],[]).map(x=>x.status),['MATCH','NOT_CONFIGURED','AMBIGUOUS']);
assert.throws(()=>verify(rr,[match,match],[]));
assert.throws(()=>verify(rr,[match],[{itemId:'one',status:'NOT_CONFIGURED'}]));
assert.throws(()=>verify(rr,[{itemId:'outside',cventEvidence:['read']}],[]));
assert.throws(()=>verify(rr,[{itemId:'three',cventEvidence:['read']}],[]));
""")

    def test_registration_mission_updates_available_field_without_guessing_group(self):
        self.node(r"""
import assert from 'node:assert/strict';
import {runTrustedCventProcedure} from './trusted_cvent_procedures.mjs';
const key='e712e34c-6117-4d13-bf4c-8ed54cf2b495';
const href='https://app.cvent.com/Subscribers/Events2/Details/RegistrationTypeDetail/Index/View?evtstub='+key+'&registrationtypestub=type-one';
let url=href, title='Old name',pending=null,saves=0,fills=0;
const ego={
 goto:async next=>{url=next},waitForTimeout:async()=>{},pageInfo:async()=>({url,title}),
 evaluate:async expression=>{
  if(expression.includes('table tr,[role=row]'))return [
   {header:true,cells:['Name','Code'],links:[]},
   {header:false,cells:[title,'ATT'],links:[{text:title,href}]}];
  if(expression.includes('document.body?.innerText'))return {title,body:'Active:\nYes\nCode:\nATT',controls:[],buttons:['Edit']};
  if(expression.includes('const labels='))return expression.includes('registration type name') ?
   {count:1,selector:'#name',tag:'INPUT',type:'text',value:title} : {count:0};
  if(expression.includes('const wanted='))return {count:1,selector:expression.includes('save and close')?'#save':'#edit'};
  throw Error('Unexpected browser read in test');
 },
 fill:async(selector,value)=>{assert.equal(selector,'#name');pending=value;fills++},
 click:async selector=>{if(selector==='#save'){assert.notEqual(pending,null);title=pending;saves++}},
};
const record={code:'ATT',name:'New name',source:'RR!A5',active:true,groupRegistration:true,reprintFee:null};
const result=await runTrustedCventProcedure(ego,{authorizedEventKey:key},'configureRegistrationTypes',
 {records:[record,{...record,code:'SPONCOMP',name:'Sponsor | Complimentary'}]});
assert.equal(fills,1);assert.equal(saves,1);assert.equal(title,'New name');
assert.equal(result.records[0].status,'EXACT_MATCH_UPDATED');
assert.deepEqual(result.records[0].configured,['name']);
assert.equal(result.records[0].fieldGaps[0].field,'groupRegistration');
assert.equal(result.records[1].status,'MATCH_UNCERTAIN_HUMAN_REVIEW');
assert.equal(result.counts.updated,1);assert.equal(result.counts.failures,2);
assert.equal(result.metrics.fullSnapshots,0);assert.ok(result.metrics.egoOperations>10);
""")

    def test_reviewed_or_unread_domains_do_not_appear_completed(self):
        state = {'completed':['rr_analysis','registration_types']}
        validation = {'items':[{'domain':'registration_types','itemId':'one','status':'VERIFIED'}]}
        result = {'domains':{'registration_types':{'status':'completed','blocked':[]}}}
        evidence = {'domains':{'registration_types':{'items':[{'itemId':'one','status':'MATCH','cventEvidence':['readback']} ]}}}
        self.assertEqual(verified_completed_stages(state,result,evidence,validation),state['completed'])
        result['domains']['registration_types']['status'] = 'review_required'
        self.assertEqual(verified_completed_stages(state,result,evidence,validation),['rr_analysis'])
        result['domains']['registration_types']['status'] = 'completed'
        evidence['domains']['registration_types']['items'][0].pop('cventEvidence')
        self.assertEqual(verified_completed_stages(state,result,evidence,validation),['rr_analysis'])
        self.assertEqual(verified_completed_stages(state,result,{},validation),['rr_analysis'])


if __name__ == '__main__':
    unittest.main()
