"""Stop keeps leases through teardown, cancels startup and preserves write safety."""
import json
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from control_store import ControlStore
from job_runner import ActiveJob, JobRunner


class StopRestartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name) / 'job'
        self.directory.mkdir()
        self.store = ControlStore(Path(self.temp.name) / 'control.db')
        self.runner = JobRunner(self.store)
        self.user = self.store.ensure_user('test', 'test@example.test', 'Test', False)
        self.event = SimpleNamespace(event_id='test-event', event_key='test-event', name='Test Event')
        self.job = self.store.create_job(self.user, self.event, 'RR.xlsx', preferred_slot=1)
        lease = self.store.reserve_now(self.job['id'], self.user['subject'])
        self.active = ActiveJob(self.job['id'], lease['token'], 1, threading.Event())
        self.runner._active[self.job['id']] = self.active

    def tearDown(self):
        self.temp.cleanup()

    def stop(self):
        self.runner.stop(self.job['id'], self.user['subject'])

    def test_startup_stop_is_idempotent_and_retains_lease_until_launch_exits(self):
        with patch('job_runner.job_dir', return_value=self.directory), patch.object(self.runner, 'steel_command') as steel:
            self.stop(); self.stop()
        steel.assert_not_called()
        self.assertTrue(self.active.stop_requested.is_set())
        self.assertFalse(self.active.stop_heartbeat.is_set())
        self.assertTrue(self.store.valid_event_lease(self.job['id'], self.active.token, 'test-event'))
        self.assertIs(self.runner.active(self.job['id']), self.active)
        with self.assertRaisesRegex(ValueError, 'cleanup'):
            self.runner.start(self.job['id'], 'test')

    def test_stop_at_each_startup_boundary_never_spawns_pi(self):
        for boundary in ['before_provider', 'provider', 'rr', 'steel', 'prompt']:
            with self.subTest(boundary=boundary):
                if boundary != 'before_provider':
                    lease = self.store.reserve_now(self.job['id'], 'test')
                    self.active = ActiveJob(self.job['id'], lease['token'], 1, threading.Event())
                    self.runner._active[self.job['id']] = self.active
                def stage(name, result):
                    if name == boundary:
                        self.stop()
                    return result
                with ExitStack() as stack:
                    stack.enter_context(patch('job_runner.job_dir', return_value=self.directory))
                    stack.enter_context(patch('job_runner.threading.Thread'))
                    stack.enter_context(patch('job_runner.write_telemetry_report'))
                    stack.enter_context(patch('job_runner.initialize_browser_runtime', return_value={}))
                    probe = stack.enter_context(patch.object(self.runner, 'verify_provider_access', side_effect=lambda *_: stage('provider', {})))
                    stack.enter_context(patch.object(self.runner, 'prepare_rr', side_effect=lambda *_: stage('rr', {})))
                    steel = stack.enter_context(patch.object(self.runner, 'steel_command', side_effect=lambda *a, **kw: stage('steel', {'running': True}) if a[3] == 'ensure' else {}))
                    stack.enter_context(patch.object(self.runner, 'render_prompt', side_effect=lambda *_: stage('prompt', 'mission')))
                    stack.enter_context(patch.object(self.runner, '_write_pi_settings'))
                    stack.enter_context(patch.object(self.runner, 'pi_command', return_value=['never-launch']))
                    popen = stack.enter_context(patch('job_runner.subprocess.Popen'))
                    if boundary == 'before_provider':
                        self.stop()
                    self.runner._launch(self.job, self.active)
                    popen.assert_not_called()
                    if boundary == 'before_provider':
                        probe.assert_not_called()
                    self.assertEqual(steel.call_args.args[3], 'release')
                self.assertIsNone(self.runner.active(self.job['id']))
                self.assertEqual(self.store.get_job(self.job['id'])['state'], 'failed_prewrite')
                self.assertEqual(json.loads((self.directory / 'state.json').read_text())['current_stage'], 'stopped')

    def test_explicit_stop_overrides_stale_login_and_success_but_not_write_safety(self):
        for attempted, unresolved, expected in [(False, False, 'failed_prewrite'), (True, False, 'failed_recoverable'), (True, True, 'failed_uncertain')]:
            with self.subTest(expected=expected):
                process = Mock(pid=123456)
                process.poll.return_value = None
                process.wait.return_value = 0
                self.active.process = process
                self.active.stop_requested.clear()
                (self.directory / 'state.json').write_text('{"status":"login_required"}')
                (self.directory / 'final-report.json').write_text('{"status":"DRAFT_COMPLETE"}')
                with patch('job_runner.job_dir', return_value=self.directory), patch.object(self.runner, '_stop_process_tree') as signal, \
                     patch.object(self.runner, 'steel_command'), patch.object(self.runner, '_finish_after_lease_loss') as finish, \
                     patch.object(self.store, 'get_job', return_value=self.job), \
                     patch('job_runner.mutation_outcome', return_value={'hasAttempts': attempted, 'unresolved': unresolved}), \
                     patch.object(self.runner, 'prepare_environment', return_value={}), \
                     patch('job_runner.subprocess.run'), patch('job_runner.write_telemetry_report'):
                    self.runner._active[self.job['id']] = self.active
                    self.stop(); self.stop()
                    signal.assert_called_once_with(process.pid)
                    self.runner._monitor(self.job, self.active)
                self.assertEqual(finish.call_args.args[2], expected)
                self.assertEqual(finish.call_args.args[4], unresolved)
                self.assertIn('Stop requested', finish.call_args.args[3])

    def test_stopping_inactive_job_is_harmless(self):
        self.runner._active.clear()
        with patch.object(self.runner, 'steel_command') as steel:
            self.stop()
        steel.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'not found'):
            self.runner.stop('missing', 'test')
