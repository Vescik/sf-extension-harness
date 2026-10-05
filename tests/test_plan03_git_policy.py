"""Git is unrestricted across roles; the only Git policy is commit-message format."""
from __future__ import annotations

import json
import os
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


class GitWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

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

    def test_every_role_can_use_all_git_and_gh_operations_without_repository_state(self):
        commands = (
            "git status", "git add .", "git add -A", "git commit -m '[chore] Record changes'",
            "git commit -am '[docs] Explain deployment'", "git commit --amend --no-edit",
            "git switch main", "git checkout -b arbitrary/name", "git branch -D arbitrary/name",
            "git stash pop", "git fetch upstream", "git pull --rebase", "git rebase main",
            "git merge arbitrary", "git cherry-pick HEAD~2", "git reset --hard HEAD",
            "git clean -fd", "git push --force-with-lease origin HEAD:main", "git push --force",
            "git push origin --delete old-branch", "git tag -d old", "git config user.name Example",
            "git -C elsewhere status", "git -c color.ui=always status",
            "gh pr create -R unrelated/project --title Example", "gh pr merge 42 --squash --admin",
            "gh repo view unrelated/project", "gh release create v1", "gh api repos/example/project",
            "git add . && git commit -m '[chore] Save all changes' && git push",
            "cd ../different/repository && git status", "git diff > /tmp/diff.patch",
        )
        for role in roles.ALLOWED_PREFIXES:
            for command in commands:
                with self.subTest(role=role, command=command):
                    self.assertEqual("allow", self.invoke(roles, command, role))
        for command in commands:
            with self.subTest(hook="safety", command=command):
                self.assertEqual("allow", self.invoke(safety, command))

    def test_invalid_literal_message_denied_by_both_hooks_for_all_roles(self):
        for role in roles.ALLOWED_PREFIXES:
            for module in (roles, safety):
                with self.subTest(role=role, module=module.__name__):
                    self.assertEqual("deny", self.invoke(module, "git commit -m 'unformatted subject'", role))
                    self.assertEqual("deny", self.invoke(module, "git commit -m '[WI-123] Work — AB#456'", role))

    def test_mixed_shell_does_not_exempt_non_git_commands(self):
        for command in (
            "git status && rm -rf force-app", "git status; sf project deploy start --target-org prod",
            "git status | python -c 'print(1)'", "git commit -m \"[chore] $(rm -rf force-app)\"",
        ):
            with self.subTest(command=command):
                self.assertEqual("deny", self.invoke(roles, command, "reviewer"))
                if "rm -rf" in command:
                    self.assertEqual("deny", self.invoke(safety, command))

    def test_pr_body_editor_scope_stays_separate_from_git_permissions(self):
        payload = {"filePath": str(self.root / policy.PR_BODY), "content": "Describe git reset --hard as data."}
        for role in roles.ALLOWED_PREFIXES:
            with self.subTest(role=role):
                self.assertEqual("allow" if role in policy.PUBLISH_ROLES else "deny",
                                 self.invoke(roles, role=role, tool="create_file", payload=payload))
        payload["filePath"] = str(self.root / ".cache/github/other.md")
        self.assertEqual("deny", self.invoke(roles, role="git-agent", tool="create_file", payload=payload))

    def test_pr_body_editor_does_not_follow_symlinks_or_hard_links(self):
        protected = self.root / "protected.md"
        protected.write_text("Keep this content", encoding="utf-8")
        body = self.root / policy.PR_BODY
        body.parent.mkdir(parents=True)
        os.link(protected, body)
        self.assertFalse(policy.pr_body_path(self.root, policy.PR_BODY))
        body.unlink()
        try:
            body.symlink_to(protected)
        except OSError:
            self.skipTest("This host cannot create symlink fixtures")
        self.assertFalse(policy.pr_body_path(self.root, policy.PR_BODY))
        self.assertEqual("Keep this content", protected.read_text(encoding="utf-8"))


