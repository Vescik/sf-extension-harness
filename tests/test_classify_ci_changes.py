"""Diff-aware CI routing — path classification and the aggregate gate decision.

The fail-safe default is the contract under test: only force-app/** and work-items/**
escape the full harness; everything else — including paths the classifier has never
seen — must require it.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import classify_ci_changes as classify


def entries(*paths: str):
    """Modification entries for plain path lists."""
    return [("M", path, path) for path in paths]


class ClassifyPathsTests(unittest.TestCase):
    def classify(self, diff_entries):
        return classify.classify_paths(diff_entries)

    def test_pure_force_app(self) -> None:
        result = self.classify(entries("force-app/main/default/classes/OrderService.cls"))
        self.assertTrue(result["salesforce_changed"])
        self.assertFalse(result["full_harness_required"])
        self.assertFalse(result["content_only"])

    def test_pure_force_app_field_counts_candidates(self) -> None:
        result = self.classify(
            entries(
                "force-app/main/default/objects/Invoice__c/fields/Total__c.field-meta.xml",
                "force-app/main/default/objects/Invoice__c/fields/Status__c.field-meta.xml",
            )
        )
        self.assertEqual(2, result["integration_field_candidates"])
        self.assertFalse(result["full_harness_required"])

    def test_pure_work_items_content(self) -> None:
        result = self.classify(
            entries("work-items/123-story/ado-context.md", "work-items/123-story/tests.md")
        )
        self.assertFalse(result["salesforce_changed"])
        self.assertFalse(result["full_harness_required"])
        self.assertTrue(result["content_only"])

    def test_force_app_plus_work_items_skips_full_harness(self) -> None:
        result = self.classify(
            entries(
                "force-app/main/default/classes/OrderService.cls",
                "work-items/123-story/tasks.md",
            )
        )
        self.assertTrue(result["salesforce_changed"])
        self.assertFalse(result["full_harness_required"])
        self.assertFalse(result["content_only"])

    def test_pure_control_plane(self) -> None:
        for path in ("README.md", "docs/x.md", "scripts/a.py", ".github/prompts/x.prompt.md", ".ai/knowledge/x.md"):
            result = self.classify(entries(path))
            self.assertFalse(result["salesforce_changed"], path)
            self.assertTrue(result["full_harness_required"], path)
            self.assertFalse(result["content_only"], path)

    def test_salesforce_plus_control_plane_runs_both(self) -> None:
        result = self.classify(
            entries("force-app/main/default/classes/OrderService.cls", "scripts/a.py")
        )
        self.assertTrue(result["salesforce_changed"])
        self.assertTrue(result["full_harness_required"])

    def test_salesforce_control_surfaces_run_both_lanes(self) -> None:
        for path in (
            "manifest/package.xml",
            "sfdx-project.json",
            "config/project-scratch-def.json",
            "tests/e2e/test_org_shape.py",
            "config/integration-fields.yml",
            "scripts/check_integration_field_impact.py",
            "tests/test_integration_field_impact.py",
        ):
            result = self.classify(entries(path))
            self.assertTrue(result["salesforce_changed"], path)
            self.assertTrue(result["full_harness_required"], path)

    def test_rename_crossing_work_items_boundary_requires_full_harness(self) -> None:
        result = self.classify([("R", "work-items/123-story/tasks.md", "scripts/sneaky.py")])
        self.assertTrue(result["full_harness_required"])
        self.assertFalse(result["content_only"])

    def test_rename_crossing_force_app_boundary_runs_both(self) -> None:
        result = self.classify([("R", "force-app/main/default/classes/A.cls", "unknown-root/A.cls")])
        self.assertTrue(result["salesforce_changed"])
        self.assertTrue(result["full_harness_required"])

    def test_unknown_new_root_defaults_to_full_harness(self) -> None:
        result = self.classify(entries("brand-new-toplevel/tool.cfg"))
        self.assertTrue(result["full_harness_required"])
        self.assertFalse(result["salesforce_changed"])

    def test_deletion_only_diff_classifies(self) -> None:
        result = self.classify([("D", "work-items/123-story/tasks.md", "work-items/123-story/tasks.md")])
        self.assertTrue(result["content_only"])
        self.assertFalse(result["full_harness_required"])

    def test_empty_diff_is_an_error_not_content_only(self) -> None:
        with self.assertRaisesRegex(classify.ClassificationError, "empty diff"):
            self.classify([])

    def test_large_path_list_is_not_truncated(self) -> None:
        many = entries(*[f"work-items/900-bulk/note-{index:04d}.md" for index in range(600)])
        result = self.classify(many)
        self.assertEqual(600, result["changed_path_count"])
        self.assertTrue(result["content_only"])

    def test_unknown_status_fails_explicitly(self) -> None:
        with self.assertRaisesRegex(classify.ClassificationError, "unsupported"):
            classify.parse_name_status("Z\0path\0")


class FailSafeAndOutputTests(unittest.TestCase):
    def test_all_zero_before_sha_fails_safe_to_full_harness(self) -> None:
        result = classify.fail_safe_result("zero sha")
        self.assertTrue(result["full_harness_required"])
        self.assertFalse(result["salesforce_changed"])
        self.assertFalse(result["content_only"])

    def test_push_with_zero_before_writes_fail_safe_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "github-output"
            code = classify.main(
                [
                    "classify",
                    "--event",
                    "push",
                    "--base",
                    "0" * 40,
                    "--head",
                    "b" * 40,
                    "--github-output",
                    str(output),
                ]
            )
            self.assertEqual(0, code)
            text = output.read_text(encoding="utf-8")
            self.assertIn("full_harness_required=true", text)
            self.assertIn("salesforce_changed=false", text)
            self.assertIn("content_only=false", text)

    def test_pull_request_with_bad_shas_is_a_hard_error(self) -> None:
        code = classify.main(
            ["classify", "--event", "pull_request", "--base", "nope", "--head", "b" * 40]
        )
        self.assertEqual(2, code)

    def test_push_with_undiffable_range_fails_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "github-output"
            # Valid-looking SHAs that exist in no repository: git diff fails, push falls back.
            code = classify.main(
                [
                    "classify",
                    "--event",
                    "push",
                    "--base",
                    "a" * 40,
                    "--head",
                    "b" * 40,
                    "--github-output",
                    str(output),
                ]
            )
            self.assertEqual(0, code)
            self.assertIn("full_harness_required=true", output.read_text(encoding="utf-8"))


class GateDecisionTests(unittest.TestCase):
    def decide(self, classify_result="success", sf=(False, "skipped"), fh=(False, "skipped")):
        ok, _messages = classify.gate_decision(classify_result, sf[0], sf[1], fh[0], fh[1])
        return ok

    def test_salesforce_required_success_full_harness_skipped(self) -> None:
        self.assertTrue(self.decide(sf=(True, "success"), fh=(False, "skipped")))

    def test_salesforce_required_failure(self) -> None:
        self.assertFalse(self.decide(sf=(True, "failure"), fh=(False, "skipped")))

    def test_full_harness_required_success_salesforce_skipped(self) -> None:
        self.assertTrue(self.decide(sf=(False, "skipped"), fh=(True, "success")))

    def test_both_required_success(self) -> None:
        self.assertTrue(self.decide(sf=(True, "success"), fh=(True, "success")))

    def test_both_required_any_bad_outcome_fails(self) -> None:
        for bad in ("failure", "cancelled", "skipped"):
            self.assertFalse(self.decide(sf=(True, "success"), fh=(True, bad)), bad)
            self.assertFalse(self.decide(sf=(True, bad), fh=(True, "success")), bad)

    def test_content_only_both_lanes_skipped_passes(self) -> None:
        self.assertTrue(self.decide(sf=(False, "skipped"), fh=(False, "skipped")))

    def test_required_lane_unexpectedly_skipped_fails(self) -> None:
        self.assertFalse(self.decide(fh=(True, "skipped")))

    def test_classifier_failure_fails_gate(self) -> None:
        for result in ("failure", "cancelled", "skipped"):
            self.assertFalse(self.decide(classify_result=result, sf=(True, "success"), fh=(True, "success")))

    def test_not_required_lane_that_ran_and_failed_fails_gate(self) -> None:
        self.assertFalse(self.decide(sf=(False, "failure"), fh=(True, "success")))

    def test_gate_cli_exit_codes(self) -> None:
        passing = classify.main(
            [
                "gate",
                "--classify-result",
                "success",
                "--salesforce-required",
                "true",
                "--salesforce-result",
                "success",
                "--full-harness-required",
                "false",
                "--full-harness-result",
                "skipped",
            ]
        )
        self.assertEqual(0, passing)
        failing = classify.main(
            [
                "gate",
                "--classify-result",
                "success",
                "--salesforce-required",
                "true",
                "--salesforce-result",
                "failure",
                "--full-harness-required",
                "false",
                "--full-harness-result",
                "skipped",
            ]
        )
        self.assertEqual(1, failing)


class GitBackedClassificationTests(unittest.TestCase):
    """Classification through a real git diff, including rename detection."""

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

    def test_rename_detected_with_both_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.git(repo, "init", "-q")
            source = repo / "work-items" / "123-story" / "tasks.md"
            source.parent.mkdir(parents=True)
            source.write_text("stable content for rename detection\n" * 10, encoding="utf-8")
            self.git(repo, "add", "-A")
            self.git(repo, "commit", "-q", "-m", "base")
            base = self.git(repo, "rev-parse", "HEAD")
            target = repo / "scripts"
            target.mkdir()
            self.git(repo, "mv", "work-items/123-story/tasks.md", "scripts/tasks.md")
            self.git(repo, "commit", "-q", "-m", "move")
            head = self.git(repo, "rev-parse", "HEAD")
            completed = subprocess.run(
                [
                    "git",
                    "diff",
                    "--name-status",
                    "-z",
                    "--find-renames",
                    "--no-color",
                    f"{base}...{head}",
                ],
                cwd=str(repo),
                capture_output=True,
                text=True,
                check=True,
            )
            parsed = classify.parse_name_status(completed.stdout)
            self.assertEqual(1, len(parsed))
            status, old_path, new_path = parsed[0]
            self.assertEqual(("R", "work-items/123-story/tasks.md", "scripts/tasks.md"), (status, old_path, new_path))
            result = classify.classify_paths(parsed)
            self.assertTrue(result["full_harness_required"])
            self.assertFalse(result["content_only"])


if __name__ == "__main__":
    unittest.main()
