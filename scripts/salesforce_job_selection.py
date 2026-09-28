"""Read-only, one-shot selection for the native Salesforce job executor.

CLI 2.151.7 TTLConfig selects the newest timestamp (stable insertion order on
ties). In particular, quick deploy does NOT search backwards for a validation.
No selected cache entry, credentials, or cache filename is returned to the model.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from scripts import salesforce_operation_policy as policy
except ModuleNotFoundError:
    import salesforce_operation_policy as policy


def _fail(message: str):
    raise policy.PolicyError("job-selection-error", message)


def _cache(home: Path, filename: str, days: int) -> dict:
    path = home / ".sf" / filename
    if not path.exists():
        return {}

    def unique_pairs(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                _fail("Duplicate job cache fields; no job selected.")
            value[key] = item
        return value

    try:
        if not path.is_file() or path.stat().st_size > 1_000_000:
            _fail("Job cache is unavailable or oversized.")
        entries = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        if not isinstance(entries, dict) or len(entries) > 2000:
            _fail("Invalid job cache shape.")
        now = datetime.now(timezone.utc)
        current = {}
        for key, value in entries.items():
            if not isinstance(value, dict) or not isinstance(value.get("timestamp"), str):
                _fail("Invalid job cache timestamp.")
            timestamp = datetime.fromisoformat(value["timestamp"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None or timestamp > now + timedelta(seconds=60):
                _fail("Job cache timestamp is ambiguous or in the future.")
            if now - timestamp <= timedelta(days=days):
                current[key] = value
        return current
    except (OSError, ValueError, TypeError) as exc:
        if isinstance(exc, policy.PolicyError):
            raise
        _fail("Job cache is malformed or unavailable.")


def _flags(parts: list[str], family: str, action: str) -> dict:
    result = {}
    aliases = {"-i": "--job-id", "-w": "--wait", "-o": "--target-org", "-a": "--api-version",
               ("-l" if family == "sandbox" else "-r"): "--use-most-recent"}
    booleans = {"--json", "--use-most-recent"}
    if family == "deploy" and action in {"quick", "cancel"}:
        booleans.add("--async")
    values = {"--job-id", "--wait", "--target-org"}
    if family == "deploy" and action == "quick":
        values.add("--api-version")
    if family == "sandbox":
        values.add("--name")
        aliases["-n"] = "--name"
    index = 4
    while index < len(parts):
        flag, equals, value = parts[index].partition("=")
        flag = aliases.get(flag, flag)
        if flag in result:
            _fail("Duplicate job option; use exactly one value for each option.")
        if flag in booleans:
            if equals:
                _fail("Boolean job options must not contain a value.")
            result[flag] = True
        elif flag in values:
            if not equals:
                index += 1
                if index >= len(parts):
                    _fail("Missing job option value.")
                value = parts[index]
            if not value or value.startswith("-"):
                _fail("Missing or ambiguous job option value.")
            result[flag] = value
        else:
            _fail("Unsupported native job option; use job-id/latest, target-org, wait, json, and supported async/api-version options only.")
        index += 1
    selectors = [key for key in ("--job-id", "--use-most-recent", "--name") if key in result]
    if len(selectors) != 1:
        _fail("Select exactly one job ID, latest job, or supported sandbox name.")
    if "--async" in result and "--wait" in result:
        _fail("Async and wait are mutually exclusive.")
    if "--wait" in result:
        minimum = 0 if family == "sandbox" else 1
        if not re.fullmatch(r"[0-9]{1,4}", result["--wait"]) or not minimum <= int(result["--wait"]) <= 120:
            _fail("Native job wait must be an integer within the supported range (up to 120 minutes).")
    if "--api-version" in result and not re.fullmatch(r"[1-9][0-9]{1,2}\.0", result["--api-version"]):
        _fail("Unsupported API version.")
    return result


def select_job(parts: list[str], home: Path, rows: list[dict]) -> dict | None:
    """Freeze job/controller/options, or return None for a non-job command.

    The caller classifies every returned target and passes this snapshot to its
    policy check. Neither policy nor executor may reselect latest after a dialog.
    """
    parts = policy.canonical_command(parts)
    words = policy.command_words(parts)
    if words == ("org", "resume", "scratch"):
        _fail("Native scratch resume is not supported: the reviewed SDK reloads mutable Dev Hub/cache settings. Use a separately reviewed explicit lifecycle workflow.")
    if words in policy.JOB_COMMANDS:
        family, action, prefix, filename, days = "deploy", words[-1], "0Af", "deploy-cache.json", 3
    elif words == ("org", "resume", "sandbox"):
        family, action, prefix, filename, days = "sandbox", "resume", "0GR", "sandbox-create-cache.json", 14
    else:
        return None
    flags = _flags(parts, family, action)
    entries = _cache(home, filename, days)
    selected = None
    if flags.get("--use-most-recent"):
        if not entries:
            _fail("No current latest job is available.")
        # Sorting is stable, matching JS TTLConfig.getLatestEntry for equal times.
        selected = max(entries, key=lambda key: datetime.fromisoformat(entries[key]["timestamp"].replace("Z", "+00:00")))
    elif "--name" in flags:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,9}", flags["--name"]):
            _fail("Invalid sandbox name.")
        if flags["--name"] not in entries:
            _fail("Sandbox name has no current cached process ID; specify a concrete job ID.")
        selected = flags["--name"]
    else:
        supplied = flags["--job-id"]
        if not re.fullmatch(prefix + r"[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?", supplied):
            _fail("Invalid job ID for this command family.")
        matches = []
        for key, entry in entries.items():
            process = entry.get("sandboxProcessObject", {}) if family == "sandbox" else {}
            candidate = process.get("Id") if isinstance(process, dict) else None
            candidate = candidate if family == "sandbox" else key
            if isinstance(candidate, str) and candidate[:15] == supplied[:15]:
                matches.append(key)
        if len(matches) > 1:
            _fail("Multiple cache entries match this job ID.")
        selected = matches[0] if matches else None
    entry = entries[selected] if selected is not None else {}
    process = entry.get("sandboxProcessObject", {})
    if family == "sandbox" and not isinstance(process, dict):
        _fail("Invalid sandbox process cache entry.")
    job_id = (process.get("Id") if family == "sandbox" else selected) if selected is not None else flags.get("--job-id")
    if not isinstance(job_id, str) or not re.fullmatch(prefix + r"[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?", job_id):
        _fail("Selected cache entry has no valid concrete job ID.")
    if family == "deploy" and action == "resume" and not entry:
        _fail("Deploy resume requires a current cached job identity.")
    cached_target = entry.get("prodOrgUsername" if family == "sandbox" else "target-org")
    if entry and (not isinstance(cached_target, str) or not cached_target):
        _fail("Selected job has no controlling org identity.")
    target = cached_target or flags.get("--target-org")
    if not target:
        _fail("Specify the target org for this uncached explicit job.")
    identity = policy._identity(target, rows)
    if identity is None:
        _fail("Selected job's controlling org is not authenticated locally.")
    if "--target-org" in flags:
        explicit = policy._identity(flags["--target-org"], rows)
        if explicit is None or (explicit["id"], explicit["host"]) != (identity["id"], identity["host"]):
            _fail("Explicit target conflicts with the job's controlling org.")
    # Use bounded standard defaults rather than copying arbitrary cached flags,
    # manifests, directories, credentials or settings into the native operation.
    default_wait = 0 if family == "sandbox" or action == "report" else 33
    options = {"waitMinutes": int(flags.get("--wait", default_wait)),
               "async": flags.get("--async", False),
               "apiVersion": flags.get("--api-version"),
               "rest": entry.get("api") == "REST"}
    if "api" in entry and entry["api"] not in {"REST", "SOAP"}:
        _fail("Unrecognized cached metadata transport.")
    if options["async"]:
        options["waitMinutes"] = 0
    rewritten = [parts[0], *words, "--job-id", job_id, "--target-org", identity["username"]]
    if "--wait" in flags:
        rewritten += ["--wait", flags["--wait"]]
    for flag in ("--json", "--async"):
        if flags.get(flag):
            rewritten.append(flag)
    if options["apiVersion"]:
        rewritten += ["--api-version", options["apiVersion"]]
    return {"parts": rewritten, "targets": [identity["username"]],
            "job": {"family": family, "action": action, "jobId": job_id,
                    "username": identity["username"], "id": identity["id"], "host": identity["host"],
                    "options": options}}
