"""Plan 04: both hooks admit scoped publication without opening broad ADO writes."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import copilot_role_guard as roles
from scripts import copilot_safety_hook as safety


ROOT = Path(__file__).resolve().parents[1]
CONFIG = {"ado": {
    "organization": "example-org", "project": "Example Project",
    "allowedHttpsOrigins": ["https://dev.azure.com/example-org"],
}}
PAGE = {
    "project": "Example Project", "wikiIdentifier": "Example.wiki",
    "path": "/Solutions/Billing/Invoice Generation", "mode": "create",
    "content": "# Invoice Generation\n\nThe system generates invoices.\n",
}
LINK = {
    "project": "Example Project", "workItemId": 1201, "linkType": "Wiki",
    "wikiIdentifier": "Example.wiki", "pagePath": "/Deliveries/1201",
}


def decision(output):
    return "allow" if output.get("continue") else output["hookSpecificOutput"]["permissionDecision"]


class WikiPolicyTests(unittest.TestCase):
    def run_hooks(self, name, payload, role="developer", config=CONFIG):
        """Run each independent host hook, including global config/scope checks."""
        event = {"tool_name": name, "tool_input": payload, "cwd": str(ROOT)}
        results = []
        for module, argv in ((safety, ["copilot_safety_hook.py"]),
                             (roles, ["copilot_role_guard.py", "--role", role])):
            output = StringIO()
            with patch("sys.stdin", StringIO(json.dumps(event))), \
                    patch("sys.argv", argv), redirect_stdout(output), \
                    patch.object(module, "_log_decision"), \
                    patch.object(safety, "load_config", return_value=deepcopy(config)):
                self.assertEqual(0, module.main())
            results.append(decision(json.loads(output.getvalue())))
        return results

    def assert_admitted(self, name, payload, role="developer"):
        self.assertEqual(["allow", "allow"], self.run_hooks(name, payload, role))

    def assert_denied(self, name, payload, role="developer", config=CONFIG):
        self.assertIn("deny", self.run_hooks(name, payload, role, config))

    def test_developer_can_create_update_and_link_with_bare_and_prefixed_names(self):
        update = {**PAGE, "mode": "update", "etag": '"abcdef0123456789"', "branch": "wikiMaster"}
        for prefix in ("", "ado-readonly/"):
            for name, payload in (("wiki_create_or_update_page", PAGE),
                                  ("wiki_create_or_update_page", update),
                                  ("wit_add_artifact_link", LINK)):
                with self.subTest(name=prefix + name, mode=payload.get("mode")):
                    self.assert_admitted(prefix + name, payload)

    def test_all_non_developer_roles_are_denied_publication(self):
        for role in roles.ALLOWED_PREFIXES:
            if role == "developer":
                continue
            for prefix in ("", "ado-readonly/"):
                for name, payload in (("wiki_create_or_update_page", PAGE), ("wit_add_artifact_link", LINK)):
                    with self.subTest(role=role, name=prefix + name):
                        self.assertEqual("deny", self.run_hooks(prefix + name, payload, role)[1])

    def test_existing_reads_remain_available_only_to_the_three_ado_roles(self):
        examples = (
            ("search_wiki", {"project": ["Example Project"], "searchText": "Invoice"}),
            ("search_workitem", {"project": ["Example Project"], "searchText": "Invoice"}),
            ("search_code", {"project": "Example Project", "searchText": "Invoice"}),
            ("wit_get_work_item", {"project": "Example Project", "id": 1201}),
            ("wit_get_work_items_batch_by_ids", {"project": "Example Project", "ids": [1201]}),
            ("wit_query_by_wiql", {"project": "Example Project", "query": "SELECT [System.Id] FROM WorkItems"}),
            ("wiki_get_page", {"project": "Example Project", "wikiIdentifier": "Example.wiki", "path": "/Home"}),
            ("wiki_get_page_content", {"project": "Example Project", "wikiIdentifier": "Example.wiki", "path": "/Home"}),
            ("wiki_list_wikis", {"project": "Example Project"}),
            ("core_list_project_teams", {"project": "Example Project"}),
        )
        for role in roles.ALLOWED_PREFIXES:
            for prefix in ("", "ado-readonly/"):
                for name, payload in examples:
                    with self.subTest(role=role, name=prefix + name):
                        actual = self.run_hooks(prefix + name, payload, role)
                        self.assertEqual("allow", actual[0])
                        self.assertEqual("allow" if role in {"developer", "designer", "test-strategist"} else "deny", actual[1])

    def test_unknown_tools_and_broad_mutations_are_denied_even_for_developer(self):
        for name in (
            "wit_update_work_item", "wit_create_work_item", "wit_update_work_items_batch",
            "wit_add_work_item_comment", "wit_update_work_item_comment", "wit_add_child_work_items",
            "wit_work_items_link", "wit_work_item_unlink", "wit_link_work_item_to_pull_request",
            "wiki_delete_page", "wiki_rename_page", "wiki_future_read", "wit_work_item",
            "repo_create_pull_request", "build_queue", "core_list_projects", "core_list_orgs",
        ):
            for prefix in ("", "ado-readonly/"):
                with self.subTest(name=prefix + name):
                    self.assertEqual(["deny", "deny"], self.run_hooks(prefix + name, {"project": "Example Project"}))
        self.assert_denied("ado-readonly/unknown_tool", {"project": "Example Project"})
        self.assert_denied("another-server/wiki_create_or_update_page", PAGE)

    def test_global_scope_checks_still_govern_both_write_tools(self):
        for name, original in (("wiki_create_or_update_page", PAGE), ("wit_add_artifact_link", LINK)):
            for extra in (
                {"project": "Other Project"}, {"project": ["Example Project", "Other Project"]},
                {"project": None}, {"project": []}, {"project": " Example Project"},
                {"organization": "other-org"}, {"projectId": "OTHER-GUID"},
                {"options": {"project": "Other Project"}},
                {"url": "https://dev.azure.com/other-org/Example%20Project/_wiki/wikis/Example.wiki"},
                {"url": "https://dev.azure.com/example-org/OtherProject/_wiki/wikis/Example.wiki"},
                {"url": "https://github.com/example/source"},
            ):
                with self.subTest(name=name, extra=extra):
                    self.assertEqual("deny", self.run_hooks(name, {**original, **extra})[0])
            self.assert_denied(name, original, config=None)
            self.assert_denied(name, original, config={"ado": None})
            payload = {key: value for key, value in original.items() if key != "project"}
            self.assert_denied(name, payload)

    def test_markdown_is_data_but_selectors_and_unknown_fields_are_still_checked(self):
        markdown = """# Operations
