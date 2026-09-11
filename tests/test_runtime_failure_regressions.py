"""Execute the real adapter with fake Ego I/O, and real killed gate processes."""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import browser_tool
from browser_gate import BrowserGate
from mutation_outcome import mutation_outcome

ROOT = Path(__file__).resolve().parents[1]


class AdapterFailureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        for name in ('ego_direct.mjs', 'trusted_cvent_procedures.mjs'):
            shutil.copy2(ROOT / name, self.folder / name)
        helper = self.folder / 'vendor/ego-browser-linux/dist/src/helpers.js'
        helper.parent.mkdir(parents=True)
        (self.folder / 'package.json').write_text('{"type":"module"}')
        helper.write_text('''
export async function listTabs(){if(process.env.CASE==='startup')throw Error('real startup error');return [{id:'target'}]}
export async function switchTab(){}
let markers=0;
export async function evaluate(expression){if(expression?.includes('document.activeElement'))return {tag:'INPUT',label:'Date',connected:true,disabled:false};if(++markers>1&&process.env.CASE==='postflight')throw Error('real postflight error');return 'cvent-runtime-test'}
export async function press(){return true}
export async function pageInfo(){return {url:'https://app.cvent.com/view?evtstub=test-event',title:'Test'}}
export async function waitForTimeout(){}
export async function screenshot(){return '/offline/screenshot.png'}
export async function snapshot(){if(process.env.CASE==='middle')throw Error('real snapshot failure');if(process.env.CASE==='string')throw 'real non-Error failure';return 'semantic snapshot'}
export async function evaluateLocator(target){if(process.env.CASE==='writes')return {tag:['@save','@edit'].includes(target)?'BUTTON':'INPUT',connected:true,disabled:false,label:target==='@save'?'Save':target==='@edit'?'Edit':target==='@delete'?'Delete':'Description'};throw Error('real target missing before dispatch')}
export async function click(){return true}
export async function fill(target,text){if(process.env.CASE==='writes'){if(text==='fail')throw Error('real dispatched mutation failure');return true}throw Error('MUTATION SHOULD NOT HAVE BEEN DISPATCHED')}
''')
        self.runtime = {'browserRuntimeId': 'cvent-runtime-test', 'cdpHttpOrigin': 'http://127.0.0.1:1',
                        'targetBrowserIdentity': {'targetId': 'target'}, 'authorizedEventKey': 'test-event'}
        (self.folder / 'browser-runtime.json').write_text(json.dumps(self.runtime))
        self.steps = [{'operation': op, 'intent': 'read'} for op in ('pageInfo', 'wait', 'snapshotText', 'screenshot')]

    def tearDown(self):
        self.tmp.cleanup()

    def run_adapter(self, case, steps=None):
        params = {'intent': 'read', 'objective': 'Offline multi-action regression', 'commitMode': 'read_only', 'steps': steps or self.steps}
        proc = subprocess.run(['node', 'ego_direct.mjs', '--runtime', str(self.folder / 'browser-runtime.json'),
                               '--operation', 'actions', '--params', json.dumps(params)], cwd=self.folder,
                              env={**{k: v for k, v in os.environ.items() if not k.startswith('CVENT_')}, 'CASE': case,
                                   'CVENT_ENV': 'development'}, capture_output=True, text=True, timeout=10)
        self.assertNotIn('ReferenceError', proc.stdout + proc.stderr)
        return proc, browser_tool.child_result(proc)

    def run_native(self, script, mode='save', case='writes', sources=None):
        (self.folder / 'rr-validation.json').write_text(json.dumps({'items': [
            {'domain': 'event_settings', 'status': 'VERIFIED', 'sourceEvidence': {'sheet': 'RR', 'range': 'B1'}},
            {'domain': 'event_settings', 'status': 'AMBIGUOUS', 'sourceEvidence': {'sheet': 'RR', 'range': 'B2'}},
            {'domain': 'event_settings', 'status': 'VERIFIED', 'sourceEvidence': {'sheet': 'RR', 'range': 'B3'}},
        ]}))
        params = {'intent': 'read' if mode == 'read_only' else 'write', 'commitMode': mode,
                  'domain': 'event_settings', 'rrSources': sources or ['RR!B1'], 'script': script}
        proc = subprocess.run(['node', 'ego_direct.mjs', '--runtime', str(self.folder / 'browser-runtime.json'),
                               '--operation', 'script', '--params', json.dumps(params)], cwd=self.folder,
                              env={**{k: v for k, v in os.environ.items() if not k.startswith('CVENT_')},
                                   'CASE': case, 'CVENT_ENV': 'development'}, capture_output=True, text=True, timeout=10)
        return proc, browser_tool.child_result(proc)

    def test_native_multi_action_save_readback_with_ambiguous_independent_item(self):
        proc, result = self.run_native("""
cliLog(await snapshotText());
for (const text of ['one','two']) await fillInput('@input', text);
await click('@save'); await wait(0.1); cliLog(await snapshotText());
""")
        self.assertEqual(proc.returncode, 0, result)
        self.assertEqual(result['writesAttempted'], 3)
        self.assertEqual(result['saves'], 1)
        self.assertEqual(result['readbacks'], 1)
        self.assertEqual(result['actionCount'], 6)

    def test_keyboard_and_save_inherit_provenance_in_multi_source_round(self):
        proc, result = self.run_native("await fillInput('@input','one',{rrSource:'RR!B1'}); await pressKey('Tab'); await click('@save'); cliLog(await snapshotText());", sources=['RR!B1','RR!B3'])
        self.assertEqual(proc.returncode, 0, result)
        self.assertEqual(result['saves'], 1)
        self.assertEqual(result['readbacks'], 1)
        self.assertEqual(result['actions'][1]['rrSource'], 'RR!B1')

    def test_native_edit_button_is_navigation_not_an_uncertain_write(self):
        proc, result = self.run_native("await click('@edit'); cliLog(await snapshotText());")
        self.assertEqual(proc.returncode, 0, result)
        self.assertEqual(result['writesAttempted'], 0)
        self.assertEqual(result['saves'], 0)

    def test_native_holds_only_nonverified_source_and_blocks_protected_actions(self):
        for script, error in [("await fillInput('@input','x',{rrSource:'RR!B2'})", 'VERIFIED'),
                              ("await click('@delete')", 'protected Cvent control'),
                              ("await gotoAndWait('https://app.cvent.com/view?evtstub=another')", 'outside exact'),
                              ("await fillInput('@input','x')", 'lacking Save')]:
            with self.subTest(script=script):
                proc, result = self.run_native(script)
                self.assertEqual(proc.returncode, 1)
                self.assertIn(error, result['error'])

    def test_native_readonly_and_script_errors_are_not_configuration(self):
        for script in ["await fillInput('@input','x')", "process.exit(0)", "await nonExistentHelper()"]:
            proc, result = self.run_native(script, 'read_only')
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(result['writesAttempted'], 0)

    def test_successful_multi_action_mission_reports_every_index(self):
        proc, result = self.run_adapter('success')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([a['index'] for a in result['actions']], [0, 1, 2, 3])
        self.assertEqual(result['actionCount'], 4)
        self.assertEqual(result['writesAttempted'], 0)

    def test_first_failure_preserves_real_error_and_previous_actions(self):
        for case, message in [('middle', 'real snapshot failure'), ('string', 'real non-Error failure')]:
            with self.subTest(case=case):
                proc, result = self.run_adapter(case)
                self.assertEqual(proc.returncode, 1)
                self.assertIn(message, result['error'])
                self.assertEqual(result['actionIndex'], 2)
                self.assertEqual([a['index'] for a in result['completedActions']], [0, 1])
                self.assertEqual(result['writesAttempted'], 0)

    def test_multiple_mock_writes_preserve_exact_dispatch_counts(self):
        steps = self.steps[:1] + [{'operation': 'fill', 'intent': 'write', 'target': '@123', 'text': value}
                                 for value in ('first value', 'second value')]
        proc, result = self.run_adapter('writes', steps)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(result['writesAttempted'], 2)
        self.assertEqual([a['index'] for a in result['actions']], [0, 1, 2])

    def test_dispatched_failure_counts_failed_attempt_and_retains_prior_success(self):
        steps = self.steps[:1] + [{'operation': 'fill', 'intent': 'write', 'target': '@123', 'text': value}
                                 for value in ('first value', 'fail', 'must not run')]
        proc, result = self.run_adapter('writes', steps)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('real dispatched mutation failure', result['error'])
        self.assertEqual(result['actionIndex'], 2)
        self.assertEqual(result['writesAttempted'], 2)
        self.assertEqual([a['index'] for a in result['completedActions']], [0, 1])

    def test_startup_and_postflight_errors_keep_their_scope_and_evidence(self):
        _, startup = self.run_adapter('startup')
        self.assertIn('real startup error', startup['error'])
        self.assertEqual(startup['actionIndex'], -1)
        self.assertEqual(startup['completedActions'], [])
        _, postflight = self.run_adapter('postflight')
        self.assertIn('real postflight error', postflight['error'])
        self.assertEqual(postflight['actionIndex'], 3)
        self.assertEqual([a['index'] for a in postflight['completedActions']], [0, 1, 2, 3])

    def test_proven_predispatch_error_creates_no_mutation_uncertainty(self):
        steps = self.steps[:2] + [{'operation': 'fill', 'intent': 'write', 'target': '@123', 'text': 'offline', 'rrSource': 'RR!B1'}]
        proc, result = self.run_adapter('predispatch', steps)
        self.assertIn('real target missing before dispatch', result['error'])
        self.assertEqual(result['actionIndex'], 2)
        self.assertEqual(result['writesAttempted'], 0)
        params = {'intent': 'write', 'steps': steps, 'domain': 'event_settings'}
        with patch.object(browser_tool, 'CURRENT', self.folder), \
             patch.object(browser_tool, 'action', side_effect=lambda *_: nullcontext()), \
             patch.object(browser_tool, 'guard', return_value={'url': 'https://app.cvent.com/view?evtstub=test-event'}), \
             patch.object(browser_tool.subprocess, 'run', return_value=proc):
            with self.assertRaisesRegex(RuntimeError, 'real target missing'):
                browser_tool.run_direct(self.folder / 'browser-runtime.json', self.runtime, 'ego', 'actions', params)
        self.assertFalse(mutation_outcome(self.folder)['hasAttempts'])
        self.assertFalse(mutation_outcome(self.folder)['unresolved'])

    def test_missing_adapter_result_after_dispatch_is_conservatively_uncertain(self):
        proc = subprocess.CompletedProcess([], -9, '', 'adapter killed')
        steps = [{'operation': 'fill', 'intent': 'write', 'target': '@123', 'rrSource': 'RR!B1'}]
        with patch.object(browser_tool, 'CURRENT', self.folder), \
             patch.object(browser_tool, 'action', side_effect=lambda *_: nullcontext()), \
             patch.object(browser_tool, 'guard', return_value={'url': 'https://app.cvent.com/view?evtstub=test-event'}), \
             patch.object(browser_tool.subprocess, 'run', return_value=proc):
            with self.assertRaisesRegex(RuntimeError, 'adapter killed'):
                browser_tool.run_direct(self.folder / 'browser-runtime.json', self.runtime, 'ego', 'actions', {'intent': 'write', 'steps': steps})
        self.assertTrue(mutation_outcome(self.folder)['unresolved'])


