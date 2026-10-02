"""Exact ADO capabilities for the pinned connector; no network or publication executor.

The global safety hook independently validates local organization/project/URL scope.
The role hook grants reads only to roles whose frontmatter exposes this connector.
Publication intent and deployed-state evidence remain the publication skill's contract.
"""
from __future__ import annotations

import re
from typing import Any


ADO_TOOL_PREFIXES = (
    "core_", "wit_", "wiki", "testplan", "build_", "repo_", "release_",
    "pipelines_", "search_", "advsec_", "work_item",
)
# @azure-devops/mcp 2.8.1: core, work-items, wiki and search. Enumeration of
# organizations/projects and every vendor mutation are deliberately absent.
READ_TOOLS = frozenset({
    "core_list_project_teams", "core_get_identity_ids",
    "wit_my_work_items", "wit_list_backlogs", "wit_list_backlog_work_items",
    "wit_get_work_item", "wit_get_work_items_batch_by_ids",
    "wit_list_work_item_comments", "wit_list_work_item_revisions",
    "wit_get_work_items_for_iteration", "wit_get_work_item_type", "wit_get_query",
    "wit_get_query_results_by_id", "wit_get_work_item_attachment", "wit_query_by_wiql",
    "wiki_get_wiki", "wiki_list_wikis", "wiki_list_pages", "wiki_get_page",
    "wiki_get_page_content", "search_code", "search_wiki", "search_workitem",
})
WRITE_TOOLS = frozenset({"wiki_create_or_update_page", "wit_add_artifact_link"})
READ_ROLES = frozenset({"developer", "designer", "test-strategist"})


def bare_tool_name(tool_name: str) -> str:
    """Accept the connector namespace and the host's observed unqualified form."""
    name = tool_name.lower()
    if name.startswith("ado-readonly/"):
        return name.removeprefix("ado-readonly/")
    if "/" not in name:
        return name
    return ""


def is_ado_tool(tool_name: str) -> bool:
    lowered = tool_name.lower()
    return "ado-readonly" in lowered or lowered.rsplit("/", 1)[-1].startswith(ADO_TOOL_PREFIXES)


def _plain_text(value: Any, maximum: int = 256) -> bool:
    if not isinstance(value, str) or not value or len(value) > maximum or value != value.strip():
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return not any(ord(char) < 32 or ord(char) == 127 for char in value)


def _wiki_identifier(value: Any) -> bool:
    return _plain_text(value) and not any(char in value for char in "/\\%?#:") and value not in {".", ".."}


def _page_path(value: Any) -> bool:
    if not _plain_text(value, 2048) or not value.startswith("/") or any(char in value for char in "\\%?#"):
        return False
    return value == "/" or all(
        segment and segment == segment.strip() and segment not in {".", ".."}
        for segment in value[1:].split("/")
    )


def _branch(value: Any) -> bool:
    return bool(_plain_text(value) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", value)
                and ".." not in value and not value.endswith(("/", ".", ".lock"))
                and all(segment and not segment.startswith(".") for segment in value.split("/")))


def _etag(value: Any) -> bool:
    # A wildcard or weak validator cannot pin the page version read by the author.
    # Reject validator lists as well: a list containing * bypasses stale-version proof.
    return bool(_plain_text(value, 256) and re.fullmatch(r'(?:[A-Za-z0-9._-]+|"[^"*,\s]+")', value))


def tool_error(tool_name: str, tool_input: Any, role: str | None = None) -> str | None:
    """Check known capability and narrow write shape; scope is checked separately."""
    name = bare_tool_name(tool_name)
    if name not in READ_TOOLS | WRITE_TOOLS:
        return "unknown or unsupported ADO tool; broad ADO mutations are forbidden"
    if role is not None and role not in READ_ROLES:
        return f"{role} has no ADO tool access"
    if not isinstance(tool_input, dict):
        return "ADO tool input must be an object"
    if name in READ_TOOLS:
        return None
    if role is not None and role != "developer":
        return "only Developer may publish Wiki pages or add the delivery document's Story link"
    if not _plain_text(tool_input.get("project")):
        return "Wiki publication requires one explicit project"
    if not _wiki_identifier(tool_input.get("wikiIdentifier")):
        return "Wiki publication requires a plain wikiIdentifier"
    if name == "wit_add_artifact_link":
        # The adapter resolves the canonical project/wiki IDs and page path. Raw
        # artifactUri or vendor projectId would bypass that live scope proof.
        required = {"project", "workItemId", "linkType", "wikiIdentifier", "pagePath"}
        if set(tool_input) != required:
            return "Story linking accepts only project, workItemId, linkType, wikiIdentifier and pagePath"
        if tool_input["linkType"] != "Wiki":
            return "Story linking permits only the Wiki Page artifact relation (linkType Wiki)"
        if type(tool_input["workItemId"]) is not int or not 1 <= tool_input["workItemId"] <= 2_147_483_647:
            return "Story linking requires a positive integer workItemId"
        if not _page_path(tool_input["pagePath"]):
            return "Story linking requires a canonical absolute wiki pagePath"
        return None
    required = {"project", "wikiIdentifier", "path", "content", "mode"}
    if not required <= set(tool_input) <= required | {"etag", "branch"}:
        return "Wiki publication accepts only project, wikiIdentifier, path, content, mode, etag and branch"
    if not _page_path(tool_input["path"]):
        return "Wiki publication requires a canonical absolute wiki path"
    if not isinstance(tool_input["content"], str):
        return "Wiki content must be Markdown text"
    if "branch" in tool_input and not _branch(tool_input["branch"]):
        return "Wiki publication branch is malformed"
    if tool_input["mode"] == "create":
        if "etag" in tool_input:
            return "Wiki creation must not supply an update ETag"
    elif tool_input["mode"] == "update":
        if not _etag(tool_input.get("etag")):
            return "Wiki update requires the concrete ETag from a fresh full-content read"
    else:
        return "Wiki publication mode must be create or update"
    return None


def selector_input(tool_name: str, tool_input: Any) -> Any:
    """Keep Markdown/ETag data out of target/command scans only for the known writer.

    This strips only known top-level textual fields. Nested objects, selectors and
    extra arguments are never exempt, and tool_error still validates the full input.
    """
    if bare_tool_name(tool_name) != "wiki_create_or_update_page" or not isinstance(tool_input, dict):
        return tool_input
    return {key: value for key, value in tool_input.items()
            if key not in {"content", "etag"} or not isinstance(value, str)}
