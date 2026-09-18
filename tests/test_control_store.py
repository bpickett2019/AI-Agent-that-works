import json
import subprocess
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from control_store import ControlStore


class ControlStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ControlStore(Path(self.temp.name) / "control.db", lease_seconds=30)
        self.users = [
            self.store.ensure_user(f"subject-{i}", f"user{i}@example.test", f"User {i}", i == 0)
            for i in range(4)
        ]

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def event(number):
        return SimpleNamespace(
            event_id=f"event-{number}", event_key=f"event-{number}", name=f"Authorized event {number}"
        )

    def job(self, user_index, event_number, preferred_slot=None):
        return self.store.create_job(
            self.users[user_index], self.event(event_number), "rr.xlsx", preferred_slot=preferred_slot
        )

    def reserve(self, job, user_index):
        return self.store.reserve_now(job["id"], self.users[user_index]["subject"])

    def assert_ui_preserves_error(self, message):
        # Exercise the unchanged frontend formatter, not a duplicate of its logic.
        template = Path(__file__).resolve().parents[1] / 'templates/index.html'
        formatter = next(line for line in template.read_text().splitlines() if line.startswith('function friendlyError('))
        rendered = subprocess.check_output(['node', '-e', formatter + '\nconsole.log(friendlyError(' + json.dumps(message) + '));'], text=True).strip()
        self.assertEqual(rendered, message)
        self.assertNotIn('USER 1 is busy', rendered)

    def last_rejection(self):
        with self.store.connect() as conn:
            row = conn.execute("SELECT details_json FROM audit_log WHERE action='job.start_rejected' ORDER BY id DESC LIMIT 1").fetchone()
        return json.loads(row[0])

    def test_preferred_worker_is_honored_without_spilling_to_another_slot(self):
        first = self.job(0, 1, preferred_slot=2)
        lease = self.reserve(first, 0)
        self.assertEqual(lease["slot_id"], 2)
        blocked = self.job(1, 2, preferred_slot=2)
        with self.assertRaisesRegex(ValueError, "Worker slot 2 is reserved: starting browser/agent") as error:
            self.reserve(blocked, 1)
        self.assert_ui_preserves_error(str(error.exception))
        details = self.last_rejection()
        self.assertEqual(details['requested_slot'], 2)
        self.assertEqual(details['blockers'][0]['job_id'], first['id'])
        self.assertEqual(details['blockers'][0]['slot_id'], 2)
        self.assertNotIn(lease['token'], json.dumps(details))
        self.assertNotIn(first['id'], str(error.exception))
        self.assertEqual(self.store.get_job(blocked["id"])["state"], "draft")

    def test_three_different_events_start_and_fourth_is_immediately_rejected(self):
        jobs = [self.job(i, i) for i in range(3)]
        leases = [self.reserve(job, i) for i, job in enumerate(jobs)]
        self.assertEqual({lease["slot_id"] for lease in leases}, {1, 2, 3})
        self.assertEqual(len(self.store.active_leases()["events"]), 3)
        fourth = self.job(3, 4)
        with self.assertRaisesRegex(ValueError, "No worker slots are free") as error:
            self.reserve(fourth, 3)
        self.assert_ui_preserves_error(str(error.exception))
        self.assertEqual([item['slot_id'] for item in self.last_rejection()['blockers']], [1, 2, 3])
        self.assertEqual(self.store.get_job(fourth["id"])["state"], "draft")

    def test_same_event_race_has_one_winner_and_immediate_busy_rejections(self):
        jobs = [self.job(i, 1) for i in range(3)]
        barrier = threading.Barrier(3)
        results = []
        lock = threading.Lock()

        def reserve(job, user_index):
            barrier.wait()
            try:
                result = ("started", self.reserve(job, user_index))
            except ValueError as exc:
                result = ("rejected", str(exc))
            with lock:
                results.append(result)

        threads = [threading.Thread(target=reserve, args=(job, i)) for i, job in enumerate(jobs)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(status == "started" for status, _ in results), 1)
        errors = [value for status, value in results if status == "rejected"]
        self.assertEqual(len(errors), 2)
        self.assertTrue(all("This event is reserved" in error for error in errors))
        states = [self.store.get_job(job["id"])["state"] for job in jobs]
        self.assertEqual(states.count("starting"), 1)
        self.assertEqual(states.count("draft"), 2)

    def test_busy_reason_distinguishes_login_handoff_and_agent_execution(self):
        first = self.job(0, 1, preferred_slot=2)
        lease = self.reserve(first, 0)
        self.store.mark_running(first['id'], lease['token'], 12345)
        blocked = self.job(1, 2, preferred_slot=2)
        directory = Path(self.temp.name) / 'workspaces' / first['workspace_id'] / 'jobs' / first['id']
        directory.mkdir(parents=True)
        for ownership, status, expected in [('USER','login_required','waiting for Cvent sign-in'), ('USER','running','waiting for browser control'), ('AGENT','running','agent running')]:
            with self.subTest(ownership=ownership, status=status):
                (directory/'browser-gate.json').write_text(json.dumps({'ownership':ownership}))
                (directory/'state.json').write_text(json.dumps({'status':status}))
                with self.assertRaises(ValueError) as error:
                    self.reserve(blocked, 1)
                self.assertIn(expected, str(error.exception))
                self.assert_ui_preserves_error(str(error.exception))
                self.assertEqual(self.last_rejection()['blockers'][0]['phase'], expected)
                self.assertTrue(self.store.valid_event_lease(first['id'], lease['token'], 'event-1'))
        self.store.finish(first['id'], lease['token'], 'login_required')
        self.assertEqual(self.reserve(blocked, 1)['slot_id'], 2)

    def test_same_event_rejection_reports_actual_holder_not_requested_slot(self):
        first = self.job(0, 1, preferred_slot=2)
        lease = self.reserve(first, 0)
        blocked = self.job(1, 1, preferred_slot=3)
        with self.assertRaises(ValueError) as error:
            self.reserve(blocked, 1)
        self.assertIn('This event is reserved on worker slot 2', str(error.exception))
        self.assert_ui_preserves_error(str(error.exception))
        details = self.last_rejection()
        self.assertEqual(details['reason'], 'event_busy')
        self.assertEqual(details['requested_slot'], 3)
        self.assertEqual(details['blockers'][0]['job_id'], first['id'])
        self.assertTrue(self.store.valid_event_lease(first['id'], lease['token'], 'event-1'))

    def test_cancelled_preworker_job_can_be_started_again(self):
        job = self.job(0, 1)
        self.store.finish(job["id"], None, "cancelled", "Cancelled before worker acquisition", False)
        lease = self.reserve(job, 0)
        self.assertIsNotNone(lease)
        self.assertEqual(self.store.get_job(job["id"])["state"], "starting")

    def test_release_allows_next_same_event_job(self):
        first = self.job(0, 1)
        second = self.job(1, 1)
        lease = self.reserve(first, 0)
        with self.assertRaisesRegex(ValueError, "This event is reserved"):
            self.reserve(second, 1)
        self.assertEqual(self.store.get_job(second["id"])["state"], "draft")
        self.store.finish(first["id"], lease["token"], "completed")
        self.assertIsNotNone(self.reserve(second, 1))

    def test_stale_prewrite_holder_is_failed_and_successor_starts(self):
        first = self.job(0, 1)
        successor = self.job(1, 1)
        different = self.job(2, 2)
        first_lease = self.reserve(first, 0)
        different_lease = self.reserve(different, 2)
        self.assertTrue(self.store.mark_running(first["id"], first_lease["token"], 11111))
        self.assertTrue(self.store.mark_running(different["id"], different_lease["token"], 33333))
        expired = datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat()
        with self.store.immediate() as conn:
            conn.execute("UPDATE event_leases SET expires_at=? WHERE holder_job_id=?", (expired, first["id"]))
            conn.execute("UPDATE worker_leases SET expires_at=? WHERE holder_job_id=?", (expired, first["id"]))
        successor_lease = self.reserve(successor, 1)
        crashed = self.store.get_job(first["id"])
        self.assertEqual(crashed["state"], "failed_prewrite")
        self.assertEqual(crashed["uncertain"], 0)
        self.assertTrue(self.store.valid_event_lease(successor["id"], successor_lease["token"], "event-1"))
        self.assertTrue(self.store.valid_event_lease(different["id"], different_lease["token"], "event-2"))

    def test_wrong_token_cannot_heartbeat_or_release_another_lease(self):
        job = self.job(0, 1)
        lease = self.reserve(job, 0)
        self.assertFalse(self.store.heartbeat(job["id"], "wrong"))
        with self.assertRaises(PermissionError):
            self.store.finish(job["id"], "wrong", "failed")
        active = self.store.active_leases()
        self.assertEqual(active["events"][0]["token"], lease["token"])
        self.assertEqual(active["workers"][0]["token"], lease["token"])

    def write_attempt(self, job):
        directory = Path(self.temp.name) / "workspaces" / job["workspace_id"] / "jobs" / job["id"]
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "scope-write-audit.jsonl").write_text('{"result":"attempted"}\n')

    def test_controller_recovery_before_first_write_is_safely_restartable(self):
        job = self.job(0, 1)
        lease = self.reserve(job, 0)
        self.assertTrue(self.store.mark_running(job["id"], lease["token"], 12345))
        self.assertEqual(self.store.recover_after_controller_restart(), [job["id"]])
        saved = self.store.get_job(job["id"])
        self.assertEqual(saved["state"], "failed_prewrite")
        self.assertEqual(saved["uncertain"], 0)
        self.assertIsNotNone(self.reserve(job, 0))

    def test_controller_recovery_after_conclusive_write_readback_is_recoverable(self):
        job = self.job(0, 1)
        lease = self.reserve(job, 0)
        self.assertTrue(self.store.mark_running(job["id"], lease["token"], 12345))
        directory = Path(self.temp.name) / "workspaces" / job["workspace_id"] / "jobs" / job["id"]
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "scope-write-audit.jsonl").write_text(
            '{"operation":"fill","rrSource":"Sheet!A1","result":"attempted"}\n'
            '{"operation":"fill","rrSource":"Sheet!A1","result":"succeeded"}\n'
        )
        self.store.recover_after_controller_restart()
        saved = self.store.get_job(job["id"])
        self.assertEqual(saved["state"], "failed_recoverable")
        self.assertEqual(saved["uncertain"], 0)
        self.assertIsNotNone(self.reserve(job, 0))

    def test_controller_recovery_after_write_attempt_remains_uncertain(self):
        job = self.job(0, 1)
        lease = self.reserve(job, 0)
        self.assertTrue(self.store.mark_running(job["id"], lease["token"], 12345))
        self.write_attempt(job)
        self.store.recover_after_controller_restart()
        saved = self.store.get_job(job["id"])
        self.assertEqual(saved["state"], "failed_uncertain")
        self.assertEqual(saved["uncertain"], 1)
        with self.assertRaisesRegex(ValueError, "current state"):
            self.reserve(job, 0)

    def test_legacy_queued_jobs_are_cancelled_without_running(self):
        job = self.job(0, 1)
        with self.store.immediate() as conn:
            conn.execute("UPDATE jobs SET state='queued',queued_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), job["id"]))
        self.assertEqual(self.store.cancel_legacy_queued_jobs(), [job["id"]])
        saved = self.store.get_job(job["id"])
        self.assertEqual(saved["state"], "cancelled")
        self.assertEqual(self.store.active_leases(), {"events": [], "workers": []})
        self.assertIsNotNone(self.reserve(job, 0))

    def test_users_only_have_distinct_workspaces(self):
        self.assertEqual(len({user["workspace_id"] for user in self.users}), 4)
        same = self.store.ensure_user("subject-0", "changed@example.test", "Changed", True)
        self.assertEqual(same["workspace_id"], self.users[0]["workspace_id"])


if __name__ == "__main__":
    unittest.main()
