import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as cvent_app
from control_store import ControlStore
from runtime_config import AuthorizedEvent


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ControlStore(Path(self.temp.name) / "control.db")
        self.old_store = cvent_app.store
        cvent_app.store = self.store
        self.scheduler = patch.object(cvent_app.runner, "start_scheduler", return_value=[])
        self.shutdown = patch.object(cvent_app.runner, "shutdown", return_value=None)
        self.scheduler.start()
        self.shutdown.start()
        self.environment = patch.dict(os.environ, {
            "CVENT_DEV_AUTH_SUBJECT": "user-one",
            "CVENT_DEV_AUTH_EMAIL": "one@example.test",
            "CVENT_DEV_AUTH_NAME": "User One",
            "CVENT_DEV_AUTH_ADMIN": "0",
        })
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.shutdown.stop()
        self.scheduler.stop()
        cvent_app.store = self.old_store
        self.temp.cleanup()

    def make_job(self, user, suffix):
        event = AuthorizedEvent(f"event-{suffix}", f"Event {suffix}", f"event-{suffix}")
        job = self.store.create_job(user, event, "rr.xlsx")
        directory = Path(self.temp.name) / job["workspace_id"] / job["id"]
        # Route authorization is checked before any workspace path is read.
        return job

    def test_user_cannot_read_another_users_job_and_admin_can(self):
        with TestClient(cvent_app.app) as first:
            me_one = first.get("/api/me").json()
            user_one = self.store.ensure_user("dev:user-one", "one@example.test", "User One", False)
            own = self.make_job(user_one, "one")
            self.assertEqual(first.get(f"/api/status?job_id={own['id']}").status_code, 200)

            os.environ["CVENT_DEV_AUTH_SUBJECT"] = "user-two"
            os.environ["CVENT_DEV_AUTH_EMAIL"] = "two@example.test"
            with TestClient(cvent_app.app) as second:
                second.get("/api/me")
                user_two = self.store.ensure_user("dev:user-two", "two@example.test", "User Two", False)
                other = self.make_job(user_two, "two")
                self.assertEqual(first.get(f"/api/status?job_id={other['id']}").status_code, 404)
                self.assertEqual(second.get(f"/api/status?job_id={own['id']}").status_code, 404)
                self.assertEqual(second.get("/api/admin/jobs").status_code, 403)

            os.environ["CVENT_DEV_AUTH_SUBJECT"] = "administrator"
            os.environ["CVENT_DEV_AUTH_ADMIN"] = "1"
            with TestClient(cvent_app.app) as admin:
                response = admin.get("/api/admin/jobs")
                self.assertEqual(response.status_code, 200)
                self.assertEqual({job["id"] for job in response.json()}, {own["id"], other["id"]})

    def test_mutations_require_csrf_token(self):
        with TestClient(cvent_app.app) as client:
            me = client.get("/api/me").json()
            self.assertTrue(me["csrf"])
            without = client.post("/api/start")
            self.assertEqual(without.status_code, 403)
            with_token = client.post("/api/start", headers={"X-CSRF-Token": me["csrf"]})
            self.assertEqual(with_token.status_code, 404)

    def test_unauthenticated_api_is_rejected(self):
        del os.environ["CVENT_DEV_AUTH_SUBJECT"]
        with TestClient(cvent_app.app) as client:
            self.assertEqual(client.get("/api/me").status_code, 401)


if __name__ == "__main__":
    unittest.main()
