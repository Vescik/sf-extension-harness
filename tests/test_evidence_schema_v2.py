"""Pins for evidence schema v2 and the retired requireDualSource trust flag (F-1).

The REST facade rewrite (docs/plan-2026-08-09-salesforce-mcp-rest-rewrite.md, D-2)
revises the envelope's `sources` to single-transport {cli, rest} under schemaVersion 2
while v1 {cli, mcp} envelopes must keep validating until the .mjs server is deleted in
F-4 (rollback provision, plan §6a). These tests pin both directions plus the refusals
that keep the contract honest: no franken-envelope carrying both transports, no
transport-less envelope, no complete REST source without a real API version.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from scripts import copilot_safety_hook as safety
from scripts.salesforce_review_client import (
    SalesforceReviewError,
    canonical_embedded_digest,
    validate_salesforce_review_envelope,
)

ROOT = Path(__file__).resolve().parents[1]

CLI_SOURCE = {
    "kind": "salesforce-cli",
    "version": "unavailable",
    "complete": False,
    "retrievedAt": "2026-08-09T12:00:00Z",
}
MCP_SOURCE = {
    "kind": "salesforce-mcp",
    "version": "0.30.15",
    "complete": False,
    "retrievedAt": "2026-08-09T12:00:00Z",
}
REST_SOURCE = {
    "kind": "salesforce-rest",
    "version": "64.0",
    "complete": False,
    "retrievedAt": "2026-08-09T12:00:00Z",
}


def envelope(schema_version: int, sources: dict) -> dict:
    env = {
        "schemaVersion": schema_version,
        "runId": "12345678-1234-4123-8123-123456789abc",
        "generatedAt": "2026-08-09T12:00:00Z",
        "reviewType": "org-identity",
        "status": "BLOCKED",
        "target": {
            "environment": "development",
            "apiVersion": "64.0",
            "aliasPolicyMatched": True,
            "expectedHostMatched": False,
            "expectedOrgIdMatched": False,
            "isSandbox": False,
            "nonProduction": False,
        },
        "sources": sources,
        "facts": {},
        "reconciliation": {"status": "NOT_RUN", "comparisons": []},
        "completeness": {"complete": False, "dualSource": False, "truncated": False},
        "warnings": ["NOT_SANDBOX"],
    }
    env["sha256"] = canonical_embedded_digest(env)
    return env


class EvidenceSchemaV2(unittest.TestCase):
    def assert_valid(self, env: dict) -> None:
        validate_salesforce_review_envelope(ROOT, env)

    def assert_invalid(self, env: dict) -> None:
        with self.assertRaises(SalesforceReviewError):
            validate_salesforce_review_envelope(ROOT, env)

    def test_v1_dual_source_envelope_still_validates(self) -> None:
        # Rollback provision (plan §6a): the .mjs server's v1 output stays valid
        # until the enum is narrowed to [2] after all completion tests pass.
        self.assert_valid(envelope(1, {"cli": CLI_SOURCE, "mcp": MCP_SOURCE}))

    def test_v2_rest_envelope_validates(self) -> None:
        self.assert_valid(envelope(2, {"cli": CLI_SOURCE, "rest": REST_SOURCE}))

    def test_both_transports_at_once_is_rejected(self) -> None:
        self.assert_invalid(
            envelope(2, {"cli": CLI_SOURCE, "mcp": MCP_SOURCE, "rest": REST_SOURCE})
        )

    def test_transport_less_envelope_is_rejected(self) -> None:
        self.assert_invalid(envelope(2, {"cli": CLI_SOURCE}))

    def test_incomplete_rest_source_may_be_unavailable(self) -> None:
        unavailable = dict(REST_SOURCE, version="unavailable")
        self.assert_valid(envelope(2, {"cli": CLI_SOURCE, "rest": unavailable}))

    def test_complete_rest_source_requires_real_api_version(self) -> None:
        contradiction = dict(REST_SOURCE, version="unavailable", complete=True)
        self.assert_invalid(envelope(2, {"cli": CLI_SOURCE, "rest": contradiction}))


class RetiredRequireDualSourceFlag(unittest.TestCase):
    """The hook's trust condition is review.enabled alone; the retired flag is
    tolerated in configs (old server still reads it until F-4) but never required."""

    def config(self, review: dict) -> dict:
        return {"salesforce": {"review": review}}

    def test_enabled_without_the_retired_flag_is_allowed(self) -> None:
        error = safety.salesforce_review_tool_error(
            self.config({"enabled": True}),
            "salesforce-readonly/review_org_identity",
            {},
        )
        self.assertIsNone(error)

    def test_enabled_with_the_retired_flag_is_still_allowed(self) -> None:
        error = safety.salesforce_review_tool_error(
            self.config({"enabled": True, "requireDualSource": True}),
            "salesforce-readonly/review_org_identity",
            {},
        )
        self.assertIsNone(error)

    def test_disabled_review_is_denied(self) -> None:
        error = safety.salesforce_review_tool_error(
            self.config({"enabled": False}),
            "salesforce-readonly/review_org_identity",
            {},
        )
        self.assertIsNotNone(error)


if __name__ == "__main__":
    unittest.main()
