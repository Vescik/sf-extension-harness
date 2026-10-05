#!/usr/bin/env python3
"""Install the message-only Git hook without replacing an existing hook configuration."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


SNAPSHOT_MARKER = b"# sf-harness installed commit-message validator\n"


def install(root: Path) -> tuple[bool, str]:
    root = root.resolve()

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)

    worktree = git("rev-parse", "--show-toplevel")
    if worktree.returncode or Path(worktree.stdout.strip()).resolve() != root:
        return False, "Run the installer from a complete harness checkout."
    configured = git("config", "--get", "core.hooksPath")
    if configured.returncode == 0:
        return False, ("Existing core.hooksPath preserved. Add the harness commit-message validator "
                       "to your existing commit-msg hook; see the Git Workflow skill.")
    if configured.returncode != 1:
        return False, "Could not read Git hook configuration; nothing changed."
    location = git("rev-parse", "--git-path", "hooks/commit-msg")
    if location.returncode:
        return False, "Could not resolve the local Git hooks directory; nothing changed."
    target = Path(location.stdout.strip())
    if not target.is_absolute():
        target = root / target
    source = root / ".githooks/commit-msg"
    try:
        content = source.read_bytes()
        policy = SNAPSHOT_MARKER + (root / "scripts/git_workflow_policy.py").read_bytes()
        if target.is_symlink():
            return False, "Existing commit-msg symlink preserved; integrate the validator in your hook."
        already_installed = target.exists()
        if already_installed:
            if not target.is_file() or target.read_bytes() != content:
                return False, "Existing commit-msg hook preserved; integrate the validator in your hook."
        snapshot = target.with_name("sf-harness-git-message-policy.py")
        if snapshot.is_symlink() or (snapshot.exists() and (
                not snapshot.is_file() or not snapshot.read_bytes().startswith(SNAPSHOT_MARKER))):
            return False, "Existing validator path preserved; integrate the validator in your hook."
        target.parent.mkdir(parents=True, exist_ok=True)
        # Pin a standalone copy in Git metadata: switching branches must neither
        # disable validation nor require that branch to contain harness scripts.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(policy)
            os.replace(temporary, snapshot)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        if not already_installed:
            # Exclusive creation also preserves a hook installed concurrently.
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o755)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
        target.chmod(target.stat().st_mode | 0o111)
    except OSError as exc:
        return False, f"Git message-hook installation failed ({type(exc).__name__}); inspect the local hook."
    return True, "Installed Git commit-message validation. Git operations have no harness restrictions."


def main() -> int:
    installed, message = install(Path(__file__).resolve().parents[1])
    print(message)
    return 0 if installed else 1


if __name__ == "__main__":
    raise SystemExit(main())
