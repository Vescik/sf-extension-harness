"""Salesforce channel policy. No evaluated operation is executed and no consent is stored.

Identity inventory is a fixed local CLI transport, never a model-supplied command. It is
not live Salesforce proof (the read MCP retains that responsibility). Each decision reloads
config, defaults and authorizations. Host execution/approval binding still needs Local QA.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Mapping

try:
    from scripts.verify_salesforce_org import ALIAS, ORG_ID, parse_org_display
except ModuleNotFoundError:
    from verify_salesforce_org import ALIAS, ORG_ID, parse_org_display

ENVIRONMENTS = ("dev", "uat", "stage", "prod")
LEGACY_ENVIRONMENTS = {"development": "dev", "production": "prod"}
IDENTITY_TIMEOUT = 2.0  # below both the 5s role hook and 10s safety hook budgets
MAX_OUTPUT = 1_000_000


def normalize_environment(value: object) -> str:
    if isinstance(value, str) and value in LEGACY_ENVIRONMENTS:
        return LEGACY_ENVIRONMENTS[value]
    if value in ENVIRONMENTS:
        return str(value)
    if value == "qa":
        raise ValueError("legacy qa requires an explicit dev/uat/stage/prod assignment for this org")
    raise ValueError("environment must be dev, uat, stage or prod")


@dataclass(frozen=True)
class Decision:
    status: str
    reason: str
    environment: str | None = None
    organization_id: str | None = None

    @property
    def allowed(self) -> bool:
        return self.status == "allow"


class PolicyError(ValueError):
    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status = status


def _read_json(path: Path, optional: bool = False) -> dict:
    try:
        if optional and not path.exists():
            return {}
        if not path.is_file() or path.stat().st_size > MAX_OUTPUT:
            raise ValueError()
        result = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (OSError, ValueError):
        raise PolicyError("config-error", "Missing, malformed or oversized local configuration.") from None


def local_authorizations(root: Path, env: Mapping[str, str], *, runner=None) -> list[dict]:
    """Fixed local-only auth inventory; never log raw stdout/stderr or token fields."""
    path = env.get("PATH", "")
    if os.name != "nt":
        path = os.pathsep.join([path, "/usr/local/bin", "/opt/homebrew/bin"])
    executable = shutil.which("sf", path=path)
    if not executable:
        raise PolicyError("identity-error", "Salesforce CLI identity inventory is unavailable.")
    child_env = dict(env)
    child_env["PATH"] = path
    child_env.update({"FORCE_COLOR": "0", "NO_COLOR": "1", "CLICOLOR": "0", "CLICOLOR_FORCE": "0"})
    child_env["SF_TEMP_SHOW_SECRETS"] = "false"
    child_env["SF_AUTOUPDATE_DISABLE"] = "true"
    child_env["SF_DISABLE_TELEMETRY"] = "true"
    try:
        result = (runner or subprocess.run)(
            [executable, "org", "list", "auth", "--json"], cwd=root, env=child_env,
            capture_output=True, text=True, timeout=IDENTITY_TIMEOUT, check=False,
        )
        if result.returncode or len(result.stdout) > MAX_OUTPUT:
            raise ValueError()
        payload = json.loads(result.stdout)
        rows = payload["result"]
        if payload.get("status") != 0 or not isinstance(rows, list) or len(rows) > 500:
            raise ValueError()
        clean = []
        for row in rows:
            if not isinstance(row, dict) or row.get("error"):
                raise ValueError()
            identity = parse_org_display(json.dumps({"status": 0, "result": {
                "orgId": row.get("orgId"), "instanceUrl": row.get("instanceUrl")
            }}), allow_production=True)
            username = row.get("username")
            aliases = row.get("alias", "")
            if identity is None or not isinstance(username, str) or not username or not isinstance(aliases, str):
                raise ValueError()
            clean.append({"username": username, "aliases": aliases.split(",") if aliases else [],
                          "id": identity[1][:15], "host": identity[0]})
        return clean
    except subprocess.TimeoutExpired:
        raise PolicyError("identity-timeout", "Local identity inventory timed out; operation was not authorized.") from None
    except (OSError, ValueError, KeyError, TypeError):
        raise PolicyError("identity-error", "Local identity inventory failed; operation was not authorized.") from None


TARGET_FLAGS = {"--target-org", "-o", "--targetusername", "--username", "-u"}
HUB_FLAGS = {"--target-dev-hub", "-v", "--targetdevhubusername"}
# These command families can use Dev Hub defaults. Evaluate both when a command names both.
HUB_COMMANDS = (("package", "create"), ("package", "version"), ("package", "delete"),
                ("package", "update"), ("package", "list"), ("org", "create", "scratch"),
                )
RETRIEVE_COMMANDS = (("project", "retrieve", "start"), ("retrieve", "metadata"))
RETRIEVE_BOOL = {"--json", "--ignore-conflicts", "-c", "--single-package", "--unzip", "-z"}
RETRIEVE_VALUES = {"--target-org", "-o", "--api-version", "-a", "--manifest", "-x",
                   "--output-dir", "-r", "--wait", "-w", "--target-metadata-dir", "-t", "--zip-file-name"}
RETRIEVE_MULTI = {"--source-dir", "-d", "--metadata", "-m", "--package-name", "-n"}


def command_words(parts: list[str]) -> tuple[str, ...]:
    words = []
    for token in parts[1:]:
        if token.startswith("-"):
            break
        words.append(token)
    return tuple(words)


def is_retrieve(parts: list[str], *, nonprod: bool = False) -> bool:
    """Reviewed retrieve grammar; production flags stay narrower than CLI 2.151.7 nonprod."""
    words = command_words(parts)
    if words not in RETRIEVE_COMMANDS:
        return False
    args = parts[1 + len(words):]
    multi = RETRIEVE_MULTI | ({"--root-type-with-dependencies"} if nonprod else set())
    i = 0
    while i < len(args):
        flag, sep, value = args[i].partition("=")
        if flag in RETRIEVE_BOOL:
            if sep:  # do not infer boolean semantics
                return False
        elif flag in RETRIEVE_VALUES | multi:
            if sep:
                if not value:
                    return False
                values = [value]
            else:
                i += 1
                if i >= len(args) or args[i].startswith("-"):
                    return False
                start = i
                if flag in multi:
                    while i + 1 < len(args) and not args[i + 1].startswith("-"):
                        i += 1
                values = args[start:i + 1]
            if flag == "--root-type-with-dependencies" and any(v not in {"Bot", "AiAgentDefinitionVersion"} for v in values):
                return False
        else:
            return False
        i += 1
    return True


# Closed set of understood org-facing command paths. New plugin commands need review.
KNOWN_COMMANDS = set(RETRIEVE_COMMANDS) | {tuple(x.split()) for x in (
    "project delete source",
    "project delete tracking",
    "project reset tracking",
    "org enable tracking",
    "org disable tracking",
    "org list metadata",
    "org list metadata-types",
    "org list sobject record-counts",
    "org refresh sandbox",
    "data search",
    "data create file",
    "data update bulk",
    "data bulk results",
    "force:data:bulk:status",
    "apex tail log",
    "logic run test",
    "logic get test",
    "package install report",
    "package uninstall report",
    "package version create list",
    "package version create report",
    "project deploy start", "project deploy validate", "project deploy quick",
    "project deploy report", "project deploy resume", "project deploy cancel", "deploy metadata",
    "project deploy preview", "project retrieve preview", "deploy metadata preview", "retrieve metadata preview",
    "data query", "data get record", "data create record", "data update record", "data delete record",
    "data upsert bulk", "data delete bulk", "data import tree", "data export tree",
    "data import bulk", "data export bulk", "data resume", "sobject describe", "sobject list",
    "org display", "org limits", "limits api display", "org list limits", "org assign permset",
    "org assign permsetlicense", "org remove permset", "org create scratch", "org delete scratch",
    "org create sandbox", "org delete sandbox", "org resume scratch", "org resume sandbox",
    "package install", "package uninstall", "package installed list", "package create", "package list",
    "package delete", "package update", "package version create", "package version list",
    "package version report", "package version promote", "package version delete", "package version update",
    "apex run", "apex run test", "apex get test", "apex get log", "apex list log",
    "force:source:deploy", "force:mdapi:deploy", "force:source:delete", "force:apex:execute",
    "force:apex:test:run", "force:data:soql:query", "force:schema:sobject:describe",
    "force:data:record:create", "force:data:record:update", "force:data:record:delete",
    "force:data:record:get", "force:data:bulk:upsert", "force:data:bulk:delete",
    "force:package:install", "force:package:uninstall", "force:org:display",
    "force:user:permset:assign",
)}
# CLI 2.151.7 manifest aliases, reviewed against the same command implementations.
# Static map: installing a plugin never grants another command. No argv is rewritten at
# execution; these are CLI-equivalent spellings used only for policy classification.
REGISTERED_COMMANDS = {
    'apex get log': 'apex:get:log force:apex:log:get',
    'apex get test': 'apex:get:test force:apex:test:report',
    'apex list log': 'apex:list:log force:apex:log:list',
    'apex run': 'apex:run force:apex:execute',
    'apex run test': 'apex:run:test force:apex:test:run',
    'apex tail log': 'apex:tail:log force:apex:log:tail',
    'data bulk results': 'data:bulk:results',
    'data create file': 'data:create:file',
    'data create record': 'data:create:record force:data:record:create',
    'data delete bulk': 'data:delete:bulk',
    'data delete record': 'data:delete:record force:data:record:delete',
    'data export bulk': 'data:export:bulk',
    'data export tree': 'data:export:tree force:data:tree:export',
    'data get record': 'data:get:record force:data:record:get',
    'data import bulk': 'data:import:bulk',
    'data import tree': 'data:import:tree force:data:tree:import',
    'data query': 'data:query force:data:soql:query',
    'data resume': 'data:resume',
    'data search': 'data:search',
    'data update bulk': 'data:update:bulk',
    'data update record': 'data:update:record force:data:record:update',
    'data upsert bulk': 'data:upsert:bulk',
    'force:data:bulk:delete': 'force:data:bulk:delete',
    'force:data:bulk:status': 'force:data:bulk:status',
    'force:data:bulk:upsert': 'force:data:bulk:upsert',
    'force:user:permset:assign': 'force:user:permset:assign',
    'logic get test': 'logic:get:test',
    'logic run test': 'logic:run:test',
    'org assign permset': 'org:assign:permset',
    'org assign permsetlicense': 'org:assign:permsetlicense',
    'org create sandbox': 'env:create:sandbox org:create:sandbox',
    'org create scratch': 'env:create:scratch org:create:scratch',
    'org delete sandbox': 'env:delete:sandbox org:delete:sandbox',
    'org delete scratch': 'env:delete:scratch org:delete:scratch',
    'org disable tracking': 'org:disable:tracking',
    'org display': 'force:org:display org:display',
    'org enable tracking': 'org:enable:tracking',
    'org list limits': 'force:limits:api:display limits:api:display org:list:limits',
    'org list metadata': 'force:mdapi:listmetadata org:list:metadata',
    'org list metadata-types': 'force:mdapi:describemetadata org:list:metadata-types',
    'org list sobject record-counts': 'force:limits:recordcounts:display limits:recordcounts:display org:list:sobject:record-counts',
    'org refresh sandbox': 'org:refresh:sandbox',
    'org resume sandbox': 'env:resume:sandbox org:resume:sandbox',
    'org resume scratch': 'env:resume:scratch org:resume:scratch',
    'package create': 'force:package:create package:create',
    'package delete': 'force:package:delete package:delete',
    'package install': 'force:package:install package:install',
    'package install report': 'force:package:install:report package:install:report',
    'package installed list': 'force:package:installed:list package:installed:list',
    'package list': 'force:package:list package:list',
    'package uninstall': 'force:package:uninstall package:uninstall',
    'package uninstall report': 'force:package:uninstall:report package:uninstall:report',
    'package update': 'force:package:update package:update',
    'package version create': 'force:package:version:create package:version:create',
    'package version create list': 'force:package:version:create:list package:version:create:list',
    'package version create report': 'force:package:version:create:report package:version:create:report',
    'package version delete': 'force:package:version:delete package:version:delete',
    'package version list': 'force:package:version:list package:version:list',
    'package version promote': 'force:package:version:promote package:version:promote',
    'package version report': 'force:package:version:report package:version:report',
    'package version update': 'force:package:version:update package:version:update',
    'project delete source': 'force:source:delete project:delete:source',
    'project delete tracking': 'force:source:tracking:clear project:delete:tracking',
    'project deploy cancel': 'deploy:metadata:cancel project:deploy:cancel',
    'project deploy preview': 'deploy:metadata:preview project:deploy:preview',
    'project deploy quick': 'deploy:metadata:quick project:deploy:quick',
    'project deploy report': 'deploy:metadata:report project:deploy:report',
    'project deploy resume': 'deploy:metadata:resume project:deploy:resume',
    'project deploy start': 'deploy:metadata project:deploy:start',
    'project deploy validate': 'deploy:metadata:validate project:deploy:validate',
    'project reset tracking': 'force:source:tracking:reset project:reset:tracking',
    'project retrieve preview': 'project:retrieve:preview retrieve:metadata:preview',
    'project retrieve start': 'project:retrieve:start retrieve:metadata',
    'sobject describe': 'force:schema:sobject:describe sobject:describe',
    'sobject list': 'force:schema:sobject:list sobject:list',
}
COMMAND_ALIASES = {
    alias: tuple(canonical.split())
    for canonical, spellings in REGISTERED_COMMANDS.items()
    for spelling in spellings.split()
    for alias in {(spelling,), tuple(spelling.split(":"))}
    if alias != tuple(canonical.split())
}



def canonical_command(parts: list[str]) -> list[str]:
    words = command_words(parts)
    canonical = COMMAND_ALIASES.get(words, words)
    return [parts[0], *canonical, *parts[1 + len(words):]] if parts else []


JOB_COMMANDS = {("project", "deploy", name) for name in ("quick", "report", "resume", "cancel")}


def _current_cache(path: Path, days: int) -> dict:
    """Read the installed CLI's TTL format; never return expired evidence or raw errors."""
    current = {}
    for key, entry in _read_json(path, optional=True).items():
        if not isinstance(entry, dict):
            raise PolicyError("identity-error", "Malformed lifecycle cache entry.")
        try:
            timestamp = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - timestamp <= timedelta(days=days):
                current[key] = entry
        except (KeyError, TypeError, ValueError):
            raise PolicyError("identity-error", "Malformed lifecycle cache timestamp.") from None
    return current


