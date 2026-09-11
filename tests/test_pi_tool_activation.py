"""Real Pi CLI startup regression; no model request, browser or credentials."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PiToolActivationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('pi'), 'Pi CLI required for startup integration')
    def test_real_cli_keeps_ego_tools_and_skill_callable(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp).resolve()
            marker = folder / 'activation.json'
            smoke = folder / 'smoke.ts'
            smoke.write_text('import fs from "node:fs";\nexport default function(pi) {\n'
                             'pi.on("session_start", (_event, ctx) => {\n'
                             f'fs.writeFileSync({json.dumps(str(marker))}, JSON.stringify({{active:pi.getActiveTools(),system:ctx.getSystemPrompt()}}));\n'
                             '});\n}\n')
            env = {k: v for k, v in os.environ.items() if not k.startswith(('CVENT_', 'PI_', 'ANTHROPIC_'))}
            env.update(CVENT_JOB_DIR=str(folder), CVENT_REPO_ROOT=str(ROOT), PI_CODING_AGENT_DIR=str(folder / 'pi'),
                       CVENT_AUTHORIZED_EVENT_ID='offline', CVENT_AUTHORIZED_EVENT_KEY='offline', CVENT_AUTHORIZED_EVENT_NAME='Offline')
            command = ['pi', '--mode', 'rpc', '--provider', 'anthropic', '--model', 'claude-sonnet-4-6',
                       '--no-extensions', '--extension', str(ROOT / 'extensions/cvent-job-tools.ts'),
                       '--extension', str(smoke), '--no-skills', '--skill', str(ROOT / 'skills/ego-browser/SKILL.md'),
                       '--no-context-files', '--no-prompt-templates', '--no-builtin-tools',
                       '--tools', 'read,bash,cvent_prepare_rr,cvent_plan,cvent_browser,cvent_finish', '--no-session']
            result = subprocess.run(command, input='{"id":"startup","type":"get_state"}\n', cwd=folder,
                                    env=env, capture_output=True, text=True, timeout=30)
            self.assertTrue(marker.exists(), result.stdout + result.stderr)
            observed = json.loads(marker.read_text())
            for name in ['read', 'bash', 'cvent_prepare_rr', 'cvent_plan', 'cvent_browser', 'cvent_finish']:
                self.assertIn(name, observed['active'])
            self.assertIn('ego-browser', observed['system'])
            self.assertNotIn('Available tools: (none)', observed['system'])
