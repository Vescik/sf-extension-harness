#!/usr/bin/env python3
"""One-time, human-run legacy Knowledge migration kit (TEMPORARY — not a product surface).

Migrates useful Knowledge from a separately located legacy workspace into this repository's
governed one-file Knowledge store. Design rules (master plan 2026-08-11):

- Migrate evidence, not files: legacy entries/ledgers are source material; nothing is copied
  into `.ai/knowledge/**` wholesale.
- `scripts/knowledge_store.py` stays the only Knowledge writer. This tool orchestrates that
  executor through its public CLI; it never edits an entry file or a ledger itself.
- Legacy approval is provenance only. Target approval happens exclusively through the existing
  `entry-review` -> human confirmation -> `entry-approve` flow, which this tool never invokes.
- Plan mode (the default, and the interactive no-argument path) writes only an ignored report
  under `output/knowledge-migration/`. Any target write requires the explicit `stage` mode, a
  digest-verified manifest, a clean target worktree, and a typed confirmation.
- No MCP, no org/ADO calls, no hooks, no scheduling, no normal-runtime cost.

Remove this file and MIGRATE-LEGACY-KNOWLEDGE.md before the final Knowledge-only commit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:  # same remedy message convention as validate_harness.py
    print(
        "migrate_legacy_knowledge: missing dev dependency PyYAML; run through the repo .venv "
        "or `pip install -r requirements-dev.lock`",
        file=sys.stderr,
    )
    raise SystemExit(1)

TOOL_VERSION = "1.0.0"
MANIFEST_VERSION = 1
TARGET_ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable

# The only members the known legacy one-file layout may contain under .ai/knowledge.
RECOGNIZED_KNOWLEDGE_MEMBERS = {
    "artifacts",
    "artifacts-ledger.jsonl",
    "artifacts-org-ledger.jsonl",
    "features",
    "features-ledger.jsonl",
    "keyword-taxonomy.md",
    "README.md",
}
IGNORED_MEMBERS = {".DS_Store"}

CLASSES = (
    "EXACT_REVIEW_CANDIDATE",
    "REAPPROVAL_CANDIDATE",
    "ORG_REFRESH_ONLY",
    "ALREADY_PRESENT",
    "CONFLICT",
    "QUARANTINE",
)
STAGEABLE = {"EXACT_REVIEW_CANDIDATE", "REAPPROVAL_CANDIDATE"}


class MigrationError(Exception):
    """Fatal, operator-facing failure; never leaves a partial target write behind."""


class UnsupportedLayout(MigrationError):
    def __init__(self, message: str, found: list[str]):
        super().__init__(message)
        self.found = found


# ---------------------------------------------------------------------------- helpers


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_id_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_frontmatter(path: Path) -> tuple[dict, str]:
    """Split a one-file entry into (frontmatter mapping, body). Raises on malformed files."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise MigrationError(f"{path}: no frontmatter")
    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        raise MigrationError(f"{path}: unterminated frontmatter")
    data = yaml.safe_load(parts[0][4:])
    if not isinstance(data, dict):
        raise MigrationError(f"{path}: frontmatter is not a mapping")
    return data, parts[1]


def read_jsonl(path: Path) -> list[dict]:
    records = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MigrationError(f"{path}:{line_no}: invalid ledger line: {exc}") from exc
        if not isinstance(record, dict):
            raise MigrationError(f"{path}:{line_no}: ledger record is not an object")
        records.append(record)
    return records


def run_process(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)


def git_output(target_root: Path, *args: str) -> str:
    result = run_process(["git", *args], target_root)
    if result.returncode != 0:
        raise MigrationError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


# ---------------------------------------------------------------------------- path safety


def normalize_operator_path(raw: str) -> str:
    return raw.strip().strip("'\"").strip()


