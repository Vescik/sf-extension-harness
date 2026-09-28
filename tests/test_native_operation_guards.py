"""Native tool admission is independent from per-invocation Salesforce authorization."""
from __future__ import annotations

import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts import copilot_role_guard as role_guard
from scripts import copilot_safety_hook as safety


ROOT = Path(__file__).resolve().parents[1]
NAMES = (
    "sf_harness_run_operation",
    "sf-harness.salesforce-operations/salesforceOperation",
    "salesforceOperation",
)
ARGUMENTS = ["data", "query", "--target-org", "unconfigured", "--query", "SELECT Id FROM Account"]


def invoke(module, event, role=None):
    output = StringIO()
    argv = ["hook", "--role", role] if role else ["hook"]
    with patch("sys.stdin", StringIO(json.dumps(event))), patch("sys.argv", argv), \
            patch.object(module, "_log_decision"), redirect_stdout(output):
        module.main()
    result = json.loads(output.getvalue())
    return "continue" if result.get("continue") else result["hookSpecificOutput"]["permissionDecision"]


def event(name=NAMES[0], tool_input=None):
    return {"cwd": str(ROOT), "tool_name": name,
            "tool_input": {"arguments": ARGUMENTS} if tool_input is None else tool_input}


class NativeOperationGuardTests(unittest.TestCase):
    def test_developer_admission_defers_environment_question_to_native_session(self):
        for name in NAMES:
            with self.subTest(name=name), patch.object(safety.sf_policy, "evaluate") as evaluate:
                self.assertEqual("continue", invoke(safety, event(name)))
                self.assertEqual("continue", invoke(role_guard, event(name), "developer"))
                evaluate.assert_not_called()

    def test_other_roles_cannot_invoke_native_tool(self):
        for name in NAMES:
            for role in role_guard.ALLOWED_PREFIXES:
                if role != "developer":
                    with self.subTest(name=name, role=role):
                        self.assertEqual("deny", invoke(role_guard, event(name), role))

    def test_model_cannot_supply_authority_or_context_fields(self):
        for key, value in (("role", "developer"), ("environment", "dev"), ("approved", True),
                           ("workspace", str(ROOT)), ("promptId", "old"), ("token", "replay")):
            payload = {"arguments": ARGUMENTS, key: value}
            with self.subTest(key=key):
                self.assertEqual("deny", invoke(safety, event(tool_input=payload)))
                self.assertEqual("deny", invoke(role_guard, event(tool_input=payload), "developer"))

    def test_malformed_and_unbounded_arguments_are_denied_by_both_hooks(self):
        payloads = [[], "data query", {}, {"arguments": []}, {"arguments": "data query"},
                    {"arguments": [None]}, {"arguments": [True]}, {"arguments": [""]},
                    {"arguments": ["a\nb"]}, {"arguments": ["a\rb"]}, {"arguments": ["a\0b"]},
                    {"arguments": ["a"] * 129}, {"arguments": ["a" * 8193]},
                    {"arguments": ["é" * 8192] * 3}, {"arguments": ["\ud800"]}]
        for payload in payloads:
            with self.subTest(payload=repr(payload)[:80]):
                self.assertEqual("deny", invoke(safety, event(tool_input=payload)))
                self.assertEqual("deny", invoke(role_guard, event(tool_input=payload), "developer"))

    def test_similar_tool_names_are_not_native_capabilities(self):
        for name in ("other/sf_harness_run_operation", "mcp/salesforceOperation",
                     "sf_harness_run_operation_extra", "SF_HARNESS_RUN_OPERATION",
                     "sf-harness.other/salesforceOperation"):
            with self.subTest(name=name):
                self.assertNotIn(name, safety.NATIVE_OPERATION_TOOLS)
                self.assertNotIn(name, role_guard.NATIVE_OPERATION_TOOLS)
                if "/" in name:
                    self.assertNotEqual("continue", invoke(safety, event(name)))

    def test_private_helpers_are_not_terminal_capabilities(self):
        commands = (
            "python scripts/salesforce_operation_session.py --workspace .",
            "python -m scripts.salesforce_operation_session --workspace .",
            "python scripts/salesforce_job_selection.py",
            "node scripts/salesforce_job_executor.mjs",
            'python -c "from scripts import salesforce_operation_session"',
            'node --input-type=module -e "import(\'./scripts/salesforce_job_executor.mjs\')"',
            r"python scripts\salesforce_operation_session.py --workspace .",
        )
        for command in commands:
            with self.subTest(command=command):
                terminal = event("execute/runInTerminal", {"command": command})
                self.assertEqual("deny", invoke(safety, terminal))
                for role in role_guard.ALLOWED_PREFIXES:
                    self.assertEqual("deny", invoke(role_guard, terminal, role))

    def test_read_and_parse_checks_do_not_execute_private_helpers(self):
        for command in ("cat scripts/salesforce_operation_session.py",
                        "python -m py_compile scripts/salesforce_operation_session.py",
                        "node --check scripts/salesforce_job_executor.mjs"):
            with self.subTest(command=command):
                self.assertFalse(safety.private_native_invocation(command))

    def test_runtime_and_package_are_root_of_trust(self):
        for path in ("scripts/salesforce_operation_policy.py", "scripts/salesforce_operation_session.py",
                     "scripts/salesforce_job_selection.py", "scripts/salesforce_job_executor.mjs",
                     "extensions/salesforce-operations/package.json",
                     "extensions/salesforce-operations/src/extension.mjs"):
            with self.subTest(path=path):
                self.assertEqual("ask", role_guard.maintainer_edit_decision(path))
                self.assertFalse(role_guard.development_edit_allowed(path, ROOT, "developer"))


if __name__ == "__main__":
    unittest.main()
