#!/usr/bin/env python3
"""Read-only, non-production-only Salesforce review facade (single REST transport).

Python rewrite of the retired dual-transport .mjs facade per
docs/plan-2026-08-09-salesforce-mcp-rest-rewrite.md. The model never receives a
command string, an org alias it did not configure, a raw token, or an unbounded
vendor response. One allowlisted non-production alias is bound at startup: the
Salesforce CLI is invoked a fixed number of times ONCE per server session (version
gate, access token, org display), the org's non-production identity is proven live
and frozen, and every subsequent tool call is a single HTTPS request over a pooled
session — no child processes per call, no per-call identity round-trips.

Hard walls (enforced here, not by prompts):
- Startup refuses to run against anything but a sandbox/scratch/Developer Edition
  host shape whose org id passes the configured pins and denied-list; the proven
  identity is frozen for the session and re-proven live after every 401 token
  refresh. An identity mismatch after refresh fail-closes the whole session.
- Read-only by construction: every handler issues GETs against /query,
  /tooling/query, /sobjects/<x>/describe, /limits. No write handler exists;
  tests/test_salesforce_review.py pins the tool surface.
- Every envelope except review_soql_query passes the sensitive-material gate
  (owner decision 2026-08-04 exempts composed SOQL rows); the gate matters more
  than in the .mjs era because the bearer token lives in this same process.
- Payload caps return normalized errors, never truncated JSON.

Protocol: newline-delimited JSON-RPC, revision 2025-06-18, stdio only. stdout is
protocol-only; ALL logging goes to stderr. tools/call dispatches to a small thread
pool (VS Code and Copilot CLI issue genuinely parallel tool calls); each response
is written under a lock as one atomic line. The internal client
(salesforce_review_client.py) batches initialize + tools/call with no
notifications/initialized and closes stdin — tools/call is deliberately not gated
on the initialized notification, and EOF drains in-flight work then exits 0.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent


def _fatal_startup(message: str) -> "NoReturn":  # noqa: F821 - typing only
    sys.stderr.write(f"Salesforce review facade blocked: {message}\n")
    sys.stderr.flush()
    raise SystemExit(2)


try:
    import requests
    from requests.adapters import HTTPAdapter
except ModuleNotFoundError:
    _fatal_startup(
        "DEPENDENCY_MISSING requests is not installed for this interpreter - "
        "run: python -m pip install --require-hashes -r requirements-dev.lock (see SETUP.md)"
    )

try:
    sys.path.insert(0, str(SCRIPT_DIR))
    # Single source of truth for the canonical envelope digest (plan par. 6c item 5):
    # a byte of divergence from the client's canonical_bytes() rejects every envelope.
    from salesforce_review_client import canonical_embedded_digest
except ModuleNotFoundError as exc:
    _fatal_startup(f"DEPENDENCY_MISSING {exc.name} (needed by salesforce_review_client)")

TEST_MODE = os.environ.get("SF_HARNESS_TEST_MODE") == "1"
CONFIG_PATH = (
    Path(os.environ["SF_HARNESS_CONFIG_PATH"]).resolve()
    if TEST_MODE and os.environ.get("SF_HARNESS_CONFIG_PATH")
    else REPO_ROOT / "config" / "harness.local.json"
)
POLICY_PATH = (
    Path(os.environ["SF_HARNESS_REVIEW_POLICY_PATH"]).resolve()
    if TEST_MODE and os.environ.get("SF_HARNESS_REVIEW_POLICY_PATH")
    else REPO_ROOT / "config" / "salesforce-review-policy.json"
)

PROTOCOL_VERSION = "2025-06-18"
SERVER_VERSION = "2.0.0"
SCHEMA_VERSION = 2

MAX_OUTER_MESSAGE_BYTES = 1_048_576
# Below half the outer cap: an envelope is embedded twice in a tools/call response
# (content[0].text and structuredContent) and must fit twice plus framing.
MAX_RESULT_BYTES = 480_000
CONNECT_TIMEOUT_SECONDS = 10
READ_TIMEOUT_SECONDS = 30
CLI_TIMEOUT_SECONDS = 60
MAX_SOQL_ROWS = 2000
THREAD_POOL_SIZE = 4
MIN_CLI_VERSION = (2, 136, 8)  # sf org auth show-access-token ships here

# Identity regexes ported character-for-character from the .mjs (plan par. 6c item 4).
OBJECT_API_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")
ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
ORG_ID = re.compile(r"^00D[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?$")
NON_PRODUCTION_HOST = re.compile(
    r"^(?:[a-z0-9][a-z0-9-]*--[a-z0-9][a-z0-9-]*\.sandbox\.my\.salesforce\.com"
    r"|[a-z0-9][a-z0-9-]*\.scratch\.my\.salesforce\.com"
    r"|[a-z0-9][a-z0-9-]*\.develop\.my\.salesforce\.com)$",
    re.IGNORECASE,
)
DEV_EDITION_HOST = re.compile(r"^[a-z0-9][a-z0-9-]*\.develop\.my\.salesforce\.com$", re.IGNORECASE)
# Second, pre-contact never-production wall (ported from the .mjs): a production-named
# alias is refused before ANY org contact - `sf org display` performs refreshAuth, so
# even reading identity from a production alias would touch the production org.
ALIAS_PRODUCTION_LIKE = re.compile(r"(^|[^a-z])(prod|production)([^a-z]|$)", re.IGNORECASE)

# GUI-launched VS Code on macOS inherits launchd's PATH, which misses every standard
# `sf` install location (observed live 2026-08-04). Colour is neutralised for every
# child: a developer profile that sets FORCE_COLOR makes `sf ... --json` emit ANSI
# escapes into the JSON (observed live 2026-08-05 as a misleading CLI_SCHEMA_MISMATCH).
SPAWN_PATH = (
    os.environ.get("PATH", "")
    if sys.platform == "win32"
    else ":".join(p for p in [os.environ.get("PATH", ""), "/usr/local/bin", "/opt/homebrew/bin"] if p)
)
SPAWN_ENV = {
    **os.environ,
    "PATH": SPAWN_PATH,
    "FORCE_COLOR": "0",
    "NO_COLOR": "1",
    "CLICOLOR": "0",
    "CLICOLOR_FORCE": "0",
}

EXPECTED_QUERIES = {
    "orgIdentity": "SELECT Id, IsSandbox FROM Organization LIMIT 1",
    "installedPackages": "SELECT SubscriberPackage.NamespacePrefix, SubscriberPackage.Name, SubscriberPackageVersion.Name, SubscriberPackageVersion.MajorVersion, SubscriberPackageVersion.MinorVersion, SubscriberPackageVersion.PatchVersion, SubscriberPackageVersion.BuildNumber FROM InstalledSubscriberPackage WHERE SubscriberPackage.NamespacePrefix IN (${PACKAGE_NAMESPACES}) ORDER BY SubscriberPackage.NamespacePrefix, SubscriberPackage.Name LIMIT 500",
    "installedPackagesAll": "SELECT SubscriberPackage.NamespacePrefix, SubscriberPackage.Name, SubscriberPackageVersion.Name, SubscriberPackageVersion.MajorVersion, SubscriberPackageVersion.MinorVersion, SubscriberPackageVersion.PatchVersion, SubscriberPackageVersion.BuildNumber FROM InstalledSubscriberPackage ORDER BY SubscriberPackage.NamespacePrefix, SubscriberPackage.Name LIMIT 500",
    "objectEntity": "SELECT QualifiedApiName FROM EntityDefinition WHERE QualifiedApiName = '${OBJECT_API_NAME}' LIMIT 2",
    # Column set verified live on 2026-08-05: IsUnique, IsCreatable and IsUpdatable do NOT
    # exist on FieldDefinition, which is why those traits come from the describe alone.
    "objectFields": "SELECT QualifiedApiName, DataType, IsNillable, IsCalculated, RelationshipName, ReferenceTo, Length, Precision, Scale, IsIndexed FROM FieldDefinition WHERE EntityDefinition.QualifiedApiName = '${OBJECT_API_NAME}' ORDER BY QualifiedApiName LIMIT 501",
}


class ReviewError(Exception):
    def __init__(self, code: str, status: str = "BLOCKED") -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(line: str) -> None:
    sys.stderr.write(line + "\n")
    sys.stderr.flush()


# --------------------------------------------------------------------------- config


def read_json(path: Path, failure_code: str) -> dict:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ReviewError(failure_code)
    if not isinstance(parsed, dict):
        raise ReviewError(failure_code)
    return parsed


def load_runtime(alias: str) -> dict:
    if not ALIAS.match(alias or ""):
        raise ReviewError("CONFIG_INVALID")
    if ALIAS_PRODUCTION_LIKE.search(alias):
        raise ReviewError("ALIAS_PRODUCTION_LIKE")
    config = read_json(CONFIG_PATH, "CONFIG_MISSING")
    policy = read_json(POLICY_PATH, "CONFIG_MISSING")
    salesforce = config.get("salesforce") or {}
    review = salesforce.get("review") or {}
    orgs = salesforce.get("orgs") or []
    configured = next((o for o in orgs if isinstance(o, dict) and o.get("alias") == alias), None)
    if configured and configured.get("environment") == "production":
        raise ReviewError("ALIAS_MARKED_PRODUCTION")
    # Owner decision 2026-08-04: any alias is admitted on live identity proof alone;
    # environment=production stays a hard deny marker and deniedOrganizationIds the
    # org-level brake. Unconfigured aliases run the dynamic-discovery lane.
    dynamic = configured is None
    entry = configured or {"alias": alias, "environment": "dynamic"}
    if review.get("enabled") is not True:
        raise ReviewError("REVIEW_DISABLED")
    if configured and entry.get("environment") not in ("development", "qa", "uat"):
        raise ReviewError("CONFIG_INVALID")
    has_host_pin = bool(configured) and "expectedInstanceHost" in entry
    has_org_pin = bool(configured) and "expectedOrganizationId" in entry
    if has_host_pin != has_org_pin:
        raise ReviewError("CONFIG_INVALID")
    pinned = has_host_pin and has_org_pin
    if pinned:
        if not NON_PRODUCTION_HOST.match(str(entry.get("expectedInstanceHost") or "")):
            raise ReviewError("CONFIG_INVALID")
        if not ORG_ID.match(str(entry.get("expectedOrganizationId") or "")):
            raise ReviewError("CONFIG_INVALID")
    denied = review.get("deniedOrganizationIds") or []
    if not isinstance(denied, list) or any(not ORG_ID.match(str(x)) for x in denied):
        raise ReviewError("CONFIG_INVALID")
    if not re.match(r"^\d{2}\.0$", str(review.get("apiVersion") or "")):
        raise ReviewError("CONFIG_INVALID")
    # requireDualSource is retired (plan F-1): tolerated if present, never required.
    allowed_objects = review.get("allowedObjectApiNames", ["*"])
    if not isinstance(allowed_objects, list) or not allowed_objects:
        raise ReviewError("CONFIG_INVALID")
    if any(name != "*" and not OBJECT_API_NAME.match(str(name)) for name in allowed_objects):
        raise ReviewError("CONFIG_INVALID")
    namespaces = review.get("allowedPackageNamespaces")
    if (
        not isinstance(namespaces, list)
        or any(ns != "*" and not re.match(r"^[A-Za-z][A-Za-z0-9]{0,14}$", str(ns)) for ns in namespaces)
        or ("*" in namespaces and len(namespaces) > 1)
    ):
        raise ReviewError("CONFIG_INVALID")
    max_fields = review.get("maxFieldsPerObject")
    if not isinstance(max_fields, int) or not 1 <= max_fields <= 500:
        raise ReviewError("CONFIG_INVALID")
    # Policy: the old server's knobs (vendor package pin, command timeout) were removed
    # from the policy file in F-4; unknown legacy keys are simply never read here.
    soql_timeout = policy.get("soqlQueryTimeoutSeconds")
    if (
        policy.get("schemaVersion") != 1
        or policy.get("mcpProtocolVersion") != PROTOCOL_VERSION
        or policy.get("salesforceCliMajor") != 2
        or not isinstance(policy.get("maxVendorPayloadBytes"), int)
        or not 65_536 <= policy["maxVendorPayloadBytes"] <= 1_048_576
        or not isinstance(soql_timeout, int)
        or not 5 <= soql_timeout <= 120
    ):
        raise ReviewError("CONFIG_INVALID")
    profiles = policy.get("profiles") or {}
    for name, query in EXPECTED_QUERIES.items():
        profile = profiles.get(name) or {}
        if profile.get("query") != query or not isinstance(profile.get("useToolingApi"), bool):
            raise ReviewError("QUERY_PROFILE_DENIED")
    return {
        "alias": alias,
        "entry": entry,
        "review": review,
        "policy": policy,
        "dynamic": dynamic,
        "pinned": pinned,
        "allowed_objects": set(allowed_objects),
        "allowed_namespaces": set(namespaces),
        "denied_org_ids": {str(x)[:15] for x in denied},
    }


# ------------------------------------------------------------------ CLI invocation


def assert_plain_cli_argument(value: str) -> str:
    # Fail-closed on quoting, on every platform (port of the .mjs guard): no argument
    # may contain a double quote, a newline, or a control character. Today none can
    # (alias regex, fixed literals) - this exists so a future change cannot open a
    # silent cmd.exe quoting hole.
    for character in str(value):
        code = ord(character)
        if character == '"' or code < 0x20 or code == 0x7F:
            raise ReviewError("CLI_SCHEMA_MISMATCH", "INCOMPLETE")
    return value


def scan_path_for_sf(path_value: str, pathext_value: str) -> "dict | None":
    """where.exe semantics, ported 1:1 (verified live on the team machine 2026-08-06):
    PATH directory order first, PATHEXT order within a directory, `.ps1` skipped
    (PowerShell is blocked on team machines), and - deliberately unlike shutil.which -
    the current directory is NEVER searched."""
    default_pathext = ".COM;.EXE;.BAT;.CMD"
    extensions = [
        ext.strip().lower()
        for ext in str(pathext_value or default_pathext).split(";")
        if ext.strip().startswith(".") and ext.strip().lower() != ".ps1"
    ]
    for directory in str(path_value or "").split(";"):
        if not directory:
            continue
        for ext in extensions:
            candidate = Path(directory) / f"sf{ext}"
            if candidate.exists():
                return {"path": str(candidate), "batch": ext in (".cmd", ".bat")}
    return None


_SF_RESOLUTION: "list | None" = None


def resolve_sf_invocation() -> "list[str]":
    """Resolve how to start `sf` for this platform.

    Windows: prefer the structural bypass - `node <install>\\bin\\run.js` - so cmd.exe
    never runs and BatBadBut-class quoting is irrelevant. The npm shim's content
    drifts between releases, so the bypass is used only after a runtime existence
    check; otherwise the full-path .cmd is spawned directly (CPython has no EINVAL
    block; safety rests on assert_plain_cli_argument + regex-validated arguments)."""
    global _SF_RESOLUTION
    if _SF_RESOLUTION is not None:
        return _SF_RESOLUTION
    if sys.platform != "win32":
        _SF_RESOLUTION = ["sf"]
        return _SF_RESOLUTION
    resolved = scan_path_for_sf(os.environ.get("PATH", ""), os.environ.get("PATHEXT", ""))
    if resolved is None:
        raise ReviewError("CLI_UNAVAILABLE", "INCOMPLETE")
    if resolved["batch"]:
        run_js = Path(resolved["path"]).parent / "node_modules" / "@salesforce" / "cli" / "bin" / "run.js"
        node = scan_path_for_sf_named_exe("node")
        if node and run_js.is_file():
            _SF_RESOLUTION = [node, str(run_js)]
            log(f"sf resolution: node bypass via {run_js}")
            return _SF_RESOLUTION
    _SF_RESOLUTION = [resolved["path"]]
    log(f"sf resolution: path={resolved['path']} batch={resolved['batch']}")
    return _SF_RESOLUTION


def scan_path_for_sf_named_exe(name: str) -> "str | None":
    for directory in str(os.environ.get("PATH", "")).split(";"):
        if not directory:
            continue
        candidate = Path(directory) / f"{name}.exe"
        if candidate.exists():
            return str(candidate)
    return None


def run_cli_json(args: "list[str]", failure_code: str = "CLI_UNAVAILABLE", timeout: int = CLI_TIMEOUT_SECONDS) -> dict:
    if TEST_MODE:
        executable = os.environ.get("SF_HARNESS_SF_EXECUTABLE", "sf")
        try:
            base_args = json.loads(os.environ.get("SF_HARNESS_SF_ARGS_JSON", "[]"))
        except json.JSONDecodeError:
            raise ReviewError("CLI_UNAVAILABLE", "INCOMPLETE")
        command = [executable, *base_args, *args]
    else:
        for arg in args:
            assert_plain_cli_argument(arg)
        command = [*resolve_sf_invocation(), *args]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            cwd=str(REPO_ROOT),
            env=SPAWN_ENV,
        )
    except (OSError, subprocess.SubprocessError):
        raise ReviewError(failure_code, "INCOMPLETE")
    if len(completed.stdout.encode("utf-8", "replace")) > MAX_OUTER_MESSAGE_BYTES:
        raise ReviewError("CLI_OUTPUT_TOO_LARGE", "INCOMPLETE")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        raise ReviewError("CLI_SCHEMA_MISMATCH", "INCOMPLETE")
    if not isinstance(payload, dict) or (payload.get("status") not in (None, 0)):
        raise ReviewError("CLI_SCHEMA_MISMATCH", "INCOMPLETE")
    return payload.get("result") if isinstance(payload.get("result"), dict) else payload


def safe_string(value, max_length: int = 160) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise ReviewError("CLI_SCHEMA_MISMATCH", "INCOMPLETE")
    return value


# ------------------------------------------------------------------- REST session


class RestClient:
    """One authenticated, pooled HTTPS session for the whole server session.

    401 handling re-runs `sf org auth show-access-token` once, then re-proves the
    live org identity with the new token before any replay - auth-file metadata is
    not trusted here because a stale or realiased file can disagree with the token
    it stores. An identity mismatch fail-closes the session permanently."""

    def __init__(self, runtime: dict, instance_url: str, api_version: str, token: str) -> None:
        self.runtime = runtime
        self.instance_url = instance_url.rstrip("/")
        self.base = (
            os.environ["SF_HARNESS_REST_BASE"].rstrip("/")
            if TEST_MODE and os.environ.get("SF_HARNESS_REST_BASE")
            else self.instance_url
        )
        self.api_version = api_version
        self.token = token
        self.fail_closed = False
        self.frozen_org_id: "str | None" = None
        self.frozen_is_sandbox: "bool | None" = None
        self._refresh_lock = threading.Lock()
        self._session_lock = threading.Lock()
        self._session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=2, pool_maxsize=THREAD_POOL_SIZE * 2)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _get(self, path: str, params: "dict | None", read_timeout: int) -> requests.Response:
        url = path if path.startswith("http") else f"{self.base}{path}"
        return self._session.get(
            url,
            params=params,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
            timeout=(CONNECT_TIMEOUT_SECONDS, read_timeout),
        )

    def get_json(self, path: str, params: "dict | None" = None, read_timeout: int = READ_TIMEOUT_SECONDS) -> dict:
        if self.fail_closed:
            raise ReviewError("IDENTITY_ORG_ID_MISMATCH")
        attempt = 0
        while True:
            attempt += 1
            session_used = self._session
            token_used = self.token
            try:
                response = self._get(path, params, read_timeout)
            except requests.exceptions.ConnectTimeout:
                raise ReviewError("REST_UNAVAILABLE", "INCOMPLETE")
            except requests.exceptions.ReadTimeout:
                # Never retried: a retry would blow the client's ~60s budget. The agent
                # gets a steering execution error instead (narrower query, lower LIMIT).
                raise ReviewError("REST_TIMEOUT", "INCOMPLETE")
            except requests.exceptions.ConnectionError:
                # Laptop sleep / dropped VPN leaves dead pooled connections. Rebuild the
                # pool and retry exactly once - every call here is an idempotent GET.
                # The swap happens under a lock and only if no other thread already
                # replaced the session we were using (concurrent rebuild race).
                if attempt > 1:
                    raise ReviewError("REST_UNAVAILABLE", "INCOMPLETE")
                with self._session_lock:
                    if self._session is session_used:
                        self._session.close()
                        self._session = self._build_session()
                continue
            except requests.exceptions.RequestException:
                raise ReviewError("REST_UNAVAILABLE", "INCOMPLETE")
            if response.status_code == 401:
                if attempt > 1:
                    raise ReviewError("REST_UNAVAILABLE", "INCOMPLETE")
                self._refresh_token_and_reprove(token_used)
                continue
            if len(response.content) > self.runtime["policy"]["maxVendorPayloadBytes"]:
                raise ReviewError("REST_SCHEMA_MISMATCH", "INCOMPLETE")
            if response.status_code == 404:
                raise ReviewError("REST_NOT_FOUND", "INCOMPLETE")
            if response.status_code >= 400:
                raise ReviewError("REST_SCHEMA_MISMATCH", "INCOMPLETE")
            try:
                parsed = response.json()
            except ValueError:
                raise ReviewError("REST_SCHEMA_MISMATCH", "INCOMPLETE")
            return parsed

    def _refresh_token_and_reprove(self, token_used: str) -> None:
        with self._refresh_lock:
            if self.fail_closed:
                raise ReviewError("IDENTITY_ORG_ID_MISMATCH")
            if self.token != token_used:
                # Another pool thread already refreshed while we queued on the lock;
                # replay with its token instead of stampeding the sf CLI (one refresh
                # serves every concurrently 401'd call).
                return
            log("token refresh: re-running sf org auth show-access-token")
            result = run_cli_json(
                ["org", "auth", "show-access-token", "--json", "-o", self.runtime["alias"]],
                timeout=15,
            )
            token = result.get("accessToken")
            if not isinstance(token, str) or not token:
                raise ReviewError("CLI_SCHEMA_MISMATCH", "INCOMPLETE")
            self.token = token
            # Live re-proof with the NEW token: the refresh must never silently rebind
            # the session to a different org (stale auth file, reused alias). Direct
            # request on purpose - going through get_json here would re-enter the
            # non-reentrant refresh lock on a second 401.
            try:
                response = self._get(
                    f"/services/data/v{self.api_version}/query/",
                    {"q": EXPECTED_QUERIES["orgIdentity"]},
                    READ_TIMEOUT_SECONDS,
                )
            except requests.exceptions.RequestException:
                raise ReviewError("REST_UNAVAILABLE", "INCOMPLETE")
            if response.status_code != 200:
                raise ReviewError("REST_UNAVAILABLE", "INCOMPLETE")
            try:
                records = response.json().get("records")
            except ValueError:
                raise ReviewError("REST_SCHEMA_MISMATCH", "INCOMPLETE")
            if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
                raise ReviewError("REST_SCHEMA_MISMATCH", "INCOMPLETE")
            record = records[0]
            org_id = str(record.get("Id") or "")[:15]
            if self.frozen_org_id is not None and org_id != self.frozen_org_id:
                self.fail_closed = True
                log("token refresh: org id mismatch - session fail-closed")
                raise ReviewError("IDENTITY_ORG_ID_MISMATCH")

    def identity_record(self) -> dict:
        payload = self.get_json(
            f"/services/data/v{self.api_version}/query/",
            {"q": EXPECTED_QUERIES["orgIdentity"]},
        )
        records = payload.get("records")
        if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
            raise ReviewError("REST_SCHEMA_MISMATCH", "INCOMPLETE")
        return records[0]

    def query(
        self,
        soql: str,
        use_tooling: bool,
        budget_seconds: int = 45,
        max_rows: int = MAX_SOQL_ROWS,
    ) -> dict:
        # One cumulative deadline for the WHOLE call, pagination included: giving each
        # nextRecordsUrl page a fresh read budget would let two slow pages blow the
        # client's hard ~60s timeout - the exact symptom this rewrite removes.
        deadline = time.monotonic() + budget_seconds

        def remaining() -> int:
            left = int(deadline - time.monotonic())
            if left <= 0:
                raise ReviewError("REST_TIMEOUT", "INCOMPLETE")
            return min(left, READ_TIMEOUT_SECONDS + 10)

        prefix = "tooling/" if use_tooling else ""
        payload = self.get_json(
            f"/services/data/v{self.api_version}/{prefix}query/", {"q": soql}, remaining()
        )
        records = list(payload.get("records") or [])
        # Strictly-less-than: a page landing exactly on the cap with done=false already
        # proves truncation - fetching one more page would be provably redundant work.
        while payload.get("done") is False and payload.get("nextRecordsUrl") and len(records) < max_rows:
            next_path = str(payload["nextRecordsUrl"])
            payload = self.get_json(next_path, None, remaining())
            records.extend(payload.get("records") or [])
        truncated = payload.get("done") is False or len(records) > max_rows
        return {"records": records[:max_rows], "truncated": truncated}


# ---------------------------------------------------------------------- envelope


def base_target(runtime: dict, proof: "dict | None" = None) -> dict:
    proof = proof or {}
    return {
        "environment": runtime["entry"]["environment"],
        "apiVersion": runtime["review"]["apiVersion"],
        "aliasPolicyMatched": True,
        "expectedHostMatched": proof.get("expectedHostMatched") is True,
        "expectedOrgIdMatched": proof.get("expectedOrgIdMatched") is True,
        "isSandbox": proof.get("isSandbox") is True,
        "nonProduction": proof.get("nonProduction") is True,
    }


def unavailable_source(kind: str, version: str = "unavailable") -> dict:
    return {"kind": kind, "version": version, "complete": False, "retrievedAt": now_iso()}


SENSITIVE_KEYS = {
    "accesstoken",
    "refreshtoken",
    "sfdxauthurl",
    "authorization",
    "clientid",
    "username",
    "orgid",
    "organizationid",
    "instanceurl",
}
SENSITIVE_PATTERNS = [
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"force://", re.IGNORECASE),
    re.compile(r"\b00D[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?\b"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
]


def contains_sensitive_material(value) -> bool:
    if isinstance(value, list):
        return any(contains_sensitive_material(item) for item in value)
    if isinstance(value, dict):
        return any(
            key.lower() in SENSITIVE_KEYS or contains_sensitive_material(child)
            for key, child in value.items()
        )
    if not isinstance(value, str):
        return False
    return any(pattern.search(value) for pattern in SENSITIVE_PATTERNS)


def make_envelope(
    runtime: dict,
    review_type: str,
    status: str,
    *,
    target: "dict | None" = None,
    sources: "dict | None" = None,
    facts: "dict | None" = None,
    reconciliation: "dict | None" = None,
    completeness: "dict | None" = None,
    warnings: "list | None" = None,
    sensitive_gate_exempt: bool = False,
) -> dict:
    envelope = {
        "schemaVersion": SCHEMA_VERSION,
        "runId": str(uuid.uuid4()),
        "generatedAt": now_iso(),
        "reviewType": review_type,
        "status": status,
        "target": target or base_target(runtime),
        "sources": sources
        or {
            "cli": unavailable_source("salesforce-cli"),
            "rest": unavailable_source("salesforce-rest"),
        },
        "facts": facts or {},
        "reconciliation": reconciliation or {"status": "NOT_RUN", "comparisons": []},
        "completeness": completeness or {"complete": False, "dualSource": False, "truncated": False},
        "warnings": sorted(set(warnings or [])),
    }
    # Composed-SOQL results are exempt (owner decision 2026-08-04): record values -
    # including emails and record Ids - return unredacted, so the leak scan would
    # blank every real result. Everything else is scanned; the gate matters more now
    # that the bearer token lives in this process.
    if not sensitive_gate_exempt and contains_sensitive_material(envelope):
        blocked = {
            **envelope,
            "status": "BLOCKED",
            "target": base_target(runtime),
            "facts": {},
            "reconciliation": {"status": "NOT_RUN", "comparisons": []},
            "completeness": {"complete": False, "dualSource": False, "truncated": False},
            "warnings": ["SENSITIVE_OUTPUT_DETECTED"],
            "sources": {
                "cli": unavailable_source("salesforce-cli"),
                "rest": unavailable_source("salesforce-rest"),
            },
        }
        blocked["sha256"] = canonical_embedded_digest(blocked)
        return blocked
    envelope["sha256"] = canonical_embedded_digest(envelope)
    return envelope


# Warning codes the schema classifies as blocking: an envelope carrying one of these
# must be BLOCKED (the INCOMPLETE conditional forbids them). CLI_SCHEMA_MISMATCH sits
# in both enums, but only the BLOCKED lane accepts it unconditionally.
BLOCKING_WARNINGS = {
    "CLI_SCHEMA_MISMATCH",
    "CLI_VERSION_UNSUPPORTED",
    "IDENTITY_HOST_MISMATCH",
    "IDENTITY_ORG_ID_MISMATCH",
    "INTERNAL_ERROR",
    "NOT_SANDBOX",
    "OBJECT_NOT_ALLOWLISTED",
    "ORG_ID_DENIED",
    "QUERY_PROFILE_DENIED",
    "QUERY_VALIDATION_DENIED",
    "SCOPED_ENUMERATION_DISABLED",
    "SENSITIVE_OUTPUT_DETECTED",
}


def error_envelope(runtime: dict, review_type: str, error: ReviewError, proof: "dict | None" = None) -> dict:
    code = error.code if error.code != "REST_NOT_FOUND" else "REST_SCHEMA_MISMATCH"
    status = (
        "INCOMPLETE"
        if error.status == "INCOMPLETE" and proof and code not in BLOCKING_WARNINGS
        else "BLOCKED"
    )
    truncated = error.code == "RESULT_TRUNCATED"
    return make_envelope(
        runtime,
        review_type,
        status,
        target=base_target(runtime, proof) if proof else None,
        reconciliation={"status": "NOT_RUN", "comparisons": []},
        completeness={"complete": False, "dualSource": False, "truncated": truncated},
        warnings=[code],
    )


def comparison(fact: str, matches: bool) -> dict:
    return {"fact": fact, "result": "MATCH" if matches else "MISMATCH"}


# -------------------------------------------------------------------- normalizers


def bool_or_null(value):
    return value if isinstance(value, bool) else None


def int_or_null(value):
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def reference_list(value):
    raw = value if isinstance(value, list) else (value or {}).get("referenceTo") if isinstance(value, dict) else None
    if not isinstance(raw, list):
        return None
    targets = sorted(safe_string(item, 80) for item in raw if item)
    # Absent and empty mean the same thing (measured live 2026-08-05 on Account:
    # the describe reports [] for non-reference fields, Tooling reports nothing).
    return targets or None


def describe_type_family(value: str) -> str:
    type_name = safe_string(value, 80).lower()
    if type_name in ("string", "textarea", "email", "phone", "url", "encryptedstring", "combobox"):
        return "text"
    if type_name in ("double", "int", "currency", "percent"):
        return "number"
    if type_name in ("reference", "masterrecord"):
        return "reference"
    if type_name in ("picklist", "multipicklist"):
        return type_name
    if type_name in ("boolean", "date", "datetime", "time", "base64", "address", "location", "id"):
        return type_name
    return f"other:{type_name}"


def tooling_type_family(value: str) -> str:
    raw = safe_string(value, 160).strip().lower()
    if re.match(r"^(text|long text area|rich text|html|encrypted text|email|phone|url|auto number)", raw):
        return "text"
    if re.match(r"^(number|currency|percent|formula \((number|currency|percent))", raw):
        return "number"
    # Lookup() with empty parentheses is how Tooling describes the record Id itself
    # (measured on Account.Id, 2026-08-05).
    if re.match(r"^lookup\(\s*\)$", raw):
        return "id"
    if re.match(r"^(lookup|master-detail|hierarchy|external lookup|indirect lookup)", raw):
        return "reference"
    if re.match(r"^name$", raw):
        return "text"
    if re.match(r"^multi-select picklist", raw):
        return "multipicklist"
    if re.match(r"^picklist", raw):
        return "picklist"
    if re.match(r"^(checkbox|formula \(checkbox)", raw):
        return "boolean"
    if re.match(r"^(date/time|formula \(date/time)", raw):
        return "datetime"
    if re.match(r"^(date|formula \(date)", raw):
        return "date"
    if re.match(r"^(time|formula \(time)", raw):
        return "time"
    if re.match(r"^geolocation", raw):
        return "location"
    if re.match(r"^address", raw):
        return "address"
    if re.match(r"^base64", raw):
        return "base64"
    if re.match(r"^id$", raw):
        return "id"
    return "other:" + re.sub(r"\s+", "-", raw)


SHARED_TRAITS = ("nillable", "calculated", "relationshipName", "referenceTo", "length", "precision", "scale")


def strip_attributes(value):
    if isinstance(value, list):
        return [strip_attributes(item) for item in value]
    if isinstance(value, dict):
        return {key: strip_attributes(child) for key, child in value.items() if key != "attributes"}
    return value


# ------------------------------------------------------------------ tool handlers


def review_org_identity(server: "Server") -> dict:
    runtime = server.runtime
    retrieved = now_iso()
    record = server.rest.identity_record()
    org_id = str(record.get("Id") or "")[:15]
    if org_id != server.rest.frozen_org_id:
        server.rest.fail_closed = True
        raise ReviewError("IDENTITY_ORG_ID_MISMATCH")
    if record.get("IsSandbox") != server.rest.frozen_is_sandbox:
        raise ReviewError("NOT_SANDBOX")
    return make_envelope(
        runtime,
        "org-identity",
        "VERIFIED",
        target=base_target(runtime, server.proof),
        sources={
            "cli": dict(server.cli_source),
            "rest": {"kind": "salesforce-rest", "version": runtime["review"]["apiVersion"], "complete": True, "retrievedAt": retrieved},
        },
        facts={
            "identityPolicyMatched": True,
            "isSandbox": server.proof["isSandbox"] is True,
            "nonProduction": True,
        },
        reconciliation={
            "status": "MATCH",
            "comparisons": [comparison("organization-identity", True), comparison("is-sandbox", True)],
        },
        completeness={"complete": True, "dualSource": False, "truncated": False},
        warnings=[],
    )


def review_installed_packages(server: "Server") -> dict:
    runtime = server.runtime
    retrieved = now_iso()
    namespaces = runtime["allowed_namespaces"]
    if not namespaces:
        records = []
    elif "*" in namespaces:
        records = server.rest.query(EXPECTED_QUERIES["installedPackagesAll"], True)["records"]
    else:
        in_list = ",".join(f"'{ns}'" for ns in sorted(namespaces))
        soql = EXPECTED_QUERIES["installedPackages"].replace("${PACKAGE_NAMESPACES}", in_list)
        records = server.rest.query(soql, True)["records"]
    if len(records) >= 500:
        raise ReviewError("RESULT_TRUNCATED", "INCOMPLETE")
    packages = []
    for item in records:
        pkg = item.get("SubscriberPackage") or {}
        ver = item.get("SubscriberPackageVersion") or {}
        parts = [ver.get("MajorVersion"), ver.get("MinorVersion"), ver.get("PatchVersion"), ver.get("BuildNumber")]
        if any(not isinstance(part, int) or part < 0 for part in parts):
            raise ReviewError("REST_SCHEMA_MISMATCH", "INCOMPLETE")
        namespace = pkg.get("NamespacePrefix")
        packages.append(
            {
                "namespace": safe_string(namespace, 80) if namespace else None,
                "name": safe_string(pkg.get("Name")),
                "version": ".".join(str(part) for part in parts),
            }
        )
    packages.sort(key=lambda entry: json.dumps(entry, sort_keys=True))
    return make_envelope(
        runtime,
        "installed-packages",
        "VERIFIED",
        target=base_target(runtime, server.proof),
        sources={
            "cli": dict(server.cli_source),
            "rest": {"kind": "salesforce-rest", "version": runtime["review"]["apiVersion"], "complete": True, "retrievedAt": retrieved},
        },
        facts={"packages": packages},
        reconciliation={"status": "SINGLE_SOURCE", "comparisons": []},
        completeness={"complete": True, "dualSource": False, "truncated": False},
        warnings=[],
    )


def review_object_contract(server: "Server", tool_input: dict) -> dict:
    runtime = server.runtime
    requested = tool_input.get("objectApiName")
    allowed = "*" in runtime["allowed_objects"] or requested in runtime["allowed_objects"]
    if not OBJECT_API_NAME.match(str(requested or "")) or not allowed:
        return make_envelope(runtime, "object-contract", "BLOCKED", warnings=["OBJECT_NOT_ALLOWLISTED"])
    retrieved = now_iso()
    entity = server.rest.query(
        EXPECTED_QUERIES["objectEntity"].replace("${OBJECT_API_NAME}", requested), True
    )
    if len(entity["records"]) > 1:
        raise ReviewError("REST_SCHEMA_MISMATCH", "INCOMPLETE")
    exists = len(entity["records"]) == 1
    fields: "list[dict]" = []
    contested: "list[str]" = []
    if exists:
        if entity["records"][0].get("QualifiedApiName") != requested:
            raise ReviewError("REST_SCHEMA_MISMATCH", "INCOMPLETE")
        tooling_rows = server.rest.query(
            EXPECTED_QUERIES["objectFields"].replace("${OBJECT_API_NAME}", requested), True
        )["records"]
        if len(tooling_rows) > runtime["review"]["maxFieldsPerObject"]:
            raise ReviewError("RESULT_TRUNCATED", "INCOMPLETE")
        # Describe supplement (owner decision 2026-08-09, option b): FieldDefinition has
        # no IsUnique/IsCreatable/IsUpdatable (verified live 2026-08-05); those traits
        # only exist in the describe, and losing them broke deterministic seeding once.
        try:
            describe = server.rest.get_json(
                f"/services/data/v{runtime['review']['apiVersion']}/sobjects/{requested}/describe/"
            )
            describe_fields = {f.get("name"): f for f in describe.get("fields") or [] if isinstance(f, dict)}
        except ReviewError as err:
            if err.code != "REST_NOT_FOUND":
                raise
            describe_fields = {}
        by_name: "dict[str, dict]" = {}
        for row in tooling_rows:
            name = safe_string(row.get("QualifiedApiName"), 80)
            by_name[name] = {
                "tooling": {
                    "typeFamily": tooling_type_family(row.get("DataType")),
                    "nillable": bool_or_null(row.get("IsNillable")),
                    "calculated": bool_or_null(row.get("IsCalculated")),
                    "relationshipName": safe_string(row["RelationshipName"], 80) if row.get("RelationshipName") else None,
                    "referenceTo": reference_list(row.get("ReferenceTo")),
                    "length": int_or_null(row.get("Length")),
                    "precision": int_or_null(row.get("Precision")),
                    "scale": int_or_null(row.get("Scale")),
                    "indexed": bool_or_null(row.get("IsIndexed")),
                    "dataType": safe_string(row.get("DataType"), 160) if row.get("DataType") else None,
                }
            }
        for name, row in describe_fields.items():
            if not isinstance(name, str) or not name:
                continue
            by_name.setdefault(name, {})["describe"] = {
                "typeFamily": describe_type_family(row.get("type")) if row.get("type") else None,
                "nillable": bool_or_null(row.get("nillable")),
                "calculated": bool_or_null(row.get("calculated")),
                "relationshipName": safe_string(row["relationshipName"], 80) if row.get("relationshipName") else None,
                "referenceTo": reference_list(row.get("referenceTo")),
                "length": int_or_null(row.get("length")),
                "precision": int_or_null(row.get("precision")),
                "scale": int_or_null(row.get("scale")),
                "unique": bool_or_null(row.get("unique")),
                "externalId": bool_or_null(row.get("externalId")),
                "createable": bool_or_null(row.get("createable")),
                "updateable": bool_or_null(row.get("updateable")),
                "dataType": safe_string(row.get("type"), 80) if row.get("type") else None,
            }
        for name in sorted(by_name):
            legs = by_name[name]
            tooling = legs.get("tooling") or {}
            describe_leg = legs.get("describe") or {}
            traits = {}
            for key in SHARED_TRAITS:
                left = describe_leg.get(key)
                right = tooling.get(key)
                if legs.get("describe") and legs.get("tooling") and json.dumps(left, sort_keys=True) != json.dumps(right, sort_keys=True):
                    # A contested trait is reported as contested, never silently
                    # resolved to one endpoint (port of the reconcile rule, par. 16.3).
                    contested.append(f"{name}.{key}")
                    traits[key] = None
                else:
                    traits[key] = left if legs.get("describe") else right
            type_family = describe_leg.get("typeFamily") or tooling.get("typeFamily") or "other:unknown"
            if (
                legs.get("describe")
                and legs.get("tooling")
                and describe_leg.get("typeFamily")
                and describe_leg["typeFamily"] != tooling["typeFamily"]
            ):
                contested.append(f"{name}.typeFamily")
            fields.append(
                {
                    "name": name,
                    "typeFamily": type_family,
                    **traits,
                    "sourceExclusive": {
                        "rest": {
                            "unique": describe_leg.get("unique"),
                            "externalId": describe_leg.get("externalId"),
                            "createable": describe_leg.get("createable"),
                            "updateable": describe_leg.get("updateable"),
                            "indexed": tooling.get("indexed"),
                            "dataType": describe_leg.get("dataType") or tooling.get("dataType"),
                        }
                    },
                }
            )
    import hashlib

    namespace = requested.split("__")[0] if requested.count("__") >= 2 else None
    schema_digest = "sha256:" + hashlib.sha256(
        json.dumps([{"name": f["name"], "typeFamily": f["typeFamily"]} for f in fields]).encode("utf-8")
    ).hexdigest()
    facts_object = {
        "objectApiName": requested,
        "namespace": namespace,
        "exists": exists,
        "fields": fields,
        "fieldCount": len(fields),
        "truncated": False,
        "contestedProperties": sorted(set(contested))[:100],
        "schemaDigest": schema_digest,
    }
    return make_envelope(
        runtime,
        "object-contract",
        "VERIFIED",
        target=base_target(runtime, server.proof),
        sources={
            "cli": dict(server.cli_source),
            "rest": {"kind": "salesforce-rest", "version": runtime["review"]["apiVersion"], "complete": True, "retrievedAt": retrieved},
        },
        facts={"object": facts_object},
        reconciliation={"status": "SINGLE_SOURCE", "comparisons": []},
        completeness={"complete": True, "dualSource": False, "truncated": False},
        warnings=[],
    )


def review_configured_orgs(server: "Server") -> dict:
    runtime = server.runtime
    config = read_json(CONFIG_PATH, "CONFIG_MISSING")
    if (config.get("safety") or {}).get("allowScopedEnumeration") is not True:
        return make_envelope(runtime, "configured-orgs", "BLOCKED", warnings=["SCOPED_ENUMERATION_DISABLED"])
    orgs = [
        {"alias": entry["alias"], "environment": entry.get("environment")}
        for entry in (config.get("salesforce") or {}).get("orgs") or []
        if isinstance(entry, dict) and isinstance(entry.get("alias"), str)
    ]
    return make_envelope(
        runtime,
        "configured-orgs",
        "VERIFIED",
        facts={"orgCount": len(orgs), "orgs": orgs},
        reconciliation={"status": "NOT_RUN", "comparisons": []},
        completeness={"complete": True, "dualSource": False, "truncated": False},
        warnings=[],
    )


def strip_soql_literals(query: str) -> str:
    # Replace single-quoted literals (with escapes) by empty literals so FROM scanning
    # cannot be confused by quoted content. The raw query is what executes; scan-only.
    return re.sub(r"'(?:[^'\\]|\\.)*'", "''", query)


def describe_composed_soql(raw_query, use_tooling, runtime: dict) -> dict:
    if not isinstance(raw_query, str) or not raw_query.strip() or len(raw_query) > 10_000:
        return {"ok": False, "warning": "QUERY_VALIDATION_DENIED"}
    if use_tooling not in (None, True, False):
        return {"ok": False, "warning": "QUERY_VALIDATION_DENIED"}
    from_targets = [
        match.group(1)
        for match in re.finditer(r"\bFROM\s+([A-Za-z][A-Za-z0-9_]*)\b", strip_soql_literals(raw_query), re.IGNORECASE)
    ]
    if not from_targets:
        return {"ok": False, "warning": "QUERY_VALIDATION_DENIED"}
    if len(set(from_targets)) > 20:
        # The evidence schema pins facts.soqlQuery.fromObjects to maxItems 20; denying
        # up front keeps the MCP lane and the digest-checked knowledge lane consistent
        # instead of emitting a VERIFIED envelope the consumer's validation rejects.
        return {"ok": False, "warning": "QUERY_VALIDATION_DENIED"}
    if "*" not in runtime["allowed_objects"]:
        # An explicitly configured allowlist is the owner's data-scoping choice for an
        # org holding sensitive data; the default (absent key = "*") restricts nothing.
        for target in from_targets:
            if target not in runtime["allowed_objects"]:
                return {"ok": False, "warning": "OBJECT_NOT_ALLOWLISTED"}
    return {"ok": True, "fromObjects": sorted(set(from_targets)), "useToolingApi": use_tooling is True}


def review_soql_query(server: "Server", tool_input: dict) -> dict:
    import hashlib

    runtime = server.runtime
    description = describe_composed_soql(tool_input.get("query"), tool_input.get("useToolingApi"), runtime)
    if not description["ok"]:
        return make_envelope(runtime, "soql-query", "BLOCKED", warnings=[description["warning"]])
    retrieved = now_iso()
    result = server.rest.query(
        tool_input["query"],
        description["useToolingApi"],
        budget_seconds=min(runtime["policy"]["soqlQueryTimeoutSeconds"], 45),
    )
    if result["truncated"]:
        raise ReviewError("RESULT_TRUNCATED", "INCOMPLETE")
    records = strip_attributes(result["records"])
    query_digest = hashlib.sha256(tool_input["query"].encode("utf-8")).hexdigest()
    return make_envelope(
        runtime,
        "soql-query",
        "VERIFIED",
        target=base_target(runtime, server.proof),
        sources={
            "cli": dict(server.cli_source),
            "rest": {"kind": "salesforce-rest", "version": runtime["review"]["apiVersion"], "complete": True, "retrievedAt": retrieved},
        },
        facts={
            "soqlQuery": {
                # The digest binds the envelope to EXACTLY the submitted statement - the
                # org-attach executor refuses when the facade executed different text.
                "queryDigest": query_digest,
                "fromObjects": description["fromObjects"],
                "useToolingApi": description["useToolingApi"],
                "matched": len(records),
                "records": records,
            }
        },
        reconciliation={
            "status": "IDENTITY_MATCH_ONLY",
            "comparisons": [comparison("organization-identity", True), comparison("is-sandbox", True)],
        },
        completeness={"complete": True, "dualSource": False, "truncated": False},
        warnings=[],
        sensitive_gate_exempt=True,
    )


def org_limits(server: "Server") -> dict:
    # Not an evidence envelope: nothing downstream consumes limits, and the evidence
    # contract exists for org facts that get cited. Sensitive gate still applies.
    payload = server.rest.get_json(f"/services/data/v{server.runtime['review']['apiVersion']}/limits/")
    result = {"retrievedAt": now_iso(), "limits": payload}
    if contains_sensitive_material(result):
        raise ReviewError("SENSITIVE_OUTPUT_DETECTED")
    return result


def explain_query(server: "Server", tool_input: dict) -> dict:
    runtime = server.runtime
    description = describe_composed_soql(tool_input.get("query"), tool_input.get("useToolingApi"), runtime)
    if not description["ok"]:
        # Same FROM scan + allowlist as review_soql_query: without it, explain would be
        # a scoping bypass (it reveals fields, indexes and cardinalities).
        raise ReviewError(description["warning"])
    prefix = "tooling/" if description["useToolingApi"] else ""
    payload = server.rest.get_json(
        f"/services/data/v{runtime['review']['apiVersion']}/{prefix}query/",
        {"explain": tool_input["query"]},
    )
    plans = payload.get("plans")
    if not isinstance(plans, list):
        raise ReviewError("REST_SCHEMA_MISMATCH", "INCOMPLETE")
    # Raw plans[] passthrough - no server-side interpretation of cost or cardinality;
    # judging selectivity is the agent's in-context job (plan D-7).
    result = {"retrievedAt": now_iso(), "plans": plans}
    if contains_sensitive_material(result):
        raise ReviewError("SENSITIVE_OUTPUT_DETECTED")
    return result


# ------------------------------------------------------------------ tool registry


STEER_EVIDENCE = (
    "MISMATCH, INCOMPLETE, and BLOCKED are never confirmed facts. Cite any number "
    "with its org context and observation time, never as production truth."
)

TOOL_DEFINITIONS = [
    {
        "name": "review_org_identity",
        "title": "Review the configured non-production Salesforce identity",
        "description": "Re-prove the session-frozen non-production org identity live over REST. " + STEER_EVIDENCE,
        "inputSchema": {"type": "object", "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "review_installed_packages",
        "title": "Review installed Salesforce packages",
        "description": "Normalized package namespace, name, and version facts (single REST source). " + STEER_EVIDENCE,
        "inputSchema": {"type": "object", "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "review_configured_orgs",
        "title": "List the locally configured Salesforce orgs (scoped enumeration)",
        "description": "Enumerate ONLY the org aliases configured in config/harness.local.json. Requires safety.allowScopedEnumeration; never reveals org ids, hosts, or unconfigured orgs.",
        "inputSchema": {"type": "object", "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "review_object_contract",
        "title": "Review one Salesforce object contract",
        "description": "Object existence and normalized field facts from the pinned FieldDefinition queries, with describe-only traits (unique/externalId/createable/updateable) under sourceExclusive.rest. Contested traits between the two REST endpoints are nulled and listed in contestedProperties. " + STEER_EVIDENCE,
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["objectApiName"],
            "properties": {
                "objectApiName": {
                    "type": "string",
                    "pattern": "^[A-Za-z][A-Za-z0-9_]{0,79}$",
                    "description": "Exact object API name.",
                }
            },
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "review_soql_query",
        "title": "Execute one composed read-only SOQL statement",
        "description": "Execute one model-composed read-only SOQL statement verbatim against the identity-proven non-production org over REST. Rows return unredacted, bounded by payload size, row cap and timeout. Add a LIMIT yourself: an overflowing result set returns INCOMPLETE/RESULT_TRUNCATED - make several narrower queries instead of one broad one.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "maxLength": 10000, "description": "The SOQL statement, executed verbatim."},
                "useToolingApi": {"type": "boolean", "description": "Run against the Tooling API query endpoint."},
            },
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "org_limits",
        "title": "Read the org's API limit consumption",
        "description": "GET /limits - DailyApiRequests max/remaining and other org limits, so investigation can watch its own API budget. Diagnostic; not citable evidence.",
        "inputSchema": {"type": "object", "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "explain_query",
        "title": "Get the query plan for a SOQL statement (no execution)",
        "description": "GET /query/?explain= - returns Salesforce's raw plans[] (leadingOperationType, relativeCost, cardinality) WITHOUT executing the query or returning rows. Beta endpoint. Judge selectivity yourself from the plans; the server does not interpret them. Never called automatically - use it only when you explicitly need plan feedback.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "maxLength": 10000, "description": "The SOQL statement to explain (not executed)."},
                "useToolingApi": {"type": "boolean", "description": "Explain against the Tooling API query endpoint."},
            },
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    },
]

ENVELOPE_TOOLS = {
    "review_org_identity",
    "review_installed_packages",
    "review_configured_orgs",
    "review_object_contract",
    "review_soql_query",
}


def validate_tool_input(name: str, tool_input) -> bool:
    if not isinstance(tool_input, dict):
        return False
    keys = set(tool_input.keys())
    if name == "review_object_contract":
        return keys == {"objectApiName"}
    if name in ("review_soql_query", "explain_query"):
        return keys in ({"query"}, {"query", "useToolingApi"})
    return not keys


# ------------------------------------------------------------------------ server


class Server:
    def __init__(self, runtime: dict) -> None:
        self.runtime = runtime
        self.proof: "dict | None" = None
        self.cli_source: "dict | None" = None
        self.rest: "RestClient | None" = None
        self._stdout_lock = threading.Lock()
        self._cancelled: "set[str]" = set()
        self._cancelled_lock = threading.Lock()
        self._stdout = sys.stdout.buffer

    # -- startup ------------------------------------------------------------

    def start(self) -> None:
        started = time.monotonic()
        version_payload = run_cli_json(["version", "--json"])
        cli_version = safe_string(version_payload.get("cliVersion"), 80)
        match = re.match(r"^@salesforce/cli/(\d+)\.(\d+)\.(\d+)$", cli_version)
        if not match or int(match.group(1)) != self.runtime["policy"]["salesforceCliMajor"]:
            raise ReviewError("CLI_VERSION_UNSUPPORTED")
        if tuple(int(part) for part in match.groups()) < MIN_CLI_VERSION:
            # sf org auth show-access-token only exists from 2.136.8 (plugin-org 5.11.0).
            raise ReviewError("CLI_VERSION_UNSUPPORTED")
        token_payload = run_cli_json(
            ["org", "auth", "show-access-token", "--json", "-o", self.runtime["alias"]]
        )
        token = token_payload.get("accessToken")
        if not isinstance(token, str) or not token:
            raise ReviewError("CLI_SCHEMA_MISMATCH")
        display = run_cli_json(["org", "display", "--json", "-o", self.runtime["alias"]])
        instance_url = str(display.get("instanceUrl") or "")
        host = self._validated_host(instance_url)
        display_org_id = str(display.get("id") or display.get("orgId") or "")
        expected_org_id = (
            self.runtime["entry"].get("expectedOrganizationId")
            if self.runtime["pinned"]
            else display_org_id
        )
        if not ORG_ID.match(display_org_id) or display_org_id[:15] != str(expected_org_id)[:15]:
            raise ReviewError("IDENTITY_ORG_ID_MISMATCH")
        if display_org_id[:15] in self.runtime["denied_org_ids"]:
            raise ReviewError("ORG_ID_DENIED")
        self.rest = RestClient(self.runtime, instance_url, self.runtime["review"]["apiVersion"], token)
        # Live probe: proves the token works, freezes the identity, and doubles as the
        # latency baseline. wantSandbox comes from the host shape - a Developer Edition
        # legitimately reports IsSandbox=false (the comment convention from the .mjs).
        record = self.rest.identity_record()
        live_org_id = str(record.get("Id") or "")
        if not ORG_ID.match(live_org_id) or live_org_id[:15] != display_org_id[:15]:
            raise ReviewError("IDENTITY_ORG_ID_MISMATCH")
        want_sandbox = not DEV_EDITION_HOST.match(host)
        if record.get("IsSandbox") is not want_sandbox:
            raise ReviewError("NOT_SANDBOX")
        self.rest.frozen_org_id = live_org_id[:15]
        self.rest.frozen_is_sandbox = record.get("IsSandbox")
        self.proof = {
            "expectedHostMatched": True,
            "expectedOrgIdMatched": True,
            "isSandbox": record.get("IsSandbox") is True,
            # Reaching this point already proves it: the live host passed
            # NON_PRODUCTION_HOST and IsSandbox matched what that host shape implies.
            "nonProduction": True,
        }
        self.cli_source = {
            "kind": "salesforce-cli",
            "version": cli_version,
            "complete": True,
            "retrievedAt": now_iso(),
        }
        log(f"startup: identity frozen for {host} in {int((time.monotonic() - started) * 1000)} ms")

    def _validated_host(self, instance_url: str) -> str:
        try:
            from urllib.parse import urlsplit

            parts = urlsplit(instance_url)
        except ValueError:
            raise ReviewError("CLI_SCHEMA_MISMATCH")
        host = (parts.hostname or "").lower()
        expected_host = (
            str(self.runtime["entry"].get("expectedInstanceHost") or "").lower()
            if self.runtime["pinned"]
            else host
        )
        if (
            parts.scheme != "https"
            or parts.port
            or parts.username
            or parts.password
            or parts.path not in ("", "/")
            or parts.query
            or parts.fragment
            or host != expected_host
            or not NON_PRODUCTION_HOST.match(host)
        ):
            raise ReviewError("IDENTITY_HOST_MISMATCH")
        return host

    # -- protocol -----------------------------------------------------------

    def write_message(self, message: dict) -> None:
        serialized = json.dumps(message, ensure_ascii=False)
        if len(serialized.encode("utf-8")) > MAX_OUTER_MESSAGE_BYTES:
            serialized = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": message.get("id"),
                    "error": {"code": -32000, "message": "CLI_OUTPUT_TOO_LARGE"},
                }
            )
        with self._stdout_lock:
            self._stdout.write(serialized.encode("utf-8") + b"\n")
            self._stdout.flush()

    def call_tool(self, name: str, tool_input: dict) -> dict:
        if not any(tool["name"] == name for tool in TOOL_DEFINITIONS) or not validate_tool_input(name, tool_input):
            envelope = make_envelope(self.runtime, "org-identity", "BLOCKED", warnings=["QUERY_PROFILE_DENIED"])
            return {"content": [{"type": "text", "text": json.dumps(envelope)}], "structuredContent": envelope, "isError": True}
        review_types = {
            "review_org_identity": "org-identity",
            "review_installed_packages": "installed-packages",
            "review_object_contract": "object-contract",
            "review_configured_orgs": "configured-orgs",
            "review_soql_query": "soql-query",
        }
        started = time.monotonic()
        try:
            if name == "review_org_identity":
                result = review_org_identity(self)
            elif name == "review_installed_packages":
                result = review_installed_packages(self)
            elif name == "review_object_contract":
                result = review_object_contract(self, tool_input)
            elif name == "review_configured_orgs":
                result = review_configured_orgs(self)
            elif name == "review_soql_query":
                result = review_soql_query(self, tool_input)
            elif name == "org_limits":
                result = org_limits(self)
            else:
                result = explain_query(self, tool_input)
            is_error = isinstance(result, dict) and result.get("status") == "BLOCKED"
        except ReviewError as error:
            if name in ENVELOPE_TOOLS:
                result = error_envelope(self.runtime, review_types[name], error, self.proof)
            else:
                elapsed = int((time.monotonic() - started) * 1000)
                result = {
                    "error": error.code,
                    "detail": f"{name} failed after {elapsed} ms ({error.code}). "
                    + ("Narrow the query or lower the LIMIT and retry." if error.code == "REST_TIMEOUT" else "See stderr on the server side."),
                }
            is_error = True
        except Exception:  # noqa: BLE001 - an unhandled exception must not kill the loop
            result = {"error": "INTERNAL_ERROR"}
            is_error = True
        elapsed_ms = int((time.monotonic() - started) * 1000)
        log(f"call {name}: {elapsed_ms} ms error={is_error}")
        text = json.dumps(result, ensure_ascii=False)
        if len(text.encode("utf-8")) > MAX_RESULT_BYTES:
            # CLI_OUTPUT_TOO_LARGE is an incomplete-class warning in the schema, so the
            # oversize envelope must go out as INCOMPLETE (with the session proof), not
            # BLOCKED - a BLOCKED envelope with it would fail the consumer's validation.
            over = (
                error_envelope(
                    self.runtime,
                    review_types.get(name, "org-identity"),
                    ReviewError("CLI_OUTPUT_TOO_LARGE", "INCOMPLETE"),
                    self.proof,
                )
                if name in ENVELOPE_TOOLS
                else {"error": "RESULT_TOO_LARGE", "detail": "Narrow the query; the result exceeded the payload cap."}
            )
            return {"content": [{"type": "text", "text": json.dumps(over)}], "structuredContent": over, "isError": True}
        return {"content": [{"type": "text", "text": text}], "structuredContent": result, "isError": is_error}

    def handle_message(self, message: dict, pool: ThreadPoolExecutor) -> None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return
        method = message.get("method")
        message_id = message.get("id")
        if method == "notifications/cancelled":
            request_id = (message.get("params") or {}).get("requestId")
            with self._cancelled_lock:
                self._cancelled.add(str(request_id))
            return
        if not isinstance(method, str) or message_id is None:
            return
        if method == "initialize":
            self.write_message(
                {
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "result": {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": "sf-harness-salesforce-review", "version": SERVER_VERSION},
                        "instructions": "Use only normalized evidence. " + STEER_EVIDENCE
                        + " review_soql_query returns single-source sandbox rows UNREDACTED so unusual configuration can be understood - they are bounded and timestamped, nothing more. Never paste raw rows into a design, an entry or an ADO artifact.",
                    },
                }
            )
            return
        if method == "ping":
            self.write_message({"jsonrpc": "2.0", "id": message_id, "result": {}})
            return
        if method == "tools/list":
            self.write_message({"jsonrpc": "2.0", "id": message_id, "result": {"tools": TOOL_DEFINITIONS}})
            return
        if method == "tools/call":
            params = message.get("params") or {}

            def run_call() -> None:
                result = self.call_tool(params.get("name"), params.get("arguments") or {})
                with self._cancelled_lock:
                    if str(message_id) in self._cancelled:
                        # Cancelled mid-flight: the client stopped waiting; a late
                        # response for this id must be suppressed (spec minimum).
                        return
                self.write_message({"jsonrpc": "2.0", "id": message_id, "result": result})

            pool.submit(run_call)
            return
        self.write_message(
            {"jsonrpc": "2.0", "id": message_id, "error": {"code": -32601, "message": "Method not found"}}
        )

    def serve(self) -> None:
        if os.name == "nt":  # Windows: text mode turns \n into \r\n and corrupts framing
            import msvcrt

            msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
            msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
        stdin = sys.stdin.buffer
        with ThreadPoolExecutor(max_workers=THREAD_POOL_SIZE) as pool:
            buffered = 0
            for raw_line in stdin:
                buffered = len(raw_line)
                if buffered > MAX_OUTER_MESSAGE_BYTES:
                    log("blocked: MCP_SCHEMA_MISMATCH (oversized frame)")
                    raise SystemExit(2)
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    log("blocked: MCP_SCHEMA_MISMATCH (unparseable frame)")
                    raise SystemExit(2)
                self.handle_message(message, pool)
            pool.shutdown(wait=True)  # EOF: drain in-flight calls, then exit cleanly


def main(argv: "list[str]") -> int:
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--org", required=True)
    # --mode is accepted for launcher compatibility and ignored (the review surface
    # is the only surface this server has).
    parser.add_argument("--mode", required=False)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        _fatal_startup("CONFIG_INVALID")
    try:
        runtime = load_runtime(args.org)
        server = Server(runtime)
        server.start()
        server.serve()
    except ReviewError as error:
        _fatal_startup(error.code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
