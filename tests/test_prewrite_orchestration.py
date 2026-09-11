import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from job_runner import ActiveJob, JobRunner

ROOT = Path(__file__).resolve().parents[1]


class PrewriteOrchestrationTests(unittest.TestCase):
    def test_extension_with_fake_helpers_no_model_or_browser(self):
        result = subprocess.run(['node', str(ROOT / 'tests/prewrite_orchestration.mjs')],
                                cwd=ROOT, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_monitor_preserves_runtime_failure_even_on_clean_tool_termination(self):
        for attempted, unresolved, expected in [(False, False, 'failed_prewrite'),
                                                (True, False, 'failed_recoverable'),
                                                (True, True, 'failed_uncertain')]:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                first = {'operation': 'authStatus', 'message': 'timeout: timed out'}
                (directory / 'controller-failure-42.json').write_text(json.dumps({
                    'first': first, 'operation': 'recover', 'message': 'renderer did not recover'}))
                # Even an old success report cannot turn this failed attempt into completion.
                (directory / 'final-report.json').write_text('{"status":"DRAFT_COMPLETE"}')
                runner = JobRunner(Mock())
                runner.store.get_job.return_value = None
                active = ActiveJob('job_test', 'token', 1, threading.Event(), Mock(pid=42))
                active.process.wait.return_value = 0
                with patch('job_runner.job_dir', return_value=directory), \
                     patch('job_runner.mutation_outcome', return_value={'hasAttempts': attempted, 'unresolved': unresolved}), \
                     patch.object(runner, '_provider_failure', return_value=None), \
                     patch.object(runner, 'steel_command'), \
                     patch.object(runner, '_finish_after_lease_loss') as finish, \
                     patch.object(runner, 'prepare_environment', return_value={}), \
                     patch('job_runner.subprocess.run'):
                    runner._monitor({'id': 'job_test', 'workspace_id': 'ws_test', 'state': 'running',
                                     'original_filename': 'rr.xlsx', 'event_name': 'Test Event',
                                     'event_id': 'test-event', 'event_key': 'test-event'}, active)
                self.assertEqual(finish.call_args.args[2], expected)
                self.assertIn('authStatus: timeout: timed out', finish.call_args.args[3])
                self.assertIn('renderer did not recover', finish.call_args.args[3])

    def test_stop_is_audited_before_signal(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            runner = JobRunner(Mock())
            runner.store.get_job.return_value = {'id': 'job_test', 'workspace_id': 'ws_test'}
            active = ActiveJob('job_test', 'token', 1, threading.Event(), Mock(pid=42))
            active.process.poll.return_value = None
            runner._active['job_test'] = active

            def stop(pid):
                self.assertEqual(pid, 42)
                self.assertEqual(json.loads((directory / 'stop-request-42.json').read_text())['actor'], 'tester')
                runner.store.audit.assert_called_once()

            with patch('job_runner.job_dir', return_value=directory), \
                 patch.object(runner, '_stop_process_tree', side_effect=stop):
                runner.stop('job_test', 'tester')
