"""Real local Git proof: final message validation without Salesforce/ADO or state gates."""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.install_git_message_hook import install


SOURCE = Path(__file__).resolve().parents[1]


class GitMessageHookTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        # Test repositories never inherit user hooks, identities or signing settings.
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        self.environment = patch.dict(os.environ, self.env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        for relative in (".githooks/commit-msg", "scripts/git_workflow_policy.py"):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SOURCE / relative, target)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Hook fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        installed, message = install(self.root)
        self.assertTrue(installed, message)
        self.git("add", ".")
        self.git("commit", "-m", "[chore] Initial fixture")

    def git(self, *args, ok=True, input=None, env=None):
        result = subprocess.run(["git", "-C", str(self.root), *args],
                                input=input, env=env or self.env, encoding="utf-8", capture_output=True)
        if ok:
            self.assertEqual(0, result.returncode, result.stderr)
        else:
            self.assertNotEqual(0, result.returncode, result.stdout)
        return result

    def change(self):
        (self.root / "example.txt").write_text("change\n")
        self.git("add", "-A")

    def test_final_file_stdin_and_reused_messages(self):
        self.change()
        before = self.git("rev-parse", "HEAD").stdout
        self.git("commit", "-F", "-", input="bad subject\n", ok=False)
        self.assertEqual(before, self.git("rev-parse", "HEAD").stdout)
        self.git("commit", "-F", "-", input="[WI-123] Change fixture — AB#123\n")
        message = self.root / "message.txt"
        message.write_text("[WI-123] Change fixture — AB#456\n", encoding="utf-8")
        self.git("commit", "--amend", "-F", str(message), ok=False)
        self.git("commit", "--amend", "--no-edit")
        self.git("commit", "--allow-empty", "-C", "HEAD")

    def test_editor_message_is_validated_after_editing(self):
        self.change()
        editor = self.root / "editor.py"
        editor.write_text("from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text('bad edited subject\\n')\n")
        env = {**self.env, "GIT_EDITOR": shlex.join([Path(sys.executable).as_posix(), editor.as_posix()])}
        self.git("commit", env=env, ok=False)
        editor.write_text("from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text('[docs] Edited subject\\n')\n")
        self.git("commit", env=env)
        self.assertEqual("[docs] Edited subject", self.git("log", "-1", "--format=%s").stdout.strip())

    def test_partial_staging_and_arbitrary_branch_preserve_git_semantics(self):
        self.git("switch", "-c", "anything/user-branch")
        self.change()
        (self.root / "example.txt").write_text("unstaged change\n")
        self.git("commit", "-m", "[chore] Commit only staged content")
        self.assertEqual("change", self.git("show", "HEAD:example.txt").stdout.strip())
        self.assertEqual("unstaged change\n", (self.root / "example.txt").read_text())

    def test_verbatim_message_subject_is_checked_without_rewriting(self):
        self.change()
        invalid = "# Invalid actual subject\n[docs] Valid later line\n"
        self.git("commit", "--cleanup=verbatim", "-F", "-", input=invalid, ok=False)
        valid = "[WI-123] Actual change — AB#123\n\n# Related item AB#456\n"
        self.git("commit", "--cleanup=verbatim", "-F", "-", input=valid)
        self.assertEqual(valid, self.git("log", "-1", "--format=%B").stdout.rstrip("\n") + "\n")

    def test_installed_validator_survives_branch_without_harness_files(self):
        self.git("switch", "-c", "historical/without-harness")
        self.git("rm", "scripts/git_workflow_policy.py", ".githooks/commit-msg")
        self.git("commit", "-m", "[chore] Remove harness from historical branch")
        self.change()
        self.git("commit", "-m", "bad subject", ok=False)
        self.git("commit", "-m", "[docs] Work on a branch without harness scripts")

    def test_legacy_encoding_validates_format_without_rewriting_bytes(self):
        self.change()
        self.git("config", "i18n.commitEncoding", "ISO-8859-1")
        message = self.root / "message.txt"
        for content, valid in ((b"Bad caf\xe9 subject\n", False),
                               (b"[WI-123] Caf\xe9 AB#456\n", False),
                               (b"[WI-123] Caf\xe9 AB#123\n\nR\xe9sum\xe9\n", True)):
            message.write_bytes(content)
            result = subprocess.run(["git", "-C", str(self.root), "commit", "--cleanup=verbatim",
                                     "-F", str(message)], env=self.env, capture_output=True)
            self.assertEqual(valid, result.returncode == 0, result.stderr)
            self.assertEqual(content, message.read_bytes())
        stored = subprocess.run(["git", "-C", str(self.root), "cat-file", "commit", "HEAD"],
                                env=self.env, capture_output=True, check=True).stdout
        self.assertEqual(content, stored.split(b"\n\n", 1)[1])

    def test_installer_is_idempotent_and_preserves_custom_hooks(self):
        self.assertTrue(install(self.root)[0])
        target = self.root / ".git/hooks/commit-msg"
        custom = b"#!/bin/sh\n# Existing personal hook\nexit 0\n"
        target.write_bytes(custom)
        self.assertFalse(install(self.root)[0])
        self.assertEqual(custom, target.read_bytes())
        self.git("config", "core.hooksPath", "custom-hooks")
        self.assertFalse(install(self.root)[0])
        self.assertEqual("custom-hooks", self.git("config", "--get", "core.hooksPath").stdout.strip())


if __name__ == "__main__":
    unittest.main()
