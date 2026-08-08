from __future__ import annotations

import json
import unittest
from io import StringIO
from unittest.mock import patch

from scripts import copilot_safety_hook as safety


def decision(output: dict[str, object]) -> tuple[str, str]:
    hook = output.get("hookSpecificOutput")
    if isinstance(hook, dict):
        return str(hook.get("permissionDecision")), str(
            hook.get("permissionDecisionReason", "")
        )
    return "continue", ""


class TerminalGateCoverageTests(unittest.TestCase):
    """Command-scoped gates must be reachable through EVERY terminal tool name form.

    The work-record approval gate this module originally pinned was deleted with its lane
    (phase 5, owner decision 2026-08-08); the tool-name coverage lesson it encoded (FIND-04:
    Copilot CLI capitalises its shell tool, so substring tokens missed it and every
    command-scoped gate was unreachable while the hook looked healthy) is preserved here
    against the destructive-command gate, which stays.
    """

    def run_hook(self, tool_name: str, command: str) -> tuple[str, str]:
        event = {"tool_name": tool_name, "tool_input": {"command": command}}
        stdout = StringIO()
        with (
            patch("sys.stdin", StringIO(json.dumps(event))),
            patch("sys.stdout", stdout),
        ):
            self.assertEqual(safety.main(), 0)
        return decision(json.loads(stdout.getvalue()))

    def test_every_terminal_tool_form_denies_destructive_commands(self) -> None:
        for tool_name in (
            "execute/runInTerminal",
            "run_in_terminal",
            "shell/execute",
            "executeCommand",
            "runTask",
            # Copilot CLI names its shell tool after the binary and sends it capitalised.
            # None of the substring tokens matches it unless folded, so every command-scoped
            # gate was unreachable in the CLI while the hook itself looked healthy (FIND-04).
            "Bash",
            "bash",
            "sh",
        ):
            with self.subTest(tool_name=tool_name):
                actual, reason = self.run_hook(tool_name, "git push origin main --force")
                self.assertEqual(actual, "deny")
                self.assertIn("Destructive operation", reason)

    def test_shell_binary_names_are_matched_exactly_not_by_substring(self) -> None:
        """The short shell names must never become substring tokens.

        "sh" as a substring matches publish, push and refresh, and would push non-command
        tool inputs through the command rules. The long host tokens (terminal, execute, …)
        stay substring-matched; these do not.
        """
        for tool_name in (
            "publish",
            "push_changes",
            "refresh_token",
            "run_soql_query",
            "run_tests",
            "apply_patch",
            "view",
            "ado-readonly-wit_get_work_item",
        ):
            with self.subTest(tool_name=tool_name):
                self.assertFalse(safety.is_terminal_tool(tool_name))

if __name__ == "__main__":
    unittest.main()
