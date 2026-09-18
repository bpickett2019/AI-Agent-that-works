"""Old target/upload/start flow with no Cvent login, Docker, or provider I/O."""
import io
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import Workbook

import app as server
from control_store import ControlStore
from job_runner import JobRunner

KEY = 'e712e34c-6117-4d13-bf4c-8ed54cf2b495'


class PreloginIntakeTests(unittest.TestCase):
    def test_target_upload_then_start_does_not_require_authenticated_inventory(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            store = ControlStore(root/'control.db')
            runner = JobRunner(store)
            directory = lambda ws, job: root/ws/'jobs'/job
            stack.enter_context(patch.dict(os.environ, {
                'CVENT_ENV':'development', 'CVENT_DEV_AUTH_SUBJECT':'local-intake',
                'CVENT_AUTHORIZED_EVENTS_JSON':json.dumps([{'event_id':KEY,'event_key':KEY,'name':'Selected Clone','event_code':'EVT-1'}]),
            }))
            stack.enter_context(patch.object(server,'store',store))
            stack.enter_context(patch.object(server,'runner',runner))
            stack.enter_context(patch.object(server,'job_dir',directory))
            stack.enter_context(patch('job_runner.job_dir',directory))
            stack.enter_context(patch.object(runner,'start_scheduler',return_value=[]))
            stack.enter_context(patch.object(runner,'shutdown'))
            start = stack.enter_context(patch.object(runner,'start',return_value={}))
            browser = stack.enter_context(patch.object(runner,'steel_command',side_effect=AssertionError('No browser before start')))
            provider = stack.enter_context(patch.object(runner,'verify_provider_access',side_effect=AssertionError('No provider before explicit start')))
            stack.enter_context(patch('event_inventory.events_for_workspace',side_effect=AssertionError('No login before upload')))
            wb = Workbook(); wb.active['A1'] = 'Different workbook event name must not select the target'
            data = io.BytesIO(); wb.save(data); wb.close()
            with TestClient(server.app) as client:
                me = client.get('/api/me').json()
                events = client.get('/api/events')
                self.assertEqual(events.status_code,200)
                self.assertEqual(events.json(),[{'event_id':KEY,'name':'Selected Clone','event_code':'EVT-1'}])
                headers = {'X-CSRF-Token':me['csrf']}
                self.assertEqual(client.get('/api/jobs').json(), [])
                self.assertEqual(client.get('/api/status?worker_slot=2').json()['status'], 'waiting_for_rr')
                self.assertEqual(client.post('/api/start', headers=headers).status_code, 404)
                self.assertEqual(client.post('/api/upload', headers=headers).status_code, 422)
                start.assert_not_called(); browser.assert_not_called(); provider.assert_not_called()
                response = client.post('/api/upload',headers=headers,data={'event_id':KEY,'worker_slot':'1'},files={'rr':('RR.xlsx',data.getvalue(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
                self.assertEqual(response.status_code,200,response.text)
                job = store.get_job(response.json()['job_id'])
                self.assertEqual(job['state'],'draft')
                self.assertEqual(job['event_key'],KEY)
                self.assertEqual(job['event_name'],'Selected Clone')
                jobdir = directory(job['workspace_id'],job['id'])
                self.assertTrue((jobdir/'input.xlsx').exists())
                self.assertFalse((jobdir/'authorized-target.json').exists())
                start.assert_not_called(); browser.assert_not_called(); provider.assert_not_called()
                unknown = client.post('/api/upload',headers=headers,data={'event_id':'11111111-1111-4111-8111-111111111111'},files={'rr':('RR.xlsx',data.getvalue())})
                self.assertEqual(unknown.status_code,404)
                result = client.post('/api/start',headers=headers,params={'job_id':job['id']})
                self.assertEqual(result.status_code,200,result.text)
                start.assert_called_once_with(job['id'],'dev:local-intake')