def _relation_target(entry: dict, key: str) -> str:
    target = entry.get(key)
    if not isinstance(target, str) or not target.strip():
        raise PolicyError("unresolved", "Lifecycle controlling org is not bound; no operation authorized.")
    return target


def _resume_target(parts: list[str], home: Path, sandbox: bool) -> str | None:
    # Do not authorize a changing selector from a snapshot. The host has not proved
    # that updatedInput binds a rewritten concrete ID to the actual execution.
    recent_flag = "-l" if sandbox else "-r"
    if any(p.split("=", 1)[0] in {"--use-most-recent", recent_flag} for p in parts):
        raise PolicyError("unresolved", "Use a concrete lifecycle job ID; most-recent is not bound to execution.")
    jobs = _targets(parts, {"--job-id", "-i"})
    names = _targets(parts, {"--name", "-n"}) if sandbox else []
    prefix = "0GR" if sandbox else "2SR"
    if len(jobs) + len(names) != 1 or (jobs and not re.fullmatch(prefix + r"[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?", jobs[0])):
        raise PolicyError("unresolved", "Select exactly one valid lifecycle job ID or sandbox name.")
    cache = _current_cache(home / ".sf" / ("sandbox-create-cache.json" if sandbox else "scratch-create-cache.json"), 14 if sandbox else 1)
    matches = []
    for key, entry in cache.items():
        if sandbox:
            process = entry.get("sandboxProcessObject", {})
            if not isinstance(process, dict):
                raise PolicyError("identity-error", "Malformed sandbox process identity.")
            match = (names and key == names[0]) or (jobs and str(process.get("Id", ""))[:15] == jobs[0][:15])
        else:
            match = key[:15] == jobs[0][:15]
        if match:
            matches.append(_relation_target(entry, "prodOrgUsername" if sandbox else "hubUsername"))
    if len(matches) > 1:
        raise PolicyError("conflict", "Multiple lifecycle cache entries match this operation.")
    if matches:
        return matches[0]
    if not sandbox:
        raise PolicyError("unresolved", "Scratch resume requires current cached Dev Hub identity.")
    # Sandbox CLI explicitly falls back to --target-org when the cache misses.
    return None