def validate_legacy_root(raw: str, target_root: Path) -> Path:
    """Resolve and safety-check an operator-supplied legacy path. Raises MigrationError."""
    cleaned = normalize_operator_path(raw)
    if not cleaned:
        raise MigrationError("empty path")
    candidate = Path(cleaned).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise MigrationError(f"path does not resolve: {candidate} ({exc})") from exc
    if not resolved.is_dir():
        raise MigrationError(f"not a directory: {resolved}")
    try:
        next(resolved.iterdir(), None)
    except PermissionError as exc:
        raise MigrationError(f"directory is not readable: {resolved}") from exc
    target = target_root.resolve()
    if resolved == target:
        raise MigrationError("the legacy path is this target repository itself")
    if target in resolved.parents:
        raise MigrationError("the legacy path is inside this target repository")
    if resolved in target.parents:
        raise MigrationError("this target repository is nested inside the legacy path")
    return resolved


# ---------------------------------------------------------------------------- legacy adapter


def detect_layout(legacy_root: Path) -> dict:
    """Recognize only the known legacy one-file Knowledge layout; read-only."""
    knowledge = legacy_root / ".ai" / "knowledge"
    if not knowledge.is_dir():
        found = sorted(
            str(p.relative_to(legacy_root))
            for p in legacy_root.glob("*")
            if p.name not in IGNORED_MEMBERS
        )[:20]
        raise UnsupportedLayout(
            "no .ai/knowledge directory — not the known legacy one-file layout", found
        )
    members = {p.name for p in knowledge.iterdir() if p.name not in IGNORED_MEMBERS}
    unrecognized = sorted(members - RECOGNIZED_KNOWLEDGE_MEMBERS)
    if unrecognized:
        raise UnsupportedLayout(
            "partially recognized layout — unknown members under .ai/knowledge "
            "(a Markdown/JSONL folder is not automatically importable)",
            [f".ai/knowledge/{name}" for name in unrecognized],
        )
    artifacts = knowledge / "artifacts"
    features = knowledge / "features"
    return {
        "knowledgeRoot": knowledge,
        "hasArtifacts": artifacts.is_dir(),
        "artifactEntryPaths": sorted(artifacts.rglob("*.md")) if artifacts.is_dir() else [],
        "artifactLedger": knowledge / "artifacts-ledger.jsonl",
        "orgLedger": knowledge / "artifacts-org-ledger.jsonl",
        "featurePaths": sorted(features.rglob("feature.md")) if features.is_dir() else [],
        "featureLedger": knowledge / "features-ledger.jsonl",
    }


def legacy_fingerprint(layout: dict) -> str:
    """Content digest over the legacy knowledge tree (paths + file digests)."""
    knowledge: Path = layout["knowledgeRoot"]
    rows = []
    for path in sorted(knowledge.rglob("*")):
        if path.is_file() and path.name not in IGNORED_MEMBERS:
            rows.append(
                f"{path.relative_to(knowledge).as_posix()}:{sha256_bytes(path.read_bytes())}"
            )
    return sha256_bytes("\n".join(rows).encode("utf-8"))


def latest_ledger_state(ledger_path: Path) -> dict[str, dict]:
    """identity -> latest approve/revoke record (latest-wins by sequence, then order)."""
    if not ledger_path.is_file():
        return {}
    state: dict[str, dict] = {}
    for record in read_jsonl(ledger_path):
        identity = record.get("identity")
        if isinstance(identity, str):
            state[identity] = record
    return state


def org_usage_identities(org_ledger_path: Path) -> set[str]:
    if not org_ledger_path.is_file():
        return set()
    return {
        record["identity"]
        for record in read_jsonl(org_ledger_path)
        if isinstance(record.get("identity"), str)
    }


def extract_purpose(body: str) -> str | None:
    """Return the prose under '## Purpose', or None when absent/sentinel/unrepresentable."""
    match = re.search(r"^## Purpose\s*$", body, flags=re.MULTILINE)
    if not match:
        return None
    prose = body[match.end():]
    next_heading = re.search(r"^## ", prose, flags=re.MULTILINE)
    if next_heading:
        prose = prose[: next_heading.start()]
    prose = prose.strip()
    if not prose or "<AGENT_" in prose:
        return None
    return prose


