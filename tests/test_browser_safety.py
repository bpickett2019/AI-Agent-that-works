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
        self.assertLess(HTML.index('id="ownership-label"'),HTML.index('id="take-control"'))
        self.assertLess(HTML.index('id="take-control"'),HTML.index('id="browser-reload"'))
        self.assertIn('class="browser-controls"',HTML)
        self.assertNotIn('class="shield-card"',HTML)
        self.assertIn('background:transparent;pointer-events:auto',HTML)
        self.assertIn('tabindex="-1"',HTML)
    def test_hover_never_changes_ownership(self):
        lowered=HTML.lower()
        for event in ('mouseenter','mouseover','pointerenter','mousemove'):
            self.assertNotIn(event,lowered)
    def test_raw_viewer_tab_hidden_until_user_control(self):
        self.assertIn('id="browser-tab" class="secondary" type="button" hidden',HTML)
        self.assertIn("if(state.browser_gate?.ownership==='USER'&&state.browser?.viewer_url)",HTML)
    def test_viewer_document_blocks_all_input_while_agent_owned(self):
        self.assertIn("'pointermove'",APP);self.assertIn("'mousemove'",APP)
        self.assertIn("'wheel'",APP);self.assertIn("'focusin'",APP)
        self.assertIn("document.body.style.pointerEvents=user?'auto':'none'",APP)
        self.assertIn("d.ownership==='USER'&&d.desiredOwnership==='USER'",APP)
        self.assertIn("if not user_owned:",APP)
        self.assertIn('ownership.get("ownership") == "USER"',APP)
    def test_product_uses_cvent_agent_branding(self):
        self.assertNotRegex(HTML,r'(?i)\bpi\b')
        self.assertIn('<title>Forge · CVENT Agent</title>',HTML)
        self.assertIn('Current CVENT Agent execution',HTML)
        self.assertIn('<dt>CVENT Agent</dt>',HTML)
        self.assertIn('FastAPI(title="CVENT Agent"',APP)
        self.assertIn('state["agent_session_saved"]',APP)
        self.assertNotIn('state["agent_session"]',APP)
    def test_forge_brand_palette(self):
        for color in ('#152c44','#5994f6','#255ab2','#4581e5','#99bfff','#cae5ff','#6ff0dd','#eefffc'):
            self.assertIn(color,HTML)
    def test_sidebar_navigation_is_clickable(self):
        for target in ('workspace-top','scope-panel','intake-panel','workbook-panel','browser-panel'):
            self.assertIn(f'data-target="{target}"',HTML)
            self.assertIn(f'id="{target}"',HTML)
        self.assertIn('window.scrollTo({top,behavior})',HTML)
        self.assertIn("target.classList.add('nav-focus')",HTML)
        self.assertLess(HTML.index('data-target="workbook-panel"'),HTML.index('data-target="browser-panel"'))
        self.assertIn('<strong>CVENT browser</strong><small>Watch and take control</small>',HTML)
        self.assertIn("x.setAttribute('aria-current','page')",HTML)
        self.assertIn('Forge Intake is authoritative',HTML)
        self.assertIn('scope-confirmed',HTML)
    def test_completed_work_is_visibly_reported(self):
        self.assertIn('id="completion-summary"',HTML)
        self.assertIn('id="completion-chips"',HTML)
        self.assertIn('id="completion-toast"',HTML)
        self.assertIn("`${prettyStage(last)} complete`",HTML)
        self.assertIn("completed.length>knownCompleted",HTML)
        self.assertIn("classList.toggle('is-complete',done)",HTML)
    def test_live_data_is_never_cached(self):
        self.assertIn("opts.cache='no-store'",HTML)
        self.assertIn('state.rr_version!==loadedRRVersion',HTML)
        self.assertIn('"Cache-Control": "no-store, no-cache, must-revalidate"',APP)
        self.assertIn('JSONResponse(product_facing(state), headers={"Cache-Control": "no-store"})',APP)

class BrowserTargetSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.old=(browser_tool.CURRENT,browser_tool.local_probe,browser_tool.load_scope_manifest)
        browser_tool.CURRENT=self.base
        browser_tool.load_scope_manifest=lambda workbook,manifest:{'entries':[{'id':'scope-004','status':'confirmed'},{'id':'scope-070','status':'unconfirmed'}]}
        self.runtime={'authorizedEventName':'(C+D) Medtrade Testing Clone 2','targetBrowserIdentity':{'url':'https://app.cvent.com/event?evtstub=locked'}}
    def tearDown(self):
        browser_tool.CURRENT,browser_tool.local_probe,browser_tool.load_scope_manifest=self.old;self.tmp.cleanup()
    def write_lock(self):
        (self.base/'authorized-target.json').write_text(json.dumps({'name':'(C+D) Medtrade Testing Clone 2','url':'https://app.cvent.com/event?evtstub=locked','event_key':'locked'}))
    def test_write_requires_lock_matching_live_page(self):
        browser_tool.local_probe=lambda runtime:{'url':'https://app.cvent.com/event?evtStub=locked'}
        self.assertEqual(browser_tool.event_key('https://app.cvent.com/event?evtStub=locked'),'locked')
        with self.assertRaisesRegex(RuntimeError,'Write blocked'):
            browser_tool.guard(self.runtime,'click',{'intent':'write'})
        self.write_lock()
        with self.assertRaisesRegex(RuntimeError,'scopeId'):
            browser_tool.guard(self.runtime,'click',{'intent':'write'})
        browser_tool.guard(self.runtime,'click',{'intent':'write','scopeIds':['scope-004']})
        with self.assertRaisesRegex(RuntimeError,'scope-070'):
            browser_tool.guard(self.runtime,'fill',{'intent':'write','scopeIds':['scope-070']})
        with self.assertRaisesRegex(RuntimeError,'explicit read or write intent'):
            browser_tool.guard(self.runtime,'js',{'expression':'document.title'})
        browser_tool.guard(self.runtime,'js',{'expression':'document.title','intent':'read'})
        browser_tool.guard(self.runtime,'cdp',{'method':'Runtime.evaluate','intent':'write','scopeIds':['scope-004']})
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
        self.assertIn('Use the `cvent_browser` capability for all Cvent browsing and building',PROMPT)
        self.assertIn('Use `cvent_browser` for all Cvent browsing, building, and verification',SKILL)
        self.assertFalse((ROOT/'browser_use_operator.py').exists())
        self.assertFalse((ROOT/'browser_use_direct.py').exists())
        self.assertIn("choices=['auto','ego']",ROUTER)
        self.assertIn("tool='ego'",ROUTER)
        self.assertIn('"browser_strategy": "EGO DIRECT · JOB-ISOLATED STEEL RUNTIME"',APP)
        self.assertIn('AUTHORITATIVE SCOPE — FAIL CLOSED',PROMPT)
        self.assertIn("params.get('scopeIds',[])",ROUTER)
        self.assertIn('Forge Intake scopeId is required',ROUTER)
        self.assertIn('Never request viewport-only, element-only, truncated, targeted, or smaller DOM reads',PROMPT)
        self.assertIn('no shell, generic read, generic write',PROMPT)
        extension=(ROOT/'extensions/cvent-job-tools.ts').read_text()
        self.assertIn('this production agent has no shell or general filesystem tools',extension)
        self.assertNotIn('"read", "bash"',extension)
        self.assertIn('safeChildEnvironment',extension)
        self.assertNotIn('environment.ANTHROPIC_API_KEY',extension)
        self.assertIn('Arbitrary JavaScript and raw CDP are not exposed',PROMPT)
        self.assertNotIn('params.expression',extension)
        self.assertNotIn('name: "bash"',extension)
        self.assertNotIn('name: "read"',extension)
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
