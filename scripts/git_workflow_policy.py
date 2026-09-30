"""Local Git/gh command admission for plan 03; no executor, network or consent registry.

The model owns semantic scope and remote PR inspection. This module checks argv, local
repository state and role boundaries; it cannot infer a user's request from a command.
"""
from __future__ import annotations

import os
import re
import shlex
import stat
import subprocess
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

AUTHOR_ROLES = frozenset({"designer", "developer", "test-strategist", "workspace-maintainer"})
PUBLISH_ROLES = AUTHOR_ROLES | {"git-agent"}
PR_BODY = ".cache/github/pr-body.md"
BRANCH = re.compile(r"(?:(work-item|feature)/([1-9][0-9]*)-([a-z0-9][a-z0-9-]*)|chore/([a-z0-9][a-z0-9-]*))\Z")
SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
STATE_MARKERS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "BISECT_LOG", "index.lock")
# Bounded Markdown destination syntax; its content never supplies the Work Item ID.
MAP_LINK = r"\[([^\[\]]+)\](?:\((?:[^()\r\n]|\([^()\r\n]*\))*\)|\[[^\[\]\r\n]*\])?"


class Rejected(ValueError):
    pass


def executable(parts: list[str]) -> str:
    return parts[0].replace("\\", "/").rsplit("/", 1)[-1].lower().removesuffix(".exe") if parts else ""


def parse_command(command: str, *, windows: bool | None = None) -> list[str]:
    """A plain-shell subset, preserving quoted data without permitting shell execution.

    Windows uses cmd-compatible double quoting and rejects expansion/caret characters.
    POSIX single quotes can contain literal dollars; double quotes cannot expand them.
    Backslash escapes outside quotes are deliberately unsupported (use quoted paths).
    """
    windows = os.name == "nt" if windows is None else windows
    if not command or any(c in command for c in "\0\r\n"):
        raise Rejected("Use one nonempty command without control separators.")
    result: list[str] = []
    word: list[str] = []
    quote = ""
    started = False
    index = 0
    while index < len(command):
        char = command[index]
        if windows and char in "%!^`$":
            raise Rejected("Shell expansion is not supported; use literal arguments.")
        if windows and char == "\\" and index + 1 < len(command) and command[index + 1] == '"':
            # CRT treats backslash+quote differently from cmd's quote state. Reject
            # this ambiguous spelling instead of hiding a following option in data.
            raise Rejected("Backslash-escaped quotes are not supported by the Windows command subset.")
        if quote:
            if char == quote:
                quote = ""
            elif not windows and quote == '"' and char in "$`!":
                raise Rejected("Command/variable/history expansion is forbidden.")
            elif not windows and quote == '"' and char == "\\":
                if index + 1 < len(command) and command[index + 1] in '\\"':
                    index += 1
                    word.append(command[index])
                else:
                    word.append(char)
            else:
                word.append(char)
        elif char.isspace():
            if started:
                result.append("".join(word))
                word, started = [], False
        elif char == '"' or (char == "'" and not windows):
            quote, started = char, True
        elif char in ";&|<>`$(){}" or (not windows and char in "\\*?[]#!"):
            raise Rejected("Chaining, redirection, substitution, unquoted glob/comments/history and escapes are forbidden.")
        elif char == "'" and windows:
            raise Rejected("Use double quotes for literal Windows arguments.")
        else:
            started = True
            word.append(char)
        index += 1
    if quote:
        raise Rejected("Unterminated quoted argument.")
    if started:
        result.append("".join(word))
    if not result:
        raise Rejected("Empty command.")
    return result


def is_git_gh_command(command: str) -> bool:
    # Only recognize a direct executable; wrappers remain on the original safety path.
    try:
        if executable(parse_command(command)) in {"git", "gh"}:
            return True
    except Rejected:
        pass
    try:
        first = shlex.shlex(command, posix=True)
        first.whitespace_split = True
        first.commenters = ""
        if executable([next(first)]) in {"git", "gh"}:
            return True
    except (ValueError, StopIteration):
        pass
    return bool(re.match(r'^\s*(?:"[^"\r\n]*[/\\])?(?:git|gh)(?:\.exe)?(?:"|\s|$)', command, re.I)
                or re.match(r'^\s*(?:[/\w.:-]+[/\\])(?:git|gh)(?:\.exe)?(?:\s|$)', command, re.I))


