"""Import the real native runtime independently of checkout Python modules."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extensions" / "salesforce-operations"


class TestNativeRuntimePackage(unittest.TestCase):
    def setUp(self) -> None:
        self.node = shutil.which("node")
        if self.node is None:
            self.skipTest("Node is required to build the native runtime.")
        temporary = tempfile.TemporaryDirectory(prefix="sf-packaged-runtime-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.runtime = self.root / "runtime"
        # An unrelated cwd and clean environment must not rescue missing package files.
        self.environment = {
            key: value for key, value in os.environ.items()
            if key.upper() not in {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "NODE_OPTIONS", "NODE_PATH"}
        }
        result = self.run_node(
            "const {buildRuntime} = await import(process.argv[1]); "
            "await buildRuntime(process.argv[2], process.argv[3]);",
            (EXTENSION / "build.mjs").as_uri(), str(ROOT), str(self.runtime),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def run_node(self, program: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.node, "--input-type=module", "-e", program, *arguments],
            cwd=self.root, env=self.environment, text=True, capture_output=True,
            timeout=30, check=False,
        )

    def verify_runtime(self) -> subprocess.CompletedProcess[str]:
        return self.run_node(
            "const {verifyRuntime} = await import(process.argv[1]); "
            "await verifyRuntime(process.argv[2]);",
            (EXTENSION / "src" / "host.mjs").as_uri(), str(self.runtime),
        )

    def test_packaged_session_imports_without_checkout_python_modules(self) -> None:
        verified = self.verify_runtime()
        self.assertEqual(verified.returncode, 0, verified.stderr)
        sentinel = "PACKAGED_SESSION_IMPORT_READY"
        program = "\n".join([
            "import sys",
            "from pathlib import Path",
            "runtime = Path(sys.argv[1]).resolve()",
            "sys.path.insert(0, str(runtime))",
            "import salesforce_operation_session as session",
            "import copilot_safety_hook as safety",
            "import ado_config",
            "import ado_tool_policy",
            "import git_workflow_policy as git_policy",
            "for module in (session, session.policy, safety, ado_config, ado_tool_policy, git_policy):",
            "    assert Path(module.__file__).resolve().parent == runtime, module.__file__",
            "assert safety.git_policy is git_policy",
            "assert safety.ado_config_error is ado_config.ado_config_error",
            f"print({sentinel!r})",
        ])
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", program, str(self.runtime)],
            cwd=self.root, env=self.environment, text=True, capture_output=True,
            timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        # A guard import failure deliberately exits with status 0 after emitting deny.
        # Only reaching the sentinel proves the native session actually loaded.
        self.assertEqual(result.stdout.strip(), sentinel, result.stdout + result.stderr)

    def test_host_rejects_manifest_that_omits_git_policy_dependency(self) -> None:
        manifest_path = self.runtime / "source-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertIn("git_workflow_policy.py", {item["path"] for item in manifest["files"]})
        manifest["files"] = [
            item for item in manifest["files"] if item["path"] != "git_workflow_policy.py"
        ]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = self.verify_runtime()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Packaged runtime is incomplete", result.stderr)

    def test_host_rejects_manifest_that_omits_ado_scope_dependency(self) -> None:
        manifest_path = self.runtime / "source-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertIn("ado_config.py", {item["path"] for item in manifest["files"]})
        manifest["files"] = [item for item in manifest["files"] if item["path"] != "ado_config.py"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = self.verify_runtime()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Packaged runtime is incomplete", result.stderr)

    def test_host_rejects_manifest_that_omits_ado_tool_policy(self) -> None:
        # The native session imports the global hook. An unbundled policy would
        # fail closed even for unrelated Salesforce operations on the host.
        manifest_path = self.runtime / "source-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertIn("ado_tool_policy.py", {item["path"] for item in manifest["files"]})
        manifest["files"] = [item for item in manifest["files"] if item["path"] != "ado_tool_policy.py"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = self.verify_runtime()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Packaged runtime is incomplete", result.stderr)


if __name__ == "__main__":
    unittest.main()