def parse_legacy_entry(path: Path, knowledge_root: Path) -> dict:
    """Parse one legacy entry into a manifest-shaped record fragment. Never copies the body."""
    front, body = read_frontmatter(path)
    subject = front.get("subject") or {}
    metadata_type = subject.get("metadataType")
    full_name = subject.get("fullName")
    namespace = subject.get("namespace")
    if not metadata_type or not full_name:
        raise MigrationError(f"{path}: entry has no subject identity")
    identity = f"{metadata_type}:{namespace or 'c'}:{full_name}"
    profile = front.get("profile") or {}
    lifecycle = front.get("lifecycle") or {}
    fragments = [
        {"path": frag.get("path"), "sourceDigest": frag.get("sourceDigest")}
        for frag in (front.get("source") or {}).get("fragments") or []
        if isinstance(frag, dict)
    ]
    purpose = extract_purpose(body)
    return {
        "legacyIdentity": identity,
        "legacyEntryPath": path.relative_to(knowledge_root).as_posix(),
        "legacyProfileId": profile.get("id"),
        "legacyProfileVersion": profile.get("version"),
        "legacyContentDigest": lifecycle.get("contentDigest"),
        "legacyState": lifecycle.get("state"),
        "legacySourceFragments": fragments,
        "legacyLimitations": [
            item for item in (front.get("limitations") or []) if isinstance(item, str)
        ],
        "_purpose": purpose,  # held in memory for staging; never written to the manifest
        "hasPurposeProse": purpose is not None,
        "subject": {
            "metadataType": metadata_type,
            "fullName": full_name,
            "namespace": namespace,
        },
    }


# ---------------------------------------------------------------------------- target probes


def target_entry_index(target_root: Path) -> dict[str, dict]:
    """identity -> {state, contentDigest} from the target's own entry files (read-only)."""
    index: dict[str, dict] = {}
    artifacts = target_root / ".ai" / "knowledge" / "artifacts"
    if not artifacts.is_dir():
        return index
    for path in sorted(artifacts.rglob("*.md")):
        try:
            front, _ = read_frontmatter(path)
        except MigrationError:
            continue
        subject = front.get("subject") or {}
        if not subject.get("metadataType") or not subject.get("fullName"):
            continue
        identity = (
            f"{subject['metadataType']}:{subject.get('namespace') or 'c'}:{subject['fullName']}"
        )
        index[identity] = {
            "state": (front.get("lifecycle") or {}).get("state"),
            "contentDigest": (front.get("lifecycle") or {}).get("contentDigest"),
        }
    return index


def refresh_target_inventory(target_root: Path) -> None:
    """Refresh the collector's own ignored derived inventory (.cache/knowledge-proposals/).

    resolve requires it; it is a local derived cache, never target Knowledge or a ledger, so
    plan mode may refresh it. Failure is tolerated — every resolve then reports
    RESOLVE_COMMAND_FAILED instead of guessing.
    """
    run_process([PYTHON, "scripts/force_app_knowledge.py", "inventory"], target_root)


def resolve_against_target(record: dict, target_root: Path) -> dict:
    """Read-only identity resolution through the target collector's resolve command."""
    subject = record["subject"]
    result = run_process(
        [PYTHON, "scripts/force_app_knowledge.py", "resolve", "--name", subject["fullName"]],
        target_root,
    )
    if result.returncode != 0:
        return {"resolves": False, "ambiguous": False, "reason": "RESOLVE_COMMAND_FAILED"}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"resolves": False, "ambiguous": False, "reason": "RESOLVE_OUTPUT_INVALID"}
    matches = [
        component
        for component in payload.get("components", [])
        if component.get("metadataType") == subject["metadataType"]
        # the live collector names the field `name`; older fixtures used `fullName`
        and (component.get("fullName") or component.get("name")) == subject["fullName"]
    ]
    if len(matches) > 1:
        return {"resolves": False, "ambiguous": True, "reason": "AMBIGUOUS_IDENTITY"}
    if not matches:
        return {"resolves": False, "ambiguous": False, "reason": "NOT_IN_TARGET_SOURCE"}
    return {"resolves": True, "ambiguous": False, "reason": None}


