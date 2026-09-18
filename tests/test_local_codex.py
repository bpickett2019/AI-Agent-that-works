import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from control_store import ControlStore
from job_runner import JobRunner
from local_codex import codex_environment, require_local_codex
from runtime_config import pi_model, pi_provider


LOCAL = {"CVENT_ENV": "development", "CVENT_LOCAL_CODEX": "1", "CVENT_EXECUTION_MODE": "simple",
         "CVENT_PI_PROVIDER": "openai-codex", "CVENT_PI_MODEL": "gpt-6-astra"}


class LocalCodexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.runner = JobRunner(ControlStore(self.root / "control.db"))
        self.job = {"id": "job_test", "workspace_id": "ws_test", "event_id": "test", "event_key": "test", "event_name": "Test"}

    def tearDown(self):
        self.temp.cleanup()

    def test_local_provider_model_and_settings(self):
        with patch.dict(os.environ, LOCAL, clear=True):
            self.assertEqual(pi_provider(), "openai-codex")
            self.assertEqual(pi_model(), "gpt-6-astra")
            self.runner._write_pi_settings(self.root)
            command = self.runner.pi_command(self.job, self.root, {}, "mission")
        settings = json.loads((self.root / "pi-config/settings.json").read_text())
        self.assertEqual(settings["defaultProvider"], "openai-codex")
        self.assertEqual(settings["defaultModel"], "gpt-6-astra")
        self.assertEqual(command[0], "node")
        self.assertTrue(command[1].endswith("run_pi_codex.mjs"))
        self.assertEqual(command[-2:], ["--job", "mission"])
        self.assertNotIn("--api-key", command)
        self.assertFalse((self.root / "pi-config/auth.json").exists())

    def test_codex_rejected_outside_explicit_local_simple_mode(self):
        for overrides in ({"CVENT_ENV": "production"}, {"CVENT_ENV": "staging"},
                          {"CVENT_LOCAL_CODEX": "0"}, {"CVENT_EXECUTION_MODE": "controlled"},
                          {"CVENT_DEPLOYMENT_SCOPE": "rg-chartdarts-stg"},
                          {"CVENT_STAGING_RESTRICTED_ACCESS": "1"}):
            with self.subTest(overrides=overrides), patch.dict(os.environ, {**LOCAL, **overrides}, clear=True):
                with self.assertRaises(RuntimeError):
                    require_local_codex()
                with self.assertRaises(RuntimeError):
                    pi_provider()

    def test_wrong_model_rejected_without_fallback(self):
        with patch.dict(os.environ, {**LOCAL, "CVENT_PI_MODEL": "gpt-5.4"}, clear=True):
            with self.assertRaises(RuntimeError):
                pi_model()

    def test_auth_file_requires_private_permissions_and_oauth(self):
        auth = self.root / "auth.json"
        auth.write_text(json.dumps({"openai-codex": {"type": "oauth", "access": "synthetic", "refresh": "synthetic"}}))
        auth.chmod(0o644)
        with patch.dict(os.environ, {**LOCAL, "CVENT_PI_AUTH_FILE": str(auth)}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "private"):
                codex_environment(self.root)
            auth.chmod(0o600)
            auth.write_text('{}')
            with self.assertRaisesRegex(RuntimeError, "login unavailable"):
                codex_environment(self.root)

    def test_probe_excludes_app_and_api_secrets_and_records_model(self):
        credentials = {"CVENT_PI_AUTH_FILE": "/private/synthetic/auth.json"}
        completed = subprocess.CompletedProcess([], 0, '{"ok":true,"classification":"usable"}\n', '')
        with patch.dict(os.environ, {**LOCAL, "ANTHROPIC_API_KEY": "secret", "ENTRA_CLIENT_SECRET": "secret"}, clear=True), \
             patch('job_runner.codex_environment', return_value=credentials), \
             patch('job_runner.subprocess.run', return_value=completed) as run:
            result = self.runner.verify_provider_access(self.root)
        self.assertEqual(result['provider'], 'openai-codex')
        self.assertEqual(result['model'], 'gpt-6-astra')
        self.assertNotIn('ANTHROPIC_API_KEY', run.call_args.kwargs['env'])
        self.assertNotIn('ENTRA_CLIENT_SECRET', run.call_args.kwargs['env'])
        self.assertEqual(run.call_args.args[0][-1], '--probe')

    def test_wrong_provider_probe_cache_cannot_skip_codex_check(self):
        from job_runner import now
        (self.root/'provider-probe.json').write_text(json.dumps({
            'ok': True, 'provider': 'anthropic', 'model': 'claude-sonnet-4-6', 'checkedAt': now()}))
        completed = subprocess.CompletedProcess([], 1, '{"ok":false,"classification":"codex_unavailable"}', '')
        with patch.dict(os.environ, LOCAL, clear=True), patch('job_runner.codex_environment', return_value={}), \
             patch('job_runner.subprocess.run', return_value=completed) as run:
            with self.assertRaisesRegex(RuntimeError, 'codex_unavailable'):
                self.runner.verify_provider_access(self.root)
            self.assertEqual(run.call_count, 1)

    def test_codex_worker_keeps_job_isolation_and_strips_api_keys(self):
        with patch.dict(os.environ, {**LOCAL, 'ANTHROPIC_API_KEY':'secret','OPENAI_API_KEY':'secret'}, clear=True), \
             patch('job_runner.codex_environment', return_value={'CVENT_PI_AUTH_FILE':'/private/synthetic/auth.json'}):
            env = self.runner.pi_environment(self.job, 'synthetic-lease', 1)
        self.assertNotIn('ANTHROPIC_API_KEY', env)
        self.assertNotIn('OPENAI_API_KEY', env)
        self.assertIn('/job_test/pi-config', env['PI_CODING_AGENT_DIR'])
        self.assertEqual(env['CVENT_LEASE_TOKEN'], 'synthetic-lease')

    def test_codex_resume_keeps_job_session(self):
        sessions = self.root/'pi-sessions'; sessions.mkdir()
        saved = sessions/'prior.jsonl'; saved.write_text('{}\n')
        with patch.dict(os.environ, LOCAL, clear=True):
            command = self.runner.pi_command(self.job,self.root,{'resume_requested':True},'mission')
        self.assertEqual(command[command.index('--session')+1], str(saved))
        self.assertIn('mission', command[-1])

    def test_probe_timeout_fails_closed(self):
        with patch.dict(os.environ, LOCAL, clear=True), patch('job_runner.codex_environment', return_value={}), \
             patch('job_runner.subprocess.run', side_effect=subprocess.TimeoutExpired('node',60)):
            with self.assertRaisesRegex(RuntimeError,'probe_unavailable'):
                self.runner.verify_provider_access(self.root)
        self.assertFalse(json.loads((self.root/'provider-probe.json').read_text())['ok'])

    def test_sdk_launcher_syntax(self):
        path = Path(__file__).resolve().parents[1]/'scripts/run_pi_codex.mjs'
        result = subprocess.run(['node','--check',str(path)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
