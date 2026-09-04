import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import browser_tool
from control_store import ControlStore


class BrowserEventLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ControlStore(Path(self.temp.name) / "control.db")
        user = self.store.ensure_user("subject", "user@example.test", "User", False)
        event = SimpleNamespace(event_id="event-one", event_key="event-one", name="Event One")
        self.job = self.store.create_job(user, event, "rr.xlsx")
        self.lease = self.store.reserve_now(self.job["id"], user["subject"])
        self.runtime = {"authorizedEventId": "event-one"}

    def tearDown(self):
        self.temp.cleanup()

    def environment(self, token=None):
        return patch.dict(os.environ, {
            "CVENT_ENV": "production",
            "CVENT_JOB_ID": self.job["id"],
            "CVENT_LEASE_TOKEN": token or self.lease["token"],
            "CVENT_LEASE_VALIDATE_URL": "http://127.0.0.1/internal-test",
        })

    def validator(self, _url, job_id, token, event_id):
        return self.store.valid_event_lease(job_id, token, event_id)

    def test_current_owner_can_pass_write_lease_check(self):
        with self.environment(), patch.object(browser_tool, "lease_is_valid", side_effect=self.validator):
            browser_tool.assert_event_lease(self.runtime)

    def test_wrong_or_released_lease_fails_closed(self):
        with self.environment("wrong"), patch.object(browser_tool, "lease_is_valid", side_effect=self.validator):
            with self.assertRaisesRegex(RuntimeError, "canonical event lease"):
                browser_tool.assert_event_lease(self.runtime)
        self.store.finish(self.job["id"], self.lease["token"], "completed")
        with self.environment(), patch.object(browser_tool, "lease_is_valid", side_effect=self.validator):
            with self.assertRaisesRegex(RuntimeError, "canonical event lease"):
                browser_tool.assert_event_lease(self.runtime)

    def test_event_identity_mismatch_fails_closed(self):
        with self.environment(), patch.object(browser_tool, "lease_is_valid", side_effect=self.validator):
            with self.assertRaisesRegex(RuntimeError, "mismatched"):
                browser_tool.assert_event_lease({"authorizedEventId": "another-event"})


if __name__ == "__main__":
    unittest.main()
