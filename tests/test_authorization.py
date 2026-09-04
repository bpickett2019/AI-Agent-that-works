import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as cvent_app
from browser_gate import BrowserGate
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

    def test_empty_worker_profile_is_selectable_without_falling_back_to_latest_job(self):
        with TestClient(cvent_app.app) as client:
            client.get("/api/me")
            response = client.get("/api/status?worker_slot=2")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "waiting_for_rr")
            self.assertEqual(response.json()["selected_worker"], 2)

    def test_mutations_require_csrf_token(self):
        with TestClient(cvent_app.app) as client:
            me = client.get("/api/me").json()
            self.assertTrue(me["csrf"])
            without = client.post("/api/start")
            self.assertEqual(without.status_code, 403)
            with_token = client.post("/api/start", headers={"X-CSRF-Token": me["csrf"]})
            self.assertEqual(with_token.status_code, 404)

    def test_development_session_secret_survives_restart(self):
        with patch.object(cvent_app, "DATA_ROOT", Path(self.temp.name)), patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CVENT_SESSION_SECRET", None)
            first = cvent_app.session_secret()
            second = cvent_app.session_secret()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        self.assertEqual((Path(self.temp.name) / ".development-session-secret").stat().st_mode & 0o777, 0o600)

    def test_return_to_agent_verifies_and_persists_slot_profile_automatically(self):
        with TestClient(cvent_app.app) as client:
            me = client.get("/api/me").json()
            headers = {"X-CSRF-Token": me["csrf"]}
            user = self.store.ensure_user("dev:user-one", "one@example.test", "User One", False)
            job = self.make_job(user, "handoff")
            directory = Path(self.temp.name) / "handoff"
            profile = Path(self.temp.name) / "browser-profiles" / "slot-1" / "chromium-profile"
            metadata_path = profile.parent / "auth-profile.json"
            profile.mkdir(parents=True)
            gate = BrowserGate(directory);gate.initialize()
            runtime = {
                "browserRuntimeId": "runtime-test", "providerSessionId": "steel-test", "workerSlot": 1,
                "profilePath": str(profile), "cdpHttpOrigin": "http://127.0.0.1:9334",
                "targetBrowserIdentity": {"targetId": "target-test"},
            }
            process = SimpleNamespace(pid=98765, poll=lambda: None)
            active = SimpleNamespace(slot_id=1, process=process)
            page = {"id": "target-test", "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/target-test"}
            cookies = {"cookies": [
                {"name": "org-id", "value": "organization-test", "domain": ".cvent.com", "session": False},
                {"name": "ESTSAUTHPERSISTENT", "value": "redacted", "domain": ".login.microsoftonline.com", "session": False},
            ]}
            ui = {"result": {"value": {"ready": "complete", "title": "Events", "hasUi": True, "hasLogin": False}}}
            with patch.object(cvent_app, "directory_for", return_value=directory), \
                 patch.object(cvent_app, "active_job", return_value=active), \
                 patch.object(cvent_app, "browser_profile_dir", return_value=profile), \
                 patch.object(cvent_app, "browser_auth_metadata_path", return_value=metadata_path), \
                 patch.object(cvent_app, "load_browser_runtime", return_value=runtime), \
                 patch.object(cvent_app, "browser_pages", return_value=[page]), \
                 patch.object(cvent_app, "select_page", return_value=page), \
                 patch.object(cvent_app, "local_probe", return_value={"url": "https://app.cvent.com/Subscribers/Events2/EventSelection", "title": "Events", "marker": "runtime-test", "targetId": "target-test"}), \
                 patch.object(cvent_app, "browser_command", side_effect=[cookies, ui]), \
                 patch.object(cvent_app.os, "killpg"):
                take = client.post(f"/api/browser/take-control?job_id={job['id']}", headers=headers)
                self.assertEqual(take.status_code, 200)
                returned = client.post(f"/api/browser/return-to-agent?job_id={job['id']}", headers=headers)
                self.assertEqual(returned.status_code, 200)
                self.assertTrue(returned.json()["verified"])
                self.assertEqual(gate.read()["ownership"], "AGENT")
                persisted = json.loads(metadata_path.read_text())
                self.assertEqual(persisted["workerSlot"], 1)
                self.assertTrue(persisted["authenticated"])
                self.assertEqual(persisted["profilePath"], str(profile))
                self.assertFalse(set(persisted) & {"password", "otp", "mfa", "cookies", "token"})
                self.assertTrue((directory / "auth-settings.json").exists())
                self.assertNotEqual(client.post("/api/start", headers=headers).status_code, 403)

    def test_incomplete_login_keeps_user_control_and_persists_nothing(self):
        with TestClient(cvent_app.app) as client:
            me = client.get("/api/me").json()
            user = self.store.ensure_user("dev:user-one", "one@example.test", "User One", False)
            job = self.make_job(user, "incomplete-login")
            directory = Path(self.temp.name) / "incomplete-login"
            metadata_path = Path(self.temp.name) / "slot-1" / "auth-profile.json"
            gate = BrowserGate(directory); gate.initialize()
            value = gate.read(); value.update({"ownership": "USER", "desiredOwnership": "USER"}); gate.write(value)
            active = SimpleNamespace(slot_id=1, process=SimpleNamespace(pid=98765, poll=lambda: None))
            with patch.object(cvent_app, "directory_for", return_value=directory), \
                 patch.object(cvent_app, "active_job", return_value=active), \
                 patch.object(cvent_app, "browser_auth_metadata_path", return_value=metadata_path), \
                 patch.object(cvent_app, "verify_authenticated_cvent", side_effect=RuntimeError("not authenticated")):
                response = client.post(f"/api/browser/return-to-agent?job_id={job['id']}",
                                       headers={"X-CSRF-Token": me["csrf"]})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["detail"], "Cvent login is not complete. Finish SSO/MFA before returning control.")
            self.assertEqual(gate.read()["ownership"], "USER")
            self.assertFalse(metadata_path.exists())

    def test_reset_login_clears_only_selected_slot(self):
        with TestClient(cvent_app.app) as client:
            me = client.get("/api/me").json()
            roots = {}
            for slot in (1, 2):
                profile = Path(self.temp.name) / "profiles" / f"slot-{slot}" / "chromium-profile"
                profile.mkdir(parents=True)
                (profile / "state").write_text("isolated")
                roots[slot] = profile
            with patch.object(cvent_app, "browser_profile_dir", side_effect=lambda _workspace, slot: roots[slot]):
                response = client.post("/api/browser/reset-login", json={"worker_slot": 1},
                                       headers={"X-CSRF-Token": me["csrf"]})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(roots[1].parent.exists())
            self.assertTrue(roots[2].exists())

    def test_return_to_agent_clears_stale_user_gate_after_login_process_exits(self):
        with TestClient(cvent_app.app) as client:
            me = client.get("/api/me").json()
            user = self.store.ensure_user("dev:user-one", "one@example.test", "User One", False)
            job = self.make_job(user, "stale-return")
            self.store.finish(job["id"], None, "login_required", None, False)
            directory = Path(self.temp.name) / "stale-return-job"
            gate = BrowserGate(directory);gate.initialize()
            value = gate.read();value.update({"ownership": "USER", "desiredOwnership": "USER", "activeActor": "USER"});gate.write(value)
            with patch.object(cvent_app, "directory_for", return_value=directory), patch.object(cvent_app, "active_job", return_value=None):
                response = client.post(
                    f"/api/browser/return-to-agent?job_id={job['id']}",
                    headers={"X-CSRF-Token": me["csrf"]},
                )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["staleReset"])
            self.assertEqual(gate.read()["ownership"], "AGENT")

    def test_continue_resets_stale_user_gate_after_login_process_exits(self):
        with TestClient(cvent_app.app) as client:
            me = client.get("/api/me").json()
            user = self.store.ensure_user("dev:user-one", "one@example.test", "User One", False)
            job = self.make_job(user, "resume")
            directory = Path(self.temp.name) / "stale-login-job"
            gate = BrowserGate(directory)
            gate.initialize()
            value = gate.read()
            value.update({"ownership": "USER", "desiredOwnership": "USER", "activeActor": "USER"})
            gate.write(value)
            with patch.object(cvent_app, "directory_for", return_value=directory), \
                 patch.object(cvent_app, "active_job", return_value=None), \
                 patch.object(cvent_app.runner, "resume") as resume:
                response = client.post(
                    f"/api/continue?job_id={job['id']}",
                    headers={"X-CSRF-Token": me["csrf"]},
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(gate.read()["ownership"], "AGENT")
            resume.assert_called_once_with(job["id"], "dev:user-one")

    def test_start_returns_immediate_409_for_busy_event_or_capacity(self):
        with TestClient(cvent_app.app) as client:
            me = client.get("/api/me").json()
            user = self.store.ensure_user("dev:user-one", "one@example.test", "User One", False)
            job = self.make_job(user, "busy")
            directory = Path(self.temp.name) / "busy-start"
            directory.mkdir()
            (directory / "input.xlsx").touch()
            BrowserGate(directory).initialize()
            headers = {"X-CSRF-Token": me["csrf"]}
            for message in (
                "Event is busy; another job holds the canonical event lease",
                "All three worker slots are busy",
            ):
                with patch.object(cvent_app, "directory_for", return_value=directory), \
                     patch.object(cvent_app, "scope_summary", return_value={"valid": True}), \
                     patch.object(cvent_app.runner, "start", side_effect=ValueError(message)):
                    response = client.post(f"/api/start?job_id={job['id']}", headers=headers)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["detail"], message)

    def test_unauthenticated_api_is_rejected(self):
        del os.environ["CVENT_DEV_AUTH_SUBJECT"]
        with TestClient(cvent_app.app) as client:
            self.assertEqual(client.get("/api/me").status_code, 401)


if __name__ == "__main__":
    unittest.main()
