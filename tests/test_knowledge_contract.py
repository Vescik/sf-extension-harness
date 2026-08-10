from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from scripts.validate_harness import reserved_fixture_leaks


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "evals/fixtures"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class KnowledgeSchemaTests(unittest.TestCase):
    def validator(self, name: str) -> Draft202012Validator:
        schema = load_json(ROOT / "schemas" / name)
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema, format_checker=FormatChecker())

    def assert_valid(self, fixture: str, schema: str) -> None:
        errors = list(self.validator(schema).iter_errors(load_yaml(FIXTURES / fixture)))
        self.assertEqual([], errors, [error.message for error in errors])

    def assert_invalid(self, fixture: str, schema: str) -> None:
        errors = list(self.validator(schema).iter_errors(load_yaml(FIXTURES / fixture)))
        self.assertTrue(errors, f"{fixture} was incorrectly accepted")

    def test_rule_ids_declare_exactly_once_and_the_registry_stays_retired(self) -> None:
        # Owner decision 2026-08-04: rule-registry.yaml was a metadata re-encoding of the
        # Principle sources; rules now resolve straight from the declaration lines. The
        # resolution stays unambiguous only while every ID is declared exactly once across
        # the four sources — and the registry (plus its schema) must not quietly return.
        # The work-record lane (and its RULE_SOURCE_TIERS constant) was deleted in
        # phase 5; the declare-once invariant now scans the Principle sources directly.
        sources = [ROOT / ".github/copilot-instructions.md"] + sorted(
            (ROOT / ".github/instructions").glob("*.instructions.md")
        )
        declarations: list[str] = []
        pattern = re.compile(r"\*\*((?:SAFE|MP|ORG|SF)-[A-Z0-9-]+)\s+—")
        for source in sources:
            declarations.extend(pattern.findall(source.read_text(encoding="utf-8")))
        self.assertTrue(declarations)
        self.assertEqual(sorted(declarations), sorted(set(declarations)))
        self.assertFalse((ROOT / ".github/instructions/rule-registry.yaml").exists())
        self.assertFalse((ROOT / "schemas/principle-registry.schema.json").exists())

    def test_live_knowledge_has_no_reserved_fixture_leak(self) -> None:
        """Reserved synthetic fixture identifiers must never reach live Knowledge
        surfaces. Legal Salesforce names (including ones that collide with old
        example names, e.g. Invoice__c) are governed by provenance and lifecycle
        rules, not by a name denylist."""
        surfaces: list[Path] = []
        knowledge_root = ROOT / ".ai/knowledge"
        surfaces.extend(sorted(knowledge_root.glob("*.md")))
        artifacts_root = knowledge_root / "artifacts"
        if artifacts_root.exists():
            surfaces.extend(sorted(artifacts_root.rglob("*.md")))
        features_root = knowledge_root / "features"
        if features_root.exists():
            surfaces.extend(sorted(features_root.glob("*.md")))
        for name in ("artifacts-ledger.jsonl", "features-ledger.jsonl"):
            ledger = knowledge_root / name
            if ledger.exists():
                surfaces.append(ledger)
        self.assertTrue(surfaces, "no live Knowledge surfaces found to scan")
        for surface in surfaces:
            leaks = reserved_fixture_leaks(surface.read_text(encoding="utf-8"))
            self.assertEqual([], leaks, f"{surface}: reserved fixture tokens leaked: {leaks}")

    def test_legal_business_names_are_not_screened_as_fixture_leaks(self) -> None:
        """Regression for the retired name denylist (introduced in 07c1788): a real
        team's legally named metadata and rule prefixes must pass the
        runtime-authority leak scan."""
        legal_text = "Flow writes Invoice__c.Status__c under rule MP-INV-001."
        self.assertEqual([], reserved_fixture_leaks(legal_text))
        self.assertEqual(
            ["HarnessEngagement"],
            reserved_fixture_leaks("references HarnessEngagement__c"),
        )

if __name__ == "__main__":
    unittest.main()
