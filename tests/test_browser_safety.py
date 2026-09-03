import json,tempfile,unittest
from pathlib import Path
import browser_gate

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'templates/index.html').read_text()
APP=(ROOT/'app.py').read_text()

class ViewerSafetyTests(unittest.TestCase):
    def test_viewer_is_shielded_by_default(self):
        self.assertIn('viewer-stage agent-owned',HTML)
        self.assertIn('.viewer-stage.agent-owned .browser-frame',HTML)
        self.assertIn('pointer-events:none',HTML)
        self.assertIn('interaction-shield',HTML)
        self.assertIn('TAKE CONTROL',HTML)
        self.assertIn('RETURN TO AGENT',HTML)
        self.assertIn('tabindex="-1"',HTML)
    def test_hover_never_changes_ownership(self):
        lowered=HTML.lower()
        for event in ('mouseenter','mouseover','pointerenter','mousemove'):
            self.assertNotIn(event,lowered)
    def test_raw_viewer_tab_hidden_until_user_control(self):
        self.assertIn('id="browser-tab" class="secondary" type="button" hidden',HTML)
        self.assertIn("if(state.browser_gate?.ownership==='USER')",HTML)
    def test_viewer_document_blocks_all_input_while_agent_owned(self):
        self.assertIn("'pointermove'",APP);self.assertIn("'mousemove'",APP)
        self.assertIn("'wheel'",APP);self.assertIn("'focusin'",APP)
        self.assertIn("document.body.style.pointerEvents=user?'auto':'none'",APP)
        self.assertIn("d.ownership==='USER'&&d.desiredOwnership==='USER'",APP)
    def test_product_uses_cvent_agent_branding(self):
        self.assertNotIn('Pi ',HTML)
        self.assertIn('Current CVENT Agent execution',HTML)
        self.assertIn('<dt>CVENT Agent</dt>',HTML)
    def test_live_data_is_never_cached(self):
        self.assertIn("opts.cache='no-store'",HTML)
        self.assertIn('state.rr_version!==loadedRRVersion',HTML)
        self.assertIn("'Cache-Control':'no-store, no-cache, must-revalidate'",APP)

class BrowserGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();base=Path(self.tmp.name)
        self.old=(browser_gate.GATE,browser_gate.LOCK)
        browser_gate.GATE=base/'gate.json';browser_gate.LOCK=base/'gate.lock'
        browser_gate.initialize()
    def tearDown(self):
        browser_gate.GATE,browser_gate.LOCK=self.old;self.tmp.cleanup()
    def test_agent_action_and_user_transition(self):
        with browser_gate.action('runtime-x','CVENT_EGO'):
            self.assertEqual(browser_gate.read()['activeActor'],'CVENT_EGO')
        self.assertEqual(browser_gate.read()['activeActor'],'NONE')
        browser_gate.request_user()
        with self.assertRaisesRegex(RuntimeError,'not agent-owned'):
            with browser_gate.action('runtime-x','CVENT_BROWSER_USE'):pass
    def test_only_explicit_request_changes_desired_ownership(self):
        self.assertEqual(browser_gate.read()['desiredOwnership'],'AGENT')
        browser_gate.request_user()
        self.assertEqual(browser_gate.read()['desiredOwnership'],'USER')

if __name__=='__main__':unittest.main()
