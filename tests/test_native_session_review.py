"""Independent native-session target and private lifecycle-boundary regressions."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from scripts import salesforce_operation_session as native


class NativeSessionReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "workspace"
        self.home = Path(temporary.name) / "home"
        (self.root / "config").mkdir(parents=True)
        (self.home / ".sf").mkdir(parents=True)
        (self.home / ".sfdx").mkdir()
        self.rows = [
            {"username": "child@example.test", "id": "00D000000000101", "host": "review--dev.sandbox.my.salesforce.com", "aliases": ["child"]},
            {"username": "hub@example.test", "id": "00D000000000102", "host": "review.develop.my.salesforce.com", "aliases": ["hub"]},
        ]
        config = {"salesforce": {"orgs": [{"alias": row["aliases"][0], "environment": "dev",
                   "expectedOrganizationId": row["id"], "expectedInstanceHost": row["host"]} for row in self.rows]}}
        (self.root / "config/harness.local.json").write_text(json.dumps(config))
        self.ask = Mock(side_effect=AssertionError("No dialog expected for these configured targets"))
        self.inventory = Mock(return_value=self.rows)

    def session(self, env=None):
        return native.OperationSession(self.root, self.ask, home=self.home, env=env or {}, inventory=self.inventory)

    def test_native_lifecycle_deletion_stops_before_identity_reads_or_dialogs(self):
        paths = [("org", "delete", "sandbox"), ("org", "delete", "scratch")]
        paths += [alias for alias, canonical in native.policy.COMMAND_ALIASES.items()
                  if canonical in paths]
        for command in paths:
            with self.subTest(command=command), self.assertRaisesRegex(native.SessionError, "controlling org relation"):
                self.session().prepare({"arguments": [*command, "-o", "child"]})
        self.inventory.assert_not_called()
        self.ask.assert_not_called()

    def test_explicit_child_and_hub_spellings_are_both_rewritten(self):
        execution = self.session().prepare({"arguments": ["org", "create", "scratch",
            "--target-org=child", "--target-dev-hub", "hub", "--definition-file", "config/scratch.json"]})["execution"]
        self.assertIn("--target-org=child@example.test", execution["arguments"])
        self.assertEqual(execution["arguments"][execution["arguments"].index("--target-dev-hub") + 1], "hub@example.test")
        self.assertEqual({target["username"] for target in execution["targets"]}, {"child@example.test", "hub@example.test"})

    def test_supplied_home_modern_and_legacy_defaults_are_pinned(self):
        for folder, filename, key in ((".sf", "config.json", "target-org"),
                                      (".sfdx", "sfdx-config.json", "defaultusername")):
            path = self.home / folder / filename
            path.write_text(json.dumps({key: "child"}))
            try:
                execution = self.session().prepare({"arguments": ["org", "display"]})["execution"]
                self.assertEqual(execution["arguments"][-2:], ["--target-org", "child@example.test"])
            finally:
                path.unlink()

    def test_home_dev_hub_default_is_explicit_even_with_other_org_default(self):
        (self.home / ".sf/config.json").write_text(json.dumps({"target-org": "child", "target-dev-hub": "hub"}))
        execution = self.session().prepare({"arguments": ["org", "create", "scratch",
                                           "--definition-file", "config/scratch.json"]})["execution"]
        self.assertEqual(execution["arguments"][-2:], ["--target-dev-hub", "hub@example.test"])
        self.assertEqual([t["username"] for t in execution["targets"]], ["hub@example.test"])


if __name__ == "__main__":
    unittest.main()
