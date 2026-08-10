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
        # The declare-once invariant scans the Principle sources directly; there is no
        # RULE_SOURCE_TIERS constant to trust instead.
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

    def test_agent_surfaces_do_not_call_a_drifted_entry_non_effective(self) -> None:
        """The runtime says `approved-drifted` is effective with disclosure; the prose must too.

        `knowledge_store.verify_entry_citations` grades a drifted citation `warning` while
        draft/revoked/not-effective/digest-mismatch grade `invalid`, and the binding resolver
        accepts drifted entries. search-knowledge had been listing `drifted` among the
        non-effective lanes, so a skill inheriting its rules by pointer silently learned the
        opposite of what the executor does — that is how check-against-principles came to
        contradict its own pointer target. The negative half of this test is the point: a future
        edit may not put `drifted` back into a non-effective enumeration.
        """
        from scripts import knowledge_store

        source = Path(knowledge_store.__file__).read_text(encoding="utf-8")
        self.assertIn('verdict="drifted",\n                severity="warning"', source)

        skill = (ROOT / ".github/skills/search-knowledge/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`approved-drifted` is effective, with disclosure", skill)
        for enumeration in re.findall(r"[Nn]on-effective matches \(([^)]*)\)", skill):
            self.assertNotIn(
                "drifted",
                enumeration,
                "search-knowledge lists drifted as non-effective, contradicting "
                "verify_entry_citations (severity 'warning', not 'invalid')",
            )

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
