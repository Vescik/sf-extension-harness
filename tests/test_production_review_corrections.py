"""Regressions for plan 01 independent review; synthetic orgs and executor only."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import salesforce_operation_policy as policy
from scripts import verify_salesforce_org as proof
from scripts.prepare_salesforce_policy_pilot import prepare
from tests.test_first_launch import first_launch, ROOT


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = prepare(Path(self.tmp.name) / 'lifecycle pilot')
        self.home = self.root / 'home'
        (self.home / '.sf').mkdir()
        (self.home / '.sfdx').mkdir()
        self.config = json.loads((self.root / 'config/harness.local.json').read_text())
        self.inventory = json.loads((self.root / 'inventory.json').read_text())
        self.config['salesforce']['orgs'].append({'alias': 'control', 'environment': 'stage',
            'expectedOrganizationId': '00D000000000003AAA', 'expectedInstanceHost': 'control--dev.sandbox.my.salesforce.com'})
        self.inventory['result'].append({'alias': 'control', 'username': 'control@example.test',
            'orgId': '00D000000000003AAA', 'instanceUrl': 'https://control--dev.sandbox.my.salesforce.com'})
        (self.root / 'config/harness.local.json').write_text(json.dumps(self.config))
        (self.root / 'inventory.json').write_text(json.dumps(self.inventory))
        self.rows = [{'id': r['orgId'][:15], 'host': r['instanceUrl'][8:], 'username': r['username'],
                      'aliases': [r['alias']]} for r in self.inventory['result']]
        self.env = {**os.environ, **json.loads((self.root / 'pilot-environment.json').read_text())}
        self.now = datetime.now(timezone.utc).isoformat()
        self.auth = {'username': 'prod-copy@example.test', 'orgId': '00D000000000002AAA',
                     'isScratch': True, 'devHubUsername': 'control@example.test', 'accessToken': 'NEVER-OUTPUT'}
        self.write_auth()

    def write_auth(self):
        (self.home / '.sfdx/prod-copy@example.test.json').write_text(json.dumps(self.auth))

    def sandbox_parent(self, parent):
        (self.home / '.sfdx/00D000000000002AAA.sandbox.json').write_text(json.dumps({'prodOrgUsername': parent}))

    def decide(self, command):
        return policy.evaluate(shlex.split(command), self.root, config=self.config, env={}, home=self.home,
                               inventory=lambda *_: self.rows)

    def hooks(self, command, expected):
        log = self.root / '.cache/executor.jsonl'
        before = log.read_text() if log.exists() else ''
        for script, extra in [('copilot_safety_hook.py', []), ('copilot_role_guard.py', ['--role', 'developer'])]:
            event = {'cwd': str(self.root), 'tool_name': 'execute/runInTerminal',
                     'tool_input': {'command': command}, 'tool_use_id': 'review-regression'}
            result = subprocess.run([sys.executable, str(self.root / 'scripts' / script), *extra],
                input=json.dumps(event), cwd=self.root, env=self.env, text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            actual = output.get('hookSpecificOutput', {}).get('permissionDecision', 'continue')
            self.assertEqual(actual, expected, (command, script, result.stdout))
            self.assertNotIn('NEVER-OUTPUT', result.stdout + result.stderr)
            if actual == 'continue':
                subprocess.run([sys.executable, str(self.root / 'scripts/pilot_cli.py'), *shlex.split(command)[1:]],
                               capture_output=True, check=True)
        if expected == 'deny':
            after = log.read_text() if log.exists() else ''
            self.assertEqual(after.count('"kind": "operation"'), before.count('"kind": "operation"'))

    def test_sandbox_delete_checks_parent_before_either_executor(self):
        command = 'sf org delete sandbox -o prod-copy --no-prompt'
        self.sandbox_parent('team-alpha')
        self.assertFalse(self.decide(command).allowed)
        self.hooks(command, 'deny')
        self.sandbox_parent('control@example.test')
        self.assertTrue(self.decide(command).allowed)
        self.hooks(command, 'continue')
        self.sandbox_parent('absent')
        self.hooks(command, 'deny')
        (self.home / '.sfdx/00D000000000002AAA.sandbox.json').unlink()
        self.hooks(command, 'deny')

    def test_scratch_delete_checks_devhub_and_any_sandbox_relationship(self):
        command = 'sf org delete scratch -o prod-copy --no-prompt'
        self.auth['devHubUsername'] = 'team-alpha@example.test'
        self.write_auth()
        self.hooks(command, 'deny')
        self.auth['devHubUsername'] = 'control@example.test'
        self.write_auth()
        self.hooks(command, 'continue')
        self.sandbox_parent('team-alpha')
        self.hooks(command, 'deny')
        self.auth['orgId'] = '00D000000000004AAA'
        self.write_auth()
        self.assertEqual(self.decide(command).status, 'identity-error')

    def test_sandbox_resume_uses_cached_parent_not_nonprod_flag(self):
        path = self.home / '.sf/sandbox-create-cache.json'
        entry = {'timestamp': self.now, 'prodOrgUsername': 'team-alpha',
                 'sandboxProcessObject': {'Id': '0GR000000000001AAA', 'SandboxName': 'sample'}}
        path.write_text(json.dumps({'sample': entry}))
        for selector in ['--job-id 0GR000000000001AAA', '--name sample', '--use-most-recent', '-l']:
            self.hooks(f'sf org resume sandbox {selector} -o prod-copy', 'deny')
        entry['prodOrgUsername'] = 'control'
        path.write_text(json.dumps({'sample': entry}))
        self.hooks('sf org resume sandbox --job-id 0GR000000000001AAA', 'continue')
        self.hooks('sf org resume sandbox --job-id 0GR000000000001AAA -o prod-copy', 'deny')
        path.unlink()
        self.hooks('sf org resume sandbox --job-id 0GR000000000001AAA', 'deny')
        # Verified CLI fallback uses the explicit parent when there is no cached job.
        self.hooks('sf org resume sandbox --job-id 0GR000000000001AAA -o control', 'continue')

    def test_scratch_resume_uses_cached_hub_and_rejects_stale_conflicting_or_bad_evidence(self):
        path = self.home / '.sf/scratch-create-cache.json'
        entry = {'timestamp': self.now, 'hubUsername': 'team-alpha'}
        command = 'sf org resume scratch --job-id 2SR000000000001AAA'
        path.write_text(json.dumps({'2SR000000000001AAA': entry}))
        self.hooks(command + ' -o prod-copy', 'deny')
        self.hooks('sf org resume scratch --use-most-recent', 'deny')
        entry['hubUsername'] = 'control'
        path.write_text(json.dumps({'2SR000000000001AAA': entry}))
        self.hooks(command, 'continue')
        for change in [{'timestamp': (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()},
                       {'timestamp': 'bad'}, {'hubUsername': ''}]:
            path.write_text(json.dumps({'2SR000000000001AAA': {**entry, **change}}))
            self.assertFalse(self.decide(command).allowed)
        path.write_text(json.dumps({'2SR000000000001AAA': entry, '2SR000000000001BBB': entry}))
        self.assertEqual(self.decide(command).status, 'conflict')

    def test_lifecycle_legacy_unknown_semantics_are_closed(self):
        for words in ['force:org:delete', 'force:org:create', 'org delete', 'env delete sandbox']:
            self.hooks(f'sfdx {words} -u prod-copy', 'deny')

    def test_four_environments_preview_matrix_and_deploy_confirmation(self):
        for environment in ['dev', 'uat', 'stage', 'prod']:
            self.config['salesforce']['orgs'][1]['environment'] = environment
            (self.root / 'config/harness.local.json').write_text(json.dumps(self.config))
            for words in ['project deploy preview', 'project retrieve preview',
                          'deploy metadata preview', 'retrieve metadata preview']:
                self.hooks(f'sf {words} -o prod-copy', 'deny' if environment == 'prod' else 'continue')
        self.config['salesforce']['orgs'][1]['environment'] = 'dev'
        (self.root / 'config/harness.local.json').write_text(json.dumps(self.config))
        for executable in ['sf', 'sfdx']:
            for words in ['project deploy start', 'deploy metadata', 'force:source:deploy', 'force:mdapi:deploy']:
                event = {'tool_name': 'execute/runInTerminal', 'tool_input': {'command':
                         f'{executable} {words} -o prod-copy -m ApexClass:Sample'}}
                result = subprocess.run([sys.executable, str(self.root / 'scripts/copilot_safety_hook.py')],
                    input=json.dumps(event), cwd=self.root, env=self.env, text=True, capture_output=True, timeout=5)
                self.assertEqual(json.loads(result.stdout)['hookSpecificOutput']['permissionDecision'], 'ask')


class TemplateOnboardingTests(unittest.TestCase):
    def test_actual_example_one_org_same_type_rerun_and_production_policy(self):
        with tempfile.TemporaryDirectory() as name:
            config_path = Path(name) / 'harness.local.json'
            with patch.object(first_launch, 'CONFIG_PATH', config_path):
                first_launch.prepare_config()
                # The released base retains its independent human Knowledge reviewer setup.
                # Supply that fixture value without changing onboarding's Knowledge behavior.
                initial = json.loads(config_path.read_text())
                initial['knowledge']['chatReviewer'] = 'Fixture Reviewer'
                config_path.write_text(json.dumps(initial))
                pending = {'ado.organization': 'example', 'ado.project': 'Demo',
                    'ado.releaseQueryId': '11111111-1111-1111-1111-111111111111',
                    'review.enabled': True, 'review.objects': ['Account'],
                    'org.alpha': {'alias': 'alpha', 'environment': 'prod',
                        'orgId': '00D000000000001AAA', 'host': 'pilot.my.salesforce.com'}}
                first_launch.apply_config(pending)
                cfg = json.loads(config_path.read_text())
                self.assertEqual(len(cfg['salesforce']['orgs']), 1)
                self.assertEqual(first_launch.local_config_findings(config_path.read_text(), first_launch.SCHEMA_PATH.read_text()), [])
                rows = [{'id': '00D000000000001', 'host': 'pilot.my.salesforce.com', 'username': 'a@example.test', 'aliases': ['alpha']}]
                for words, allowed in [('project retrieve start -m ApexClass:Sample', True), ('project deploy start', False)]:
                    decision = policy.evaluate(shlex.split(f'sf {words} -o alpha'), Path(name),
                        config=cfg, env={}, home=Path(name), inventory=lambda *_: rows)
                    self.assertEqual(decision.allowed, allowed)
                first = copy.deepcopy(cfg['salesforce']['orgs'][0])
                second = {'alias': 'beta', 'environment': 'prod', 'orgId': '00D000000000002AAA', 'host': 'other.my.salesforce.com'}
                first_launch.prepare_config()
                first_launch.apply_config({'org.beta': second})
                first_launch.apply_config({'org.beta': second})
                cfg = json.loads(config_path.read_text())
                self.assertEqual(len(cfg['salesforce']['orgs']), 2)
                self.assertEqual(cfg['salesforce']['orgs'][0], first)
                self.assertEqual(first_launch.local_config_findings(config_path.read_text(), first_launch.SCHEMA_PATH.read_text()), [])

    def test_partially_configured_template_identity_is_preserved(self):
        cfg = json.loads(first_launch.EXAMPLE_PATH.read_text())
        cfg['salesforce']['orgs'][0]['expectedOrganizationId'] = '00D000000000001AAA'
        retained = copy.deepcopy(cfg['salesforce']['orgs'][0])
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'harness.local.json'
            path.write_text(json.dumps(cfg))
            with patch.object(first_launch, 'CONFIG_PATH', path):
                first_launch.apply_config({'org.alpha': {'alias': 'alpha', 'environment': 'dev',
                    'orgId': '00D000000000002AAA', 'host': 'pilot--dev.sandbox.my.salesforce.com'}})
            orgs = json.loads(path.read_text())['salesforce']['orgs']
            self.assertEqual(orgs[0], retained)
            self.assertEqual(len(orgs), 2)

    def test_customized_example_real_identity_is_not_removed(self):
        cfg = json.loads(first_launch.EXAMPLE_PATH.read_text())
        real = {'alias': 'real', 'environment': 'prod',
                'expectedOrganizationId': '00D000000000001AAA',
                'expectedInstanceHost': 'real.my.salesforce.com'}
        cfg['salesforce']['orgs'] = [real]
        with tempfile.TemporaryDirectory() as name:
            path, example = Path(name) / 'local.json', Path(name) / 'example.json'
            path.write_text(json.dumps(cfg))
            example.write_text(json.dumps(cfg))
            with patch.object(first_launch, 'CONFIG_PATH', path), patch.object(first_launch, 'EXAMPLE_PATH', example):
                first_launch.apply_config({'org.next': {'alias': 'next', 'environment': 'prod',
                    'orgId': '00D000000000002AAA', 'host': 'other.my.salesforce.com'}})
            self.assertEqual(json.loads(path.read_text())['salesforce']['orgs'][0], real)


class DiagnosticConflictTests(unittest.TestCase):
    def test_duplicate_alias_never_enters_dynamic_lane_or_executes_cli(self):
        entries = [{'alias': 'same', 'expectedOrganizationId': f'00D00000000000{i}AAA',
                    'expectedInstanceHost': f'org{i}.my.salesforce.com'} for i in (1, 2)]
        with patch.object(proof, 'load_config', return_value={'salesforce': {'orgs': entries}}), \
             patch.object(proof, 'verify_org_identity', return_value=(True, 'would prove unrelated C')) as verify, \
             patch.object(sys, 'argv', ['verify_salesforce_org.py', '--org', 'same']), \
             patch.object(sys, 'stdout', StringIO()):
            self.assertEqual(proof.main(), 2)
            verify.assert_not_called()
            self.assertIn('duplicate', proof.configured_identity('same'))
            self.assertIsNone(proof.configured_identity('actually-unconfigured'))
