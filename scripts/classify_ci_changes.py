#!/usr/bin/env python3
"""Diff-aware CI routing: one authoritative path classification plus the gate decision.

`classify` inspects the changed paths between two commits and exports the lane booleans
consumed by .github/workflows/harness-ci.yml. `gate` evaluates, at the end of the run,
whether every lane the classifier required actually succeeded.

Policy (master plan 2026-08-12, D3/D4/D4A/D12):
- Exactly two path classes are exempt from the full harness: `force-app/**` (activates
  the Salesforce lane) and `work-items/**` (delivery content, activates neither heavy
  lane). EVERY other path — including any path the classifier has never seen — is
  workspace control plane and requires the full harness. Fail-safe by default.
- Salesforce control surfaces (manifest/, sfdx-project.json, the scratch org definition,
  tests/e2e/, the integration field registry, the impact checker and its tests) activate
  the Salesforce lane AND, being control plane, the full harness.
- Renames/copies classify BOTH the old and the new identity.
- `content_only` is true only when at least one path changed and every old/new path is
  under work-items/**. An empty or unclassifiable diff is an error, never a content-only
  success.
- On `push`, an all-zero or unresolvable `before` SHA cannot produce a trustworthy diff:
  classification fails safe to the full harness instead of skipping validation.

Uses only the Python standard library so the classify job needs no dependency install.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

FIELD_PATH_RE = re.compile(
    r"^force-app/main/default/objects/([^/]+)/fields/([^/]+)\.field-meta\.xml$"
)

# The only two path classes exempt from the full harness (D3).
FORCE_APP_PREFIX = "force-app/"
WORK_ITEMS_PREFIX = "work-items/"

# Paths that activate the Salesforce lane (D4). Prefixes end with '/'; exact names don't.
SALESFORCE_PREFIXES = (
    "force-app/",
    "manifest/",
    "tests/e2e/",
)
SALESFORCE_FILES = frozenset(
    {
        "sfdx-project.json",
        "config/project-scratch-def.json",
        "config/integration-fields.yml",
        "scripts/check_integration_field_impact.py",
        "tests/test_integration_field_impact.py",
    }
)

SINGLE_PATH_STATUSES = {"A", "M", "D", "T"}
DUAL_PATH_STATUSES = {"R", "C"}

ZERO_SHA_RE = re.compile(r"^0{40}$")


class ClassificationError(Exception):
    """The diff cannot be classified trustworthily."""


# ------------------------------------------------------------------------------- diff


def parse_name_status(raw: str) -> List[Tuple[str, Optional[str], Optional[str]]]:
    """Parse NUL-separated `git diff --name-status -z` output into
    (status letter, old path or None, new path or None)."""
    tokens = [token for token in raw.split("\0") if token != ""]
    entries: List[Tuple[str, Optional[str], Optional[str]]] = []
    position = 0
    while position < len(tokens):
        status_token = tokens[position]
        letter = status_token[:1]
        if letter in DUAL_PATH_STATUSES:
            if position + 2 > len(tokens) - 1:
                raise ClassificationError(f"truncated diff entry after status {status_token!r}")
            entries.append((letter, tokens[position + 1], tokens[position + 2]))
            position += 3
        elif letter in SINGLE_PATH_STATUSES and status_token == letter:
            if position + 1 > len(tokens) - 1:
                raise ClassificationError(f"truncated diff entry after status {status_token!r}")
            path = tokens[position + 1]
            entries.append((letter, path, path))
            position += 2
        else:
            raise ClassificationError(f"unsupported git diff status {status_token!r}")
    return entries


def git_diff_entries(base: str, head: str) -> List[Tuple[str, Optional[str], Optional[str]]]:
    for label, sha in (("base", base), ("head", head)):
        if not re.fullmatch(r"[0-9a-fA-F]{4,40}", sha or ""):
            raise ClassificationError(f"{label} is not a usable commit id: {sha!r}")
    completed = subprocess.run(
        [
            "git",
            "diff",
            "--name-status",
            "-z",
            "--find-renames",
            "--find-copies",
            "--no-color",
            f"{base}...{head}",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if completed.returncode != 0:
        raise ClassificationError(
            f"git diff failed for {base}...{head}: {completed.stderr.strip() or completed.returncode}"
        )
    return parse_name_status(completed.stdout)


# ---------------------------------------------------------------------- classification


def is_salesforce_path(path: str) -> bool:
    return path.startswith(SALESFORCE_PREFIXES) or path in SALESFORCE_FILES


def is_exempt_from_full_harness(path: str) -> bool:
    return path.startswith(FORCE_APP_PREFIX) or path.startswith(WORK_ITEMS_PREFIX)


def classify_paths(entries: List[Tuple[str, Optional[str], Optional[str]]]) -> Dict[str, object]:
    """Classify parsed diff entries. Raises ClassificationError on an empty diff."""
    paths: List[str] = []
    field_candidates = set()
    for _status, old_path, new_path in entries:
        for path in (old_path, new_path):
            if path is None:
                continue
            if path not in paths:
                paths.append(path)
            if FIELD_PATH_RE.fullmatch(path):
                field_candidates.add(path)
    if not paths:
        raise ClassificationError("empty diff: nothing to classify (this is an error, not a pass)")
    salesforce_changed = any(is_salesforce_path(path) for path in paths)
    full_harness_required = any(not is_exempt_from_full_harness(path) for path in paths)
    content_only = all(path.startswith(WORK_ITEMS_PREFIX) for path in paths)
    return {
        "salesforce_changed": salesforce_changed,
        "full_harness_required": full_harness_required,
        "content_only": content_only,
        "integration_field_candidates": len(field_candidates),
        "changed_path_count": len(paths),
        "note": "",
    }


def fail_safe_result(note: str) -> Dict[str, object]:
    """No trustworthy diff: require the full harness rather than skip validation (D12)."""
    return {
        "salesforce_changed": False,
        "full_harness_required": True,
        "content_only": False,
        "integration_field_candidates": 0,
        "changed_path_count": -1,
        "note": note,
    }


# ---------------------------------------------------------------------------- outputs


def write_github_outputs(result: Dict[str, object], output_path: Optional[str]) -> None:
    if not output_path:
        return
    lines = []
    for key in ("salesforce_changed", "full_harness_required", "content_only"):
        lines.append(f"{key}={'true' if result[key] else 'false'}")
    lines.append(f"integration_field_candidates={result['integration_field_candidates']}")
    with open(output_path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def print_diagnostics(base: str, head: str, result: Dict[str, object]) -> None:
    lanes = []
    if result["salesforce_changed"]:
        lanes.append("salesforce")
    if result["full_harness_required"]:
        lanes.append("full-harness")
    if not lanes:
        lanes.append("none (content-only)")
    print(f"classify: base={base} head={head}")
    print(f"classify: changed paths={result['changed_path_count']}")
    print(f"classify: lanes={', '.join(lanes)}")
    print(f"classify: content_only={result['content_only']}")
    print(f"classify: integration_field_candidates={result['integration_field_candidates']}")
    if result["note"]:
        print(f"classify: note={result['note']}")


# ------------------------------------------------------------------------------- gate


def gate_decision(
    classify_result: str,
    salesforce_required: bool,
    salesforce_result: str,
    full_harness_required: bool,
    full_harness_result: str,
) -> Tuple[bool, List[str]]:
    """(gate passes, human-readable reasons). A required lane must be 'success'; a lane
    may be 'skipped' only when the classifier declared it unnecessary; a lane that ran
    and failed or was cancelled fails the gate even if it was not required."""
    messages: List[str] = []
    ok = True
    if classify_result != "success":
        return False, [f"classification did not succeed (result: {classify_result})"]
    for lane, required, result in (
        ("salesforce", salesforce_required, salesforce_result),
        ("full-harness", full_harness_required, full_harness_result),
    ):
        requirement = "required" if required else "not required"
        if result == "success":
            messages.append(f"{lane}: success ({requirement})")
        elif result == "skipped" and not required:
            messages.append(f"{lane}: skipped as declared unnecessary")
        elif result == "skipped":
            ok = False
            messages.append(f"{lane}: REQUIRED but skipped - failing the gate")
        else:
            ok = False
            messages.append(f"{lane}: {result} ({requirement}) - failing the gate")
    return ok, messages


# ------------------------------------------------------------------------------- main


def parse_bool(value: str) -> bool:
    lowered = (value or "").strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no", ""):
        return False
    raise argparse.ArgumentTypeError(f"expected a boolean, got {value!r}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    classify = commands.add_parser("classify", help="classify the changed paths of a commit range")
    classify.add_argument("--event", required=True, choices=("pull_request", "push"))
    classify.add_argument("--base", required=True)
    classify.add_argument("--head", required=True)
    classify.add_argument(
        "--github-output",
        default=os.environ.get("GITHUB_OUTPUT"),
        help="file to append key=value outputs to (defaults to $GITHUB_OUTPUT)",
    )

    gate = commands.add_parser("gate", help="final aggregate decision over the lane results")
    gate.add_argument("--classify-result", required=True)
    gate.add_argument("--salesforce-required", required=True, type=parse_bool)
    gate.add_argument("--salesforce-result", required=True)
    gate.add_argument("--full-harness-required", required=True, type=parse_bool)
    gate.add_argument("--full-harness-result", required=True)
    return parser


def run_classify(args: argparse.Namespace) -> int:
    if args.event == "push" and (not args.base or ZERO_SHA_RE.fullmatch(args.base)):
        result = fail_safe_result(
            f"push event with unusable before SHA {args.base!r}; failing safe to full harness"
        )
    else:
        try:
            result = classify_paths(git_diff_entries(args.base, args.head))
        except ClassificationError as exc:
            if args.event == "push":
                # A pushed range we cannot diff (e.g. force-pushed history) must not skip
                # validation; a pull_request event with bad SHAs is a hard error instead.
                result = fail_safe_result(f"push diff not classifiable ({exc}); failing safe")
            else:
                print(f"classify: ERROR: {exc}", file=sys.stderr)
                return 2
    print_diagnostics(args.base, args.head, result)
    write_github_outputs(result, args.github_output)
    return 0


def run_gate(args: argparse.Namespace) -> int:
    ok, messages = gate_decision(
        args.classify_result,
        args.salesforce_required,
        args.salesforce_result,
        args.full_harness_required,
        args.full_harness_result,
    )
    for message in messages:
        print(f"gate: {message}")
    print(f"gate: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def harden_console_streams() -> None:
    """Changed paths can contain arbitrary user text; a Windows cp1252/cp437 console
    must degrade the echo (errors="replace"), never crash the classifier."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: Optional[List[str]] = None) -> int:
    harden_console_streams()
    args = build_parser().parse_args(argv)
    if args.command == "classify":
        return run_classify(args)
    return run_gate(args)


if __name__ == "__main__":
    sys.exit(main())
