import json,tempfile,unittest
from pathlib import Path
import browser_gate,browser_tool

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'templates/index.html').read_text()
APP=(ROOT/'app.py').read_text()
PROMPT=(ROOT/'PI_PROMPT.md').read_text()
SKILL=(ROOT/'.agents/skills/cvent-browser/SKILL.md').read_text()
ROUTER=(ROOT/'browser_tool.py').read_text()

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
        self.assertNotRegex(HTML,r'(?i)\bpi\b')
        self.assertIn('<title>Emerald · CVENT Agent</title>',HTML)
        self.assertIn('Current CVENT Agent execution',HTML)
        self.assertIn('<dt>CVENT Agent</dt>',HTML)
        self.assertIn("FastAPI(title='CVENT Agent')",APP)
        self.assertIn("st['agent_session_saved']",APP)
        self.assertNotIn("st['agent_session']",APP)
    def test_live_data_is_never_cached(self):
        self.assertIn("opts.cache='no-store'",HTML)
        self.assertIn('state.rr_version!==loadedRRVersion',HTML)
        self.assertIn("'Cache-Control':'no-store, no-cache, must-revalidate'",APP)
        self.assertIn("JSONResponse(product_facing(st),headers={'Cache-Control':'no-store'})",APP)

class BrowserTargetSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.old=(browser_tool.CURRENT,browser_tool.local_probe)
        browser_tool.CURRENT=self.base
        self.runtime={'authorizedEventName':'(C+D) Medtrade Testing Clone 2','targetBrowserIdentity':{'url':'https://app.cvent.com/event?evtstub=locked'}}
    def tearDown(self):
        browser_tool.CURRENT,browser_tool.local_probe=self.old;self.tmp.cleanup()
    def write_lock(self):
        (self.base/'authorized-target.json').write_text(json.dumps({'name':'(C+D) Medtrade Testing Clone 2','url':'https://app.cvent.com/event?evtstub=locked','event_key':'locked'}))
    def test_write_requires_lock_matching_live_page(self):
        browser_tool.local_probe=lambda runtime:{'url':'https://app.cvent.com/event?evtStub=locked'}
        self.assertEqual(browser_tool.event_key('https://app.cvent.com/event?evtStub=locked'),'locked')
        with self.assertRaisesRegex(RuntimeError,'Write blocked'):
            browser_tool.guard(self.runtime,'click',{'intent':'write'})
        self.write_lock();browser_tool.guard(self.runtime,'click',{'intent':'write'})
        with self.assertRaisesRegex(RuntimeError,'explicit read or write intent'):
            browser_tool.guard(self.runtime,'js',{'expression':'document.title'})
        browser_tool.guard(self.runtime,'js',{'expression':'document.title','intent':'read'})
        browser_tool.guard(self.runtime,'cdp',{'method':'Runtime.evaluate','intent':'write'})
        browser_tool.local_probe=lambda runtime:{'url':'https://app.cvent.com/event?evtstub=other'}
        with self.assertRaisesRegex(RuntimeError,'Write blocked'):
            browser_tool.guard(self.runtime,'click',{'intent':'write'})
    def test_navigation_fails_closed(self):
        browser_tool.local_probe=lambda runtime:{'url':'https://app.cvent.com/subscribers/events2/EventSelection'}
        with self.assertRaisesRegex(RuntimeError,'non-authorized'):
            browser_tool.guard(self.runtime,'navigate',{'url':'https://app.cvent.com/event?evtstub=other','intent':'read'})
        with self.assertRaisesRegex(RuntimeError,'account-global'):
            browser_tool.guard(self.runtime,'navigate',{'url':'https://app.cvent.com/account/settings','intent':'read'})
    def test_ego_inside_steel_is_the_only_active_router(self):
        self.assertIn('Use Ego direct for all Cvent browsing and building',PROMPT)
        self.assertIn('Ego is the only browser tool',SKILL)
        self.assertFalse((ROOT/'browser_use_operator.py').exists())
        self.assertFalse((ROOT/'browser_use_direct.py').exists())
        self.assertIn("choices=['auto','ego']",ROUTER)
        self.assertIn("tool='ego'",ROUTER)
        self.assertIn("st['browser_strategy']='EGO DIRECT · SAME STEEL RUNTIME'",APP)
    def test_ego_scroll_search_precedes_advanced_search(self):
        self.assertIn("'scanEventList'",ROUTER)
        self.assertIn('Ego `scanEventList`',PROMPT)
        self.assertIn('Do not default to Advanced Search',PROMPT)

class BrowserGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();base=Path(self.tmp.name)
        self.old=(browser_gate.GATE,browser_gate.LOCK)
        browser_gate.GATE=base/'gate.json';browser_gate.LOCK=base/'gate.lock'
        browser_gate.initialize()
    def tearDown(self):
        browser_gate.GATE,browser_gate.LOCK=self.old;self.tmp.cleanup()
    def test_agent_action_and_user_transition(self):
        self.assertEqual(browser_gate.read()['automationOwner'],'PI_EGO')
        with browser_gate.action('runtime-x','PI_EGO'):
            self.assertEqual(browser_gate.read()['activeActor'],'PI_EGO')
            self.assertEqual(browser_gate.read()['automationOwner'],'PI_EGO')
        self.assertEqual(browser_gate.read()['activeActor'],'NONE')
        self.assertEqual(browser_gate.read()['automationOwner'],'PI_EGO')
        browser_gate.request_user()
        with self.assertRaisesRegex(RuntimeError,'not agent-owned'):
            with browser_gate.action('runtime-x','PI_EGO'):pass
    def test_only_explicit_request_changes_desired_ownership(self):
        self.assertEqual(browser_gate.read()['desiredOwnership'],'AGENT')
        browser_gate.request_user()
        self.assertEqual(browser_gate.read()['desiredOwnership'],'USER')

if __name__=='__main__':unittest.main()
