"""Git admission validates commit text only; it never probes repository state.

All Git and gh operations are available to every agent. Shell command separation
keeps unrelated commands on their normal policy path. Final messages from an editor,
stdin, a reused commit or expansion are validated by the optional commit-msg hook.
"""
from __future__ import annotations

import argparse
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

# These constants describe the separate PR-body editor grant, not Git permissions.
AUTHOR_ROLES = frozenset({"designer", "developer", "test-strategist", "workspace-maintainer"})
PUBLISH_ROLES = AUTHOR_ROLES | {"git-agent"}
PR_BODY = ".cache/github/pr-body.md"
SOLUTION_DOCUMENTATION_PATTERN = re.compile(
    r"docs/solutions/[a-z0-9]+(?:-[a-z0-9]+)*/(?:overview|flows|components)\.md"
)


class Rejected(ValueError):
    pass


@dataclass(frozen=True)
class GitAdmission:
    has_git: bool = False
    decision: str = "allow"
    reason: str = ""
    remaining_commands: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Word:
    text: str
    dynamic: bool = False


@dataclass(frozen=True)
class _Command:
    raw: str
    words: tuple[_Word, ...]


def executable(parts: list[str]) -> str:
    return parts[0].replace("\\", "/").rsplit("/", 1)[-1].lower().removesuffix(".exe") if parts else ""


def _scan(command: str, windows: bool) -> tuple[list[_Command], list[str]]:
    """Read shell words and executable segments without evaluating any shell text."""
    commands: list[_Command] = []
    substitutions: list[str] = []
    words: list[_Word] = []
    word: list[str] = []
    quote = ""
    started = dynamic = False
    segment = index = 0

    def finish_word() -> None:
        nonlocal word, started, dynamic
        if started:
            words.append(_Word("".join(word), dynamic))
        word, started, dynamic = [], False, False

    def finish_command(end: int) -> None:
        nonlocal words
        finish_word()
        if words:
            commands.append(_Command(command[segment:end].strip(), tuple(words)))
        words = []

    while index < len(command):
        char = command[index]
        if char == "\\" and not windows and quote != "'" and index + 1 < len(command):
            following = command[index + 1]
            if following in "\\\"' $`;&|<>\n":
                if following != "\n":
                    word.append(following)
                    started = True
                index += 2
                continue
        if char in "\"'" and (not quote or quote == char):
            quote = "" if quote else char
            started = True
            index += 1
            continue
        if quote != "'" and command.startswith("$(", index):
            begin = index + 2
            depth, nested_quote = 1, ""
            index = begin
            while index < len(command) and depth:
                nested = command[index]
                if nested == "\\" and index + 1 < len(command):
                    index += 2
                    continue
                if nested in "\"'" and (not nested_quote or nested_quote == nested):
                    nested_quote = "" if nested_quote else nested
                elif not nested_quote:
                    depth += (nested == "(") - (nested == ")")
                index += 1
            if depth:
                raise Rejected("Unterminated shell command substitution.")
            inner = command[begin:index - 1]
            if inner.startswith("(") and inner.endswith(")"):
                # Arithmetic expansion is data, while substitutions embedded in
                # that expression still execute commands and must stay visible.
                _, arithmetic_substitutions = _scan(inner[1:-1], windows)
                substitutions.extend(arithmetic_substitutions)
            else:
                substitutions.append(inner)
            word.append(command[begin - 2:index])
            started = dynamic = True
            continue
        if quote != "'" and char == "`" and not windows:
            end = index + 1
            while end < len(command):
                if command[end] == "\\":
                    end += 2
                elif command[end] == "`":
                    break
                else:
                    end += 1
            if end == len(command):
                raise Rejected("Unterminated shell command substitution.")
            substitutions.append(command[index + 1:end])
            word.append(command[index:end + 1])
            started = dynamic = True
            index = end + 1
            continue
        if quote != "'" and (char == "$" or (windows and char in "%!")):
            dynamic = True
        if not quote and char == "#" and not started:
            finish_command(index)
            newline = command.find("\n", index)
            if newline < 0:
                return commands, substitutions
            index = newline + 1
            segment = index
            continue
        if not quote and (char in ";&|\n\r()" or (char in "{}" and not started)):
            # Descriptor duplication (2>&1) is a redirect, not a new command.
            if char == "&" and ((index and command[index - 1] in "<>") or command[index:index + 2] == "&>"):
                word.append(char)
                started = True
            else:
                finish_command(index)
                segment = index + 1
        elif not quote and char.isspace():
            finish_word()
        else:
            word.append(char)
            started = True
        index += 1
    if quote:
        raise Rejected("Unterminated shell quoted argument.")
    finish_command(len(command))
    return commands, substitutions


