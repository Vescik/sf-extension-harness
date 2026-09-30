"""Plan 03 admission checks on real temporary Git repositories; no remote operations."""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts import copilot_role_guard as roles
from scripts import copilot_safety_hook as safety
from scripts import git_workflow_policy as policy


def shell_command(args):
    return subprocess.list2cmdline(args) if os.name == "nt" else shlex.join(args)


class GitWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Local test")
        self.git("config", "user.email", "local-test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.write(".gitignore", ".cache/\noutput/\nconfig/harness.local.json\n")
        self.write("work-items/123-example/ado-context.md", "# Work Item 123\nType: User Story\n")
        self.write("work-items/456-other/ado-context.md", "# Work Item 456\nType: Bug\n")
        self.write("force-app/main/default/classes/Example.cls", "public class Example {}\n")
        self.git("add", ".")
        self.git("commit", "-m", "fixture")
        self.git("remote", "add", "origin", "https://github.com/example/repository.git")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("switch", "-c", "work-item/123-example")

    def git(self, *args):
        run = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True)
        self.assertEqual(0, run.returncode, run.stderr)
        return run.stdout.strip()

    def write(self, name, contents="changed\n"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        return path

    def decide(self, command, role="developer"):
        with patch.object(roles, "HARNESS_ROOT", self.root), patch.object(roles, "METADATA_ROOT", self.root):
            return roles.workflow_terminal_decision(command, self.root, role)

    def assertDecision(self, expected, command, role="developer"):
        result = self.decide(command, role)
        self.assertIsNotNone(result)
        self.assertEqual(expected, result[0], result)

    def invoke(self, module, command=None, role="developer", tool="execute/runInTerminal", payload=None):
        event = {"cwd": str(self.root), "tool_name": tool,
                 "tool_input": payload if payload is not None else {"command": command}}
        out = StringIO()
        argv = ["hook", "--role", role] if module is roles else ["hook"]
        with patch("sys.stdin", StringIO(json.dumps(event))), patch("sys.argv", argv), \
                patch.object(module, "HARNESS_ROOT", self.root), patch.object(module, "_log_decision"), \
                patch.object(roles, "METADATA_ROOT", self.root), redirect_stdout(out):
            module.main()
        result = json.loads(out.getvalue())
        return "allow" if result.get("continue") else result["hookSpecificOutput"]["permissionDecision"]

    def stage_design(self):
        path = "work-items/123-example/design.md"
        self.write(path)
        self.git("add", "--", path)
        return path

    def commit_command(self, path, subject="[WI-123] document retry design — AB#123", *body):
        return shell_command(["git", "commit", "-m", subject, *[token for paragraph in body for token in ("-m", paragraph)], "--", path])

    def gh_body(self):
        self.write(policy.PR_BODY, "Describe sf project retrieve and git reset --hard as data.\n")

    def feature(self):
        self.write("work-items/500-feature/ado-context.md", "# Feature 500\nType: Feature\n")
        self.write("work-items/500-feature/delivery-map.md", "# Feature 500\n## Included delivery Work Items\n| ID | Type | Title |\n|---|---|---|\n| 123 | User Story | Example |\n## Deferred direct children\n| 456 | Bug | Later |\n")

    def test_exact_add_and_commit_produce_real_commit_and_preserve_unrelated_unstaged(self):
        path = "work-items/123-example/design.md"
        self.write(path, "Retry design\n")
        untouched = "work-items/456-other/design.md"
        self.write(untouched, "Unrelated human notes\n")
        self.assertDecision("allow", f"git add -- {path}", "designer")
        self.git("add", "--", path)
        command = self.commit_command(path, "[WI-123] document retry design — AB#123", "Describe the intended retry boundary.", "Verification: reviewed the contract.")
        self.assertDecision("allow", command, "designer")
        before = self.git("rev-parse", "HEAD")
        self.git(*policy.parse_command(command)[1:])
        self.assertEqual(before, self.git("rev-parse", "HEAD^"))
        self.assertEqual(path, self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"))
        self.assertEqual("Unrelated human notes\n", (self.root / untouched).read_text())
        self.assertEqual("", self.git("diff", "--cached", "--name-only"))

    def test_staged_unrelated_index_is_preserved_and_denied(self):
        path = self.stage_design()
        other = "work-items/456-other/design.md"
        self.write(other)
        self.git("add", "--", other)
        before = self.git("diff", "--cached")
        self.assertDecision("deny", self.commit_command(path))
        self.assertDecision("deny", f"git add -- {path}")
        self.assertEqual(before, self.git("diff", "--cached"))

    def test_partial_staging_denies_without_restage(self):
        path = self.stage_design()
        staged = self.git("show", ":" + path)
        self.write(path, "Additional unstaged human edit\n")
        self.assertDecision("deny", self.commit_command(path))
        self.assertDecision("deny", f"git add -- {path}")
        self.assertEqual(staged, self.git("show", ":" + path))

    def test_same_size_and_mtime_cannot_hide_working_tree_content_changes(self):
        self.git("config", "core.trustctime", "false")
        self.git("config", "core.checkStat", "minimal")
        path = "work-items/123-example/design.md"
        file = self.write(path, "changed\n")
        os.utime(file, (1_000_000_000, 1_000_000_000))
        self.git("add", "--", path)
        self.write(path, "altered\n")
        os.utime(file, (1_000_000_000, 1_000_000_000))
        self.assertEqual("", self.git("diff", "--", path))
        self.assertDecision("deny", self.commit_command(path))
        self.assertDecision("deny", "git add -- " + path)
        self.assertEqual("changed", self.git("show", ":" + path))

    def test_fresh_content_hash_uses_git_line_ending_normalization(self):
        self.write(".gitattributes", "*.md text eol=lf\n")
        path = self.stage_design()
        (self.root / path).write_bytes(b"changed\r\n")
        self.assertDecision("allow", self.commit_command(path))

    def test_delete_and_rename_are_checked_on_both_ends(self):
        old = "force-app/main/default/classes/Example.cls"
        new = "force-app/main/default/classes/Renamed.cls"
        (self.root / old).rename(self.root / new)
        self.assertDecision("allow", f"git add -- {old} {new}")
        self.git("add", "--", old, new)
        command = shell_command(["git", "commit", "-m", "[WI-123] rename the example class — AB#123", "--", old, new])
        self.assertDecision("allow", command)
        self.assertDecision("deny", self.commit_command(new))
        self.git(*policy.parse_command(command)[1:])
        (self.root / new).unlink()
        self.assertDecision("allow", f"git add -- {new}")
        self.git("add", "--", new)
        self.assertDecision("allow", self.commit_command(new))
        self.write(new, "Recreated but untracked\n")
        self.assertDecision("deny", self.commit_command(new))

    @unittest.skipIf(os.name == "nt", "Windows has no POSIX executable mode; the index mode is authoritative")
    def test_file_mode_change_after_stage_is_denied(self):
        path = self.stage_design()
        self.git("config", "core.filemode", "true")
        (self.root / path).chmod(0o755)
        self.assertDecision("deny", self.commit_command(path))
        self.git("config", "core.filemode", "false")
        self.assertDecision("deny", self.commit_command(path))
        self.assertDecision("deny", f"git add -- {path}")

    def test_current_source_documentation_without_context_preserves_plan02_lane(self):
        self.git("switch", "main")
        branch = "work-item/789-standalone-docs"
        path = "work-items/789-standalone-docs/technical-documentation.md"
        self.write(path, "# Technical documentation\nCurrent ADO source was read.\n")
        self.assertDecision("allow", f"git switch -c {branch}")
        self.git("switch", "-c", branch)
        self.assertDecision("allow", f"git add -- {path}")
        self.git("add", "--", path)
        self.assertDecision("allow", self.commit_command(path, "[WI-789] describe the current solution — AB#789"))
        self.assertFalse((self.root / "work-items/789-standalone-docs/ado-context.md").exists())
        self.write("work-items/789-duplicate/technical-documentation.md")
        self.assertDecision("deny", self.commit_command(path, "[WI-789] describe the current solution — AB#789"))

    def test_no_changes_empty_commit_and_unstaged_only_are_denied(self):
        path = "work-items/123-example/design.md"
        self.assertDecision("deny", self.commit_command(path))
        self.write(path)
        self.assertDecision("deny", self.commit_command(path))

    def test_main_detached_and_git_operation_in_progress_deny(self):
        path = self.stage_design()
        self.git("switch", "main")
        self.assertDecision("deny", self.commit_command(path))
        self.git("switch", "--detach")
        self.assertDecision("deny", self.commit_command(path))
        self.git("switch", "work-item/123-example")
        self.write(".git/MERGE_HEAD", self.git("rev-parse", "HEAD"))
        self.assertDecision("deny", self.commit_command(path))

    def test_author_exact_flags_paths_and_role_boundaries(self):
        path = self.stage_design()
        for command in ("git add .", "git add -A", "git add -u", "git add -f -- " + path,
                        "git add -- work-items", "git add -- work-items/*", "git add -- :(top)" + path,
                        "git add -- ../escape", "git add -- .cache/github/pr-body.md",
                        "git add -- config/harness.local.json", "git add -- .ai/knowledge/artifacts/x.md",
                        "git commit --amend -m x -- " + path, "git commit --no-verify -m x -- " + path,
                        "git commit -a -m x -- " + path, "git commit -m x -- " + path):
            with self.subTest(command=command):
                self.assertDecision("deny", command)
        for role in ("reviewer", "knowledge-curator", "config-investigator"):
            self.assertDecision("deny", "git add -- " + path, role)
        self.assertDecision("deny", "git add -- force-app/main/default/classes/Example.cls", "designer")
        self.assertDecision("deny", "git add -- " + path, "test-strategist")
        self.write("work-items/123-example/qa-test-plan.md")
        self.git("restore", "--staged", "--", path)
        self.assertDecision("allow", "git add -- work-items/123-example/qa-test-plan.md", "test-strategist")

    def test_subject_id_scope_and_transition_keywords(self):
        path = self.stage_design()
        for subject in ("[WI-456] wrong branch — AB#456", "[WI-123] missing reference",
                        "[WI-123] fixes behavior — AB#123", "[WI-123] mixed refs — AB#123 AB#456"):
            self.assertDecision("deny", self.commit_command(path, subject))
        self.assertDecision("deny", self.commit_command(path, "[WI-123] implement design — AB#123", "Closes AB#123"))
        self.assertDecision("deny", "git add -- work-items/456-other/ado-context.md")

    def test_chore_commit_without_fake_item_and_root_of_trust_edit_not_bypassed(self):
        self.git("switch", "-c", "chore/policy")
        path = "scripts/git_workflow_policy.py"
        self.write(path)
        self.assertEqual("ask", roles.maintainer_edit_decision(path))
        self.assertDecision("allow", f"git add -- {path}", "workspace-maintainer")
        self.git("add", "--", path)
        self.assertDecision("allow", self.commit_command(path, "[chore] update workflow policy"), "workspace-maintainer")
        self.assertDecision("deny", self.commit_command(path, "[chore] update workflow — AB#123"), "workspace-maintainer")

    def test_feature_membership_and_separate_work_item_commits(self):
        self.feature()
        self.git("add", "--", "work-items/500-feature")
        self.git("commit", "-m", "fixture feature")
        self.git("switch", "-c", "feature/500-feature")
        path = self.stage_design()
        self.assertDecision("allow", self.commit_command(path))
        self.assertDecision("deny", self.commit_command(path, "[WI-456] wrong member — AB#456"))
        self.assertDecision("deny", self.commit_command(path, "[FEATURE-500] hide child change — AB#500"))
        map_path = self.root / "work-items/500-feature/delivery-map.md"
        map_path.write_text(map_path.read_text().replace("| 123 |", "| 1500123 |"))
        self.assertDecision("deny", self.commit_command(path))

    def feature_map_commit_fixture(self):
        self.feature()
        self.git("add", "--", "work-items/500-feature")
        self.git("commit", "-m", "fixture feature")
        self.git("switch", "-c", "feature/500-feature")
        return self.stage_design()

    def assert_feature_map_admission(self, expected, path, included, deferred="", extra=""):
        map_path = self.write("work-items/500-feature/delivery-map.md",
                              "# Feature 500\n## Included delivery Work Items\n" + included +
                              "\n## Deferred direct children\n" + deferred + extra)
        before = (self.git("rev-parse", "HEAD"), (self.root / ".git/index").read_bytes(), map_path.read_bytes())
        self.assertEqual(expected, self.invoke(roles, self.commit_command(path), role="designer"))
        after = (self.git("rev-parse", "HEAD"), (self.root / ".git/index").read_bytes(), map_path.read_bytes())
        self.assertEqual(before, after, "Admission must not commit, restage or migrate the existing map")

    def test_legacy_feature_map_columns_markup_and_lists_allow_real_role_commit_admission(self):
        path = self.feature_map_commit_fixture()
        variants = (
            "| ID | Type | Title |\n| --- | --- | --- |\n| 123 | User Story | Example |\n",
            "| Type | ID | Title |\n| --- | --- | --- |\n| User Story | 123 | Example |\n",
            "| Title | Type | ID |\n| --- | --- | --- |\n| Example | User Story | 123 |\n",
            "Type | ID | Title\n--- | --- | ---\nUser Story | 123 | Example\n",
            "| 123 | User Story | ID |\n",
            "| ID | Type | Title |\n| --- | --- | --- |\n| 123 | User Story | ID |\n",
            "- 123 User Story: Example\n",
            "1. 123 User Story: Example\n",
            "2) 123: Example\n",
        ) + tuple("| Type | ID | Title |\n| --- | --- | --- |\n| User Story | " + identity + " | Example |\n"
                  for identity in ("**123**", "__123__", "*123*", "_123_", "`123`", "``123``",
                                   "[123]", "[123][wi-123]", "[123][]", "**`123`**", "[`123`](https://example.invalid/123)",
                                   "[123](https://example.invalid/items/456)", "[123](https://example.invalid/(items)/123)",
                                   "**[123](https://example.invalid/123)**")) \
          + tuple("- " + identity + " Example\n" for identity in
                  ("**123**", "*123*", "_123_", "`123`", "[123]", "[123][wi-123]", "[123][]",
                   "[123](https://example.invalid/(items)/123)", "[123](https://example.invalid/123)", "[**123**](https://example.invalid/123)"))
        for included in variants:
            with self.subTest(included=included):
                self.assert_feature_map_admission("allow", path, included, "- **456** Later\n")

    def test_legacy_feature_map_rejects_ambiguous_or_nonexact_identity_without_mutation(self):
        path = self.feature_map_commit_fixture()
        variants = (
            "| Type | Title |\n| --- | --- |\n| User Story | 123 |\n",
            "| ID | ID |\n| --- | --- |\n| 123 | 456 |\n",
            "| Type | ID | Title |\n| --- | --- | --- |\n| User Story | 456 | 123 |\n",
            "| 123 | User Story | Example |\n| **123** | User Story | Duplicate |\n",
            "- **123** Example\n- [123](https://example.invalid/123) Duplicate\n",
            "- See [123](https://example.invalid/123)\n",
            "- 123suffix Example\n",
        ) + tuple("| Type | ID | Title |\n| --- | --- | --- |\n| User Story | " + identity + " | 123 |\n"
                  for identity in ("0", "0123", "-123", "123.0", "123 and 456", "**123** suffix",
                                   "[123](https://example.invalid/123)[456](https://example.invalid/456)",
                                   "`**123**`", "`[123](https://example.invalid/456)`",
                                   "[Example][123]", "[0123]", "[123] suffix", "[123](url) extra (text)",
                                   "[Example](https://example.invalid/items/123)", "https://example.invalid/items/123"))
        for included in variants:
            with self.subTest(included=included):
                self.assert_feature_map_admission("deny", path, included)
        self.assert_feature_map_admission("deny", path, "- **123** Example\n",
                                          "| Type | ID | Title |\n| --- | --- | --- |\n| User Story | `123` | Deferred |\n")
        self.assert_feature_map_admission("deny", path, "- 123 Example\n",
                                          "| Type | ID | Title |\n| --- | --- | --- |\n| User Story | 0123 | Ambiguous |\n")

    def test_feature_map_examples_and_unrelated_sections_do_not_grant_membership(self):
        path = self.feature_map_commit_fixture()
        examples = (
            "```markdown\n| ID | Type |\n| --- | --- |\n| 123 | User Story |\n```\n",
            "~~~markdown\n## Included delivery Work Items\n- 123 Example\n~~~\n",
            "    - 123 Example\n",
            "> - 123 Example\n",
        )
        for example in examples:
            with self.subTest(example=example):
                self.assert_feature_map_admission("deny", path, example,
                                                  extra="\n## Dependencies and boundaries\n- 123 Dependency\n")
                self.assert_feature_map_admission("allow", path, "- 123 Example\n\n" + example)
        self.assert_feature_map_admission("deny", path, "- 456 Other member\n",
                                          extra="\n## Notes\n- 123 Mentioned outside membership\n")
        self.assert_feature_map_admission("deny", path, "- 123 Example\n```markdown\n")

    def test_bootstrap_from_main_preserves_staged_and_unstaged_own_result(self):
        self.git("switch", "main")
        self.git("branch", "-D", "work-item/123-example")
        path = self.stage_design()
        self.write(path, "Unstaged addition\n")
        staged = self.git("diff", "--cached")
        unstaged = self.git("diff")
        self.assertDecision("allow", "git fetch origin", "designer")
        self.assertDecision("allow", "git switch -c work-item/123-example", "designer")
        self.git("switch", "-c", "work-item/123-example")
        self.assertEqual(staged, self.git("diff", "--cached"))
        self.assertEqual(unstaged, self.git("diff"))

    def test_bootstrap_stale_base_existing_branch_and_unrelated_work(self):
        self.git("switch", "main")
        self.assertDecision("deny", "git switch -c work-item/123-example")
        self.git("branch", "-D", "work-item/123-example")
        self.write("work-items/456-other/design.md")
        self.assertDecision("deny", "git switch -c work-item/123-example")
        (self.root / "work-items/456-other/design.md").unlink()
        self.git("commit", "--allow-empty", "-m", "local divergence")
        self.assertDecision("deny", "git switch -c work-item/123-example")
        self.assertDecision("deny", "git fetch arbitrary")
        self.assertDecision("deny", "git switch -C work-item/123-example")

    def test_resume_same_head_preserves_dirty_result(self):
        self.git("branch", "work-item/123-resume")
        self.stage_design()
        self.assertDecision("allow", "git switch work-item/123-resume")
        self.assertDecision("deny", "git switch main")

    def test_remote_only_resume_has_explicit_tracking_and_preserves_same_head_changes(self):
        branch = "work-item/123-remote"
        self.git("update-ref", "refs/remotes/origin/" + branch, "HEAD")
        command = f"git switch --track -c {branch} origin/{branch}"
        self.assertDecision("allow", command)
        path = self.stage_design()
        self.write(path, "Unstaged addition\n")
        staged, unstaged = self.git("diff", "--cached"), self.git("diff")
        self.assertDecision("allow", command)
        self.git(*policy.parse_command(command)[1:])
        self.assertEqual(staged, self.git("diff", "--cached"))
        self.assertEqual(unstaged, self.git("diff"))
        self.assertEqual("origin/" + branch, self.git("rev-parse", "--abbrev-ref", "@{upstream}"))
        self.assertDecision("deny", command)

    def test_remote_only_resume_rejects_mismatch_missing_ref_and_dirty_other_head(self):
        branch = "work-item/123-remote"
        command = f"git switch --track -c {branch} origin/{branch}"
        self.assertDecision("deny", command)
        self.git("update-ref", "refs/remotes/origin/" + branch, "HEAD")
        self.assertDecision("deny", command.replace("origin/", "other/"))
        self.assertDecision("deny", command.replace("origin/" + branch, "origin/work-item/456-other"))
        self.git("commit", "--allow-empty", "-m", "different current HEAD")
        self.assertDecision("allow", command)
        self.stage_design()
        self.assertDecision("deny", command)

    def test_return_to_confirmed_main_before_next_task_requires_clean_checkout(self):
        self.assertDecision("allow", "git switch main")
        self.write("work-items/123-example/design.md")
        self.assertDecision("deny", "git switch main")

    def test_stalled_git_inspection_denies_before_host_timeout(self):
        with patch.object(policy.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 3)):
            self.assertDecision("deny", "git add -- work-items/123-example/design.md")

    def test_parallel_child_uses_confirmed_remote_feature_membership(self):
        self.feature()
        self.git("add", "--", "work-items/500-feature")
        self.git("commit", "-m", "fixture feature")
        self.git("update-ref", "refs/remotes/origin/feature/500-feature", "HEAD")
        self.assertDecision("allow", "git switch -c work-item/123-parallel origin/feature/500-feature")
        self.assertDecision("deny", "git switch -c work-item/456-parallel origin/feature/500-feature")

    def feature_ref_fixture(self, current_member=None, target_member="123"):
        """Prepare independent current/target maps, simulating fetched refs locally."""
        branch = "feature/500-feature"
        self.git("switch", "main")
        if current_member is not None:
            self.feature()
            self.write_feature_member(current_member)
            self.git("add", "--", "work-items/500-feature")
            self.git("commit", "-m", "current checkout Feature map")
            self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("switch", "-c", branch)
        self.feature()
        self.write_feature_member(target_member)
        self.git("add", "--", "work-items/500-feature")
        self.git("commit", "-m", "target Feature map")
        self.git("update-ref", "refs/remotes/origin/" + branch, "HEAD")
        self.git("switch", "main")
        return branch

    def write_feature_member(self, member):
        deferred = "456" if member == "123" else "123"
        # The ref reader must keep the compatibility fixed in audit point 3.
        self.write("work-items/500-feature/delivery-map.md",
                   "# Feature 500\n## Included delivery Work Items\n"
                   "| Type | ID | Title |\n| --- | --- | --- |\n"
                   f"| User Story | **{member}** | Included |\n"
                   f"## Deferred direct children\n- `{deferred}` Later\n")

    def test_parallel_child_rejects_checkout_inclusion_when_remote_base_defers_it(self):
        branch = self.feature_ref_fixture(current_member="123", target_member="456")
        before = (self.git("rev-parse", "HEAD"), (self.root / ".git/index").read_bytes())
        self.assertEqual("deny", self.invoke(roles, f"git switch -c work-item/123-parallel origin/{branch}"))
        self.assertEqual(before, (self.git("rev-parse", "HEAD"), (self.root / ".git/index").read_bytes()))

    def test_parallel_child_uses_base_inclusion_despite_checkout_deferral(self):
        branch = self.feature_ref_fixture(current_member="456", target_member="123")
        command = f"git switch -c work-item/123-parallel origin/{branch}"
        self.assertEqual("allow", self.invoke(roles, command))
        self.git(*policy.parse_command(command)[1:])
        self.assertEqual(self.git("rev-parse", "refs/remotes/origin/" + branch), self.git("rev-parse", "HEAD"))
        self.assertEqual({"123"}, policy.feature_members(policy.Repo(self.root), "500"))

    def test_parallel_child_and_clean_local_feature_resume_need_no_current_feature_context(self):
        branch = self.feature_ref_fixture()
        self.assertFalse((self.root / "work-items/500-feature").exists())
        self.assertEqual("allow", self.invoke(roles, f"git switch -c work-item/123-parallel origin/{branch}"))
        command = f"git switch {branch}"
        self.assertEqual("allow", self.invoke(roles, command))
        self.git(*policy.parse_command(command)[1:])
        self.assertEqual("", self.git("status", "--porcelain"))
        self.assertEqual({"123"}, policy.feature_members(policy.Repo(self.root), "500"))

    def test_clean_remote_feature_resume_reads_target_context(self):
        branch = self.feature_ref_fixture()
        self.git("branch", "-D", branch)
        command = f"git switch --track -c {branch} origin/{branch}"
        self.assertEqual("allow", self.invoke(roles, command))
        self.git(*policy.parse_command(command)[1:])
        self.assertEqual("origin/" + branch, self.git("rev-parse", "--abbrev-ref", "@{upstream}"))
        self.assertEqual("", self.git("status", "--porcelain"))

    def test_feature_resume_and_parallel_bootstrap_preserve_dirty_head_restrictions(self):
        branch = self.feature_ref_fixture()
        path = self.stage_design()
        self.write(path, "Additional human edit\n")
        before = (self.git("diff", "--cached"), self.git("diff"), (self.root / ".git/index").read_bytes())
        for command in (f"git switch {branch}", f"git switch -c work-item/123-parallel origin/{branch}"):
            self.assertEqual("deny", self.invoke(roles, command))
        self.git("branch", "-D", branch)
        self.assertEqual("deny", self.invoke(roles, f"git switch --track -c {branch} origin/{branch}"))
        self.assertEqual(before, (self.git("diff", "--cached"), self.git("diff"), (self.root / ".git/index").read_bytes()))

    def test_feature_same_head_resume_uses_carried_dirty_scope_without_restaging(self):
        branch = self.feature_ref_fixture()
        self.git("switch", branch)
        self.git("switch", "-c", "chore/inspect")
        path = self.stage_design()
        self.write(path, "Additional human edit\n")
        before = (self.git("diff", "--cached"), self.git("diff"), (self.root / ".git/index").read_bytes())
        self.assertEqual("allow", self.invoke(roles, f"git switch {branch}"))
        self.assertEqual(before, (self.git("diff", "--cached"), self.git("diff"), (self.root / ".git/index").read_bytes()))
        self.write_feature_member("456")
        self.assertEqual("deny", self.invoke(roles, f"git switch {branch}"))

    def test_new_feature_keeps_local_uncommitted_intake_on_synchronized_main(self):
        self.git("switch", "main")
        self.feature()
        before = self.git("status", "--porcelain")
        command = "git switch -c feature/500-feature"
        self.assertEqual("allow", self.invoke(roles, command))
        self.git(*policy.parse_command(command)[1:])
        self.assertEqual(before, self.git("status", "--porcelain"))

    def test_feature_ref_rejects_ambiguous_folders_and_nonregular_prepared_metadata(self):
        branch = self.feature_ref_fixture()
        original = self.git("rev-parse", "refs/heads/" + branch)
        for variant in ("duplicate", "missing-context", "map-symlink", "context-symlink", "folder-symlink"):
            with self.subTest(variant=variant):
                self.git("switch", branch)
                self.git("reset", "--hard", original)
                if variant == "duplicate":
                    self.write("work-items/500-duplicate/notes.md")
                    self.git("add", "--", "work-items/500-duplicate")
                elif variant == "missing-context":
                    self.git("rm", "--", "work-items/500-feature/ado-context.md")
                elif variant == "folder-symlink":
                    self.git("rm", "-r", "--", "work-items/500-feature")
                    blob = self.git("rev-parse", original + ":work-items/500-feature/ado-context.md")
                    self.git("update-index", "--add", "--cacheinfo", "120000", blob, "work-items/500-feature")
                else:
                    name = "delivery-map.md" if variant == "map-symlink" else "ado-context.md"
                    path = "work-items/500-feature/" + name
                    blob = self.git("rev-parse", ":" + path)
                    # Index modes make this fixture portable even on Windows
                    # hosts without permission to create filesystem symlinks.
                    self.git("update-index", "--cacheinfo", "120000", blob, path)
                self.git("commit", "-m", "invalid prepared metadata")
                self.git("update-ref", "refs/remotes/origin/" + branch, "HEAD")
                self.git("switch", "--discard-changes", "main")
                self.assertEqual("deny", self.invoke(roles, f"git switch {branch}"))
                self.assertEqual("deny", self.invoke(roles, f"git switch -c work-item/123-parallel origin/{branch}"))

    def test_child_pr_uses_remote_feature_base_membership_not_current_map(self):
        branch = self.feature_ref_fixture(current_member="123", target_member="456")
        self.git("switch", "-c", "work-item/123-pr")
        self.gh_body()
        command = ("gh pr create --repo example/repository --head work-item/123-pr "
                   f"--base {branch} --title Child --body-file .cache/github/pr-body.md --draft")
        for module in (roles, safety):
            self.assertEqual("deny", self.invoke(module, command))
        self.git("update-ref", "refs/remotes/origin/" + branch, "HEAD")
        self.write_feature_member("456")
        for module in (roles, safety):
            self.assertEqual("ask", self.invoke(module, command))

    def test_assume_unchanged_is_denied(self):
        path = self.stage_design()
        self.git("update-index", "--assume-unchanged", "--", path)
        self.assertDecision("deny", self.commit_command(path))

    def test_symlink_staging_is_denied(self):
        path = self.stage_design()
        self.git("update-index", "--no-assume-unchanged", "--", path)
        alias = self.root / "work-items/123-example/link.md"
        try:
            alias.symlink_to(self.root / path)
        except OSError as exc:
            if os.name != "nt":
                raise
            self.skipTest("This host cannot create symlink fixtures: " + str(exc))
        self.assertDecision("deny", "git add -- work-items/123-example/link.md")

    def test_git_environment_override_denies_local_scope_inspection(self):
        with patch.dict(os.environ, {"GIT_INDEX_FILE": str(self.root / "alternate-index")}):
            self.assertDecision("deny", "git add -- work-items/123-example/design.md")

    def test_literal_commit_messages_pass_both_hooks_without_executing_words(self):
        path = self.stage_design()
        for subject in ("[WI-123] document sf project retrieve — AB#123",
                        "[WI-123] explain git reset --hard protection — AB#123",
                        "[WI-123] explain <VendorNS> and A & B — AB#123",
                        "[WI-123] explain salesforce_operation_session — AB#123"):
            command = self.commit_command(path, subject)
            for module in (roles, safety):
                self.assertEqual("allow", self.invoke(module, command), (module.__name__, command))

    def test_real_chaining_substitution_wrappers_and_destructive_commands_stay_denied(self):
        path = self.stage_design()
        for command in (f'git commit -m "$(touch stolen)" -- {path}',
                        f'git commit -m "`touch stolen`" -- {path}',
                        f'git add -- {path}; git reset --hard', "git reset --hard", "git clean -fd",
                        "git push origin work-item/123-example --force"):
            self.assertEqual("deny", self.invoke(safety, command), command)
        self.assertEqual("deny", self.invoke(safety, 'bash -c "sf project retrieve start"'))

    def test_destructive_git_executable_spellings_keep_global_denial(self):
        for executable in ("git", "git.exe", "/usr/bin/git", '"/tmp/quoted directory/git"', "'git'"):
            for arguments in ("reset --hard", "push --force origin work-item/123-example",
                              "push -f origin work-item/123-example", "clean -fd"):
                command = executable + " " + arguments
                self.assertEqual("deny", self.invoke(safety, command), command)
                self.assertNotEqual("allow", self.invoke(roles, command, "git-agent"), command)

    @unittest.skipIf(os.name == "nt", "This paired-hook case verifies POSIX shell glob expansion")
    def test_unquoted_globs_cannot_expand_force_or_repository_flags(self):
        for command in ("git push --f*", "g'i't push --f*", "gh pr edit 1 --repo example/repository --title --*/?*",
                        "gh pr edit 1 --repo example/repository --title [a-z]*", "git status # ignored options"):
            for module in (roles, safety):
                self.assertEqual("deny", self.invoke(module, command, "git-agent"), command)

    def test_git_agent_keeps_existing_broad_local_taxonomy(self):
        for command in ("git add -A", "git commit --amend -m descriptive", "git branch -D old",
                        "git remote set-url origin https://github.com/example/other.git", "git restore .",
                        "git stash", "git fetch arbitrary", "git log --output local.txt"):
            self.assertDecision("allow", command, "git-agent")
        self.assertDecision("ask", "git push origin work-item/123-example", "git-agent")
        self.assertDecision("deny", "git push origin --delete gone", "git-agent")
        self.assertDecision("allow", "/usr/bin/git add -A", "git-agent")
        self.assertDecision("allow", "git.exe stash", "git-agent")
        self.assertDecision("allow", '"git" add -A', "git-agent")

    def test_all_shell_tool_aliases_enforce_reviewer_git_write_boundary(self):
        self.stage_design()
        for tool in ("Bash", "sh", "pwsh", "execute/runInTerminal", "run_task", "run_commands", "shell"):
            self.assertEqual("deny", self.invoke(roles, "git add -- work-items/123-example/design.md", "reviewer", tool))

    def test_all_eight_roles_receive_bounded_gh_reads(self):
        commands = ["gh --version", "gh auth status", "gh repo view --json nameWithOwner,url",
                    "gh pr list --limit 20 --state open --json number,headRefName",
                    "gh pr view 12 --json headRefOid,baseRefName,mergeStateStatus",
                    "gh pr diff 12 --patch", "gh pr checks 12 --required"]
        for role in roles.ALLOWED_PREFIXES:
            for command in commands:
                self.assertDecision("allow", command, role)

    def test_gh_read_bypasses_and_wrong_targets_are_denied(self):
        for command in ("gh auth token", "gh auth status --show-token", "gh auth status --json token",
                        "gh api repos/example/repository", "gh repo view another/repository",
                        "gh pr view https://github.com/other/repository/pull/12",
                        "gh pr view 12 -R other/repository", "gh pr list -L 10000",
                        "gh pr view 12 --web", "gh pr diff 12 --output outside"):
            self.assertDecision("deny", command, "reviewer")
        with patch.dict(os.environ, {"GH_REPO": "another/repository"}):
            self.assertDecision("deny", "gh pr view 12")
        with patch.dict(os.environ, {"GH_HOST": "elsewhere.example.test"}):
            self.assertDecision("deny", "gh pr view 12")

    def test_reviewer_git_reads_cannot_launch_external_diff_or_write_output(self):
        for command in ("git diff --ext-diff", "git show --textconv", "git grep -Ovi pattern", "git log --output=outside"):
            self.assertFalse(roles.allowed_role_command(command, self.root, "reviewer"))

    def test_gh_create_requires_scoped_explicit_args_and_title_is_literal_in_both_hooks(self):
        self.gh_body()
        command = 'gh pr create --repo example/repository --head work-item/123-example --base main --title "Describe sf project retrieve and git reset --hard" --body-file .cache/github/pr-body.md --draft'
        for role in policy.PUBLISH_ROLES:
            self.assertDecision("ask", command, role)
        for module in (roles, safety):
            self.assertEqual("ask", self.invoke(module, command))
        for variant in (command.replace("--head work-item/123-example ", ""), command.replace("--repo example/repository ", ""),
                        command.replace("--base main", "--base unrelated"), command.replace("work-item/123-example", "work-item/456-other"),
                        command + " --fill", command + " --repo other/repository"):
            self.assertDecision("deny", variant)

    def test_gh_edits_ready_and_merge_need_explicit_pr_and_restricted_role(self):
        self.gh_body()
        sha = self.git("rev-parse", "HEAD")
        for command in ('gh pr edit 12 -R example/repository --title "Updated design" --body-file .cache/github/pr-body.md',
                        "gh pr ready 12 --repo example/repository", "gh pr ready 12 -R example/repository --undo",
                        f"gh pr merge 12 -R example/repository --merge --match-head-commit {sha}"):
            self.assertDecision("ask", command)
            self.assertDecision("deny", command, "reviewer")
            self.assertDecision("deny", command, "knowledge-curator")
        for command in ("gh pr edit 12 -R example/repository --base elsewhere", "gh pr edit 12 -R example/repository --add-reviewer x",
                        "gh pr merge 12 -R example/repository --merge", f"gh pr merge 12 -R example/repository --merge --match-head-commit {sha} --admin",
                        f"gh pr merge 12 -R example/repository --merge --match-head-commit {sha} --delete-branch",
                        "gh pr ready -R example/repository", "gh pr ready somebody-branch -R example/repository",
                        "gh pr ready https://github.com/example/other/pull/12 -R example/repository"):
            self.assertDecision("deny", command)

    def test_repo_global_selector_enterprise_and_no_repeated_options(self):
        self.assertDecision("allow", "gh -R example/repository pr view 12", "reviewer")
        self.assertDecision("deny", "gh -R example/repository pr view 12 --repo example/repository", "reviewer")
        self.git("remote", "set-url", "origin", "git@ghe.example.test:team/project.git")
        self.assertDecision("allow", "gh pr view https://ghe.example.test/team/project/pull/12 --repo ghe.example.test/team/project")
        self.assertDecision("deny", "gh pr view 12 --repo team/project")

    def test_feature_merge_preserves_work_item_history(self):
        self.feature()
        self.git("switch", "-c", "feature/500-feature")
        sha = self.git("rev-parse", "HEAD")
        self.assertDecision("ask", f"gh pr merge 12 -R example/repository --merge --match-head-commit {sha}")
        self.assertDecision("deny", f"gh pr merge 12 -R example/repository --squash --match-head-commit {sha}")

    def test_pr_body_exact_edit_permission_and_quoted_body_data(self):
        payload = {"filePath": str(self.root / policy.PR_BODY), "content": "Explain sf project retrieve and git reset --hard, not an execution."}
        for role in roles.ALLOWED_PREFIXES:
            self.assertEqual("allow" if role in policy.PUBLISH_ROLES else "deny", self.invoke(roles, role=role, tool="create_file", payload=payload), role)
        self.assertEqual("allow", self.invoke(safety, tool="create_file", payload=payload))
        payload["filePath"] = str(self.root / ".cache/github/other.md")
        self.assertEqual("deny", self.invoke(roles, role="git-agent", tool="create_file", payload=payload))

    def test_pr_body_symlink_is_rejected_by_edit_and_gh_guards(self):
        self.gh_body()
        body = self.root / policy.PR_BODY
        body.unlink()
        try:
            body.symlink_to(self.root / "work-items/123-example/ado-context.md")
        except OSError as exc:
            if os.name != "nt":
                raise
            self.skipTest("This host cannot create symlink fixtures: " + str(exc))
        self.assertEqual("deny", self.invoke(roles, tool="create_file", payload={"filePath": str(body), "content": "x"}))
        self.assertDecision("deny", "gh pr edit 12 -R example/repository --body-file .cache/github/pr-body.md")
        self.assertEqual("deny", self.invoke(roles, tool="create_file", payload={"filePath": str(self.root / ".cache/github/../github/pr-body.md"), "content": "x"}))

    def test_pr_body_hard_link_cannot_widen_git_agent_edit_authority(self):
        protected = self.write(".github/copilot-instructions.md", "Protected instructions\n")
        self.gh_body()
        body = self.root / policy.PR_BODY
        body.unlink()
        os.link(protected, body)
        self.assertEqual(2, body.stat().st_nlink)
        self.assertFalse(policy.pr_body_path(self.root, policy.PR_BODY))
        self.assertEqual("deny", self.invoke(roles, role="git-agent", tool="create_file", payload={"filePath": str(body), "content": "new"}))
        self.assertDecision("deny", "gh pr edit 12 -R example/repository --body-file .cache/github/pr-body.md")
        self.assertEqual("Protected instructions\n", protected.read_text())

    def test_scoped_push_is_asked_and_remote_rewrite_flags_are_denied(self):
        self.assertDecision("ask", "git push -u origin work-item/123-example")
        for command in ("git push origin main", "git push other work-item/123-example", "git push origin HEAD:main",
                        "git push --force origin work-item/123-example", "git push origin --delete work-item/123-example"):
            self.assertDecision("deny", command)
        self.git("config", "remote.origin.pushurl", "https://github.com/other/repository.git")
        self.assertDecision("deny", "git push origin work-item/123-example")


class ShellParsingTests(unittest.TestCase):
    def test_missing_or_broken_shared_policy_emits_valid_deny(self):
        source = Path(__file__).resolve().parents[1] / "scripts"
        for failure in (None, 'raise RuntimeError("broken Git policy")\n'):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / "salesforce_operation_policy.py").write_text("# Import-only fixture\n")
                if failure:
                    (root / "git_workflow_policy.py").write_text(failure)
                for name in ("copilot_role_guard.py", "copilot_safety_hook.py"):
                    shutil.copy2(source / name, root / name)
                    args = [sys.executable, str(root / name)]
                    if name == "copilot_role_guard.py":
                        args += ["--role", "developer"]
                    result = subprocess.run(args, input="{}", text=True, capture_output=True, cwd=root)
                    self.assertEqual(0, result.returncode)
                    payload = json.loads(result.stdout)
                    self.assertFalse(payload["continue"])
                    self.assertEqual("deny", payload["hookSpecificOutput"]["permissionDecision"])

    def test_posix_literals_and_windows_paths(self):
        self.assertEqual(["git", "commit", "-m", "literal $value; A & B", "--", "a b.md"],
                         policy.parse_command("git commit -m 'literal $value; A & B' -- 'a b.md'", windows=False))
        self.assertEqual(["gh.exe", "pr", "edit", "12", "--title", "A & B", "--body-file", r".cache\github\pr-body.md"],
                         policy.parse_command('gh.exe pr edit 12 --title "A & B" --body-file ".cache\\github\\pr-body.md"', windows=True))
        for command in ('git commit -m "%PATH%"', 'git commit -m "!VAR!"', 'git commit -m "x" & whoami',
                        "git commit -m 'single quotes are not cmd quoting'", 'git commit -m "unterminated'):
            with self.assertRaises(policy.Rejected):
                policy.parse_command(command, windows=True)

    def test_windows_crt_escaped_quotes_cannot_hide_another_repo_option(self):
        args = ["gh", "pr", "edit", "1", "--repo", "example/repository", "--title", 'x"',
                "--repo", "attacker/repository", "--title", 'y"']
        encoded = subprocess.list2cmdline(args)
        self.assertIn('\\"', encoded)
        with self.assertRaises(policy.Rejected):
            policy.parse_command(encoded, windows=True)
        for token in ('"\\\\\\" --repo attacker/repository"', 'x\\" --admin', '"path\\"'):
            with self.assertRaises(policy.Rejected):
                policy.parse_command("gh pr edit 1 --title " + token, windows=True)

    def test_quoted_glob_characters_remain_literal_but_history_expansion_is_rejected(self):
        self.assertEqual(["git", "commit", "-m", "Literal * ? [] # !"],
                         policy.parse_command("git commit -m 'Literal * ? [] # !'", windows=False))
        for command in ('git commit -m "!!"', "git commit -m !previous", "gh pr edit 1 --title ?*", "git status # comment"):
            with self.assertRaises(policy.Rejected):
                policy.parse_command(command, windows=False)


if __name__ == "__main__":
    unittest.main()