def source_fragments_match_target(record: dict, target_root: Path) -> bool:
    for fragment in record["legacySourceFragments"]:
        rel, digest = fragment.get("path"), fragment.get("sourceDigest")
        if not rel or not digest:
            return False
        candidate = target_root / rel
        if not candidate.is_file() or sha256_bytes(candidate.read_bytes()) != digest:
            return False
    return bool(record["legacySourceFragments"])


# ---------------------------------------------------------------------------- classification


def classify(record: dict, resolution: dict, target_index: dict[str, dict],
             org_identities: set[str], target_root: Path) -> tuple[str, list[str]]:
    """Return (class, reason codes) for one parsed legacy entry — §7.3, exact classes."""
    identity = record["legacyIdentity"]
    reasons: list[str] = []
    existing = target_index.get(identity)
    if existing is not None:
        if existing.get("contentDigest") == record.get("legacyContentDigest"):
            return "ALREADY_PRESENT", ["TARGET_ENTRY_SAME_DIGEST"]
        if existing.get("state") == "draft":
            # A previous wave already staged this identity: continue its review/approval
            # rather than re-staging (per-plan resume semantics — never duplicate).
            return "CONFLICT", ["TARGET_ENTRY_DIFFERENT_DIGEST", "TARGET_DRAFT_PENDING_REVIEW"]
        return "CONFLICT", ["TARGET_ENTRY_DIFFERENT_DIGEST"]
    if resolution["ambiguous"]:
        return "CONFLICT", ["AMBIGUOUS_IDENTITY"]
    if not record["hasPurposeProse"]:
        if identity in org_identities:
            return "ORG_REFRESH_ONLY", ["NO_PROSE", "LEGACY_ORG_USAGE_PRESENT"]
        return "QUARANTINE", ["NO_REPRESENTABLE_PROSE"]
    if not record.get("legacyProfileId"):
        return "QUARANTINE", ["MISSING_PROFILE"]
    if not resolution["resolves"]:
        return "QUARANTINE", ["SOURCE_NOT_IN_TARGET", resolution["reason"] or ""]
    if source_fragments_match_target(record, target_root):
        return "EXACT_REVIEW_CANDIDATE", ["SOURCE_DIGESTS_MATCH"]
    reasons.append("SOURCE_DIGESTS_DIFFER")
    return "REAPPROVAL_CANDIDATE", reasons


# ---------------------------------------------------------------------------- plan mode