def command_for_safety(command: str) -> str:
    """Remove only parsed message/title operands, never commands or option boundaries."""
    if not is_git_gh_command(command):
        return command
    parts = parse_command(command)
    exe = executable(parts)
    # Existing global destructive patterns key on the executable token. A PATH
    # spelling, .exe suffix or quoted installation path must have identical policy.
    parts[0] = exe
    message_flags: set[str] = set()
    if exe == "git" and parts[1:2] == ["commit"]:
        message_flags = {"-m", "--message"}
    elif exe == "gh":
        # gh's full argv validator owns argument meanings before this is used.
        message_flags = {"--title", "-t", "--body", "-b"}
    sanitized: list[str] = []
    index = 0
    while index < len(parts):
        token = parts[index]
        if token == "--":
            sanitized.extend(parts[index:])
            break
        if token in message_flags and index + 1 < len(parts):
            sanitized.extend((token, "LITERAL_MESSAGE"))
            index += 2
            continue
        if any(token.startswith(flag + "=") for flag in message_flags):
            sanitized.append(token.split("=", 1)[0] + "=LITERAL_MESSAGE")
        elif exe == "git" and token.startswith("-m") and len(token) > 2:
            sanitized.append("-mLITERAL_MESSAGE")
        else:
            sanitized.append(token)
        index += 1
    return shlex.join(sanitized)


