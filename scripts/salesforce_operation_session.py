"""Private, single-invocation protocol for the installed VS Code operation tool.

Only the native host may answer its dialogs. This program never grants reusable consent,
persists classification, executes a shell, or accepts an environment from model input.
The host consumes one execution description after clean EOF and dispatches it exactly once.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import secrets
import sys
import threading
from typing import Callable

try:
    from scripts import salesforce_operation_policy as policy
    from scripts.copilot_safety_hook import is_real_deploy_command, deploy_scope
    from scripts.verify_salesforce_org import is_allowed_salesforce_host
except ModuleNotFoundError:
    import salesforce_operation_policy as policy
    from copilot_safety_hook import is_real_deploy_command, deploy_scope
    from verify_salesforce_org import is_allowed_salesforce_host

MAX_LINE = 65_536
DIALOG_TIMEOUT = 300


class SessionError(ValueError):
    pass


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_request(request: object) -> list[str]:
    if not isinstance(request, dict) or set(request) != {"arguments"}:
        raise SessionError("Provide only Salesforce arguments; environment and approval are native user inputs.")
    args = request["arguments"]
    if not isinstance(args, list) or not 1 <= len(args) <= 128:
        raise SessionError("Provide one bounded Salesforce command as an argument array.")
    # Arguments go directly to a fixed executable with shell=False. Punctuation
    # within a query/value is data, not shell syntax; preserve ordinary SOQL.
    if any(not isinstance(arg, str) or not arg or len(arg) > 8192 or
           re.search(r"[\x00-\x1f]", arg) for arg in args):
        raise SessionError("Invalid Salesforce arguments.")
    if sum(len(arg) for arg in args) > 32768:
        raise SessionError("Command arguments are too large.")
    return policy.canonical_command(["sf", *args])


def _rows(rows: object) -> list[dict]:
    if not isinstance(rows, list) or not rows or len(rows) > 500:
        raise SessionError("No bounded authenticated org inventory is available.")
    result = []
    for row in rows:
        if not isinstance(row, dict) or not policy.ORG_ID.fullmatch(str(row.get("id", ""))):
            raise SessionError("Invalid authenticated org identity.")
        username, host, aliases = row.get("username"), row.get("host"), row.get("aliases")
        if (not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9@._+%=-]{1,254}", username)
                or not isinstance(host, str) or not is_allowed_salesforce_host(host)
                or not isinstance(aliases, list) or any(not isinstance(a, str) for a in aliases)):
            raise SessionError("Invalid authenticated org inventory.")
        result.append({"username": username, "id": row["id"][:15], "host": host.lower(), "aliases": sorted(aliases)})
    return sorted(result, key=lambda r: (r["username"], r["id"], r["host"]))


def identity(target: str, rows: list[dict]) -> dict:
    row = policy._identity(target, rows)
    if row is None:
        raise SessionError("Target identity is unavailable; authenticate or repair the alias before selecting an environment.")
    return row


class OperationSession:
    def __init__(self, root: Path, ask: Callable[[dict], dict], *, home: Path | None = None,
                 env: dict | None = None, inventory: Callable | None = None,
                 job_selector: Callable | None = None) -> None:
        self.root = root.resolve()
        self.home = Path.home() if home is None else home
        self.env = dict(os.environ if env is None else env)
        self.inventory = inventory or policy.local_authorizations
        self.ask = ask
        self.job_selector = job_selector
        self.used = False
        self.prompts: set[str] = set()

    def _reply(self, kind: str, *, values: list | None = None, **fields):
        prompt_id = secrets.token_hex(16)
        self.prompts.add(prompt_id)
        response = self.ask({"type": kind, "promptId": prompt_id, **fields})
        if (not isinstance(response, dict) or set(response) != {"promptId", "value"}
                or response["promptId"] != prompt_id or prompt_id not in self.prompts):
            raise SessionError("Invalid, expired or replayed native answer; no operation was authorized.")
        self.prompts.remove(prompt_id)
        value = response["value"]
        if value is None or (values is not None and value not in values):
            raise SessionError("Operation canceled or no valid native answer supplied.")
        return value

    def _state(self, rows: list[dict]) -> dict:
        paths = [self.root / "config/harness.local.json"]
        for base in (self.root, self.home):
            paths += [base / ".sf/config.json", base / ".sfdx/sfdx-config.json"]
        paths += [self.home / ".sf" / name for name in
                  ("deploy-cache.json", "scratch-create-cache.json", "sandbox-create-cache.json")]
        for row in rows:
            paths.append(self.home / ".sfdx" / (row["username"] + ".json"))
            paths += list((self.home / ".sfdx").glob(row["id"] + "*.sandbox.json"))
        state = {}
        for path in paths:
            if path.exists():
                if not path.is_file() or path.stat().st_size > policy.MAX_OUTPUT:
                    raise SessionError("Local identity/configuration state is invalid or oversized.")
                state[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                state[str(path)] = None
        return state

    def _choose_target(self, parts: list[str], rows: list[dict]) -> list[str]:
        words = policy.command_words(parts)
        hub = any(words[:len(prefix)] == prefix for prefix in policy.HUB_COMMANDS)
        flags = policy.HUB_FLAGS if hub else policy.TARGET_FLAGS
        if policy._targets(parts, flags):
            return parts
        defaults = policy._defaults(self.root, self.home, self.env, hub)
        if defaults:
            selected = [identity(value, rows) for value in defaults]
            if len({(r["id"], r["host"]) for r in selected}) != 1:
                raise SessionError("Conflicting default targets; explicitly select the intended org.")
            target = selected[0]["username"]
        else:
            items = [{**{k: r[k] for k in ("username", "id", "host")},
                      "label": ", ".join(r["aliases"]) or r["username"]} for r in rows]
            target = self._reply("selectOrg", values=[r["username"] for r in rows], items=items,
                                 arguments=parts[1:], purpose="Dev Hub" if hub else "Target org")
        return [*parts, "--target-dev-hub" if hub else "--target-org", target]

    def _targets(self, parts: list[str], rows: list[dict], selected: dict | None) -> list[dict]:
        words = policy.command_words(parts)
        hub = any(words[:len(prefix)] == prefix for prefix in policy.HUB_COMMANDS)
        values = policy._targets(parts, policy.TARGET_FLAGS)
        values += policy._targets(parts, policy.HUB_FLAGS if hub else policy.HUB_FLAGS - {"-v"})
        if selected:
            values += selected["targets"]
        if words in {("org", "delete", "sandbox"), ("org", "delete", "scratch")}:
            values += policy._delete_controllers(values, rows, self.home, words[-1] == "sandbox")
        unique = {}
        for value in values:
            row = identity(value, rows)
            unique[(row["id"], row["host"])] = row
        if not unique:
            raise SessionError("No authenticated operation target was selected.")
        return list(unique.values())

    def prepare(self, request: object) -> dict:
        if self.used:
            raise SessionError("This native invocation has already been consumed.")
        self.used = True  # an error/cancel cannot be retried as a continuation
        parts = validate_request(request)
        if policy.command_words(parts) not in policy.KNOWN_COMMANDS:
            raise SessionError("This tool accepts reviewed org operations only.")
        if policy.command_words(parts) in {("org", "delete", "sandbox"), ("org", "delete", "scratch")}:
            # Generic CLI Org.delete() resolves its parent/Dev Hub again from mutable auth
            # relations. Pinning only the child username cannot bind that controller.
            # Existing direct-terminal policy is unchanged; no private delete adapter exists.
            raise SessionError("Native lifecycle deletion is unavailable: the CLI reloads the controlling org relation. No operation was authorized.")
        config_path = self.root / "config/harness.local.json"
        rows = _rows(self.inventory(self.root, self.env))
        before = self._state(rows)
        config = policy._read_json(config_path)
        if before != self._state(rows):
            raise SessionError("Configuration changed while loading; start a new assessment.")
        selected = None
        if self.job_selector is None:
            try:
                from scripts.salesforce_job_selection import select_job
            except ModuleNotFoundError:
                from salesforce_job_selection import select_job
        else:
            select_job = self.job_selector
        selected = select_job(parts, self.home, rows)
        if selected:
            parts = list(selected["parts"])
        else:
            parts = self._choose_target(parts, rows)
        targets = self._targets(parts, rows, selected)
        overlay = copy.deepcopy(config)
        overlay_rows = copy.deepcopy(rows)
        selected_envs = {}
        keywords = {}
        if selected:
            words = policy.command_words(parts)
            keywords["lifecycle_target" if words[:2] == ("org", "resume") else "job_target"] = selected["job"]["username"]

        # Config validation, conflicts, denied IDs and known production run BEFORE a dialog.
        while True:
            decision = policy.evaluate(parts, self.root, config=overlay, env=self.env, home=self.home,
                                       inventory=lambda *_: overlay_rows, **keywords)
            if decision.allowed:
                break
            if decision.status != "environment-required":
                raise SessionError(decision.reason)
            candidates = [r for r in targets if r["id"] == decision.organization_id]
            if len(candidates) != 1 or decision.organization_id in selected_envs:
                raise SessionError("Ambiguous or repeated environment classification.")
            row = candidates[0]
            environments = list(policy.ENVIRONMENTS)
            environment = self._reply("environment", values=environments,
                                      target={k: row[k] for k in ("username", "id", "host")},
                                      arguments=parts[1:], environments=environments)
            selected_envs[row["id"]] = environment
            alias = "native-" + row["id"]
            for item in overlay_rows:
                if item["id"] == row["id"] and item["host"] == row["host"]:
                    item["aliases"].append(alias)
            overlay["salesforce"]["orgs"].append({"alias": alias, "environment": environment,
                "expectedOrganizationId": row["id"], "expectedInstanceHost": row["host"]})

        # Replace mutable spellings/defaults with the assessed explicit usernames.
        words = policy.command_words(parts)
        hub = any(words[:len(prefix)] == prefix for prefix in policy.HUB_COMMANDS)
        target_flags = policy.TARGET_FLAGS | (policy.HUB_FLAGS if hub else policy.HUB_FLAGS - {"-v"})
        pinned = list(parts)
        for i, part in enumerate(pinned):
            name, eq, value = part.partition("=")
            if name in target_flags:
                spelling = value if eq else pinned[i + 1]
                username = identity(spelling, rows)["username"]
                if eq:
                    pinned[i] = name + "=" + username
                else:
                    pinned[i + 1] = username
        assessed_targets = []
        for row in targets:
            d = policy.classify_target(row["username"], overlay["salesforce"]["orgs"], overlay_rows)
            if d.status != "resolved":
                raise SessionError(d.reason)
            assessed_targets.append({**{k: row[k] for k in ("username", "id", "host")}, "environment": d.environment})
        if is_real_deploy_command(pinned):
            answer = self._reply("confirmDeploy", targets=assessed_targets, arguments=pinned[1:], scope=deploy_scope(pinned))
            if answer is not True:
                raise SessionError("Deployment was not confirmed.")
        after_rows = _rows(self.inventory(self.root, self.env))
        if rows != after_rows or before != self._state(after_rows):
            raise SessionError("Identity or configuration/cache changed during the operation; start a new assessment.")
        execution = {"kind": "job" if selected else "cli", "arguments": pinned[1:],
                     "targets": assessed_targets,
                     "configDigest": before[str(config_path)]}
        if selected:
            execution["job"] = copy.deepcopy(selected["job"])
        return {"type": "execute", "execution": execution, "digest": digest(execution)}


def read_line(stream, timeout: float = DIALOG_TIMEOUT) -> dict:
    result: queue.Queue = queue.Queue(maxsize=1)
    def read():
        try:
            result.put(stream.readline(MAX_LINE + 1))
        except Exception:
            result.put(None)
    threading.Thread(target=read, daemon=True).start()
    try:
        line = result.get(timeout=timeout)
    except queue.Empty:
        raise SessionError("Native dialog timed out; no operation was authorized.") from None
    if not isinstance(line, str) or not line.endswith("\n") or len(line.encode()) > MAX_LINE:
        raise SessionError("Native host canceled or sent invalid protocol input.")
    try:
        return json.loads(line)
    except (ValueError, TypeError):
        raise SessionError("Malformed native protocol input.") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    def emit(event):
        print(json.dumps(event, ensure_ascii=True), flush=True)
    def ask(event):
        emit(event)
        return read_line(sys.stdin)
    try:
        root = Path(args.workspace).resolve(strict=True)
        if not (root / "sfdx-project.json").is_file():
            raise SessionError("Select one trusted Salesforce workspace.")
        session = OperationSession(root, ask)
        emit(session.prepare(read_line(sys.stdin)))
        return 0
    except (SessionError, policy.PolicyError, OSError, ValueError, KeyError, TypeError):
        # No exception traceback/CLI output can leak credentials across the model boundary.
        message = str(sys.exception()) if isinstance(sys.exception(), (SessionError, policy.PolicyError)) else "Native operation could not be verified."
        emit({"type": "blocked", "message": message})
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
