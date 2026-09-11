import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from mutation_outcome import mutation_outcome


class MutationResolutionTests(unittest.TestCase):
    def test_resolution_is_exact_and_preserves_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);evidence=d/'persisted-readback.json';evidence.write_text('{"venue":"Javits Convention Center"}')
            attempts=[{'at':at,'operation':'script','rrSource':'Event Details!B10','result':'attempted'} for at in ['first','second']]
            audit=d/'scope-write-audit.jsonl';audit.write_text('\n'.join(map(json.dumps,attempts)))
            before=audit.read_bytes()
            resolution={'attemptAt':'first','operation':'script','rrSource':'Event Details!B10','outcome':'NOT_PERSISTED','actor':'operator','evidencePath':evidence.name,'evidenceSha256':hashlib.sha256(evidence.read_bytes()).hexdigest()}
            (d/'mutation-resolutions.json').write_text(json.dumps({'resolutions':[resolution]}))
            result=mutation_outcome(d)
            self.assertEqual(result['notPersisted'],1)
            self.assertEqual(result['unmatchedAttempts'],1)
            self.assertTrue(result['unresolved'])
            self.assertEqual(audit.read_bytes(),before)
            # Only the reviewed attempt is resolved; a marker always contains further uncertainty.
            audit.write_text(json.dumps(attempts[0]))
            self.assertFalse(mutation_outcome(d)['unresolved'])
            (d/'browser-mutation-uncertain.json').write_text('{}')
            self.assertTrue(mutation_outcome(d)['unresolved'])
            (d/'browser-mutation-uncertain.json').unlink()
            evidence.write_text('{}')
            self.assertTrue(mutation_outcome(d)['unresolved'])
            self.assertTrue(mutation_outcome(d)['malformedAudit'])