class Repo:
    def __init__(self, root: Path):
        self.root = root.resolve()
        # The role hook has a 5s host budget. Finish with an explicit deny before a
        # host timeout (which can be nonblocking), even when local Git is stalled.
        self.deadline = time.monotonic() + 3.0
        for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR", "GIT_CONFIG_COUNT"):
            if os.environ.get(key):
                raise Rejected(f"{key} overrides the repository; use the ordinary workspace environment.")
        if Path(self.git("rev-parse", "--show-toplevel").strip()).resolve() != self.root:
            raise Rejected("Run Git/gh from the repository root.")

    def git(self, *args: str, ok: tuple[int, ...] = (0,)) -> str:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise Rejected("Local Git preflight exceeded its bounded hook budget; inspect and retry later.")
        try:
            completed = subprocess.run(["git", "--no-optional-locks", "-C", str(self.root), *args],
                                       capture_output=True, timeout=remaining, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Rejected("Could not inspect local Git state.") from exc
        if completed.returncode not in ok:
            raise Rejected("Could not prove local Git state: " + " ".join(args[:2]))
        return completed.stdout.decode("utf-8", errors="strict")

    def branch(self) -> str:
        branch = self.git("symbolic-ref", "--quiet", "--short", "HEAD").strip()
        if not BRANCH.fullmatch(branch):
            raise Rejected("Use a work-item/<ID>-..., feature/<ID>-... or chore/... branch, never main/master or detached HEAD.")
        return branch

    def idle(self) -> None:
        if self.git("ls-files", "--unmerged", "-z"):
            raise Rejected("Resolve the existing Git conflict before staging or committing.")
        for marker in STATE_MARKERS:
            path = Path(self.git("rev-parse", "--git-path", marker).strip())
            if (path if path.is_absolute() else self.root / path).exists():
                raise Rejected("A Git operation is in progress; inspect it before continuing.")

    def staged(self) -> set[str]:
        return set(filter(None, self.git("diff", "--cached", "--name-only", "--no-renames", "-z", "--").split("\0")))

    def dirty(self) -> set[str]:
        tracked = self.git("diff", "HEAD", "--name-only", "--no-renames", "-z", "--")
        untracked = self.git("ls-files", "--others", "--exclude-standard", "-z")
        return set(filter(None, (tracked + untracked).split("\0")))

    def oid(self, ref: str) -> str:
        return self.git("rev-parse", "--verify", ref + "^{commit}").strip()


def exact_path(root: Path, raw: str) -> str:
    if not raw or raw.startswith(("-", "/", "\\")) or any(char in raw for char in "*?[:\\\0\r\n"):
        raise Rejected("Use exact repository-relative file paths, without pathspec magic or escapes.")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise Rejected("Path traversal and directories are not staging targets.")
    candidate = root
    for part in parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise Rejected("Symlink paths are not supported by this author workflow.")
    if candidate.is_dir() or not candidate.resolve().is_relative_to(root.resolve()):
        raise Rejected("The target must be a repository-contained file.")
    return raw


def pr_body_path(root: Path, raw: str, *, must_exist: bool = False) -> bool:
    try:
        if os.name == "nt":
            raw = raw.replace("\\", "/")
        candidate = Path(raw)
        if candidate.is_absolute():
            raw = candidate.relative_to(root).as_posix()
        if exact_path(root, raw) != PR_BODY:
            return False
        path = root / raw
        if not path.exists():
            return not must_exist
        metadata = path.stat()
        # The narrow editor grant must not modify another protected path through
        # an in-place write to a hard link (or block on a FIFO/device).
        return stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1
    except (ValueError, OSError):
        return False


def commit_path(repo: Repo, raw: str, allowed: Callable[[str], bool]) -> str:
    path = exact_path(repo.root, raw)
    lowered = path.casefold()
    if lowered.startswith((".cache/", "output/", ".git/", ".sf/", ".sfdx/", ".ai/knowledge/")) or lowered == "config/harness.local.json":
        raise Rejected("Cache, local configuration, output and Knowledge are outside author auto-commits.")
    if any(part in {".env", "credentials", "secrets"} or part.startswith(".env.") for part in lowered.split("/")) or lowered.endswith((".pem", ".key", ".p12", ".pfx")):
        raise Rejected("Secret-bearing paths are not author commit targets.")
    if not allowed(path):
        raise Rejected("This role may not stage or commit " + path)
    if repo.git("check-ignore", "--no-index", "--", path, ok=(0, 1)).strip():
        raise Rejected("Ignored files cannot be staged by the author workflow.")
    return path


def context_path(repo: Repo, item: str, *, required: bool = True) -> Path | None:
    folders = list((repo.root / "work-items").glob(item + "-*"))
    if len(folders) > 1:
        raise Rejected("Multiple local folders claim Work Item " + item)
    paths = list((repo.root / "work-items").glob(item + "-*/ado-context.md"))
    if not paths and not required:
        return None
    if len(paths) != 1 or paths[0].is_symlink() or not paths[0].resolve().is_relative_to(repo.root):
        raise Rejected("Require exactly one local ADO context for Work Item " + item)
    return paths[0]


def map_label(value: str) -> str:
    """Read bounded display markup, never an identity from a link destination."""
    value = value.strip()
    for _ in range(4):
        emphasis = re.fullmatch(r"(\*\*|__|\*|_)(.+)\1", value)
        code = re.fullmatch(r"(`+)([^`]+)\1", value)
        link = re.fullmatch(MAP_LINK, value)
        if code:
            # Inline code displays its contents literally, so do not interpret
            # nested Markdown there (for example `**123**` is not numeric text).
            return code.group(2).strip()
        if emphasis:
            value = emphasis.group(2).strip()
        elif link:
            value = link.group(1).strip()
        else:
            break
    return value


def map_ids(lines: list[str]) -> list[str]:
    """Accept legacy ID columns/markup and canonical ID-first rows or lists."""
    found: list[str] = []
    column: int | None = None
    width = 0
    for line in lines:
        value = line.strip()
        if "|" in value and not re.match(r"(?:[-+*]|\d+[.)])\s", value):
            cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", value.strip("|"))]
            if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                if column is None or len(cells) != width:
                    raise Rejected("Ambiguous table structure in the Feature map.")
                continue
            headers = [index for index, cell in enumerate(cells) if map_label(cell).casefold() == "id"]
            if headers and column is None and not re.fullmatch(r"[1-9][0-9]*", map_label(cells[0])):
                if len(headers) != 1:
                    raise Rejected("Use one unambiguous ID column in each Feature membership table.")
                column, width = headers[0], len(cells)
                continue
            if column is None:
                column, width = 0, len(cells)
            if len(cells) != width:
                raise Rejected("Ambiguous table structure in the Feature map.")
            identity = map_label(cells[column])
        else:
            column, width = None, 0
            item = re.match(r"(?:[-+*]|\d+[.)])\s+(.+)", value)
            if not item:
                continue
            # A membership list starts with a whole displayed ID; following prose
            # is a title, not another place to search for an identity.
            token = re.match(r"(\*\*.+?\*\*|__.+?__|\*[^*]+\*|_[^_]+_|`+[^`]+`+|" + MAP_LINK + r"|[0-9]+)(?=\s|:|$)", item.group(1))
            if not token:
                raise Rejected("Require one exact positive numeric ID at the start of a Feature membership list item.")
            identity = map_label(token.group(1))
        if not re.fullmatch(r"[1-9][0-9]*", identity):
            raise Rejected("Require one exact positive numeric ID in each Feature membership row.")
        found.append(identity)
    return found


def feature_members(repo: Repo, feature: str) -> set[str]:
    context = context_path(repo, feature)
    maps = list((repo.root / "work-items").glob(feature + "-*/delivery-map.md"))
    if len(maps) != 1 or maps[0].parent != context.parent or maps[0].is_symlink():
        raise Rejected("Require exactly one prepared delivery map for Feature " + feature)
    text = maps[0].read_text(encoding="utf-8")
    sections: dict[str, list[str]] = {"included": [], "deferred": []}
    active = ""
    counts = {"included": 0, "deferred": 0}
    fence = ""
    for line in text.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence) and not marker.group(2).strip():
                fence = ""
            continue
        if marker:
            fence = marker.group(1)
            continue
        if line.startswith(("    ", "\t")) or line.lstrip().startswith(">"):
            continue
        if re.match(r"^ {0,3}#{1,6}\s", line):
            lowered = line.lower()
            active = "included" if re.search(r"\bincluded\b", lowered) else "deferred" if re.search(r"\bdeferred\b", lowered) else ""
            if active:
                counts[active] += 1
        elif active:
            sections[active].append(line)
    if fence or counts["included"] != 1 or counts["deferred"] > 1:
        raise Rejected("Use one clear Included delivery Work Items section in the prepared map.")
    included, deferred = map_ids(sections["included"]), map_ids(sections["deferred"])
    if len(included) != len(set(included)) or set(included) & set(deferred):
        raise Rejected("Ambiguous included/deferred membership in the Feature map.")
    return set(included)


