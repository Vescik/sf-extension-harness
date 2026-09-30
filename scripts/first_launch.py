#!/usr/bin/env python3
"""First-launch onboarding for the brain-core Salesforce Copilot harness.

Human-run setup helper for Windows, macOS, and Linux. It is NOT an agent tool and is
deliberately not on the role-guard allowlist. It:

  1. checks prerequisites (git, node, npm, sf, python);
  2. installs the pinned dependencies (npm ci, hash-pinned pip lock into .venv);
  3. creates config/harness.local.json from the tracked example if absent;
  4. collects ADO configuration interactively;
  5. walks you through authorizing each NON-PRODUCTION org (``sf org login web``) —
     sandbox, scratch org, or Developer Edition — auto-fills the expected host +
     organization id from ``sf org display``, and refuses anything else. The live
     ``Organization.IsSandbox`` value must match what the hostname implies (true for a
     sandbox or scratch org, false for a Developer Edition), which is the proof
     (mirrors SAFE-ENV-001);
  6. runs the static repository validator and reports local-config status.

External capabilities are proven at the point of use, not here: the Salesforce review
MCP proves the selected org's non-production identity when it starts, and ADO scope is
checked on every tool call.

Salesforce MCP is review (read-only) mode only. That restriction applies to the MCP facade,
not to the Developer role: Salesforce org changes use direct ``sf``/``sfdx`` commands, and
every real deployment requires fresh chat confirmation for its exact target and scope.

Credentials are never handled by this script: ``sf org login web`` performs interactive
browser OAuth, and no tokens/passwords are read, printed, or stored.

Usage:
    python scripts/first_launch.py                 # full guided run
    python scripts/first_launch.py --skip-install  # deps already present
    python scripts/first_launch.py --non-interactive  # checks + install + verify only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
try:
    from scripts.ado_config import ado_config_error
    from scripts import salesforce_operation_policy as sf_policy
except ModuleNotFoundError:
    from ado_config import ado_config_error
    import salesforce_operation_policy as sf_policy

from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "harness.local.json"
EXAMPLE_PATH = REPO_ROOT / "config" / "harness.example.json"
SANDBOX_HOST_PATTERN = re.compile(
    r"^[a-z0-9][a-z0-9-]*--[a-z0-9][a-z0-9-]*\.sandbox\.my\.salesforce\.com$"
)
SCRATCH_HOST_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*\.scratch\.my\.salesforce\.com$")
# Onboarding accepted sandboxes only while the runtime had already admitted scratch orgs and
# Developer Editions (owner decision 2026-07-31), so the one org shape a tester is most likely
# to have could not be onboarded at all and had to be hand-written into the config.
DEV_EDITION_HOST_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*\.develop\.my\.salesforce\.com$")
PRODUCTION_HOST_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*(?:\.my)?\.salesforce\.com$")
MIN_PYTHON = (3, 11)
IS_WINDOWS = os.name == "nt"


def _enable_ansi() -> bool:
    if not sys.stdout.isatty():
        return False
    if IS_WINDOWS:
        os.system("")  # enables VT processing on Windows 10+ consoles
    return True


_COLOR = _enable_ansi()


def _c(code: str, message: str) -> str:
    return f"\033[{code}m{message}\033[0m" if _COLOR else message


def step(message: str) -> None:
    print(_c("36", f"\n==> {message}"))


def ok(message: str) -> None:
    print(_c("32", f"    [ok] {message}"))


def warn(message: str) -> None:
    print(_c("33", f"    [!]  {message}"))


def fail(message: str) -> None:
    print(_c("31", f"    [x]  {message}"))
    raise SystemExit(1)


def which(tool: str) -> str | None:
    """Resolve a tool on PATH (handles .cmd/.exe shims on Windows)."""
    return shutil.which(tool)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command without a shell; the first element must be a resolved path."""
    return subprocess.run(cmd, **kwargs)


def tool_version(path: str, args: list[str]) -> str:
    try:
        out = run([path, *args], capture_output=True, text=True, timeout=60)
        first = (out.stdout or out.stderr).strip().splitlines()
        return first[0] if first else "present"
    except Exception:  # noqa: BLE001 - reporting only
        return "present"


def venv_python() -> Path:
    if IS_WINDOWS:
        candidate = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = REPO_ROOT / ".venv" / "bin" / "python"
    return candidate


