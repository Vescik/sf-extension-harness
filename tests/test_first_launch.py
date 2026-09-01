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
    def test_sandbox_and_scratch_expect_is_sandbox_true(self) -> None:
        for host in (
            "acme--dev.sandbox.my.salesforce.com",
            "mpsadev.scratch.my.salesforce.com",
        ):
            with self.subTest(host=host):
                self.assertTrue(first_launch.classify_non_production_host(host))

    def test_developer_edition_expects_is_sandbox_false(self) -> None:
        """Salesforce reports false for a Developer Edition; that is the proof, not a failure."""
        self.assertTrue(
            first_launch.classify_non_production_host("orgfarm-x-dev-ed.develop.my.salesforce.com")
        )

    def test_production_and_login_hosts_are_refused(self) -> None:
        for host in (
            "acme.my.salesforce.com",
            "login.salesforce.com",
            "acme.develop.my.salesforce.com.evil.test",
            "",
        ):
            with self.subTest(host=host):
                self.assertFalse(first_launch.classify_non_production_host(host))


class ConfigWritingTests(unittest.TestCase):
    def test_developer_edition_writes_pins_and_no_flags(self) -> None:
        """Owner 2026-08-04: onboarding writes identity pins only — no allowAgent* flags
        and no allowAnyNonProduction toggle (both retired with the read-anywhere convention)."""
        cfg = {
            "ado": {},
            "salesforce": {"orgs": [{"environment": "development"}], "review": {}},
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
            "salesforce": {"orgs": [{"environment": "development"}], "review": {}},
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
        self.assertEqual(len(findings), 2)

    def test_schema_violation_is_reported_and_clean_config_passes(self) -> None:
        self.assertEqual(first_launch.local_config_findings(json.dumps({"ado": {}}), self.SCHEMA), [])
        findings = first_launch.local_config_findings(json.dumps({}), self.SCHEMA)
        self.assertEqual(len(findings), 1)
        self.assertIn("config schema validation failed", findings[0])

    def test_findings_describe_config_shape_not_capability_readiness(self) -> None:
        # The distinction §setup vs point-of-use: nothing in a finding may claim an
        # external capability was proven or is unusable — only config shape.
        config = json.dumps({"ado": {"organization": "<ADO_ORG>"}})
        for finding in first_launch.local_config_findings(config, None):
            for banned in ("ready", "preflight", "live", "proven"):
                self.assertNotIn(banned, finding.lower())


if __name__ == "__main__":
    unittest.main()
