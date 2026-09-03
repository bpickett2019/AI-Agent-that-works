import json
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from control_store import ControlStore
from job_runner import JobRunner
from runtime_config import DEFAULT_EVENT_KEY, DEFAULT_EVENT_NAME


class JobRunnerConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name) / "job"
        self.directory.mkdir()
        self.runner = JobRunner(ControlStore(Path(self.temp.name) / "control.db"))
        self.job = {
            "id": "job_test", "workspace_id": "ws_test", "event_id": DEFAULT_EVENT_KEY,
            "event_name": DEFAULT_EVENT_NAME, "event_key": DEFAULT_EVENT_KEY,
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_pi_command_is_explicit_anthropic_and_never_contains_key(self):
        command = self.runner.pi_command(self.job, self.directory, {}, "job prompt")
        self.assertEqual(command[command.index("--provider") + 1], "anthropic")
        self.assertEqual(command[command.index("--model") + 1], "claude-sonnet-4-6")
        self.assertNotIn("--api-key", command)
        self.assertNotIn("ANTHROPIC_API_KEY", " ".join(command))
        self.assertIn("--no-builtin-tools", command)
        extension = command[command.index("--extension") + 1]
        self.assertTrue(extension.endswith("extensions/cvent-job-tools.ts"))
        tools = set(command[command.index("--tools") + 1].split(","))
        self.assertNotIn("read", tools)
        self.assertNotIn("bash", tools)
        self.assertEqual(tools, {
            "cvent_prepare_rr", "cvent_expectations", "cvent_scope", "cvent_job_read",
            "cvent_job_update", "cvent_record_domain", "cvent_browser", "cvent_login_handoff",
            "cvent_snapshot_chunk", "cvent_finish",
        })
        self.assertEqual(command[-1], "job prompt")

    def test_pi_environment_excludes_application_auth_secrets(self):
        with patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "provider-key",
            "ENTRA_CLIENT_SECRET": "entra-secret",
            "CVENT_SESSION_SECRET": "session-secret",
            "AZURE_CLIENT_SECRET": "azure-secret",
        }):
            environment = self.runner.pi_environment(self.job, "lease-token", 1)
        self.assertEqual(environment["ANTHROPIC_API_KEY"], "provider-key")
        self.assertEqual(environment["CVENT_LEASE_TOKEN"], "lease-token")
        self.assertNotIn("ENTRA_CLIENT_SECRET", environment)
        self.assertNotIn("CVENT_SESSION_SECRET", environment)
        self.assertNotIn("AZURE_CLIENT_SECRET", environment)

    def test_pi_config_bounds_429_retry_behavior(self):
        self.runner._write_pi_settings(self.directory)
        settings = json.loads((self.directory / "pi-config" / "settings.json").read_text())
        self.assertEqual(settings["retry"]["maxRetries"], 3)
        self.assertEqual(settings["retry"]["baseDelayMs"], 2000)
        self.assertEqual(settings["retry"]["provider"]["maxRetries"], 0)
        self.assertEqual(settings["retry"]["provider"]["maxRetryDelayMs"], 60000)

    def test_prompt_has_job_paths_and_no_unresolved_placeholders(self):
        prompt = self.runner.render_prompt(self.job, self.directory, {})
        self.assertIn(str(self.directory.resolve()), prompt)
        self.assertIn(DEFAULT_EVENT_NAME, prompt)
        self.assertIn(DEFAULT_EVENT_KEY, prompt)
        self.assertNotRegex(prompt, r"{{[A-Z0-9_]+}}")


if __name__ == "__main__":
    unittest.main()