class CommitMessageTests(unittest.TestCase):
    def test_message_formats_are_independent_of_branch_context_and_ado(self):
        for message in (
            "[chore] Update workspace configuration", "[docs] Explain architecture\n\nAny body text.",
            "[WI-123] Add validation — AB#123", "[FEATURE-456] Integrate billing changes AB#456\n\nSee also AB#789",
            "[WI-123] Fixes validation AB#123\n\nCloses the bug.",
        ):
            with self.subTest(message=message):
                self.assertIsNone(policy.message_error(message))
        for message in ("", "[chore]", "[docs] ", "plain subject", "[WI-0] Work AB#0",
                        "[WI-123] Work", "[WI-123] Work AB#124", "[WI-123] Work AB#123 AB#124",
                        "[WI-123] Work\n\nAB#123", "# invalid subject\n[docs] Hidden later",
                        "\n[docs] Not the first line", "\ufeff[docs] Subject starts with BOM"):
            with self.subTest(message=message):
                self.assertIsNotNone(policy.message_error(message))

    def test_all_common_message_option_spellings(self):
        for arguments in (
            "-m '[chore] Save'", "--message='[chore] Save'", "-m'[chore] Save'",
            "-am '[chore] Save'", "-aqm'[chore] Save'", "--amend -m '[chore] Save'",
            "-m '[WI-123] Save AB#123' -m AB#456", "--message '[FEATURE-456] Save AB#456' -m AB#789",
        ):
            with self.subTest(arguments=arguments):
                self.assertEqual("allow", policy.inspect_command("git commit " + arguments, Path.cwd()).decision)
        for arguments in ("-m bad", "--message=bad", "-mbad", "-am bad", "-aqmbad", "--amend -m bad"):
            with self.subTest(arguments=arguments):
                self.assertEqual("deny", policy.inspect_command("git commit " + arguments, Path.cwd()).decision)

    def test_message_files_follow_cd_and_git_C_without_git_subprocesses(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "nested" / "repo"
            target.mkdir(parents=True)
            message = target / "message.txt"
            message.write_text("invalid\n", encoding="utf-8")
            for command in ("git -C nested/repo commit -F message.txt", "cd nested && git -C repo commit --file=message.txt",
                            "git -Cnested -C repo commit -Fmessage.txt", "env -C nested/repo git commit -Fmessage.txt"):
                with self.subTest(command=command):
                    self.assertEqual("deny", policy.inspect_command(command, root).decision)
            message.write_text("[chore] Saved from file\n", encoding="utf-8")
            self.assertEqual("allow", policy.inspect_command("git -C nested/repo commit -F message.txt", root).decision)

    def test_dynamic_directories_defer_file_reads_but_not_literal_messages(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "message.txt").write_text("invalid", encoding="utf-8")
            for prefix in ('git -C "$ROOT"', 'cd "$ROOT" && git', 'env -C "$ROOT" git'):
                with self.subTest(prefix=prefix):
                    self.assertEqual("allow", policy.inspect_command(prefix + " commit -F message.txt", root).decision)
                    self.assertEqual("deny", policy.inspect_command(prefix + " commit -m bad", root).decision)

    def test_dynamic_editor_stdin_and_reused_messages_defer_to_native_hook(self):
        for command in ("git commit", "git commit --amend --no-edit", "git commit -C HEAD", "git commit -F -",
                        'git commit -m "$MESSAGE"', "git commit -F missing.txt", "git commit --fixup HEAD",
                        "git commit --edit -m 'a draft to edit'"):
            with self.subTest(command=command):
                result = policy.inspect_command(command, Path.cwd())
                self.assertTrue(result.has_git)
                self.assertEqual("allow", result.decision)
                self.assertFalse(result.remaining_commands)

    def test_final_message_cli_returns_sanitized_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "COMMIT_EDITMSG"
            for message, exit_code in (
                ("[docs] Explain Git", 0), ("sensitive invalid contents", 1),
                ("[WI-123] Save AB#123\n# Editor reference AB#456\n", 0),
                ("[WI-123] Save AB#123\n# ------------------------ >8 ------------------------\n+AB#456", 0),
                ("# invalid subject\n[docs] Hidden later", 1),
                ("# ------------------------ >8 ------------------------\n[docs] Hidden later", 1),
                ("\n[docs] Not the first line", 1),
                ("\ufeff[docs] Subject starts with BOM", 1),
            ):
                path.write_text(message, encoding="utf-8")
                result = subprocess.run([sys.executable, policy.__file__, "--message-file", str(path)],
                                        text=True, capture_output=True, check=False)
                self.assertEqual(exit_code, result.returncode)
                self.assertNotIn("sensitive", result.stderr)
                self.assertEqual(message, path.read_text(encoding="utf-8"))


class ShellParsingTests(unittest.TestCase):
    def inspect(self, command, **kwargs):
        return policy.inspect_command(command, Path.cwd(), **kwargs)

    def test_paths_flags_chains_navigation_and_redirects_are_not_restrictions(self):
        for command in (
            '"C:\\Program Files\\Git\\cmd\\git.exe" -C "C:\\repo" status',
            '/usr/local/bin/git -c core.quotePath=false --git-dir=.git status',
            'cd /tmp && git add -A && git commit -m "[chore] Save; pipes | are literal"',
            'git status; git log > /tmp/log.txt 2>&1', 'git diff | git apply',
            "env GIT_INDEX_FILE=other-index git add -A", "command git status", "GIT_DIR=.git git status",
            'git -C ${PWD} status', 'if git status; then git diff; fi', 'git status &> /tmp/log.txt',
            "bash -c 'git status && git diff'", 'cmd /c "git status"',
            'git show HEAD~$((1 + 1))', 'git add -- $(git diff --name-only)',
        ):
            with self.subTest(command=command):
                result = self.inspect(command)
                self.assertTrue(result.has_git)
                self.assertEqual("allow", result.decision)
                self.assertEqual((), result.remaining_commands)

    def test_mixed_commands_and_nested_substitutions_stay_visible(self):
        for command, expected in (
            ("git status && sf project deploy start", "sf project deploy start"),
            ("git status; rm -rf force-app", "rm -rf force-app"),
            ('git commit -m "[chore] $(sf org display)"', "sf org display"),
            ('git status `rm -rf force-app`', "rm -rf force-app"),
            ('git status <(rm -rf force-app)', "rm -rf force-app"),
            ("bash -c 'git status && rm -rf force-app'", "rm -rf force-app"),
            ("cd /tmp && git status && sf project deploy start", "cd /tmp && sf project deploy start"),
            ('git show HEAD~$((1 + $(sf org display)))', "sf org display"),
        ):
            with self.subTest(command=command):
                result = self.inspect(command)
                self.assertTrue(result.has_git)
                self.assertIn(expected, result.remaining_commands)
        literal = self.inspect("git commit -m '[chore] Document $(rm -rf) and git reset --hard'")
        self.assertEqual((), literal.remaining_commands)
        self.assertEqual("allow", literal.decision)

    def test_parse_errors_remain_on_normal_policy_path(self):
        for command in ('git commit -m "unterminated', "git status $(unfinished"):
            result = self.inspect(command)
            self.assertFalse(result.has_git)
            self.assertEqual((command,), result.remaining_commands)

    def test_wrapper_argument_values_cannot_masquerade_as_git_executables(self):
        for command in ("exec -a git rm -rf /tmp/example", "env -a git sf project deploy start",
                        "env --argv0 git sf project deploy start", "env --unknown-option git rm -rf /tmp/example"):
            with self.subTest(command=command):
                result = self.inspect(command)
                self.assertFalse(result.has_git)
                self.assertEqual((command,), result.remaining_commands)
                mixed = self.inspect("git status && " + command)
                self.assertTrue(mixed.has_git)
                self.assertEqual((command,), mixed.remaining_commands)

    def test_windows_messages_paths_and_non_git_chain(self):
        result = self.inspect('"C:\\Program Files\\Git\\cmd\\git.exe" commit -m "[chore] Windows"', windows=True)
        self.assertTrue(result.has_git)
        self.assertEqual("allow", result.decision)
        self.assertEqual(("Remove-Item -Recurse force-app",),
                         self.inspect("git status & Remove-Item -Recurse force-app", windows=True).remaining_commands)
        self.assertEqual("allow", self.inspect('git commit -m "%MESSAGE%"', windows=True).decision)


if __name__ == "__main__":
    unittest.main()
