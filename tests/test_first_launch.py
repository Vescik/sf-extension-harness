"""Onboarding must accept exactly the org shapes the runtime accepts.

`first_launch.py` had no tests, and it silently drifted: it kept requiring
`*--*.sandbox.my.salesforce.com` with `IsSandbox=true` long after the 2026-07-31 decision
admitted scratch orgs and Developer Editions. The result was that the one org shape a
tester is most likely to have could not be onboarded at all — the config entry had to be
hand-written, which is how the drift stayed invisible.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("first_launch", ROOT / "scripts" / "first_launch.py")
assert SPEC and SPEC.loader
first_launch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(first_launch)


class HostClassificationTests(unittest.TestCase):
    def test_generic_host_classifier_accepts_production_and_preserves_nonprod_types(self) -> None:
        for host, result in (
            ("acme.my.salesforce.com", ("production", False)),
            ("na123.salesforce.com", ("production", False)),
            ("acme--dev.sandbox.my.salesforce.com", ("sandbox", True)),
            ("mpsadev.scratch.my.salesforce.com", ("scratch", True)),
            ("orgfarm-x-dev-ed.develop.my.salesforce.com", ("developer-edition", False)),
            ("login.salesforce.com", None),
            ("test.salesforce.com", None),
            ("acme.my.salesforce.com.evil.test", None),
        ):
            with self.subTest(host=host):
                self.assertEqual(first_launch.classify_salesforce_host(host), result)

    def test_sandbox_and_scratch_expect_is_sandbox_true(self) -> None:
        for host in (
            "acme--dev.sandbox.my.salesforce.com",
            "mpsadev.scratch.my.salesforce.com",
        ):
            with self.subTest(host=host):
                self.assertEqual(first_launch.classify_non_production_host(host), (True, True))

    def test_developer_edition_expects_is_sandbox_false(self) -> None:
        """Salesforce reports false for a Developer Edition; that is the proof, not a failure."""
        self.assertEqual(
            first_launch.classify_non_production_host("orgfarm-x-dev-ed.develop.my.salesforce.com"),
            (True, False),
        )

    def test_production_and_login_hosts_are_refused(self) -> None:
        for host in (
            "acme.my.salesforce.com",
            "login.salesforce.com",
            "acme.develop.my.salesforce.com.evil.test",
            "",
        ):
            with self.subTest(host=host):
                self.assertIsNone(first_launch.classify_non_production_host(host))


class ConfigWritingTests(unittest.TestCase):
    def test_ado_org_change_replaces_old_scope_and_preserves_non_ado_origins(self) -> None:
        cfg = {"ado": {
            "organization": "old-org", "project": "Existing project",
            "releaseQueryId": "existing-query",
            "allowedHttpsOrigins": ["https://dev.azure.com/old-org", "https://old-org.visualstudio.com",
                                    "https://almsearch.dev.azure.com/old-org",
                                    "https://attachments.example.test/approved"],
        }, "unrelated": {"keep": True}}
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "harness.local.json"
            path.write_text(json.dumps(cfg), encoding="utf-8")
            with patch.object(first_launch, "CONFIG_PATH", path):
                first_launch.apply_config({"ado.organization": "new-org"})
            written = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(written["ado"], {
            "organization": "new-org", "project": "Existing project", "releaseQueryId": "existing-query",
            "allowedHttpsOrigins": ["https://dev.azure.com/new-org", "https://attachments.example.test/approved"],
        })
        self.assertEqual(written["unrelated"], cfg["unrelated"])

    def test_ado_project_change_preserves_current_origins_and_rejects_invalid_update_without_write(self) -> None:
        cfg = {"ado": {
            "organization": "example-org", "project": "Old project", "releaseQueryId": "existing-query",
            "allowedHttpsOrigins": ["https://dev.azure.com/example-org", "https://attachments.example.test"],
        }}
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "harness.local.json"
            path.write_text(json.dumps(cfg), encoding="utf-8")
            with patch.object(first_launch, "CONFIG_PATH", path):
                first_launch.apply_config({"ado.project": "New project Ż"})
                written = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(written["ado"]["project"], "New project Ż")
                self.assertEqual(written["ado"]["allowedHttpsOrigins"], cfg["ado"]["allowedHttpsOrigins"])
                for pending in ({"ado.organization": "https://other.test"}, {"ado.project": " "},
                                {"ado.organization": "<ORG>"}, {"ado.project": "TODO"}):
                    before = path.read_bytes()
                    with self.subTest(pending=pending), self.assertRaisesRegex(ValueError, "ADO configuration error"):
                        first_launch.apply_config(pending)
                    self.assertEqual(path.read_bytes(), before)

    def test_review_collection_requires_explicit_yes_and_nonempty_scope(self) -> None:
        for answers, expected in (
            (["no"], {}), (["yes", ""], {}),
            (["yes", "Account"], {"review.enabled": True, "review.objects": ["Account"]}),
        ):
            pending = {}
            with patch.object(first_launch, "prompt", side_effect=answers):
                first_launch.collect_review_allowlist(pending)
            self.assertEqual(pending, expected)

    def test_legacy_production_context_writes_canonical_environment(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "harness.local.json"
            path.write_text(json.dumps({"ado": {}, "salesforce": {"orgs": [], "review": {}}}))
            with patch.object(first_launch, "CONFIG_PATH", path):
                first_launch.apply_config({"org.production": {"alias": "prod-read",
                    "host": "acme.my.salesforce.com", "orgId": "00D000000000002AAA"}})
            self.assertEqual(json.loads(path.read_text())["salesforce"]["orgs"][0]["environment"], "prod")

    def test_developer_edition_writes_pins_and_no_flags(self) -> None:
        """Owner 2026-08-04: onboarding writes identity pins only — no allowAgent* flags
        and no allowAnyNonProduction toggle (both retired with the read-anywhere convention)."""
        cfg = {
            "ado": {},
            "salesforce": {"orgs": [], "review": {}},
        }
        pending = {
            "org.development": {
                "alias": "devmp",
                "host": "orgfarm-x-dev-ed.develop.my.salesforce.com",
                "orgId": "00D000000000000EAA",
            },
        }
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "harness.local.json"
            path.write_text(json.dumps(cfg), encoding="utf-8")
            with patch.object(first_launch, "CONFIG_PATH", path):
                first_launch.apply_config(pending)
            written = json.loads(path.read_text(encoding="utf-8"))

        self.assertNotIn("allowAnyNonProduction", written["salesforce"]["review"])
        org = written["salesforce"]["orgs"][0]
        self.assertEqual(org["expectedInstanceHost"], "orgfarm-x-dev-ed.develop.my.salesforce.com")
        self.assertEqual(org["expectedOrganizationId"], "00D000000000000EAA")
        for retired in ("allowAgentRead", "allowAgentReview", "allowAgentWrite"):
            self.assertNotIn(retired, org)

    def test_sandbox_onboarding_does_not_touch_the_toggle(self) -> None:
        cfg = {
            "ado": {},
            "salesforce": {"orgs": [], "review": {}},
        }
        pending = {
            "org.development": {
                "alias": "dev-sbx",
                "host": "acme--dev.sandbox.my.salesforce.com",
                "orgId": "00D000000000001AAA",
            },
        }
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "harness.local.json"
            path.write_text(json.dumps(cfg), encoding="utf-8")
            with patch.object(first_launch, "CONFIG_PATH", path):
                first_launch.apply_config(pending)
            written = json.loads(path.read_text(encoding="utf-8"))

        self.assertNotIn("allowAnyNonProduction", written["salesforce"]["review"])


class LocalConfigFindingsTests(unittest.TestCase):
    """Setup reports configuration shape only — never universal live readiness."""

    SCHEMA = json.dumps({"type": "object", "required": ["ado"]})

    def test_invalid_json_is_one_precise_finding(self) -> None:
        findings = first_launch.local_config_findings("{not json", self.SCHEMA)
        self.assertEqual(len(findings), 1)
        self.assertIn("invalid JSON", findings[0])

    def test_placeholders_are_reported_by_exact_path(self) -> None:
        config = json.dumps(
            {"ado": {"organization": "<ADO_ORG>", "project": "real"},
             "salesforce": {"orgs": [{"alias": "<ALIAS>"}]}}
        )
        findings = first_launch.local_config_findings(config, self.SCHEMA)
        self.assertIn("unresolved placeholder at ado.organization", findings)
        self.assertIn("unresolved placeholder at salesforce.orgs[0].alias", findings)
        self.assertTrue(any("ADO configuration error: ado.organization" in finding for finding in findings))

    def test_schema_violation_is_reported_and_clean_config_passes(self) -> None:
        config = {"ado": {"organization": "example-org", "project": "Example project",
                          "allowedHttpsOrigins": ["https://dev.azure.com/example-org"]}}
        self.assertEqual(first_launch.local_config_findings(json.dumps(config), self.SCHEMA), [])
        findings = first_launch.local_config_findings(json.dumps({}), self.SCHEMA)
        self.assertTrue(any("config schema validation failed" in finding for finding in findings))

    def test_ado_scope_validation_does_not_require_schema_or_legacy_env(self) -> None:
        valid = {"organization": "example-org", "project": "Example project",
                 "allowedHttpsOrigins": ["https://dev.azure.com/example-org"]}
        for legacy in (None, "", " ", "different-org"):
            with self.subTest(legacy=legacy), patch.dict(first_launch.os.environ, {}, clear=True):
                if legacy is not None:
                    first_launch.os.environ["ADO_ORGANIZATION"] = legacy
                self.assertEqual(first_launch.local_config_findings(json.dumps({"ado": valid}), None), [])
        for key, value in (("organization", None), ("organization", " "), ("project", 3),
                           ("project", ""), ("project", "TBD"),
                           ("allowedHttpsOrigins", ["https://dev.azure.com/previous-org"])):
            with self.subTest(key=key, value=value):
                findings = first_launch.local_config_findings(json.dumps({"ado": {**valid, key: value}}), None)
                self.assertTrue(any(f"ADO configuration error: ado.{key}" in finding for finding in findings))

    def test_findings_describe_config_shape_not_capability_readiness(self) -> None:
        # The distinction §setup vs point-of-use: nothing in a finding may claim an
        # external capability was proven or is unusable — only config shape.
        config = json.dumps({"ado": {"organization": "<ADO_ORG>"}})
        for finding in first_launch.local_config_findings(config, None):
            for banned in ("ready", "preflight", "live", "proven"):
                self.assertNotIn(banned, finding.lower())


class AdoDependencyVerificationTests(unittest.TestCase):
    def test_verify_checks_installed_pin_without_starting_connector(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            config = root / "harness.local.json"
            config.write_text(json.dumps({"ado": {"organization": "example-org", "project": "Example project",
                              "allowedHttpsOrigins": ["https://dev.azure.com/example-org"]}}), encoding="utf-8")
            package = root / "node_modules" / "@azure-devops" / "mcp"
            package.mkdir(parents=True)
            for version, has_entrypoint, package_name, expected_error in (
                (None, False, "@azure-devops/mcp", True), ("2.8.1", False, "@azure-devops/mcp", True),
                ("2.8.2", True, "@azure-devops/mcp", True), ("2.8.1", True, "another-package", True),
                ("2.8.1", True, "@azure-devops/mcp", False),
            ):
                with self.subTest(version=version, entrypoint=has_entrypoint, package=package_name):
                    if version is not None:
                        (package / "package.json").write_text(json.dumps({"name": package_name, "version": version}), encoding="utf-8")
                    if has_entrypoint:
                        (package / "dist").mkdir(exist_ok=True)
                        (package / "dist" / "index.js").write_text("", encoding="utf-8")
                    with patch.object(first_launch, "REPO_ROOT", root), patch.object(first_launch, "CONFIG_PATH", config), \
                         patch.object(first_launch, "SCHEMA_PATH", root / "absent-schema.json"), \
                         patch.object(first_launch, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
                        valid, findings = first_launch.verify()
                    self.assertTrue(valid)
                    self.assertEqual(any("ADO dependency" in finding for finding in findings), expected_error)
                    run.assert_called_once()
                    self.assertEqual(Path(run.call_args.args[0][1]).name, "validate_harness.py")


if __name__ == "__main__":
    unittest.main()

class MultipleOrgMigrationTests(unittest.TestCase):
    def apply(self, orgs, pending):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name)/'harness.local.json'
            cfg = {'ado':{}, 'salesforce':{'orgs':orgs,'review':{}}}
            path.write_text(json.dumps(cfg))
            before=path.read_text()
            with patch.object(first_launch,'CONFIG_PATH',path):
                try:
                    first_launch.apply_config(pending)
                except ValueError:
                    self.assertEqual(path.read_text(),before)
                    raise
            return json.loads(path.read_text())['salesforce']['orgs']

    def test_add_and_update_only_one_alias_with_same_environment(self):
        a={'alias':'team-alpha','environment':'dev','expectedOrganizationId':'00D000000000001AAA','expectedInstanceHost':'a--dev.sandbox.my.salesforce.com'}
        b={'alias':'prod-copy','environment':'dev','expectedOrganizationId':'00D000000000002AAA','expectedInstanceHost':'b--dev.sandbox.my.salesforce.com'}
        pending={'org.anything':{'environment':'stage','alias':'prod-copy','orgId':b['expectedOrganizationId'],'host':b['expectedInstanceHost']}}
        result=self.apply([a,b],pending)
        self.assertEqual(result[0],a)
        self.assertEqual(result[1]['environment'],'stage')
        pending['org.third']={'environment':'dev','alias':'unrelated-name','orgId':'00D000000000003AAA','host':'c--dev.sandbox.my.salesforce.com'}
        result=self.apply([a,b],pending)
        self.assertEqual(len(result),3)
        self.assertEqual(result[0],a)

    def test_production_identity_cannot_be_downgraded_by_new_alias(self):
        for spelling in ['prod','production']:
            with self.subTest(spelling=spelling),self.assertRaises(ValueError):
                self.apply([{'alias':'team-alpha','environment':spelling,'expectedOrganizationId':'00D000000000001AAA'}],
                           {'org.prod-copy':{'environment':'dev','alias':'prod-copy','orgId':'00D000000000001AAA','host':'sample.my.salesforce.com'}})

    def test_qa_requires_explicit_assignment_and_diagnostics_name_entry(self):
        with self.assertRaises(ValueError):
            self.apply([],{'org.qa':{'alias':'qa-team','orgId':'00D000000000001AAA','host':'a--qa.sandbox.my.salesforce.com'}})
        cfg={'salesforce':{'orgs':[{'alias':'qa-team','environment':'qa'}]}}
        findings=first_launch.local_config_findings(json.dumps(cfg),None)
        self.assertTrue(any('salesforce.orgs[0].environment (qa-team)' in s and 'explicitly' in s for s in findings))

    def test_schema_matches_runtime_migration_contract(self):
        from jsonschema import Draft202012Validator
        schema=json.loads((ROOT/'schemas/harness-config.schema.json').read_text())['properties']['salesforce']['properties']['orgs']['items']
        validator=Draft202012Validator(schema)
        for value in ['dev','uat','stage','prod','development','production']:
            self.assertEqual(list(validator.iter_errors({'alias':'team-alpha','environment':value})),[])
        for value in ['qa','dynamic','sandbox']:
            self.assertTrue(list(validator.iter_errors({'alias':'team-alpha','environment':value})))
