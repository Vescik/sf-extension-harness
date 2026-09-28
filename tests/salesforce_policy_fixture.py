"""Synthetic local identity inventory for hook regressions; never contacts real CLI/orgs."""
from contextlib import contextmanager
from pathlib import Path
import tempfile
from unittest.mock import patch
from scripts import salesforce_operation_policy as policy

CONFIG = {'salesforce': {'orgs': [
    {'alias': 'dev-sbx', 'environment': 'dev'},
    {'alias': 'qa-sbx', 'environment': 'uat'},
    {'alias': 'production', 'environment': 'prod'},
    {'alias': 'scratch-one', 'environment': 'dev'},
]}}
ROWS = [{'id': f'00D00000000000{i}', 'host': f'example--{name.removesuffix("-sbx")}.sandbox.my.salesforce.com',
         'username': name+'@example.test', 'aliases': [name] + (['prod-full'] if name == 'production' else [])}
        for i, name in enumerate(['dev-sbx', 'qa-sbx', 'production', 'scratch-one'], 1)]

def fixture_json(path, **kwargs):
    if path.name == 'harness.local.json':
        return CONFIG
    if path.name == 'deploy-cache.json':
        return {'0Af000000000001AAA': {'target-org': 'dev-sbx', 'timestamp': '2099-01-01T00:00:00Z'}}
    if path.name == 'scratch-one@example.test.json':
        return {'username': 'scratch-one@example.test', 'orgId': '00D000000000004AAA',
                'isScratch': True, 'devHubUsername': 'dev-sbx@example.test'}
    return {'target-org': 'dev-sbx', 'target-dev-hub': 'dev-sbx'}


@contextmanager
def configured_policy():
    with tempfile.TemporaryDirectory() as home, \
         patch.object(policy.Path, 'home', return_value=Path(home)), \
         patch.object(policy.shutil, 'which', side_effect=lambda name, **kw: '/usr/local/bin/'+name), \
         patch.object(policy, '_read_json', side_effect=fixture_json), \
         patch.object(policy, 'local_authorizations', return_value=ROWS), \
         patch.object(policy.os, 'environ', {}):
        yield
