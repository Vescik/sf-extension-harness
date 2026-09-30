"""Bounded Git inspection must cover every selected path without changing state.

The existing policy suite retains the command and single-file safety contracts.
These regressions cover bulk admission, failures beyond the first batch, and Git's
per-path clean conversion. The fixture is composed to avoid collecting its tests twice.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import copilot_role_guard as roles
from scripts import copilot_safety_hook as safety
from scripts import git_workflow_policy as policy
from tests import test_plan03_git_policy as fixtures


class GitBatchingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = self.make_fixture()

    def make_fixture(self):
        fixture = fixtures.GitWorkflowTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        return fixture

    def staged_paths(self, fixture, count):
        paths = [f"work-items/123-example/batch-{index:03d}.md" for index in range(count)]
        for index, path in enumerate(paths):
            fixture.write(path, f"original {index}\n")
        fixture.git("add", "--", *paths)
        fixture.git("commit", "-m", "batch fixture")
        for index, path in enumerate(paths):
            file = fixture.write(path, f"changed {index}\n")
            os.utime(file, (1_000_000_000, 1_000_000_000))
        fixture.git("add", "--", *paths)
        return paths

    def command(self, operation, paths):
        message = ["-m", "[WI-123] document selected changes — AB#123"] if operation == "commit" else []
        return fixtures.shell_command(["git", operation, *message, "--", *paths])

    def state(self, fixture):
        files = {
            path.relative_to(fixture.root).as_posix(): (path.read_bytes(), path.stat().st_mode)
            for path in fixture.root.rglob("*")
            if ".git" not in path.relative_to(fixture.root).parts and path.is_file()
        }
        return fixture.git("rev-parse", "HEAD"), (fixture.root / ".git/index").read_bytes(), files

    def assert_hooks(self, fixture, expected, command):
        before = self.state(fixture)
        # Both hooks admit valid commands; index-state denial belongs to the role hook.
        for module in (roles, safety) if expected == "allow" else (roles,):
            with self.subTest(hook=module.__name__):
                self.assertEqual(expected, fixture.invoke(module, command))
                self.assertEqual(before, self.state(fixture))

    def test_one_hundred_files_pass_both_hooks_with_bounded_git_calls_and_no_mutation(self):
        fixture = self.fixture
        paths = self.staged_paths(fixture, 100)
        fixture.write("work-items/456-other/design.md", "Unrelated human work\n")
        before = self.state(fixture)
        run = subprocess.run
        for operation in ("add", "commit"):
            for module in (roles, safety):
                with self.subTest(operation=operation, hook=module.__name__):
                    with patch.object(policy.subprocess, "run", wraps=run) as calls:
                        self.assertEqual("allow", fixture.invoke(module, self.command(operation, paths)))
                    # A loose fixed bound catches the old five-processes-per-file
                    # regression without pinning unrelated inspection details or timing.
                    self.assertLessEqual(calls.call_count, 32)
                    self.assertEqual(before, self.state(fixture))

    def test_later_batches_preserve_equality_flags_deletions_and_ignore_boundaries(self):
        for index, condition in enumerate(("clean", "hidden edit", "skip-worktree", "recreated deletion", "ignored")):
            with self.subTest(condition=condition):
                fixture = self.fixture if index == 0 else self.make_fixture()
                fixture.git("config", "core.trustctime", "false")
                fixture.git("config", "core.checkStat", "minimal")
                paths = self.staged_paths(fixture, 20)
                last = paths[-1]
                with patch.object(policy, "GIT_ARGUMENT_BUDGET", 1024):
                    batches = list(policy.path_batches(SimpleNamespace(root=fixture.root), set(paths)))
                    self.assertGreater(len(batches), 1)
                    self.assertIn(last, batches[-1])
                    if condition == "hidden edit":
                        file = fixture.root / last
                        metadata = file.stat()
                        content = file.read_bytes()
                        # Preserve native CRLF/LF so only content changes, not size.
                        file.write_bytes(content.replace(b"changed", b"altered", 1))
                        os.utime(file, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
                        self.assertEqual(metadata.st_size, file.stat().st_size)
                        self.assertNotEqual(content, file.read_bytes())
                        self.assertEqual("", fixture.git("diff", "--", last))
                    elif condition == "skip-worktree":
                        fixture.git("update-index", "--skip-worktree", "--", last)
                    elif condition == "recreated deletion":
                        fixture.git("rm", "-f", "--", last)
                        fixture.write(last, "Recreated human work\n")
                    elif condition == "ignored":
                        with (fixture.root / ".git/info/exclude").open("a", encoding="utf-8") as excludes:
                            excludes.write("\n" + last + "\n")
                    for operation in ("add", "commit"):
                        self.assert_hooks(fixture, "allow" if condition == "clean" else "deny",
                                          self.command(operation, paths))

    def test_batch_hashes_use_each_paths_clean_filter_and_crlf_rules(self):
        fixture = self.fixture
        script = fixture.write(".cache/batch-filter.py", "import sys\n"
                               "data = sys.stdin.buffer.read()\n"
                               "sys.stdout.buffer.write(data.upper() if sys.argv[1] == 'upper' else data.lower())\n")
        # Git runs clean commands with its shell, including Git for Windows' shell.
        # Forward-slash executable paths and POSIX quoting work in that shell.
        for mode in ("upper", "lower"):
            fixture.git("config", f"filter.batch-{mode}.clean",
                        shlex.join([Path(sys.executable).as_posix(), script.as_posix(), mode]))
            fixture.git("config", f"filter.batch-{mode}.required", "true")
        paths = ["work-items/123-example/z upper.md", "work-items/123-example/m eol.md",
                 "work-items/123-example/a lower.md"]
        fixture.write(".gitattributes", '*.md text eol=lf\n"' + paths[0] + '" filter=batch-upper\n"'
                      + paths[2] + '" filter=batch-lower\n')
        for path in paths:
            fixture.write(path, "Mixed content\n")
        fixture.git("add", "--", *paths)
        (fixture.root / paths[1]).write_bytes(b"Mixed content\r\n")
        self.assertEqual("MIXED CONTENT", fixture.git("show", ":" + paths[0]))
        self.assertEqual("mixed content", fixture.git("show", ":" + paths[2]))
        for path in paths:
            self.assertNotEqual(fixture.git("rev-parse", ":" + path),
                                fixture.git("hash-object", "--no-filters", "--", path))
        self.assert_hooks(fixture, "allow", self.command("commit", paths))

    def test_partial_failed_or_malformed_hash_output_denies_the_whole_batch(self):
        fixture = self.fixture
        paths = self.staged_paths(fixture, 3)
        hashes = fixture.git("hash-object", "--", *paths).splitlines()
        run = subprocess.run
        cases = {
            "failure after valid prefix": (128, hashes[:1]),
            "missing hash": (0, hashes[:-1]),
            "extra hash": (0, hashes + hashes[:1]),
            "invalid hash": (0, ["not-an-object-id", *hashes[1:]]),
            "wrong order": (0, list(reversed(hashes))),
        }
        for name, (returncode, output) in cases.items():
            with self.subTest(output=name):
                intercepted = []

                def inspect(argv, *args, **kwargs):
                    if argv[4:5] == ["hash-object"]:
                        intercepted.append(argv)
                        return subprocess.CompletedProcess(argv, returncode,
                                                           ("\n".join(output) + "\n").encode(), b"hash failure")
                    return run(argv, *args, **kwargs)

                with patch.object(policy.subprocess, "run", side_effect=inspect):
                    self.assert_hooks(fixture, "deny", self.command("commit", paths))
                self.assertEqual(1, len(intercepted), "The role hook must reach the hash inspection once")

    def test_incomplete_ambiguous_or_out_of_scope_index_records_deny(self):
        fixture = self.fixture
        paths = self.staged_paths(fixture, 3)
        records = fixture.git("ls-files", "--stage", "-v", "-z", "--", *paths)
        first = records.split("\0")[0] + "\0"
        cases = {
            "unterminated": records[:-1],
            "duplicate": records + first,
            "unexpected path": records.replace(paths[-1], "work-items/123-example/not-selected.md"),
            "nonzero stage": records.replace(" 0\t", " 1\t", 1),
        }
        run = subprocess.run
        for name, output in cases.items():
            with self.subTest(records=name):
                intercepted = []

                def inspect(argv, *args, **kwargs):
                    if argv[4:6] == ["ls-files", "--stage"]:
                        intercepted.append(argv)
                        return subprocess.CompletedProcess(argv, 0, output.encode(), b"")
                    return run(argv, *args, **kwargs)

                with patch.object(policy.subprocess, "run", side_effect=inspect):
                    self.assert_hooks(fixture, "deny", self.command("commit", paths))
                self.assertEqual(1, len(intercepted))

    def test_argument_budget_includes_long_root_spaces_and_non_bmp_characters(self):
        root = self.fixture.root / ("long workspace 🌿 " * 10)
        repo = SimpleNamespace(root=root)
        paths = {f"work-items/123-example/file {index:02d} {'🌿' * 5}.md" for index in range(20)}
        commands = (
            ["check-ignore", "--no-index", "--"],
            ["diff", "--name-only", "--no-ext-diff", "--no-textconv", "--no-renames", "-z", "--"],
            ["ls-files", "--stage", "-v", "-z", "--"],
            ["hash-object", "--"],
        )
        with patch.object(policy, "GIT_ARGUMENT_BUDGET", 1024):
            batches = list(policy.path_batches(repo, paths))
            self.assertGreater(len(batches), 1)
            self.assertEqual(sorted(paths), [path for batch in batches for path in batch])
            for batch in batches:
                for command in commands:
                    argv = ["git", "--no-optional-locks", "-C", str(root), *command, *batch]
                    serialized = subprocess.list2cmdline(argv)
                    windows_units = len(serialized.encode("utf-16-le")) // 2 + 1
                    posix_bytes = sum(len(os.fsencode(arg)) + 1 for arg in argv) + 8 * (len(argv) + 1)
                    self.assertGreater(windows_units, len(serialized))
                    self.assertLessEqual(windows_units, 1024)
                    self.assertLessEqual(posix_bytes, 1024)
            with self.assertRaises(policy.Rejected):
                list(policy.path_batches(repo, {"x" * 1024}))
            with self.assertRaises(policy.Rejected):
                list(policy.path_batches(SimpleNamespace(root=root / ("x" * 1024)), {"short.md"}))

    def test_batches_share_the_original_deadline(self):
        fixture = self.fixture
        paths = self.staged_paths(fixture, 20)
        repo = policy.Repo(fixture.root)
        inspect = repo.git
        hashed_batches = []

        def expire_after_first_batch(*args, **kwargs):
            result = inspect(*args, **kwargs)
            if args[0] == "hash-object":
                hashed_batches.append(args)
                repo.deadline = 0
            return result

        before = self.state(fixture)
        with patch.object(policy, "GIT_ARGUMENT_BUDGET", 1024), \
                patch.object(repo, "git", side_effect=expire_after_first_batch):
            with self.assertRaisesRegex(policy.Rejected, "bounded hook budget"):
                policy.require_index_equality(repo, set(paths))
        self.assertEqual(1, len(hashed_batches))
        self.assertEqual(before, self.state(fixture))


if __name__ == "__main__":
    unittest.main()
