#!/usr/bin/env python3
"""Deterministic structural and contract validation for the Copilot brain-core."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import traceback
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Iterable

try:
    import yaml
    from jsonschema import Draft202012Validator
except ImportError as exc:  # system interpreters lack the dev deps; name the remedy
    print(
        f"validate_harness: missing dev dependency ({getattr(exc, 'name', None) or exc}); "
        "run through the repo .venv or `pip install -r requirements-dev.lock`",
        file=sys.stderr,
    )
    raise SystemExit(1)

try:
    from schema_format import FORMAT_CHECKER
except ModuleNotFoundError:  # imported as scripts.validate_harness by unit tests
    from scripts.schema_format import FORMAT_CHECKER

try:
    from knowledge_digest import canonical_digest
except ModuleNotFoundError:  # imported as scripts.validate_harness by unit tests
    from scripts.knowledge_digest import canonical_digest

try:
    from validate_handover_output import template_fixed_texts
except ModuleNotFoundError:  # imported as scripts.validate_harness by unit tests
    from scripts.validate_handover_output import template_fixed_texts


ROOT = Path(__file__).resolve().parents[1]
# Reserved, deliberately synthetic identifiers owned by this harness's test fixtures.
# They may appear only under tests/ and evals/fixtures; runtime authority surfaces
# (.github, .ai, config, schemas, scripts) must never depend on or mention them.
# Legal Salesforce names (e.g. a real team's Invoice__c) are NOT screened here —
# provenance and lifecycle rules, not name denylists, govern real metadata.
RESERVED_FIXTURE_TOKENS = (
    "HarnessEngagement",
    "HarnessInvoice",
    "HarnessBilling",
    "ExampleManagedObject__c",
)


def reserved_fixture_leaks(text: str) -> list[str]:
    """Return the reserved test-fixture tokens present in runtime-authority text."""
    return [token for token in RESERVED_FIXTURE_TOKENS if token in text]
BUILT_IN_AGENTS = {"agent", "ask", "plan", "edit"}
ALLOWED_TOOLS = {
    "read",
    "search",
    "edit/editFiles",
    "execute/runInTerminal",
    "web/fetch",
    "vscode/askQuestions",
    "agent",
    "knowledge/*",
    "ado-readonly/*",
    "salesforce-readonly/review_org_identity",
    "salesforce-readonly/review_installed_packages",
    "salesforce-readonly/review_object_contract",
    "salesforce-readonly/review_configured_orgs",
    "salesforce-readonly/review_soql_query",
    "salesforce-readonly/org_limits",
    "salesforce-readonly/explain_query",
    "solution-design/design_open",
    "solution-design/design_record",
    "solution-design/design_check",
    "solution-design/design_submit",
}
# Internal runtime stages/retired tools that are never model-facing. Granting one of these —
# or a `solution-design/*` wildcard — is a contract failure, not a convenience. The retired
# 18-tool surface stays here so a stale agent file fails loudly instead of loading silently.
FORBIDDEN_SOLUTION_DESIGN_GRANTS = {
    "solution-design/*",
    "solution-design/design_apply",
    "solution-design/design_context",
    "solution-design/design_import_repository_receipt",
    "solution-design/design_import_knowledge_reference",
    "solution-design/design_import_soql_envelope",
    "solution-design/design_request_human_input",
    "solution-design/design_request_candidate_decision",
    "solution-design/design_request_writer_transfer",
    "solution-design/design_start_development",
    "solution-design/design_review_candidate",
    "solution-design/design_report_divergence",
    "solution-design/design_record_recheck",
    "solution-design/design_record_verification",
    "solution-design/design_request_implementation_review",
    "solution-design/design_review_implementation",
}
LEGACY_TOOLS = {"readFile", "editFiles", "runInTerminal", "fetch", "codebase", "githubRepo"}
REQUIRED_SETTINGS = (
    "github.copilot.chat.codeGeneration.useInstructionFiles",
    "chat.includeApplyingInstructions",
    "chat.includeReferencedInstructions",
    "chat.instructionsFilesLocations",
    "chat.promptFilesLocations",
    "chat.agentFilesLocations",
    "chat.useAgentSkills",
    "chat.agentSkillsLocations",
    "chat.useAgentsMdFile",
    "chat.hookFilesLocations",
    "chat.useCustomAgentHooks",
    "chat.useCustomizationsInParentRepositories",
)
# Phase 1 of the context-first rebuild: the naming-convention, code-review, and
# decision-format placeholders left with organization-principles and re-enter with
# docs/design-guides.md in phase 2. Only the shared-sandbox rule remains always-on.
EXPECTED_HUMAN_PLACEHOLDERS = {
    "<TU_WSTAW_ZASADY_PRACY_NA_WSPOLDZIELONYM_SANDBOXIE>",
}


class Audit:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.checks = 0

    def require(self, condition: bool, message: str) -> None:
        self.checks += 1
        if not condition:
            self.errors.append(message)

    def extend(self, messages: Iterable[str]) -> None:
        for message in messages:
            self.require(False, message)


def relative(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def required_text(path: Path, audit: Audit) -> str:
    """Read a named file, recording an audit error instead of raising when it is unreadable.

    check_required_files only records a missing file; a later unconditional read_text
    would raise and discard every already-collected finding."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        audit.require(False, f"{relative(path)}: unreadable: {exc}")
        return ""