class BoundedRecoveryTests(unittest.TestCase):
    def test_dead_renderer_or_occupied_gate_never_enters_a_retry_loop(self):
        for message in ('Page crashed!', 'Browser action gate is occupied', 'ReferenceError: missing variable'):
            with self.subTest(message=message), \
                 patch.object(browser_tool, 'action', side_effect=lambda *_: nullcontext()), \
                 patch.object(browser_tool, 'local_probe', side_effect=RuntimeError(message)) as probe, \
                 patch.object(browser_tool.subprocess, 'run') as run, \
                 patch.object(browser_tool.time, 'sleep') as sleep:
                with self.assertRaisesRegex(RuntimeError, 'one bounded probe') as error:
                    browser_tool.recover_browser(Path('/offline/runtime.json'), {'browserRuntimeId': 'test'}, 'ego', {'timeoutSeconds': 240})
                self.assertIn(message, str(error.exception))
                self.assertEqual(probe.call_count, 1)
                run.assert_not_called()
                sleep.assert_not_called()

    def test_failed_recovery_adapter_is_called_once_and_preserves_cause(self):
        proc = subprocess.CompletedProcess([], 1, 'BROWSER_TOOL_RESULT=' + json.dumps({'ok': False, 'error': 'real renderer failure'}), '')
        with patch.object(browser_tool, 'action', side_effect=lambda *_: nullcontext()), \
             patch.object(browser_tool, 'local_probe', return_value={'url': 'https://app.cvent.com'}) as probe, \
             patch.object(browser_tool.subprocess, 'run', return_value=proc) as run:
            with self.assertRaisesRegex(RuntimeError, 'real renderer failure'):
                browser_tool.recover_browser(Path('/offline/runtime.json'), {'browserRuntimeId': 'test'}, 'ego', {'timeoutSeconds': 300})
            self.assertEqual(run.call_count, 1)
            self.assertEqual(probe.call_count, 1)
            self.assertLessEqual(run.call_args.kwargs['timeout'], 25)


