import json
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from control_store import ControlStore
from job_runner import JobRunner, classify_process_outcome
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

    def test_worker_profiles_persist_per_workspace_and_never_share_between_slots(self):
        first = self.runner.environment(self.job, "lease-token", 1)
        same = self.runner.environment(dict(self.job, id="job_next"), "lease-next", 1)
        second = self.runner.environment(self.job, "lease-token", 2)
        self.assertEqual(first["CVENT_BROWSER_PROFILE_DIR"], same["CVENT_BROWSER_PROFILE_DIR"])
        self.assertNotEqual(first["CVENT_BROWSER_PROFILE_DIR"], second["CVENT_BROWSER_PROFILE_DIR"])
        self.assertIn("browser-profiles/slot-1/chromium-profile", first["CVENT_BROWSER_PROFILE_DIR"])
        self.assertIn("browser-profiles/slot-2/chromium-profile", second["CVENT_BROWSER_PROFILE_DIR"])

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

    def test_provider_credit_failure_is_reported_without_exposing_secrets(self):
        (self.directory / "pi-output.log").write_text(
            'invalid_request_error: Your credit balance is too low to access the Anthropic API\n'
        )
        self.assertEqual(
            self.runner._provider_failure(self.directory),
            "Anthropic API credit balance is too low",
        )

    def test_controlled_incomplete_report_requires_review_instead_of_failed_prewrite(self):
        self.assertEqual(
            classify_process_outcome(0, "INCOMPLETE", "running", False, None),
            ("review_required", False, None),
        )
        self.assertEqual(
            classify_process_outcome(1, "INCOMPLETE", "running", False, None)[0],
            "failed_prewrite",
        )

    def test_failed_prewrite_retry_uses_a_fresh_session_only_without_write_evidence(self):
        job = {**self.job, "state": "failed_prewrite", "uncertain": 0, "original_filename": "rr.xlsx"}
        (self.directory / "state.json").write_text(json.dumps({
            "status": "failed_prewrite", "resume_requested": True,
            "pi_session": "old-session", "completed": ["event_basics"],
        }))
        with patch.object(self.runner.store, "get_job", return_value=job), \
             patch("job_runner.job_dir", return_value=self.directory), \
             patch.object(self.runner, "start") as start:
            self.runner.retry_prewrite(job["id"], "operator")
        state = json.loads((self.directory / "state.json").read_text())
        self.assertFalse(state["resume_requested"])
        self.assertIsNone(state["pi_session"])
        self.assertEqual(state["completed"], [])
        start.assert_called_once_with(job["id"], "operator")

        (self.directory / "scope-write-audit.jsonl").write_text("attempted\n")
        with patch.object(self.runner.store, "get_job", return_value=job), \
             patch("job_runner.job_dir", return_value=self.directory):
            with self.assertRaisesRegex(ValueError, "mutation evidence"):
                self.runner.retry_prewrite(job["id"], "operator")

    def test_prompt_has_job_paths_and_no_unresolved_placeholders(self):
        prompt = self.runner.render_prompt(self.job, self.directory, {})
        self.assertIn(str(self.directory.resolve()), prompt)
        self.assertIn(DEFAULT_EVENT_NAME, prompt)
        self.assertIn(DEFAULT_EVENT_KEY, prompt)
        self.assertNotRegex(prompt, r"{{[A-Z0-9_]+}}")


if __name__ == "__main__":
    unittest.main()