def parse_command(command: str, *, windows: bool | None = None) -> list[str]:
    commands, _ = _scan(command, os.name == "nt" if windows is None else windows)
    if len(commands) != 1:
        raise Rejected("Expected one command.")
    return [word.text for word in commands[0].words]


def _directory(cwd: Path | None, word: _Word) -> Path | None:
    if word.dynamic or word.text in {"-", "~"} or word.text.startswith("~/"):
        return None
    path = Path(word.text)
    return path if path.is_absolute() else cwd / path if cwd is not None else None


def _unwrap(words: tuple[_Word, ...], cwd: Path | None) -> tuple[tuple[_Word, ...], Path | None]:
    index = 0
    while index < len(words):
        token = words[index].text
        if token in {"if", "then", "elif", "else", "while", "until", "do", "!"}:
            index += 1
        elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", token):
            index += 1
        elif token in {"command", "exec", "env"}:
            wrapper = token
            index += 1
            while index < len(words) and words[index].text.startswith("-"):
                option = words[index].text
                index += 1
                if option == "--":
                    break
                value_options = {"exec": {"-a"}, "env": {"-u", "--unset", "-C", "--chdir", "-a", "--argv0"}, "command": set()}[wrapper]
                flag_options = {"exec": {"-c", "-l"}, "env": {"-i", "--ignore-environment", "-0", "--null", "-v", "--debug"}, "command": {"-p", "-v", "-V"}}[wrapper]
                if option in value_options and index < len(words):
                    if option in {"-C", "--chdir"}:
                        cwd = _directory(cwd, words[index])
                    index += 1
                elif wrapper == "env" and option.startswith("--chdir="):
                    cwd = _directory(cwd, _Word(option.split("=", 1)[1], words[index - 1].dynamic))
                elif wrapper == "env" and option.startswith(("--unset=", "--argv0=")):
                    pass
                elif option not in flag_options:
                    # An unknown wrapper option may consume the apparent `git`
                    # token as data (for example exec -a git rm). Keep the wrapper
                    # on normal policy unless its executable position is known.
                    return words, cwd
        else:
            break
    return words[index:], cwd


def message_error(message: str) -> str | None:
    """Validate the first-line subject exactly; body text is unconstrained."""
    lines = message.splitlines()
    subject = lines[0] if lines else ""
    if re.fullmatch(r"\[(?:chore|docs)\] \S.*", subject):
        return None
    match = re.fullmatch(r"\[(WI|FEATURE)-([1-9][0-9]*)\] \S.*", subject)
    if match:
        references = set(re.findall(r"\bAB#([0-9]+)\b", subject))
        if references == {match.group(2)}:
            return None
        return "Commit subject must contain AB#" + match.group(2) + " and no conflicting AB# ID."
    return "Commit subject must use [chore], [docs], [WI-ID] or [FEATURE-ID] followed by a description; WI/FEATURE subjects also need the matching AB#ID."


def _read_message(path: Path) -> str | None:
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError):
        # Missing/dynamic inputs are handled by Git and its final commit-msg hook.
        return None