def check_prerequisites() -> dict[str, str]:
    step("Checking prerequisites")
    if sys.version_info < MIN_PYTHON:
        warn(
            f"this interpreter is Python {sys.version_info.major}.{sys.version_info.minor}; "
            f"the supported baseline is {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ (CI certifies 3.12). "
            "Install a current Python from python.org before a fresh setup."
        )
    tools = {"git": ["--version"], "node": ["--version"], "npm": ["--version"], "sf": ["--version"]}
    resolved: dict[str, str] = {}
    for name, args in tools.items():
        path = which(name)
        if path is None:
            fail(f"{name} is not installed or not on PATH.")
        resolved[name] = path
        ok(f"{name} -> {tool_version(path, args)}")
    ok(f"python -> {sys.version.split()[0]} ({sys.executable})")
    return resolved


def install_dependencies(npm_path: str) -> None:
    step("Installing pinned dependencies")
    print("    npm ci --ignore-scripts (exact lockfile; do not use npm install)")
    if run([npm_path, "ci", "--ignore-scripts"], cwd=REPO_ROOT).returncode != 0:
        fail("npm ci failed.")
    ok("node_modules installed from package-lock.json")

    venv_dir = REPO_ROOT / ".venv"
    if not venv_dir.exists():
        print("    creating .venv")
        if sys.version_info < MIN_PYTHON:
            fail(
                f"refusing to create a fresh .venv with Python "
                f"{sys.version_info.major}.{sys.version_info.minor}; re-run with Python "
                f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}+."
            )
        if run([sys.executable, "-m", "venv", str(venv_dir)]).returncode != 0:
            fail("could not create .venv")
    py = venv_python()
    if not py.exists():
        fail(f"venv python not found at {py}")
    print("    pip install --require-hashes -r requirements-dev.lock")
    result = run(
        [
            str(py),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--require-hashes",
            "-r",
            str(REPO_ROOT / "requirements-dev.lock"),
        ]
    )
    if result.returncode != 0:
        fail("pip install (hash-pinned) failed.")
    ok("Python validation dependencies installed into .venv")


def prepare_config() -> None:
    step("Preparing local configuration")
    if not CONFIG_PATH.exists():
        shutil.copyfile(EXAMPLE_PATH, CONFIG_PATH)
        ok("created config/harness.local.json from the example template")
    else:
        ok("config/harness.local.json already exists (will update in place)")


def prompt(text: str) -> str:
    try:
        return input(f"    {text}: ").strip()
    except EOFError:
        return ""


def sf_json(sf_path: str, args: list[str]) -> dict | None:
    try:
        out = run([sf_path, *args, "--json"], capture_output=True, text=True, timeout=120)
        return json.loads(out.stdout)
    except Exception:  # noqa: BLE001 - any failure means "could not read"
        return None


def collect_ado(pending: dict[str, object]) -> None:
    step("Azure DevOps configuration (press Enter to keep the current value)")
    print("    One organization and project per workspace; saved only in config/harness.local.json.")
    ado_org = prompt("ADO organization")
    ado_project = prompt("ADO project")
    ado_query = prompt("ADO release saved-query id")
    if ado_org:
        pending["ado.organization"] = ado_org
    if ado_project:
        pending["ado.project"] = ado_project
    if ado_query:
        pending["ado.releaseQueryId"] = ado_query


def classify_non_production_host(host: str) -> tuple[bool, bool] | None:
    """Return (recognized, expected_is_sandbox) for a non-production host, else None.

    `Organization.IsSandbox` is true for a sandbox or scratch org and false for a Developer
    Edition, so the live value is checked against what the hostname implies rather than
    being required to be true. Production hosts match nothing here and are refused.
    """
    if SANDBOX_HOST_PATTERN.match(host) or SCRATCH_HOST_PATTERN.match(host):
        return True, True
    if DEV_EDITION_HOST_PATTERN.match(host):
        return True, False
    return None


def classify_salesforce_host(host: str) -> tuple[str, bool] | None:
    """Return the technical org type and expected IsSandbox for a Salesforce host."""
    if host in {"login.salesforce.com", "test.salesforce.com", "auth.salesforce.com"}:
        return None
    if SANDBOX_HOST_PATTERN.fullmatch(host):
        return "sandbox", True
    if SCRATCH_HOST_PATTERN.fullmatch(host):
        return "scratch", True
    if DEV_EDITION_HOST_PATTERN.fullmatch(host):
        return "developer-edition", False
    if PRODUCTION_HOST_PATTERN.fullmatch(host):
        return "production", False
    return None