def scope_paths(repo: Repo, branch: str, paths: set[str], item: str | None = None) -> None:
    match = BRANCH.fullmatch(branch)
    if not match:
        raise Rejected("Unrecognized delivery branch.")
    kind, branch_id = match.group(1, 2)
    if kind == "work-item":
        context = context_path(repo, branch_id, required=False)
        # Plan 02 permits technical documentation from current ADO source without
        # manufacturing ado-context.md. Empty bootstrap checks may precede writing it.
        if context is None and paths and not all(re.fullmatch(
            rf"work-items/{branch_id}-[^/]+/technical-documentation\.md", path
        ) for path in paths):
            raise Rejected("Without local intake, only the existing current-source technical-documentation lane is supported.")
        permitted = {branch_id}
    elif kind == "feature":
        members = feature_members(repo, branch_id)
        if item and item != branch_id and item not in members:
            raise Rejected("Work Item is absent or deferred in the prepared Feature map.")
        permitted = {branch_id} | ({item} if item else members)
    else:
        permitted = set()
    for path in paths:
        work = re.match(r"work-items/([1-9][0-9]*)-", path)
        if work and work.group(1) not in permitted:
            raise Rejected("A path belongs to another Work Item; split the delivery scope.")


def commit_message(repo: Repo, branch: str, messages: list[str], paths: set[str]) -> None:
    if not 1 <= len(messages) <= 4 or any(not message.strip() for message in messages):
        raise Rejected("Use one subject and at most three nonempty body paragraphs with repeated -m.")
    text = "\n\n".join(messages)
    if re.search(r"\b(?:Fixes|Fixed|Closes|Closed|Resolves)\b", text, re.I):
        raise Rejected("Commit messages cannot contain Work Item state-transition keywords.")
    branch_match = BRANCH.fullmatch(branch)
    subject = messages[0]
    ids = re.findall(r"\bAB#([1-9][0-9]*)\b", text)
    if branch.startswith("chore/"):
        if not re.match(r"\[(?:docs|chore)\] \S", subject) or ids:
            raise Rejected("Maintenance commits use [docs] or [chore], without an invented AB# ID.")
        scope_paths(repo, branch, paths)
        return
    prefix = re.match(r"\[(WI|FEATURE)-([1-9][0-9]*)\] \S", subject)
    if not prefix or set(ids) != {prefix.group(2)}:
        raise Rejected("Use [WI-ID] or [FEATURE-ID] with the matching raw AB#ID.")
    kind, item = prefix.groups()
    branch_kind, branch_id = branch_match.group(1, 2)
    if branch_kind == "work-item" and (kind != "WI" or item != branch_id):
        raise Rejected("Commit Work Item ID must match its branch.")
    if branch_kind == "feature":
        if kind == "FEATURE":
            if item != branch_id or any(not path.startswith(f"work-items/{branch_id}-") for path in paths):
                raise Rejected("Feature commits contain only their coordination/integration artifacts.")
            if any(Path(path).suffix.lower() != ".md" for path in paths):
                raise Rejected("Feature-wide commits cannot hide child source changes.")
        else:
            context_path(repo, item)
    scope_paths(repo, branch, paths, item)