def build_plan(legacy_root: Path, target_root: Path) -> dict:
    layout = detect_layout(legacy_root)
    ledger_state = latest_ledger_state(layout["artifactLedger"])
    org_identities = org_usage_identities(layout["orgLedger"])
    target_index = target_entry_index(target_root)
    if layout["artifactEntryPaths"]:
        refresh_target_inventory(target_root)

    records = []
    for path in layout["artifactEntryPaths"]:
        try:
            record = parse_legacy_entry(path, layout["knowledgeRoot"])
        except MigrationError as exc:
            records.append(
                {
                    "legacyIdentity": None,
                    "legacyEntryPath": path.relative_to(layout["knowledgeRoot"]).as_posix(),
                    "class": "QUARANTINE",
                    "reasons": ["INVALID_LEGACY_ENTRY", str(exc)],
                    "proposedAction": "none — human decision",
                }
            )
            continue
        resolution = resolve_against_target(record, target_root)
        cls, reasons = classify(record, resolution, target_index, org_identities, target_root)
        approval = ledger_state.get(record["legacyIdentity"])
        row = {
            key: value for key, value in record.items() if not key.startswith("_")
        }
        row.update(
            {
                "class": cls,
                "reasons": [reason for reason in reasons if reason],
                "identityResolvesInTarget": resolution["resolves"],
                "targetProfileValidation": "stage-time (the executor itself validates on entry-draft)",
                "targetCollision": (
                    "same-effective-entry"
                    if cls == "ALREADY_PRESENT"
                    else "different-existing-entry"
                    if "TARGET_ENTRY_DIFFERENT_DIGEST" in reasons
                    else "absent"
                ),
                "legacyApproval": (
                    {
                        "action": approval.get("action"),
                        "reviewedAt": approval.get("reviewedAt"),
                        "reviewedBy": approval.get("reviewedBy"),
                        "reviewedContentDigest": approval.get("reviewedContentDigest"),
                        "note": "historical provenance only — never a target approval",
                    }
                    if approval
                    else None
                ),
                "proposedAction": {
                    "EXACT_REVIEW_CANDIDATE": "stage target draft; then normal review/approval",
                    "REAPPROVAL_CANDIDATE": "stage target draft; flag for human review",
                    "ORG_REFRESH_ONLY": "no entry; schedule a fresh target org investigation",
                    "ALREADY_PRESENT": "none — already effective in target",
                    "CONFLICT": "none — human decision required",
                    "QUARANTINE": "none — preserve manifest record only",
                }[cls],
            }
        )
        row["recordDigest"] = sha256_bytes(canonical_json(row).encode("utf-8"))
        records.append(row)

    features = [
        {
            "path": path.relative_to(layout["knowledgeRoot"]).as_posix(),
            "note": "listed only — Feature migration follows the artifact corpus (plan §9.3)",
        }
        for path in layout["featurePaths"]
    ]

    counts = {cls: 0 for cls in CLASSES}
    for row in records:
        counts[row["class"]] += 1

    header = {
        "manifestVersion": MANIFEST_VERSION,
        "toolVersion": TOOL_VERSION,
        "generatedAt": utc_now(),
        "targetRoot": str(target_root),
        "targetHead": git_output(target_root, "rev-parse", "HEAD"),
        "targetWorktreeDirty": bool(git_output(target_root, "status", "--porcelain")),
        "targetSourceTree": git_output(target_root, "rev-parse", "HEAD:force-app"),
        "collectorVersion": read_collector_version(target_root),
        "legacyRoot": str(legacy_root),
        "legacyRootNote": "local-only provenance — never persist into tracked target files",
        "legacyFingerprint": legacy_fingerprint(layout),
        "counts": counts,
        "artifactEntries": len(records),
        "featureDocuments": len(features),
    }
    return {"header": header, "records": records, "features": features}


