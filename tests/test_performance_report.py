import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import performance_report


class PerformanceReportTests(unittest.TestCase):
    def test_non_human_denominator_and_section_action_metrics_are_consistent(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "state.json").write_text(json.dumps({
                "started_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:01+00:00",
            }))
            (directory / "preflight-performance.json").write_text("{}")
            events = [
                {"timestamp": "2026-01-01T00:00:00.200+00:00", "kind": "human_handoff", "durationMs": 200},
                {"timestamp": "2026-01-01T00:00:00.400+00:00", "kind": "anthropic_response", "durationMs": 100, "section": "event_settings"},
                {"timestamp": "2026-01-01T00:00:00.500+00:00", "kind": "model_response_progress", "durationMs": 150, "section": "event_settings", "browserOperations": 1, "zeroProgress": False},
                {"timestamp": "2026-01-01T00:00:00.600+00:00", "kind": "browser_operation", "durationMs": 50, "section": "event_settings", "operation": "actions", "actionCount": 10, "egoExecutionRound": True, "intent": "write"},
                {"timestamp": "2026-01-01T00:00:00.610+00:00", "kind": "ego_execution_round", "durationMs": 0, "domain": "event_settings", "actionCount": 10},
            ]
            (directory / "performance-events.jsonl").write_text("".join(json.dumps(item) + "\n" for item in events))
            (directory / "system-metrics.jsonl").write_text("")
            with contextlib.redirect_stdout(io.StringIO()):
                performance_report.main(directory)
            summary = json.loads((directory / "performance-summary.json").read_text())
            self.assertEqual(summary["totalAutomationMs"], 1000)
            self.assertEqual(summary["humanHandoffMs"], 200)
            self.assertEqual(summary["nonHumanAutomationMs"], 800)
            self.assertEqual(summary["modelActiveShareOfNonHumanPercent"], 12.5)
            section = summary["sections"]["event_settings"]
            self.assertEqual(section["modelTurns"], 1)
            self.assertEqual(section["modelTurnsWithAction"], 1)
            self.assertEqual(section["modelTurnsWithZeroProgress"], 0)
            self.assertEqual(section["egoRounds"], 1)
            self.assertEqual(section["actionsPerEgoRound"], 10)
            self.assertEqual(section["browserOperations"], 1)
            self.assertEqual(section["modelTimeMs"], 100)
            self.assertEqual(section["browserTimeMs"], 50)

    def test_legacy_handoff_is_derived_from_activity_log(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "activity.log").write_text(
                "2026-01-01T00:00:01.000Z  Cvent login required; browser control handed to user for SSO/MFA\n"
                "2026-01-01T00:00:03.500Z  User returned browser control; profile verified\n"
            )
            self.assertEqual(performance_report.legacy_human_handoff_ms(directory), 2500)


if __name__ == "__main__":
    unittest.main()