def frontmatter(path: Path, audit: Audit) -> tuple[dict[str, Any], str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        audit.require(False, f"{relative(path)}: unreadable: {exc}")
        return {}, ""
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
    audit.require(match is not None, f"{relative(path)}: missing YAML frontmatter")
    if match is None:
        return {}, text
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        audit.require(False, f"{relative(path)}: invalid YAML frontmatter: {exc}")
        return {}, text[match.end() :]
    audit.require(isinstance(data, dict), f"{relative(path)}: frontmatter must be an object")
    return (data if isinstance(data, dict) else {}), text[match.end() :]


def load_json(path: Path, audit: Audit) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        audit.require(False, f"{relative(path)}: invalid JSON: {exc}")
        return {}


def load_jsonc(path: Path, audit: Audit) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
        return json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        audit.require(False, f"{relative(path)}: invalid JSONC: {exc}")
        return {}


def load_yaml(path: Path, audit: Audit) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        audit.require(False, f"{relative(path)}: invalid YAML: {exc}")
        return {}


def check_required_files(audit: Audit) -> None:
    required = (
        "AGENTS.md",
        "README.md",
        "SETUP.md",
        "sf-harness.code-workspace",
        ".github/copilot-instructions.md",
        ".github/hooks/safety.json",
        ".github/CODEOWNERS",
        ".github/pull_request_template.md",
        ".vscode/settings.json",
        ".vscode/mcp.json",
        ".github/mcp.json",
        "scripts/knowledge_mcp_server.mjs",
        "config/harness.example.json",
        "schemas/harness-config.schema.json",
        "requirements-dev.lock",
        "scripts/verify_salesforce_org.py",
        "scripts/salesforce_review_server.py",
        "scripts/force_app_knowledge.py",
        "scripts/render_repo_map.py",
        "config/repo-map-seed.json",
        ".ai/repo-map.md",
        ".ai/repo-map.json",
        "schemas/ado-wiki-cache.schema.json",
        ".ai/contracts/execution-contract.md",
        ".ai/contracts/tool-capabilities.md",
        ".ai/contracts/source-authority.md",
        "schemas/force-app-knowledge-inventory.schema.json",
        "schemas/force-app-knowledge-resolve.schema.json",
        "schemas/knowledge-entry.schema.json",
        "schemas/knowledge-feature.schema.json",
        "scripts/knowledge_store.py",
        "scripts/knowledge_search.py",
        "scripts/validate_handover_output.py",
        "docs/knowledge-one-file-contract.md",
        "schemas/salesforce-org-review-evidence.schema.json",
        "config/knowledge-policy.json",
        "config/salesforce-review-policy.json",
        "docs/grounding-architecture.md",
        "sfdx-project.json",
        "package.json",
        "package-lock.json",
        "manifest/package.xml",
        "config/project-scratch-def.json",
        ".forceignore",
        ".prettierignore",
        ".prettierrc",
        "eslint.config.js",
    )
    for name in required:
        audit.require((ROOT / name).is_file(), f"required file is missing: {name}")
    audit.require(not any((ROOT / ".github/chatmodes").glob("*")), "legacy chat mode files remain")
    audit.require((ROOT / "force-app").is_dir(), "required Salesforce metadata directory is missing: force-app")
    audit.require(not (ROOT / "salesforce").exists(), "legacy nested salesforce/ project remains")


def check_salesforce_project(audit: Audit, root: Path = ROOT) -> None:
    salesforce_root = root
    project = load_json(salesforce_root / "sfdx-project.json", audit)
    if not isinstance(project, dict):
        audit.require(False, "sfdx-project.json must be a JSON object")
        project = {}
    package_directories = project.get("packageDirectories", []) if isinstance(project, dict) else []
    audit.require(
        any(
            isinstance(entry, dict)
            and entry.get("path") == "force-app"
            and entry.get("default") is True
            for entry in package_directories
        ),
        "sfdx-project.json must define force-app as the default package directory",
    )
    audit.require(project.get("name") == "sf-harness-salesforce", "embedded SFDX project name is unexpected")
    audit.require(project.get("namespace") == "", "embedded SFDX scaffold must not bake in a package namespace")
    audit.require(
        project.get("sfdcLoginUrl") == "https://test.salesforce.com",
        "embedded SFDX project must default to the Salesforce sandbox login URL",
    )
    api_version = project.get("sourceApiVersion")
    audit.require(
        isinstance(api_version, str) and re.fullmatch(r"\d+\.0", api_version) is not None,
        "embedded SFDX sourceApiVersion must use the major.0 form",
    )
    audit.require(
        (salesforce_root / "force-app/main/default").is_dir(),
        "embedded SFDX project is missing force-app/main/default",
    )
    audit.require(
        (salesforce_root / ".git").is_dir(),
        "the root SFDX project must use the repository's existing Git directory",
    )

    manifest_path = salesforce_root / "manifest/package.xml"
    try:
        manifest_root = ET.parse(manifest_path).getroot()
    except (OSError, ET.ParseError) as exc:
        audit.require(False, f"manifest/package.xml: invalid XML: {exc}")
        manifest_root = None
    if manifest_root is not None:
        namespace = "{http://soap.sforce.com/2006/04/metadata}"
        audit.require(manifest_root.tag == f"{namespace}Package", "Salesforce manifest root must be Metadata API Package")
        manifest_version = manifest_root.findtext(f"{namespace}version")
        audit.require(manifest_version == api_version, "Salesforce manifest and SFDX API versions must match")
        type_names = [
            item.findtext(f"{namespace}name")
            for item in manifest_root.findall(f"{namespace}types")
        ]
        audit.require(all(type_names), "Salesforce manifest types must have names")
        audit.require(len(type_names) == len(set(type_names)), "Salesforce manifest type names must be unique")

    package = load_json(salesforce_root / "package.json", audit)
    package_lock = load_json(salesforce_root / "package-lock.json", audit)
    audit.require(package.get("private") is True, "package.json must remain private")
    required_scripts = {"lint", "prettier:verify"}
    audit.require(
        required_scripts.issubset(package.get("scripts", {})),
        "package.json must expose the root lint and formatting checks",
    )
    audit.require(
        package_lock.get("packages", {}).get("", {}).get("name") == package.get("name"),
        "package-lock.json must match package.json",
    )


def check_customizations(audit: Audit, root: Path = ROOT) -> None:
    agent_paths = sorted((root / ".github/agents").glob("*.agent.md"))
    prompt_paths = sorted((root / ".github/prompts").glob("*.prompt.md"))
    skill_paths = sorted((root / ".github/skills").glob("*/SKILL.md"))
    instruction_paths = sorted((root / ".github/instructions").glob("*.instructions.md"))

    agents: dict[str, dict[str, Any]] = {}
    for path in agent_paths:
        data, _ = frontmatter(path, audit)
        name = data.get("name")
        audit.require(name == path.name.removesuffix(".agent.md"), f"{relative(path)}: name must match filename")
        audit.require(data.get("target") == "vscode", f"{relative(path)}: target must be vscode")
        audit.require(bool(data.get("description")), f"{relative(path)}: description is required")
        audit.require(bool(data.get("argument-hint")), f"{relative(path)}: argument-hint is required")
        tools = data.get("tools")
        tools_ok = isinstance(tools, list) and all(isinstance(tool, str) for tool in tools)
        audit.require(tools_ok, f"{relative(path)}: tools must be an array of tool-name strings")
        if tools_ok:
            forbidden = sorted(set(tools) & FORBIDDEN_SOLUTION_DESIGN_GRANTS)
            audit.require(
                not forbidden,
                f"{relative(path)}: grants an internal Solution Design operation or wildcard "
                f"{forbidden}; human transition operations are never model-facing tools",
            )
        if tools_ok:
            unknown = sorted(set(tools) - ALLOWED_TOOLS)
            legacy = sorted(set(tools) & LEGACY_TOOLS)
            audit.require(not unknown, f"{relative(path)}: unknown tools: {unknown}")
            audit.require(not legacy, f"{relative(path)}: legacy tools: {legacy}")
            if data.get("agents"):
                audit.require("agent" in tools, f"{relative(path)}: agents allowlist requires the agent tool")
        if isinstance(name, str):
            agents[name] = data

    for name, data in agents.items():
        path_label = f".github/agents/{name}.agent.md"
        for child in data.get("agents", []) or []:
            audit.require(child in agents, f"{path_label}: unknown delegated agent {child!r}")
        handoffs = data.get("handoffs", []) or []
        audit.require(isinstance(handoffs, list), f"{path_label}: handoffs must be an array")
        if isinstance(handoffs, list):
            for index, handoff in enumerate(handoffs):
                label = f"{path_label}: handoff {index + 1}"
                audit.require(isinstance(handoff, dict), f"{label} must be an object")
                if not isinstance(handoff, dict):
                    continue
                audit.require(bool(handoff.get("label")), f"{label} needs label")
                audit.require(bool(handoff.get("prompt")), f"{label} needs prompt")
                target = handoff.get("agent")
                audit.require(target in agents or target in BUILT_IN_AGENTS, f"{label} has unknown agent {target!r}")
                audit.require(handoff.get("send") is False, f"{label} must remain human-triggered with send: false")

    reviewer_tools = {
        tool
        for tool in (agents.get("reviewer", {}).get("tools") or [])
        if isinstance(tool, str)
    }
    audit.require("edit/editFiles" not in reviewer_tools, "reviewer must not edit")
    audit.require("salesforce-development/*" not in reviewer_tools, "reviewer must not mutate Salesforce")
    reviewer_hooks = agents.get("reviewer", {}).get("hooks", {})
    audit.require("--role reviewer" in json.dumps(reviewer_hooks, default=str), "reviewer role guard is required")
    # Owner decision 2026-08-11: reviewer.agent.md is the single source of the review lane's
    # tool grants. A prompt-level `tools` key overrides the agent's list, and the override had
    # silently removed `knowledge/*` while the skill (and §7 Set A) require `knowledge_context`.
    # The prompt must inherit, so a future grant is reviewed in exactly one place.
    review_prompt, _ = frontmatter(ROOT / ".github/prompts/check-against-principles.prompt.md", audit)
    audit.require(
        "tools" not in review_prompt,
        ".github/prompts/check-against-principles.prompt.md must not declare `tools`: the review "
        "lane inherits reviewer.agent.md, which is the single source of its grants",
    )
    audit.require(
        "knowledge/*" in reviewer_tools,
        "reviewer needs `knowledge/*`: the check-against-principles skill runs `knowledge_context` "
        "as its step-1 lookup (§7 Set A)",
    )
    # Every grant the review procedure actually spends, pinned against the procedure. A skill
    # step whose tool is missing does not fail loudly — it degrades into the agent guessing,
    # which is how the prompt-level override went unnoticed. `execute/runInTerminal` is the
    # sharpest of these: step 7 must run `entry-verify-citations --envelope` BEFORE the verdict,
    # so without the terminal the citation gate is skipped and `SAFE` is issued unverified.
    for tool, reason in (
        ("search", "the review reads a diff and repository files, not single known paths"),
        (
            "execute/runInTerminal",
            "step 7 runs `knowledge_store.py entry-verify-citations --envelope` before the verdict",
        ),
        ("salesforce-readonly/review_soql_query", "the review reconciles design claims against org records"),
        ("salesforce-readonly/review_object_contract", "package-namespace claims need the object contract"),
        ("salesforce-readonly/review_org_identity", "evidence must name the org it came from"),
        ("salesforce-readonly/review_installed_packages", "package version is part of the evidence"),
    ):
        audit.require(tool in reviewer_tools, f"reviewer needs `{tool}`: {reason}")
    audit.require(
        not any(tool.startswith("ado-readonly") for tool in reviewer_tools),
        "reviewer must not gain ADO access: the review subject is the persisted design or the "
        "exact diff (owner decision 2026-08-11)",
    )

    prompt_names: list[str] = []
    for path in prompt_paths:
        data, body = frontmatter(path, audit)
        name = data.get("name")
        audit.require(name == path.name.removesuffix(".prompt.md"), f"{relative(path)}: name must match filename")
        audit.require(bool(data.get("description")), f"{relative(path)}: description is required")
        audit.require(bool(data.get("argument-hint")), f"{relative(path)}: argument-hint is required")
        prompt_agent = data.get("agent")
        audit.require(prompt_agent in agents or prompt_agent in BUILT_IN_AGENTS, f"{relative(path)}: unknown agent {prompt_agent!r}")
        tools = data.get("tools")
        if tools is not None:
            tools_ok = isinstance(tools, list) and all(isinstance(tool, str) for tool in tools)
            audit.require(tools_ok, f"{relative(path)}: tools must be an array of tool-name strings")
            if tools_ok:
                audit.require(not (set(tools) - ALLOWED_TOOLS), f"{relative(path)}: unknown tools {sorted(set(tools) - ALLOWED_TOOLS)}")
                forbidden = sorted(set(tools) & FORBIDDEN_SOLUTION_DESIGN_GRANTS)
                audit.require(
                    not forbidden,
                    f"{relative(path)}: grants an internal Solution Design operation or wildcard "
                    f"{forbidden}; human transition operations are never model-facing tools",
                )
        audit.require("skill](" in body.lower(), f"{relative(path)}: prompt must link its skill")
        if isinstance(name, str):
            prompt_names.append(name)

    public_skill_names: list[str] = []
    for path in skill_paths:
        data, body = frontmatter(path, audit)
        folder = path.parent.name
        audit.require(data.get("name") == folder, f"{relative(path)}: name must match skill folder")
        description = data.get("description")
        audit.require(isinstance(description, str) and 1 <= len(description) <= 1024, f"{relative(path)}: description must be 1..1024 characters")
        audit.require(data.get("user-invocable") is False, f"{relative(path)}: internal skill must set user-invocable: false")
        if data.get("user-invocable") is not False and isinstance(data.get("name"), str):
            public_skill_names.append(data["name"])

    public_commands = prompt_names + public_skill_names
    audit.require(len(public_commands) == len(set(public_commands)), "public slash-command names collide")

    for path in instruction_paths:
        data, _ = frontmatter(path, audit)
        audit.require(bool(data.get("description")), f"{relative(path)}: description is required")
        # Context-first architecture (plan 2026-08-07): instructions load contextually by
        # path scope, not through role machinery. Every instruction file must say where it
        # applies; managed-package boundaries must apply everywhere.
        audit.require(bool(data.get("applyTo")), f"{relative(path)}: instructions must declare an applyTo scope")
    mp_data, _ = frontmatter(ROOT / ".github/instructions/managed-package.instructions.md", audit)
    audit.require(mp_data.get("applyTo") == "**", "managed-package.instructions.md must apply to every file (applyTo: \"**\")")

    for path in agent_paths:
        data, _body = frontmatter(path, audit)
        # The rule that matters for a handoff prompt: it may never depend on chat context.
        # Durable state lives in work-items/<id>-<slug>/, so a handoff cites files, not the
        # conversation above it.
        for handoff in data.get("handoffs", []) or []:
            if isinstance(handoff, dict):
                prompt = str(handoff.get("prompt", "")).lower()
                audit.require(" above" not in prompt and "previous response" not in prompt, f"{relative(path)}: handoff depends on chat context")


def check_links(audit: Audit) -> None:
    paths = [ROOT / ".github/copilot-instructions.md", ROOT / "AGENTS.md", ROOT / "README.md", ROOT / "SETUP.md"]
    paths.extend((ROOT / ".github").glob("**/*.md"))
    paths.extend((ROOT / ".ai/contracts").glob("*.md"))
    paths.extend((ROOT / ".ai/templates").glob("*.md"))
    pattern = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
    for path in sorted(set(paths)):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for raw in pattern.findall(text):
            target = raw.strip().split("#", 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            resolved = (path.parent / target).resolve()
            audit.require(resolved.exists(), f"{relative(path)}: broken relative link {raw!r}")


def check_settings_and_mcp(audit: Audit) -> None:
    settings = load_jsonc(ROOT / ".vscode/settings.json", audit)
    workspace = load_json(ROOT / "sf-harness.code-workspace", audit)
    workspace_settings = workspace.get("settings", {}) if isinstance(workspace, dict) else {}
    for key in REQUIRED_SETTINGS:
        audit.require(key in settings, f".vscode/settings.json: missing {key}")
        audit.require(key in workspace_settings, f"sf-harness.code-workspace: missing {key}")
        if key in settings and key in workspace_settings:
            audit.require(settings[key] == workspace_settings[key], f"workspace setting differs from folder setting: {key}")
    audit.require(settings.get("chat.useCustomizationsInParentRepositories") is False, "parent repository customizations must be disabled")

    # Terminal auto-approval must not weaken the safety model.
    for blanket in ("chat.tools.global.autoApprove", "chat.tools.autoApprove"):
        audit.require(settings.get(blanket) is not True, f"blanket tool auto-approval is forbidden: {blanket}")
        audit.require(workspace_settings.get(blanket) is not True, f"blanket tool auto-approval is forbidden in workspace: {blanket}")
    auto = settings.get("chat.tools.terminal.autoApprove")
    if auto is not None:
        audit.require(
            workspace_settings.get("chat.tools.terminal.autoApprove") == auto,
            "terminal auto-approve list differs between folder and workspace settings",
        )
        audit.require(isinstance(auto, dict), "chat.tools.terminal.autoApprove must be an object")
        if isinstance(auto, dict):
            for denied in ("sf", "sfdx", "rm", "del"):
                audit.require(auto.get(denied) is False, f"terminal auto-approve must deny '{denied}'")
    workspace_folders = workspace.get("folders", []) if isinstance(workspace, dict) else []
    folders = {
        (item.get("name"), item.get("path"))
        for item in workspace_folders
        if isinstance(item, dict)
    }
    audit.require(folders == {("brain-core", ".")}, "workspace must contain only the root SFDX folder named brain-core")
    for item in workspace_folders:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        path = Path(item["path"])
        audit.require(
            not path.is_absolute() and ".." not in path.parts,
            f"workspace folder {item.get('name')!r} must not escape the harness repository",
        )

    mcp = load_json(ROOT / ".vscode/mcp.json", audit)
    servers = mcp.get("servers", {}) if isinstance(mcp, dict) else {}
    audit.require(
        set(servers) == {"ado-readonly", "salesforce-readonly", "knowledge"},
        "MCP server set is unexpected",
    )
    ado = servers.get("ado-readonly", {})
    # Local stdio @azure-devops/mcp (owner decision 2026-07-14): the hosted endpoint did not
    # honor the X-MCP-Toolsets header, so the local server with actually-honored -d domain args
    # replaces it. Read-only is policy (hook + role guard), no longer server-enforced.
    #
    # 2026-08-05 (rebuild P3): the launcher moved from `npx -y` to the lockfile-resolved local
    # entrypoint. Runtime package acquisition executes whatever the registry serves at start
    # time; a pinned version does not pin the fetch. The package now carries a dependency
    # admission record and lockfile integrity, and the workspace starts offline.
    audit.require(ado.get("type") == "stdio", "ADO MCP must be the local stdio server")
    audit.require(
        ado.get("command") == "node",
        "ADO MCP must launch the locally installed entrypoint with node, never acquire a "
        "package at runtime",
    )
    audit.require(ado.get("cwd") == "${workspaceFolder}", "ADO MCP must start in the workspace root")
    audit.require(
        ado.get("args")
        == [
            "node_modules/@azure-devops/mcp/dist/index.js",
            "${env:ADO_ORGANIZATION}",
            "-d",
            "work-items",
            "wiki",
            "search",
        ],
        "ADO MCP args must resolve the lockfile-installed entrypoint, take the organization "
        "from the environment (checked per-call by the safety hook), and bound the domains to "
        "work-items/wiki/search (the Test Plans domain retired with the QA sync lane; linked "
        "Test Cases are read as Work Items)",
    )
    audit.require(
        "@azure-devops/mcp" in json.dumps(load_json(ROOT / "package.json", audit) or {}),
        "@azure-devops/mcp must be a declared dependency, not a runtime acquisition",
    )
    audit.require(not any(item.get("id") == "ado_org" for item in mcp.get("inputs", [])), "independent ADO organization prompt is forbidden")
    for name in ("salesforce-readonly",):
        server = servers.get(name, {})
        audit.require(server.get("command") == "node", f"{name}: wrapper must run with node")
        audit.require(server.get("cwd") == "${workspaceFolder}", f"{name}: wrapper must start in the direct-folder-safe root SFDX workspace")
        audit.require("scripts/start_salesforce_mcp.mjs" in server.get("args", []), f"{name}: guarded wrapper is required")
        args = server.get("args", [])
        audit.require(
            "--mode" in args and args[args.index("--mode") + 1] == "review",
            f"{name}: MCP never mutates the org — only review mode may be configured",
        )
    audit.require(
        "salesforce-development" not in servers,
        "MCP is read-only by the 2026-07-14 decision; the development/write server must not return",
    )
    # Knowledge MCP (owner decision 2026-08-04: MCP is the only named read surface for
    # agents). The server binds no org and takes no inputs; both host configs must point
    # at the same guarded wrapper.
    knowledge = servers.get("knowledge", {})
    audit.require(knowledge.get("command") == "node", "knowledge: wrapper must run with node")
    audit.require(
        knowledge.get("args") == ["scripts/knowledge_mcp_server.mjs"],
        "knowledge: exactly the guarded wrapper, no extra args — it binds no org and takes no secrets",
    )
    # No design MCP server exists; registering one would reintroduce a process surface that
    # writes design state outside the reviewed work-items/ files.
    audit.require(
        "solution-design" not in servers,
        ".vscode/mcp.json must not register the retired solution-design server",
    )

    cli_mcp = load_json(ROOT / ".github/mcp.json", audit)
    cli_servers = cli_mcp.get("mcpServers", {}) if isinstance(cli_mcp, dict) else {}
    audit.require(
        set(cli_servers) == {"knowledge"},
        ".github/mcp.json (Copilot CLI) carries exactly the knowledge server — org-bound "
        "servers stay in .vscode/mcp.json where inputs exist",
    )
    cli_knowledge = cli_servers.get("knowledge", {})
    audit.require(cli_knowledge.get("type") == "local", ".github/mcp.json knowledge: type must be local")
    audit.require(cli_knowledge.get("command") == "node", ".github/mcp.json knowledge: wrapper must run with node")
    audit.require(
        cli_knowledge.get("args") == knowledge.get("args"),
        "the CLI and VS Code knowledge servers must launch the same wrapper",
    )
    serialized = json.dumps(mcp).lower()
    audit.require(
        "${workspacefolder:" not in serialized,
        "MCP configuration must not use a named workspaceFolder variable; direct folder opens cannot resolve it",
    )
    for forbidden in ("@latest", "allow_all_orgs", "default_target_org", "login.salesforce.com", "npx"):
        audit.require(forbidden not in serialized, f"MCP config contains forbidden token {forbidden!r}")
    # OS-level MCP sandbox keys were removed with the write server (2026-07-14): the fleet is
    # Windows (where VS Code cannot sandbox MCP) and the remaining servers are read-only by
    # construction — the wrapper, review facade, and safety hook are the enforcement layers.
    audit.require("sandbox" not in mcp, "the MCP sandbox block was retired with the write server; do not reintroduce it without a recorded decision")
    audit.require("sandboxEnabled" not in json.dumps(mcp), "sandboxEnabled was retired with the write server")

    tasks_document = load_json(ROOT / ".vscode/tasks.json", audit)
    audit.require(
        "${workspacefolder:" not in json.dumps(tasks_document).lower(),
        "VS Code tasks must use direct-folder-safe unqualified workspaceFolder variables",
    )
    tasks = tasks_document.get("tasks", []) if isinstance(tasks_document, dict) else []
    tasks_by_label = {
        item.get("label"): item
        for item in tasks
        if isinstance(item, dict) and isinstance(item.get("label"), str)
    }
    required_salesforce_tasks = {
        "Salesforce: Format Check",
        "Salesforce: Lint",
        "Salesforce: Check",
    }
    audit.require(
        required_salesforce_tasks.issubset(tasks_by_label),
        "VS Code tasks must expose the embedded Salesforce project checks",
    )
    for label in required_salesforce_tasks - {"Salesforce: Check"}:
        task = tasks_by_label.get(label, {})
        audit.require(
            task.get("options", {}).get("cwd") == "${workspaceFolder}",
            f"{label} must execute in the root SFDX workspace folder",
        )
    hooks = load_json(ROOT / ".github/hooks/safety.json", audit)
    pre = hooks.get("hooks", {}).get("PreToolUse", []) if isinstance(hooks, dict) else []
    audit.require(len(pre) == 1, "exactly one global PreToolUse hook is required")
    if pre:
        audit.require(pre[0].get("command") == "python3 scripts/copilot_safety_hook.py", "global safety hook command differs")
        audit.require("timeout" in pre[0] and "timeoutSec" not in pre[0], "hook must use the current timeout property")
        audit.require(pre[0].get("timeout", 0) >= 10, "global hook timeout must accommodate guarded command parsing")

    launcher = required_text(ROOT / "scripts/start_salesforce_mcp.mjs", audit)
    # Owner decision 2026-08-04 retired the launcher's per-alias grants, write lane and
    # startup identity subprocess; plan-2026-08-09 F-3 repointed it at the Python REST
    # facade with an interpreter-resolving probe (local, no org contact). These markers
    # pin what must survive both slimmings.
    for marker in (
        "production-like",
        'environment === "production"',
        "org changes are human-only",
        "salesforce_review_server.py",
    ):
        audit.require(marker in launcher, f"Salesforce MCP launcher is missing runtime gate: {marker}")
    # The launcher must never contact an org itself: identity is proven in the facade.
    # (The interpreter probe is local by construction - it imports a Python module.)
    for forbidden in ('"sf"', "org display", "show-access-token", "@salesforce/mcp"):
        audit.require(forbidden not in launcher, f"the launcher must not contact orgs or vendor MCP: {forbidden}")
    audit.require('"data,metadata,testing,code-analysis"' not in launcher, "broad Salesforce data-write toolset is forbidden")
    # Live facade (Python, plan-2026-08-09 F-2): pin the walls that make never-production
    # and read-only true. The .mjs facade and its pins were deleted in F-4.
    py_facade = required_text(ROOT / "scripts/salesforce_review_server.py", audit)
    for marker in (
        "ALIAS_PRODUCTION_LIKE",
        "NON_PRODUCTION_HOST",
        "denied_org_ids",
        "fail_closed",
        "contains_sensitive_material",
        "IDENTITY_ORG_ID_MISMATCH",
    ):
        audit.require(marker in py_facade, f"Python review facade is missing runtime gate: {marker}")

    development_frontmatter, _ = frontmatter(ROOT / ".github/agents/developer.agent.md", audit)
    audit.require("execute/runInTerminal" in (development_frontmatter.get("tools") or []), "developer needs guarded terminal execution")
    audit.require("--role developer" in json.dumps(development_frontmatter.get("hooks", {}), default=str), "developer role guard is required")
    doc_prompt, _ = frontmatter(ROOT / ".github/prompts/document-metadata-change.prompt.md", audit)
    audit.require("salesforce-development/*" not in doc_prompt.get("tools", []), "Documentation prompt must not inherit Salesforce write tools")
    audit.require("execute/runInTerminal" in doc_prompt.get("tools", []), "Documentation prompt needs guarded terminal execution (read-only orientation)")
    release_prompt, _ = frontmatter(ROOT / ".github/prompts/release-handover.prompt.md", audit)
    audit.require("execute/runInTerminal" in release_prompt.get("tools", []), "Release prompt needs guarded terminal execution (handover render check, citation verify)")
    role_guard = required_text(ROOT / "scripts/copilot_role_guard.py", audit)
    audit.require(role_guard.count('".cache/ado-items/"') >= 3, "ADO cache must be writable by its three consuming roles")
    audit.require('".cache/test-cases/"' not in role_guard, "the Test Case cache write permission retired with the QA sync lane and must not return")
    audit.require("QA_TEST_PLAN_PATTERN" in role_guard, "Test Strategist needs the exact-path QA test-plan write rule (D18)")
    strategist_prefixes = re.search(r'"test-strategist":\s*\(([^)]*)\)', role_guard)
    audit.require(
        strategist_prefixes is not None and '"work-items/"' not in strategist_prefixes.group(1),
        "Test Strategist must not gain the broad work-items/ prefix; the QA plan write is the "
        "exact-path QA_TEST_PLAN_PATTERN rule only (D18)",
    )
    audit.require('".cache/org-usage/"' in role_guard, "Config Investigator must be able to author org-usage probes-files (contract §6.6)")
    # Documentation wording is not pinned here: the read-only MCP model, the retrieve
    # confirmation, and credential isolation are enforced by the machine checks above and the
    # hook/facade test suites; docs are covered by the link check and AGENTS.md size bound.


def check_ci(audit: Audit) -> None:
    path = ROOT / ".github/workflows/harness-ci.yml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        audit.require(False, f"{relative(path)}: invalid workflow YAML: {exc}")
        return
    audit.require(data.get("permissions", {}).get("contents") == "read", "CI permissions must be contents: read")
    serialized = path.read_text(encoding="utf-8")
    uses = re.findall(r"^\s*uses:\s*([^\s#]+)", serialized, flags=re.MULTILINE)
    audit.require(bool(uses), "CI must use explicit actions")
    for value in uses:
        revision = value.rsplit("@", 1)[-1]
        audit.require(bool(re.fullmatch(r"[0-9a-f]{40}", revision)), f"CI action is not SHA-pinned: {value}")
    audit.require("ubuntu-latest" in serialized and "windows-latest" in serialized, "CI must cover Linux and Windows")
    audit.require("requirements-dev.lock" in serialized, "CI must install the resolved dependency lock")
    audit.require("npm run prettier:verify" in serialized, "CI must run the root Salesforce formatting gate")
    audit.require("npm run lint" in serialized, "CI must run the root lint gate")
    codeowners = required_text(ROOT / ".github/CODEOWNERS", audit)
    for owned_path in ("/sfdx-project.json", "/force-app/", "/manifest/", "/tests/e2e/"):
        audit.require(owned_path in codeowners, f"CODEOWNERS is missing root Salesforce path: {owned_path}")
    audit.require("/salesforce/" not in codeowners, "CODEOWNERS retains the legacy nested Salesforce path")
    for canary in (
        "config/harness.local.json",
        ".cache/knowledge-proposals/example.yaml",
        ".env",
        "force-app/main/default/lwc/jsconfig.json",
        "deploy-options.json",
    ):
        audit.require(git_check_ignore(canary) == 0, f"local/generated path is not ignored: {canary}")
    # The inverse contract: normal Salesforce source must stay trackable. Exit code 1 is the only
    # "not ignored" answer; >1 is a git failure and must not be mistaken for trackability.
    for canary in ("force-app/main/default/classes/TrackedCanary.cls",):
        audit.require(git_check_ignore(canary) == 1, f"Salesforce source path is unexpectedly ignored: {canary}")


def git_check_ignore(path: str) -> int:
    """Return git check-ignore's exit code for path: 0 ignored, 1 not ignored, >1 error."""
    completed = subprocess.run(
        ["git", "check-ignore", "--quiet", path],
        cwd=ROOT,
        check=False,
        timeout=5,
    )
    return completed.returncode


def check_secret_signatures(audit: Audit) -> None:
    patterns = (
        re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"),
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
        re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
        re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}\b", re.IGNORECASE),
        re.compile(r"\bforce://[^\s]+@[^\s]+"),
    )
    completed = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    audit.require(completed.returncode == 0, "could not enumerate repository files for secret scan")
    for name in completed.stdout.splitlines():
        path = ROOT / name
        if not path.is_file() or path.stat().st_size > 1_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in patterns:
            audit.require(pattern.search(text) is None, f"{name}: high-confidence secret signature detected")


# §7 Set A: the surfaces whose step-1 SOURCE lookup must run through the entry index.
# The membership is declared HERE, explicitly — this list is the single source of truth
# (decoupled from the retired knowledge master plan on the owner's 2026-08-10 decision:
# parsing a frozen planning document coupled runtime validation to it;
# moving a surface now means editing this tuple in the same commit that edits
# the surface, and the git diff is the review trail).
# 2026-08-04 (owner decision, MCP-only definitions): the step-1 surface is the MCP tool,
# not the CLI literal. The CLI menu survives only in search-knowledge as the operator
# fallback, which is deliberately NOT a Set A surface — the gate this design replaced
# counted a list that included the menu owner and was green while measuring the wrong
# thing.
SET_A_SURFACES = (
    "solution-design",
    "check-against-principles",
    "check-feature-coverage",
    "adhoc-fix",
    "investigate-config-records",
    "generate-technical-documentation",
    "investigate-object",
    "developer.agent.md",
    "test-strategist.agent.md",
)
SET_A_CALL = "knowledge_context"
# The second half of a correct step-1 lookup. A context lookup without the re-read rule lets
# an agent cite a row carrying `hydrated: false`, which contract §14.2 rules uncitable — the
# retrieval defect P0–P4 made visible, re-introduced at the last hop. Wave 2 claimed the rule was
# present in all eight Set A surfaces when it was present in two, so §7 asserts both tokens.
SET_A_HYDRATION_RULE = "hydrated"


def consumer_surface_path(root: Path, name: str) -> Path:
    """A §7 surface name resolved to its file — agents by filename, skills by directory."""

    if name.endswith(".agent.md"):
        return root / ".github/agents" / name
    return root / ".github/skills" / name / "SKILL.md"


def check_knowledge_consumer_sets(audit: Audit, root: Path = ROOT) -> None:
    """§7 Set A: every declared surface runs the step-1 source lookup AND its re-read rule.

    Set B (the preserved layer-2 registry call) retired with the claim registry
    (v1 retirement P2b, owner D-C 2026-08-03). Membership lives in SET_A_SURFACES above.
    """

    for name in SET_A_SURFACES:
        path = consumer_surface_path(root, name)
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        audit.require(
            SET_A_CALL in text,
            f"§7 Set A ({len(SET_A_SURFACES)} surfaces): {relative(path)} no longer runs "
            f"`{SET_A_CALL}` as its step-1 source lookup — remove it from SET_A_SURFACES "
            f"only together with the design change that retires the surface",
        )
        audit.require(
            SET_A_HYDRATION_RULE in text,
            f"§7 Set A ({len(SET_A_SURFACES)} surfaces): {relative(path)} names the step-1 "
            f"command but not the `{SET_A_HYDRATION_RULE}` re-read rule — an agent may then "
            f"cite a row contract §14.2 rules uncitable",
        )


def check_skill_commands(audit: Audit) -> None:
    """Guarded-command instructions in skills must be role-guard-valid and cross-OS.

    The role guard (copilot_role_guard.allowed_role_command) only permits the harness scripts when
    invoked as `python scripts/<name>.py …` with forward slashes. A bare `scripts/<name>.py` (no
    interpreter) or a backslash path is denied — which is exactly what made agents "get lost" on the
    first command. Fail closed here so the skill text and the guard can never drift apart again.
    """

    guarded = "force_app_knowledge|validate_handover_output"
    bare = re.compile(r"`\s*scripts/(?:" + guarded + r")\.py(?:\s|`)")
    backslash = re.compile(r"`[^`]*(?:scripts\\|\.venv\\)")
    for skill in sorted((ROOT / ".github/skills").glob("*/SKILL.md")):
        text = skill.read_text(encoding="utf-8")
        for match in bare.finditer(text):
            audit.require(
                False,
                f"{relative(skill)}: guarded command lacks a python interpreter prefix "
                f"(role guard will deny it): {match.group(0)!r}",
            )
        for match in backslash.finditer(text):
            audit.require(
                False,
                f"{relative(skill)}: guarded command uses a backslash path (POSIX shlex mangles it): {match.group(0)!r}",
            )


def check_release_handover_contract(audit: Audit) -> None:
    """The handover template stays the single structure source; the skill quotes none of it.

    scripts/validate_handover_output.py derives the expected document shape from the template
    at every run, keyed on the repeat-per-item marker, so template edits are enforced without
    any code change. The skill must load the template by path and instruct the render
    self-check, and must not embed any of the template's fixed fallback texts: a quoted
    literal desynchronizes the moment a human edits the template (T11 follow-up).
    """

    template = required_text(ROOT / ".ai/templates/release-handover.md", audit)
    audit.require(
        template.count("<!-- repeat-per-item -->") == 1,
        "release-handover template must contain exactly one <!-- repeat-per-item --> marker "
        "(scripts/validate_handover_output.py keys per-item repetition on it; keep it when "
        "editing the template)",
    )
    skill = required_text(ROOT / ".github/skills/generate-release-handover/SKILL.md", audit)
    audit.require(
        "../../../.ai/templates/release-handover.md" in skill,
        "generate-release-handover must load the template by path (single structure source)",
    )
    audit.require(
        "scripts/validate_handover_output.py" in skill,
        "generate-release-handover must instruct the render self-check",
    )
    for text in template_fixed_texts(template):
        audit.require(
            text not in skill,
            f"generate-release-handover quotes a template fixed text ({text!r}); reference "
            "the template's fallback generically so template edits cannot desynchronize "
            "the skill",
        )


def check_python_yaml_safety(audit: Audit) -> None:
    """Enforce the safe_load-only invariant so an unsafe YAML loader cannot be introduced.

    PyYAML's arbitrary-code-execution class is only reachable through the unsafe loader family
    (full/unsafe/plain load) or an explicit non-safe loader argument. All parsing in this repo
    uses the safe loader/dumper; this gate keeps it that way in CI.
    """

    forbidden = re.compile(r"\byaml\.(?:unsafe_load|full_load|load)\s*\(|\bLoader\s*=")
    for directory in ("scripts", "tests"):
        for path in sorted((ROOT / directory).rglob("*.py")):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            match = forbidden.search(text)
            audit.require(
                match is None,
                f"{relative(path)}: unsafe YAML loader is forbidden (use yaml.safe_load); found {match.group(0) if match else ''!r}",
            )


def apply_patch(instance: Any, dotted: str, value: Any) -> None:
    """Apply one dotted-path patch in place; KeyError/TypeError when the path does not
    resolve in the base fixture (the caller reports the offending path by name)."""
    target = instance
    parts = dotted.split(".")
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value


def check_schemas_and_evals(audit: Audit) -> None:
    mappings = {
        "ado-item-cache.schema.json": ("ado-item.complete.json", "ado-item.partial.json"),
        "ado-wiki-cache.schema.json": ("ado-wiki.complete.json", "ado-wiki.partial.json"),
        "output-envelope.schema.json": (
            "output.incomplete.json",
            "output.release-handover.valid.json",
        ),
    }
    for schema_name, fixture_names in mappings.items():
        schema_path = ROOT / "schemas" / schema_name
        schema = load_json(schema_path, audit)
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as exc:  # jsonschema exposes several schema-error subclasses
            audit.require(False, f"{relative(schema_path)}: invalid JSON Schema: {exc}")
            continue
        validator = Draft202012Validator(schema, format_checker=FORMAT_CHECKER)
        for fixture_name in fixture_names:
            fixture_path = ROOT / "evals/fixtures" / fixture_name
            fixture = load_json(fixture_path, audit)
            errors = sorted(validator.iter_errors(fixture), key=lambda item: list(item.path))
            audit.require(not errors, f"{relative(fixture_path)}: schema failure: {errors[0].message if errors else ''}")

    negative_path = ROOT / "evals/fixtures/invalid-contract-states.json"
    negative = load_json(negative_path, audit)
    for case in negative.get("cases", []):
        schema = load_json(ROOT / "schemas" / case["schema"], audit)
        instance = deepcopy(
            load_json(ROOT / "evals/fixtures" / case["baseFixture"], audit)
        )
        patched = True
        for dotted, value in case.get("patch", {}).items():
            try:
                apply_patch(instance, dotted, value)
            except (KeyError, TypeError):
                audit.require(
                    False,
                    f"invalid-contract-states.json: case {case.get('id')}: patch path "
                    f"{dotted!r} does not resolve in {case.get('baseFixture')}",
                )
                patched = False
        if not patched:
            continue
        errors = list(Draft202012Validator(schema).iter_errors(instance))
        audit.require(bool(errors), f"negative contract fixture was incorrectly accepted: {case.get('id')}")

    for filename, minimum in (("safety-scenarios.yaml", 10), ("agent-scenarios.yaml", 10)):
        path = ROOT / "evals" / filename
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            audit.require(False, f"{relative(path)}: invalid evaluation YAML: {exc}")
            continue
        audit.require(data.get("schemaVersion") == 1, f"{relative(path)}: schemaVersion must be 1")
        scenarios = data.get("scenarios", [])
        audit.require(isinstance(scenarios, list) and len(scenarios) >= minimum, f"{relative(path)}: expected at least {minimum} scenarios")
        ids = [scenario.get("id") for scenario in scenarios if isinstance(scenario, dict)]
        audit.require(len(ids) == len(set(ids)), f"{relative(path)}: scenario IDs must be unique")


def check_grounding_contracts(audit: Audit) -> None:
    root_instructions = required_text(ROOT / ".github/copilot-instructions.md", audit)
    agents_md = required_text(ROOT / "AGENTS.md", audit)
    markdown_link = re.compile(r"(?<!!)\[[^\]]+\]\([^)]+\)")
    audit.require(not markdown_link.search(root_instructions), "always-on safety kernel must not pull role resources through Markdown links")
    # 120 → 150 (2026-08-03): the cap keeps this file from growing into a second instruction
    # set, and 150 words preserves that intent. The extra room buys the host statement — which
    # host actually enforces the per-agent role guard — and that is exactly the compatibility
    # question this shim exists to answer.
    audit.require(len(agents_md.split()) <= 150, "AGENTS.md must remain a bounded compatibility shim")
    # Context-first phase 1: the kernel is orientation-only; the non-negotiable rules
    # moved to managed-package.instructions.md, whose applyTo "**" keeps them always-on.
    boundaries = required_text(ROOT / ".github/instructions/managed-package.instructions.md", audit)
    # SAFE-ENV-001 prose was removed 2026-08-08 (owner decision): the production block
    # is hook-enforced (copilot_safety_hook denies with that label); prose no longer duplicates it.
    for marker in ("MP-NS-001", "SAFE-UNTRUST-001", "SAFE-TOOL-001", "SAFE-HUMAN-001"):
        audit.require(marker in boundaries, f"always-on boundary rule is missing: {marker}")

    principle_paths = [ROOT / ".github/copilot-instructions.md"] + sorted(
        (ROOT / ".github/instructions").glob("*.instructions.md")
    )
    source_ids: set[str] = set()
    for path in principle_paths:
        source_ids.update(re.findall(r"\*\*((?:SAFE|MP|ORG|SF)-[A-Z0-9-]+)\s+—", required_text(path, audit)))

    # Owner decision 2026-08-04: every rule ID is DECLARED EXACTLY ONCE across the Principle
    # sources, so a rule citation is always unambiguous.
    declarations: list[str] = []
    for path in principle_paths:
        declarations.extend(
            re.findall(r"\*\*((?:SAFE|MP|ORG|SF)-[A-Z0-9-]+)\s+—", required_text(path, audit))
        )
    duplicate_ids = sorted({rule_id for rule_id in declarations if declarations.count(rule_id) > 1})
    audit.require(not duplicate_ids, f"rule IDs declared more than once across Principle sources: {duplicate_ids}")
    audit.require(bool(source_ids), "Principle sources must declare at least one rule ID")

    for data_name, schema_name in (
        ("config/knowledge-policy.json", "knowledge-policy.schema.json"),
        ("config/knowledge-extraction.json", "knowledge-extraction.schema.json"),
        ("config/salesforce-review-policy.json", "salesforce-review-policy.schema.json"),
    ):
        data = load_json(ROOT / data_name, audit)
        schema = load_json(ROOT / "schemas" / schema_name, audit)
        errors = sorted(
            Draft202012Validator(schema, format_checker=FORMAT_CHECKER).iter_errors(data),
            key=lambda item: list(item.path),
        )
        audit.require(not errors, f"{data_name}: schema failure: {errors[0].message if errors else ''}")

    # Every tracked schema must itself be a valid Draft 2020-12 schema. Discovery replaces
    # a hand-kept list: adding a schema file makes it validated, with no second list to edit.
    # Fixture mappings (positive AND negative) stay explicit in check_schemas_and_evals and
    # above, because the mapping itself carries contract meaning.
    for schema_path in sorted((ROOT / "schemas").glob("*.schema.json")):
        schema = load_json(schema_path, audit)
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as exc:
            audit.require(False, f"{relative(schema_path)}: invalid JSON Schema: {exc}")

    # Knowledge entry-check and feature-check are domain gates owned by CI (explicit,
    # attributable steps in harness-ci.yml) and by the VS Code Test task locally; the static
    # validator no longer re-runs them as subprocesses.

    runtime_roots = (ROOT / ".github", ROOT / ".ai", ROOT / "config", ROOT / "schemas", ROOT / "scripts")
    for base in runtime_roots:
        for path in base.glob("**/*"):
            if path.resolve() == Path(__file__).resolve():
                continue
            if path.is_file() and path.stat().st_size <= 1_000_000:
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                leaks = reserved_fixture_leaks(text)
                audit.require(not leaks, f"{relative(path)}: reserved test-fixture identifier leaked into runtime authority: {', '.join(leaks)}")

    package = load_json(ROOT / "package.json", audit)
    audit.require(package.get("private") is True, "package.json must remain private")
    # F-4 (plan-2026-08-09): the vendor MCP child is retired with the .mjs facade; its
    # reappearance in the dependency tree would resurrect the per-call-child architecture.
    audit.require(
        "@salesforce/mcp" not in package.get("dependencies", {}),
        "the retired @salesforce/mcp dependency must not return (REST facade replaced it)",
    )
    package_lock = load_json(ROOT / "package-lock.json", audit)
    audit.require(
        "node_modules/@salesforce/mcp" not in package_lock.get("packages", {}),
        "package-lock.json must not resolve the retired @salesforce/mcp",
    )
    harness_example = load_json(ROOT / "config/harness.example.json", audit)
    example_review = harness_example.get("salesforce", {}).get("review", {})
    audit.require(example_review.get("enabled") is False, "example Salesforce review must be disabled")
    audit.require(example_review.get("allowedPackageNamespaces") == [], "disabled example package allowlist must be empty")
    audit.require(example_review.get("allowedObjectApiNames") == [], "disabled example object allowlist must be empty")
    workflow = required_text(ROOT / ".github/workflows/harness-ci.yml", audit)
    audit.require("npm ci --ignore-scripts" in workflow, "CI must install the pinned Salesforce review runtime without lifecycle scripts")
    # The static validator does not run the Knowledge domain gates itself; CI must own them
    # as explicit, attributable steps.
    for gate in ("entry-check", "feature-check"):
        audit.require(
            f"python scripts/knowledge_store.py {gate}" in workflow,
            f"CI must keep the explicit knowledge {gate} gate",
        )


def check_repo_map(audit: Audit) -> None:
    """The generated repository atlas must exist, match its sources, and stay in budget."""

    completed = subprocess.run(
        [sys.executable, "scripts/render_repo_map.py", "render", "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    audit.require(
        completed.returncode == 0,
        f"repo map drift/render failure: {completed.stderr.strip() or completed.stdout.strip()}",
    )
    repo_map = load_json(ROOT / ".ai/repo-map.json", audit)
    audit.require(
        # Keep in sync with render_repo_map.WORD_BUDGET.
        isinstance(repo_map.get("wordCount"), int) and repo_map["wordCount"] <= 900,
        "repo-map.md exceeds its 900-word budget",
    )
    digests = repo_map.get("sourceDigests", {})
    expected_sources = (
        sorted((ROOT / ".github/agents").glob("*.agent.md"))
        + sorted((ROOT / ".github/skills").glob("*/SKILL.md"))
        + sorted((ROOT / ".github/prompts").glob("*.prompt.md"))
        + sorted((ROOT / ".github/instructions").glob("*.instructions.md"))
        + sorted((ROOT / ".ai/contracts").glob("*.md"))
    )
    for path in expected_sources:
        audit.require(
            path.relative_to(ROOT).as_posix() in digests,
            f"repo map does not cover {relative(path)}",
        )


def check_placeholders(audit: Audit, root: Path = ROOT) -> None:
    found: set[str] = set()
    for base in (root / ".github", root / ".ai/contracts"):
        for path in base.glob("**/*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:  # binary assets carry no human placeholders
                continue
            found.update(re.findall(r"<TU_WSTAW_[^>]+>", text))
    audit.require(found == EXPECTED_HUMAN_PLACEHOLDERS, f"human placeholder register drifted: found {sorted(found)}")


def third_party_python_imports(root: Path) -> dict[str, set[str]]:
    """Top-level module names imported by scripts/*.py that resolve outside the standard library.

    Resolution is by spec origin rather than a hand-kept stdlib list, because a hand-kept list
    silently misclassifies extension modules (`math`, `unicodedata`) and turns the admission
    gate into an inert check.
    """
    local = {path.stem for path in (root / "scripts").glob("*.py")} | {"scripts"}
    found: dict[str, set[str]] = {}
    for path in sorted((root / "scripts").glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
        for name in names:
            if not name or name in local:
                continue
            try:
                spec = importlib.util.find_spec(name)
            except (ImportError, ValueError):
                spec = None
            origin = getattr(spec, "origin", None) or ""
            search = " ".join(getattr(spec, "submodule_search_locations", None) or [])
            if "site-packages" in origin or "dist-packages" in origin or "site-packages" in search:
                found.setdefault(name, set()).add(path.name)
    return found


def check_dependency_admissions(audit: Audit, root: Path = ROOT) -> None:
    """DEP-01: a third-party Python import without a current admission record fails the build.

    The npm side is enforced structurally rather than by import scan: `check_settings_and_mcp`
    pins every MCP launcher to a locally installed entrypoint and refuses the token `npx`
    anywhere in the configuration, and `@azure-devops/mcp` carries its own admission record.
    A Node import scan would add little on top of that, because the wrappers are built on
    Node built-ins by policy.
    """
    records: dict[str, dict] = {}
    admissions = root / "config" / "dependency-admissions"
    for path in sorted(admissions.glob("*/*.json")):
        record = load_json(path, audit)
        if not isinstance(record, dict):
            continue
        expected = f"{record.get('safeSlug')}--{record.get('nameDigest12')}.json"
        audit.require(
            path.name == expected,
            f"{relative(path)}: admission filename must be '{expected}' (safe slug plus name digest)",
        )
        canonical = f"{record.get('ecosystem')}:{str(record.get('packageName', '')).lower()}"
        audit.require(
            record.get("nameDigest12")
            == hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12],
            f"{relative(path)}: nameDigest12 does not match sha256('{canonical}')",
        )
        for name in record.get("importNames", []):
            audit.require(
                name not in records,
                f"import name '{name}' is claimed by two admission records",
            )
            records[name] = record
    lock = (root / "requirements-dev.lock").read_text(encoding="utf-8") if (
        root / "requirements-dev.lock"
    ).is_file() else ""
    for name, users in sorted(third_party_python_imports(root).items()):
        record = records.get(name)
        audit.require(
            record is not None,
            f"third-party import '{name}' (used by {', '.join(sorted(users))}) has no dependency "
            f"admission record under config/dependency-admissions/",
        )
        if record is None:
            continue
        pin = f"{record['packageName']}=={record['version']}"
        audit.require(
            pin in lock,
            f"admission record for '{name}' pins {pin}, which is absent from requirements-dev.lock",
        )
        for digest in record.get("integrity", {}).get("artifactDigests", []):
            audit.require(
                f"--hash={digest}" in lock,
                f"admission record for '{name}' lists artifact digest {digest[:19]}… that the "
                f"lockfile does not contain",
            )


def check_retired_surfaces(audit: Audit, root: Path = ROOT) -> None:
    """A replacement phase removes its predecessor; this proves the old name is unreachable.

    Every retired surface names the exact tokens that must not appear in a tracked file, plus
    the historical audit documents that are allowed to keep describing it. The scan covers the
    whole tracked tree so a deletion cannot leave a live consumer behind in an unexpected
    directory, which is the failure mode §5.3 of the rebuild plan exists to prevent.
    """
    manifest = load_json(root / "config/retired-surfaces.json", audit)
    if not isinstance(manifest, dict):
        return
    result = subprocess.run(
        ["git", "ls-files"], cwd=root, text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        audit.require(False, "retired-surface scan cannot list tracked files")
        return
    tracked = [line for line in result.stdout.splitlines() if line]
    for entry in manifest.get("retired", []):
        # The manifest names the retired tokens by construction; scanning it would always fail.
        allowlist = set(entry.get("historicalAllowlist", [])) | {"config/retired-surfaces.json"}
        tokens = entry.get("tokens", [])
        offenders: list[str] = []
        for relative_path in tracked:
            if relative_path in allowlist:
                continue
            path = root / relative_path
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if any(token in text for token in tokens):
                offenders.append(relative_path)
        audit.require(
            not offenders,
            f"retired surface '{entry.get('name')}' (removed in {entry.get('retiredIn')}) is still "
            f"referenced by {', '.join(sorted(offenders)[:6])}; replacement is "
            f"{entry.get('replacement')}",
        )


def check_contracts_match_mcp(audit: Audit) -> None:
    """Normative contracts must not advertise MCP servers that mcp.json does not configure.

    The capability map kept advertising the removed salesforce-development DX MCP as a live
    surface. The alternation lists every server name the contracts have referenced; extend
    it when a server is added or renamed.
    """
    mcp = load_json(ROOT / ".vscode/mcp.json", audit)
    servers = set(mcp.get("servers", {})) if isinstance(mcp, dict) else set()
    referenced = re.compile(r"`(ado-readonly|salesforce-readonly|salesforce-development)/")
    for path in sorted((ROOT / ".ai/contracts").glob("*.md")):
        for name in sorted(set(referenced.findall(path.read_text(encoding="utf-8")))):
            audit.require(
                name in servers,
                f"{relative(path)}: references MCP server '{name}/' absent from .vscode/mcp.json",
            )


def check_org_usage(audit: Audit, root: Path = ROOT) -> None:
    """Org-usage hard integrity gate (contract §6.6): the entry-check disclosure is advisory,
    THIS is where tamper fails the build. Three rules: the org ledger is append-only and
    monotonic; every org-bearing entry's sectionDigest recomputes AND is the latest org-ledger
    record for its identity; and org-bearing entries may exist only where origin containment
    passes (gate 1, owner D-1 2026-08-03) — a failing `git remote` is a refusal, never a pass.
    All checks are lazy: an org-free workspace (this public origin) pays one exists() call."""
    ledger_path = root / ".ai/knowledge/artifacts-org-ledger.jsonl"
    records: list[dict] = []
    if ledger_path.exists():
        for index, line in enumerate(ledger_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                audit.require(False, f"org ledger line {index} is not JSON")
                continue
            audit.require(
                record.get("sequence") == index,
                f"org ledger sequence break at line {index} (append-only violated)",
            )
            records.append(record)
    latest: dict[str, dict] = {}
    for record in records:
        if isinstance(record.get("identity"), str):
            latest[record["identity"]] = record
    artifacts = root / ".ai/knowledge/artifacts"
    org_bearing = 0
    if artifacts.is_dir():
        for path in sorted(artifacts.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            if "orgUsage" not in text:
                continue
            try:
                frontmatter_block = yaml.safe_load(text.split("---", 2)[1])
            except (IndexError, yaml.YAMLError):
                continue  # unparseable entries are compute_lane/entry-check territory
            section = (frontmatter_block or {}).get("orgUsage")
            if not isinstance(section, dict):
                continue
            org_bearing += 1
            subject = frontmatter_block.get("subject") or {}
            identity = (
                f"{subject.get('metadataType')}:{subject.get('namespace') or 'c'}:{subject.get('fullName')}"
            )
            recomputed = canonical_digest(section.get("orgs") or {})
            audit.require(
                section.get("sectionDigest") == recomputed,
                f"{relative(path)}: orgUsage.sectionDigest does not recompute (tamper or crash; "
                "recover forward with entry-org-attach or entry-org-detach)",
            )
            record = latest.get(identity)
            audit.require(
                record is not None and record.get("orgUsageDigest") == recomputed,
                f"{relative(path)}: orgUsage is not the latest org-ledger record for {identity}",
            )
    if org_bearing:
        policy = load_json(root / "config/knowledge-policy.json", audit)
        allowlist = (policy.get("orgUsage") or {}).get("allowedOriginRemotes") or []
        contained = bool(allowlist)
        if contained:
            import subprocess

            try:
                completed = subprocess.run(
                    ["git", "-C", str(root), "remote", "-v"],
                    text=True, capture_output=True, timeout=30, check=False,
                )
            except (OSError, subprocess.SubprocessError):
                contained = False
            else:
                if completed.returncode != 0:
                    contained = False
                else:
                    urls = {
                        parts[1]
                        for parts in (line.split() for line in completed.stdout.splitlines())
                        if len(parts) >= 2
                    }
                    contained = all(url in allowlist for url in urls)
        audit.require(
            contained,
            f"{org_bearing} org-bearing entr{'y' if org_bearing == 1 else 'ies'} present but origin "
            "containment fails (gate 1: allowlist empty, off-list remote, or git unavailable)",
        )


def run_checks(audit: Audit, checks: Iterable[Callable[[Audit], None]]) -> None:
    """Run every check; an uncaught exception becomes a named audit error, not a lost report.

    The 2026-08-04 deep test showed a single malformed input file raising through a check
    and discarding every already-collected finding. The traceback still goes to stderr for
    debugging; the report keeps accumulating and printing."""
    for check in checks:
        try:
            check(audit)
        except Exception as exc:
            traceback.print_exc()
            audit.require(
                False,
                f"{check.__name__} crashed ({type(exc).__name__}: {exc}) — remaining "
                "checks in this function were skipped",
            )


def main() -> int:
    audit = Audit()
    run_checks(
        audit,
        (
            check_required_files,
            check_salesforce_project,
            check_customizations,
            check_links,
            check_settings_and_mcp,
            check_ci,
            check_schemas_and_evals,
            check_grounding_contracts,
            check_contracts_match_mcp,
            check_repo_map,
            check_placeholders,
            check_secret_signatures,
            check_python_yaml_safety,
            check_skill_commands,
            check_release_handover_contract,
            check_knowledge_consumer_sets,
            check_org_usage,
            check_retired_surfaces,
            check_dependency_admissions,
        ),
    )
    if audit.errors:
        print(f"FAIL: static harness validation ({len(audit.errors)} errors, {audit.checks} assertions)")
        for message in audit.errors:
            print(f"- {message}")
        return 1
    print(f"PASS: static harness validation ({audit.checks} assertions)")
    print("Scope: tracked repository structure, configuration contracts, and safety wiring")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
