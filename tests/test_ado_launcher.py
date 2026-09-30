"""Process-boundary proof for ADO startup, scope isolation, and shutdown.

The real launcher runs against an installed-package stub in temporary workspaces.
No Azure connection or credentials are used. Hook tests separately prove operation
scope; these tests prove the transport cannot start or continue with invalid config.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
VALID_CONFIG = {
    "ado": {
        "organization": "workspace-org",
        "project": "Project with spaces",
        "allowedHttpsOrigins": ["https://dev.azure.com/workspace-org", "https://docs.example.test/reference"],
    },
}
VENDOR_STUB = r"""
import { appendFileSync, writeFileSync, readFileSync } from 'node:fs';
const started = {args: process.argv.slice(2), cwd: process.cwd(), node: process.execPath, pid: process.pid};
writeFileSync('vendor-started.json', JSON.stringify(started));
process.stdin.on('data', (chunk) => {
  appendFileSync('vendor-input.bin', chunk);
  if (process.env.TEST_ADO_CHANGE_ON_INPUT) {
    const config = JSON.parse(readFileSync('config/harness.local.json', 'utf8'));
    config.ado.project = 'Changed before reply';
    writeFileSync('config/harness.local.json', JSON.stringify(config));
  }
  process.stdout.write(chunk);
});
process.stdin.on('end', () => {
  writeFileSync('vendor-eof', 'yes');
  if (!process.env.TEST_ADO_IGNORE_SHUTDOWN && !process.env.TEST_ADO_WAIT_FOR_SIGNAL) clearInterval(keepAlive);
});
for (const name of ['SIGTERM', 'SIGINT']) process.on(name, () => {
  writeFileSync('vendor-signal', name);
  if (!process.env.TEST_ADO_IGNORE_SHUTDOWN) process.exit(0);
});
const keepAlive = setInterval(() => {}, 1000);
process.stdout.write(JSON.stringify(started) + '\n');
process.stderr.write('vendor diagnostic\n');
"""


@unittest.skipUnless(NODE, "Node is required for ADO launcher process tests")
class AdoLauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ado launcher spaces ")
        self.addCleanup(self.temp.cleanup)
        self.root = self.workspace("workspace one")

    def workspace(self, name: str, organization: str = "workspace-org") -> Path:
        root = Path(self.temp.name) / name
        (root / "scripts").mkdir(parents=True)
        (root / "config").mkdir()
        shutil.copyfile(ROOT / "scripts/start_ado_mcp.mjs", root / "scripts/start_ado_mcp.mjs")
        package = root / "node_modules/@azure-devops/mcp"
        (package / "dist").mkdir(parents=True)
        (package / "package.json").write_text(json.dumps({"name": "@azure-devops/mcp", "version": "2.8.1", "type": "module"}), encoding="utf-8")
        (package / "dist/index.js").write_text(VENDOR_STUB, encoding="utf-8")
        config = copy.deepcopy(VALID_CONFIG)
        config["ado"]["organization"] = organization
        config["ado"]["allowedHttpsOrigins"][0] = f"https://dev.azure.com/{organization}"
        self.write_config(config, root)
        return root

    def write_config(self, config: object, root: Path | None = None) -> None:
        (root or self.root).joinpath("config/harness.local.json").write_text(json.dumps(config), encoding="utf-8")

    def env(self, **extra: str) -> dict[str, str]:
        env = os.environ.copy()
        env.pop("ADO_ORGANIZATION", None)
        env.update(extra)
        return env

    def run_launcher(self, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run([NODE, str(self.root / "scripts/start_ado_mcp.mjs")], cwd=self.temp.name,
                              env=self.env(**env), input=b'{"jsonrpc":"2.0","id":1}\n', capture_output=True, timeout=5)

    def start_launcher(self, root: Path | None = None, **env: str) -> tuple[subprocess.Popen, dict]:
        root = root or self.root
        proc = subprocess.Popen([NODE, str(root / "scripts/start_ado_mcp.mjs")], cwd=self.temp.name,
                                env=self.env(**env), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(self.cleanup_process, proc)
        lines = queue.Queue()
        threading.Thread(target=lambda: lines.put(proc.stdout.readline()), daemon=True).start()
        try:
            ready = lines.get(timeout=5)
        except queue.Empty:
            self.fail("vendor stub did not become ready")
        self.assertTrue(ready, "launcher ended before vendor readiness")
        return proc, json.loads(ready)

    @staticmethod
    def cleanup_process(proc: subprocess.Popen) -> None:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream and not stream.closed:
                stream.close()

    def assert_blocked(self, config: object, key: str) -> None:
        self.write_config(config)
        result = self.run_launcher(ADO_ORGANIZATION="otherwise-valid-old-org")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertIn(key, result.stderr.decode())
        self.assertIn("config/harness.local.json", result.stderr.decode())
        self.assertFalse((self.root / "vendor-started.json").exists())

    def test_start_uses_local_scope_and_repo_paths_regardless_of_old_env_and_cwd(self) -> None:
        for old_env in (None, "", "   ", "wrong-old-org"):
            with self.subTest(old_env=old_env):
                result = self.run_launcher(**({} if old_env is None else {"ADO_ORGANIZATION": old_env}))
                self.assertEqual(result.returncode, 0, result.stderr)
                ready, protocol = result.stdout.split(b"\n", 1)
                started = json.loads(ready)
                self.assertEqual(started["args"], ["workspace-org", "-d", "work-items", "wiki", "search"])
                self.assertEqual(Path(started["cwd"]).resolve(), self.root.resolve())
                self.assertEqual(Path(started["node"]).resolve(), Path(NODE).resolve())
                self.assertEqual(protocol, b'{"jsonrpc":"2.0","id":1}\n')
                self.assertIn(b"vendor diagnostic", result.stderr)
                self.assertTrue((self.root / "vendor-eof").exists())

    def test_missing_invalid_json_and_wrong_top_level_never_spawn_or_leak_data(self) -> None:
        path = self.root / "config/harness.local.json"
        for raw in (None, '{"secret":"DO-NOT-PRINT",', "null", "[]", "42", '"a string"', "{}", '{"ado":[]}'):
            with self.subTest(raw=raw):
                if raw is None:
                    path.unlink()
                else:
                    path.write_text(raw, encoding="utf-8")
                result = self.run_launcher(ADO_ORGANIZATION="valid-old-org")
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertIn(b"ADO configuration error", result.stderr)
                self.assertNotIn(b"DO-NOT-PRINT", result.stderr)
                self.assertFalse((self.root / "vendor-started.json").exists())

    def test_missing_invalid_and_placeholder_org_project_never_spawn(self) -> None:
        for key in ("organization", "project"):
            for value in (None, 1, False, [], {}, "", " \t ", " leading", "trailing ", "a\nb", "<ORG>", "partial<", "TODO", "tbd", "CHANGEME", "REPLACE_ME", "your-org-slug", "your-project-name", "https://dev.azure.com/org", "a/b", "a\\b"):
                with self.subTest(key=key, value=value):
                    config = copy.deepcopy(VALID_CONFIG)
                    config["ado"][key] = value
                    self.assert_blocked(config, f"ado.{key}")
            config = copy.deepcopy(VALID_CONFIG)
            del config["ado"][key]
            self.assert_blocked(config, f"ado.{key}")
        config = copy.deepcopy(VALID_CONFIG)
        config["ado"]["organization"] = "--authentication"
        self.assert_blocked(config, "ado.organization")

    def test_origin_must_match_org_and_preserve_only_valid_https_origins(self) -> None:
        canonical = "https://dev.azure.com/workspace-org"
        for origins in (None, "https://dev.azure.com/workspace-org", [], [canonical, canonical],
                        ["https://dev.azure.com"], ["https://dev.azure.com/other-org"],
                        [canonical, "https://dev.azure.com/other-org"],
                        [canonical, "https://other-org.visualstudio.com"],
                        [canonical, "https://almsearch.dev.azure.com/other-org"],
                        [canonical, "http://example.test"], [canonical, "https://user:secret@example.test"],
                        [canonical, "https://user@example.test"], [canonical, "https://:secret@example.test"],
                        [canonical, "https://example.test:443"], [canonical, "https://example.test?"],
                        [canonical, "https://example.test#"], [canonical, "https://example.test/has space"],
                        [canonical, "https://example.test\\other"], [canonical, 4]):
            with self.subTest(origins=origins):
                config = copy.deepcopy(VALID_CONFIG)
                config["ado"]["allowedHttpsOrigins"] = origins
                self.assert_blocked(config, "ado.allowedHttpsOrigins")

    def test_missing_wrong_or_incomplete_dependency_never_spawns(self) -> None:
        package = self.root / "node_modules/@azure-devops/mcp"
        manifest = package / "package.json"
        for metadata in (None, "not json", {"name": "@azure-devops/mcp", "version": "2.9.0"},
                         {"name": "another-package", "version": "2.8.1"},
                         {"name": "@azure-devops/mcp", "version": "2.8.1"}):
            with self.subTest(metadata=metadata):
                if metadata is None:
                    manifest.unlink()
                else:
                    manifest.write_text(metadata if isinstance(metadata, str) else json.dumps(metadata), encoding="utf-8")
                if metadata == {"name": "@azure-devops/mcp", "version": "2.8.1"}:
                    (package / "dist/index.js").unlink()
                result = self.run_launcher()
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertIn(b"npm ci", result.stderr)
                self.assertFalse((self.root / "vendor-started.json").exists())

    def test_extra_launcher_arguments_cannot_override_scope_or_domains(self) -> None:
        result = subprocess.run([NODE, str(self.root / "scripts/start_ado_mcp.mjs"), "other-org"],
                                cwd=self.temp.name, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"does not accept arguments", result.stderr)
        self.assertFalse((self.root / "vendor-started.json").exists())

    def test_two_workspaces_keep_independent_scopes_with_same_old_env(self) -> None:
        second = self.workspace("workspace two", "second-org")
        one, first_ready = self.start_launcher(ADO_ORGANIZATION="shared-old-org")
        two, second_ready = self.start_launcher(second, ADO_ORGANIZATION="shared-old-org")
        self.assertEqual(first_ready["args"][0], "workspace-org")
        self.assertEqual(second_ready["args"][0], "second-org")
        for proc in (one, two):
            output, error = proc.communicate(b"independent\n", timeout=5)
            self.assertEqual(proc.returncode, 0, error)
            self.assertEqual(output, b"independent\n")

    def test_scope_edit_blocks_immediate_next_input_and_terminates_old_child(self) -> None:
        for field in ("organization", "project", "allowedHttpsOrigins"):
            with self.subTest(field=field):
                self.write_config(VALID_CONFIG)
                proc, _ = self.start_launcher()
                config = copy.deepcopy(VALID_CONFIG)
                if field == "organization":
                    config["ado"][field] = "new-org"
                    config["ado"]["allowedHttpsOrigins"][0] = "https://dev.azure.com/new-org"
                elif field == "project":
                    config["ado"][field] = "New project"
                else:
                    config["ado"][field].append("https://new.example.test")
                self.write_config(config)
                output, error = proc.communicate(b"must-not-reach-old-server\n", timeout=5)
                self.assertEqual(proc.returncode, 2)
                self.assertEqual(output, b"")
                self.assertIn(b"Restart the ADO MCP server", error)
                self.assertFalse((self.root / "vendor-input.bin").exists())

    def test_idle_invalid_configuration_tears_down_old_child(self) -> None:
        proc, ready = self.start_launcher()
        (self.root / "config/harness.local.json").write_text("{unfinished", encoding="utf-8")
        proc.wait(timeout=5)
        self.assertEqual(proc.returncode, 2)
        self.assertIn(b"Restart the ADO MCP server", proc.stderr.read())
        if os.name != "nt":
            with self.assertRaises(ProcessLookupError):
                os.kill(ready["pid"], 0)

    def test_changed_scope_blocks_old_output_before_host_receives_it(self) -> None:
        proc, _ = self.start_launcher(TEST_ADO_CHANGE_ON_INPUT="1")
        output, error = proc.communicate(b"old-result\n", timeout=5)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(output, b"")
        self.assertIn(b"Restart the ADO MCP server", error)
        self.assertEqual((self.root / "vendor-input.bin").read_bytes(), b"old-result\n")

    @unittest.skipIf(os.name == "nt", "Windows kills the stub before a POSIX signal marker can be written")
    def test_scope_denial_stays_latched_after_original_configuration_is_restored(self) -> None:
        proc, _ = self.start_launcher(TEST_ADO_IGNORE_SHUTDOWN="1")
        config = copy.deepcopy(VALID_CONFIG)
        config["ado"]["project"] = "Changed project"
        self.write_config(config)
        deadline = time.monotonic() + 3
        while not (self.root / "vendor-signal").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue((self.root / "vendor-signal").exists(), "idle scope denial was not observed")
        self.write_config(VALID_CONFIG)
        output, error = proc.communicate(b"must-still-be-blocked\n", timeout=5)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(output, b"")
        self.assertIn(b"Restart the ADO MCP server", error)
        self.assertFalse((self.root / "vendor-input.bin").exists())

    def test_unrelated_config_and_origin_order_changes_do_not_restart(self) -> None:
        proc, _ = self.start_launcher()
        config = copy.deepcopy(VALID_CONFIG)
        config["ado"]["allowedHttpsOrigins"].reverse()
        config["ado"]["releaseQueryId"] = "new-query"
        config["salesforce"] = {"orgs": []}
        self.write_config(config)
        output, error = proc.communicate(b"still-current\n", timeout=5)
        self.assertEqual(proc.returncode, 0, error)
        self.assertEqual(output, b"still-current\n")

    def test_backpressure_preserves_all_protocol_bytes_and_eof(self) -> None:
        proc, _ = self.start_launcher()
        payload = (b'{"jsonrpc":"2.0","id":7,"value":"' + b"x" * 1000 + b'"}\n') * 2048
        output, error = proc.communicate(payload, timeout=10)
        self.assertEqual(proc.returncode, 0, error)
        self.assertEqual(output, payload)
        self.assertEqual((self.root / "vendor-input.bin").read_bytes(), payload)
        self.assertTrue((self.root / "vendor-eof").exists())

    @unittest.skipIf(os.name == "nt", "Windows does not deliver POSIX SIGINT/SIGTERM to Node handlers")
    def test_stop_signal_reaches_child_and_returns_signal_exit_status(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=sig):
                proc, _ = self.start_launcher(TEST_ADO_WAIT_FOR_SIGNAL="1")
                proc.send_signal(sig)
                proc.wait(timeout=5)
                self.assertEqual(proc.returncode, 128 + sig)
                self.assertEqual((self.root / "vendor-signal").read_text(), signal.Signals(sig).name)

    def test_eof_forces_stuck_vendor_shutdown(self) -> None:
        proc, ready = self.start_launcher(TEST_ADO_IGNORE_SHUTDOWN="1")
        started = time.monotonic()
        proc.communicate(timeout=5)
        self.assertNotEqual(proc.returncode, 0)
        self.assertLess(time.monotonic() - started, 5)
        self.assertTrue((self.root / "vendor-eof").exists())
        if os.name != "nt":
            with self.assertRaises(ProcessLookupError):
                os.kill(ready["pid"], 0)


if __name__ == "__main__":
    unittest.main()