def read_collector_version(target_root: Path) -> str:
    text = (target_root / "scripts" / "force_app_knowledge.py").read_text(encoding="utf-8")
    match = re.search(r'^COLLECTOR_VERSION\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    return match.group(1) if match else "unknown"


def manifest_digest(plan: dict) -> str:
    return sha256_bytes(
        canonical_json({"header": plan["header"], "records": plan["records"]}).encode("utf-8")
    )


def write_plan(plan: dict, target_root: Path) -> Path:
    run_dir = target_root / "output" / "knowledge-migration" / run_id_now()
    run_dir.mkdir(parents=True, exist_ok=True)
    plan_payload = dict(plan)
    plan_payload["manifestDigest"] = manifest_digest(plan)
    (run_dir / "manifest.json").write_text(
        json.dumps(plan_payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text(render_report(plan_payload), encoding="utf-8")
    return run_dir


def render_report(plan: dict) -> str:
    header = plan["header"]
    lines = [
        "# Legacy Knowledge migration plan (ignored operator report)",
        "",
        f"Generated: {header['generatedAt']}  ·  tool {header['toolVersion']}  ·  "
        f"manifest v{header['manifestVersion']}",
        f"Target HEAD: `{header['targetHead']}`  ·  worktree dirty: "
        f"**{header['targetWorktreeDirty']}**",
        f"Legacy fingerprint: `{header['legacyFingerprint'][:23]}…`",
        "",
        "Legacy approval history is provenance only; every migrated entry goes through the",
        "target's own review and digest-pinned human approval.",
        "",
        "## Counts",
        "",
        "| Class | Count |",
        "|---|---:|",
    ]
    for cls in CLASSES:
        lines.append(f"| {cls} | {header['counts'][cls]} |")
    lines += [
        f"| **artifact entries total** | **{header['artifactEntries']}** |",
        f"| feature documents (listed only) | {header['featureDocuments']} |",
        "",
        "## Rows",
        "",
    ]
    if not plan["records"]:
        lines.append(
            "_Empty corpus: the legacy layout was recognized but contains no artifact "
            "entries. Nothing to migrate._"
        )
    for row in plan["records"]:
        lines.append(
            f"- `{row.get('legacyIdentity') or row['legacyEntryPath']}` — **{row['class']}** "
            f"({', '.join(row['reasons'])}) → {row['proposedAction']}"
        )
    if header["targetWorktreeDirty"]:
        lines += ["", "> **WARNING:** the target worktree is dirty. Staging will refuse."]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------- stage mode


def load_manifest(manifest_path: Path) -> dict:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError(f"cannot read manifest: {exc}") from exc
    stored = payload.get("manifestDigest")
    computed = sha256_bytes(
        canonical_json({"header": payload.get("header"), "records": payload.get("records")}).encode(
            "utf-8"
        )
    )
    if stored != computed:
        raise MigrationError("manifest digest mismatch — the manifest was edited or truncated")
    if payload.get("header", {}).get("toolVersion") != TOOL_VERSION:
        raise MigrationError("manifest was generated by a different tool version — re-run plan")
    return payload


def stage_preconditions(payload: dict, target_root: Path) -> None:
    header = payload["header"]
    if Path(header["targetRoot"]).resolve() != target_root.resolve():
        raise MigrationError("manifest target root does not match this repository")
    if git_output(target_root, "status", "--porcelain"):
        raise MigrationError("target worktree is dirty — commit or stash first, then re-run plan")
    if git_output(target_root, "rev-parse", "HEAD") != header["targetHead"]:
        raise MigrationError("target HEAD changed since the plan — re-run plan")
    if git_output(target_root, "rev-parse", "HEAD:force-app") != header["targetSourceTree"]:
        raise MigrationError("target force-app changed since the plan — re-run plan")
    if read_collector_version(target_root) != header["collectorVersion"]:
        raise MigrationError("target collector version changed since the plan — re-run plan")
    legacy_root = Path(header["legacyRoot"])
    if not legacy_root.is_dir():
        raise MigrationError("legacy root from the manifest is not accessible — re-run plan")
    if legacy_fingerprint(detect_layout(legacy_root)) != header["legacyFingerprint"]:
        raise MigrationError("legacy corpus changed since the plan — re-run plan")


def store_call(target_root: Path, *args: str) -> subprocess.CompletedProcess:
    return run_process([PYTHON, "scripts/knowledge_store.py", *args], target_root)


def stage(manifest_path: Path, target_root: Path, ask=input, echo=print) -> int:
    payload = load_manifest(manifest_path)
    stage_preconditions(payload, target_root)
    candidates = [
        row
        for row in payload["records"]
        if row["class"] in STAGEABLE
        and row.get("identityResolvesInTarget")
        and row.get("targetCollision") == "absent"
    ]
    if not candidates:
        echo("Nothing stageable in this manifest (no EXACT/REAPPROVAL rows without collision).")
        return 0
    echo("Stageable rows:")
    for row in candidates:
        echo(f"  {row['legacyIdentity']}  [{row['class']}]")
    selection = normalize_operator_path(
        ask("Identities to stage (comma-separated, or 'all'): ")
    )
    if selection.lower() == "all":
        selected = candidates
    else:
        wanted = {token.strip() for token in selection.split(",") if token.strip()}
        selected = [row for row in candidates if row["legacyIdentity"] in wanted]
        missing = wanted - {row["legacyIdentity"] for row in selected}
        if missing:
            raise MigrationError(f"not stageable or unknown: {', '.join(sorted(missing))}")
    if not selected:
        echo("No rows selected. CANCELLED — no target Knowledge was written.")
        return 1
    confirmation = normalize_operator_path(
        ask(f"Type the number of drafts to create ({len(selected)}) to confirm: ")
    )
    if confirmation != str(len(selected)):
        echo("Confirmation mismatch. CANCELLED — no target Knowledge was written.")
        return 1

    # Re-read the legacy corpus for the Purpose prose (the manifest never carries bodies).
    legacy_layout = detect_layout(Path(payload["header"]["legacyRoot"]))
    prose: dict[str, tuple[str, list[str]]] = {}
    for path in legacy_layout["artifactEntryPaths"]:
        try:
            record = parse_legacy_entry(path, legacy_layout["knowledgeRoot"])
        except MigrationError:
            continue
        if record["_purpose"] is not None:
            prose[record["legacyIdentity"]] = (record["_purpose"], record["legacyLimitations"])

    run_dir = manifest_path.parent
    outcomes_path = run_dir / "stage-outcomes.jsonl"
    staged = 0
    for row in selected:
        identity = row["legacyIdentity"]
        if identity not in prose:
            raise MigrationError(f"{identity}: purpose prose vanished from the legacy corpus")
        purpose, limitations = prose[identity]
        if "<AGENT_" in purpose or not purpose.strip():
            raise MigrationError(f"{identity}: unrepresentable purpose body at stage time")
        if target_entry_index(target_root).get(identity) is not None:
            append_outcome(outcomes_path, identity, "skipped", "target entry already exists")
            echo(f"  = {identity}: target entry already exists — skipped (idempotent)")
            continue
        subject = row["subject"]
        draft_args = [
            "entry-draft",
            "--metadata-type", subject["metadataType"],
            "--full-name", subject["fullName"],
        ]
        if subject.get("namespace"):
            draft_args += ["--namespace", subject["namespace"]]
        result = store_call(target_root, *draft_args)
        if result.returncode != 0:
            append_outcome(outcomes_path, identity, "failed", f"entry-draft: {result.stderr.strip()}")
            echo(f"STOP: {identity}: entry-draft failed:\n{result.stdout}\n{result.stderr}")
            echo("Wave stopped. Already-created drafts are left intact (re-run detects them).")
            return 1
        purpose_file = run_dir / f"purpose-{re.sub(r'[^A-Za-z0-9_.-]', '_', identity)}.md"
        purpose_file.write_text(purpose + "\n", encoding="utf-8")
        describe_args = ["entry-describe", "--identity", identity, "--purpose-file", str(purpose_file)]
        for limitation in limitations:
            describe_args += ["--limitation", limitation]
        result = store_call(target_root, *describe_args)
        if result.returncode != 0:
            append_outcome(outcomes_path, identity, "failed", f"entry-describe: {result.stderr.strip()}")
            echo(f"STOP: {identity}: entry-describe failed:\n{result.stdout}\n{result.stderr}")
            echo("Wave stopped. The created draft is left intact for inspection.")
            return 1
        result = store_call(target_root, "entry-status", "--identity", identity)
        state_ok = result.returncode == 0 and '"draft"' in result.stdout
        if not state_ok:
            append_outcome(outcomes_path, identity, "failed", "post-write entry-status is not draft")
            echo(f"STOP: {identity}: post-write status check did not report a draft.")
            return 1
        append_outcome(outcomes_path, identity, "staged-draft", "entry-draft + entry-describe ok")
        staged += 1
        echo(f"  + {identity}: target draft created")
    echo(
        f"Staged {staged} target draft(s). Next: python migrate_legacy_knowledge.py "
        f"prepare-review --manifest {manifest_path}"
    )
    return 0


def append_outcome(path: Path, identity: str, outcome: str, detail: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {"at": utc_now(), "identity": identity, "outcome": outcome, "detail": detail}
            )
            + "\n"
        )


# ---------------------------------------------------------------------------- prepare-review


def prepare_review(manifest_path: Path, target_root: Path, echo=print) -> int:
    payload = load_manifest(manifest_path)
    outcomes_path = manifest_path.parent / "stage-outcomes.jsonl"
    if not outcomes_path.is_file():
        raise MigrationError("no stage outcomes beside this manifest — run stage first")
    staged = [
        record["identity"]
        for record in read_jsonl(outcomes_path)
        if record.get("outcome") == "staged-draft"
    ]
    if not staged:
        raise MigrationError("no staged drafts recorded — nothing to prepare for review")
    args = ["entry-review"]
    for identity in sorted(set(staged)):
        args += ["--identity", identity]
    result = store_call(target_root, *args)
    echo(result.stdout.rstrip())
    if result.returncode != 0:
        echo(result.stderr.rstrip())
        return 1
    echo(
        "\nReview artifact rendered for the staged identities. Approval stays HUMAN-ONLY:\n"
        "run the digest-pinned entry-approve command printed above only after the human\n"
        "confirmation required by the existing Knowledge review flow. This tool never runs it."
    )
    return 0


# ---------------------------------------------------------------------------- entry points


def interactive_plan(target_root: Path, ask=input, echo=print) -> int:
    echo("Legacy Knowledge migration — plan mode (read-only; writes only an ignored report).")
    legacy_root = None
    while legacy_root is None:
        try:
            raw = ask("Path to the legacy Knowledge repository: ")
        except EOFError:
            echo("No path supplied. CANCELLED — no target Knowledge was written.")
            return 1
        try:
            legacy_root = validate_legacy_root(raw, target_root)
        except MigrationError as exc:
            echo(f"  invalid path: {exc}")
    return run_plan(legacy_root, target_root, ask=ask, echo=echo, confirm=True)


def run_plan(legacy_root: Path, target_root: Path, ask=input, echo=print, confirm: bool = False) -> int:
    try:
        layout = detect_layout(legacy_root)
    except UnsupportedLayout as exc:
        echo(f"UNSUPPORTED_LAYOUT: {exc}")
        for found in exc.found:
            echo(f"  found: {found}")
        echo("No target writes. Amend the master plan before implementing a new adapter.")
        return 2
    echo(
        f"Detected legacy one-file layout at {legacy_root}: "
        f"{len(layout['artifactEntryPaths'])} artifact entr(y/ies), "
        f"{len(layout['featurePaths'])} feature document(s), "
        f"artifact ledger {'present' if layout['artifactLedger'].is_file() else 'absent'}, "
        f"org ledger {'present' if layout['orgLedger'].is_file() else 'absent'}."
    )
    if not layout["hasArtifacts"]:
        echo("Note: no artifacts/ tree — a valid empty corpus, not an error.")
    if confirm:
        answer = normalize_operator_path(ask("Create the ignored migration report? [y/N]: "))
        if answer.lower() not in {"y", "yes"}:
            echo("CANCELLED — no target Knowledge was written.")
            return 1
    plan = build_plan(legacy_root, target_root)
    run_dir = write_plan(plan, target_root)
    echo(f"Plan written (ignored): {run_dir / 'report.md'}")
    echo(f"Manifest:               {run_dir / 'manifest.json'}")
    counts = plan["header"]["counts"]
    echo("Counts: " + ", ".join(f"{cls}={counts[cls]}" for cls in CLASSES))
    if plan["header"]["targetWorktreeDirty"]:
        echo("WARNING: target worktree is dirty — staging will refuse until it is clean.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="migrate_legacy_knowledge",
        description="One-time legacy Knowledge migration (temporary kit; plan mode by default).",
    )
    commands = parser.add_subparsers(dest="command")
    plan_cmd = commands.add_parser("plan", help="read-only migration plan (ignored report only)")
    plan_cmd.add_argument("--legacy-root", default=None)
    stage_cmd = commands.add_parser("stage", help="create target DRAFTS for reviewed manifest rows")
    stage_cmd.add_argument("--manifest", required=True)
    review_cmd = commands.add_parser(
        "prepare-review", help="render the target review surface for staged identities"
    )
    review_cmd.add_argument("--manifest", required=True)
    args = parser.parse_args(argv)

    try:
        if args.command is None:
            return interactive_plan(TARGET_ROOT)
        if args.command == "plan":
            if args.legacy_root is None:
                return interactive_plan(TARGET_ROOT)
            legacy_root = validate_legacy_root(args.legacy_root, TARGET_ROOT)
            return run_plan(legacy_root, TARGET_ROOT)
        if args.command == "stage":
            return stage(Path(args.manifest).resolve(), TARGET_ROOT)
        if args.command == "prepare-review":
            return prepare_review(Path(args.manifest).resolve(), TARGET_ROOT)
        raise MigrationError(f"unknown command {args.command!r}")
    except KeyboardInterrupt:
        print("\nCANCELLED — no target Knowledge was written by this interrupted run step.")
        return 130
    except MigrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
