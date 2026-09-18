import json
import tempfile
import unittest
from pathlib import Path
from job_runner import JobRunner


class PrewriteUiAuditTests(unittest.TestCase):
    def test_explicit_nonpersisting_ui_actions_allow_retry_without_erasing_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            audit = directory / 'scope-write-audit.jsonl'
            records = [dict(result=result, operation='click', target=target,
                            dataChange=False, isSave=False, potentiallyPersisted=False)
                       for target in ['Edit', 'Cancel', 'Open Site Designer']
                       for result in ['ui_action_attempted', 'ui_action_completed']]
            audit.write_text('\n'.join(map(json.dumps, records)))
            before = audit.read_bytes()
            self.assertFalse(JobRunner._mutation_attempted(directory))
            self.assertEqual(audit.read_bytes(), before)

    def test_actual_or_unknown_mutations_still_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            audit = directory / 'scope-write-audit.jsonl'
            safe = dict(result='ui_action_completed', dataChange=False, isSave=False, potentiallyPersisted=False)
            for record in [dict(safe, dataChange=True), dict(safe, isSave=True),
                           dict(safe, potentiallyPersisted=True), dict(safe, result='attempted'),
                           dict(safe, result='succeeded'), {'result': 'ui_action_completed'}, None, []]:
                with self.subTest(record=record):
                    audit.write_text(json.dumps(record))
                    self.assertTrue(JobRunner._mutation_attempted(directory))
            audit.write_text('partial invalid JSON')
            self.assertTrue(JobRunner._mutation_attempted(directory))

    def test_pending_save_or_uncertainty_always_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.assertFalse(JobRunner._mutation_attempted(directory))
            for name in ['browser-mutation-uncertain.json', 'browser-write-readback-required.json']:
                marker = directory / name
                marker.write_text('{}')
                self.assertTrue(JobRunner._mutation_attempted(directory))
                marker.unlink()