def authorize_salesforce_orgs(sf_path: str, pending: dict[str, object]) -> None:
    step("Salesforce org authorization for the read-only review MCP")
    warn(
        "Production, Sandbox, Scratch Org, and Developer Edition use the same read workflow. "
        "Organization.IsSandbox must match the resolved instance host."
    )
    while True:
        env_name = prompt("Org environment [dev/uat/stage/prod; Enter to finish]").lower()
        if not env_name:
            break
        if env_name not in sf_policy.ENVIRONMENTS:
            warn("Choose dev, uat, stage or prod explicitly. qa has no automatic mapping.")
            continue
        alias = prompt(f"Alias to use for '{env_name}'")
        if not sf_policy.ALIAS.fullmatch(alias):
            warn("invalid alias; use 1-80 alphanumeric, dot, underscore or hyphen characters")
            continue

        login_url = prompt("Salesforce login URL [https://login.salesforce.com]")
        if not login_url:
            login_url = "https://login.salesforce.com"

        print(f"    Launching browser login for alias '{alias}' ...")
        login = run([sf_path, "org", "login", "web", "--instance-url", login_url, "--alias", alias])
        if login.returncode != 0:
            warn(f"sf login did not complete for '{alias}'; skipping.")
            continue

        display = sf_json(sf_path, ["org", "display", "--target-org", alias])
        if not display or display.get("status") != 0:
            warn(f"could not read org identity for '{alias}'; skipping.")
            continue
        result = display.get("result") or {}
        instance_url = result.get("instanceUrl") or ""
        org_id = result.get("id") or result.get("orgId") or ""
        host = urlsplit(instance_url).hostname or ""

        classified = classify_salesforce_host(host)
        if classified is None:
            warn(
                f"REFUSED: '{host}' is not a recognized Salesforce instance host. Not recorded."
            )
            continue
        environment_type, expected_is_sandbox = classified

        query = sf_json(
            sf_path,
            [
                "data",
                "query",
                "--query",
                "SELECT IsSandbox FROM Organization LIMIT 1",
                "--target-org",
                alias,
            ],
        )
        records = ((query or {}).get("result") or {}).get("records") or []
        if not records or records[0].get("IsSandbox") is not expected_is_sandbox:
            warn(
                f"REFUSED: live Organization.IsSandbox is not {str(expected_is_sandbox).lower()} "
                f"for '{alias}', which its host signature requires. Not recorded."
            )
            continue

        pending[f"org.{alias}"] = {"environment": env_name, "alias": alias, "host": host,
                                  "orgId": org_id, "environmentType": environment_type}
        ok(f"recorded '{env_name}': {alias} -> {host} ({org_id}); environment type: {environment_type}")


def collect_review_allowlist(pending: dict[str, object]) -> None:
    step("Read-only Salesforce review MCP")
    answer = prompt("Enable bounded Salesforce reads after setting an object allowlist? [y/N]").lower()
    if answer not in {"y", "yes"}:
        warn("Salesforce review enablement is unchanged; review.enabled must be true to start MCP.")
        return
    objects = [part.strip() for part in prompt(
        "Comma-separated object API names (required; use * only after reviewing that scope)"
    ).split(",") if part.strip()]
    if not objects:
        warn("No object allowlist entered; Salesforce review was not enabled.")
        return
    pending["review.enabled"] = True
    pending["review.objects"] = objects


