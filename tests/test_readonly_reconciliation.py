import tempfile
import unittest
import hashlib
import json
import ast
import __future__
from unittest.mock import Mock
from fastapi import HTTPException
from browser_gate import BrowserGate
import browser_tool
from readonly_session import resolve_readonly_session
from pathlib import Path
from types import SimpleNamespace

from control_store import ControlStore
from scripts.reconcile_registration_readonly import readonly_lease, verified_detail, READ_ACTIONS


class ReadonlyReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=ControlStore(Path(self.tmp.name)/'control.db')
        self.user=self.store.ensure_user('test-user','test@example.test','Test',False)
        event=SimpleNamespace(event_id='event-one',event_key='event-one',name='Selected event')
        self.job=self.store.create_job(self.user,event,'original.xlsx',preferred_slot=1)
        self.store.finish(self.job['id'],None,'failed_uncertain','Retain original uncertainty',True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_lease_preserves_failed_job_and_releases_on_error(self):
        before=self.store.get_job(self.job['id'])
        with self.assertRaisesRegex(RuntimeError,'simulated read error'):
            with readonly_lease(self.store,self.job['id'],'event-one') as (token,lost):
                self.assertTrue(self.store.valid_event_lease(self.job['id'],token,'event-one'))
                self.assertFalse(lost.is_set())
                current=self.store.get_job(self.job['id'])
                for field in ('state','uncertain','pid','slot_id','lease_token','error'):
                    self.assertEqual(current[field],before[field])
                with self.assertRaisesRegex(ValueError,'current state'):
                    self.store.reserve_now(self.job['id'],'test-user')
                raise RuntimeError('simulated read error')
        self.assertEqual(self.store.active_leases(),{'events':[],'workers':[]})
        self.assertEqual(self.store.get_job(self.job['id'])['uncertain'],1)

    def test_no_parallel_reader_or_other_worker(self):
        with readonly_lease(self.store,self.job['id'],'event-one'):
            with self.assertRaisesRegex(RuntimeError,'already leased'):
                with readonly_lease(self.store,self.job['id'],'event-one'):pass
        for slot in (2,3):
            with self.assertRaisesRegex(ValueError,'USER 1'):
                with readonly_lease(self.store,self.job['id'],'event-one',slot):pass
        with self.assertRaisesRegex(RuntimeError,'binding mismatch'):
            with readonly_lease(self.store,self.job['id'],'another-event'):pass

    def test_dispatcher_cannot_mutate_or_save(self):
        self.assertTrue(READ_ACTIONS.isdisjoint({'click','activate','fill','type','setChecked','selectOption',
                                               'configureRegistrationTypes','configureAdmissionItems','save'}))

    def test_readonly_runtime_blocks_mutations_even_without_uncertainty_file(self):
        runtime={'accessMode':'read_only_reconciliation'}
        for operation,intent in [('fill','write'),('click','read'),('configureRegistrationTypes','read'),('configureAdmissionItems','write')]:
            with self.assertRaisesRegex(RuntimeError,'Read-only reconciliation cannot dispatch'):
                browser_tool.guard(runtime,operation,{'intent':intent})

    def test_viewer_requires_current_lease_fingerprint_and_exact_runtime(self):
        directory=Path(self.tmp.name)/'job';folder=directory/'reconciliation/atted-0123456789ab';folder.mkdir(parents=True)
        job=self.store.get_job(self.job['id'])
        runtime={'accessMode':'read_only_reconciliation','authorizedEventId':job['event_id'],
                 'authorizedEventKey':job['event_key'],'authorizedEventName':job['event_name'],
                 'workerSlot':1,'browserRuntimeId':'fresh-read-runtime'}
        (folder/'browser-runtime.json').write_text(json.dumps(runtime))
        pointer={'directory':folder.name,'jobId':job['id'],'browserRuntimeId':'fresh-read-runtime'}
        with readonly_lease(self.store,job['id'],'event-one') as (token,_):
            pointer['leaseFingerprint']=hashlib.sha256(token.encode()).hexdigest()
            (directory/'read-only-reconciliation.json').write_text(json.dumps(pointer))
            active=resolve_readonly_session(self.store,job,directory)
            self.assertTrue(active.read_only);self.assertIsNone(active.process)
            self.assertEqual(active.runtime_dir,folder)
            pointer['leaseFingerprint']='wrong'
            (directory/'read-only-reconciliation.json').write_text(json.dumps(pointer))
            self.assertIsNone(resolve_readonly_session(self.store,job,directory))
            pointer['leaseFingerprint']=hashlib.sha256(token.encode()).hexdigest()
            (directory/'read-only-reconciliation.json').write_text(json.dumps(pointer))
            runtime['authorizedEventKey']='another'
            (folder/'browser-runtime.json').write_text(json.dumps(runtime))
            self.assertIsNone(resolve_readonly_session(self.store,job,directory))
        self.assertIsNone(resolve_readonly_session(self.store,job,directory))

    def test_readonly_return_verifies_login_but_never_resumes_a_process(self):
        directory=Path(self.tmp.name)/'readback';directory.mkdir()
        gate=BrowserGate(directory);gate.initialize()
        value=gate.read();value.update(ownership='USER',desiredOwnership='USER',activeActor='USER');gate.write(value)
        job=self.store.get_job(self.job['id'])
        active=SimpleNamespace(read_only=True,process=None,runtime_dir=directory,slot_id=1)
        node=next(n for n in ast.parse((Path(__file__).resolve().parents[1]/'app.py').read_text()).body
                  if isinstance(n,ast.FunctionDef) and n.name=='return_to_agent')
        node.decorator_list=[]
        verify=Mock(return_value=({'authenticated':True},{'readback':True}))
        persist=Mock();kill=Mock(side_effect=AssertionError('A read-only handoff must not resume Pi'))
        namespace={'Request':object,'current_user':lambda *a,**k:{'subject':'test-user'},
                   'authorize_job':lambda *a:job,'browser_directory_for':lambda *a:directory,
                   'BrowserGate':BrowserGate,'active_job':lambda *a:active,
                   'verify_authenticated_cvent':verify,'persist_authenticated_cvent':persist,
                   'atomic_json':lambda path,data:path.write_text(json.dumps(data)),
                   'store':self.store,'HTTPException':HTTPException,'os':SimpleNamespace(killpg=kill)}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'reviewed_return','exec',flags=__future__.annotations.compiler_flag),namespace)
        result=namespace['return_to_agent'](object(),job['id'])
        self.assertTrue(result['readOnly']);self.assertTrue(result['verified']);kill.assert_not_called()
        verify.assert_called_once_with(job,active,directory);persist.assert_called_once()
        self.assertEqual(gate.read()['ownership'],'AGENT')
        self.assertEqual(self.store.get_job(job['id'])['state'],'failed_uncertain')
        self.assertEqual(self.store.get_job(job['id'])['uncertain'],1)
        verify.side_effect=RuntimeError('Not authenticated')
        with self.assertRaises(HTTPException) as error:namespace['return_to_agent'](object(),job['id'])
        self.assertEqual(error.exception.status_code,409)
        self.assertEqual(gate.read()['ownership'],'USER');kill.assert_not_called()

    def test_exact_parent_detail_identity_required(self):
        href='https://app.cvent.com/Subscribers/Events2/Details/RegistrationTypeDetail/Index/View?evtStub=event-one&registrationtypestub=item-one'
        link={'text':'Attendee | Educator','href':href}
        self.assertEqual(verified_detail({'links':[link]},'event-one'),link)
        for bad in (href+'&evtstub=other',href.replace('app.cvent.com','evilcvent.com'),
                    href.replace('https:','http:'),href.replace('RegistrationTypeDetail','AccountSettings'),
                    href+'&RegistrationTypeStub=second'):
            with self.assertRaisesRegex(RuntimeError,'not unique'):
                verified_detail({'links':[{'href':bad}]},'event-one')
        with self.assertRaisesRegex(RuntimeError,'not unique'):
            verified_detail({'links':[link,link]},'event-one')


if __name__=='__main__':unittest.main()
