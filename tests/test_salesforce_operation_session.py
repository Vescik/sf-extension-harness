"""Native answers authorize only one immutable operation; no real CLI/org is used."""
from __future__ import annotations

import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import salesforce_operation_session as native


class NativeSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / 'workspace'
        self.home = Path(self.tmp.name).resolve() / 'home'
        (self.root / 'config').mkdir(parents=True)
        self.home.mkdir()
        (self.root / 'sfdx-project.json').write_text('{}')
        self.rows = [
            {'username': 'prod@example.test', 'id': '00D000000000001',
             'host': 'example.my.salesforce.com', 'aliases': ['primary']},
            {'username': 'dev@example.test', 'id': '00D000000000002',
             'host': 'example--dev.sandbox.my.salesforce.com', 'aliases': ['team-two']},
        ]
        self.config = {'salesforce': {'orgs': [
            {'alias': row['aliases'][0], 'environment': environment,
             'expectedOrganizationId': row['id'], 'expectedInstanceHost': row['host']}
            for row, environment in zip(self.rows, ['prod', 'dev'])]}}
        self.path = self.root / 'config/harness.local.json'
        self.save()
        self.events = []
        self.answers = []

    def save(self):
        self.path.write_text(json.dumps(self.config))

    def ask(self, event):
        self.events.append(event)
        value = self.answers.pop(0) if self.answers else None
        return {'promptId': event['promptId'], 'value': value}

    def session(self, **kwargs):
        return native.OperationSession(self.root, kwargs.pop('ask', self.ask), home=self.home,
            env=kwargs.pop('env', {}), inventory=kwargs.pop('inventory', lambda *_: self.rows), **kwargs)

    def run_operation(self, args, **kwargs):
        return self.session(**kwargs).prepare({'arguments': args})

    def unknown(self, index=1):
        self.config['salesforce']['orgs'].pop(index)
        self.save()

    def test_configured_org_is_pinned_without_a_question(self):
        result = self.run_operation(['data', 'query', '-o', 'team-two', '-q', 'SELECT Id FROM Account'])
        self.assertEqual(result['type'], 'execute')
        self.assertEqual(result['execution']['arguments'][3], 'dev@example.test')
        self.assertEqual(result['execution']['targets'][0]['environment'], 'dev')
        self.assertEqual(result['digest'], native.digest(result['execution']))
        self.assertEqual(self.events, [])

    def test_environment_is_one_operation_only_and_never_persisted(self):
        self.unknown()
        before = self.path.read_bytes()
        args = ['data', 'query', '-o', 'team-two', '-q', 'SELECT Id FROM Account']
        for environment in ['dev', 'uat', 'stage']:
            self.answers = [environment]
            result = self.run_operation(args)
            self.assertEqual(result['execution']['targets'][0]['environment'], environment)
            self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual([e['type'] for e in self.events], ['environment'] * 3)
        self.assertEqual(len({e['promptId'] for e in self.events}), 3)

    def test_query_punctuation_remains_one_literal_argument(self):
        self.unknown()
        self.answers = ['dev']
        query = "SELECT Id FROM Account WHERE AnnualRevenue > 1 AND Name = '$Example;Inc'"
        result = self.run_operation(['data', 'query', '-o', 'team-two', '-q', query])
        self.assertEqual(result['execution']['arguments'][-1], query)

    def test_unclassified_regular_host_can_be_developer_edition(self):
        self.unknown(0)
        self.answers = ['dev']
        result = self.run_operation(['data', 'query', '-o', 'primary', '-q', 'SELECT Id FROM Account'])
        self.assertEqual(self.events[0]['environments'], ['dev', 'uat', 'stage', 'prod'])
        self.assertEqual(result['execution']['targets'][0]['environment'], 'dev')

    def test_unknown_chosen_prod_restricts_to_retrieve(self):
        self.unknown()
        self.answers = ['prod']
        with self.assertRaisesRegex(native.SessionError, 'Production CLI'):
            self.run_operation(['data', 'query', '-o', 'team-two', '-q', 'SELECT Id FROM Account'])
        self.answers = ['prod']
        result = self.run_operation(['project', 'retrieve', 'start', '-o', 'team-two', '-m', 'ApexClass:Sample'])
        self.assertEqual(result['execution']['targets'][0]['environment'], 'prod')

    def test_known_prod_cannot_be_overridden(self):
        self.answers = ['dev', True]
        with self.assertRaisesRegex(native.SessionError, 'Production CLI'):
            self.run_operation(['project', 'deploy', 'start', '-o', 'primary', '-m', 'ApexClass:Sample'])
        self.assertEqual(self.events, [])

    def test_missing_target_uses_native_picker_then_environment(self):
        self.unknown()
        self.answers = ['dev@example.test', 'uat']
        result = self.run_operation(['org', 'display'])
        self.assertEqual([e['type'] for e in self.events], ['selectOrg', 'environment'])
        self.assertEqual(result['execution']['arguments'][-2:], ['--target-org', 'dev@example.test'])
        self.assertEqual(self.events[0]['items'][1]['id'], '00D000000000001')

    def test_resolved_default_is_pinned_but_conflicting_defaults_block(self):
        result = self.run_operation(['org', 'display'], env={'SF_TARGET_ORG': 'team-two'})
        self.assertEqual(result['execution']['arguments'][-1], 'dev@example.test')
        with self.assertRaisesRegex(native.SessionError, 'Conflicting default'):
            self.run_operation(['org', 'display'], env={'SF_TARGET_ORG': 'team-two', 'SFDX_DEFAULTUSERNAME': 'primary'})

    def test_missing_identity_and_denied_id_never_ask_environment(self):
        with self.assertRaises(native.SessionError):
            self.run_operation(['org', 'display', '-o', 'missing'])
        self.unknown()
        self.config['salesforce']['review'] = {'deniedOrganizationIds': ['00D000000000002']}
        self.save()
        with self.assertRaisesRegex(native.SessionError, 'denied'):
            self.run_operation(['org', 'display', '-o', 'team-two'])
        self.assertEqual(self.events, [])

    def test_deploy_answer_is_separate_and_requires_actual_boolean_true(self):
        self.unknown()
        args = ['project', 'deploy', 'start', '-o', 'team-two', '-m', 'ApexClass:Sample']
        self.answers = ['dev', True]
        result = self.run_operation(args)
        self.assertEqual([e['type'] for e in self.events], ['environment', 'confirmDeploy'])
        self.assertEqual(result['execution']['targets'][0]['environment'], 'dev')
        self.assertIn('ApexClass:Sample', self.events[-1]['scope'])
        for forged in [False, 'true', 1, None]:
            self.answers = ['dev', forged]
            with self.subTest(answer=forged), self.assertRaises(native.SessionError):
                self.run_operation(args)

    def test_validation_does_not_ask_real_deployment_consent(self):
        self.run_operation(['project', 'deploy', 'validate', '-o', 'team-two', '-m', 'ApexClass:Sample'])
        self.assertEqual(self.events, [])

    def test_canceled_and_forged_or_replayed_answers_block(self):
        self.unknown()
        args = ['org', 'display', '-o', 'team-two']
        for answer in [None, 'qa', True, {'environment': 'dev'}]:
            self.answers = [answer]
            with self.subTest(answer=answer), self.assertRaises(native.SessionError):
                self.run_operation(args)
        for reply in [{'promptId': 'old', 'value': 'dev'}, {'value': 'dev'},
                      {'promptId': 'old', 'value': 'dev', 'approved': True}]:
            with self.assertRaises(native.SessionError):
                self.run_operation(args, ask=lambda _: reply)

    def test_invocation_is_consumed_after_success_or_failure(self):
        for target in ['team-two', 'missing']:
            session = self.session()
            request = {'arguments': ['org', 'display', '-o', target]}
            try:
                session.prepare(request)
            except native.SessionError:
                pass
            with self.assertRaisesRegex(native.SessionError, 'already been consumed'):
                session.prepare(request)

    def test_config_inventory_and_cache_changes_during_dialog_abort(self):
        self.unknown()
        original_rows = copy.deepcopy(self.rows)
        original_config = self.path.read_bytes()
        cache = self.home / '.sf/deploy-cache.json'
        cache.parent.mkdir()
        def change_config():
            self.path.write_text('{}')
        def change_identity():
            self.rows[1]['id'] = '00D000000000003'
        def change_cache():
            cache.write_text('{}')
        for mutation in [change_config, change_identity, change_cache]:
            self.rows = copy.deepcopy(original_rows)
            self.path.write_bytes(original_config)
            def ask(event):
                mutation()
                return {'promptId': event['promptId'], 'value': 'dev'}
            with self.subTest(change=mutation.__name__), self.assertRaisesRegex(native.SessionError, 'changed'):
                self.run_operation(['org', 'display', '-o', 'team-two'], ask=ask)

    def test_config_changed_while_loading_is_rejected(self):
        real_read = native.policy._read_json
        def reading(path, *args, **kwargs):
            data = real_read(path, *args, **kwargs)
            if path == self.path:
                self.path.write_text('{}')
            return data
        with patch.object(native.policy, '_read_json', side_effect=reading), self.assertRaisesRegex(native.SessionError, 'changed while loading'):
            self.run_operation(['org', 'display', '-o', 'team-two'])

    def test_user_cannot_supply_environment_or_approval(self):
        request = {'arguments': ['org', 'display', '-o', 'team-two']}
        for key, value in [('environment', 'dev'), ('approved', True), ('workspace', '/tmp')]:
            with self.subTest(key=key), self.assertRaises(native.SessionError):
                self.session().prepare({**request, key: value})

    def test_malformed_or_compound_arguments_are_rejected(self):
        for args in [[], ['org', 'display;id'], ['org', 'display', '-o', 'a\n'],
                     ['org', 'display', '--flags-dir=folder'], ['api', 'request', 'rest'],
                     ['org', 'display', 7], ['x'] * 129]:
            with self.subTest(args=args), self.assertRaises(native.SessionError):
                self.run_operation(args)

    def test_multiple_controlling_orgs_are_classified(self):
        self.config['salesforce']['orgs'] = []
        self.save()
        self.answers = ['dev', 'stage']
        result = self.run_operation(['org', 'create', 'scratch', '-o', 'team-two', '-v', 'primary', '-f', 'config/project-scratch-def.json'])
        self.assertEqual([t['environment'] for t in result['execution']['targets']], ['dev', 'stage'])
        self.assertEqual([e['type'] for e in self.events], ['environment', 'environment'])

    def test_native_job_binding_is_immutable_and_subject_to_prod_rules(self):
        job = {'family': 'deploy', 'action': 'report', 'jobId': '0Af000000000001AAA',
               'username': 'dev@example.test', 'id': self.rows[1]['id'], 'host': self.rows[1]['host'],
               'options': {'waitMinutes': 0, 'async': False, 'apiVersion': None, 'rest': False}}
        def select(parts, home, rows):
            return {'parts': ['sf', 'project', 'deploy', 'report', '--job-id', job['jobId'], '-o', job['username']],
                    'targets': [job['username']], 'job': job}
        result = self.run_operation(['project', 'deploy', 'report', '--use-most-recent'], job_selector=select)
        job['username'] = 'prod@example.test'
        self.assertEqual(result['execution']['job']['username'], 'dev@example.test')
        with self.assertRaisesRegex(native.SessionError, 'Production CLI'):
            self.run_operation(['project', 'deploy', 'report', '--use-most-recent'], job_selector=select)


class ProtocolInputTests(unittest.TestCase):
    def test_single_json_line_and_no_eof_or_oversized_input(self):
        self.assertEqual(native.read_line(io.StringIO('{"arguments":["org","display"]}\n')), {'arguments': ['org', 'display']})
        for raw in ['', '{}', 'not-json\n', 'x' * (native.MAX_LINE + 1) + '\n', '"' + 'ą' * native.MAX_LINE + '"\n']:
            with self.subTest(length=len(raw)), self.assertRaises(native.SessionError):
                native.read_line(io.StringIO(raw))

    def test_timeout_fails_closed(self):
        import threading
        done = threading.Event()
        self.addCleanup(done.set)
        class WaitingStream:
            def readline(self, _):
                done.wait(1)
                return '{}\n'
        with self.assertRaisesRegex(native.SessionError, 'timed out'):
            native.read_line(WaitingStream(), timeout=0.01)


if __name__ == '__main__':
    unittest.main()
