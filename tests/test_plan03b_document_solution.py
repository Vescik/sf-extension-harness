"""Plan 03b's narrow editor grant remains independent of unrestricted Git access.

Contract: Developer may edit exactly three files per lowercase hyphenated solution
slug. Regression: a broad docs grant or path alias would overwrite unrelated files.
Gap: delivery-document tests do not cover this set or in-repository redirection.
Git validates commit-message syntax; it does not repeat editor path or role checks.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts import copilot_role_guard as roles


class SolutionDocumentationFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "repo"
        self.root.mkdir()
        self.paths = [f"docs/solutions/invoice-approval/{name}.md"
                      for name in ("overview", "flows", "components")]

    def write(self, path, content="# Source-backed documentation\n"):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")
        return file

    def symlink(self, alias, target, *, directory=False):
        alias = self.root / alias
        alias.parent.mkdir(parents=True, exist_ok=True)
        try:
            alias.symlink_to(target, target_is_directory=directory)
        except OSError as exc:
            if os.name != "nt":
                raise
            self.skipTest("This host cannot create symlink fixtures: " + str(exc))
        return alias

    def invoke(self, payload, *, role="developer", tool="edit/editFiles", cwd=None):
        event = {"cwd": str(cwd or self.root), "tool_name": tool, "tool_input": payload}
        stdout = StringIO()
        with (patch("sys.stdin", StringIO(json.dumps(event))),
              patch("sys.argv", ["guard", "--role", role]),
              patch.object(roles, "HARNESS_ROOT", self.root),
              patch.object(roles, "METADATA_ROOT", self.root),
              patch.object(roles, "_log_decision"), redirect_stdout(stdout)):
            self.assertEqual(0, roles.main())
        response = json.loads(stdout.getvalue())
        return "allow" if response.get("continue") else response["hookSpecificOutput"]["permissionDecision"]

    def edit(self, path, **kwargs):
        return self.invoke({"filePath": str(path), "content": "Updated documentation\n"}, **kwargs)

    def git(self, *args):
        result = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout.strip()

    def git_decision(self, *args, role="developer"):
        command = subprocess.list2cmdline(["git", *args]) if os.name == "nt" else shlex.join(["git", *args])
        return self.invoke({"command": command}, role=role, tool="execute/runInTerminal")

    def init_git(self, branch="work-item/123-invoice-approval", *, with_context=True):
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Local test")
        self.git("config", "user.email", "local-test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.write(".gitignore", ".cache/\noutput/\n")
        if branch.startswith("work-item/") and with_context:
            self.write("work-items/123-invoice-approval/ado-context.md", "# Work Item 123\nType: User Story\n")
        self.git("add", ".")
        self.git("commit", "-m", "fixture")
        self.git("switch", "-c", branch)


class SolutionDocumentationEditTests(SolutionDocumentationFixture):
    def test_three_files_can_be_created_and_updated_through_host_edit_events(self):
        for tool in ("create_file", "edit/editFiles", "apply_patch"):
            with self.subTest(tool=tool, phase="create"):
                self.assertEqual("allow", self.invoke({"files": self.paths}, tool=tool))
        for path in self.paths:
            self.write(path)
        for tool in ("replace_string_in_file", "edit/editFiles"):
            with self.subTest(tool=tool, phase="update"):
                self.assertEqual("allow", self.invoke({"files": self.paths}, tool=tool))

    def test_only_exact_names_and_lowercase_hyphenated_slugs_are_allowed(self):
        invalid = (
            "docs/solutions/invoice-approval/technical-documentation.md",
            "docs/solutions/invoice-approval/README.md",
            "docs/solutions/invoice-approval/overview.json",
            "docs/solutions/invoice-approval/Overview.md",
            "docs/solutions/invoice-approval/overview.md/child.md",
            "docs/solutions/invoice-approval/nested/overview.md",
            "docs/solutions/Billing/invoice-approval/overview.md",
            "docs/solutions/Invoice-approval/overview.md",
            "docs/solutions/invoice_approval/overview.md",
            "docs/solutions/invoice approval/overview.md",
            "docs/solutions/-invoice/overview.md",
            "docs/solutions/invoice-/overview.md",
            "docs/solutions/invoice--approval/overview.md",
            "docs/solutions/zażółć/overview.md",
            "docs/solutions/overview.md",
            "docs/solutions",
            "docs/other/overview.md",
            "docs/workspace-topology.md",
        )
        for path in invalid:
            with self.subTest(path=path):
                self.assertEqual("deny", self.edit(path))
        self.assertEqual("allow", self.edit("docs/solutions/invoice-v2/overview.md"))
        self.assertEqual("deny", self.invoke({"files": [*self.paths, invalid[0]]}))

    def test_absolute_nested_cwd_and_native_separator_paths_keep_the_same_boundary(self):
        self.assertEqual("allow", self.edit(self.root / self.paths[0]))
        folder = self.root / "docs/solutions/invoice-approval"
        folder.mkdir(parents=True)
        self.assertEqual("allow", self.edit("overview.md", cwd=folder))
        self.assertEqual("deny", self.edit(self.root.parent / self.paths[0]))
        self.assertEqual("allow" if os.name == "nt" else "deny",
                         self.edit(r"docs\solutions\invoice-approval\overview.md"))
        self.assertEqual("deny", self.edit(r"docs\solutions\invoice-approval\..\..\..\work-items\123\design.md"))

    def test_traversal_cannot_reenter_solution_scope_or_other_developer_grants(self):
        for path in (
            "docs/solutions/invoice-approval/../other/overview.md",
            "docs/solutions/invoice-approval/../../../work-items/123-example/design.md",
            "docs/solutions/invoice-approval/../../../output/documentation/example.md",
            "docs/solutions/invoice-approval/../../../../outside.md",
            "work-items/../docs/solutions/invoice-approval/overview.md",
            "docs/../docs/solutions/invoice-approval/overview.md",
        ):
            with self.subTest(path=path):
                self.assertEqual("deny", self.edit(path))

    def test_solution_file_symlinks_cannot_redirect_into_any_existing_grant(self):
        targets = (
            "work-items/123-example/design.md",
            "output/documentation/example.md",
            ".cache/ado-items/item.md",
            "force-app/main/default/classes/Example.cls",
            "docs/solutions/other/overview.md",
            "docs/workspace-topology.md",
        )
        for index, target in enumerate(targets):
            with self.subTest(target=target):
                file = self.write(target, "Preserve me\n")
                alias = self.symlink(f"docs/solutions/alias-{index}/overview.md", file)
                self.assertEqual("deny", self.edit(alias))
                self.assertEqual("Preserve me\n", file.read_text())
        outside = self.root.parent / "outside.md"
        outside.write_text("Outside repository\n")
        self.assertEqual("deny", self.edit(self.symlink("docs/solutions/outside/overview.md", outside)))

    def test_directory_symlinks_and_aliases_into_solution_documents_are_denied(self):
        target = self.write(self.paths[0])
        for alias in ("work-items/123-alias/overview.md", "docs/solutions/invalid/extra.md"):
            with self.subTest(alias=alias):
                self.assertEqual("deny", self.edit(self.symlink(alias, target)))
        allowed_folder = self.write("work-items/123-target/overview.md").parent
        alias = self.symlink("docs/solutions/directory-alias", allowed_folder, directory=True)
        self.assertEqual("deny", self.edit(alias / "overview.md"))
        # The docs/solutions ancestor itself must not redirect to another allowed tree.
        separate_root = self.root / "second"
        separate_root.mkdir()
        (separate_root / "docs").mkdir()
        self.symlink("second/docs/solutions", self.root / "work-items", directory=True)
        original_root = self.root
        try:
            self.root = separate_root
            self.assertEqual("deny", self.edit("docs/solutions/123-target/overview.md"))
        finally:
            self.root = original_root

    def test_hard_links_and_directories_do_not_receive_file_write_authority(self):
        protected = self.write(".github/copilot-instructions.md", "Protected instructions\n")
        target = self.root / self.paths[0]
        target.parent.mkdir(parents=True)
        os.link(protected, target)
        self.assertEqual("deny", self.edit(target))
        self.assertEqual("Protected instructions\n", protected.read_text())
        directory = self.root / self.paths[1]
        directory.mkdir()
        self.assertEqual("deny", self.edit(directory))

    def test_other_role_authorities_and_existing_developer_lanes_are_unchanged(self):
        for role in roles.ALLOWED_PREFIXES:
            with self.subTest(role=role):
                expected = "allow" if role in {"developer", "workspace-maintainer"} else "deny"
                self.assertEqual(expected, self.edit(self.paths[0], role=role))
        # Maintainer already owns docs; the new filename restriction adds no role restriction.
        self.assertEqual("allow", self.edit("docs/solutions/invoice-approval/notes.md", role="workspace-maintainer"))
        for path in ("work-items/123-example/technical-documentation.md",
                     "output/documentation/example.md", "docs/org-changes/2026-09-30-example.md",
                     "force-app/main/default/classes/Example.cls"):
            with self.subTest(path=path):
                self.assertEqual("allow", self.edit(path))
        self.assertEqual("deny", self.edit(".ai/knowledge/artifacts/example.md"))


class SolutionDocumentationGitTests(SolutionDocumentationFixture):
    def test_three_files_inherit_scoped_local_commit_and_preserve_unrelated_work(self):
        self.init_git()
        for path in self.paths:
            self.write(path)
        other = self.write("docs/unrelated.md", "Human notes\n")
        self.assertEqual("allow", self.git_decision("add", "--", *self.paths))
        self.git("add", "--", *self.paths)
        args = ("commit", "-m", "[WI-123] document invoice approval — AB#123", "--", *self.paths)
        self.assertEqual("allow", self.git_decision(*args))
        self.git(*args)
        self.assertEqual(set(self.paths), set(self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()))
        self.assertEqual("Human notes\n", other.read_text())
        self.assertEqual("?? docs/unrelated.md", self.git("status", "--short"))

    def test_git_authority_is_independent_of_editor_scope_for_every_role(self):
        self.init_git()
        for path in self.paths:
            self.write(path)
        self.write("docs/solutions/invoice-approval/extra.md")
        self.assertEqual("allow", self.git_decision("add", "--", *self.paths, "docs/solutions/invoice-approval/extra.md"))
        for role in roles.ALLOWED_PREFIXES:
            with self.subTest(role=role):
                self.assertEqual("allow", self.git_decision("add", "--", *self.paths, role=role))

    def test_standalone_documentation_uses_existing_chore_commit_without_fictional_item(self):
        self.init_git("chore/document-invoice-approval")
        for path in self.paths:
            self.write(path)
        self.assertEqual("allow", self.git_decision("add", "--", *self.paths))
        self.git("add", "--", *self.paths)
        self.assertEqual("allow", self.git_decision("commit", "-m", "[docs] document invoice approval", "--", *self.paths))
        self.assertFalse((self.root / "work-items").exists())

    def test_existing_work_item_branch_can_commit_solution_docs_without_manufactured_intake(self):
        self.init_git(with_context=False)
        for path in self.paths:
            self.write(path)
        for additional in ("docs/solutions/invoice-approval/extra.md",
                           "force-app/main/default/classes/Example.cls",
                           "work-items/123-invoice-approval/design.md"):
            self.write(additional)
            self.assertEqual("allow", self.git_decision("add", "--", *self.paths, additional), additional)
            (self.root / additional).unlink()
        self.assertEqual("allow", self.git_decision("add", "--", *self.paths))
        self.git("add", "--", *self.paths)
        args = ("commit", "-m", "[WI-123] document invoice approval — AB#123", "--", *self.paths)
        self.assertEqual("allow", self.git_decision(*args))
        self.git(*args)
        self.assertEqual(set(self.paths), set(self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()))
        self.assertFalse((self.root / "work-items/123-invoice-approval/ado-context.md").exists())

    def test_git_path_handling_is_not_an_editor_permission_check(self):
        self.init_git()
        source = self.write("work-items/123-invoice-approval/design.md")
        self.symlink(self.paths[0], source)
        self.assertEqual("allow", self.git_decision("add", "--", self.paths[0]))
        self.assertEqual("allow", self.git_decision("add", "--", "docs/solutions/other/../invoice-approval/overview.md"))


if __name__ == "__main__":
    unittest.main()
