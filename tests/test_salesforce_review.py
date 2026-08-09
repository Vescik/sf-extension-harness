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
IDENTITY_QUERY = "SELECT Id, IsSandbox FROM Organization LIMIT 1"

FAKE_SF = r'''
import json, os, sys
state_dir = os.environ["FAKE_SF_STATE"]
with open(os.path.join(state_dir, "cli-state.json"), encoding="utf-8") as fh:
    state = json.load(fh)
calls_path = os.path.join(state_dir, "cli-calls.log")
args = sys.argv[1:]
with open(calls_path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(args) + "\n")
def count(prefix):
    n = 0
    with open(calls_path, encoding="utf-8") as fh:
        for line in fh:
            if json.loads(line)[: len(prefix)] == prefix:
                n += 1
    return n
if args[:1] == ["version"]:
    print(json.dumps({"cliVersion": state["cliVersion"], "architecture": "test"}))
elif args[:3] == ["org", "auth", "show-access-token"]:
    tokens = state["tokens"]
    index = min(count(["org", "auth", "show-access-token"]) - 1, len(tokens) - 1)
    print(json.dumps({"status": 0, "result": {"accessToken": tokens[index]}, "warnings": []}))
elif args[:2] == ["org", "display"]:
    print(json.dumps({"status": 0, "result": state["display"], "warnings": []}))
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
        if params.get("q") == IDENTITY_QUERY:
            self._respond(
                200,
                {
                    "totalSize": 1,
                    "done": True,
                    "records": [
                        {
                            "attributes": {"type": "Organization"},
                            "Id": state.get("org_id", ORG_ID_18),
                            "IsSandbox": state.get("is_sandbox", True),
                        }
                    ],
                },
            )
            return
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


class FacadeHarness(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        tmp = Path(self.tmp.name)
        MockSalesforce.state = {
            "valid_tokens": ["token-1"],
            "org_id": ORG_ID_18,
            "is_sandbox": True,
        }
        MockSalesforce.requests_seen = []
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), MockSalesforce)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
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
        cli_version: str = "@salesforce/cli/2.146.3",
        tokens=("token-1", "token-2"),
        instance_url: str = f"https://{SANDBOX_HOST}",
        org_id: str = ORG_ID_18,
    ) -> None:
        self.cli_state_path.write_text(
            json.dumps(
                {
                    "cliVersion": cli_version,
                    "tokens": list(tokens),
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

    def write_config(self, allowed_objects=None, denied=None, allow_enumeration: bool = False) -> None:
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
                            }
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
        # of show-access-token calls in THIS session, so a re-spawned server starts
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


class ProtocolAndSurface(FacadeHarness):
    def test_tool_surface_pin_and_handshake(self) -> None:
        responses, _ = self.roundtrip([self.initialize_message(), {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
        init = next(r for r in responses if r["id"] == 1)
        self.assertEqual(init["result"]["protocolVersion"], "2025-06-18")
        tools = next(r for r in responses if r["id"] == 2)["result"]["tools"]
        # Read-only pin (plan par. 7 test 7): exactly these seven, no write handlers.
        self.assertEqual(
            sorted(tool["name"] for tool in tools),
            [
                "explain_query",
                "org_limits",
                "review_configured_orgs",
                "review_installed_packages",
                "review_object_contract",
                "review_org_identity",
                "review_soql_query",
            ],
        )
        for tool in tools:
            self.assertTrue(tool["annotations"]["readOnlyHint"])

    def test_batch_client_flow_without_initialized_notification(self) -> None:
        # salesforce_review_client.py batches initialize + tools/call, never sends
        # notifications/initialized, then closes stdin. Both answers, clean exit 0.
        responses, process = self.roundtrip([self.initialize_message(), self.call(2, "review_org_identity")])
        self.assertEqual(process.returncode, 0)
        envelope = self.envelope_of(responses, 2)
        self.assertEqual(envelope["status"], "VERIFIED")
        validate_salesforce_review_envelope(ROOT, envelope)

    def test_startup_spawns_a_fixed_number_of_cli_processes(self) -> None:
        self.roundtrip([self.initialize_message(), self.call(2, "review_soql_query", {"query": "SELECT Id FROM Account"})])
        self.assertEqual(self.cli_calls(["version"]), 1)
        self.assertEqual(self.cli_calls(["org", "auth", "show-access-token"]), 1)
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
    def test_401_refresh_replays_once_and_succeeds(self) -> None:
        MockSalesforce.state["records"] = [{"Id": "001AA0000001"}]
        process = self.spawn()
        # Let startup complete against token-1, then invalidate it: the next data call
        # 401s, the server re-runs show-access-token (getting token-2) and replays.
        process.stdin.write((json.dumps(self.initialize_message()) + "\n").encode("utf-8"))
        process.stdin.flush()
        time.sleep(2.5)
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
        self.assertEqual(self.cli_calls(["org", "auth", "show-access-token"]), 2)

    def test_refresh_landing_on_a_different_org_fails_closed(self) -> None:
        MockSalesforce.state["records"] = [{"Id": "001AA0000001"}]
        process = self.spawn()
        process.stdin.write((json.dumps(self.initialize_message()) + "\n").encode("utf-8"))
        process.stdin.flush()
        time.sleep(2.5)
        # Invalidate the token AND swap the org the mock claims to be: the refresh
        # re-proof must catch the rebind and fail-close the whole session.
        MockSalesforce.state["valid_tokens"] = ["token-2"]
        MockSalesforce.state["org_id"] = "00DBB0000009999BBB"
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
            self.assertEqual(envelope["status"], "BLOCKED")
            self.assertIn("IDENTITY_ORG_ID_MISMATCH", envelope["warnings"])

    def test_production_shaped_host_refuses_to_start(self) -> None:
        self.write_cli_state(instance_url="https://acme.my.salesforce.com")
        process = self.spawn()
        stdout, stderr = process.communicate(b"", timeout=60)
        self.assertEqual(process.returncode, 2)
        self.assertIn(b"IDENTITY_HOST_MISMATCH", stderr)
        self.assertEqual(stdout, b"")

    def test_denied_org_id_refuses_to_start(self) -> None:
        self.write_config(denied=[ORG_ID_18])
        process = self.spawn()
        stdout, stderr = process.communicate(b"", timeout=60)
        self.assertEqual(process.returncode, 2)
        self.assertIn(b"ORG_ID_DENIED", stderr)

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

    def test_too_old_cli_refuses_to_start(self) -> None:
        # show-access-token only exists from 2.136.8; older CLIs must fail loudly.
        self.write_cli_state(cli_version="@salesforce/cli/2.100.0")
        process = self.spawn()
        _, stderr = process.communicate(b"", timeout=60)
        self.assertEqual(process.returncode, 2)
        self.assertIn(b"CLI_VERSION_UNSUPPORTED", stderr)

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


if __name__ == "__main__":
    unittest.main()
