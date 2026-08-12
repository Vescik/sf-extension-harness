"""Integration Field Impact Check — registry, projection, diff, rendering, and CLI.

The advisory/enforced boundary is the contract under test: a registered-field match must
never fail the run, while a broken registry, bad invocation, or unreadable diff must.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import check_integration_field_impact as impact

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER = REPO_ROOT / "scripts/check_integration_field_impact.py"

FIELD_PATH = "force-app/main/default/objects/{obj}/fields/{field}.field-meta.xml"

VALID_REGISTRY = {
    "version": 1,
    "integrations": {
        "erp-customer-sync": {
            "name": "ERP Customer Sync",
            "owner": "integration-team",
            "fields": ["Account.External_Id__c", "Contact.Customer_Number__c"],
        },
        "billing-bridge": {
            "name": "Billing Bridge",
            "owner": "finance-platform",
            "fields": ["Account.External_Id__c"],
        },
    },
}


def registry_file(directory: Path, data) -> Path:
    import yaml

    path = directory / "integration-fields.yml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


class RegistryValidationTests(unittest.TestCase):
    def validated(self, data):
        return impact.validate_registry(data, "test-registry")

    def test_valid_minimal_registry(self) -> None:
        result = self.validated({"version": 1, "integrations": {}})
        self.assertEqual({}, result)

    def test_multiple_integrations_and_shared_field(self) -> None:
        integrations = self.validated(VALID_REGISTRY)
        index = impact.build_field_index(integrations)
        self.assertEqual(
            ["billing-bridge", "erp-customer-sync"],
            [key for key, _name, _owner in index["Account.External_Id__c"]],
        )

    def test_blank_name_and_owner_rejected(self) -> None:
        for attr in ("name", "owner"):
            data = {
                "version": 1,
                "integrations": {
                    "x-sync": {"name": "X", "owner": "team", "fields": ["A.B"], attr: "  "}
                },
            }
            with self.assertRaisesRegex(impact.CheckError, attr):
                self.validated(data)

    def test_duplicate_field_within_one_integration_rejected(self) -> None:
        data = {
            "version": 1,
            "integrations": {
                "x-sync": {"name": "X", "owner": "team", "fields": ["A.B", "A.B"]}
            },
        }
        with self.assertRaisesRegex(impact.CheckError, "twice"):
            self.validated(data)

    def test_invalid_types_rejected(self) -> None:
        for data in (
            ["not", "a", "map"],
            {"version": 1, "integrations": ["not-a-map"]},
            {"version": 1, "integrations": {"x-sync": ["not-a-map"]}},
            {"version": 1, "integrations": {"x-sync": {"name": "X", "owner": "t", "fields": "A.B"}}},
            {"version": 1, "integrations": {"x-sync": {"name": "X", "owner": "t", "fields": []}}},
            {"version": 1, "integrations": {"x-sync": {"name": "X", "owner": "t", "fields": [7]}}},
        ):
            with self.assertRaises(impact.CheckError):
                self.validated(data)

    def test_unsupported_version_rejected(self) -> None:
        for version in (0, 2, "1", None):
            with self.assertRaisesRegex(impact.CheckError, "version"):
                self.validated({"version": version, "integrations": {}})

    def test_missing_keys_rejected(self) -> None:
        with self.assertRaises(impact.CheckError):
            self.validated({"version": 1})

    def test_malformed_key_and_separator_rules(self) -> None:
        for key in ("Bad_Key", "UPPER", "two--dashes", "-lead", "trail-"):
            with self.assertRaisesRegex(impact.CheckError, "kebab-case"):
                self.validated(
                    {"version": 1, "integrations": {key: {"name": "X", "owner": "t", "fields": ["A.B"]}}}
                )
        for field in ("NoSeparator", "Too.Many.Dots", "A/B.C", "A\\B.C", ".B", "A."):
            with self.assertRaises(impact.CheckError):
                self.validated(
                    {"version": 1, "integrations": {"x-sync": {"name": "X", "owner": "t", "fields": [field]}}}
                )

    def test_identity_styles_remain_representable(self) -> None:
        fields = [
            "Account.Name",
            "Invoice__c.Total__c",
            "vendorns__Order__c.vendorns__Status__c",
            "Shipment_Event__e.Payload__c",
            "Sync_Rule__mdt.Endpoint_Path__c",
            "Archive_Row__b.Source_Key__c",
        ]
        data = {
            "version": 1,
            "integrations": {"wide-sync": {"name": "W", "owner": "t", "fields": fields}},
        }
        self.assertEqual(fields, self.validated(data)["wide-sync"]["fields"])

    def test_malformed_yaml_and_unreadable_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.yml"
            bad.write_text("version: 1\nintegrations: {unclosed", encoding="utf-8")
            with self.assertRaisesRegex(impact.CheckError, "YAML"):
                impact.load_registry(bad)
            with self.assertRaisesRegex(impact.CheckError, "readable"):
                impact.load_registry(Path(tmp) / "absent.yml")


class PathProjectionTests(unittest.TestCase):
    def test_exact_field_paths_project(self) -> None:
        cases = {
            FIELD_PATH.format(obj="Invoice__c", field="Total__c"): "Invoice__c.Total__c",
            FIELD_PATH.format(obj="Account", field="Name"): "Account.Name",
            FIELD_PATH.format(
                obj="vendorns__Order__c", field="vendorns__Status__c"
            ): "vendorns__Order__c.vendorns__Status__c",
        }
        for path, identity in cases.items():
            self.assertEqual(identity, impact.field_identity(path))

    def test_non_field_paths_ignored(self) -> None:
        for path in (
            "force-app/main/default/objects/Account/Account.object-meta.xml",
            "force-app/main/default/objects/Account/listViews/All.listView-meta.xml",
            "force-app/main/default/classes/OrderService.cls",
            "src/main/default/objects/Account/fields/Name.field-meta.xml",
            "force-app/main/default/objects/Account/fields/Name.field-meta.xml.orig",
            "force-app/main/default/objects/Account/fields/Name.field-meta.yml",
            "force-app/main/default/objects/../fields/Name.field-meta.xml",
            "force-app/main/default/objects/Account/fields/extra/Name.field-meta.xml",
        ):
            self.assertIsNone(impact.field_identity(path), path)

    def test_spaces_outside_api_segments_do_not_corrupt(self) -> None:
        events, ignored = impact.field_events(
            [("M", "docs/some file with spaces.md", "docs/some file with spaces.md")]
        )
        self.assertEqual(([], 1), (events, ignored))


class DiffStatusTests(unittest.TestCase):
    REGISTERED = FIELD_PATH.format(obj="Account", field="External_Id__c")
    OTHER = FIELD_PATH.format(obj="Case", field="Origin_Code__c")

    def test_add_modify_delete(self) -> None:
        events, ignored = impact.field_events(
            [
                ("A", None, self.REGISTERED),
                ("M", self.OTHER, self.OTHER),
                ("D", self.REGISTERED, None),
            ]
        )
        self.assertEqual(
            [
                ("A", "Account.External_Id__c"),
                ("M", "Case.Origin_Code__c"),
                ("D", "Account.External_Id__c"),
            ],
            events,
        )
        self.assertEqual(0, ignored)

    def test_rename_reports_both_identities_from_paths_alone(self) -> None:
        events, _ = impact.field_events([("R", self.REGISTERED, self.OTHER)])
        self.assertEqual(
            [
                ("D (renamed away)", "Account.External_Id__c"),
                ("A (renamed in)", "Case.Origin_Code__c"),
            ],
            events,
        )

    def test_rename_across_the_field_boundary(self) -> None:
        events, ignored = impact.field_events([("R", self.REGISTERED, "docs/x.md")])
        self.assertEqual([("D (renamed away)", "Account.External_Id__c")], events)
        self.assertEqual(0, ignored)
        events, ignored = impact.field_events([("R", "docs/x.md", "docs/y.md")])
        self.assertEqual(([], 1), (events, ignored))

    def test_copy_reports_destination(self) -> None:
        events, _ = impact.field_events([("C", self.OTHER, self.REGISTERED)])
        self.assertEqual([("A (copied in)", "Account.External_Id__c")], events)

    def test_typechange_is_treated_as_modification(self) -> None:
        events, _ = impact.field_events([("T", self.REGISTERED, self.REGISTERED)])
        self.assertEqual([("M", "Account.External_Id__c")], events)

    def test_unknown_status_fails_explicitly(self) -> None:
        with self.assertRaisesRegex(impact.CheckError, "unsupported"):
            impact.parse_name_status("Q\0some/path\0")

    def test_truncated_diff_fails_explicitly(self) -> None:
        for raw in ("M\0", "R100\0only/one\0"):
            with self.assertRaisesRegex(impact.CheckError, "truncated"):
                impact.parse_name_status(raw)

    def test_name_status_parsing_with_scores(self) -> None:
        raw = "R100\0old/path\0new/path\0C75\0src/path\0dst/path\0A\0added/file\0"
        self.assertEqual(
            [
                ("R", "old/path", "new/path"),
                ("C", "src/path", "dst/path"),
                ("A", None, "added/file"),
            ],
            impact.parse_name_status(raw),
        )


class RenderingTests(unittest.TestCase):
    def render(self, integrations, events):
        index = impact.build_field_index(integrations)
        rows = []
        for change, identity in events:
            for key, name, owner in index.get(identity, ()):
                rows.append((change, identity, key, name, owner))
        rows.sort(key=lambda row: (row[1], row[2], row[0]))
        if not integrations:
            state = impact.STATE_EMPTY
        elif not events:
            state = impact.STATE_NO_FIELDS
        elif rows:
            state = impact.STATE_IMPACT
        else:
            state = impact.STATE_NO_IMPACT
        return state, impact.render_report(state, "a" * 40, "b" * 40, events, rows, 0)

    def test_empty_registry_reports_not_assessed(self) -> None:
        state, report = self.render({}, [("M", "Account.External_Id__c")])
        self.assertEqual(impact.STATE_EMPTY, state)
        self.assertEqual(impact.STATE_EMPTY, report.splitlines()[0])
        self.assertIn("not assessed", report)
        self.assertNotIn(impact.STATE_NO_IMPACT, report)

    def test_no_fields_changed(self) -> None:
        state, report = self.render(VALID_REGISTRY["integrations"], [])
        self.assertEqual(impact.STATE_NO_FIELDS, state)
        self.assertTrue(report.startswith(impact.STATE_NO_FIELDS))

    def test_changed_fields_without_registry_match(self) -> None:
        state, report = self.render(
            VALID_REGISTRY["integrations"], [("M", "Case.Origin_Code__c")]
        )
        self.assertEqual(impact.STATE_NO_IMPACT, state)
        self.assertIn("no changed field is registered", report)

    def test_single_match_and_multi_integration_field(self) -> None:
        state, report = self.render(
            VALID_REGISTRY["integrations"], [("M", "Account.External_Id__c")]
        )
        self.assertEqual(impact.STATE_IMPACT, state)
        lines = [line for line in report.splitlines() if line.startswith("| M ")]
        self.assertEqual(2, len(lines))
        self.assertLess(report.index("Billing Bridge"), report.index("ERP Customer Sync"))
        self.assertIn("integration-team", report)
        self.assertIn("not proof of a breaking change", report)

    def test_deterministic_ordering_by_field_then_key(self) -> None:
        events = [("M", "Contact.Customer_Number__c"), ("M", "Account.External_Id__c")]
        _, report = self.render(VALID_REGISTRY["integrations"], events)
        rows = [line for line in report.splitlines() if line.startswith("| M ")]
        self.assertEqual(3, len(rows))
        self.assertIn("Account.External\\_Id\\_\\_c", rows[0])
        self.assertIn("Contact.Customer\\_Number\\_\\_c", rows[2])

    def test_markdown_escaping_of_registry_values(self) -> None:
        integrations = {
            "odd-sync": {
                "name": "Pipe | `Tick` <b>",
                "owner": "line\nbreak",
                "fields": ["Account.External_Id__c"],
            }
        }
        _, report = self.render(integrations, [("M", "Account.External_Id__c")])
        self.assertIn(r"Pipe \| \`Tick\` \<b\>", report)
        self.assertIn("line break", report)

    def test_no_absolute_local_paths_leak(self) -> None:
        _, report = self.render(VALID_REGISTRY["integrations"], [("M", "Account.External_Id__c")])
        self.assertNotIn(str(REPO_ROOT), report)
        self.assertNotIn("/Users/", report)

    def test_error_report_carries_state_and_detail(self) -> None:
        report = impact.render_report(
            impact.STATE_ERROR, "a" * 40, "b" * 40, [], [], 0, detail="registry exploded"
        )
        self.assertTrue(report.startswith(impact.STATE_ERROR))
        self.assertIn("registry exploded", report)


class GitFixture(unittest.TestCase):
    """Shared temporary-repository helpers; carries no tests itself."""

    def make_repo(self) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="impact-fixture-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        self.git(tmp, "init", "-q")
        return tmp

    @staticmethod
    def git(repo: Path, *args: str) -> str:
        completed = subprocess.run(
            ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=True,
        )
        return completed.stdout.strip()

    def commit_all(self, repo: Path, message: str) -> str:
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", message)
        return self.git(repo, "rev-parse", "HEAD")

    def write(self, repo: Path, relative: str, content: str) -> None:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


class CliAndGitIntegrationTests(GitFixture):
    def field_file(self, repo: Path, obj: str, field: str, content: str = "<CustomField/>") -> str:
        relative = FIELD_PATH.format(obj=obj, field=field)
        self.write(repo, relative, content)
        return relative

    def run_cli(self, repo: Path, registry: Path, base: str, head: str):
        report_path = repo / "impact-report.md"
        completed = subprocess.run(
            [
                sys.executable,
                str(CHECKER),
                "--registry",
                str(registry),
                "--base",
                base,
                "--head",
                head,
                "--markdown-output",
                str(report_path),
            ],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
        )
        report = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
        return completed, report

    def test_match_exits_zero_and_reports_impact(self) -> None:
        repo = self.make_repo()
        self.field_file(repo, "Account", "External_Id__c")
        base = self.commit_all(repo, "base")
        self.field_file(repo, "Account", "External_Id__c", "<CustomField>changed</CustomField>")
        head = self.commit_all(repo, "head")
        registry = registry_file(repo, VALID_REGISTRY)
        completed, report = self.run_cli(repo, registry, base, head)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertTrue(report.startswith(impact.STATE_IMPACT))
        self.assertIn("ERP Customer Sync", report)

    def test_empty_registry_reports_registry_empty_not_no_impact(self) -> None:
        repo = self.make_repo()
        self.field_file(repo, "Account", "External_Id__c")
        base = self.commit_all(repo, "base")
        self.field_file(repo, "Account", "External_Id__c", "<CustomField>v2</CustomField>")
        head = self.commit_all(repo, "head")
        registry = registry_file(repo, {"version": 1, "integrations": {}})
        completed, report = self.run_cli(repo, registry, base, head)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertTrue(report.startswith(impact.STATE_EMPTY))
        self.assertNotIn(impact.STATE_NO_IMPACT, report)

    def test_bootstrap_repository_registry_is_empty_and_valid(self) -> None:
        integrations = impact.load_registry(REPO_ROOT / "config/integration-fields.yml")
        self.assertEqual({}, integrations)

    def test_deleted_field_reported_without_reading_the_tree(self) -> None:
        repo = self.make_repo()
        self.field_file(repo, "Account", "External_Id__c")
        self.write(repo, "keep.txt", "keep")
        base = self.commit_all(repo, "base")
        (repo / FIELD_PATH.format(obj="Account", field="External_Id__c")).unlink()
        head = self.commit_all(repo, "delete")
        registry = registry_file(repo, VALID_REGISTRY)
        completed, report = self.run_cli(repo, registry, base, head)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertTrue(report.startswith(impact.STATE_IMPACT))
        self.assertIn("| D |", report)

    def test_renamed_field_reports_old_and_new_identity(self) -> None:
        repo = self.make_repo()
        relative = self.field_file(repo, "Account", "External_Id__c", "<CustomField>stable</CustomField>")
        base = self.commit_all(repo, "base")
        target = FIELD_PATH.format(obj="Account", field="Legacy_External_Id__c")
        self.git(repo, "mv", relative, target)
        head = self.commit_all(repo, "rename")
        registry = registry_file(repo, VALID_REGISTRY)
        completed, report = self.run_cli(repo, registry, base, head)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertTrue(report.startswith(impact.STATE_IMPACT))
        self.assertIn("renamed away", report)

    def test_invalid_registry_fails_the_run_with_check_error(self) -> None:
        repo = self.make_repo()
        self.field_file(repo, "Account", "External_Id__c")
        base = self.commit_all(repo, "base")
        self.field_file(repo, "Account", "External_Id__c", "<CustomField>v2</CustomField>")
        head = self.commit_all(repo, "head")
        registry = registry_file(repo, {"version": 99, "integrations": {}})
        completed, report = self.run_cli(repo, registry, base, head)
        self.assertEqual(2, completed.returncode)
        self.assertTrue(report.startswith(impact.STATE_ERROR))

    def test_unusable_shas_fail_the_run(self) -> None:
        repo = self.make_repo()
        self.write(repo, "a.txt", "a")
        head = self.commit_all(repo, "only")
        registry = registry_file(repo, VALID_REGISTRY)
        completed, _ = self.run_cli(repo, registry, "not-a-sha", head)
        self.assertEqual(2, completed.returncode)
        completed, _ = self.run_cli(repo, registry, "f" * 40, head)
        self.assertEqual(2, completed.returncode)

    def test_no_field_metadata_changed(self) -> None:
        repo = self.make_repo()
        self.write(repo, "docs/a.md", "one")
        base = self.commit_all(repo, "base")
        self.write(repo, "docs/a.md", "two")
        head = self.commit_all(repo, "head")
        registry = registry_file(repo, VALID_REGISTRY)
        completed, report = self.run_cli(repo, registry, base, head)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertTrue(report.startswith(impact.STATE_NO_FIELDS))


if __name__ == "__main__":
    unittest.main()
