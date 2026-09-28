"""Policy and controlled-executor tests; these are not live VS Code acceptance."""
from __future__ import annotations

import copy
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import salesforce_operation_policy as policy
from scripts import copilot_safety_hook as safety
from scripts import copilot_role_guard as roles

ROOT = Path(__file__).resolve().parents[1]
PROD_ID = '00D000000000001'
DEV_ID = '00D000000000002'
ROWS = [
    {'id': PROD_ID, 'host': 'sample.my.salesforce.com', 'username': 'owner@example.test',
     'aliases': ['team-alpha', 'another-name', 'production']},
    {'id': DEV_ID, 'host': 'sample--dev.sandbox.my.salesforce.com', 'username': 'developer@example.test',
     'aliases': ['prod-copy', 'dev-sbx', 'scratch-one']},
]
CONFIG = {'salesforce': {'orgs': [
    {'alias': 'team-alpha', 'environment': 'prod', 'expectedOrganizationId': PROD_ID+'AAA', 'expectedInstanceHost': ROWS[0]['host']},
    {'alias': 'prod-copy', 'environment': 'dev', 'expectedOrganizationId': DEV_ID+'AAA', 'expectedInstanceHost': ROWS[1]['host']},
], 'review': {'enabled': True}}}


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = copy.deepcopy(CONFIG)
        self.rows = copy.deepcopy(ROWS)
        self.env = {}

    def decide(self, command):
        return policy.evaluate(shlex.split(command), self.root, config=self.config,
                               env=self.env, home=self.root, inventory=lambda *_: self.rows)

    def test_same_production_identity_all_target_spellings(self):
        for target in ['team-alpha', 'another-name', 'owner@example.test', PROD_ID, PROD_ID+'AAA']:
            for flag in ['--target-org', '-o', '-u', '--targetusername']:
                with self.subTest(target=target, flag=flag):
                    d = self.decide(f'sf data query {flag} {target} --query SELECT')
                    self.assertEqual(d.status, 'deny')
                    self.assertEqual(d.environment, 'prod')

    def test_all_prod_operations_except_retrieve_denied(self):
        for words in ['project deploy start', 'project deploy validate', 'project deploy quick',
                      'project deploy report', 'project deploy resume', 'project deploy cancel',
                      'data create record', 'data delete record', 'data update record', 'data upsert bulk',
                      'package install', 'org assign permset', 'apex run', 'apex run test',
                      'sobject describe', 'org display', 'limits api display', 'plugins run retrieve',
                      'package version retrieve', 'unknown retrieve', 'project retrieve preview']:
            with self.subTest(words=words):
                self.assertFalse(self.decide(f'sf {words} -o team-alpha').allowed)
        self.assertFalse(self.decide('sf project deploy start --dry-run -o team-alpha').allowed)
        self.assertFalse(self.decide('sf imaginary write -o prod-copy').allowed)
        self.config['salesforce']['review']['deniedOrganizationIds'] = [PROD_ID+'AAA']
        self.assertFalse(self.decide('sf project retrieve start -o team-alpha').allowed)

    def test_verified_retrieve_grammar_modern_and_shim(self):
        for exe in ['sf', 'sfdx', 'sf.cmd', 'sfdx.exe']:
            for command in ['project retrieve start', 'retrieve metadata']:
                self.assertTrue(self.decide(f'{exe} {command} -o team-alpha -m ApexClass:One --json --wait 3').allowed)
        for command in ['sf project retrieve resume --job-id 09Sx',
                        'sfdx force:source:retrieve -m ApexClass:One',
                        'sfdx force:mdapi:retrieve:report -i 09Sx',
                        'sf project retrieve start --flags-dir flags',
                        'sf project retrieve start --async',
                        'sf project retrieve start --deploy',
                        'sf project retrieve start --target-org=']:
            self.assertFalse(self.decide(f'{command} -o team-alpha').allowed)

    def test_alias_name_and_nonprod_types_do_not_grant_permissions(self):
        for value in ['dev', 'uat', 'stage', 'development']:
            self.config['salesforce']['orgs'][1]['environment'] = value
            self.assertTrue(self.decide('sf data create record -o prod-copy').allowed)
        self.config['salesforce']['orgs'][0]['environment'] = 'production'
        self.assertEqual(self.decide('sf apex run -o another-name').environment, 'prod')

    def test_qa_requires_assignment_without_blocking_independent_prod(self):
        self.config['salesforce']['orgs'][1]['environment'] = 'qa'
        self.assertEqual(self.decide('sf data query -o prod-copy').status, 'migration-required')
        self.assertTrue(self.decide('sf project retrieve start -o team-alpha').allowed)

    def test_alias_identity_drift_and_conflicting_org_classification(self):
        self.config['salesforce']['orgs'].append({'alias': 'another-name', 'environment': 'dev'})
        self.assertEqual(self.decide('sf project retrieve start -o team-alpha').status, 'conflict')
        self.config = copy.deepcopy(CONFIG)
        self.rows[0]['id'] = '00D000000000003'
        self.assertEqual(self.decide('sf project retrieve start -o team-alpha').status, 'identity-error')

    def test_defaults_environment_legacy_and_dev_hub(self):
        for env_name in ['SF_TARGET_ORG', 'SFDX_DEFAULTUSERNAME']:
            self.env = {env_name: 'another-name'}
            self.assertEqual(self.decide('sf data query').environment, 'prod')
        self.env = {'SF_TARGET_DEV_HUB': 'team-alpha'}
        self.assertEqual(self.decide('sf package version create').environment, 'prod')
        self.assertFalse(self.decide('sf package version create -o prod-copy -v team-alpha').allowed)
        self.env = {}
        for directory, filename, key in [('.sf', 'config.json', 'target-org'), ('.sfdx', 'sfdx-config.json', 'defaultusername')]:
            (self.root/directory).mkdir(exist_ok=True)
            (self.root/directory/filename).write_text(json.dumps({key: 'team-alpha'}))
            self.assertEqual(self.decide('sf org display').environment, 'prod')

    def test_conflicting_targets_defaults_missing_config_and_unknown(self):
        self.assertEqual(self.decide('sf project retrieve start -o team-alpha --target-org prod-copy').status, 'conflict')
        self.assertTrue(self.decide('sf project retrieve start -o team-alpha --target-org another-name').allowed)
        self.env = {'SF_TARGET_ORG': 'team-alpha', 'SFDX_DEFAULTUSERNAME': 'prod-copy'}
        self.assertEqual(self.decide('sf org display').status, 'conflict')
        self.assertEqual(self.decide('sf org display -o missing').status, 'identity-unresolved')
        self.config = {}
        self.assertFalse(self.decide('sf project retrieve start -o team-alpha').allowed)

    def test_default_aliases_and_usernames_compare_identity_not_spelling(self):
        self.env = {'SF_TARGET_ORG': 'team-alpha', 'SFDX_DEFAULTUSERNAME': 'owner@example.test'}
        self.assertTrue(self.decide('sf project retrieve start -m ApexClass:One').allowed)
        self.assertEqual(self.decide('sf org display').environment, 'prod')
        self.env = {'SF_TARGET_DEV_HUB': 'prod-copy', 'SFDX_DEFAULTDEVHUBUSERNAME': 'developer@example.test'}
        self.assertTrue(self.decide('sf package version create').allowed)
        self.env = {}
        (self.root / '.sf').mkdir()
        (self.root / '.sf/config.json').write_text(json.dumps({
            'target-org': 'team-alpha', 'defaultusername': 'another-name'}))
        self.assertTrue(self.decide('sf project retrieve start -m ApexClass:One').allowed)
        (self.root / '.sf/config.json').write_text(json.dumps({'target-org': 123}))
        self.assertEqual(self.decide('sf project retrieve start -m ApexClass:One').status, 'config-error')

    def test_timeout_error_and_bad_config_never_allow(self):
        for error in [policy.PolicyError('identity-timeout', 'timeout'), RuntimeError('SECRET')]:
            with patch.object(policy, 'local_authorizations', side_effect=error):
                d = policy.evaluate(['sf', 'apex', 'run', '-o', 'prod-copy'], self.root, config=self.config)
                self.assertFalse(d.allowed)
                self.assertNotIn('SECRET', d.reason)
        self.config['salesforce']['orgs'].append(copy.deepcopy(self.config['salesforce']['orgs'][0]))
        self.assertEqual(self.decide('sf org display -o team-alpha').status, 'conflict')

    def test_no_self_attested_grant_and_no_reused_decision(self):
        self.env = {'ENVIRONMENT': 'dev', 'APPROVED': 'true', 'SF_ENVIRONMENT': 'dev'}
        self.assertFalse(self.decide('sf data query -o missing --environment dev --approved').allowed)
        self.assertTrue(self.decide('sf data query -o prod-copy').allowed)
        self.config['salesforce']['orgs'][1]['environment'] = 'prod'
        self.assertFalse(self.decide('sf data query -o prod-copy').allowed)

    def test_internal_transport_is_fixed_bounded_and_sanitizes(self):
        raw = {'status': 0, 'result': [{'username': ROWS[0]['username'], 'orgId': PROD_ID+'AAA',
               'instanceUrl': 'https://sample.my.salesforce.com', 'alias': 'team-alpha,another-name', 'accessToken': 'TOP-SECRET'}]}
        with patch.object(policy.shutil, 'which', return_value='/trusted/sf'), patch.object(policy.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(raw))) as run:
            rows = policy.local_authorizations(self.root, {'SF_TEMP_SHOW_SECRETS': 'true'})
            self.assertNotIn('TOP-SECRET', repr(rows))
            self.assertEqual(run.call_args.args[0], ['/trusted/sf', 'org', 'list', 'auth', '--json'])
            self.assertEqual(run.call_args.kwargs['timeout'], 2.0)
            self.assertEqual(run.call_args.kwargs['env']['SF_TEMP_SHOW_SECRETS'], 'false')
        with patch.object(policy.shutil, 'which', return_value='/trusted/sf'), patch.object(policy.subprocess, 'run', side_effect=subprocess.TimeoutExpired('internal', 2)):
            with self.assertRaises(policy.PolicyError) as error:
                policy.local_authorizations(self.root, {})
            self.assertEqual(error.exception.status, 'identity-timeout')

    def test_hook_denial_keeps_controlled_executor_uninvoked(self):
        calls = []
        for command in ['sf data query -o team-alpha', 'sf project deploy start -o another-name',
                        'sf apex run -o missing', 'sfdx force:source:deploy -u team-alpha']:
            event = {'tool_name': 'execute/runInTerminal', 'tool_input': {'command': command, 'environment': 'dev', 'approved': True}, 'tool_use_id': 'one'}
            output = StringIO()
            with patch.object(safety, 'HARNESS_ROOT', self.root), patch.object(safety, 'load_config', return_value=self.config), patch.object(policy, '_read_json', return_value=self.config), patch.object(policy, 'local_authorizations', return_value=self.rows), patch.object(sys, 'stdin', StringIO(json.dumps(event))), patch.object(sys, 'stdout', output):
                self.assertEqual(safety.main(), 0)
            response = json.loads(output.getvalue())
            if response.get('continue') is True:
                calls.append(command)  # controlled executor, never Salesforce
            self.assertEqual(response['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertEqual(calls, [])

    def test_role_still_owns_cli_authority(self):
        with patch.object(policy, '_read_json', return_value=self.config), patch.object(policy, 'local_authorizations', return_value=self.rows):
            for role in ['reviewer', 'designer', 'knowledge-curator', 'config-investigator']:
                self.assertFalse(roles.allowed_role_command('sf project retrieve start -o team-alpha', self.root, role))
            self.assertTrue(roles.allowed_role_command('sf project retrieve start -o team-alpha', self.root, 'developer'))
            self.assertFalse(roles.allowed_role_command('sf project deploy start -o team-alpha', self.root, 'developer'))

    def test_local_help_without_identity(self):
        self.config = {}
        for command in ['sf --version', 'sfdx --help', 'sf project retrieve start --help']:
            self.assertTrue(self.decide(command).allowed)
    def test_cached_production_job_cannot_use_nonprod_flag(self):
        (self.root/'.sf').mkdir()
        (self.root/'.sf/deploy-cache.json').write_text(json.dumps({
            '0Af000000000001AAA': {'target-org': 'team-alpha', 'timestamp': '2099-01-01T00:00:00Z'}
        }))
        for cmd in ['report', 'quick', 'resume', 'cancel']:
            for target in ['', ' -o prod-copy', ' -o team-alpha']:
                with self.subTest(cmd=cmd, target=target):
                    self.assertFalse(self.decide(f'sf project deploy {cmd} --job-id 0Af000000000001{target}').allowed)
        self.assertFalse(self.decide('sf project deploy report --use-most-recent -o prod-copy').allowed)

    def test_known_nonprod_job_uses_its_cache_identity(self):
        (self.root/'.sf').mkdir()
        (self.root/'.sf/deploy-cache.json').write_text(json.dumps({
            '0Af000000000001AAA': {'target-org': 'prod-copy', 'timestamp': '2099-01-01T00:00:00Z'}
        }))
        self.assertTrue(self.decide('sf project deploy resume --job-id 0Af000000000001AAA').allowed)
        self.assertFalse(self.decide('sf random mutation -o prod-copy').allowed)


class HookProcessTests(unittest.TestCase):
    def test_real_hook_process_and_stub_cli_never_execute_forbidden_operation(self):
        from scripts.prepare_salesforce_policy_pilot import prepare
        with tempfile.TemporaryDirectory() as name:
            root = prepare(Path(name) / 'pilot')
            (root/'config/harness.local.json').write_text(json.dumps(CONFIG))
            inventory = {'status': 0, 'result': [
                {'orgId': row['id']+'AAA', 'instanceUrl': 'https://'+row['host'],
                 'username': row['username'], 'alias': ','.join(row['aliases']), 'accessToken': 'DO-NOT-LOG'}
                for row in ROWS]}
            (root/'inventory.json').write_text(json.dumps(inventory))
            stub = root/'scripts/pilot_cli.py'
            env = {**os.environ, **json.loads((root/'pilot-environment.json').read_text())}
            for command in ['sf data query -o team-alpha', 'sf project deploy start -o another-name',
                            'sf project retrieve start -o team-alpha --flags-dir flags',
                            'sf apex run -o absent']:
                event={'tool_name':'execute/runInTerminal','tool_input':{'command':command}}
                result=subprocess.run([sys.executable,str(root/'scripts/copilot_safety_hook.py')],input=json.dumps(event),text=True,capture_output=True,cwd=root,env=env,timeout=5)
                self.assertEqual(result.returncode,0,result.stderr)
                response=json.loads(result.stdout)
                if response.get('continue') is True:
                    subprocess.run([sys.executable,str(stub),*shlex.split(command)[1:]],cwd=root,env=env,check=True)
                self.assertEqual(response['hookSpecificOutput']['permissionDecision'],'deny')
                self.assertNotIn('"kind": "operation"', (root/'.cache/executor.jsonl').read_text())
                self.assertNotIn('DO-NOT-LOG',result.stdout+result.stderr)
            # A local inventory timeout produces deny before the outer 5 second budget.
            (root/'.cache/inventory-mode.txt').write_text('timeout')
            event={'tool_name':'execute/runInTerminal','tool_input':{'command':'sf project retrieve start -o team-alpha'}}
            result=subprocess.run([sys.executable,str(root/'scripts/copilot_safety_hook.py')],input=json.dumps(event),text=True,capture_output=True,cwd=root,env=env,timeout=5)
            self.assertEqual(json.loads(result.stdout)['hookSpecificOutput']['permissionDecision'],'deny')
            self.assertNotIn('"kind": "operation"', (root/'.cache/executor.jsonl').read_text())
            # Malformed event errors cannot exit with the host's nonblocking error status.
            for payload in ['[1]', '{invalid']:
                result=subprocess.run([sys.executable,str(root/'scripts/copilot_safety_hook.py')],input=payload,text=True,capture_output=True,cwd=root,env=env,timeout=5)
                self.assertEqual(result.returncode,0)
                self.assertEqual(json.loads(result.stdout)['hookSpecificOutput']['permissionDecision'],'deny')
