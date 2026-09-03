import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scope_manifest import SCOPE_MANIFEST, SCOPE_WORKBOOK, compile_scope, load_manifest


class ScopeManifestTests(unittest.TestCase):
    def test_authoritative_scope_counts_and_statuses(self):
        manifest = load_manifest()
        self.assertEqual(manifest['authority'], 'Forge Intake')
        self.assertEqual(manifest['counts'], {'confirmed': 65, 'unconfirmed': 33, 'deferred': 18})
        entries = {entry['id']: entry for entry in manifest['entries']}
        self.assertEqual(entries['scope-004']['cventField'], 'Event Name')
        self.assertEqual(entries['scope-004']['status'], 'confirmed')
        self.assertEqual(entries['scope-070']['status'], 'unconfirmed')
        self.assertEqual(entries['scope-114']['status'], 'deferred')
        self.assertEqual(entries['scope-098']['section'], 'K. Discounts')
        self.assertEqual(entries['scope-100']['section'], 'L. Vouchers')

    def test_manifest_fails_closed_when_workbook_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            workbook = Path(directory) / 'scope.xlsx'
            manifest_path = Path(directory) / 'scope.json'
            shutil.copy2(SCOPE_WORKBOOK, workbook)
            shutil.copy2(SCOPE_MANIFEST, manifest_path)
            with workbook.open('ab') as target:
                target.write(b'changed')
            with self.assertRaisesRegex(RuntimeError, 'do not match'):
                load_manifest(workbook, manifest_path)

    def test_every_entry_has_stable_id_and_field(self):
        manifest = compile_scope()
        self.assertEqual(len(manifest['entries']), 116)
        self.assertEqual(len({entry['id'] for entry in manifest['entries']}), 116)
        self.assertTrue(all(entry['cventField'] for entry in manifest['entries']))


if __name__ == '__main__':
    unittest.main()
