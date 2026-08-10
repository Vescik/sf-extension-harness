"""Direct subprocess client for the read-only Salesforce review facade.

The knowledge org-attach executor calls the facade this way — the executor observes;
the agent never carries attested bytes, so it cannot mint digests.
The returned envelope is schema-validated and digest-checked before anything trusts it.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

try:
    from schema_format import FORMAT_CHECKER
except ModuleNotFoundError:  # imported as scripts.salesforce_review_client
    from scripts.schema_format import FORMAT_CHECKER

HARNESS_ROOT = Path(__file__).resolve().parents[1]


class SalesforceReviewError(RuntimeError):
    """A facade call or its evidence envelope failed validation."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def json_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def canonical_embedded_digest(value: dict[str, Any], digest_field: str = "sha256") -> str:
    unsigned = {key: child for key, child in value.items() if key != digest_field}
    return json_hash(unsigned)


def contract_schema(root: Path, filename: str) -> Path:
    local = root / "schemas" / filename
    return local if local.is_file() else HARNESS_ROOT / "schemas" / filename


def _load_json(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SalesforceReviewError(f"required file is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SalesforceReviewError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SalesforceReviewError(f"expected a JSON object in {path}")
    return parsed


def validate_salesforce_review_envelope(root: Path, envelope: dict[str, Any]) -> None:
    schema = _load_json(contract_schema(root, "salesforce-org-review-evidence.schema.json"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FORMAT_CHECKER).iter_errors(envelope),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        location = ".".join(str(part) for part in errors[0].absolute_path) or "$"
        raise SalesforceReviewError(
            f"Salesforce review evidence: schema failure at {location}: {errors[0].message}"
        )
    if envelope.get("sha256") != canonical_embedded_digest(envelope):
        raise SalesforceReviewError("Salesforce review evidence digest is invalid")


def call_salesforce_review_facade(
    root: Path,
    alias: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Call the fixed local facade directly and return only its normalized envelope."""

    script = root / "scripts" / "salesforce_review_server.py"
    if not script.is_file():
        raise SalesforceReviewError("Salesforce review facade is missing")
    messages = "\n".join(
        [
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "knowledge-org-attach", "version": "1.0.0"},
                    },
                }
            ),
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                }
            ),
            "",
        ]
    )
    try:
        completed = subprocess.run(
            [sys.executable, str(script), "--org", alias],
            cwd=root,
            input=messages,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SalesforceReviewError("Salesforce review facade was unavailable") from exc
    if completed.returncode != 0 or len(completed.stdout.encode("utf-8")) > 1_048_576:
        raise SalesforceReviewError(
            "Salesforce review facade did not return a bounded successful receipt"
        )
    response: dict[str, Any] | None = None
    for line in completed.stdout.splitlines():
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and candidate.get("id") == 2:
            response = candidate
            break
    envelope = response.get("result", {}).get("structuredContent") if response else None
    if not isinstance(envelope, dict):
        raise SalesforceReviewError("Salesforce review facade response was malformed")
    validate_salesforce_review_envelope(root, envelope)
    return envelope
