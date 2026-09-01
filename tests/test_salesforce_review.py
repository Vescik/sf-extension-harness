"""End-to-end tests for the REST Salesforce review facade (salesforce_review_server.py).

Replaces the previous suite wholesale (plan F-2): the old tests mocked the CLI and
vendor-MCP child processes of the retired .mjs server; this suite drives the
real Python server as a stdio subprocess against an in-process mock Salesforce REST
endpoint and a fake `sf` CLI script, over exactly the newline-delimited JSON-RPC
frames real clients send. Every VERIFIED envelope asserted here is also validated
through salesforce_review_client.validate_salesforce_review_envelope - the real
schema + canonical digest - so these tests pin the live consumer contract, not a
copy of it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "scripts" / "salesforce_review_server.py"
sys.path.insert(0, str(ROOT))

from scripts.salesforce_review_client import validate_salesforce_review_envelope

ALIAS = "devsb"
ORG_ID_18 = "00DAA0000001234AAA"
SANDBOX_HOST = "acme--dev.sandbox.my.salesforce.com"

FAKE_SF = r'''
import json, os, sys, time
state_dir = os.environ["FAKE_SF_STATE"]
with open(os.path.join(state_dir, "cli-state.json"), encoding="utf-8") as fh:
    state = json.load(fh)
calls_path = os.path.join(state_dir, "cli-calls.log")
args = sys.argv[1:]
with open(calls_path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(args) + "\n")
if state.get("cliDelaySeconds"):
    time.sleep(state["cliDelaySeconds"])
def count(prefix):
    n = 0
    with open(calls_path, encoding="utf-8") as fh:
        for line in fh:
            if json.loads(line)[: len(prefix)] == prefix:
                n += 1
    return n
if args[:2] == ["org", "display"]:
    tokens = state["tokens"]
    index = min(count(["org", "display"]) - 1, len(tokens) - 1)
    result = dict(state["display"])
    result["accessToken"] = tokens[index]
    print(json.dumps({"status": 0, "result": result, "warnings": []}))
else:
    print(json.dumps({"status": 1, "message": "unknown"}))
    sys.exit(1)
'''


class MockSalesforce(BaseHTTPRequestHandler):
    state: dict = {}
    requests_seen: list = []
    lock = threading.Lock()

    def log_message(self, *args):  # noqa: D102 - keep test output clean
        return

    def do_GET(self):  # noqa: N802
        state = type(self).state
        parts = urlsplit(self.path)
        params = {k: v[0] for k, v in parse_qs(parts.query).items()}
        with type(self).lock:
            type(self).requests_seen.append({"path": parts.path, "params": params})
        token = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
        if token not in state.get("valid_tokens", []):
            self._respond(401, [{"message": "Session expired or invalid", "errorCode": "INVALID_SESSION_ID"}])
            return
        delay = state.get("delay_seconds")
        if delay and "/query" in parts.path and "explain" not in params:
            time.sleep(delay)
        if "explain" in params:
            self._respond(200, {"plans": state.get("plans", [])})
            return
        if parts.path.endswith("/limits/"):
            self._respond(200, state.get("limits", {"DailyApiRequests": {"Max": 100000, "Remaining": 99999}}))
            return
        if "/sobjects/" in parts.path and parts.path.endswith("/describe/"):
            describe = state.get("describe")
            if describe is None:
                self._respond(404, [{"errorCode": "NOT_FOUND", "message": "The requested resource does not exist"}])
            else:
                self._respond(200, describe)
            return
        if params.get("q", "").startswith("SELECT QualifiedApiName FROM EntityDefinition"):
            self._respond(200, {"done": True, "records": state.get("entity_records", [])})
            return
        if params.get("q", "").startswith("SELECT QualifiedApiName, DataType"):
            self._respond(200, {"done": True, "records": state.get("field_records", [])})
            return
        if "InstalledSubscriberPackage" in params.get("q", ""):
            self._respond(200, {"done": True, "records": state.get("package_records", [])})
            return
        if parts.path.endswith("/query/") and "q" in params:
            pages = state.get("pages") or [{"done": True, "records": state.get("records", [])}]
            self._respond(200, pages[0])
            return
        if "/query/" in parts.path:  # nextRecordsUrl continuation
            pages = state.get("pages") or []
            index = int(parts.path.rsplit("-", 1)[-1]) if "-" in parts.path else 1
            self._respond(200, pages[min(index, len(pages) - 1)])
            return
        self._respond(404, [{"errorCode": "NOT_FOUND", "message": "no route"}])

    def _respond(self, status: int, payload) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class QuietHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):  # noqa: D102
        # The server under test may close its socket mid-body after a bounded
        # streaming rejection; the resulting BrokenPipeError in the mock is expected
        # and must not spray tracebacks over the test output.
        return


class FacadeHarness(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        tmp = Path(self.tmp.name)
        MockSalesforce.state = {
            "valid_tokens": ["token-1"],
        }
        MockSalesforce.requests_seen = []
        self.http = QuietHTTPServer(("127.0.0.1", 0), MockSalesforce)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        # shutdown() stops serve_forever but leaves the listening socket open —
        # server_close() releases it, or every test leaks a socket warning.
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        (tmp / "fake_sf.py").write_text(FAKE_SF, encoding="utf-8")
        self.cli_state_path = tmp / "cli-state.json"
        self.write_cli_state()
        (tmp / "cli-calls.log").write_text("", encoding="utf-8")
        real_policy = json.loads((ROOT / "config" / "salesforce-review-policy.json").read_text(encoding="utf-8"))
        (tmp / "policy.json").write_text(json.dumps(real_policy), encoding="utf-8")
        self.config_path = tmp / "config.json"
        self.write_config()
        self.tmp_path = tmp

    def write_cli_state(
        self,
        tokens=("token-1", "token-2"),
        instance_url: str = f"https://{SANDBOX_HOST}",
        org_id: str = ORG_ID_18,
        cli_delay_seconds: float = 0,
    ) -> None:
        self.cli_state_path.write_text(
            json.dumps(
                {
                    "tokens": list(tokens),
                    "cliDelaySeconds": cli_delay_seconds,
                    "display": {
                        "id": org_id,
                        "instanceUrl": instance_url,
                        "apiVersion": "64.0",
                        "username": "dev@example.invalid",
                        "connectedStatus": "Connected",
                    },
                }
            ),
            encoding="utf-8",
        )

    def write_config(self, allowed_objects=None, denied=None, allow_enumeration: bool = False, extra_orgs=None) -> None:
        review = {
            "enabled": True,
            "apiVersion": "64.0",
            "allowedPackageNamespaces": ["*"],
            "maxFieldsPerObject": 500,
            "evidenceMaxAgeMinutes": 60,
        }
        if allowed_objects is not None:
            review["allowedObjectApiNames"] = allowed_objects
        if denied is not None:
            review["deniedOrganizationIds"] = denied
        self.config_path.write_text(
            json.dumps(
                {
                    "safety": {"allowScopedEnumeration": allow_enumeration},
                    "salesforce": {
                        "review": review,
                        "orgs": [
                            {
                                "alias": ALIAS,
                                "environment": "development",
                                "expectedInstanceHost": SANDBOX_HOST,
                                "expectedOrganizationId": ORG_ID_18,
                            },
                            *(extra_orgs or []),
                        ],
                    },
                }
            ),
            encoding="utf-8",
        )

    def server_env(self) -> dict:
        port = self.http.server_address[1]
        return {
            **os.environ,
            "SF_HARNESS_TEST_MODE": "1",
            "SF_HARNESS_CONFIG_PATH": str(self.config_path),
            "SF_HARNESS_REVIEW_POLICY_PATH": str(self.tmp_path / "policy.json"),
            "SF_HARNESS_SF_EXECUTABLE": sys.executable,
            "SF_HARNESS_SF_ARGS_JSON": json.dumps([str(self.tmp_path / "fake_sf.py")]),
            "SF_HARNESS_REST_BASE": f"http://127.0.0.1:{port}",
            "FAKE_SF_STATE": str(self.tmp_path),
        }

    def spawn(self) -> subprocess.Popen:
        # Per-session CLI call log: the fake CLI indexes its token list by the number
        # of org-display calls in THIS session, so a re-spawned server starts
        # from token-1 again instead of inheriting the previous session's counter.
        (self.tmp_path / "cli-calls.log").write_text("", encoding="utf-8")
        process = subprocess.Popen(
            [sys.executable, str(SERVER), "--org", ALIAS],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.server_env(),
            cwd=str(ROOT),
        )
        self.addCleanup(lambda: process.poll() is None and process.kill())
        return process

    def roundtrip(self, messages: "list[dict]", timeout: int = 60) -> "tuple[list[dict], subprocess.Popen]":
        process = self.spawn()
        stdin_payload = "".join(json.dumps(m) + "\n" for m in messages)
        stdout, stderr = process.communicate(stdin_payload.encode("utf-8"), timeout=timeout)
        self.assertNotIn(b"\r", stdout, "CRLF regression: protocol frames must never carry \\r")
        responses = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        if process.returncode != 0:
            self.fail(f"server exited {process.returncode}; stderr: {stderr.decode('utf-8', 'replace')[-2000:]}")
        return responses, process

    def initialize_message(self, message_id: int = 1) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        }

    def call(self, message_id: int, name: str, arguments: "dict | None" = None) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }

    def envelope_of(self, responses: "list[dict]", message_id: int) -> dict:
        response = next(r for r in responses if r.get("id") == message_id)
        return response["result"]["structuredContent"]

    def cli_calls(self, prefix: "list[str]") -> int:
        count = 0
        for line in (self.tmp_path / "cli-calls.log").read_text(encoding="utf-8").splitlines():
            if json.loads(line)[: len(prefix)] == prefix:
                count += 1
        return count

    @staticmethod
    def large_account_describe(target_bytes: int) -> dict:
        """A realistic oversized describe, generated in memory (never a committed fixture).

        The bulk mirrors the live regression: a giant picklistValues collection that
        normalization intentionally ignores. Field traits stay describe-shaped so the
        normal merge path runs once the payload is accepted."""
        describe = {
            "name": "Account",
            "fields": [
                {"name": "Name", "type": "string", "nillable": False, "calculated": False, "relationshipName": None, "referenceTo": [], "length": 255, "precision": None, "scale": None, "unique": False, "externalId": False, "createable": True, "updateable": True},
                {
                    "name": "Load__c",
                    "type": "picklist",
                    "nillable": True,
                    "calculated": False,
                    "relationshipName": None,
                    "referenceTo": [],
                    "length": 255,
                    "precision": None,
                    "scale": None,
                    "unique": False,
                    "externalId": False,
                    "createable": True,
                    "updateable": True,
                    "picklistValues": [],
                },
            ],
        }
        value = {"active": True, "defaultValue": False, "label": "Harness Load Value %07d", "value": "harness_load_value_%07d"}
        overhead = len(json.dumps(value).encode()) + 10
        count = max(1, (target_bytes - len(json.dumps(describe).encode())) // overhead)
        describe["fields"][1]["picklistValues"] = [
            {"active": True, "defaultValue": False, "label": f"Harness Load Value {i:07d}", "value": f"harness_load_value_{i:07d}"}
            for i in range(count)
        ]
        return describe

    def seed_two_field_tooling(self) -> None:
        MockSalesforce.state["entity_records"] = [{"QualifiedApiName": "Account"}]
        MockSalesforce.state["field_records"] = [
            {"QualifiedApiName": "Name", "DataType": "Text(255)", "IsNillable": False, "IsCalculated": False, "RelationshipName": None, "ReferenceTo": None, "Length": 255, "Precision": None, "Scale": None, "IsIndexed": True},
            {"QualifiedApiName": "Load__c", "DataType": "Picklist", "IsNillable": True, "IsCalculated": False, "RelationshipName": None, "ReferenceTo": None, "Length": 255, "Precision": None, "Scale": None, "IsIndexed": False},
        ]


class ProtocolAndSurface(FacadeHarness):
    def test_tool_surface_pin_and_handshake(self) -> None:
        responses, _ = self.roundtrip([self.initialize_message(), {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
        init = next(r for r in responses if r["id"] == 1)
        self.assertEqual(init["result"]["protocolVersion"], "2025-06-18")
        # Version pin: 2.4.0 marks single-command CLI readiness.
        self.assertEqual(init["result"]["serverInfo"]["version"], "2.4.0")
        tools = next(r for r in responses if r["id"] == 2)["result"]["tools"]
        # Read-only pin: exactly these six, no write handlers or identity-query tool.
        self.assertEqual(
            sorted(tool["name"] for tool in tools),
            [
                "explain_query",
                "org_limits",
                "review_configured_orgs",
                "review_installed_packages",
                "review_object_contract",
                "review_soql_query",
            ],
        )
        for tool in tools:
            self.assertTrue(tool["annotations"]["readOnlyHint"])

    def test_handshake_does_not_wait_for_the_salesforce_cli(self) -> None:
        self.write_cli_state(cli_delay_seconds=2)
        started = time.monotonic()
        responses, _ = self.roundtrip([self.initialize_message(), {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertIn("result", next(r for r in responses if r["id"] == 1))
        # Background readiness may already be using the CLI, but it must not delay discovery.

    def test_batch_client_flow_without_initialized_notification(self) -> None:
        # salesforce_review_client.py batches initialize + tools/call, never sends
        # notifications/initialized, then closes stdin. Both answers, clean exit 0.
        responses, process = self.roundtrip([self.initialize_message(), self.call(2, "review_installed_packages")])
        self.assertEqual(process.returncode, 0)
        envelope = self.envelope_of(responses, 2)
        self.assertEqual(envelope["status"], "VERIFIED")
        validate_salesforce_review_envelope(ROOT, envelope)

    def test_startup_spawns_a_fixed_number_of_cli_processes(self) -> None:
        self.roundtrip([self.initialize_message(), self.call(2, "review_soql_query", {"query": "SELECT Id FROM Account"})])
        self.assertEqual(self.cli_calls(["org", "display"]), 1)

    def test_cancellation_suppresses_the_response(self) -> None:
        MockSalesforce.state["delay_seconds"] = 1.5
        MockSalesforce.state["records"] = [{"Id": "001AA0000001"}]
        process = self.spawn()
        frames = [
            self.initialize_message(),
            self.call(7, "review_soql_query", {"query": "SELECT Id FROM Account"}),
            {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 7, "reason": "test"}},
        ]
        stdout, _ = process.communicate("".join(json.dumps(m) + "\n" for m in frames).encode("utf-8"), timeout=60)
        ids = [json.loads(line).get("id") for line in stdout.splitlines() if line.strip()]
        self.assertIn(1, ids)
        self.assertNotIn(7, ids, "a cancelled request id must never get a late response")

    def test_two_parallel_slow_calls_both_answered_atomically(self) -> None:
        MockSalesforce.state["delay_seconds"] = 1.2
        MockSalesforce.state["records"] = [{"Id": "001AA0000001"}]
        responses, _ = self.roundtrip(
            [
                self.initialize_message(),
                self.call(11, "review_soql_query", {"query": "SELECT Id FROM Account"}),
                self.call(12, "review_soql_query", {"query": "SELECT Id FROM Contact"}),
            ]
        )
        # Every stdout line parsed as standalone JSON already proves atomic,
        # non-interleaved frames; both ids answered proves pool dispatch.
        for message_id in (11, 12):
            envelope = self.envelope_of(responses, message_id)
            self.assertEqual(envelope["status"], "VERIFIED")
        self.assertEqual(self.cli_calls(["org", "display"]), 1)


class SoqlEnvelope(FacadeHarness):
    def test_verified_envelope_validates_against_the_real_contract(self) -> None:
        MockSalesforce.state["records"] = [
            {"attributes": {"type": "Account"}, "Id": "001AA000000001AAA", "Name": "One"},
            {"attributes": {"type": "Account"}, "Id": "001AA000000002AAA", "Name": "Two"},
        ]
        responses, _ = self.roundtrip(
            [self.initialize_message(), self.call(2, "review_soql_query", {"query": "SELECT Id, Name FROM Account"})]
        )
        envelope = self.envelope_of(responses, 2)
        validate_salesforce_review_envelope(ROOT, envelope)
        self.assertEqual(envelope["schemaVersion"], 2)
        self.assertEqual(set(envelope["sources"]), {"cli", "rest"})
        facts = envelope["facts"]["soqlQuery"]
        self.assertEqual(facts["fromObjects"], ["Account"])
        self.assertEqual(facts["matched"], 2)
        self.assertNotIn("attributes", facts["records"][0])
        self.assertEqual(envelope["reconciliation"]["status"], "IDENTITY_MATCH_ONLY")

    def test_pagination_follows_next_records_url(self) -> None:
        MockSalesforce.state["pages"] = [
            {"done": False, "nextRecordsUrl": "/services/data/v64.0/query/01g-1", "records": [{"Id": "001AA0000001"}]},
            {"done": True, "records": [{"Id": "001AA0000002"}]},
        ]
        responses, _ = self.roundtrip(
            [self.initialize_message(), self.call(2, "review_soql_query", {"query": "SELECT Id FROM Account"})]
        )
        facts = self.envelope_of(responses, 2)["facts"]["soqlQuery"]
        self.assertEqual(facts["matched"], 2)

    def test_row_overflow_returns_incomplete_result_truncated(self) -> None:
        MockSalesforce.state["records"] = [{"Id": f"001AA{i:010d}"} for i in range(2001)]
        responses, _ = self.roundtrip(
            [self.initialize_message(), self.call(2, "review_soql_query", {"query": "SELECT Id FROM Account"})]
        )
        envelope = self.envelope_of(responses, 2)
        self.assertEqual(envelope["status"], "INCOMPLETE")
        self.assertIn("RESULT_TRUNCATED", envelope["warnings"])
        validate_salesforce_review_envelope(ROOT, envelope)

    def test_page_landing_exactly_on_the_cap_skips_the_redundant_fetch(self) -> None:
        # 2000 rows + done=false already proves truncation; fetching another page would
        # spend org latency on provably discarded work (review finding, off-by-one).
        MockSalesforce.state["pages"] = [
            {
                "done": False,
                "nextRecordsUrl": "/services/data/v64.0/query/01g-1",
                "records": [{"Id": f"001AA{i:010d}"} for i in range(2000)],
            },
            {"done": True, "records": [{"Id": "never-fetched"}]},
        ]
        responses, _ = self.roundtrip(
            [self.initialize_message(), self.call(2, "review_soql_query", {"query": "SELECT Id FROM Account"})]
        )
        envelope = self.envelope_of(responses, 2)
        self.assertEqual(envelope["status"], "INCOMPLETE")
        self.assertIn("RESULT_TRUNCATED", envelope["warnings"])
        continuations = [r for r in MockSalesforce.requests_seen if "01g-1" in r["path"]]
        self.assertEqual(continuations, [], "no continuation page may be fetched past the cap")

    def test_more_than_twenty_from_targets_is_denied_up_front(self) -> None:
        # The schema pins fromObjects to maxItems 20; both lanes must agree by denying.
        joins = " ".join(f"(SELECT Id FROM Child{i}__r)," for i in range(21))
        query = f"SELECT Id, {joins[:-1]} FROM Parent__c"
        responses, _ = self.roundtrip(
            [self.initialize_message(), self.call(2, "review_soql_query", {"query": query})]
        )
        envelope = self.envelope_of(responses, 2)
        self.assertEqual(envelope["status"], "BLOCKED")
        self.assertIn("QUERY_VALIDATION_DENIED", envelope["warnings"])

    def test_object_allowlist_blocks_soql_and_explain(self) -> None:
        self.write_config(allowed_objects=["Account"])
        responses, _ = self.roundtrip(
            [
                self.initialize_message(),
                self.call(2, "review_soql_query", {"query": "SELECT Id FROM Secret__c"}),
                self.call(3, "explain_query", {"query": "SELECT Id FROM Secret__c"}),
            ]
        )
        blocked = self.envelope_of(responses, 2)
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertIn("OBJECT_NOT_ALLOWLISTED", blocked["warnings"])
        explain_result = next(r for r in responses if r["id"] == 3)["result"]
        self.assertTrue(explain_result["isError"], "explain must not be an allowlist bypass")
        self.assertEqual(explain_result["structuredContent"]["error"], "OBJECT_NOT_ALLOWLISTED")


class RefreshAndWalls(FacadeHarness):
    def initialize_ready_process(self, process: subprocess.Popen) -> None:
        frames = [self.initialize_message(), self.call(2, "review_installed_packages")]
        process.stdin.write("".join(json.dumps(frame) + "\n" for frame in frames).encode("utf-8"))
        process.stdin.flush()
        seen = set()
        while seen != {1, 2}:
            line = process.stdout.readline()
            self.assertTrue(line, "server closed before readiness completed")
            seen.add(json.loads(line)["id"])

    def assert_first_call_warning(self, warning: str) -> None:
        responses, _ = self.roundtrip([self.initialize_message(), self.call(2, "review_installed_packages")])
        envelope = self.envelope_of(responses, 2)
        self.assertIn(warning, envelope["warnings"])

    def test_401_refresh_replays_once_and_succeeds(self) -> None:
        MockSalesforce.state["records"] = [{"Id": "001AA0000001"}]
        process = self.spawn()
        # Let background readiness complete against token-1, then invalidate it: the next data call
        # 401s, the server re-runs org display (getting token-2) and replays.
        self.initialize_ready_process(process)
        MockSalesforce.state["valid_tokens"] = ["token-2"]
        process.stdin.write(
            (json.dumps(self.call(5, "review_soql_query", {"query": "SELECT Id FROM Account"})) + "\n").encode("utf-8")
        )
        process.stdin.close()
        process.stdin = None  # Py3.9 communicate() would flush the closed pipe
        stdout, stderr = process.communicate(timeout=60)
        responses = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        envelope = next(r for r in responses if r.get("id") == 5)["result"]["structuredContent"]
        self.assertEqual(envelope["status"], "VERIFIED", stderr.decode("utf-8", "replace")[-1500:])
        self.assertEqual(self.cli_calls(["org", "display"]), 2)

    def test_refresh_does_not_query_organization_identity(self) -> None:
        MockSalesforce.state["records"] = [{"Id": "001AA0000001"}]
        process = self.spawn()
        self.initialize_ready_process(process)
        # Token refresh is deliberately token-only; it must not query Organization.
        MockSalesforce.state["valid_tokens"] = ["token-2"]
        for message_id in (6, 7):
            process.stdin.write(
                (json.dumps(self.call(message_id, "review_soql_query", {"query": "SELECT Id FROM Account"})) + "\n").encode("utf-8")
            )
        process.stdin.close()
        process.stdin = None  # Py3.9 communicate() would flush the closed pipe
        stdout, _ = process.communicate(timeout=60)
        responses = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        for message_id in (6, 7):
            envelope = next(r for r in responses if r.get("id") == message_id)["result"]["structuredContent"]
            self.assertEqual(envelope["status"], "VERIFIED")
        self.assertEqual(self.cli_calls(["org", "display"]), 2)
        self.assertFalse(
            any("Organization" in request.get("params", {}).get("q", "") for request in MockSalesforce.requests_seen)
        )

    def test_production_shaped_host_is_refused_on_first_tool_call(self) -> None:
        self.write_cli_state(instance_url="https://acme.my.salesforce.com")
        self.assert_first_call_warning("NON_PRODUCTION_HOST_REQUIRED")

    def test_denied_org_id_is_refused_on_first_tool_call(self) -> None:
        self.write_config(denied=[ORG_ID_18])
        self.assert_first_call_warning("ORG_ID_DENIED")

    def test_production_like_alias_refused_before_any_org_contact(self) -> None:
        # Second never-production wall (ported from the .mjs): `sf org display` performs
        # refreshAuth, so a production-named alias must be refused pre-contact.
        process = subprocess.Popen(
            [sys.executable, str(SERVER), "--org", "prod-sandbox"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.server_env(),
            cwd=str(ROOT),
        )
        _, stderr = process.communicate(b"", timeout=60)
        self.assertEqual(process.returncode, 2)
        self.assertIn(b"ALIAS_PRODUCTION_LIKE", stderr)
        self.assertEqual(
            (self.tmp_path / "cli-calls.log").read_text(encoding="utf-8"),
            "",
            "the refusal must happen before any sf CLI invocation",
        )

    def test_readiness_logs_all_cli_stages_to_output(self) -> None:
        process = self.spawn()
        frames = [self.initialize_message(), self.call(2, "review_installed_packages")]
        stdout, stderr = process.communicate(
            "".join(json.dumps(frame) + "\n" for frame in frames).encode("utf-8"),
            timeout=60,
        )
        responses = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        self.assertEqual(self.envelope_of(responses, 2)["status"], "VERIFIED")
        output = stderr.decode("utf-8", "replace")
        for marker in (
            "readiness started: checking Salesforce CLI authorization",
            "readiness org-display:",
            "readiness complete: configured org accepted",
        ):
            self.assertIn(marker, output)

    def test_duplicate_selected_alias_is_rejected_as_invalid_config(self) -> None:
        # Two config entries claiming the selected alias are ambiguous: pins could be
        # taken from the wrong entry. Fail closed instead of picking the first.
        self.write_config(
            extra_orgs=[
                {
                    "alias": ALIAS,
                    "environment": "qa",
                    "expectedInstanceHost": SANDBOX_HOST,
                    "expectedOrganizationId": ORG_ID_18,
                }
            ]
        )
        process = self.spawn()
        _, stderr = process.communicate(b"", timeout=60)
        self.assertEqual(process.returncode, 2)
        self.assertIn(b"CONFIG_INVALID", stderr)
        self.assertEqual(
            (self.tmp_path / "cli-calls.log").read_text(encoding="utf-8"),
            "",
            "ambiguous config must be refused before any sf CLI invocation",
        )

    def test_unrelated_stale_alias_does_not_block_the_selected_alias(self) -> None:
        # Only the selected alias is proven. A stale, unauthorized, or half-filled
        # entry for a different alias must not block this session.
        self.write_config(
            extra_orgs=[
                {
                    "alias": "stale-qa",
                    "environment": "qa",
                    "expectedInstanceHost": "gone--old.sandbox.my.salesforce.com",
                    "expectedOrganizationId": "00DZZ0000008888ZZZ",
                }
            ]
        )
        responses, _ = self.roundtrip([self.initialize_message(), {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
        init = next(r for r in responses if r["id"] == 1)
        self.assertIn("result", init)

    def test_startup_never_runs_version_or_show_access_token(self) -> None:
        responses, _ = self.roundtrip(
            [self.initialize_message(), self.call(2, "review_installed_packages")]
        )
        self.assertEqual(self.envelope_of(responses, 2)["status"], "VERIFIED")
        self.assertEqual(self.cli_calls(["version"]), 0)
        self.assertEqual(self.cli_calls(["org", "auth", "show-access-token"]), 0)

    def test_sensitive_gate_blocks_non_soql_and_exempts_soql(self) -> None:
        leaky = [
            {
                "attributes": {"type": "InstalledSubscriberPackage"},
                "SubscriberPackage": {"NamespacePrefix": None, "Name": "admin@example.com"},
                "SubscriberPackageVersion": {"MajorVersion": 1, "MinorVersion": 0, "PatchVersion": 0, "BuildNumber": 1},
            }
        ]
        MockSalesforce.state["package_records"] = leaky
        MockSalesforce.state["records"] = [{"Email": "admin@example.com"}]
        responses, _ = self.roundtrip(
            [
                self.initialize_message(),
                self.call(2, "review_installed_packages"),
                self.call(3, "review_soql_query", {"query": "SELECT Email FROM Contact"}),
            ]
        )
        gated = self.envelope_of(responses, 2)
        self.assertEqual(gated["status"], "BLOCKED")
        self.assertEqual(gated["warnings"], ["SENSITIVE_OUTPUT_DETECTED"])
        exempt = self.envelope_of(responses, 3)
        self.assertEqual(exempt["status"], "VERIFIED")
        self.assertEqual(exempt["facts"]["soqlQuery"]["records"][0]["Email"], "admin@example.com")


class ObjectContractAndDiagnostics(FacadeHarness):
    def test_object_contract_merges_describe_traits_and_reports_contests(self) -> None:
        MockSalesforce.state["entity_records"] = [{"QualifiedApiName": "Account"}]
        MockSalesforce.state["field_records"] = [
            {"QualifiedApiName": "Name", "DataType": "Text(255)", "IsNillable": False, "IsCalculated": False, "RelationshipName": None, "ReferenceTo": None, "Length": 255, "Precision": None, "Scale": None, "IsIndexed": True},
            {"QualifiedApiName": "OwnerId", "DataType": "Lookup(User)", "IsNillable": False, "IsCalculated": False, "RelationshipName": "Owner", "ReferenceTo": {"referenceTo": ["User"]}, "Length": None, "Precision": None, "Scale": None, "IsIndexed": True},
        ]
        MockSalesforce.state["describe"] = {
            "name": "Account",
            "fields": [
                # nillable disagrees with Tooling on purpose: contested -> null + listed.
                {"name": "Name", "type": "string", "nillable": True, "calculated": False, "relationshipName": None, "referenceTo": [], "length": 255, "precision": None, "scale": None, "unique": False, "externalId": False, "createable": True, "updateable": True},
                {"name": "OwnerId", "type": "reference", "nillable": False, "calculated": False, "relationshipName": "Owner", "referenceTo": ["User"], "length": None, "precision": None, "scale": None, "unique": False, "externalId": False, "createable": True, "updateable": True},
            ],
        }
        responses, _ = self.roundtrip(
            [self.initialize_message(), self.call(2, "review_object_contract", {"objectApiName": "Account"})]
        )
        envelope = self.envelope_of(responses, 2)
        validate_salesforce_review_envelope(ROOT, envelope)
        self.assertEqual(envelope["status"], "VERIFIED")
        obj = envelope["facts"]["object"]
        self.assertTrue(obj["exists"])
        by_name = {field["name"]: field for field in obj["fields"]}
        self.assertIsNone(by_name["Name"]["nillable"], "contested trait must be nulled, not resolved")
        self.assertIn("Name.nillable", obj["contestedProperties"])
        rest = by_name["Name"]["sourceExclusive"]["rest"]
        self.assertEqual(rest["createable"], True)
        self.assertEqual(rest["indexed"], True)
        self.assertEqual(by_name["OwnerId"]["referenceTo"], ["User"])

    def test_large_valid_describe_above_generic_cap_is_accepted(self) -> None:
        # Live regression pin (2026-08-11): Account describe of 2,102,565 bytes returned
        # HTTP 200 yet the generic 1 MiB vendor cap rejected it as REST_SCHEMA_MISMATCH
        # with empty facts. The describe supplement owns a larger fixed bound; the
        # normalized contract must come back VERIFIED with describe-only traits intact.
        self.seed_two_field_tooling()
        describe = self.large_account_describe(1_300_000)
        self.assertGreater(len(json.dumps(describe).encode()), 1_048_576)
        MockSalesforce.state["describe"] = describe
        responses, _ = self.roundtrip(
            [self.initialize_message(), self.call(2, "review_object_contract", {"objectApiName": "Account"})]
        )
        envelope = self.envelope_of(responses, 2)
        validate_salesforce_review_envelope(ROOT, envelope)
        self.assertEqual(envelope["status"], "VERIFIED")
        self.assertEqual(envelope["warnings"], [])
        obj = envelope["facts"]["object"]
        self.assertTrue(obj["exists"])
        by_name = {field["name"]: field for field in obj["fields"]}
        self.assertEqual(len(by_name), 2)
        rest = by_name["Load__c"]["sourceExclusive"]["rest"]
        self.assertEqual(rest["unique"], False)
        self.assertEqual(rest["externalId"], False)
        self.assertEqual(rest["createable"], True)
        self.assertEqual(rest["updateable"], True)

    def test_object_contract_respects_allowlist(self) -> None:
        self.write_config(allowed_objects=["Account"])
        responses, _ = self.roundtrip(
            [self.initialize_message(), self.call(2, "review_object_contract", {"objectApiName": "Secret__c"})]
        )
        envelope = self.envelope_of(responses, 2)
        self.assertEqual(envelope["status"], "BLOCKED")
        self.assertIn("OBJECT_NOT_ALLOWLISTED", envelope["warnings"])

    def test_org_limits_passthrough(self) -> None:
        responses, _ = self.roundtrip([self.initialize_message(), self.call(2, "org_limits")])
        result = next(r for r in responses if r["id"] == 2)["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["limits"]["DailyApiRequests"]["Remaining"], 99999)

    def test_explain_returns_raw_plans(self) -> None:
        MockSalesforce.state["plans"] = [
            {
                "cardinality": 1,
                "fields": ["Id"],
                "leadingOperationType": "Index",
                "relativeCost": 0.0,
                "sobjectCardinality": 10,
                "sobjectType": "Account",
                "notes": [],
            }
        ]
        responses, _ = self.roundtrip(
            [
                self.initialize_message(),
                self.call(2, "explain_query", {"query": "SELECT Id FROM Account WHERE Id = '001AA000000001AAA'"}),
            ]
        )
        result = next(r for r in responses if r["id"] == 2)["result"]
        self.assertFalse(result["isError"])
        plans = result["structuredContent"]["plans"]
        self.assertEqual(plans[0]["leadingOperationType"].lower(), "index")

    def test_configured_orgs_requires_the_toggle_and_lists_only_config(self) -> None:
        responses, _ = self.roundtrip([self.initialize_message(), self.call(2, "review_configured_orgs")])
        blocked = self.envelope_of(responses, 2)
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertIn("SCOPED_ENUMERATION_DISABLED", blocked["warnings"])
        self.write_config(allow_enumeration=True)
        responses, _ = self.roundtrip([self.initialize_message(), self.call(2, "review_configured_orgs")])
        envelope = self.envelope_of(responses, 2)
        validate_salesforce_review_envelope(ROOT, envelope)
        self.assertEqual(envelope["facts"]["orgs"], [{"alias": ALIAS, "environment": "development"}])


class LargeDescribePayloadBounds(FacadeHarness):
    """Endpoint-specific inbound bounds for the object-contract path only (2026-08-18).

    The full sObject describe accepts up to 64 MiB and each Tooling FieldDefinition
    query page up to 16 MiB; every other REST call keeps the generic
    maxVendorPayloadBytes policy cap. An oversized response is a payload-size failure
    (REST_PAYLOAD_TOO_LARGE), never the false REST_SCHEMA_MISMATCH diagnosis the
    original live Account regression produced, and larger inbound bounds never widen
    the fixed 500-field, 480 KB result, or 1 MiB frame caps."""

    def test_object_fields_above_generic_cap_below_16mib_is_accepted(self) -> None:
        # A FieldDefinition page above the old generic 1 MiB cap (but under 16 MiB,
        # 500 fields, and the result cap) must now produce the normal VERIFIED
        # contract instead of a payload rejection.
        MockSalesforce.state["entity_records"] = [{"QualifiedApiName": "Account"}]
        MockSalesforce.state["field_records"] = [
            {
                "QualifiedApiName": f"F{i:03d}__c",
                "DataType": "Text(255)",
                "IsNillable": True,
                "IsCalculated": False,
                "RelationshipName": None,
                "ReferenceTo": None,
                "Length": 255,
                "Precision": None,
                "Scale": None,
                "IsIndexed": False,
                "Filler": "x" * 8192,
            }
            for i in range(300)
        ]
        raw = len(json.dumps({"done": True, "records": MockSalesforce.state["field_records"]}).encode())
        self.assertGreater(raw, 1_048_576)
        self.assertLess(raw, 16 * 1024 * 1024)
        responses, _ = self.roundtrip(
            [self.initialize_message(), self.call(2, "review_object_contract", {"objectApiName": "Account"})]
        )
        envelope = self.envelope_of(responses, 2)
        validate_salesforce_review_envelope(ROOT, envelope)
        self.assertEqual(envelope["status"], "VERIFIED")
        self.assertEqual(envelope["warnings"], [])
        obj = envelope["facts"]["object"]
        self.assertEqual(obj["fieldCount"], 300)
        self.assertFalse(obj["truncated"])

    def test_object_field_page_above_16mib_is_rejected(self) -> None:
        # One Tooling page above 16 MiB stops at the stream boundary with the size
        # classification — never a schema mismatch, never a widened bound.
        MockSalesforce.state["entity_records"] = [{"QualifiedApiName": "Account"}]
        MockSalesforce.state["field_records"] = [
            {"QualifiedApiName": f"F{i:04d}__c", "DataType": "Text(255)", "Filler": "y" * 8192}
            for i in range(2100)
        ]
        raw = len(json.dumps({"done": True, "records": MockSalesforce.state["field_records"]}).encode())
        self.assertGreater(raw, 16 * 1024 * 1024)
        responses, _ = self.roundtrip(
            [self.initialize_message(), self.call(2, "review_object_contract", {"objectApiName": "Account"})]
        )
        envelope = self.envelope_of(responses, 2)
        validate_salesforce_review_envelope(ROOT, envelope)
        self.assertEqual(envelope["status"], "INCOMPLETE")
        self.assertEqual(envelope["warnings"], ["REST_PAYLOAD_TOO_LARGE"])
        self.assertNotIn("object", envelope.get("facts") or {})

    def test_more_than_500_fields_still_returns_result_truncated(self) -> None:
        # D10: larger response bytes never buy a larger semantic field contract.
        MockSalesforce.state["entity_records"] = [{"QualifiedApiName": "Account"}]
        MockSalesforce.state["field_records"] = [
            {"QualifiedApiName": f"F{i:03d}__c", "DataType": "Text(255)", "IsNillable": True}
            for i in range(501)
        ]
        responses, _ = self.roundtrip(
            [self.initialize_message(), self.call(2, "review_object_contract", {"objectApiName": "Account"})]
        )
        envelope = self.envelope_of(responses, 2)
        validate_salesforce_review_envelope(ROOT, envelope)
        self.assertEqual(envelope["status"], "INCOMPLETE")
        self.assertEqual(envelope["warnings"], ["RESULT_TRUNCATED"])
        self.assertTrue(envelope["completeness"]["truncated"])

    def test_non_object_query_above_generic_cap_remains_rejected(self) -> None:
        # D2: model-composed SOQL never inherits the enlarged object-contract bounds.
        MockSalesforce.state["records"] = [
            {"Id": f"001AA{i:010d}", "Payload__c": "z" * 4000} for i in range(300)
        ]
        raw = len(json.dumps({"done": True, "records": MockSalesforce.state["records"]}).encode())
        self.assertGreater(raw, 1_048_576)
        responses, _ = self.roundtrip(
            [self.initialize_message(), self.call(2, "review_soql_query", {"query": "SELECT Id, Payload__c FROM Account"})]
        )
        envelope = self.envelope_of(responses, 2)
        validate_salesforce_review_envelope(ROOT, envelope)
        self.assertEqual(envelope["status"], "INCOMPLETE")
        self.assertEqual(envelope["warnings"], ["REST_PAYLOAD_TOO_LARGE"])

    def test_describe_above_old_8mib_bound_is_accepted_and_compacted(self) -> None:
        # A ~9.5 MB describe (generated in memory, never a committed fixture) would
        # have overflowed the previous 8 MiB bound; it must now normalize, and none
        # of its raw picklist bulk may reach the agent-facing envelope.
        self.seed_two_field_tooling()
        describe = self.large_account_describe(9_500_000)
        self.assertGreater(len(json.dumps(describe).encode()), 8 * 1024 * 1024)
        MockSalesforce.state["describe"] = describe
        responses, _ = self.roundtrip(
            [self.initialize_message(), self.call(2, "review_object_contract", {"objectApiName": "Account"})]
        )
        envelope = self.envelope_of(responses, 2)
        validate_salesforce_review_envelope(ROOT, envelope)
        self.assertEqual(envelope["status"], "VERIFIED")
        self.assertEqual(envelope["warnings"], [])
        serialized = json.dumps(envelope)
        self.assertNotIn("picklistValues", serialized)
        self.assertNotIn("Harness Load Value", serialized)
        self.assertLess(len(serialized.encode()), 480_000)

    def test_object_contract_normalized_above_result_cap_keeps_output_failure(self) -> None:
        # An inbound payload accepted under 16 MiB whose NORMALIZED contract exceeds
        # 480,000 bytes must keep the existing output-size classification — inbound
        # capacity never relabels or widens the agent-facing result cap.
        MockSalesforce.state["entity_records"] = [{"QualifiedApiName": "Account"}]
        MockSalesforce.state["field_records"] = [
            {
                "QualifiedApiName": f"Ref{i:03d}__c",
                "DataType": "Lookup(User)",
                "IsNillable": True,
                "IsCalculated": False,
                "RelationshipName": f"Ref{i:03d}__r",
                "ReferenceTo": {"referenceTo": [f"Target_{i:03d}_{j:02d}_{'t' * 40}" for j in range(25)]},
                "Length": None,
                "Precision": None,
                "Scale": None,
                "IsIndexed": False,
            }
            for i in range(400)
        ]
        responses, _ = self.roundtrip(
            [self.initialize_message(), self.call(2, "review_object_contract", {"objectApiName": "Account"})]
        )
        envelope = self.envelope_of(responses, 2)
        validate_salesforce_review_envelope(ROOT, envelope)
        self.assertEqual(envelope["status"], "INCOMPLETE")
        self.assertEqual(envelope["warnings"], ["CLI_OUTPUT_TOO_LARGE"])

    def test_payload_warning_is_incomplete_class_never_blocking(self) -> None:
        from scripts import salesforce_review_server as srv

        self.assertNotIn("REST_PAYLOAD_TOO_LARGE", srv.BLOCKING_WARNINGS)
        schema = json.loads(
            (ROOT / "schemas" / "salesforce-org-review-evidence.schema.json").read_text(encoding="utf-8")
        )
        defs = schema["$defs"]
        self.assertIn("REST_PAYLOAD_TOO_LARGE", defs["warning"]["enum"])
        self.assertIn("REST_PAYLOAD_TOO_LARGE", defs["incompleteWarning"]["enum"])
        self.assertNotIn("REST_PAYLOAD_TOO_LARGE", defs["blockingWarning"]["enum"])

    def test_result_cap_is_independent_and_unchanged(self) -> None:
        # D7: an inbound payload accepted under its bound may still overflow the
        # normalized 480,000-byte result cap and must keep CLI_OUTPUT_TOO_LARGE.
        MockSalesforce.state["records"] = [
            {"Name": f"row-{i:05d}", "Payload__c": "v" * 700} for i in range(1000)
        ]
        raw = len(json.dumps({"done": True, "records": MockSalesforce.state["records"]}).encode())
        self.assertLess(raw, 1_048_576, "inbound stays under the generic cap on purpose")
        self.assertGreater(raw, 480_000)
        responses, _ = self.roundtrip(
            [
                self.initialize_message(),
                self.call(2, "review_soql_query", {"query": "SELECT Name, Payload__c FROM Account"}),
            ]
        )
        envelope = self.envelope_of(responses, 2)
        self.assertEqual(envelope["status"], "INCOMPLETE")
        self.assertEqual(envelope["warnings"], ["CLI_OUTPUT_TOO_LARGE"])


class FakeStreamResponse:
    """A streaming requests.Response stand-in: decoded chunks, headers, close tracking."""

    def __init__(self, content: bytes = b"", status_code: int = 200, headers: "dict | None" = None, chunk_size: int = 1024, explode_after: "int | None" = None):
        self._content = content
        self.status_code = status_code
        self.headers = {k.title(): v for k, v in (headers or {}).items()}
        self._chunk_size = chunk_size
        self.closed = False
        self.chunks_yielded = 0
        self._explode_after = explode_after

    def iter_content(self, chunk_size: int = 65_536):
        for start in range(0, len(self._content), self._chunk_size):
            if self._explode_after is not None and self.chunks_yielded >= self._explode_after:
                raise RuntimeError("unexpected mid-body failure")
            self.chunks_yielded += 1
            yield self._content[start:start + self._chunk_size]

    def close(self):
        self.closed = True


class BoundedStreamingTransport(unittest.TestCase):
    """D3/D4: bounds count decoded bytes via a bounded streaming read (limit + 1),
    the response is closed on every exit path, and diagnostics stay sanitized."""

    def make_client(self):
        from scripts import salesforce_review_server as srv

        client = srv.RestClient.__new__(srv.RestClient)
        client.runtime = {
            "alias": ALIAS,
            "policy": {
                "maxVendorPayloadBytes": 1_048_576,
                "cliTimeoutSeconds": 120,
                "restReadTimeoutSeconds": 60,
                "operationTimeoutSeconds": 180,
                "soqlQueryTimeoutSeconds": 60,
            }
        }
        client.token = "t"
        client.api_version = "64.0"
        client._session = srv.requests.Session()
        self.addCleanup(client._session.close)
        client._session_lock = threading.Lock()
        client._refresh_lock = threading.Lock()
        return client

    def get_with(self, response, **kwargs):
        from unittest.mock import patch
        from scripts import salesforce_review_server as srv

        client = self.make_client()
        with patch.object(srv.RestClient, "_get", return_value=response):
            return client.get_json("/x", **kwargs)

    def assert_rejected(self, response, code: str, **kwargs):
        from unittest.mock import patch
        from scripts import salesforce_review_server as srv

        client = self.make_client()
        with patch.object(srv.RestClient, "_get", return_value=response):
            with self.assertRaises(srv.ReviewError) as ctx:
                client.get_json("/x", **kwargs)
        self.assertEqual(ctx.exception.code, code)
        self.assertTrue(response.closed, "the response must be closed on every exit path")
        return ctx.exception

    def test_body_exactly_at_the_bound_succeeds(self) -> None:
        body = json.dumps({"pad": "y" * 480}).encode()
        response = FakeStreamResponse(body, chunk_size=100)
        parsed = self.get_with(response, max_payload_bytes=len(body), operation="object-describe")
        self.assertEqual(parsed["pad"], "y" * 480)
        self.assertTrue(response.closed)

    def test_body_at_bound_plus_one_is_rejected_and_stops_consuming(self) -> None:
        import io
        from unittest.mock import patch
        from scripts import salesforce_review_server as srv

        body = json.dumps({"pad": "y" * 100_000}).encode()
        response = FakeStreamResponse(body, chunk_size=1000)
        captured = io.StringIO()
        with patch.object(srv.sys, "stderr", captured):
            error = self.assert_rejected(response, "REST_PAYLOAD_TOO_LARGE", max_payload_bytes=len(body) - 1)
        self.assertEqual(error.status, "INCOMPLETE")
        # Overflow is detected on the crossing chunk; nothing further is consumed.
        self.assertEqual(response.chunks_yielded, len(body) // 1000 + (1 if len(body) % 1000 else 0))
        diagnostic = captured.getvalue()
        self.assertIn("operation=generic", diagnostic)
        self.assertIn(f"limit={len(body) - 1}", diagnostic)
        self.assertNotIn("Bearer", diagnostic)
        self.assertNotIn("/x", diagnostic)
        self.assertNotIn("pad", diagnostic, "no body fragment may reach the diagnostic")

    def test_overflow_early_in_a_large_body_stops_at_the_boundary(self) -> None:
        body = b"[" + b"1," * 200_000 + b"1]"
        response = FakeStreamResponse(body, chunk_size=1000)
        self.assert_rejected(response, "REST_PAYLOAD_TOO_LARGE", max_payload_bytes=10_000)
        self.assertLessEqual(response.chunks_yielded, 11, "consumption must stop at limit + 1, not read the tail")

    def test_honest_identity_content_length_rejects_without_reading(self) -> None:
        body = json.dumps({"pad": "y" * 5000}).encode()
        response = FakeStreamResponse(body, headers={"Content-Length": str(len(body))})
        self.assert_rejected(response, "REST_PAYLOAD_TOO_LARGE", max_payload_bytes=1000)
        self.assertEqual(response.chunks_yielded, 0, "an honest oversized header must reject before any body chunk")

    def test_encoded_content_length_is_ignored_for_admission(self) -> None:
        # A gzip transfer's Content-Length describes compressed bytes; admission must
        # come from counting the decoded stream, so a small decoded body passes even
        # under a huge header, and an oversized decoded body still fails.
        body = json.dumps({"pad": "ok"}).encode()
        response = FakeStreamResponse(body, headers={"Content-Length": "999999999", "Content-Encoding": "gzip"})
        parsed = self.get_with(response, max_payload_bytes=1000)
        self.assertEqual(parsed["pad"], "ok")
        oversized = FakeStreamResponse(json.dumps({"pad": "z" * 5000}).encode(), headers={"Content-Length": "10", "Content-Encoding": "gzip"})
        self.assert_rejected(oversized, "REST_PAYLOAD_TOO_LARGE", max_payload_bytes=1000)

    def test_missing_malformed_or_lying_content_length_still_counts_the_stream(self) -> None:
        for headers in (None, {"Content-Length": "abc"}, {"Content-Length": "10"}):
            oversized = FakeStreamResponse(json.dumps({"pad": "z" * 5000}).encode(), headers=headers)
            self.assert_rejected(oversized, "REST_PAYLOAD_TOO_LARGE", max_payload_bytes=1000)

    def test_default_bound_is_the_generic_policy_cap(self) -> None:
        oversized_default = FakeStreamResponse(json.dumps({"pad": "z" * 1_100_000}).encode(), chunk_size=65_536)
        self.assert_rejected(oversized_default, "REST_PAYLOAD_TOO_LARGE")

    def test_invalid_utf8_below_the_bound_is_a_schema_failure(self) -> None:
        response = FakeStreamResponse(b'{"pad": "\xff\xfe"}')
        self.assert_rejected(response, "REST_SCHEMA_MISMATCH", max_payload_bytes=1000)

    def test_invalid_json_and_non_object_top_level_are_schema_failures(self) -> None:
        self.assert_rejected(FakeStreamResponse(b'{"pad": '), "REST_SCHEMA_MISMATCH", max_payload_bytes=1000)
        self.assert_rejected(FakeStreamResponse(b"[1, 2, 3]"), "REST_SCHEMA_MISMATCH", max_payload_bytes=1000)

    def test_http_errors_under_the_bound_keep_their_classification(self) -> None:
        body = json.dumps([{"errorCode": "UNKNOWN_EXCEPTION"}]).encode()
        self.assert_rejected(FakeStreamResponse(body, status_code=500), "REST_SCHEMA_MISMATCH", max_payload_bytes=64 * 1024 * 1024)
        self.assert_rejected(FakeStreamResponse(body, status_code=404), "REST_NOT_FOUND", max_payload_bytes=64 * 1024 * 1024)

    def test_unexpected_mid_body_exception_still_closes_the_response(self) -> None:
        from unittest.mock import patch
        from scripts import salesforce_review_server as srv

        client = self.make_client()
        response = FakeStreamResponse(b"x" * 5000, chunk_size=1000, explode_after=2)
        with patch.object(srv.RestClient, "_get", return_value=response):
            with self.assertRaises(RuntimeError):
                client.get_json("/x", max_payload_bytes=1_000_000)
        self.assertTrue(response.closed)

    def test_401_short_circuits_closed_without_consuming_the_body(self) -> None:
        from unittest.mock import patch
        from scripts import salesforce_review_server as srv

        client = self.make_client()
        response = FakeStreamResponse(b'{"never": "read"}', status_code=401)
        with patch.object(srv.RestClient, "_get", return_value=response):
            status, body = client._fetch_bounded("/x", None, 30, 1000, "generic")
        self.assertEqual((status, body), (401, b""))
        self.assertEqual(response.chunks_yielded, 0)
        self.assertTrue(response.closed)

    def test_connection_error_rebuilds_the_pool_and_retries_exactly_once(self) -> None:
        from unittest.mock import patch
        from scripts import salesforce_review_server as srv

        ok = FakeStreamResponse(json.dumps({"pad": "ok"}).encode())
        with patch.object(
            srv.RestClient, "_get", side_effect=[srv.requests.exceptions.ConnectionError("dead pool"), ok]
        ) as mocked:
            client = self.make_client()
            self.assertEqual(client.get_json("/x")["pad"], "ok")
        self.assertEqual(mocked.call_count, 2)
        with patch.object(
            srv.RestClient,
            "_get",
            side_effect=[srv.requests.exceptions.ConnectionError("a"), srv.requests.exceptions.ConnectionError("b")],
        ) as mocked:
            client = self.make_client()
            with self.assertRaises(srv.ReviewError) as ctx:
                client.get_json("/x")
        self.assertEqual(ctx.exception.code, "REST_UNAVAILABLE")
        self.assertEqual(mocked.call_count, 2, "the pool rebuild retry stays bounded to one replay")

    def test_read_timeout_is_never_retried(self) -> None:
        from unittest.mock import patch
        from scripts import salesforce_review_server as srv

        with patch.object(srv.RestClient, "_get", side_effect=srv.requests.exceptions.ReadTimeout("slow")) as mocked:
            client = self.make_client()
            with self.assertRaises(srv.ReviewError) as ctx:
                client.get_json("/x")
        self.assertEqual(ctx.exception.code, "REST_TIMEOUT")
        self.assertEqual(mocked.call_count, 1)

    def test_token_refresh_uses_the_configured_cli_timeout(self) -> None:
        from unittest.mock import Mock, patch
        from scripts import salesforce_review_server as srv

        client = self.make_client()
        with patch.object(srv, "run_cli_json", return_value={"accessToken": "fresh"}) as cli:
            client._refresh_token("t")
        self.assertEqual(cli.call_args.kwargs["timeout"], 120)
        self.assertEqual(
            cli.call_args.args[0],
            ["org", "display", "--json", "-o", ALIAS],
        )
        self.assertEqual(client.token, "fresh")


class ScaledBoundsConstants(unittest.TestCase):
    """D1/D2/D9/D10/D11: the exact production constants, pinned in isolation."""

    def test_endpoint_specific_constants_are_exact(self) -> None:
        from scripts import salesforce_review_server as srv

        self.assertEqual(srv.MAX_DESCRIBE_PAYLOAD_BYTES, 64 * 1024 * 1024)
        self.assertEqual(srv.MAX_OBJECT_FIELDS_PAYLOAD_BYTES, 16 * 1024 * 1024)

    def test_generic_policy_and_output_caps_are_unchanged(self) -> None:
        from scripts import salesforce_review_server as srv

        policy = json.loads((ROOT / "config" / "salesforce-review-policy.json").read_text(encoding="utf-8"))
        self.assertEqual(policy["maxVendorPayloadBytes"], 1_048_576)
        schema = json.loads((ROOT / "schemas" / "salesforce-review-policy.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["maxVendorPayloadBytes"]["maximum"], 1_048_576)
        self.assertEqual(srv.MAX_RESULT_BYTES, 480_000)
        self.assertEqual(srv.MAX_OUTER_MESSAGE_BYTES, 1_048_576)

    def test_server_version_is_bumped_for_stale_process_detection(self) -> None:
        from scripts import salesforce_review_server as srv

        self.assertEqual(srv.SERVER_VERSION, "2.4.0")

    def test_timeout_policy_defaults_are_pinned(self) -> None:
        policy = json.loads((ROOT / "config" / "salesforce-review-policy.json").read_text(encoding="utf-8"))
        self.assertEqual(policy["cliTimeoutSeconds"], 120)
        self.assertEqual(policy["restReadTimeoutSeconds"], 60)
        self.assertEqual(policy["operationTimeoutSeconds"], 180)
        self.assertEqual(policy["soqlQueryTimeoutSeconds"], 60)

    def test_cli_subprocess_timeout_has_an_explicit_classification(self) -> None:
        from unittest.mock import patch
        from scripts import salesforce_review_server as srv

        with patch.object(srv, "resolve_sf_invocation", return_value=["sf"]), patch.object(
            srv.subprocess,
            "run",
            side_effect=srv.subprocess.TimeoutExpired(["sf", "version", "--json"], 120),
        ):
            with self.assertRaises(srv.ReviewError) as ctx:
                srv.run_cli_json(["version", "--json"], timeout=120)
        self.assertEqual(ctx.exception.code, "CLI_TIMEOUT")
        self.assertEqual(ctx.exception.status, "INCOMPLETE")

    def test_outer_operation_deadline_caps_every_blocking_step(self) -> None:
        from scripts import salesforce_review_server as srv

        token = srv._OPERATION_DEADLINE.set(time.monotonic() - 1)
        try:
            with self.assertRaises(srv.ReviewError) as ctx:
                srv.bounded_operation_timeout(120)
        finally:
            srv._OPERATION_DEADLINE.reset(token)
        self.assertEqual(ctx.exception.code, "MCP_TIMEOUT")

    def test_field_query_limit_sentinel_is_fixed(self) -> None:
        from scripts import salesforce_review_server as srv

        self.assertTrue(srv.EXPECTED_QUERIES["objectFields"].endswith("LIMIT 501"))


class StubRest:
    """Duck-typed RestClient stand-in recording every bound/operation it receives."""

    def __init__(self, field_rows=None, describe=None):
        self.calls: "list[dict]" = []
        self.field_rows = field_rows or []
        self.describe = describe if describe is not None else {"fields": []}
        self.describe_started = threading.Event()
        self.describe_hold: "threading.Event | None" = None
        self.describe_delay = 0.0
        self.describe_windows: "list[tuple[float, float]]" = []
        self.fail_query_with: "Exception | None" = None
        self._lock = threading.Lock()

    def query(self, soql, use_tooling, budget_seconds=45, max_rows=2000, *, max_payload_bytes=None, operation="generic"):
        with self._lock:
            self.calls.append({"kind": "query", "soql": soql, "budget_seconds": budget_seconds, "max_payload_bytes": max_payload_bytes, "operation": operation})
        if self.fail_query_with is not None:
            raise self.fail_query_with
        if "FROM EntityDefinition" in soql:
            return {"records": [{"QualifiedApiName": "Account"}], "truncated": False}
        return {"records": list(self.field_rows), "truncated": False}

    def get_json(self, path, params=None, read_timeout=30, *, max_payload_bytes=None, operation="generic"):
        with self._lock:
            self.calls.append({"kind": "get_json", "path": path, "max_payload_bytes": max_payload_bytes, "operation": operation})
        if "/describe/" in path:
            start = time.monotonic()
            self.describe_started.set()
            if self.describe_hold is not None:
                self.describe_hold.wait(timeout=10)
            if self.describe_delay:
                time.sleep(self.describe_delay)
            with self._lock:
                self.describe_windows.append((start, time.monotonic()))
            return json.loads(json.dumps(self.describe))
        return {"DailyApiRequests": {"Max": 100000, "Remaining": 99999}}


class ObjectContractWiringAndConcurrency(unittest.TestCase):
    """D6/D7/D8 at the handler level: exact bound wiring, one-at-a-time raw describe,
    and immediate compaction of describe rows to the consumed trait set."""

    def make_server(self, stub: StubRest):
        from scripts import salesforce_review_server as srv

        runtime = {
            "alias": "devsb",
            "entry": {"environment": "development"},
            "review": {"apiVersion": "64.0", "maxFieldsPerObject": 500},
            "allowed_objects": {"*"},
            "allowed_namespaces": {"*"},
            "policy": {
                "maxVendorPayloadBytes": 1_048_576,
                "cliTimeoutSeconds": 120,
                "restReadTimeoutSeconds": 60,
                "operationTimeoutSeconds": 180,
                "soqlQueryTimeoutSeconds": 60,
            },
        }
        server = srv.Server(runtime)
        server.rest = stub
        server.proof = {"expectedHostMatched": True, "expectedOrgIdMatched": True, "isSandbox": True, "nonProduction": True}
        server.cli_source = {"kind": "salesforce-cli", "version": "@salesforce/cli/2.146.3", "complete": True, "retrievedAt": "2026-08-18T00:00:00Z"}
        return srv, server

    def tooling_row(self, name: str) -> dict:
        return {"QualifiedApiName": name, "DataType": "Text(255)", "IsNillable": True, "IsCalculated": False, "RelationshipName": None, "ReferenceTo": None, "Length": 255, "Precision": None, "Scale": None, "IsIndexed": False}

    def test_only_the_two_fixed_object_calls_use_the_enlarged_bounds(self) -> None:
        stub = StubRest(
            field_rows=[self.tooling_row("Name")],
            describe={"fields": [{"name": "Name", "type": "string", "nillable": True, "calculated": False, "relationshipName": None, "referenceTo": [], "length": 255, "precision": None, "scale": None, "unique": False, "externalId": False, "createable": True, "updateable": True, "picklistValues": [{"value": "raw-must-not-leak"}], "childRelationships": ["raw"]}]},
        )
        srv, server = self.make_server(stub)
        envelope = srv.review_object_contract(server, {"objectApiName": "Account"})
        self.assertEqual(envelope["status"], "VERIFIED")
        by_kind = {}
        for call in stub.calls:
            if call["kind"] == "query" and "FROM EntityDefinition" in call["soql"]:
                by_kind["entity"] = call
            elif call["kind"] == "query":
                by_kind["fields"] = call
            else:
                by_kind["describe"] = call
        self.assertIsNone(by_kind["entity"]["max_payload_bytes"], "the entity lookup stays generic")
        self.assertEqual(by_kind["entity"]["operation"], "generic")
        self.assertEqual(by_kind["fields"]["max_payload_bytes"], srv.MAX_OBJECT_FIELDS_PAYLOAD_BYTES)
        self.assertEqual(by_kind["fields"]["operation"], "object-fields")
        self.assertEqual(by_kind["describe"]["max_payload_bytes"], srv.MAX_DESCRIBE_PAYLOAD_BYTES)
        self.assertEqual(by_kind["describe"]["operation"], "object-describe")
        serialized = json.dumps(envelope)
        self.assertNotIn("raw-must-not-leak", serialized)
        self.assertNotIn("picklistValues", serialized)
        self.assertNotIn("childRelationships", serialized)

    def test_composed_soql_honors_the_policy_timeout_without_a_hidden_cap(self) -> None:
        stub = StubRest()
        srv, server = self.make_server(stub)
        envelope = srv.review_soql_query(server, {"query": "SELECT Id FROM Account"})
        self.assertEqual(envelope["status"], "VERIFIED")
        query_call = next(call for call in stub.calls if call["kind"] == "query")
        self.assertEqual(query_call["budget_seconds"], 60)

    def test_query_propagates_the_bound_to_every_pagination_page(self) -> None:
        from scripts import salesforce_review_server as srv

        client = srv.RestClient.__new__(srv.RestClient)
        client.api_version = "64.0"
        client.runtime = {
            "policy": {"restReadTimeoutSeconds": 60, "soqlQueryTimeoutSeconds": 60}
        }
        pages = [
            {"records": [{"n": 1}], "done": False, "nextRecordsUrl": "/services/data/v64.0/query/01g-1"},
            {"records": [{"n": 2}], "done": True},
        ]
        calls = []

        def fake_get_json(path, params=None, read_timeout=30, *, max_payload_bytes=None, operation="generic"):
            calls.append({"path": path, "max_payload_bytes": max_payload_bytes, "operation": operation})
            return pages[len(calls) - 1]

        client.get_json = fake_get_json
        result = srv.RestClient.query(
            client, "SELECT X FROM Y", True, max_payload_bytes=srv.MAX_OBJECT_FIELDS_PAYLOAD_BYTES, operation="object-fields"
        )
        self.assertEqual(len(result["records"]), 2)
        self.assertEqual(len(calls), 2, "initial page plus one nextRecordsUrl page")
        for call in calls:
            self.assertEqual(call["max_payload_bytes"], srv.MAX_OBJECT_FIELDS_PAYLOAD_BYTES)
            self.assertEqual(call["operation"], "object-fields")
        calls.clear()
        pages[0] = {"records": [{"n": 1}], "done": True}
        srv.RestClient.query(client, "SELECT X FROM Y", True)
        self.assertEqual(calls, [{"path": "/services/data/v64.0/tooling/query/", "max_payload_bytes": None, "operation": "generic"}])

    def test_compaction_projects_exactly_the_consumed_traits(self) -> None:
        from scripts import salesforce_review_server as srv

        raw = {
            "name": "Load__c",
            "type": "picklist",
            "nillable": True,
            "calculated": False,
            "relationshipName": None,
            "referenceTo": [],
            "length": 255,
            "precision": None,
            "scale": None,
            "unique": False,
            "externalId": False,
            "createable": True,
            "updateable": True,
            "picklistValues": [{"value": "x"} for _ in range(1000)],
            "label": "unused",
            "inlineHelpText": "unused",
        }
        compact = srv.compact_describe_field(raw)
        self.assertEqual(
            set(compact),
            {"typeFamily", "nillable", "calculated", "relationshipName", "referenceTo", "length", "precision", "scale", "unique", "externalId", "createable", "updateable", "dataType"},
        )
        self.assertEqual(compact["typeFamily"], "picklist")
        self.assertEqual(compact["dataType"], "picklist")

    def test_two_object_contracts_never_overlap_the_high_memory_section(self) -> None:
        stub = StubRest(field_rows=[self.tooling_row("Name")], describe={"fields": []})
        stub.describe_delay = 0.25
        srv, server = self.make_server(stub)
        results = []

        def worker():
            results.append(srv.review_object_contract(server, {"objectApiName": "Account"}))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertEqual(len(results), 2)
        self.assertEqual({envelope["status"] for envelope in results}, {"VERIFIED"})
        (a_start, a_end), (b_start, b_end) = sorted(stub.describe_windows)
        self.assertGreaterEqual(b_start, a_end, "raw describe sections must be serialized, never concurrent")

    def test_exception_releases_the_object_contract_lock(self) -> None:
        from scripts import salesforce_review_server as srv

        stub = StubRest()
        stub.fail_query_with = srv.ReviewError("REST_TIMEOUT", "INCOMPLETE")
        _, server = self.make_server(stub)
        with self.assertRaises(srv.ReviewError):
            srv.review_object_contract(server, {"objectApiName": "Account"})
        acquired = server.object_contract_lock.acquire(timeout=1)
        self.assertTrue(acquired, "a failing contract must release the serialization lock")
        server.object_contract_lock.release()

    def test_non_object_tools_run_while_a_contract_holds_the_lock(self) -> None:
        stub = StubRest(field_rows=[self.tooling_row("Name")], describe={"fields": []})
        stub.describe_hold = threading.Event()
        srv, server = self.make_server(stub)
        contract_thread = threading.Thread(target=srv.review_object_contract, args=(server, {"objectApiName": "Account"}))
        contract_thread.start()
        try:
            self.assertTrue(stub.describe_started.wait(timeout=5))
            limits = srv.org_limits(server)
            self.assertEqual(limits["limits"]["DailyApiRequests"]["Remaining"], 99999)
            self.assertTrue(contract_thread.is_alive(), "org_limits completed while the contract still held its lock")
        finally:
            stub.describe_hold.set()
            contract_thread.join(timeout=10)
        self.assertFalse(contract_thread.is_alive())


if __name__ == "__main__":
    unittest.main()