def author_git_decision(parts: list[str], root: Path, role: str, allowed: Callable[[str], bool]) -> tuple[str, str] | None:
    if executable(parts) != "git" or len(parts) < 2:
        return None
    operation, args = parts[1], parts[2:]
    if operation not in {"add", "commit", "fetch", "switch", "checkout", "branch", "push"}:
        return None
    if operation == "branch" and (not args or all(arg in {"-a", "--all", "-v", "-vv", "-l", "--list", "-r", "--remotes"} for arg in args)):
        return None
    if role not in AUTHOR_ROLES:
        return ("deny", "Only active author roles can use this local Git workflow.")
    try:
        repo = Repo(root)
        repo.idle()
        if operation == "fetch":
            if args != ["origin"]:
                raise Rejected("The author bootstrap fetches exactly origin, without ref/config overrides.")
            repo.git("remote", "get-url", "origin")
            return ("allow", "")
        if operation in {"switch", "checkout", "branch"}:
            return bootstrap(repo, operation, args, allowed)
        branch = repo.branch()
        if operation == "push":
            if args and args[0] in {"-u", "--set-upstream"}:
                args = args[1:]
            if args != ["origin", branch]:
                raise Rejected("Push exactly the current delivery branch to origin; no refspec, force or deletion.")
            expected = origin_identity(repo)
            push_urls = repo.git("remote", "get-url", "--push", "--all", "origin").splitlines()
            if len(push_urls) != 1 or identity(push_urls[0]) != expected:
                raise Rejected("origin's push destination differs from its reviewed repository identity.")
            return ("ask", "Publish this branch only when the user's instruction covers push/publication. A milestone is not authorization.")
        messages: list[str] = []
        if operation == "commit":
            while args and args[0] == "-m":
                if len(args) < 2:
                    raise Rejected("Each -m requires a literal message.")
                messages.append(args[1])
                args = args[2:]
        if len(args) < 2 or args[0] != "--":
            raise Rejected("Use git add -- <exact files> or git commit -m <subject> [-m <body>] -- <exact files>.")
        paths = {commit_path(repo, path, allowed) for path in args[1:]}
        if len(paths) != len(args) - 1:
            raise Rejected("Duplicate commit paths are not supported.")
        scope_paths(repo, branch, paths)
        staged = repo.staged()
        if not staged.issubset(paths):
            raise Rejected("The index contains other paths; preserve them and resolve the commit scope first.")
        if operation == "add":
            for path in staged & paths:
                require_index_equality(repo, path)
            known = repo.dirty() | set(filter(None, repo.git("ls-files", "-z", "--", *sorted(paths)).split("\0")))
            if not paths.issubset(known):
                raise Rejected("A staging target is neither a file nor a tracked deletion.")
            return ("allow", "")
        if not staged or paths != staged:
            raise Rejected("The exact path list must equal the complete nonempty staged diff.")
        commit_message(repo, branch, messages, paths)
        for path in paths:
            require_index_equality(repo, path)
        return ("allow", "")
    except (Rejected, OSError, UnicodeError) as exc:
        return ("deny", str(exc))


def require_index_equality(repo: Repo, path: str) -> None:
    if repo.git("diff", "--name-only", "--no-ext-diff", "--no-textconv", "--no-renames", "-z", "--", path):
        raise Rejected("Selected files differ between index and working tree; do not restage automatically.")
    entries = repo.git("ls-files", "--stage", "-z", "--", path)
    flags = repo.git("ls-files", "-v", "--", path)
    if flags and (flags[0].islower() or flags[0] == "S"):
        raise Rejected("Assume-unchanged/skip-worktree files cannot prove index equality.")
    if entries and not entries.startswith(("100644 ", "100755 ")):
        raise Rejected("Only ordinary files and tracked deletions belong in this commit.")
    file = repo.root / path
    if not entries and file.exists():
        raise Rejected("A staged deletion was recreated in the working tree.")
    if entries:
        index_oid = entries.split(" ", 2)[1]
        # diff may trust the index's cached size/mtime. Hash current bytes afresh
        # with the same clean filters/CRLF normalization Git uses for this path.
        working_oid = repo.git("hash-object", "--path=" + path, "--", path).strip()
        if working_oid != index_oid:
            raise Rejected("The selected file content differs from the index; do not restage automatically.")
    # On POSIX executable mode exists even if core.filemode=false hides it from diff.
    # Windows has no equivalent executable bit; Git's index mode is authoritative there.
    if entries and os.name != "nt":
        expected_executable = entries.startswith("100755 ")
        if bool(file.stat().st_mode & 0o111) != expected_executable:
            raise Rejected("The selected file mode differs from the index.")