def _delete_controllers(targets: list[str], rows: list[dict], home: Path, sandbox: bool) -> list[str]:
    """Resolve local relationships without querying/mutating the child or parent org."""
    controllers = []
    for target in targets:
        row = _identity(target, rows)
        if row is None:
            raise PolicyError("unresolved", "Lifecycle child identity is unresolved.")
        username = row["username"]
        if not isinstance(username, str) or any(c in username for c in '/\\\x00') or username in {".", ".."}:
            raise PolicyError("identity-error", "Unsafe lifecycle authorization locator.")
        auth = _read_json(home / ".sfdx" / (username + ".json"))
        # Auth is read only to extract bounded identity/relation fields. No credential
        # fields, full filenames, or raw JSON enter a decision or log.
        if auth.get("username") != username or not ORG_ID.fullmatch(str(auth.get("orgId", ""))) or auth["orgId"][:15] != row["id"]:
            raise PolicyError("identity-error", "Lifecycle authorization identity changed.")
        relation_paths = list((home / ".sfdx").glob(row["id"] + "*.sandbox.json"))
        if len(relation_paths) > 1:
            raise PolicyError("conflict", "Ambiguous sandbox parent evidence.")
        if relation_paths:
            path = relation_paths[0]
            if not ORG_ID.fullmatch(path.name.removesuffix(".sandbox.json")):
                raise PolicyError("identity-error", "Malformed sandbox identity locator.")
            controllers.append(_relation_target(_read_json(path), "prodOrgUsername"))
        elif sandbox:
            raise PolicyError("unresolved", "Sandbox parent evidence is missing.")
        # Org.delete can choose sandbox even under `delete scratch`. Check the
        # scratch relation too if present, never trust the subcommand as lineage.
        if not sandbox:
            if auth.get("isScratch") is not True:
                raise PolicyError("unresolved", "Scratch identity is not proven locally.")
            controllers.append(_relation_target(auth, "devHubUsername"))
    return controllers


