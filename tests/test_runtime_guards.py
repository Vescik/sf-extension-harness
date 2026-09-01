from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from jsonschema import Draft202012Validator

from scripts import verify_salesforce_org as verifier


ROOT = Path(__file__).resolve().parents[1]
ORG_ID = "00D000000000001AAA"
SANDBOX_HOST = "acme--dev.sandbox.my.salesforce.com"
SCRATCH_HOST = "mpsadev.scratch.my.salesforce.com"
DEV_EDITION_HOST = "orgfarm-x-dev-ed.develop.my.salesforce.com"


class SalesforceReadinessTests(unittest.TestCase):
    @staticmethod
    def display(host: str, org_id: str = ORG_ID) -> SimpleNamespace:
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "status": 0,
                    "result": {"instanceUrl": f"https://{host}", "id": org_id},
                }
            ),
            stderr="",
        )

    def verify(self, runner: Mock, **kwargs):
        with patch.object(verifier.shutil, "which", return_value="/usr/bin/sf"):
            return verifier.check_non_production_org("dev-sbx", runner=runner, **kwargs)

    def test_production_host_is_rejected_after_one_org_display_call(self) -> None:
        runner = Mock(return_value=self.display("acme.my.salesforce.com"))
        ok, _ = self.verify(
            runner,
            expected_host=SANDBOX_HOST,
            expected_org_id=ORG_ID,
        )
        self.assertFalse(ok)
        self.assertEqual(runner.call_count, 1)

    def test_pinned_host_and_org_id_pass_without_organization_query(self) -> None:
        runner = Mock(return_value=self.display(SANDBOX_HOST))
        ok, reason = self.verify(
            runner,
            expected_host=SANDBOX_HOST,
            expected_org_id=ORG_ID,
        )
        self.assertTrue(ok)
        self.assertEqual(
            reason,
            f"configured non-production host and organization matched for '{SANDBOX_HOST}'",
        )
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(runner.call_args.args[0][1:3], ["org", "display"])

    def test_org_display_gets_the_full_sixty_second_budget(self) -> None:
        runner = Mock(return_value=self.display(SANDBOX_HOST))
        ok, _ = self.verify(
            runner,
            expected_host=SANDBOX_HOST,
            expected_org_id=ORG_ID,
        )
        self.assertTrue(ok)
        self.assertEqual(runner.call_args.kwargs["timeout"], 60)

    def test_dynamic_lane_accepts_sandbox_scratch_and_dev_edition(self) -> None:
        for host in (SANDBOX_HOST, SCRATCH_HOST, DEV_EDITION_HOST):
            with self.subTest(host=host):
                runner = Mock(return_value=self.display(host))
                ok, reason = self.verify(runner)
                self.assertTrue(ok, reason)
                self.assertEqual(runner.call_count, 1)

    def test_denied_organization_id_is_refused_in_both_lanes(self) -> None:
        denied = frozenset({ORG_ID[:15]})
        for pins in ({}, {"expected_host": SANDBOX_HOST, "expected_org_id": ORG_ID}):
            with self.subTest(pinned=bool(pins)):
                runner = Mock(return_value=self.display(SANDBOX_HOST))
                ok, reason = self.verify(runner, denied_org_ids=denied, **pins)
                self.assertFalse(ok)
                self.assertIn("deniedOrganizationIds", reason)

    def test_pinned_host_and_org_id_must_match_org_display(self) -> None:
        cases = (
            self.display(SCRATCH_HOST),
            self.display(SANDBOX_HOST, "00D000000000002AAA"),
        )
        for result in cases:
            with self.subTest(result=result.stdout):
                ok, _ = self.verify(
                    Mock(return_value=result),
                    expected_host=SANDBOX_HOST,
                    expected_org_id=ORG_ID,
                )
                self.assertFalse(ok)

    def test_malformed_or_failed_org_display_is_rejected(self) -> None:
        for result in (
            SimpleNamespace(returncode=1, stdout="{}", stderr="failed"),
            SimpleNamespace(returncode=0, stdout="not json", stderr=""),
            SimpleNamespace(returncode=0, stdout="x" * 1_000_001, stderr=""),
        ):
            with self.subTest(returncode=result.returncode, size=len(result.stdout)):
                ok, _ = self.verify(Mock(return_value=result))
                self.assertFalse(ok)


class ContractConsistencyTests(unittest.TestCase):
    def test_negative_completeness_fixtures_are_rejected(self) -> None:
        cases = json.loads(
            (ROOT / "evals/fixtures/invalid-contract-states.json").read_text(
                encoding="utf-8"
            )
        )["cases"]
        for case in cases:
            with self.subTest(case=case["id"]):
                schema = json.loads(
                    (ROOT / "schemas" / case["schema"]).read_text(encoding="utf-8")
                )
                instance = deepcopy(
                    json.loads(
                        (ROOT / "evals/fixtures" / case["baseFixture"]).read_text(
                            encoding="utf-8"
                        )
                    )
                )
                for dotted, value in case["patch"].items():
                    target = instance
                    parts = dotted.split(".")
                    for part in parts[:-1]:
                        target = target[part]
                    target[parts[-1]] = value
                self.assertTrue(list(Draft202012Validator(schema).iter_errors(instance)))


if __name__ == "__main__":
    unittest.main()