def bootstrap(repo: Repo, operation: str, args: list[str], allowed: Callable[[str], bool]) -> tuple[str, str]:
    if operation == "switch" and args[:2] == ["--track", "-c"]:
        if len(args) != 4 or not BRANCH.fullmatch(args[2]) or args[3] != "origin/" + args[2]:
            raise Rejected("Resume with git switch --track -c <branch> origin/<same-branch>.")
        branch, remote = args[2:]
        if repo.git("for-each-ref", "--format=%(refname)", "refs/heads/" + branch).strip():
            raise Rejected("The local branch already exists; inspect and switch to it instead.")
        # Prove the remote ref locally after the workflow's explicit fetch. Never
        # use Git's DWIM tracking or checkout.defaultRemote to choose another remote.
        target = repo.oid("refs/remotes/" + remote)
        repo.git("symbolic-ref", "--quiet", "--short", "HEAD")
        dirty = repo.dirty() | repo.staged()
        if dirty:
            if repo.oid("HEAD") != target:
                raise Rejected("Dirty remote-branch resume requires the same HEAD; preserve and inspect the changes.")
            for path in dirty:
                commit_path(repo, path, allowed)
            scope_paths(repo, branch, dirty)
        return ("allow", "")
    creating = operation == "branch" or (bool(args) and args[0] == ("-c" if operation == "switch" else "-b"))
    if operation != "branch" and creating:
        args = args[1:]
    if not creating and args == ["main"]:
        if repo.dirty() or repo.staged() or repo.oid("refs/heads/main") != repo.oid("refs/remotes/origin/main"):
            raise Rejected("Return to main only with a clean checkout and local main equal to origin/main.")
        return ("allow", "")
    if not 1 <= len(args) <= (2 if creating else 1) or not BRANCH.fullmatch(args[0]):
        raise Rejected("Use a plain delivery branch create/switch, without force or reset flags.")
    branch = args[0]
    dirty = repo.dirty() | repo.staged()
    for path in dirty:
        commit_path(repo, path, allowed)
    scope_paths(repo, branch, dirty)
    current = repo.git("symbolic-ref", "--quiet", "--short", "HEAD").strip()
    if not creating:
        target = repo.oid("refs/heads/" + branch)
        if dirty and target != repo.oid("HEAD"):
            raise Rejected("Dirty changes cannot be switched onto a different commit; preserve and inspect them.")
        return ("allow", "")
    existing = repo.git("for-each-ref", "--format=%(refname)", "refs/heads/" + branch, "refs/remotes/origin/" + branch)
    if existing.strip():
        raise Rejected("The branch exists locally or remotely; resume only after inspection.")
    base = args[1] if len(args) == 2 else "origin/main"
    if base != "origin/main":
        match = re.fullmatch(r"origin/feature/([1-9][0-9]*)-[a-z0-9][a-z0-9-]*", base)
        child = BRANCH.fullmatch(branch)
        if not match or child.group(1) != "work-item" or child.group(2) not in feature_members(repo, match.group(1)):
            raise Rejected("A parallel child requires its exact confirmed remote Feature base and included membership.")
    base_oid = repo.oid("refs/remotes/" + base)
    if base == "origin/main":
        if current != "main" or repo.oid("HEAD") != base_oid:
            raise Rejected("Bootstrap requires local main equal to confirmed origin/main; do not reset or pull.")
    elif dirty and repo.oid("HEAD") != base_oid:
        raise Rejected("Dirty changes require the same HEAD as the confirmed remote Feature base.")
    if len(args) == 1 and repo.oid("HEAD") != base_oid:
        raise Rejected("An implicit base must equal HEAD.")
    return ("allow", "")


def identity(value: str) -> tuple[str, str, str]:
    value = value.strip().removesuffix(".git")
    if value.startswith("git@"):
        match = re.fullmatch(r"git@([^:/]+):([^/]+)/([^/]+)", value)
        if not match:
            raise Rejected("Unrecognized GitHub repository identity.")
        host, owner, name = match.groups()
    elif "://" in value:
        parsed = urlparse(value)
        if parsed.scheme not in {"https", "ssh"} or parsed.password or (parsed.username and parsed.username != "git") or parsed.query or parsed.fragment or parsed.port:
            raise Rejected("Use an unambiguous HTTPS/SSH GitHub repository identity without credentials.")
        host = parsed.hostname or ""
        pieces = parsed.path.strip("/").split("/")
        if len(pieces) != 2:
            raise Rejected("Unrecognized repository path.")
        owner, name = pieces
    else:
        pieces = value.split("/")
        if len(pieces) == 2:
            host, owner, name = "github.com", *pieces
        elif len(pieces) == 3:
            host, owner, name = pieces
        else:
            raise Rejected("Use [host/]owner/repo.")
    if not re.fullmatch(r"[a-zA-Z0-9.-]+", host) or not all(re.fullmatch(r"[a-zA-Z0-9_.-]+", part) and part not in {".", ".."} for part in (owner, name)):
        raise Rejected("Invalid repository identity.")
    return host.casefold(), owner.casefold(), name.casefold()