def _job_target(parts: list[str], home: Path) -> str | None:
    """CLI deploy cache wins over -o, including report/quick (verified CLI source)."""
    job_ids = _targets(parts, {"--job-id", "-i"})
    recent = any(p.split("=", 1)[0] in {"--use-most-recent", "-r"} for p in parts)
    if recent:
        # The latest job may change during host confirmation. Require its stable ID.
        raise PolicyError("unresolved", "Use an explicit deploy job ID; most-recent job is not bound to this operation.")
    if len(job_ids) != 1 or not re.fullmatch(r"0Af[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?", job_ids[0]):
        raise PolicyError("unresolved", "An explicit valid deploy job ID is required.")
    cache = _read_json(home / ".sf/deploy-cache.json", optional=True)
    matched = []
    for key, value in cache.items():
        if key[:15] != job_ids[0][:15]:
            continue
        if not isinstance(value, dict) or not isinstance(value.get("target-org"), str):
            raise PolicyError("identity-error", "Deploy job target evidence is malformed.")
        try:
            timestamp = datetime.fromisoformat(value["timestamp"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - timestamp > timedelta(days=3):
                continue
        except (KeyError, ValueError, TypeError):
            raise PolicyError("identity-error", "Deploy job timestamp is malformed.") from None
        matched.append(value["target-org"])
    if len(set(matched)) > 1:
        raise PolicyError("conflict", "Deploy job has conflicting target evidence.")
    if not matched and command_words(parts) == ("project", "deploy", "resume"):
        raise PolicyError("unresolved", "Resume requires a bound, current deploy-cache identity.")
    return matched[0] if matched else None


def _targets(parts: list[str], flags: set[str]) -> list[str]:
    values = []
    for index, part in enumerate(parts):
        flag, eq, val = part.partition("=")
        if flag in flags:
            if not eq:
                val = parts[index + 1] if index + 1 < len(parts) else ""
            if not val or val.startswith("-"):
                raise PolicyError("conflict", "Target flag has no unambiguous value.")
            values.append(val)
        elif any(part.startswith(f) and len(part) > 2 for f in flags if len(f) == 2):
            raise PolicyError("conflict", "Use a separate value for short target flags.")
    return values


def _defaults(root: Path, home: Path, env: Mapping[str, str], hub: bool) -> list[str]:
    modern, legacy = ("target-dev-hub", "defaultdevhubusername") if hub else ("target-org", "defaultusername")
    env_names = ("SF_TARGET_DEV_HUB", "SFDX_DEFAULTDEVHUBUSERNAME") if hub else ("SF_TARGET_ORG", "SFDX_DEFAULTUSERNAME")
    groups = [[env.get(name) for name in env_names]]
    for directory in (root, home):
        sf = _read_json(directory / ".sf/config.json", optional=True)
        sfdx = _read_json(directory / ".sfdx/sfdx-config.json", optional=True)
        groups.append([sf.get(modern), sf.get(legacy), sfdx.get(legacy), sfdx.get(modern)])
    for group in groups:
        if any(x is not None and not isinstance(x, str) for x in group):
            raise PolicyError("config-error", "Default target must be a string.")
        values = list(dict.fromkeys(x for x in group if x))
        if values:
            # Resolve every spelling in the winning precedence tier. Two aliases or a
            # username can refer to one identity; different Org IDs still fail closed.
            return values
    return []


def _identity(target: str, rows: list[dict]) -> dict | None:
    matches = [r for r in rows if target == r["username"] or target in r["aliases"]
               or (ORG_ID.fullmatch(target) and target[:15] == r["id"])]
    identities = {(r["id"], r["host"]) for r in matches}
    if len(identities) > 1:
        raise PolicyError("conflict", "Target resolves to conflicting authorized identities.")
    return matches[0] if matches else None


def classify_target(target: str, entries: list[dict], rows: list[dict]) -> Decision:
    identity = _identity(target, rows)
    if identity is None:
        return Decision("identity-unresolved", "Target identity is not proven. Resolve the authentication/alias identity before asking about environment; an environment answer cannot authorize this operation.")
    matches = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not ALIAS.fullmatch(str(entry.get("alias", ""))):
            raise PolicyError("config-error", f"Invalid salesforce.orgs[{index}].alias.")
        pin = entry.get("expectedOrganizationId")
        host = entry.get("expectedInstanceHost")
        if (pin is None) != (host is None) or (pin is not None and not ORG_ID.fullmatch(str(pin))):
            raise PolicyError("config-error", f"Invalid identity pins at salesforce.orgs[{index}].")
        bound = _identity(entry["alias"], rows)
        relevant = entry["alias"] == target or (pin and pin[:15] == identity["id"]) or (bound and bound["id"] == identity["id"])
        if not relevant:
            # An unpinned, unavailable production alias could hide this very identity.
            if bound is None and pin is None:
                raise PolicyError("identity-error", f"Cannot bind unpinned salesforce.orgs[{index}] to an identity.")
            continue
        if bound is None or (pin and (pin[:15] != bound["id"] or str(host).lower() != bound["host"])):
            raise PolicyError("identity-error", f"Identity changed or unavailable at salesforce.orgs[{index}].")
        try:
            matches.append(normalize_environment(entry.get("environment")))
        except (ValueError, TypeError):
            raise PolicyError("migration-required", f"salesforce.orgs[{index}].environment: explicitly assign dev/uat/stage/prod (legacy qa has no automatic mapping).") from None
    if len(set(matches)) > 1:
        raise PolicyError("conflict", "The same Org ID has conflicting environment classifications.")
    if not matches:
        return Decision("environment-required", f"Authenticated Org ID {identity['id']} has no environment classification. Use the installed native Salesforce operation tool to ask the user: dev, uat, stage or prod for this exact displayed command and arguments only. Do not change configuration or reuse the answer. Terminal execution cannot consume this native answer.", organization_id=identity["id"])
    return Decision("resolved", "Target classified by authorized Org ID.", matches[0], identity["id"])


def evaluate(parts: list[str], root: Path, *, config: dict | None = None,
             env: Mapping[str, str] | None = None, home: Path | None = None,
             inventory=None, job_target: str | None = None,
             lifecycle_target: str | None = None) -> Decision:
    """Caller already enforces a plain single command and role. Fail closed on every error."""
    try:
        if parts and "/" in parts[0].replace("\\", "/"):
            executable = Path(parts[0].replace("\\", "/"))
            trusted = shutil.which(executable.name)
            candidate = executable if executable.is_absolute() else root / executable
            if not trusted or candidate.resolve() != Path(trusted).resolve():
                return Decision("deny", "Salesforce executable path is not the installed CLI; wrappers are forbidden.")
        if len(parts) < 2:
            return Decision("deny", "Specify a concrete Salesforce command.")
        # Exact local help/version forms do not resolve/contact an org.
        if parts[1:] in (["--version"], ["version"], ["--help"], ["-h"]):
            return Decision("allow", "Local CLI help/version.")
        if parts[-1] in {"--help", "-h"} and all(re.fullmatch(r"[a-z][a-z:-]*", p) for p in parts[1:-1]):
            return Decision("allow", "Local command help.")
        if any(p == "--flags-dir" or p.startswith("--flags-dir=") for p in parts):
            return Decision("deny", "Flag files can change the assessed target and scope; use explicit arguments.")
        parts = canonical_command(parts)
        cfg = config if config is not None else _read_json(root / "config/harness.local.json")
        entries = cfg["salesforce"]["orgs"]
        if not isinstance(entries, list):
            raise PolicyError("config-error", "salesforce.orgs must be an array.")
        aliases = [e.get("alias") for e in entries if isinstance(e, dict)]
        if len(aliases) != len(set(aliases)):
            raise PolicyError("conflict", "Duplicate configured org alias.")
        effective_env = os.environ if env is None else env
        effective_home = Path.home() if home is None else home
        targets = _targets(parts, TARGET_FLAGS)
        words = command_words(parts)
        if words not in KNOWN_COMMANDS:
            return Decision("deny", "Unknown or unverified Salesforce command semantics; no operation authorized.")
        if words in RETRIEVE_COMMANDS and not is_retrieve(parts, nonprod=True):
            return Decision("deny", "Unverified retrieve flags or argument form.")
        if words in JOB_COMMANDS:
            # Native execution may supply the privately resolved immutable job binding.
            # No CLI flag or model input reaches these parameters.
            cached_target = job_target if job_target is not None else _job_target(parts, effective_home)
            if cached_target:
                targets.append(cached_target)
        if words in {("org", "resume", "sandbox"), ("org", "resume", "scratch")}:
            cached_target = lifecycle_target if lifecycle_target is not None else _resume_target(parts, effective_home, words[-1] == "sandbox")
            if cached_target:
                targets.append(cached_target)
        is_hub = any(words[:len(prefix)] == prefix for prefix in HUB_COMMANDS)
        hubs = _targets(parts, HUB_FLAGS if is_hub else HUB_FLAGS - {"-v"})
        if not targets and not is_hub and not hubs:
            targets = _defaults(root, effective_home, effective_env, False)
        if is_hub and not hubs:
            hubs = _defaults(root, effective_home, effective_env, True)
            if not hubs:
                return Decision("unresolved", "Dev Hub target is unresolved; no operation authorized.")
        if not targets and not hubs:
            return Decision("unresolved", "No target/default is resolved. Ask the user to identify this operation's org and environment; do not execute.")
        rows = (inventory or local_authorizations)(root, effective_env)
        controllers = []
        if words in {("org", "delete", "sandbox"), ("org", "delete", "scratch")}:
            controllers = _delete_controllers(targets, rows, effective_home, words[-1] == "sandbox")
        decisions = [classify_target(t, entries, rows) for t in targets + hubs + controllers]
        denied = cfg["salesforce"].get("review", {}).get("deniedOrganizationIds", [])
        if not isinstance(denied, list) or any(not ORG_ID.fullmatch(str(x)) for x in denied):
            return Decision("config-error", "Invalid deniedOrganizationIds configuration.")
        if any(d.organization_id in {str(x)[:15] for x in denied} for d in decisions):
            return Decision("deny", "Org ID is denied by existing local policy.")
        # Multiple spellings are permitted only if they identify the exact same org per lane.
        for lane in (decisions[:len(targets)], decisions[len(targets):len(targets) + len(hubs)]):
            if len({d.organization_id for d in lane}) > 1:
                return Decision("conflict", "Conflicting explicit target identities.")
        for d in decisions:
            if d.environment == "prod" and (hubs or not is_retrieve(parts)):
                return Decision("deny", "Production CLI permits only verified metadata retrieve. Use existing read-only Salesforce MCP tools for other reads. Confirmation cannot override this denial.", "prod", d.organization_id)
        for d in decisions:
            if d.status != "resolved":
                return d
        # Unknown retrieve lookalikes never gain a production exception above.
        return Decision("allow", "Configured environment permits the operation under existing role/deploy rules.", decisions[0].environment, decisions[0].organization_id)
    except PolicyError as exc:
        return Decision(exc.status, str(exc))
    except Exception:
        return Decision("identity-error", "Salesforce policy evaluation failed; operation was not authorized.")