class KilledGateTests(unittest.TestCase):
    def exercise_kill(self, mutating, child):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            gate = BrowserGate(directory)
            gate.initialize()
            code = '''
import sys,time,subprocess,json
from pathlib import Path
from browser_gate import BrowserGate,child_lock_fds
folder=Path(sys.argv[1])
with BrowserGate(folder).action('runtime','PI_EGO',sys.argv[2]=='True'):
 child=subprocess.Popen(['node','-e','setTimeout(()=>{},30000)'],pass_fds=child_lock_fds()) if sys.argv[3]=='True' else None
 (folder/'ready.json').write_text(json.dumps({'child':child.pid if child else None}))
 time.sleep(30)
'''
            process = subprocess.Popen([sys.executable, '-c', code, temp, str(mutating), str(child)],
                                       cwd=ROOT, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 5
                while not (directory / 'ready.json').exists():
                    if time.monotonic() > deadline:
                        self.fail('gate helper did not start')
                    time.sleep(.025)
                child_pid = json.loads((directory / 'ready.json').read_text())['child']
                process.kill()
                process.wait(timeout=3)
                if child:
                    with self.assertRaisesRegex(RuntimeError, 'occupied by a live helper or child'):
                        with gate.action('runtime', 'PI_EGO'):
                            self.fail('Concurrent action admitted while orphaned child lives')
                    os.kill(child_pid, signal.SIGKILL)
                started = time.monotonic()
                with gate.action('runtime', 'PI_EGO'):
                    self.assertEqual(gate.read()['activeActor'], 'PI_EGO')
                self.assertLess(time.monotonic() - started, 1)
                self.assertEqual(gate.read()['activeActor'], 'NONE')
                self.assertEqual((directory / 'browser-mutation-uncertain.json').exists(), mutating)
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=3)

    def test_killed_read_helper_releases_gate_without_uncertainty(self):
        self.exercise_kill(False, False)

    def test_orphaned_browser_child_holds_lock_until_dead(self):
        self.exercise_kill(False, True)

    def test_mutating_helper_kill_requires_readback_even_after_lock_released(self):
        self.exercise_kill(True, True)
