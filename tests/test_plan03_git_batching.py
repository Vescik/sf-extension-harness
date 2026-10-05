"""Git admission no longer inspects files, filters, index state or repository scope."""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import git_workflow_policy as policy


class GitAdmissionStateIndependenceTests(unittest.TestCase):
    def test_bulk_staging_and_commit_need_no_repo_or_process(self):
        paths = " ".join(f"outside-scope/{index}.txt" for index in range(1000))
        with patch("subprocess.run", side_effect=AssertionError("No subprocess belongs in Git admission")), \
                patch.dict(os.environ, {"GIT_INDEX_FILE": "custom-index", "GIT_DIR": "elsewhere/.git"}):
            for command in ("git add .", "git add -A", "git add -- " + paths,
                            "git commit -m '[WI-999] Save files AB#999' -- " + paths):
                with self.subTest(operation=command[:40]):
                    result = policy.inspect_command(command, Path("/not/a/repository"))
                    self.assertTrue(result.has_git)
                    self.assertEqual("allow", result.decision)
                    self.assertFalse(result.remaining_commands)

    def test_partial_index_invalid_ado_and_branch_names_do_not_affect_admission(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def git(*args):
                return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True).stdout
            git("init", "-b", "main")
            git("config", "user.name", "Local test")
            git("config", "user.email", "test@example.invalid")
            target = root / "arbitrary.txt"
            target.write_text("staged text", encoding="utf-8")
            git("add", ".")
            target.write_text("unstaged text", encoding="utf-8")
            config = root / "config/harness.local.json"
            config.parent.mkdir()
            config.write_bytes(b"\xff invalid ADO configuration")
            index_before = (root / ".git/index").read_bytes()
            status_before = git("status", "--porcelain")
            for command in ("git add .", "git commit -m '[chore] Save partial staging'", "git push origin main"):
                self.assertEqual("allow", policy.inspect_command(command, root).decision)
            self.assertEqual(index_before, (root / ".git/index").read_bytes())
            self.assertEqual(status_before, git("status", "--porcelain"))
            self.assertEqual("unstaged text", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