Source: [implementation](https://github.com/example/project/blob/main/src/service.py).
An external organization reference: https://dev.azure.com/other-org/OtherProject/_wiki/wikis/wiki
Never run `rm -rf /`, `git reset --hard`, `git push --force`, `DROP TABLE invoices`, or `DELETE FROM invoices`.
```sh
sf project deploy start --target-org production
```
"""
        for prefix in ("", "ado-readonly/"):
            name = prefix + "wiki_create_or_update_page"
            self.assert_admitted(name, {**PAGE, "content": markdown})
            self.assert_denied(name, {**PAGE, "content": markdown, "url": "https://evil.example/target"})
            self.assert_denied(name, {**PAGE, "content": markdown, "command": "rm -rf /"})
            self.assert_denied(name, {**PAGE, "content": {"text": markdown, "project": "OtherProject"}})
            self.assert_denied(name, {**PAGE, "options": {"content": markdown}})
            self.assert_denied(name, {**PAGE, "path": "/rm -rf files"})
        # The exception does not spread to search input, link arguments, or unknown tools.
        self.assert_denied("search_wiki", {"project": ["Example Project"], "content": markdown})
        self.assert_denied("wit_add_artifact_link", {**LINK, "content": markdown})
        self.assert_denied("wiki_future_write", {**PAGE, "content": markdown})

    def test_publication_requires_strict_canonical_selectors_and_explicit_mode(self):
        bad_values = (
            ("wikiIdentifier", ""), ("wikiIdentifier", "../other"),
            ("wikiIdentifier", "https://evil.example/wiki"), ("wikiIdentifier", {"id": "wiki"}),
            ("path", "Solutions/Page"), ("path", "/Home/../Other"),
            ("path", "/Home/%2e%2e/Other"), ("path", "/Home\\Other"),
            ("path", "/Home?path=/Other"), ("path", "/Home//Other"),
            ("path", "/Home\nOther"), ("path", ["/Home"]),
            ("branch", "main?api-version=1"), ("branch", "../main"),
            ("content", {"text": "Page content"}), ("mode", "overwrite"),
            ("mode", None), ("etag", "unused-create-etag"),
        )
        for key, value in bad_values:
            with self.subTest(key=key, value=value):
                self.assert_denied("wiki_create_or_update_page", {**PAGE, key: value})
        self.assert_denied("wiki_create_or_update_page", {key: value for key, value in PAGE.items() if key != "mode"})
        for etag in (None, "", "*", '"old", *', '"old", "other"', 'W/"weak"',
                     "value\r\nInjected: header", {"etag": "value"}):
            with self.subTest(etag=etag):
                self.assert_denied("wiki_create_or_update_page", {**PAGE, "mode": "update", "etag": etag})
        self.assert_denied("wiki_create_or_update_page", {**PAGE, "mode": "update"})

    def test_story_link_cannot_supply_raw_uri_other_relation_or_extra_patch(self):
        for extra in (
            {"linkType": "Wiki Page"}, {"linkType": "Branch"}, {"linkType": "Related Workitem"},
            {"artifactUri": "vstfs:///Wiki/WikiPage/OTHER-PROJECT%2FOTHER-WIKI%2FPage"},
            {"artifactUri": "https://dev.azure.com/example-org/OtherProject/_wiki/wikis/wiki"},
            {"projectId": "OTHER-PROJECT"}, {"wikiId": "OTHER-WIKI"}, {"pageId": 5},
            {"repositoryId": "repo"}, {"comment": "An unrelated mutation"},
            {"patch": [{"op": "remove", "path": "/relations/0"}]},
            {"pagePath": "/Home/../Other"}, {"wikiIdentifier": "//evil.example"},
            {"workItemId": "1201"}, {"workItemId": True}, {"workItemId": 0},
        ):
            with self.subTest(extra=extra):
                self.assert_denied("wit_add_artifact_link", {**LINK, **extra})

    def test_missing_shared_policy_denies_in_both_standalone_hook_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            script_dir = Path(directory) / "scripts"
            script_dir.mkdir()
            for filename in ("copilot_role_guard.py", "copilot_safety_hook.py", "salesforce_operation_policy.py",
                             "git_workflow_policy.py", "verify_salesforce_org.py", "ado_config.py"):
                shutil.copy2(ROOT / "scripts" / filename, script_dir / filename)
            for script, args in (("copilot_role_guard.py", ["--role", "developer"]),
                                 ("copilot_safety_hook.py", [])):
                bootstrap = (
                    "import pathlib,runpy,sys; sys.argv=sys.argv[1:]; "
                    "sys.path.insert(0,str(pathlib.Path(sys.argv[0]).parent)); "
                    "runpy.run_path(sys.argv[0],run_name='__main__')"
                )
                result = subprocess.run(
                    [sys.executable, "-I", "-B", "-c", bootstrap, str(script_dir / script), *args],
                    input=json.dumps({"tool_name": "wiki_create_or_update_page", "tool_input": PAGE}),
                    cwd=directory, text=True, capture_output=True, timeout=10,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                output = json.loads(result.stdout)
                self.assertEqual("deny", decision(output))
                self.assertIn("ADO policy unavailable", output["hookSpecificOutput"]["permissionDecisionReason"])
                self.assertIn("ado_tool_policy", output["hookSpecificOutput"]["permissionDecisionReason"])


if __name__ == "__main__":
    unittest.main()
