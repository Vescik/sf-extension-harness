"""Relocation and actual child-process tests without Salesforce installation or accounts."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.prepare_salesforce_policy_pilot import prepare, ROOT, SOURCES


class PortablePilotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = prepare(Path(self.tmp.name) / "other customer workspace żółć")
        self.env = {**os.environ, **json.loads((self.root / 'pilot-environment.json').read_text())}

    def test_copied_final_hooks_run_in_relocated_workspace_without_auth(self):
        result = subprocess.run([sys.executable, str(self.root / 'scripts/pilot_check.py')],
                                cwd=self.root, env=self.env, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['hostAcceptance'], 'NOT VERIFIED')
        self.assertEqual(len(report['results']), 8)
        for source in SOURCES:
            self.assertEqual(report['sources'][source], hashlib.sha256((ROOT / source).read_bytes()).hexdigest())
        events = [json.loads(line) for line in (self.root / '.cache/executor.jsonl').read_text().splitlines()]
        self.assertEqual(sum(event['kind'] == 'operation' for event in events), 3)
        self.assertFalse(list((self.root / 'home').glob('**/*.json')))

    def test_existing_directory_is_never_overwritten(self):
        before = (self.root / 'config/harness.local.json').read_bytes()
        with self.assertRaises(FileExistsError):
            prepare(self.root)
        self.assertEqual((self.root / 'config/harness.local.json').read_bytes(), before)

    def test_missing_or_broken_policy_import_is_a_valid_deny_not_host_exit_one(self):
        module = self.root / 'scripts/salesforce_operation_policy.py'
        for broken in (None, 'raise RuntimeError("PRIVATE-ERROR-TEXT")\n', 'not valid python !!!\n'):
            if broken is None:
                module.unlink()
            else:
                module.write_text(broken)
            for script, extra in (('copilot_safety_hook.py', []), ('copilot_role_guard.py', ['--role', 'developer'])):
                with self.subTest(broken=broken, script=script):
                    proc = subprocess.run([sys.executable, '-B', str(self.root / 'scripts' / script), *extra],
                                          input='{}', cwd=self.root, env=self.env,
                                          text=True, capture_output=True, timeout=5)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertEqual(json.loads(proc.stdout)['hookSpecificOutput']['permissionDecision'], 'deny')
                    self.assertNotIn('PRIVATE-ERROR-TEXT', proc.stdout + proc.stderr)
        self.assertFalse((self.root / '.cache/executor.jsonl').exists())

    def test_inventory_failure_and_timeout_deny_in_both_copied_hooks(self):
        event = {'cwd': str(self.root), 'tool_name': 'execute/runInTerminal',
                 'tool_input': {'command': 'sf project retrieve start -o team-alpha -m ApexClass:Pilot'}}
        for mode in ('error', 'timeout'):
            (self.root / '.cache/inventory-mode.txt').write_text(mode)
            for script, extra in (('copilot_safety_hook.py', []), ('copilot_role_guard.py', ['--role', 'developer'])):
                with self.subTest(mode=mode, script=script):
                    proc = subprocess.run([sys.executable, str(self.root / 'scripts' / script), *extra],
                                          input=json.dumps(event), cwd=self.root, env=self.env,
                                          text=True, capture_output=True, timeout=5)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertEqual(json.loads(proc.stdout)['hookSpecificOutput']['permissionDecision'], 'deny')
        events = [json.loads(line) for line in (self.root / '.cache/executor.jsonl').read_text().splitlines()]
        self.assertTrue(events)
        self.assertTrue(all(event['kind'] == 'inventory' for event in events))