def apply_config(pending: dict[str, object]) -> None:
    step("Writing configuration")
    with CONFIG_PATH.open(encoding="utf-8") as fh:
        cfg = json.load(fh)

    # Remove only exact, untouched org rows from the shipped template when the
    # user actually supplies orgs. Never match/delete by environment, and preserve
    # partially edited rows so their unresolved identity is reported for repair.
    if any(key.startswith("org.") for key in pending):
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        templates = [org for org in example.get("salesforce", {}).get("orgs", [])
                     if all(PLACEHOLDER.fullmatch(str(org.get(key, ""))) for key in
                            ("alias", "expectedOrganizationId"))
                     and PLACEHOLDER.search(str(org.get("expectedInstanceHost", "")))]
        cfg["salesforce"]["orgs"] = [org for org in cfg["salesforce"]["orgs"]
                                      if not any(org == template for template in templates)]

    ado_org = pending.get("ado.organization")
    if ado_org:
        cfg["ado"]["organization"] = ado_org
        # Keep owner-approved non-ADO origins. Replace all old ADO origins so a
        # changed organization cannot retain the previous organization's scope.
        origins = cfg["ado"].get("allowedHttpsOrigins", [])
        if not isinstance(origins, list):
            raise ValueError("ADO configuration error: ado.allowedHttpsOrigins must be an array. Set it in config/harness.local.json.")
        retained = []
        for origin in origins:
            try:
                host = urlsplit(origin).hostname if isinstance(origin, str) else None
            except ValueError:
                host = None
            if (host in {"dev.azure.com", "visualstudio.com"}
                    or (host and host.endswith((".dev.azure.com", ".visualstudio.com")))):
                continue
            retained.append(origin)
        cfg["ado"]["allowedHttpsOrigins"] = [f"https://dev.azure.com/{ado_org}", *retained]
    if pending.get("ado.project"):
        cfg["ado"]["project"] = pending["ado.project"]
    if pending.get("ado.releaseQueryId"):
        cfg["ado"]["releaseQueryId"] = pending["ado.releaseQueryId"]
    if any(key.startswith("ado.") for key in pending):
        error = ado_config_error(cfg)
        if error:
            raise ValueError(error)

    for key, entry in pending.items():
        if not key.startswith("org."):
            continue
        env_name = sf_policy.normalize_environment(entry.get("environment", key[4:]))
        orgs = cfg["salesforce"]["orgs"]
        matching = [org for org in orgs if org.get("alias") == entry["alias"]]
        if len(matching) > 1:
            raise ValueError("Duplicate org alias; resolve configuration before onboarding")
        related = [org for org in orgs if org in matching or
                   str(org.get("expectedOrganizationId", ""))[:15] == entry["orgId"][:15]]
        for org in related:
            if org.get("environment") in ("prod", "production") and env_name != "prod":
                raise ValueError("Known production identity cannot be reclassified by onboarding")
            if org not in matching and sf_policy.normalize_environment(org.get("environment")) != env_name:
                raise ValueError("The same Org ID cannot have conflicting environment classifications")
            if org in matching and org.get("expectedOrganizationId") and org["expectedOrganizationId"][:15] != entry["orgId"][:15]:
                raise ValueError("Alias identity changed; resolve the conflict explicitly")
        updated = {"alias": entry["alias"], "environment": env_name,
                   "expectedInstanceHost": entry["host"], "expectedOrganizationId": entry["orgId"]}
        if matching:
            matching[0].update(updated)
        else:
            orgs.append(updated)

    if pending.get("review.enabled") is True:
        cfg["salesforce"]["review"]["enabled"] = True
    if pending.get("review.objects"):
        cfg["salesforce"]["review"]["allowedObjectApiNames"] = pending["review.objects"]

    with CONFIG_PATH.open("w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    ok("config/harness.local.json saved")


PLACEHOLDER = re.compile(r"<[^>]+>")
SCHEMA_PATH = REPO_ROOT / "schemas" / "harness-config.schema.json"


def placeholder_paths(node: object, prefix: str = "") -> list[str]:
    """Dotted paths of every string value still holding an unresolved <PLACEHOLDER>."""
    paths: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            paths.extend(placeholder_paths(value, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            paths.extend(placeholder_paths(value, f"{prefix}[{index}]"))
    elif isinstance(node, str) and PLACEHOLDER.search(node):
        paths.append(prefix or "<root>")
    return paths


def local_config_findings(config_text: str, schema_text: "str | None") -> list[str]:
    """Pure setup-level diagnostics for config/harness.local.json.

    Returns human-readable findings; an empty list means the file parses, matches the
    schema (when one is supplied and jsonschema is importable), and holds no
    unresolved placeholders. This reports configuration shape only — whether
    Salesforce or ADO actually work is proven by their own runtimes at the point of
    use.
    """
    try:
        config = json.loads(config_text)
    except json.JSONDecodeError as exc:
        return [f"config/harness.local.json is invalid JSON: {exc}"]
    findings = [
        f"unresolved placeholder at {path}" for path in placeholder_paths(config)
    ]
    ado_error = ado_config_error(config)
    if ado_error:
        findings.append(ado_error)
    if schema_text is not None:
        try:
            from jsonschema import Draft202012Validator  # deferred: pre-install python may lack it

            schema = json.loads(schema_text)
            for error in sorted(
                Draft202012Validator(schema).iter_errors(config),
                key=lambda item: list(item.path),
            ):
                location = ".".join(str(part) for part in error.path) or "<root>"
                findings.append(f"config schema validation failed at {location}: {error.message}")
        except ModuleNotFoundError:
            findings.append(
                "config schema check skipped: jsonschema is not importable by this "
                "interpreter (install dependencies, then re-run)"
            )
    salesforce = config.get("salesforce") if isinstance(config, dict) else None
    if isinstance(salesforce, dict):
        for index, entry in enumerate(salesforce.get("orgs", [])):
            if not isinstance(entry, dict):
                continue
            value = entry.get("environment")
            if value in ("development", "production", "qa"):
                target = sf_policy.LEGACY_ENVIRONMENTS.get(value, "an explicitly selected dev/uat/stage/prod")
                findings.append(f"salesforce.orgs[{index}].environment ({entry.get('alias')}): migrate {value} to {target}")
        review = salesforce.get("review")
        if isinstance(review, dict) and review.get("enabled") is not True:
            findings.append("salesforce.review.enabled must be true before starting the read-only Salesforce MCP")
    return findings


def verify() -> "tuple[bool, list[str] | None]":
    step("Verifying the harness")
    py = venv_python()
    runner = str(py) if py.exists() else sys.executable
    validate = run([runner, str(REPO_ROOT / "scripts" / "validate_harness.py")], cwd=REPO_ROOT)
    if not CONFIG_PATH.exists():
        return validate.returncode == 0, None
    schema_text = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.exists() else None
    findings = local_config_findings(
        CONFIG_PATH.read_text(encoding="utf-8"), schema_text
    )
    package_dir = REPO_ROOT / "node_modules" / "@azure-devops" / "mcp"
    try:
        package = json.loads((package_dir / "package.json").read_text(encoding="utf-8"))
        dependency_valid = (isinstance(package, dict) and package.get("name") == "@azure-devops/mcp"
                            and package.get("version") == "2.8.1"
                            and (package_dir / "dist" / "index.js").is_file())
    except (OSError, ValueError):
        dependency_valid = False
    if not dependency_valid:
        findings.append("ADO dependency is missing or does not match version 2.8.1; run npm ci --ignore-scripts.")
    return validate.returncode == 0, findings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="skip npm ci / pip install (dependencies already present)",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="only run checks + install + verify; no prompts or org authorization",
    )
    args = parser.parse_args()
    os.chdir(REPO_ROOT)

    resolved = check_prerequisites()

    if args.skip_install:
        step("Skipping dependency install (--skip-install)")
    else:
        install_dependencies(resolved["npm"])

    prepare_config()

    pending: dict[str, object] = {}
    if args.non_interactive:
        warn(
            "Non-interactive: leaving ADO and Salesforce org values as-is. "
            "Fill them later and re-run without --non-interactive."
        )
    else:
        collect_ado(pending)
        authorize_salesforce_orgs(resolved["sf"], pending)
        collect_review_allowlist(pending)

    if pending:
        apply_config(pending)

    validate_ok, config_findings = verify()

    step("Summary")
    if validate_ok:
        ok("static repository validation passed")
    else:
        warn("validate_harness reported issues (see above)")
    if config_findings is None:
        warn("config/harness.local.json does not exist yet; re-run this script to create it")
    elif config_findings:
        warn("local setup needs follow-up:")
        for finding in config_findings:
            warn(f"  - {finding}")
        warn("Workflows that need these values will fail closed until they are filled in.")
    else:
        ok("config/harness.local.json parses, matches the schema, and has no placeholders")
    print(
        "\n    Salesforce and ADO are validated when their tools run: the Salesforce "
        "review MCP proves\n    the selected org's identity at startup, "
        "and ADO scope is checked on every\n    tool call. Optional org diagnostic: "
        "python scripts/verify_salesforce_org.py --org <alias>."
    )
    print(_c("36", "\nNext steps:"))
    print("  - In VS Code, select the .venv interpreter (Python: Select Interpreter).")
    print("  - Start ado-readonly in VS Code and complete the connector's interactive OAuth sign-in.")
    print("  - Restart ado-readonly after changing ado.organization or ado.project.")
    print("  - Verify one Work Item and one wiki page in the configured project; setup checks do not prove ADO access.")
    print(
        "  - Start the Salesforce MCP; when prompted for \"sf_review_org\", enter an "
        "authorized alias."
    )
    print(
        "  - The Salesforce MCP is review-only; Developer org changes use direct sf/sfdx "
        "on dev/uat/stage, with fresh chat confirmation before every real deploy. "
        "Production CLI permits only verified metadata retrieve."
    )
    print("  - config/harness.local.json is gitignored and never leaves this machine.")


if __name__ == "__main__":
    main()
