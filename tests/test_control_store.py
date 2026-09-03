import tempfile
import threading
import unittest
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

    def job(self, user_index, event_number):
        job = self.store.create_job(self.users[user_index], self.event(event_number), "rr.xlsx")
        self.store.queue_job(job["id"], self.users[user_index]["subject"])
        return job

    def test_three_different_events_get_three_isolated_slots(self):
        jobs = [self.job(i, i) for i in range(3)]
        leases = [self.store.acquire(job["id"]) for job in jobs]
        self.assertEqual({lease["slot_id"] for lease in leases if lease}, {1, 2, 3})
        self.assertEqual(len(self.store.active_leases()["events"]), 3)
        fourth = self.job(3, 4)
        self.assertIsNone(self.store.acquire(fourth["id"]))

    def test_same_event_is_serialized_even_under_race(self):
        jobs = [self.job(i, 1) for i in range(3)]
        barrier = threading.Barrier(3)
        results = []
        lock = threading.Lock()

        def acquire(job_id):
            barrier.wait()
            result = self.store.acquire(job_id)
            with lock:
                results.append(result)

        threads = [threading.Thread(target=acquire, args=(job["id"],)) for job in jobs]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(len(self.store.active_leases()["events"]), 1)

    def test_release_allows_next_same_event_job(self):
        first = self.job(0, 1)
        second = self.job(1, 1)
        lease = self.store.acquire(first["id"])
        self.assertIsNone(self.store.acquire(second["id"]))
        self.store.finish(first["id"], lease["token"], "completed")
        self.assertIsNotNone(self.store.acquire(second["id"]))

    def test_wrong_token_cannot_heartbeat_or_release_someone_elses_lease(self):
        job = self.job(0, 1)
        lease = self.store.acquire(job["id"])
        self.assertFalse(self.store.heartbeat(job["id"], "wrong"))
        with self.assertRaises(PermissionError):
            self.store.finish(job["id"], "wrong", "failed")
        active = self.store.active_leases()
        self.assertEqual(active["events"][0]["token"], lease["token"])
        self.assertEqual(active["workers"][0]["token"], lease["token"])

    def test_controller_recovery_fails_active_job_closed(self):
        job = self.job(0, 1)
        lease = self.store.acquire(job["id"])
        self.assertTrue(self.store.mark_running(job["id"], lease["token"], 12345))
        recovered = self.store.recover_after_controller_restart()
        self.assertEqual(recovered, [job["id"]])
        saved = self.store.get_job(job["id"])
        self.assertEqual(saved["state"], "failed_uncertain")
        self.assertEqual(saved["uncertain"], 1)
        self.assertEqual(self.store.active_leases(), {"events": [], "workers": []})

    def test_users_only_have_distinct_workspaces(self):
        self.assertEqual(len({user["workspace_id"] for user in self.users}), 4)
        same = self.store.ensure_user("subject-0", "changed@example.test", "Changed", True)
        self.assertEqual(same["workspace_id"], self.users[0]["workspace_id"])


if __name__ == "__main__":
    unittest.main()