def origin_identity(repo: Repo) -> tuple[str, str, str]:
    urls = repo.git("remote", "get-url", "--all", "origin").splitlines()
    if len(urls) != 1:
        raise Rejected("Require one unambiguous origin repository.")
    return identity(urls[0])


def options(args: list[str], values: dict[str, str], booleans: dict[str, str]) -> tuple[dict[str, str | bool], list[str]]:
    parsed: dict[str, str | bool] = {}
    positionals: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        key, equals, value = token.partition("=")
        if key in values:
            name = values[key]
            if not equals:
                index += 1
                if index >= len(args):
                    raise Rejected("Missing option value for " + key)
                value = args[index]
            if not value or name in parsed:
                raise Rejected("Empty or duplicate option: " + key)
            parsed[name] = value
        elif key in booleans and not equals:
            name = booleans[key]
            if name in parsed:
                raise Rejected("Duplicate option: " + key)
            parsed[name] = True
        elif token.startswith("-"):
            raise Rejected("Unsupported option: " + token)
        else:
            positionals.append(token)
        index += 1
    return parsed, positionals


def gh_decision(parts: list[str], root: Path, role: str | None) -> tuple[str, str]:
    try:
        if executable(parts) != "gh":
            raise Rejected("Expected a direct gh command.")
        args = parts[1:]
        if args == ["--version"]:
            return ("allow", "")
        prefix: list[str] = []
        while args and (args[0] in {"-R", "--repo"} or args[0].startswith("--repo=")):
            token = args.pop(0)
            prefix.append(token)
            if "=" not in token:
                if not args:
                    raise Rejected("Missing repo selector.")
                prefix.append(args.pop(0))
        if len(args) < 2:
            raise Rejected("Select a supported gh repo/PR operation.")
        family, operation, *rest = args
        rest = prefix + rest
        if (family, operation) == ("auth", "status"):
            opts, positional = options(rest, {"--hostname": "host", "-h": "host"}, {"--active": "active"})
            if positional:
                raise Rejected("auth status accepts no token or account mutation options.")
            return ("allow", "")
        values = {"--repo": "repo", "-R": "repo"}
        booleans: dict[str, str] = {}
        if family == "repo" and operation == "view":
            values.update({"--json": "json", "--jq": "jq", "-q": "jq", "--template": "template", "-t": "template"})
        elif family == "pr" and operation in {"list", "view", "diff", "checks"}:
            if operation in {"list", "view", "checks"}:
                values.update({"--json": "json", "--jq": "jq", "-q": "jq", "--template": "template", "-t": "template"})
            if operation == "list":
                values.update({"--limit": "limit", "-L": "limit", "--state": "state", "-s": "state", "--head": "head", "-H": "head", "--base": "base", "-B": "base", "--author": "author", "-A": "author", "--assignee": "assignee", "-a": "assignee", "--label": "label", "-l": "label", "--search": "search", "-S": "search"})
                booleans.update({"--draft": "draft", "-d": "draft"})
            if operation == "view":
                booleans.update({"--comments": "comments", "-c": "comments"})
            if operation == "diff":
                values["--color"] = "color"
                booleans.update({"--patch": "patch", "--name-only": "name-only"})
            if operation == "checks":
                booleans.update({"--required": "required", "--watch": "watch", "--fail-fast": "fail-fast"})
                values.update({"--interval": "interval", "-i": "interval"})
        elif family == "pr" and operation in {"create", "edit", "ready", "merge"}:
            if operation in {"create", "edit"}:
                values.update({"--title": "title", "-t": "title", "--body-file": "body-file", "-F": "body-file"})
            if operation == "create":
                values.update({"--head": "head", "-H": "head", "--base": "base", "-B": "base"})
                booleans.update({"--draft": "draft", "-d": "draft"})
            if operation == "ready":
                booleans["--undo"] = "undo"
            if operation == "merge":
                values["--match-head-commit"] = "match-head-commit"
                booleans.update({"--merge": "merge", "-m": "merge", "--squash": "squash", "-s": "squash", "--rebase": "rebase", "-r": "rebase", "--auto": "auto"})
        else:
            raise Rejected("This gh operation is outside the repo/PR workflow.")
        opts, positional = options(rest, values, booleans)
        repo = Repo(root)
        expected = origin_identity(repo)
        if os.environ.get("GH_HOST") and os.environ["GH_HOST"].casefold() != expected[0]:
            raise Rejected("GH_HOST conflicts with the workspace's origin host.")
        if os.environ.get("GH_REPO") and identity(os.environ["GH_REPO"]) != expected:
            raise Rejected("GH_REPO conflicts with the workspace's origin repository.")
        selected = identity(str(opts["repo"])) if "repo" in opts else expected
        if selected != expected:
            raise Rejected("The selected repository differs from this workspace's origin.")
        writing = family == "pr" and operation in {"create", "edit", "ready", "merge"}
        if writing and role is not None and role not in PUBLISH_ROLES:
            raise Rejected("This role has read-only GitHub access.")
        if writing and "repo" not in opts:
            raise Rejected("Remote writes require an explicit --repo matching origin.")
        if family == "repo":
            if len(positional) > 1 or (positional and identity(positional[0]) != expected):
                raise Rejected("repo view must refer to the workspace origin.")
        elif operation in {"create", "list"}:
            if positional:
                raise Rejected("This command accepts no implicit PR/repository selector.")
        else:
            if len(positional) > 1 or (writing and len(positional) != 1):
                raise Rejected("Specify exactly one concrete PR number or URL for a write.")
            if positional:
                selector = positional[0]
                if selector.startswith("https://"):
                    url = urlparse(selector)
                    match = re.fullmatch(r"/([^/]+)/([^/]+)/pull/([1-9][0-9]*)/?", url.path)
                    if not match or url.query or url.fragment or url.username or url.port or (url.hostname or "").casefold() != expected[0] or (match.group(1).casefold(), match.group(2).casefold()) != expected[1:]:
                        raise Rejected("The PR URL must identify a concrete PR in origin.")
                elif not re.fullmatch(r"[1-9][0-9]*", selector):
                    raise Rejected("Use a concrete PR number or same-origin URL.")
        if "limit" in opts and (not str(opts["limit"]).isdigit() or not 1 <= int(str(opts["limit"])) <= 100):
            raise Rejected("PR list limit must be between 1 and 100.")
        if "interval" in opts and (not str(opts["interval"]).isdigit() or not 1 <= int(str(opts["interval"])) <= 3600):
            raise Rejected("Check polling interval must be between 1 and 3600 seconds.")
        if "body-file" in opts and not pr_body_path(repo.root, str(opts["body-file"]), must_exist=True):
            raise Rejected("Use the existing nonsymlink .cache/github/pr-body.md transport file.")
        if operation == "create":
            if not {"head", "base", "title", "body-file"}.issubset(opts):
                raise Rejected("PR creation requires explicit head, base, title and body-file.")
            if str(opts["head"]) != repo.branch():
                raise Rejected("The PR head must be the current delivery branch.")
            base = str(opts["base"])
            if base != "main" and not re.fullmatch(r"feature/[1-9][0-9]*-[a-z0-9][a-z0-9-]*", base):
                raise Rejected("Use main or the prepared parent Feature branch as base.")
            if repo.branch().startswith("feature/") and base != "main":
                raise Rejected("The final Feature PR targets main.")
            if base != "main":
                head = BRANCH.fullmatch(repo.branch())
                if head.group(1) != "work-item" or head.group(2) not in feature_members(repo, base.split("/", 1)[1].split("-", 1)[0]):
                    raise Rejected("A child PR must be included in its target Feature.")
        if operation == "edit" and not ({"title", "body-file"} & opts.keys()):
            raise Rejected("pr edit changes only the requested title and/or body file.")
        if operation == "merge":
            if not SHA.fullmatch(str(opts.get("match-head-commit", ""))):
                raise Rejected("Merge requires --match-head-commit with the expected full head SHA.")
            methods = {"merge", "squash", "rebase"} & opts.keys()
            if len(methods) != 1:
                raise Rejected("Select exactly one repository-approved merge method.")
            if repo.branch().startswith("feature/") and methods != {"merge"}:
                raise Rejected("Feature delivery preserves its logical Work Item commits with --merge.")
        if writing:
            return ("ask", "Run this PR operation only within the user's explicit instruction; publication does not authorize merge. Check the exact PR/head/base and current remote state first.")
        return ("allow", "")
    except (Rejected, OSError, UnicodeError, ValueError) as exc:
        return ("deny", str(exc))
