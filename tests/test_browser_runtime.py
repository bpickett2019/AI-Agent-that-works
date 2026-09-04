import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import browser_runtime


class BrowserRuntimeIdentityTests(unittest.TestCase):
    def test_explicit_persistent_profile_is_recorded_in_runtime_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job = root / "job"
            profile = root / "workspace" / "browser-profiles" / "slot-1" / "chromium-profile"
            profile.mkdir(parents=True)
            page = {
                "id": "target-1",
                "url": "https://app.cvent.com/Subscribers/Events2/EventSelection",
                "title": "Events",
                "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/target-1",
            }
            version = {
                "Browser": "Chrome/Test",
                "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/browser/browser-1",
            }
            with patch.object(browser_runtime, "get_json", return_value=version), \
                 patch.object(browser_runtime, "pages", return_value=[page]), \
                 patch.object(browser_runtime, "command", return_value={}), \
                 patch.object(browser_runtime, "evaluate", return_value=None):
                runtime = browser_runtime.initialize(
                    job, 1, "Authorized event", "event-1", "event-1", "/viewer",
                    profile_path=profile,
                )
            self.assertEqual(runtime["profilePath"], str(profile.resolve()))
            self.assertNotEqual(runtime["profilePath"], str((job / "chromium-profile").resolve()))


if __name__ == "__main__":
    unittest.main()
