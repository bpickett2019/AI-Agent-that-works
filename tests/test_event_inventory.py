import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import event_inventory


KEY = "e712e34c-6117-4d13-bf4c-8ed54cf2b495"
OTHER = "b712e34c-6117-4d13-bf4c-8ed54cf2b496"


class AuthenticatedEventInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "ws_test"
        self.workspace.mkdir()
        self.patch = patch.object(event_inventory, "workspace_dir", return_value=self.workspace)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def write(self, events):
        (self.workspace / "event-inventory.json").write_text(json.dumps({
            "schemaVersion": 1,
            "workspaceId": "ws_test",
            "source": "authenticated-cvent-inventory",
            "capturedAt": "2099-01-01T00:00:00+00:00",
            "events": events,
        }))

    def row(self, key=KEY, name="Selected Event"):
        return {"eventKey": key, "name": name, "code": "EVT-1", "status": "Active",
                "href": f"https://app.cvent.com/event?evtStub={key}"}

    def test_explicit_targets_are_selectable_before_login_without_inventory_refresh(self):
        config = [{'event_id':KEY,'event_key':KEY,'name':'Selected Event','event_code':'EVT-1'}]
        for setting, content in [('CVENT_AUTHORIZED_EVENTS_JSON',json.dumps(config)), ('CVENT_AUTHORIZED_EVENTS_B64',base64.b64encode(json.dumps(config).encode()).decode())]:
            with self.subTest(setting=setting), patch.dict(os.environ,{setting:content},clear=True), patch.object(event_inventory,'events_for_workspace',side_effect=AssertionError('Must not require login for intake')):
                selected = event_inventory.resolve_event('ws_test',KEY.upper())
                self.assertEqual(selected.name,'Selected Event')
                self.assertEqual(selected.event_code,'EVT-1')
                with self.assertRaisesRegex(KeyError,'EVENT_NOT_FOUND'):
                    event_inventory.resolve_event('ws_test',OTHER)
                # Config authorization must never masquerade as live browser proof.
                self.assertFalse((self.workspace/'event-inventory.json').exists())

    def test_invalid_config_fails_closed_without_falling_back_to_live_inventory(self):
        valid = {'event_id':KEY,'event_key':KEY,'name':'Selected Event'}
        for value in ([], [valid,valid], [{**valid,'event_id':OTHER}], [{**valid,'name':''}], [{'event_id':'guess','event_key':'guess','name':'Guessed'}], [None]):
            with self.subTest(value=value), patch.dict(os.environ,{'CVENT_AUTHORIZED_EVENTS_JSON':json.dumps(value)},clear=True), patch.object(event_inventory,'events_for_workspace',side_effect=AssertionError('Invalid config must not fall back')):
                with self.assertRaisesRegex(RuntimeError,'Invalid server-authorized target list'):
                    event_inventory.selectable_events('ws_test')

    def test_resolves_exact_canonical_identity_from_authenticated_inventory(self):
        self.write([self.row(), self.row(OTHER, "Other Event")])
        selected = event_inventory.resolve_event("ws_test", KEY.upper())
        self.assertEqual((selected.event_id, selected.event_key, selected.name, selected.event_code),
                         (KEY, KEY, "Selected Event", "EVT-1"))

    def test_zero_match_is_event_not_found(self):
        self.write([self.row()])
        with self.assertRaisesRegex(KeyError, "EVENT_NOT_FOUND"):
            event_inventory.resolve_event("ws_test", OTHER)

    def test_duplicate_canonical_key_is_ambiguous(self):
        self.write([self.row(), self.row(KEY, "Duplicate Row")])
        with self.assertRaisesRegex(RuntimeError, "EVENT_AMBIGUOUS"):
            event_inventory.read_events("ws_test")

    def test_cross_event_or_non_cvent_href_is_not_selectable(self):
        wrong = self.row(); wrong["href"] = f"https://app.cvent.com/event?evtstub={OTHER}"
        external = self.row(); external["href"] = f"https://example.com/event?evtstub={KEY}"
        self.write([wrong, external])
        with self.assertRaisesRegex(RuntimeError, "No accessible"):
            event_inventory.read_events("ws_test")

    def test_workspace_binding_prevents_cross_user_cache_reuse(self):
        self.write([self.row()])
        payload = json.loads((self.workspace / "event-inventory.json").read_text())
        payload["workspaceId"] = "ws_other"
        (self.workspace / "event-inventory.json").write_text(json.dumps(payload))
        with self.assertRaisesRegex(RuntimeError, "not bound"):
            event_inventory.read_events("ws_test")


if __name__ == "__main__":
    unittest.main()
