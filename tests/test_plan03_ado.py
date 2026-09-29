"""Executable cache compatibility checks; these do not simulate agent no-op behavior."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from scripts.schema_format import FORMAT_CHECKER


ROOT = Path(__file__).resolve().parents[1]


def fixture(name):
    return json.loads((ROOT / "evals" / "fixtures" / name).read_text())


class AdoCacheCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads((ROOT / "schemas" / "ado-item-cache.schema.json").read_text())
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema, format_checker=FORMAT_CHECKER)

    def assert_valid(self, value):
        errors = list(self.validator.iter_errors(value))
        self.assertEqual([], errors, "\n".join(error.message for error in errors))

    def assert_invalid(self, value):
        self.assertTrue(list(self.validator.iter_errors(value)))

    def test_complete_and_partial_v2_and_legacy_v1_are_readable_without_mutation(self):
        for prefix in ("ado-item", "ado-item.legacy-v1"):
            for completeness in ("complete", "partial"):
                with self.subTest(prefix=prefix, completeness=completeness):
                    value = fixture(f"{prefix}.{completeness}.json")
                    original = deepcopy(value)
                    self.assert_valid(value)
                    self.assertEqual(original, value)
                    self.assertEqual(completeness, value["completeness"]["status"])

    def test_unknown_versions_and_missing_version_are_not_legacy_fallbacks(self):
        for version in (0, 3, "2", None):
            with self.subTest(version=version):
                value = fixture("ado-item.complete.json")
                value["schemaVersion"] = version
                self.assert_invalid(value)
        value.pop("schemaVersion")
        self.assert_invalid(value)

    def test_v1_retains_its_required_positive_revision_contract(self):
        value = fixture("ado-item.legacy-v1.complete.json")
        for revision in (None, 0, -1, "7"):
            with self.subTest(revision=revision):
                value["source"]["revision"] = revision
                self.assert_invalid(value)
        del value["source"]["revision"]
        self.assert_invalid(value)

    def test_v2_rejects_old_revision_even_with_otherwise_valid_source(self):
        for revision in (1, 999999, None):
            with self.subTest(revision=revision):
                value = fixture("ado-item.complete.json")
                value["source"]["revision"] = revision
                self.assert_invalid(value)

    def test_v2_rejects_nested_transport_metadata(self):
        for key in ("rev", "revision", "System.Rev"):
            for nested in (
                {key: 4},
                {"fields": {key: 4}},
                {"children": [{"fields": {key: 4}}]},
                {"testCases": [{"steps": [{key: 4}]}]},
            ):
                with self.subTest(key=key, nested=nested):
                    value = fixture("ado-item.complete.json")
                    value["item"].update(nested)
                    self.assert_invalid(value)

    def test_v1_remains_compatible_with_previously_permitted_item_metadata(self):
        value = fixture("ado-item.legacy-v1.complete.json")
        value["item"]["rev"] = 7
        value["item"]["children"] = [{"fields": {"System.Rev": 9}}]
        self.assert_valid(value)

    def test_source_text_can_contain_revision_words_without_becoming_metadata(self):
        value = fixture("ado-item.complete.json")
        text = 'Keep "revision", "rev" and "System.Rev" when these are requirement text.'
        value["item"]["description"] = text
        value["item"]["acceptanceCriteria"] = text
        value["item"]["testCases"] = [{"id": 44, "steps": [{"action": text}]}]
        self.assert_valid(value)
        self.assertEqual(text, value["item"]["description"])

    def test_required_identity_and_timestamp_fields_remain_required(self):
        for prefix in ("ado-item", "ado-item.legacy-v1"):
            for key in ("organization", "project", "itemId", "retrievedAt"):
                with self.subTest(prefix=prefix, key=key):
                    value = fixture(f"{prefix}.complete.json")
                    del value["source"][key]
                    self.assert_invalid(value)
            value = fixture(f"{prefix}.complete.json")
            value["source"]["retrievedAt"] = "not-a-timestamp"
            self.assert_invalid(value)

    def test_identity_shape_and_unknown_source_fields_remain_rejected(self):
        for key, invalid in (("organization", ""), ("project", ""), ("itemId", 0),
                             ("itemId", "1201"), ("unexpected", "scope")):
            with self.subTest(key=key, invalid=invalid):
                value = fixture("ado-item.complete.json")
                value["source"][key] = invalid
                self.assert_invalid(value)

    def test_complete_cannot_claim_missing_relations_or_remove_untrusted_marker(self):
        for prefix in ("ado-item", "ado-item.legacy-v1"):
            value = fixture(f"{prefix}.partial.json")
            value["completeness"]["status"] = "complete"
            self.assert_invalid(value)
            for marker in (False, None):
                value = fixture(f"{prefix}.complete.json")
                value["untrustedExternalData"] = marker
                self.assert_invalid(value)

    def test_completeness_shape_is_not_weakened_by_version_transition(self):
        for key in ("status", "detailLevel", "relationsIncluded", "testCasesIncluded",
                    "attachments", "pagesFetched", "missingRelations"):
            with self.subTest(key=key):
                value = fixture("ado-item.complete.json")
                del value["completeness"][key]
                self.assert_invalid(value)

    def test_handover_keeps_template_git_identity_but_not_query_revision(self):
        value = fixture("output.release-handover.valid.json")
        schema = json.loads((ROOT / "schemas" / "output-envelope.schema.json").read_text())
        Draft202012Validator(schema, format_checker=FORMAT_CHECKER).validate(value)
        query_refs = [ref for ref in value["sourceRefs"] if "/query/" in ref]
        self.assertTrue(query_refs)
        for ref in query_refs:
            self.assertNotRegex(ref, r"@\d+$")
        template_refs = [ref for ref in value["sourceRefs"] if ref.startswith("template:")]
        self.assertEqual(1, len(template_refs))
        self.assertRegex(template_refs[0], r"@[0-9a-f]{40}(?:\+dirty)?$")
        self.assertIn("recordRevision", schema["$defs"]["recordRef"]["required"])


if __name__ == "__main__":
    unittest.main()
