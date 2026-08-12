#!/usr/bin/env python3
"""Integration Field Impact Check — advisory report over changed CustomField metadata.

Maps changed `force-app/main/default/objects/<Object>/fields/<Field>.field-meta.xml`
paths between two commits onto the integration field registry
(config/integration-fields.yml) and renders a deterministic Markdown report.

Contract (master plan 2026-08-12, D6–D9):
- A registered-field match is advisory and NEVER fails the run by itself (exit 0).
- Checker integrity failures DO fail the run (exit 2): invalid registry, invalid
  arguments, an unreadable or untrustworthy diff, or an unexpected internal error.
- The report's first line is exactly one machine-readable state:
  IMPACT_DETECTED | NO_REGISTERED_IMPACT | NO_FIELD_METADATA_CHANGED |
  REGISTRY_EMPTY | CHECK_ERROR.
- REGISTRY_EMPTY is the bootstrap state of a freshly copied workspace: valid, exit 0,
  but the report must say impact was NOT assessed. NO_REGISTERED_IMPACT is only valid
  once at least one integration entry exists.
- Matching is exact path identity; no substring, filename-only, fuzzy, or XML-content
  inference. Deleted/renamed identities derive from the path, never the working tree.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

STATE_IMPACT = "IMPACT_DETECTED"
STATE_NO_IMPACT = "NO_REGISTERED_IMPACT"
STATE_NO_FIELDS = "NO_FIELD_METADATA_CHANGED"
STATE_EMPTY = "REGISTRY_EMPTY"
STATE_ERROR = "CHECK_ERROR"

ADVISORY = (
    "A match indicates potential integration impact and is a prompt for human analysis; "
    "it is not proof of a breaking change."
)

FIELD_PATH_RE = re.compile(
    r"^force-app/main/default/objects/([^/]+)/fields/([^/]+)\.field-meta\.xml$"
)
INTEGRATION_KEY_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# Git name-status letters the checker understands. Anything else in the diff stream is a
# trustworthiness failure, not something to skip silently.
SINGLE_PATH_STATUSES = {"A", "M", "D", "T"}
DUAL_PATH_STATUSES = {"R", "C"}


class CheckError(Exception):
    """Any condition under which the checker cannot produce a trustworthy result."""


# --------------------------------------------------------------------------- registry


def validate_registry(data: Any, source: str) -> Dict[str, Dict[str, Any]]:
    """Return the validated integrations mapping or raise CheckError."""
    if not isinstance(data, dict):
        raise CheckError(f"{source}: registry root must be a mapping")
    if data.get("version") != 1:
        raise CheckError(f"{source}: unsupported registry version {data.get('version')!r} (expected 1)")
    missing = {"version", "integrations"} - set(data)
    if missing:
        raise CheckError(f"{source}: missing required key(s): {', '.join(sorted(missing))}")
    integrations = data["integrations"]
    if integrations is None:
        integrations = {}
    if not isinstance(integrations, dict):
        raise CheckError(f"{source}: 'integrations' must be a mapping")
    for key, entry in integrations.items():
        if not isinstance(key, str) or not INTEGRATION_KEY_RE.fullmatch(key):
            raise CheckError(f"{source}: integration key {key!r} must be lowercase kebab-case")
        if not isinstance(entry, dict):
            raise CheckError(f"{source}: integration {key!r} must be a mapping")
        for attr in ("name", "owner"):
            value = entry.get(attr)
            if not isinstance(value, str) or not value.strip():
                raise CheckError(f"{source}: integration {key!r} requires a non-empty '{attr}'")
        fields = entry.get("fields")
        if not isinstance(fields, list) or not fields:
            raise CheckError(f"{source}: integration {key!r} requires a non-empty 'fields' list")
        seen = set()
        for field in fields:
            if not isinstance(field, str):
                raise CheckError(f"{source}: integration {key!r} has a non-string field entry")
            if "/" in field or "\\" in field:
                raise CheckError(
                    f"{source}: integration {key!r} field {field!r} must not contain path separators"
                )
            parts = field.split(".")
            if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
                raise CheckError(
                    f"{source}: integration {key!r} field {field!r} must be exactly "
                    "'ObjectApiName.FieldApiName'"
                )
            if field in seen:
                raise CheckError(f"{source}: integration {key!r} lists field {field!r} twice")
            seen.add(field)
    return integrations


def load_registry(path: Path) -> Dict[str, Dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CheckError(f"registry is not readable: {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise CheckError(f"{path}: registry is not valid YAML: {exc}") from exc
    return validate_registry(data, str(path))


def build_field_index(
    integrations: Dict[str, Dict[str, Any]]
) -> Dict[str, List[Tuple[str, str, str]]]:
    """field identity -> sorted [(integration key, name, owner)] — one indexed lookup
    per changed path instead of a nested scan over every integration."""
    index: Dict[str, List[Tuple[str, str, str]]] = {}
    for key in sorted(integrations):
        entry = integrations[key]
        for field in entry["fields"]:
            index.setdefault(field, []).append((key, entry["name"], entry["owner"]))
    return index


# ------------------------------------------------------------------------------- diff


def parse_name_status(raw: str) -> List[Tuple[str, Optional[str], Optional[str]]]:
    """Parse NUL-separated `git diff --name-status -z` output into
    (status letter, old path or None, new path or None) tuples."""
    tokens = [token for token in raw.split("\0") if token != ""]
    entries: List[Tuple[str, Optional[str], Optional[str]]] = []
    position = 0
    while position < len(tokens):
        status_token = tokens[position]
        letter = status_token[:1]
        if letter in DUAL_PATH_STATUSES:
            if position + 2 > len(tokens) - 1:
                raise CheckError(f"truncated diff entry after status {status_token!r}")
            entries.append((letter, tokens[position + 1], tokens[position + 2]))
            position += 3
        elif letter in SINGLE_PATH_STATUSES and status_token == letter:
            if position + 1 > len(tokens) - 1:
                raise CheckError(f"truncated diff entry after status {status_token!r}")
            path = tokens[position + 1]
            old_path = path if letter in ("M", "D", "T") else None
            new_path = path if letter in ("A", "M", "T") else None
            entries.append((letter, old_path, new_path))
            position += 2
        else:
            raise CheckError(f"unsupported git diff status {status_token!r}")
    return entries


def git_diff_entries(
    base: str, head: str, cwd: Optional[Path] = None
) -> List[Tuple[str, Optional[str], Optional[str]]]:
    """Name-status entries for the merge-base range base...head."""
    for label, sha in (("base", base), ("head", head)):
        if not re.fullmatch(r"[0-9a-fA-F]{4,40}", sha or ""):
            raise CheckError(f"{label} is not a usable commit id: {sha!r}")
    command = [
        "git",
        "diff",
        "--name-status",
        "-z",
        "--find-renames",
        "--find-copies",
        "--no-color",
        f"{base}...{head}",
    ]
    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if completed.returncode != 0:
        raise CheckError(
            f"git diff failed for {base}...{head}: {completed.stderr.strip() or completed.returncode}"
        )
    return parse_name_status(completed.stdout)


# ----------------------------------------------------------------------- field events


def field_identity(path: str) -> Optional[str]:
    match = FIELD_PATH_RE.fullmatch(path)
    if not match:
        return None
    if match.group(1) in (".", "..") or match.group(2) in (".", ".."):
        return None  # traversal-shaped segments are never Salesforce API names
    return f"{match.group(1)}.{match.group(2)}"


def field_events(
    entries: List[Tuple[str, Optional[str], Optional[str]]]
) -> Tuple[List[Tuple[str, str]], int]:
    """Project diff entries onto (change label, field identity) events.

    Returns the events plus the count of changed paths that are not field metadata.
    Identities come from the path alone — a deleted file is never read from the tree.
    """
    events: List[Tuple[str, str]] = []
    ignored = 0

    def consider(label: str, path: Optional[str]) -> bool:
        if path is None:
            return False
        identity = field_identity(path)
        if identity is None:
            return False
        events.append((label, identity))
        return True

    for status, old_path, new_path in entries:
        if status in ("A", "M", "T"):
            path = new_path if new_path is not None else old_path
            if not consider("M" if status == "T" else status, path):
                ignored += 1
        elif status == "D":
            if not consider("D", old_path):
                ignored += 1
        elif status == "R":
            hit_old = consider("D (renamed away)", old_path)
            hit_new = consider("A (renamed in)", new_path)
            if not (hit_old or hit_new):
                ignored += 1
        elif status == "C":
            if not consider("A (copied in)", new_path):
                ignored += 1
        else:  # unreachable behind parse_name_status, kept as a hard stop
            raise CheckError(f"unsupported git diff status {status!r}")
    return events, ignored


# ------------------------------------------------------------------------- rendering


def escape_markdown(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    for character in ("|", "`", "*", "_", "[", "]", "<", ">"):
        escaped = escaped.replace(character, "\\" + character)
    return escaped.replace("\r", " ").replace("\n", " ")


def render_report(
    state: str,
    base: str,
    head: str,
    events: List[Tuple[str, str]],
    rows: List[Tuple[str, str, str, str, str]],
    ignored: int,
    detail: str = "",
) -> str:
    lines = [state, "", "# Integration Field Impact Check", ""]
    if state == STATE_ERROR:
        lines += [f"The check could not produce a trustworthy result: {escape_markdown(detail)}", ""]
        return "\n".join(lines)
    lines += [
        f"- Compared: `{base[:12]}` → `{head[:12]}`",
        f"- Changed field metadata paths: {len(events)}",
        f"- Registered matches: {len(rows)}",
    ]
    if ignored:
        lines.append(f"- Other changed paths ignored by the field matcher: {ignored}")
    lines.append("")
    if state == STATE_EMPTY:
        lines += [
            "The integration field registry (`config/integration-fields.yml`) contains no "
            "integrations, so integration impact was **not assessed** for this change. "
            "This is the expected bootstrap state of a freshly copied workspace; populate "
            "the registry with confirmed integration entries to activate coverage.",
            "",
        ]
    elif state == STATE_NO_FIELDS:
        lines += ["No `*.field-meta.xml` changes were detected in this range.", ""]
    elif state == STATE_NO_IMPACT:
        lines += [
            "Field metadata changed, but no changed field is registered to an integration.",
            "",
        ]
    else:
        lines += [
            "| Change | Field | Integration | Owner |",
            "|---|---|---|---|",
        ]
        for change, field, _key, name, owner in rows:
            lines.append(
                f"| {escape_markdown(change)} | {escape_markdown(field)} "
                f"| {escape_markdown(name)} | {escape_markdown(owner)} |"
            )
        lines.append("")
    lines += [f"> {ADVISORY}", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------------------ main


def run_check(
    registry_path: Path,
    base: str,
    head: str,
    cwd: Optional[Path] = None,
) -> Tuple[str, str]:
    """Return (state, markdown report). Raises CheckError on integrity failures."""
    integrations = load_registry(registry_path)
    index = build_field_index(integrations)
    entries = git_diff_entries(base, head, cwd=cwd)
    events, ignored = field_events(entries)

    rows: List[Tuple[str, str, str, str, str]] = []
    for change, identity in events:
        for key, name, owner in index.get(identity, ()):
            rows.append((change, identity, key, name, owner))
    # Deterministic: field identity, then integration key, then change label.
    rows.sort(key=lambda row: (row[1], row[2], row[0]))

    if not integrations:
        state = STATE_EMPTY
    elif not events:
        state = STATE_NO_FIELDS
    elif rows:
        state = STATE_IMPACT
    else:
        state = STATE_NO_IMPACT
    return state, render_report(state, base, head, events, rows, ignored)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--base", required=True, help="base commit id (explicit, no default)")
    parser.add_argument("--head", required=True, help="head commit id (explicit, no default)")
    parser.add_argument("--markdown-output", required=True, type=Path)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        state, report = run_check(args.registry, args.base, args.head)
        exit_code = 0
    except CheckError as exc:
        state = STATE_ERROR
        report = render_report(STATE_ERROR, args.base, args.head, [], [], 0, detail=str(exc))
        exit_code = 2
    try:
        args.markdown_output.write_text(report, encoding="utf-8")
    except OSError as exc:
        print(f"CHECK_ERROR: cannot write report: {exc}", file=sys.stderr)
        return 2
    print(report)
    if exit_code:
        print(f"integration field impact check failed: {state}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
