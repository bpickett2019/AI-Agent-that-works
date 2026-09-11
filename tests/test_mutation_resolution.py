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

    def test_operator_can_resolve_exact_attempt_as_persisted_without_rewriting_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);evidence=d/'fresh-reopen-readback.json'
            evidence.write_text('{"hotelInfo":"https://bdny.com/bookyourhotel/"}')
            attempts=[
                {'at':'apply-at','operation':'click#apply','rrSource':'uploaded RR','result':'attempted'},
                {'at':'save-at','operation':'click#save','rrSource':'uploaded RR','result':'attempted'},
            ]
            audit=d/'scope-write-audit.jsonl';audit.write_text('\n'.join(map(json.dumps,attempts)))
            before=audit.read_bytes();digest=hashlib.sha256(evidence.read_bytes()).hexdigest()
            resolutions=[{
                'attemptAt':item['at'],'operation':item['operation'],'rrSource':item['rrSource'],
                'outcome':'PERSISTED','actor':'operator','evidencePath':evidence.name,
                'evidenceSha256':digest,
            } for item in attempts]
            (d/'mutation-resolutions.json').write_text(json.dumps({'resolutions':resolutions}))
            result=mutation_outcome(d)
            self.assertEqual(result['persistedResolved'],2)
            self.assertEqual(result['unmatchedAttempts'],0)
            self.assertFalse(result['unresolved'])
            self.assertEqual(audit.read_bytes(),before)

    def test_persisted_resolution_requires_operator_and_hashed_job_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);evidence=d/'readback.json';evidence.write_text('{}')
            (d/'scope-write-audit.jsonl').write_text(json.dumps(
                {'at':'one','operation':'script','rrSource':'Sheet!A1','result':'attempted'}))
            invalid={'attemptAt':'one','operation':'script','rrSource':'Sheet!A1','outcome':'PERSISTED',
                     'actor':'agent','evidencePath':evidence.name,
                     'evidenceSha256':hashlib.sha256(evidence.read_bytes()).hexdigest()}
            (d/'mutation-resolutions.json').write_text(json.dumps({'resolutions':[invalid]}))
            result=mutation_outcome(d)
            self.assertTrue(result['unresolved'])
            self.assertTrue(result['malformedAudit'])
