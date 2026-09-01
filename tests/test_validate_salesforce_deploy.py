"""Deterministic tests for the guarded check-only deploy validation executor.

Everything runs against mocked CLI/config/filesystem fixtures: no test contacts a live
org or depends on the developer's current Salesforce authentication. The tests pin the
Phase 2 safety intent: the constructed child command is always a check-only async
dry-run against the proven project-local development org, forbidden flags cannot be
constructed from any input, and transport problems are never reported as deploy results.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts import validate_salesforce_deploy as vsd
from scripts import verify_salesforce_org as org_proof


DEV_ALIAS = "devsb"
SANDBOX_HOST = "acme--dev.sandbox.my.salesforce.com"
ORG_ID = "00D000000000001EAA"
JOB_ID = "0Af000000000001AAA"
FORBIDDEN_CHILD_FLAGS = (
    "--wait",
    "--use-most-recent",
    "--pre-destructive-changes",
    "--post-destructive-changes",
    "--purge-on-delete",
    "--ignore-errors",
    "--ignore-warnings",
    "--ignore-conflicts",
    "--metadata-dir",
    "--flags-dir",
)


def completed(stdout: str, returncode: int = 0) -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


def config_get_response(alias: str = DEV_ALIAS, location: str = "Local") -> SimpleNamespace:
    return completed(
        json.dumps(
            {
                "status": 0,
                "result": [
                    {
                        "name": "target-org",
                        "key": "target-org",
                        "value": alias,
                        "location": location,
                        "success": True,
                    }
                ],
            }
        )
    )


def org_display_response() -> SimpleNamespace:
    return completed(
        json.dumps(
            {
                "status": 0,
                "result": {"instanceUrl": f"https://{SANDBOX_HOST}", "id": ORG_ID},
            }
        )
    )


def deploy_start_response(status: str = "Queued", job_id: str = JOB_ID) -> SimpleNamespace:
    return completed(json.dumps({"status": 0, "result": {"id": job_id, "status": status}}))


def deploy_report_response(status: str, result_extra: dict | None = None) -> SimpleNamespace:
    result = {"id": JOB_ID, "status": status}
    result.update(result_extra or {})
    return completed(json.dumps({"status": 0, "result": result}))


class RecordingRunner:
    """Routes sf argv shapes to canned responses and records every child command."""

    def __init__(self, overrides: dict[str, SimpleNamespace] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.overrides = overrides or {}

    def classify(self, argv: list[str]) -> str:
        tail = [part.lower() for part in argv[1:4]]
        if tail[:2] == ["config", "get"]:
            return "config-get"
        if tail[:2] == ["org", "display"]:
            return "org-display"
        if tail == ["project", "deploy", "start"]:
            return "deploy-start"
        if tail == ["project", "deploy", "report"]:
            return "deploy-report"
        return "unknown"

    def __call__(self, argv: list[str], **_: object) -> SimpleNamespace:
        self.calls.append(list(argv))
        kind = self.classify(argv)
        if kind in self.overrides:
            return self.overrides[kind]
        defaults = {
            "config-get": config_get_response(),
            "org-display": org_display_response(),
            "deploy-start": deploy_start_response(),
            "deploy-report": deploy_report_response("Succeeded"),
        }
        return defaults.get(kind, completed("{}", returncode=1))

    def child(self, kind: str) -> list[str] | None:
        for argv in self.calls:
            if self.classify(argv) == kind:
                return argv
        return None


class ExecutorFixture(unittest.TestCase):
    """Temp repo root + temp local config + patched CLI discovery."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="deploy-validate-test-")
        self.root = Path(self._tmp.name).resolve()
        (self.root / "force-app/main/default/classes").mkdir(parents=True)
        (self.root / "force-app/main/default/objects").mkdir(parents=True)
        (self.root / "manifest").mkdir()
        (self.root / "outside").mkdir()
        (self.root / "force-app/main/default/objects/Widget__c.object-meta.xml").write_text(
            "<CustomObject/>", encoding="utf-8"
        )
        (self.root / "manifest/package.xml").write_text(
            self.manifest_xml(["CustomObject"]), encoding="utf-8"
        )
        self.config_path = self.root / "harness.local.json"
        self.write_config()
        self._cwd = os.getcwd()
        # LIFO cleanups: the temp dir must be removed LAST, after the cwd has left it —
        # Windows cannot rmdir the current working directory (WinError 32).
        self.addCleanup(self._tmp.cleanup)
        os.chdir(self.root)
        self.addCleanup(os.chdir, self._cwd)
        patches = [
            mock.patch.object(vsd, "REPO_ROOT", self.root),
            mock.patch.object(org_proof, "CONFIG_PATH", self.config_path),
            mock.patch.object(vsd.shutil, "which", return_value="/usr/local/bin/sf"),
            mock.patch.object(org_proof.shutil, "which", return_value="/usr/local/bin/sf"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    @staticmethod
    def manifest_xml(type_names: list[str]) -> str:
        types = "".join(
            "<types><members>*</members><name>{}</name></types>".format(name)
            for name in type_names
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Package xmlns="http://soap.sforce.com/2006/04/metadata">'
            f"{types}<version>67.0</version></Package>"
        )

    def write_config(self, orgs: list[dict] | None = None, denied: list[str] | None = None) -> None:
        payload = {
            "salesforce": {
                "orgs": orgs
                if orgs is not None
                else [{"alias": DEV_ALIAS, "environment": "development"}],
                "review": {"deniedOrganizationIds": denied or []},
            }
        }
        self.config_path.write_text(json.dumps(payload), encoding="utf-8")

    def add_apex_class(self) -> None:
        (self.root / "force-app/main/default/classes/WidgetService.cls").write_text(
            "public class WidgetService {}", encoding="utf-8"
        )

    def start(self, argv: list[str], runner: RecordingRunner) -> tuple[int, dict]:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = vsd.main(argv, runner=runner)
        return code, json.loads(buffer.getvalue())


class TestCommandGrammar(ExecutorFixture):
    def test_duplicate_singleton_flags_fail_before_any_salesforce_call(self) -> None:
        runner = RecordingRunner()
        for argv in (
            ["start", "--manifest", "manifest/package.xml", "--manifest", "manifest/package.xml"],
            ["status", "--job-id", JOB_ID, "--job-id", JOB_ID, "--org", DEV_ALIAS],
            ["status", "--job-id", JOB_ID, "--org", DEV_ALIAS, "--org", DEV_ALIAS],
        ):
            with self.subTest(argv=argv):
                code, envelope = self.start(argv, runner)
                self.assertEqual(envelope["state"], "ERROR")
                self.assertEqual(code, 2)
        self.assertEqual(runner.calls, [])

    def test_unknown_flags_and_positional_extras_fail_closed(self) -> None:
        runner = RecordingRunner()
        for argv in (
            ["start", "--source-dir", "force-app", "--ignore-errors"],
            ["start", "--source-dir", "force-app", "--wait", "10"],
            ["start", "force-app"],
            ["deploy", "start"],
            [],
        ):
            with self.subTest(argv=argv):
                code, envelope = self.start(argv, runner)
                self.assertEqual(envelope["state"], "ERROR")
                self.assertEqual(code, 2)
        self.assertEqual(runner.calls, [])

    def test_mixed_and_empty_scope_forms_are_rejected(self) -> None:
        runner = RecordingRunner()
        for argv in (
            ["start"],
            ["start", "--source-dir", "force-app", "--manifest", "manifest/package.xml"],
        ):
            with self.subTest(argv=argv):
                _, envelope = self.start(argv, runner)
                self.assertEqual(envelope["state"], "ERROR")
        self.assertEqual(runner.calls, [])

    def test_invalid_test_names_are_rejected(self) -> None:
        runner = RecordingRunner()
        for bad in ("1Bad", "Bad-Name", "Bad Name", "x" * 300, "--tests"):
            with self.subTest(bad=bad):
                _, envelope = self.start(
                    ["start", "--source-dir", "force-app", "--test", bad], runner
                )
                self.assertEqual(envelope["state"], "ERROR")
        self.assertEqual(runner.calls, [])

    def test_invalid_job_ids_and_aliases_are_rejected(self) -> None:
        runner = RecordingRunner()
        for argv in (
            ["status", "--job-id", "not-a-job", "--org", DEV_ALIAS],
            ["status", "--job-id", "005000000000001AAA", "--org", DEV_ALIAS],
            ["status", "--job-id", JOB_ID, "--org", "bad alias!"],
        ):
            with self.subTest(argv=argv):
                _, envelope = self.start(argv, runner)
                self.assertEqual(envelope["state"], "ERROR")
        self.assertEqual(runner.calls, [])


class TestScopeContainment(ExecutorFixture):
    def test_traversal_absolute_and_outside_paths_fail_before_salesforce(self) -> None:
        runner = RecordingRunner()
        for raw in (
            "force-app/../outside",
            str(self.root / "force-app"),
            "outside",
            "force-app/does-not-exist",
            "~/force-app",
        ):
            with self.subTest(raw=raw):
                _, envelope = self.start(["start", "--source-dir", raw], runner)
                self.assertEqual(envelope["state"], "ERROR")
        self.assertEqual(runner.calls, [])

    def test_symlink_escape_is_denied(self) -> None:
        link = self.root / "force-app/link-out"
        try:
            link.symlink_to(self.root / "outside")
        except OSError:  # Windows without symlink privilege: containment still enforced
            self.skipTest("symlink creation is not permitted on this runner")
        runner = RecordingRunner()
        _, envelope = self.start(["start", "--source-dir", "force-app/link-out"], runner)
        self.assertEqual(envelope["state"], "ERROR")
        self.assertEqual(runner.calls, [])

    def test_manifest_must_be_contained_under_manifest(self) -> None:
        runner = RecordingRunner()
        for raw in ("force-app", "manifest/../outside/x.xml", "manifest/missing.xml"):
            with self.subTest(raw=raw):
                _, envelope = self.start(["start", "--manifest", raw], runner)
                self.assertEqual(envelope["state"], "ERROR")
        self.assertEqual(runner.calls, [])


class TestAdaptiveTestLevel(ExecutorFixture):
    def test_declarative_only_scope_derives_no_test_run(self) -> None:
        runner = RecordingRunner()
        _, envelope = self.start(["start", "--source-dir", "force-app"], runner)
        self.assertEqual(envelope["testLevel"], "NoTestRun")
        child = runner.child("deploy-start")
        self.assertIn("NoTestRun", child)

    def test_apex_with_explicit_tests_derives_run_specified_tests(self) -> None:
        self.add_apex_class()
        runner = RecordingRunner()
        _, envelope = self.start(
            ["start", "--source-dir", "force-app", "--test", "WidgetServiceTest"], runner
        )
        self.assertEqual(envelope["testLevel"], "RunSpecifiedTests")
        child = runner.child("deploy-start")
        self.assertIn("--tests", child)
        self.assertIn("WidgetServiceTest", child)

    def test_apex_without_tests_derives_run_local_tests_not_no_test_run(self) -> None:
        self.add_apex_class()
        runner = RecordingRunner()
        _, envelope = self.start(["start", "--source-dir", "force-app"], runner)
        self.assertEqual(envelope["testLevel"], "RunLocalTests")

    def test_manifest_apex_types_are_detected(self) -> None:
        (self.root / "manifest/apex.xml").write_text(
            self.manifest_xml(["ApexClass"]), encoding="utf-8"
        )
        runner = RecordingRunner()
        _, envelope = self.start(["start", "--manifest", "manifest/apex.xml"], runner)
        self.assertEqual(envelope["testLevel"], "RunLocalTests")


class TestStartSubmission(ExecutorFixture):
    def test_happy_path_returns_exact_job_and_guarded_status_command(self) -> None:
        runner = RecordingRunner()
        code, envelope = self.start(["start", "--source-dir", "force-app"], runner)
        self.assertEqual(code, 0)
        self.assertEqual(envelope["state"], "IN_PROGRESS")
        self.assertEqual(envelope["jobId"], JOB_ID)
        self.assertEqual(envelope["targetOrg"], DEV_ALIAS)
        self.assertEqual(envelope["scope"], {"form": "source-dir", "sourceDirs": ["force-app"]})
        self.assertEqual(
            envelope["statusCommand"],
            f"python scripts/validate_salesforce_deploy.py status --job-id {JOB_ID} --org {DEV_ALIAS}",
        )

    def test_child_command_is_always_a_check_only_async_dry_run(self) -> None:
        runner = RecordingRunner()
        self.start(["start", "--source-dir", "force-app"], runner)
        child = runner.child("deploy-start")
        self.assertIsNotNone(child)
        for required in ("--dry-run", "--async", "--json", "--target-org", DEV_ALIAS):
            self.assertIn(required, child)
        for forbidden in FORBIDDEN_CHILD_FLAGS:
            self.assertNotIn(forbidden, child)
        self.assertEqual(child.count("--source-dir"), 1)
        self.assertNotIn("--manifest", child)

    def test_configured_target_check_runs_before_submission(self) -> None:
        runner = RecordingRunner()
        self.start(["start", "--source-dir", "force-app"], runner)
        kinds = [runner.classify(argv) for argv in runner.calls]
        self.assertIn("org-display", kinds)
        self.assertNotIn("data-query", kinds)
        self.assertLess(kinds.index("org-display"), kinds.index("deploy-start"))

    def test_global_only_target_is_blocked(self) -> None:
        runner = RecordingRunner({"config-get": config_get_response(location="Global")})
        code, envelope = self.start(["start", "--source-dir", "force-app"], runner)
        self.assertEqual(envelope["state"], "BLOCKED")
        self.assertEqual(code, 2)
        self.assertIsNone(runner.child("deploy-start"))

    def test_unconfigured_alias_is_blocked_even_if_a_real_sandbox(self) -> None:
        self.write_config(orgs=[{"alias": "other", "environment": "development"}])
        runner = RecordingRunner()
        _, envelope = self.start(["start", "--source-dir", "force-app"], runner)
        self.assertEqual(envelope["state"], "BLOCKED")
        self.assertIn("not configured", envelope["reason"])
        self.assertIsNone(runner.child("deploy-start"))

    def test_qa_uat_production_entries_are_blocked_in_v1(self) -> None:
        for environment in ("qa", "uat", "production"):
            with self.subTest(environment=environment):
                self.write_config(orgs=[{"alias": DEV_ALIAS, "environment": environment}])
                runner = RecordingRunner()
                _, envelope = self.start(["start", "--source-dir", "force-app"], runner)
                self.assertEqual(envelope["state"], "BLOCKED")
                self.assertIsNone(runner.child("deploy-start"))

    def test_denied_organization_id_is_blocked(self) -> None:
        self.write_config(denied=[ORG_ID])
        runner = RecordingRunner()
        _, envelope = self.start(["start", "--source-dir", "force-app"], runner)
        self.assertEqual(envelope["state"], "BLOCKED")
        self.assertIn("denied", envelope["reason"])
        self.assertIsNone(runner.child("deploy-start"))

    def test_failed_configured_target_check_blocks_submission(self) -> None:
        runner = RecordingRunner({"org-display": completed("not json", returncode=1)})
        _, envelope = self.start(["start", "--source-dir", "force-app"], runner)
        self.assertEqual(envelope["state"], "BLOCKED")
        self.assertIsNone(runner.child("deploy-start"))

    def test_malformed_submission_response_is_error_with_no_invented_job_id(self) -> None:
        runner = RecordingRunner({"deploy-start": completed("{ nope")})
        code, envelope = self.start(["start", "--source-dir", "force-app"], runner)
        self.assertEqual(envelope["state"], "ERROR")
        self.assertNotIn("jobId", envelope)
        self.assertEqual(code, 2)

    def test_rejected_submission_without_job_id_is_error(self) -> None:
        runner = RecordingRunner(
            {"deploy-start": completed(json.dumps({"status": 1, "message": "bad request"}))}
        )
        _, envelope = self.start(["start", "--source-dir", "force-app"], runner)
        self.assertEqual(envelope["state"], "ERROR")
        self.assertNotIn("jobId", envelope)


class TestStatusReporting(ExecutorFixture):
    def status(self, runner: RecordingRunner) -> tuple[int, dict]:
        return self.start(["status", "--job-id", JOB_ID, "--org", DEV_ALIAS], runner)

    def test_report_command_uses_exact_job_and_never_waits_or_infers(self) -> None:
        runner = RecordingRunner()
        code, envelope = self.status(runner)
        self.assertEqual(code, 0)
        self.assertEqual(envelope["state"], "SUCCEEDED")
        child = runner.child("deploy-report")
        self.assertEqual(child[1:4], ["project", "deploy", "report"])
        self.assertIn(JOB_ID, child)
        for forbidden in ("--wait", "--use-most-recent", "resume"):
            self.assertNotIn(forbidden, child)

    def test_in_progress_stays_distinct_from_succeeded(self) -> None:
        runner = RecordingRunner({"deploy-report": deploy_report_response("InProgress")})
        code, envelope = self.status(runner)
        self.assertEqual(envelope["state"], "IN_PROGRESS")
        self.assertEqual(code, 0)
        self.assertNotIn("failures", envelope)

    def test_failed_report_is_normalized_bounded_and_keeps_totals(self) -> None:
        failures = [
            {
                "componentType": "CustomField",
                "fullName": f"Widget__c.Field_{index}__c",
                "problemType": "Error",
                "problem": "x" * 2000,
            }
            for index in range(25)
        ]
        runner = RecordingRunner(
            {
                "deploy-report": deploy_report_response(
                    "Failed",
                    {
                        "numberComponentErrors": 25,
                        "numberComponentsTotal": 30,
                        "details": {"componentFailures": failures},
                    },
                )
            }
        )
        code, envelope = self.status(runner)
        self.assertEqual(envelope["state"], "FAILED")
        self.assertEqual(code, 1)
        details = envelope["failures"]
        self.assertEqual(details["componentErrors"], 25)
        self.assertEqual(len(details["componentFailures"]), vsd.MAX_FAILURE_DETAILS)
        self.assertTrue(details["componentFailuresTruncated"])
        self.assertLessEqual(len(details["componentFailures"][0]["problem"]), vsd.MAX_PROBLEM_CHARS)

    def test_canceled_is_its_own_state(self) -> None:
        runner = RecordingRunner({"deploy-report": deploy_report_response("Canceled")})
        code, envelope = self.status(runner)
        self.assertEqual(envelope["state"], "CANCELED")
        self.assertEqual(code, 1)

    def test_transport_problems_are_incomplete_never_a_deploy_result(self) -> None:
        for override in (
            completed("{ nope"),
            completed("[]"),
            completed("x" * (vsd.MAX_CLI_OUTPUT_BYTES + 1)),
        ):
            with self.subTest(override=override.stdout[:10]):
                runner = RecordingRunner({"deploy-report": override})
                code, envelope = self.status(runner)
                self.assertEqual(envelope["state"], "INCOMPLETE")
                self.assertEqual(code, 2)

    def test_report_for_a_different_job_id_is_incomplete(self) -> None:
        runner = RecordingRunner(
            {
                "deploy-report": completed(
                    json.dumps(
                        {"status": 0, "result": {"id": "0Af000000000999AAA", "status": "Succeeded"}}
                    )
                )
            }
        )
        _, envelope = self.status(runner)
        self.assertEqual(envelope["state"], "INCOMPLETE")

    def test_target_drift_between_start_and_status_is_blocked(self) -> None:
        self.write_config(
            orgs=[
                {"alias": DEV_ALIAS, "environment": "development"},
                {"alias": "otherdev", "environment": "development"},
            ]
        )
        runner = RecordingRunner({"config-get": config_get_response(alias="otherdev")})
        code, envelope = self.status(runner)
        self.assertEqual(envelope["state"], "BLOCKED")
        self.assertIn("target mismatch", envelope["reason"])
        self.assertIsNone(runner.child("deploy-report"))
        self.assertEqual(code, 2)

    def test_dry_run_success_is_labeled_validation_not_deployment(self) -> None:
        runner = RecordingRunner()
        _, envelope = self.status(runner)
        self.assertIn("not a deployment", envelope["capability"])


if __name__ == "__main__":
    unittest.main()
