import json
import tempfile
import unittest
from pathlib import Path

from telemetry_report import build_telemetry_report, write_telemetry_report


class PersistedTelemetryReportTests(unittest.TestCase):
    def test_persisted_browser_counts_replace_stale_model_zeroes(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            root = directory / "release"
            root.mkdir()
            (root / ".deployed-git-sha").write_text("a" * 40)
            (directory / "state.json").write_text(json.dumps({
                "completed": ["event_settings"], "started_at": "2026-09-11T05:19:41Z",
                "deployed_sha": "b" * 40,
            }))
            (directory / "final-report.json").write_text(json.dumps({
                "status": "INCOMPLETE", "real_reads": [], "real_writes": [],
            }))
            (directory / "configuration-plan.json").write_text(json.dumps({
                "mission": [{"domain": "event_settings"}, {"domain": "optional_items"}],
            }))
            (directory / "rr-validation.json").write_text(json.dumps({"items": [
                {"domain": "event_settings", "itemId": "one"},
                {"domain": "optional_items", "itemId": "two"},
            ]}))
            (directory / "final-verification.json").write_text(json.dumps({"domains": {
                "event_settings": {"verifiedAt": "2026-09-11T05:24:22Z", "cventEvidence": ["A2Z Event ID=2123 after Save"],
                                   "items": [{"itemId": "one", "status": "MATCH"}]},
            }}))
            (directory / "domain-results.json").write_text(json.dumps({"domains": {
                "event_settings": {"checkpoint": "COMPLETE", "status": "completed", "updated": ["A2Z Event ID=2123"]},
            }}))
            events = [
                {"kind": "browser_operation", "section": "event_settings", "operation": "script", "writes": 2, "saves": 1, "readbacks": 1},
                {"kind": "browser_operation", "section": "event_settings", "operation": "snapshotText", "writes": 0, "saves": 0, "readbacks": 0},
            ]
            (directory / "performance-events.jsonl").write_text("".join(json.dumps(item) + "\n" for item in events))
            job = {"id": "job_711", "event_name": "Selected", "event_id": "event", "event_key": "event",
                   "created_at": "2026-09-11T05:19:39Z", "started_at": "2026-09-11T05:19:41Z"}
            report = build_telemetry_report(directory, job, root)
            self.assertEqual((report["writes"], report["saves"], report["readbacks"]), (2, 1, 1))
            self.assertEqual(report["browser_operations"], 2)
            self.assertEqual(report["deployed_sha"], "b" * 40)
            self.assertEqual(report["domains"]["event_settings"]["status"], "COMPLETE")
            self.assertEqual(report["domains"]["optional_items"]["status"], "INCOMPLETE")
            self.assertIn("2 persisted write(s)", report["real_writes"][0])
            written = write_telemetry_report(directory, job, root)
            self.assertEqual(json.loads((directory / "final-report.json").read_text())["writes"], written["writes"])

    def test_simple_reporting_preserves_pi_qa_and_counts_audit_without_domain_ledgers(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for name, value in {
                "browser-runtime.json": {"executionMode": "simple"},
                "state.json": {"completed": ["Location", "Admission text"], "pending": []},
                "final-report.json": {"execution_mode": "simple", "status": "DRAFT_COMPLETE", "real_reads": ["Reopened both sections"], "real_writes": ["Saved location and admission text"]},
                "domain-results.json": {"domains": {"irrelevant_legacy_domain": {"status": "INCOMPLETE"}}},
            }.items():
                (directory / name).write_text(json.dumps(value))
            audit = [
                {"result": "ui_action_completed", "dataChange": True, "isSave": False},
                {"result": "ui_action_completed", "isSave": True},
                {"result": "succeeded", "resolvedBy": "pi", "isSave": True},
                {"result": "ui_action_error", "isSave": True},
            ]
            (directory / "scope-write-audit.jsonl").write_text("".join(json.dumps(row) + "\n" for row in audit))
            (directory / "performance-events.jsonl").write_text(json.dumps({"kind": "browser_operation", "readbacks": 10}) + "\n")
            report = build_telemetry_report(directory, {"id": "simple"}, directory)
            self.assertEqual((report["writes"], report["saves"], report["readbacks"]), (1, 1, 1))
            self.assertEqual(report["real_reads"], ["Reopened both sections"])
            self.assertEqual(report["real_writes"], ["Saved location and admission text"])
            self.assertEqual(report["checklist"]["completed"], ["Location", "Admission text"])
            self.assertEqual(report["domains"], {})
            self.assertEqual(report["status"], "DRAFT_COMPLETE")
            self.assertIsNone(report["maximum_consecutive_zero_progress_rounds"])

    def test_legacy_activity_counts_are_used_when_old_events_lack_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for name, value in {
                "state.json": {}, "final-report.json": {"real_writes": []}, "configuration-plan.json": {"mission": [{"domain": "event_settings"}]},
                "rr-validation.json": {"items": [{"domain": "event_settings"}]}, "final-verification.json": {"domains": {}},
            }.items():
                (directory / name).write_text(json.dumps(value))
            (directory / "performance-events.jsonl").write_text(json.dumps({"kind": "browser_operation", "section": "event_settings"}) + "\n")
            (directory / "activity.log").write_text("2026-09-11T05:23:02Z  Ego event_settings: 4 actions, 2 writes, 1 saves, 1 readbacks\n")
            report = build_telemetry_report(directory, {"id": "job_711"}, directory)
            self.assertEqual((report["writes"], report["saves"], report["readbacks"]), (2, 1, 1))


if __name__ == "__main__":
    unittest.main()
