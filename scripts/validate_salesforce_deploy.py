#!/usr/bin/env python3
"""Guarded check-only Salesforce deploy validation for the Developer role.

Two public shapes, nothing else:

    python scripts/validate_salesforce_deploy.py start \
        (--source-dir <force-app path> [--source-dir <path> ...] | --manifest <manifest path>) \
        [--test <ApexTestClass> ...]

    python scripts/validate_salesforce_deploy.py status --job-id <0Af...> --org <alias>

`start` resolves the PROJECT-LOCAL VS Code `target-org` (a global default is never
accepted), requires that alias to be configured `environment: development` in
config/harness.local.json, checks its configured non-production host and org-id walls through
scripts/verify_salesforce_org.py, validates one bounded scope form, derives an honest
test level, and submits exactly `sf project deploy start --dry-run --async ... --json`.
`status` re-proves the same target and reads exactly one `sf project deploy report
--job-id ... --json` with no `--wait`, no `--use-most-recent`, and no `deploy resume`.

This is NOT a deployment capability: the constructed child command always contains
`--dry-run`; destructive-change, ignore-error/warning/conflict, wait, metadata-dir, and
raw passthrough flags do not exist in this grammar and cannot be constructed from any
input. This legacy wrapper never starts a real deployment; the Developer's separate direct
``sf``/``sfdx`` path may do so only after fresh chat confirmation for the exact target and
scope. Transport problems (bad JSON, timeout, oversized output, missing CLI, configured-target drift)
are reported as BLOCKED/ERROR/INCOMPLETE — never as deployment success or failure.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any, Callable

try:
    from scripts import verify_salesforce_org as org_proof
except ImportError:  # direct invocation: `python scripts/validate_salesforce_deploy.py`
    import verify_salesforce_org as org_proof


REPO_ROOT = Path(__file__).resolve().parents[1]
# Metadata deploy request IDs are the 0Af key prefix, 15 or 18 characters.
DEPLOY_JOB_ID = re.compile(r"^0Af[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?$")
APEX_TEST_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,254}$")
MAX_TESTS = 50
# Bounded child output: a report larger than this is untrustworthy, never partially parsed.
MAX_CLI_OUTPUT_BYTES = 2_000_000
CLI_TIMEOUT_SECONDS = 120
MAX_FAILURE_DETAILS = 20
MAX_PROBLEM_CHARS = 500
APEX_SOURCE_SUFFIXES = frozenset({".cls", ".trigger"})
MANIFEST_APEX_TYPES = frozenset({"apexclass", "apextrigger"})

# start: 0 = submitted (IN_PROGRESS) or already SUCCEEDED; status: 0 = SUCCEEDED/IN_PROGRESS.
EXIT_BY_STATE = {
    "IN_PROGRESS": 0,
    "SUCCEEDED": 0,
    "FAILED": 1,
    "CANCELED": 1,
    "BLOCKED": 2,
    "ERROR": 2,
    "INCOMPLETE": 2,
}


def emit(envelope: dict[str, Any]) -> int:
    print(json.dumps(envelope, indent=2, sort_keys=True))
    return EXIT_BY_STATE.get(str(envelope.get("state")), 2)


def blocked(command: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {"command": command, "state": "BLOCKED", "reason": reason, **extra}


def error(command: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {"command": command, "state": "ERROR", "reason": reason, **extra}


def bounded_stdout(completed: Any) -> str | None:
    stdout = completed.stdout if isinstance(completed.stdout, str) else ""
    if len(stdout.encode("utf-8", errors="replace")) > MAX_CLI_OUTPUT_BYTES:
        return None
    return stdout


def resolve_project_local_target(runner: Callable[..., Any]) -> tuple[str | None, str]:
    """Return the exact project-local target-org alias, refusing global-only defaults."""

    executable = shutil.which("sf")
    if executable is None:
        return None, "Salesforce CLI is unavailable"
    try:
        completed = runner(
            [executable, "config", "get", "target-org", "--json"],
            text=True,
            capture_output=True,
            timeout=CLI_TIMEOUT_SECONDS,
            cwd=REPO_ROOT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None, "target-org resolution failed"
    stdout = bounded_stdout(completed)
    if completed.returncode != 0 or stdout is None:
        return None, "target-org resolution was rejected or oversized"
    try:
        rows = json.loads(stdout).get("result", [])
    except (json.JSONDecodeError, AttributeError):
        return None, "target-org resolution returned invalid JSON"
    local = [
        str(row.get("value"))
        for row in rows
        if isinstance(row, dict)
        and row.get("key") == "target-org"
        and str(row.get("location", "")).lower() == "local"
        and row.get("value")
    ]
    if len(local) != 1:
        return None, (
            "no single project-local target-org is selected; a global default is not "
            "accepted — select the development org for this project in VS Code first"
        )
    alias = local[0]
    if not org_proof.ALIAS.fullmatch(alias):
        return None, "project-local target-org value is not a valid alias"
    return alias, f"project-local target-org is '{alias}'"


def prove_development_org(alias: str, runner: Callable[..., Any]) -> tuple[bool, str]:
    """Fail closed unless alias is configured `development` and passes target walls.

    Reuses scripts/verify_salesforce_org.py — this module adds no
    second, weaker non-production detector.
    """

    if org_proof.load_config() is None:
        return False, "local harness configuration (config/harness.local.json) is missing"
    entry = org_proof.org_entry(alias)
    if not isinstance(entry, dict):
        return False, (
            f"alias '{alias}' is not configured in config/harness.local.json; "
            "unconfigured aliases are valid for governed reads but never for dry-run validation"
        )
    environment = str(entry.get("environment", "")).lower()
    if environment != "development":
        return False, (
            f"alias '{alias}' is configured as '{environment or 'unset'}'; dry-run "
            "validation targets only a configured 'development' org"
        )
    identity = org_proof.configured_identity(alias)
    if isinstance(identity, str):
        return False, identity
    denied = org_proof.denied_organization_ids()
    if identity is not None:
        return org_proof.check_non_production_org(
            alias,
            expected_host=identity[0],
            expected_org_id=identity[1],
            denied_org_ids=denied,
            runner=runner,
        )
    return org_proof.check_non_production_org(alias, denied_org_ids=denied, runner=runner)


def contained_repo_path(raw: str, prefix: str) -> tuple[str | None, str]:
    """Canonical repo-relative path contained under prefix, or (None, reason)."""

    if not raw or raw.startswith("~"):
        return None, f"path {raw!r} is not a repository-relative path"
    normalized = raw.replace("\\", "/")
    candidate = Path(normalized)
    if candidate.is_absolute() or re.match(r"^[A-Za-z]:", normalized):
        return None, f"path {raw!r} must be repository-relative, not absolute"
    resolved = (REPO_ROOT / candidate).resolve(strict=False)
    boundary = (REPO_ROOT / prefix).resolve()
    try:
        relative = resolved.relative_to(boundary)
    except ValueError:
        return None, f"path {raw!r} escapes {prefix}/ after normalization"
    if not resolved.exists():
        return None, f"path {raw!r} does not exist"
    return (Path(prefix) / relative).as_posix() if str(relative) != "." else prefix, "ok"


def validate_scope(
    source_dirs: list[str], manifest: str | None
) -> tuple[dict[str, Any] | None, str]:
    if source_dirs and manifest:
        return None, "supply either --source-dir or --manifest, never both"
    if not source_dirs and not manifest:
        return None, "an explicit bounded scope is required (--source-dir or --manifest)"
    if manifest is not None:
        contained, reason = contained_repo_path(manifest, "manifest")
        if contained is None:
            return None, reason
        if not contained.endswith(".xml"):
            return None, "manifest scope must be a package.xml-style file under manifest/"
        return {"form": "manifest", "manifest": contained}, "ok"
    seen: list[str] = []
    for raw in source_dirs:
        contained, reason = contained_repo_path(raw, "force-app")
        if contained is None:
            return None, reason
        if contained not in seen:
            seen.append(contained)
    return {"form": "source-dir", "sourceDirs": seen}, "ok"


def scope_contains_apex(scope: dict[str, Any]) -> tuple[bool | None, str]:
    if scope["form"] == "manifest":
        try:
            root = ElementTree.parse(REPO_ROOT / scope["manifest"]).getroot()
        except (OSError, ElementTree.ParseError) as exc:
            return None, f"manifest could not be parsed: {exc}"
        for types in root:
            if not types.tag.endswith("types"):
                continue
            for child in types:
                if child.tag.endswith("name") and (child.text or "").strip().lower() in MANIFEST_APEX_TYPES:
                    return True, "ok"
        return False, "ok"
    for source_dir in scope["sourceDirs"]:
        base = REPO_ROOT / source_dir
        candidates = base.rglob("*") if base.is_dir() else [base]
        for path in candidates:
            if path.suffix.lower() in APEX_SOURCE_SUFFIXES:
                return True, "ok"
    return False, "ok"


def derive_test_level(has_apex: bool, tests: list[str]) -> tuple[str, list[str]]:
    """Honest adaptive policy (plan D10): never silently weaker than the scope demands."""

    if tests:
        return "RunSpecifiedTests", tests
    if has_apex:
        return "RunLocalTests", []
    return "NoTestRun", []


def validated_tests(raw_tests: list[str]) -> tuple[list[str] | None, str]:
    if len(raw_tests) > MAX_TESTS:
        return None, f"at most {MAX_TESTS} Apex test classes may be supplied"
    tests: list[str] = []
    for name in raw_tests:
        if not APEX_TEST_NAME.fullmatch(name):
            return None, f"invalid Apex test class name: {name!r}"
        if name not in tests:
            tests.append(name)
    return tests, "ok"


def build_start_command(
    executable: str, alias: str, scope: dict[str, Any], test_level: str, tests: list[str]
) -> list[str]:
    command = [
        executable,
        "project",
        "deploy",
        "start",
        "--dry-run",
        "--async",
        "--target-org",
        alias,
        "--json",
        "--test-level",
        test_level,
    ]
    if scope["form"] == "manifest":
        command += ["--manifest", scope["manifest"]]
    else:
        for source_dir in scope["sourceDirs"]:
            command += ["--source-dir", source_dir]
    for name in tests:
        command += ["--tests", name]
    return command


def normalize_deploy_state(raw_status: Any) -> str:
    status = str(raw_status or "").strip().lower()
    if status == "succeeded":
        return "SUCCEEDED"
    if status in {"failed", "succeededpartial", "partiallysucceeded", "error"}:
        return "FAILED"
    if status in {"canceled", "cancelled", "canceling", "cancelling"}:
        return "CANCELED"
    if status in {"pending", "inprogress", "queued", ""}:
        return "IN_PROGRESS"
    return "INCOMPLETE"


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def truncate(text: Any) -> str:
    rendered = str(text or "")
    return rendered[:MAX_PROBLEM_CHARS]


def normalized_failures(result: dict[str, Any]) -> dict[str, Any]:
    """Bounded, sanitized failure details; totals survive even when lists are capped."""

    details = result.get("details") if isinstance(result.get("details"), dict) else {}
    component_failures = as_list(details.get("componentFailures"))
    run_test_result = (
        details.get("runTestResult") if isinstance(details.get("runTestResult"), dict) else {}
    )
    test_failures = as_list(run_test_result.get("failures"))
    components = [
        {
            "componentType": truncate(item.get("componentType")),
            "fullName": truncate(item.get("fullName")),
            "problemType": truncate(item.get("problemType")),
            "problem": truncate(item.get("problem")),
        }
        for item in component_failures[:MAX_FAILURE_DETAILS]
        if isinstance(item, dict)
    ]
    apex_tests = [
        {
            "name": truncate(item.get("name")),
            "methodName": truncate(item.get("methodName")),
            "message": truncate(item.get("message")),
        }
        for item in test_failures[:MAX_FAILURE_DETAILS]
        if isinstance(item, dict)
    ]
    def count(key: str, fallback: int) -> int:
        value = result.get(key)
        return value if isinstance(value, int) else fallback

    return {
        "componentErrors": count("numberComponentErrors", len(component_failures)),
        "componentsTotal": count("numberComponentsTotal", 0),
        "testErrors": count("numberTestErrors", len(test_failures)),
        "testsTotal": count("numberTestsTotal", 0),
        "componentFailures": components,
        "componentFailuresTruncated": len(component_failures) > len(components),
        "apexTestFailures": apex_tests,
        "apexTestFailuresTruncated": len(test_failures) > len(apex_tests),
    }


def run_cli_json(
    command: list[str], runner: Callable[..., Any]
) -> tuple[dict[str, Any] | None, str]:
    try:
        completed = runner(
            command,
            text=True,
            capture_output=True,
            timeout=CLI_TIMEOUT_SECONDS,
            cwd=REPO_ROOT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None, "Salesforce CLI call failed or timed out"
    stdout = bounded_stdout(completed)
    if stdout is None:
        return None, "Salesforce CLI output exceeded the trusted size bound"
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None, "Salesforce CLI returned invalid JSON"
    if not isinstance(data, dict):
        return None, "Salesforce CLI returned an unexpected JSON shape"
    return data, "ok"


def status_command_hint(job_id: str, alias: str) -> str:
    return (
        f"python scripts/validate_salesforce_deploy.py status --job-id {job_id} --org {alias}"
    )


def run_start(args: argparse.Namespace, runner: Callable[..., Any]) -> dict[str, Any]:
    if Path.cwd().resolve() != REPO_ROOT:
        return blocked("start", "run from the repository root")
    tests, reason = validated_tests(args.test or [])
    if tests is None:
        return error("start", reason)
    scope, reason = validate_scope(args.source_dir or [], args.manifest)
    if scope is None:
        return error("start", reason)
    alias, reason = resolve_project_local_target(runner)
    if alias is None:
        return blocked("start", reason)
    target_ok, reason = prove_development_org(alias, runner)
    if not target_ok:
        return blocked("start", f"non-production development check failed: {reason}")
    has_apex, reason = scope_contains_apex(scope)
    if has_apex is None:
        return error("start", reason)
    test_level, applied_tests = derive_test_level(has_apex, tests)
    executable = shutil.which("sf")
    if executable is None:
        return blocked("start", "Salesforce CLI is unavailable")
    command = build_start_command(executable, alias, scope, test_level, applied_tests)
    data, reason = run_cli_json(command, runner)
    if data is None:
        return error("start", f"dry-run submission did not return a trustworthy result: {reason}")
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    job_id = str(result.get("id") or "")
    if not DEPLOY_JOB_ID.fullmatch(job_id):
        message = truncate(data.get("message") or data.get("name") or "no job ID returned")
        return error("start", f"submission was rejected before job creation: {message}")
    state = normalize_deploy_state(result.get("status"))
    envelope: dict[str, Any] = {
        "command": "start",
        "state": state,
        "capability": "check-only dry-run validation (this is not a deployment)",
        "targetOrg": alias,
        "jobId": job_id,
        "scope": scope,
        "testLevel": test_level,
        "tests": applied_tests,
        "statusCommand": status_command_hint(job_id, alias),
    }
    if state in {"FAILED", "CANCELED"}:
        envelope["failures"] = normalized_failures(result)
    return envelope


def run_status(args: argparse.Namespace, runner: Callable[..., Any]) -> dict[str, Any]:
    if Path.cwd().resolve() != REPO_ROOT:
        return blocked("status", "run from the repository root")
    job_id = str(args.job_id)
    alias = str(args.org)
    if not DEPLOY_JOB_ID.fullmatch(job_id):
        return error("status", "job ID is not a Salesforce deploy request ID (0Af...)")
    if not org_proof.ALIAS.fullmatch(alias):
        return error("status", "org alias is invalid")
    current, reason = resolve_project_local_target(runner)
    if current is None:
        return blocked("status", reason)
    if current != alias:
        return blocked(
            "status",
            f"target mismatch: the project-local target-org is now '{current}' but this "
            f"job was started against '{alias}'; re-select the original development org "
            "instead of checking the job through a different target",
        )
    target_ok, reason = prove_development_org(alias, runner)
    if not target_ok:
        return blocked("status", f"non-production development check failed: {reason}")
    executable = shutil.which("sf")
    if executable is None:
        return blocked("status", "Salesforce CLI is unavailable")
    command = [
        executable,
        "project",
        "deploy",
        "report",
        "--job-id",
        job_id,
        "--target-org",
        alias,
        "--json",
    ]
    data, reason = run_cli_json(command, runner)
    if data is None:
        return {
            "command": "status",
            "state": "INCOMPLETE",
            "reason": f"deploy report was not trustworthy: {reason}",
            "targetOrg": alias,
            "jobId": job_id,
            "statusCommand": status_command_hint(job_id, alias),
        }
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    reported_id = str(result.get("id") or "")
    if reported_id and reported_id[:15] != job_id[:15]:
        return {
            "command": "status",
            "state": "INCOMPLETE",
            "reason": "deploy report answered for a different job ID",
            "targetOrg": alias,
            "jobId": job_id,
        }
    state = normalize_deploy_state(result.get("status"))
    envelope: dict[str, Any] = {
        "command": "status",
        "state": state,
        "capability": "check-only dry-run validation (this is not a deployment)",
        "targetOrg": alias,
        "jobId": job_id,
        "statusCommand": status_command_hint(job_id, alias),
    }
    if state in {"FAILED", "CANCELED", "SUCCEEDED"}:
        envelope["failures"] = normalized_failures(result)
    return envelope


SINGLETON_FLAGS = ("--manifest", "--job-id", "--org")


def duplicate_singleton_flag(argv: list[str]) -> str | None:
    for flag in SINGLETON_FLAGS:
        occurrences = sum(
            1 for token in argv if token == flag or token.startswith(f"{flag}=")
        )
        if occurrences > 1:
            return flag
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="validate_salesforce_deploy.py",
        description="Guarded check-only Salesforce deploy validation (never a real deploy).",
        allow_abbrev=False,
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    start = subparsers.add_parser("start", allow_abbrev=False)
    start.add_argument("--source-dir", action="append", default=[])
    start.add_argument("--manifest")
    start.add_argument("--test", action="append", default=[])
    status = subparsers.add_parser("status", allow_abbrev=False)
    status.add_argument("--job-id", required=True)
    status.add_argument("--org", required=True)
    return parser


def main(argv: list[str] | None = None, runner: Callable[..., Any] = subprocess.run) -> int:
    argv = sys.argv[1:] if argv is None else argv
    duplicated = duplicate_singleton_flag(argv)
    if duplicated is not None:
        return emit(error("input", f"duplicate singleton flag: {duplicated}"))
    try:
        args = build_parser().parse_args(argv)
    except SystemExit:
        return emit(error("input", "invalid arguments; see the two documented command shapes"))
    if args.subcommand == "start":
        return emit(run_start(args, runner))
    return emit(run_status(args, runner))


if __name__ == "__main__":
    raise SystemExit(main())
