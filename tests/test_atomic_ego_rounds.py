"""Live Venue failure: execute the real wrapper against fake Ego, never Cvent."""
import json
import subprocess
from pathlib import Path
from unittest.mock import patch
from contextlib import nullcontext
import unittest
import test_runtime_failure_regressions as regressions
import browser_tool
from mutation_outcome import mutation_outcome


class AtomicEgoRoundsTests(unittest.TestCase):
    setUp = regressions.AdapterFailureTests.setUp
    tearDown = regressions.AdapterFailureTests.tearDown
    run_native = regressions.AdapterFailureTests.run_native
    def atomic(self, body, source_header=None):
        return self.run_native("cliLog(await page.snapshot());\n"+body+"\nawait page.click('@save'); await page.waitForTimeout(10); cliLog(await page.snapshot());", sources=source_header)

    def test_later_invalid_source_rejects_before_first_valid_fill(self):
        _, result = self.atomic("await page.fill('@input','one',{rrSource:'RR!B1'}); await page.fill('@input','two',{rrSource:'RR!B3'});", ['RR!B1'])
        self.assertFalse(result['ok'])
        self.assertEqual(result['writesAttempted'], 0)
        self.assertFalse(result['unresolvedWrites'])
        self.assertIn('rrSource', result['error'])

    def test_venue_fill_without_save_is_zero_dispatch_no_hold(self):
        script="cliLog(await page.snapshot()); await page.fill('@input','The Hangar at Regatta Harbour',{rrSource:'RR!B1'});"
        proc, result = self.run_native(script)
        self.assertEqual(result['writesAttempted'], 0)
        self.assertIn('lacking Save', result['error'])
        params={'intent':'write','domain':'event_settings','commitMode':'save','rrSources':['RR!B1'],'script':script}
        with patch.object(browser_tool,'CURRENT',self.folder), patch.object(browser_tool,'action',side_effect=lambda *_:nullcontext()), patch.object(browser_tool,'guard',return_value={'url':'https://app.cvent.com/view?evtstub=test-event'}), patch.object(browser_tool.subprocess,'run',return_value=proc):
            with self.assertRaisesRegex(RuntimeError,'ROUND_PLANNING_ERROR'):
                browser_tool.run_direct(self.folder/'browser-runtime.json',self.runtime,'ego','script',params)
        self.assertFalse(mutation_outcome(self.folder)['unresolved'])
        self.assertFalse((self.folder/'browser-mutation-uncertain.json').exists())

    def test_save_tab_edit_do_not_have_fake_cells(self):
        _, result=self.atomic("await page.fill('@input','one',{rrSource:'RR!B1'}); await page.keyboard.press('Tab');", ['RR!B1','RR!B3'])
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['writesAttempted'],2) # one data fill and one Save, not Tab
        self.assertEqual(result['saves'],1)
        self.assertEqual(result['readbacks'],1)
        for action in result['actions']:
            if action['operation'] in ['press','click']:self.assertIsNone(action.get('rrSource'))

    def test_commit_control_is_resolved_before_fill(self):
        _, result=self.run_native("cliLog(await page.snapshot()); await page.fill('@input','one'); await page.click('@not-save'); await page.waitForTimeout(10); cliLog(await page.snapshot());")
        self.assertEqual(result['writesAttempted'],0)
        self.assertRegex(result['error'],'No exact, current Save|Mutating control requires write intent')

    def test_runtime_failure_after_dispatch_remains_uncertain(self):
        _,result=self.atomic("await page.fill('@input','fail',{rrSource:'RR!B1'});")
        self.assertEqual(result['writesAttempted'],1)
        self.assertEqual(result['saves'],0)
        self.assertEqual(result['readbacks'],0)
        self.assertTrue(result['unresolvedWrites'])

    def test_conditional_save_and_comment_save_cannot_authorize_fill(self):
        for script in [
            "cliLog(await page.snapshot()); await page.fill('@input','one'); // await page.click('@save');\n await page.waitForTimeout(10); cliLog(await page.snapshot());",
            "cliLog(await page.snapshot()); await page.fill('@input','one'); if(false) await page.click('@save'); await page.waitForTimeout(10); cliLog(await page.snapshot());",
            "cliLog(await page.snapshot()); await page.fill('@input','one'); await page.click('@save'); cliLog(await page.snapshot());",
        ]:
            with self.subTest(script=script):
                _,result=self.run_native(script)
                self.assertEqual(result['writesAttempted'],0)
                self.assertFalse(result['ok'])

    def test_target_binding_is_checked_before_dispatch(self):
        (self.folder/'authorized-target.json').unlink()
        _,result=self.atomic("await page.fill('@input','one');")
        self.assertEqual(result['writesAttempted'],0)
        self.assertIn('target is not bound',result['error'])

    def test_resolved_source_matches_desired_value_not_previous_field(self):
        root=Path(__file__).resolve().parents[1]
        source="""
import assert from 'node:assert/strict';
import {sourceForAction} from './ego_round_validation.mjs';
const items=[['B10','Venue'],['B18','2026-11-13']].map(([range,value])=>({status:'VERIFIED',sourceEvidence:{sheet:'Event Details',range},interpretedCventValue:value}));
const sources=['Event Details!B10','Event Details!B18'];
assert.equal(sourceForAction({text:'Venue'},sources,items),'Event Details!B10');
assert.equal(sourceForAction({text:'11/13/2026',rrSource:sources[1]},sources,items),sources[1]);
assert.throws(()=>sourceForAction({text:'wrong venue',rrSource:sources[0]},sources,items),/Desired value/);
assert.throws(()=>sourceForAction({text:'Venue',rrSource:'Event Details!B12'},sources,items),/VERIFIED/);
"""
        p=subprocess.run(['node','--input-type=module','-e',source],cwd=root,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stderr)
