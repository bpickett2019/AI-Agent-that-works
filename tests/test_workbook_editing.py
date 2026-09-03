import json
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException
from openpyxl import Workbook, load_workbook

import app as cvent_app


class WorkbookEditingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old = (
            cvent_app.CURRENT,
            cvent_app.STATE,
            cvent_app.LOG,
            cvent_app.REPORT,
            cvent_app.running,
        )
        cvent_app.CURRENT = self.root
        cvent_app.STATE = self.root / 'state.json'
        cvent_app.LOG = self.root / 'activity.log'
        cvent_app.REPORT = self.root / 'final-report.json'
        cvent_app.running = lambda: False
        cvent_app.LOG.touch()
        cvent_app.atomic_json(cvent_app.STATE, cvent_app.fresh_state('rr.xlsx'))

        wb = Workbook()
        ws = wb.active
        ws.title = 'RR'
        ws['A1'] = 'Original'
        ws['B1'] = 12
        ws['C1'] = 'Merged'
        ws.merge_cells('C1:D1')
        wb.save(self.root / 'input.xlsx')
        wb.close()

    def tearDown(self):
        (
            cvent_app.CURRENT,
            cvent_app.STATE,
            cvent_app.LOG,
            cvent_app.REPORT,
            cvent_app.running,
        ) = self.old
        self.temp.cleanup()

    def version(self):
        return str((self.root / 'input.xlsx').stat().st_mtime_ns)

    def test_batch_edit_saves_backup_preserves_types_and_resets_state(self):
        (self.root / 'expected-domains.json').write_text('{}')
        result = cvent_app.update_workbook({
            'version': self.version(),
            'changes': [
                {'sheet': 'RR', 'row': 1, 'column': 1, 'value': 'Changed'},
                {'sheet': 'RR', 'row': 1, 'column': 2, 'value': '42'},
                {'sheet': 'RR', 'row': 2, 'column': 1, 'value': '=B1*2'},
            ],
        })
        self.assertEqual(result['saved'], 3)
        self.assertEqual(result['version'], self.version())
        self.assertTrue((self.root / 'workbook-backups' / result['backup']).exists())
        self.assertFalse((self.root / 'expected-domains.json').exists())

        wb = load_workbook(self.root / 'input.xlsx', data_only=False)
        try:
            self.assertEqual(wb['RR']['A1'].value, 'Changed')
            self.assertEqual(wb['RR']['B1'].value, 42)
            self.assertIsInstance(wb['RR']['B1'].value, int)
            self.assertEqual(wb['RR']['A2'].value, '=B1*2')
        finally:
            wb.close()
        state = json.loads(cvent_app.STATE.read_text())
        self.assertEqual(state['status'], 'ready')
        self.assertIn('edited', state['current_action'])

    def test_rejects_stale_version_merged_cell_and_running_agent(self):
        with self.assertRaises(HTTPException) as stale:
            cvent_app.update_workbook({'version': 'stale', 'changes': [{'sheet': 'RR', 'row': 1, 'column': 1, 'value': 'x'}]})
        self.assertEqual(stale.exception.status_code, 409)

        with self.assertRaises(HTTPException) as merged:
            cvent_app.update_workbook({'version': self.version(), 'changes': [{'sheet': 'RR', 'row': 1, 'column': 4, 'value': 'x'}]})
        self.assertEqual(merged.exception.status_code, 409)

        cvent_app.running = lambda: True
        with self.assertRaises(HTTPException) as active:
            cvent_app.update_workbook({'version': self.version(), 'changes': [{'sheet': 'RR', 'row': 1, 'column': 1, 'value': 'x'}]})
        self.assertEqual(active.exception.status_code, 409)

    def test_sheet_marks_merged_follower_non_editable(self):
        response = cvent_app.workbook_sheet('RR', 1, 10)
        body = json.loads(response.body)
        self.assertTrue(body['editable'][0][2])
        self.assertFalse(body['editable'][0][3])
        self.assertIsInstance(body['version'], str)


if __name__ == '__main__':
    unittest.main()