def _commit_error(words: tuple[_Word, ...], cwd: Path | None) -> str | None:
    index = 1
    while index < len(words) and words[index].text.startswith("-"):
        token = words[index].text
        if token in {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--exec-path"}:
            if index + 1 >= len(words):
                return None
            if token == "-C":
                cwd = _directory(cwd, words[index + 1])
            index += 2
        else:
            if token.startswith("-C") and len(token) > 2:
                cwd = _directory(cwd, _Word(token[2:], words[index].dynamic))
            index += 1
    if index == len(words) or words[index].text != "commit":
        return None
    args = words[index + 1:]
    messages: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        token = arg.text
        if token == "--":
            break
        # Git constructs/reuses these messages; validate their final text natively.
        if token in {"-c", "-C", "--reedit-message", "--reuse-message", "--fixup", "--squash", "--edit", "-e"} or token.startswith(("--fixup=", "--squash=", "--reuse-message=", "--reedit-message=")):
            return None
        kind = value = None
        dynamic = arg.dynamic
        if token in {"-m", "--message", "-F", "--file"}:
            if index + 1 == len(args):
                return None
            kind = "message" if token in {"-m", "--message"} else "file"
            index += 1
            value, dynamic = args[index].text, args[index].dynamic
        elif token.startswith(("--message=", "--file=")):
            kind = "message" if token.startswith("--message=") else "file"
            value = token.split("=", 1)[1]
        elif token.startswith("-") and not token.startswith("--"):
            # Combined common flags (-am, -aqm, -mTEXT, -Ffile) retain Git syntax.
            short = re.fullmatch(r"-[aqvsn]*(m|F)(.*)", token)
            if short:
                kind = "message" if short.group(1) == "m" else "file"
                value = short.group(2)
                if not value:
                    if index + 1 == len(args):
                        return None
                    index += 1
                    value, dynamic = args[index].text, args[index].dynamic
        if kind:
            if dynamic:
                return None
            if kind == "file":
                if value == "-":
                    return None
                path = _directory(cwd, _Word(value))
                value = _read_message(path) if path is not None else None
                if value is None:
                    return None
            messages.append(value)
        index += 1
    return message_error("\n\n".join(messages)) if messages else None


def inspect_command(command: str, cwd: Path | None, *, windows: bool | None = None) -> GitAdmission:
    """Admit Git segments and return other shell commands for their existing policy."""
    windows = os.name == "nt" if windows is None else windows
    try:
        commands, substitutions = _scan(command, windows)
    except Rejected:
        return GitAdmission(remaining_commands=(command,))
    has_git = False
    error = None
    remaining: list[str] = []
    navigation: list[str] = []
    current = Path(cwd) if cwd is not None else None
    for item in commands:
        words, command_cwd = _unwrap(item.words, current)
        if not words:
            continue
        exe = executable([words[0].text])
        if exe in {"fi", "done"} and len(words) == 1:
            continue
        if exe in {"cd", "pushd", "set-location"}:
            navigation.append(item.raw)
            targets = [word for word in words[1:] if word.text.lower() not in {"/d", "--", "-literalpath", "-path"}]
            current = _directory(command_cwd, targets[0]) if len(targets) == 1 else None
            continue
        if exe in {"git", "gh"} and not words[0].dynamic:
            has_git = True
            if exe == "git":
                error = error or _commit_error(words, command_cwd)
        else:
            shell_options = {"sh": "-c", "bash": "-c", "zsh": "-c", "dash": "-c",
                             "cmd": "/c", "powershell": "-command", "pwsh": "-command"}
            shell_option = shell_options.get(exe)
            body = next((words[index + 1] for index in range(1, len(words) - 1)
                         if words[index].text.lower() == shell_option), None) if shell_option else None
            if body is not None and not body.dynamic:
                nested = inspect_command(body.text, command_cwd, windows=windows or exe in {"cmd", "powershell", "pwsh"})
                has_git = has_git or nested.has_git
                error = error or (nested.reason if nested.decision == "deny" else None)
                remaining.extend(" && ".join([*navigation, residual]) for residual in nested.remaining_commands)
            else:
                remaining.append(" && ".join([*navigation, item.raw]))
    for substitution in substitutions:
        nested = inspect_command(substitution, current, windows=windows)
        has_git = has_git or nested.has_git
        error = error or (nested.reason if nested.decision == "deny" else None)
        remaining.extend(" && ".join([*navigation, residual]) for residual in nested.remaining_commands)
    if not has_git:
        remaining = [command] if command.strip() else []
    return GitAdmission(has_git, "deny" if error else "allow", error or "", tuple(remaining))


def is_git_gh_command(command: str) -> bool:
    return inspect_command(command, Path.cwd()).has_git


def exact_path(root: Path, raw: str) -> str:
    """Exact-file check for editor grants; never a Git path restriction."""
    if not raw or raw.startswith(("-", "/", "\\")) or any(char in raw for char in "*?[:\\\0\r\n"):
        raise Rejected("Use an exact repository-relative editor file path.")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise Rejected("Editor paths cannot contain traversal.")
    candidate = root
    for part in parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise Rejected("Editor grants do not follow symlinks.")
    if candidate.is_dir() or not candidate.resolve().is_relative_to(root.resolve()):
        raise Rejected("The editor target must be a repository-contained file.")
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
        return stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1
    except (ValueError, OSError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the final Git commit message format.")
    parser.add_argument("--message-file", type=Path, required=True)
    args = parser.parse_args()
    message = _read_message(args.message_file)
    error = message_error(message) if message is not None else "Could not read the final commit message as UTF-8 text."
    if error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
