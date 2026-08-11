from __future__ import annotations

import argparse
import copy
import json
import shutil
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from jsonschema import Draft202012Validator

from scripts import knowledge_store as store
from scripts import relation_kinds

FLOW_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Flow xmlns="http://soap.sforce.com/2006/04/metadata">
    <label>Harness Alpha Router</label>
    <processType>AutoLaunchedFlow</processType>
    <status>Active</status>
    <start>
        <object>HarnessAlphaCase__c</object>
        <triggerType>RecordAfterSave</triggerType>
        <recordTriggerType>Update</recordTriggerType>
    </start>
    <variables>
        <name>caseRecord</name>
        <dataType>SObject</dataType>
        <objectType>HarnessAlphaCase__c</objectType>
        <isInput>true</isInput>
    </variables>
    <recordUpdates>
        <name>Update_Case</name>
        <object>HarnessAlphaCase__c</object>
        <inputAssignments><field>Status__c</field><value><stringValue>Done</stringValue></value></inputAssignments>
        <faultConnector><targetReference>Fault_Screen</targetReference></faultConnector>
    </recordUpdates>
    <customErrors>
        <name>Block_Discount</name>
        <label>Block Discount</label>
        <customErrorMessages>
            <errorMessage>Discount cannot exceed 20% for Standard tier.</errorMessage>
            <isFieldError>true</isFieldError>
            <fieldSelection>Status__c</fieldSelection>
        </customErrorMessages>
    </customErrors>
    <screens>
        <name>Fault_Screen</name>
        <label>Fault Screen</label>
        <fields>
            <name>Reason</name>
            <validationRule>
                <errorMessage>Reason is required before retry.</errorMessage>
                <formulaExpression>NOT(ISBLANK({!Reason}))</formulaExpression>
            </validationRule>
        </fields>
    </screens>
</Flow>
"""

FIELD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Status__c</fullName>
    <label>Status</label>
    <type>Picklist</type>
    <required>true</required>
</CustomField>
"""

APEX_CLASS = """public with sharing class HarnessAlphaService {
    @AuraEnabled
    public static void run() {
        List<HarnessAlphaCase__c> rows = [SELECT Id FROM HarnessAlphaCase__c];
        update rows;
    }
}
"""

APEX_META = """<?xml version="1.0" encoding="UTF-8"?>
<ApexClass xmlns="http://soap.sforce.com/2006/04/metadata">
    <apiVersion>64.0</apiVersion>
    <status>Active</status>
</ApexClass>
"""

VALIDATION_RULE = """<?xml version="1.0" encoding="UTF-8"?>
<ValidationRule xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Status_Required</fullName>
    <active>true</active>
    <errorConditionFormula>ISBLANK(Status__c)</errorConditionFormula>
    <errorMessage>Status is required.</errorMessage>
    <errorDisplayField>Status__c</errorDisplayField>
</ValidationRule>
"""

PATCHED = ("ROOT", "ARTIFACTS_ROOT", "LEDGER_PATH", "REVIEW_ARTIFACT_ROOT", "LOCAL_CONFIG",
           "TAXONOMY_PATH", "FEATURES_ROOT", "FEATURE_LEDGER_PATH")


class KnowledgeStoreFixture(unittest.TestCase):
    """setUp + helpers ONLY — no test methods. Test classes inherit THIS, never each
    other: inheriting a test-bearing class silently re-runs every inherited test in each
    subclass (this module used to collect 460 tests for 97 unique methods, 363 of them
    accidental re-runs). TestArchitectureTests pins the rule."""

    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.temp, True)
        self._saved = {name: getattr(store, name) for name in PATCHED}
        store.ROOT = self.temp
        store.ARTIFACTS_ROOT = self.temp / ".ai/knowledge/artifacts"
        store.LEDGER_PATH = self.temp / ".ai/knowledge/artifacts-ledger.jsonl"
        store.REVIEW_ARTIFACT_ROOT = self.temp / "output/knowledge-approvals"
        store.LOCAL_CONFIG = self.temp / "config/harness.local.json"
        store.TAXONOMY_PATH = self.temp / ".ai/knowledge/keyword-taxonomy.md"
        store.FEATURES_ROOT = self.temp / ".ai/knowledge/features"
        store.FEATURE_LEDGER_PATH = self.temp / ".ai/knowledge/features-ledger.jsonl"
        self.addCleanup(lambda: [setattr(store, k, v) for k, v in self._saved.items()])
        flow_dir = self.temp / "force-app/main/default/flows"
        flow_dir.mkdir(parents=True)
        (flow_dir / "HarnessAlphaRouter.flow-meta.xml").write_text(FLOW_XML, encoding="utf-8")
        field_dir = self.temp / "force-app/main/default/objects/HarnessAlphaCase__c/fields"
        field_dir.mkdir(parents=True)
        (field_dir / "Status__c.field-meta.xml").write_text(FIELD_XML, encoding="utf-8")
        apex_dir = self.temp / "force-app/main/default/classes"
        apex_dir.mkdir(parents=True)
        (apex_dir / "HarnessAlphaService.cls").write_text(APEX_CLASS, encoding="utf-8")
        (apex_dir / "HarnessAlphaService.cls-meta.xml").write_text(APEX_META, encoding="utf-8")
        vr_dir = self.temp / "force-app/main/default/objects/HarnessAlphaCase__c/validationRules"
        vr_dir.mkdir(parents=True)
        (vr_dir / "Status_Required.validationRule-meta.xml").write_text(VALIDATION_RULE, encoding="utf-8")
        (self.temp / ".ai/knowledge").mkdir(parents=True)
        shutil.copytree(Path(__file__).resolve().parents[1] / "schemas", self.temp / "schemas")
        (self.temp / "config").mkdir()
        (self.temp / "config/harness.local.json").write_text(
            json.dumps({"knowledge": {"chatReviewer": "Reviewer Person"}}), encoding="utf-8"
        )
        (self.temp / "sfdx-project.json").write_text(
            json.dumps({"sourceApiVersion": "63.0"}), encoding="utf-8"
        )
        purpose = self.temp / "purpose.md"
        purpose.write_text("Routes alpha cases to the right queue.", encoding="utf-8")
        self.purpose = str(purpose)
        import subprocess

        for command in (
            ["git", "init", "-q"],
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"],
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "fixture"],
        ):
            subprocess.run(command, cwd=self.temp, check=True, capture_output=True)

    def draft(self, **overrides):
        args = argparse.Namespace(
            metadata_type="Flow",
            full_name="HarnessAlphaRouter",
            namespace=None,
            purpose_file=self.purpose,
            source_api_version="64.0",
            candidate_keyword=None,
        )
        for key, value in overrides.items():
            setattr(args, key, value)
        return store.command_entry_draft(args)

    def approve(self, pins):
        return store.command_entry_approve(argparse.Namespace(entry=pins))

    def lane_of(self, identity):
        result = store.command_entry_status(argparse.Namespace(identity=identity))
        self.assertEqual(1, len(result["entries"]))
        return result["entries"][0]

    def review(self, identities=None):
        return store.command_entry_review(argparse.Namespace(identity=identities))


class KnowledgeStoreTests(KnowledgeStoreFixture):
    def test_draft_stamps_collector_version_outside_the_digests(self) -> None:
        from scripts.force_app_knowledge import COLLECTOR_VERSION

        drafted = self.draft()
        frontmatter, body = store.split_entry(
            (self.temp / drafted["path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(COLLECTOR_VERSION, frontmatter["scope"]["collectorVersion"])
        # The stamp dates a factsDigest move for a future auditor; it must never BE one.
        # Facts and the reviewed digest ignore scope, so a collector release alone cannot
        # open a re-approval window.
        stripped = copy.deepcopy(frontmatter)
        del stripped["scope"]["collectorVersion"]
        self.assertEqual(store.facts_digest(frontmatter), store.facts_digest(stripped))
        self.assertEqual(
            store.reviewed_content_digest(frontmatter, body),
            store.reviewed_content_digest(stripped, body),
        )

    def test_draft_approve_happy_path_and_decoy_exclusion(self) -> None:
        drafted = self.draft()
        self.assertEqual("DRAFTED", drafted["outcome"])
        path = self.temp / drafted["path"]
        frontmatter, body = store.split_entry(path.read_text(encoding="utf-8"))
        # R-13: exactly the customErrors element; screen validation and fault path excluded.
        self.assertEqual(1, len(frontmatter["intentionalErrors"]))
        error = frontmatter["intentionalErrors"][0]
        self.assertEqual("customErrors", error["originTag"])
        self.assertEqual("Block_Discount", error["elementApiName"])
        self.assertEqual({"mode": "field", "field": "Status__c"}, error["presentation"])
        self.assertNotIn("Reason is required", json.dumps(frontmatter))
        self.assertIn("## Purpose", body)
        self.assertEqual("draft", self.lane_of(drafted["identity"])["lane"])
        approved = self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        self.assertEqual("APPROVED", approved["outcome"])
        lane = self.lane_of(drafted["identity"])
        self.assertEqual("approved-current", lane["lane"])
        artifact = store.REVIEW_ARTIFACT_ROOT / f"{approved['chunkId']}.md"
        self.assertIn("Full body", artifact.read_text(encoding="utf-8"))
        self.assertEqual("PASS", store.command_entry_check(argparse.Namespace())["outcome"])

    def test_entry_check_passes_over_undescribed_drafts_and_counts_them(self) -> None:
        # Owner decision 2026-08-06 (F-3): a freshly drafted, undescribed corpus is
        # outstanding work, not corruption — the gate must stay green and disclose the debt.
        drafted = self.draft(purpose_file=None)
        frontmatter, body = store.split_entry((self.temp / drafted["path"]).read_text(encoding="utf-8"))
        self.assertIn("<AGENT_DESCRIPTION>", body)
        result = store.command_entry_check(argparse.Namespace())
        self.assertEqual("PASS", result["outcome"])
        self.assertEqual(1, result["awaitingDescription"])
        # Approval must still reject the sentinel — the check-time relaxation never
        # weakens the approval gate.
        with self.assertRaises(store.StoreError):
            self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])

    def test_entry_check_still_fails_on_a_sentinel_outside_the_draft_lane(self) -> None:
        # A non-draft entry carrying the sentinel is corruption (it cannot be produced by
        # the executor), and the check-time relaxation must not swallow it.
        drafted = self.draft(purpose_file=None)
        path = self.temp / drafted["path"]
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("state: draft", "state: approved"), encoding="utf-8")
        with self.assertRaises(store.StoreError) as ctx:
            store.command_entry_check(argparse.Namespace())
        self.assertIn("sentinel", str(ctx.exception))

    def test_draft_defaults_source_api_version_from_the_project_file(self) -> None:
        # F-5: the old hardcoded "64.0" default silently drifted from the project's real
        # version; the default must be the project's own declaration, fail-closed.
        drafted = self.draft(purpose_file=None, source_api_version=None)
        frontmatter, _ = store.split_entry((self.temp / drafted["path"]).read_text(encoding="utf-8"))
        self.assertEqual("63.0", frontmatter["scope"]["sourceApiVersion"])
        # An explicit flag still wins…
        drafted = self.draft(source_api_version="65.0")
        frontmatter, _ = store.split_entry((self.temp / drafted["path"]).read_text(encoding="utf-8"))
        self.assertEqual("65.0", frontmatter["scope"]["sourceApiVersion"])
        # …and a project file without the key fails closed, never a stand-in literal.
        (self.temp / "sfdx-project.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(store.StoreError):
            self.draft(purpose_file=None, source_api_version=None)

    def test_customfield_draft_is_supported(self) -> None:
        drafted = self.draft(metadata_type="CustomField", full_name="HarnessAlphaCase__c.Status__c")
        frontmatter, _ = store.split_entry((self.temp / drafted["path"]).read_text(encoding="utf-8"))
        self.assertEqual("Picklist", frontmatter["typeFacts"]["type"])
        self.assertEqual([], frontmatter.get("intentionalErrors", []))

    def test_namespace_c_is_reserved(self) -> None:
        with self.assertRaises(store.StoreError):
            self.draft(namespace="c")

    def test_hand_flipped_state_without_ledger_is_quarantined(self) -> None:
        drafted = self.draft()
        path = self.temp / drafted["path"]
        text = path.read_text(encoding="utf-8").replace("state: draft", "state: approved")
        path.write_text(text, encoding="utf-8")
        lane = self.lane_of(drafted["identity"])
        self.assertEqual("not-effective", lane["lane"])

    def test_approval_toctou_pin_mismatch_rejects_chunk(self) -> None:
        drafted = self.draft()
        path = self.temp / drafted["path"]
        path.write_text(path.read_text(encoding="utf-8").replace("right queue", "wrong queue"), encoding="utf-8")
        with self.assertRaises(store.StoreError) as ctx:
            self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        self.assertIn("digest pin mismatch", str(ctx.exception))

    def test_byte_replay_of_old_approval_is_not_current(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        path = self.temp / drafted["path"]
        old_bytes = path.read_text(encoding="utf-8")
        (self.temp / "purpose.md").write_text("Corrected purpose text.", encoding="utf-8")
        redrafted = self.draft()
        self.approve([f"{redrafted['identity']}:{redrafted['reviewedContentDigest']}"])
        self.assertEqual("approved-current", self.lane_of(drafted["identity"])["lane"])
        path.write_text(old_bytes, encoding="utf-8")  # replay previously approved bytes
        lane = self.lane_of(drafted["identity"])
        self.assertEqual("not-effective", lane["lane"])  # ledger latest wins (R-01)

    def test_revocation_lane(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        store.command_entry_revoke(
            argparse.Namespace(identity=drafted["identity"], rationale="mis-approved")
        )
        self.assertEqual("revoked", self.lane_of(drafted["identity"])["lane"])

    def test_source_drift_moves_to_drifted_lane(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        flow = self.temp / "force-app/main/default/flows/HarnessAlphaRouter.flow-meta.xml"
        flow.write_text(FLOW_XML.replace("Update</recordTriggerType>", "Create</recordTriggerType>"), encoding="utf-8")
        self.assertEqual("approved-drifted", self.lane_of(drafted["identity"])["lane"])

    def test_wrong_path_copy_fails_round_trip(self) -> None:
        drafted = self.draft()
        source = self.temp / drafted["path"]
        rogue = store.ARTIFACTS_ROOT / "CustomField" / "c" / source.name
        rogue.parent.mkdir(parents=True, exist_ok=True)
        rogue.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaises(store.StoreError) as ctx:
            store.command_entry_check(argparse.Namespace())
        self.assertIn("round-trip", str(ctx.exception))

    def test_duplicate_frontmatter_keys_rejected(self) -> None:
        with self.assertRaises(store.StoreError):
            store.split_entry("---\na: 1\na: 2\n---\n\nbody\n")

    def test_alias_and_merge_keys_rejected(self) -> None:
        with self.assertRaises(store.StoreError):
            store.split_entry("---\nbase: &b {x: 1}\nother: *b\n---\n\n")

    def test_facts_digest_is_enumeration_order_invariant(self) -> None:
        base = {
            "typeFacts": {
                "processType": "Flow",
                "references": [
                    {"kind": "writes-field", "target": "B.F", "assurance": "source-exact"},
                    {"kind": "operates-on", "target": "A", "assurance": "source-exact"},
                ],
            },
            "limitations": ["b", "a"],
            "extractionCoverage": {"typeFacts": "full"},
            "assurance": {"typeFacts": "source-exact"},
        }
        reordered = json.loads(json.dumps(base))
        reordered["typeFacts"]["references"].reverse()
        reordered["limitations"].reverse()
        self.assertEqual(store.facts_digest(base), store.facts_digest(reordered))  # R-03

    def test_truncation_digest_uses_full_identity(self) -> None:
        long_a = "A" * 120 + "X"
        long_b = "A" * 120 + "Y"
        name_a = store.safe_name(long_a, f"CustomField:c:{long_a}")
        name_b = store.safe_name(long_b, f"CustomField:c:{long_b}")
        self.assertNotEqual(name_a, name_b)  # R-14
        self.assertTrue(len(name_a) <= store.SAFE_NAME_BUDGET + 9)

    def test_autolaunched_beta_family_drafts_without_trigger(self) -> None:
        # Second independent fixture family (HarnessBeta*): autolaunched, no trigger object.
        flow_dir = self.temp / "force-app/main/default/flows"
        (flow_dir / "HarnessBetaDispatch.flow-meta.xml").write_text(
            FLOW_XML.replace("HarnessAlphaRouter", "HarnessBetaDispatch")
            .replace(
                "<start>\n        <object>HarnessAlphaCase__c</object>\n"
                "        <triggerType>RecordAfterSave</triggerType>\n"
                "        <recordTriggerType>Update</recordTriggerType>\n    </start>",
                "<start></start>",
            ),
            encoding="utf-8",
        )
        drafted = self.draft(full_name="HarnessBetaDispatch")
        frontmatter, _ = store.split_entry((self.temp / drafted["path"]).read_text(encoding="utf-8"))
        self.assertNotIn("trigger", frontmatter["typeFacts"])
        self.assertEqual(1, len(frontmatter["intentionalErrors"]))

    def test_entry_review_renders_the_surface_before_approval(self) -> None:
        drafted = self.draft()
        result = self.review()
        self.assertEqual("REVIEW_READY", result["outcome"])
        artifact = self.temp / result["reviewArtifact"]
        text = artifact.read_text(encoding="utf-8")
        # The executor renders the attested body itself; the agent never authors it.
        self.assertIn("Routes alpha cases to the right queue.", text)
        self.assertIn("Attested body", text)
        self.assertIn(drafted["reviewedContentDigest"], text)
        self.assertIn("new approval", text)
        self.assertEqual([drafted["identity"]], result["classification"]["proseChanges"])
        self.assertIn(f"--entry {drafted['identity']}:{drafted['reviewedContentDigest']}", result["approveCommand"])

    def test_reviewed_command_approves_and_edits_after_review_are_rejected(self) -> None:
        drafted = self.draft()
        pins = self.review()["approveCommand"].split("--entry ")[1:]
        self.assertEqual("APPROVED", self.approve([pin.strip() for pin in pins])["outcome"])
        self.assertEqual("approved-current", self.lane_of(drafted["identity"])["lane"])
        # Re-review after a prose edit yields a different digest; the stale pin fails closed.
        path = self.temp / drafted["path"]
        path.write_text(path.read_text(encoding="utf-8").replace("right queue", "other queue"), encoding="utf-8")
        with self.assertRaises(store.StoreError):
            self.approve([pin.strip() for pin in pins])

    def test_entry_review_skips_invalid_drafts_and_reports_why(self) -> None:
        drafted = self.draft(purpose_file=None)  # facts extracted, description not authored yet
        result = self.review([drafted["identity"]])
        self.assertEqual("NOTHING_TO_REVIEW", result["outcome"])
        self.assertTrue(
            any("sentinel" in problem or "Purpose" in problem for problem in result["problems"]),
            f"the refusal must name why: {result['problems']}",
        )

    def test_entry_review_auto_chunks_past_the_prose_cap(self) -> None:
        # Plan 2026-08-09 §2.2e: exceeding the cap no longer dead-ends in CHUNK_TOO_LARGE —
        # the sorted draft list is cut into ≤cap rounds, each with its own artifact and
        # digest-pinned approve command. The cap itself (25 full bodies per human round)
        # is unchanged; only the manual selection of round boundaries is removed.
        self.draft()
        self.draft(metadata_type="CustomField", full_name="HarnessAlphaCase__c.Status__c")
        saved = store.PROSE_CHUNK_LIMIT
        store.PROSE_CHUNK_LIMIT = 1
        self.addCleanup(setattr, store, "PROSE_CHUNK_LIMIT", saved)
        result = self.review()
        self.assertEqual("REVIEW_READY_CHUNKED", result["outcome"])
        self.assertEqual(2, result["entries"])
        self.assertEqual(2, len(result["chunks"]))
        for chunk in result["chunks"]:
            self.assertEqual(1, chunk["entries"])
            self.assertEqual([], chunk["capViolations"])
            self.assertTrue((self.temp / chunk["reviewArtifact"]).is_file())
            self.assertEqual(1, chunk["approveCommand"].count("--entry "))

    def test_auto_chunked_approve_commands_actually_approve(self) -> None:
        self.draft()
        self.draft(metadata_type="CustomField", full_name="HarnessAlphaCase__c.Status__c")
        saved = store.PROSE_CHUNK_LIMIT
        store.PROSE_CHUNK_LIMIT = 1
        self.addCleanup(setattr, store, "PROSE_CHUNK_LIMIT", saved)
        result = self.review()
        for chunk in result["chunks"]:
            pins = [pin.strip() for pin in chunk["approveCommand"].split("--entry ")[1:]]
            self.assertEqual("APPROVED", self.approve(pins)["outcome"])

    def test_facts_only_reapproval_is_classified_separately(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        flow = self.temp / "force-app/main/default/flows/HarnessAlphaRouter.flow-meta.xml"
        flow.write_text(FLOW_XML.replace("<status>Active</status>", "<status>Draft</status>"), encoding="utf-8")
        redrafted = self.draft()  # same prose, regenerated facts
        result = self.review([redrafted["identity"]])
        self.assertEqual([redrafted["identity"]], result["classification"]["factsOnly"])
        self.assertEqual([], result["classification"]["proseChanges"])

    def test_apex_and_validation_rule_profiles_draft_and_approve(self) -> None:
        apex = self.draft(metadata_type="ApexClass", full_name="HarnessAlphaService")
        front, _ = store.split_entry((self.temp / apex["path"]).read_text(encoding="utf-8"))
        self.assertEqual("ApexClass", front["typeFacts"]["kind"])
        self.assertEqual("64.0", front["typeFacts"]["apiVersion"])
        self.assertIn("references", front["typeFacts"])
        # Heuristic Apex lineage must not be laundered as exact.
        self.assertTrue(all("assurance" in edge for edge in front["typeFacts"]["references"]))
        self.assertEqual([], front.get("intentionalErrors", []))

        rule = self.draft(
            metadata_type="ValidationRule", full_name="HarnessAlphaCase__c.Status_Required"
        )
        front, _ = store.split_entry((self.temp / rule["path"]).read_text(encoding="utf-8"))
        self.assertEqual("HarnessAlphaCase__c", front["typeFacts"]["object"])
        self.assertTrue(front["typeFacts"]["active"])
        # The rule itself must be IN the entry — an entry saying only "this rule has a
        # condition" cannot answer what the rule enforces.
        declared = front["typeFacts"]["errorCatalog"][0]
        self.assertEqual("ISBLANK(Status__c)", declared["condition"])
        self.assertEqual("Status is required.", declared["errorMessage"])
        # ...while staying out of intentionalErrors, which is FlowCustomError-only.
        self.assertEqual([], front.get("intentionalErrors", []))

        self.approve([f"{apex['identity']}:{apex['reviewedContentDigest']}",
                      f"{rule['identity']}:{rule['reviewedContentDigest']}"])
        for drafted in (apex, rule):
            self.assertEqual("approved-current", self.lane_of(drafted["identity"])["lane"])

    def test_every_profile_has_a_schema_and_an_adapter(self) -> None:
        for metadata_type, profile in store.PROFILES.items():
            with self.subTest(metadataType=metadata_type):
                self.assertIn(metadata_type, store.ADAPTERS)
                self.assertTrue((self.temp / "schemas" / profile["schema"]).is_file())

    # --- remaining adversarial-review evals (R-09..R-24) ---------------------------

    def test_r09_reparse_point_under_knowledge_fails_closed(self) -> None:
        target = self.temp / "elsewhere"
        target.mkdir()
        link = self.temp / ".ai/knowledge/artifacts-link"
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError) as error:  # Windows without developer mode
            self.skipTest(f"symlink creation unavailable on this platform: {error}")
        with self.assertRaises(store.StoreError) as ctx:
            store.assert_no_reparse_points()
        self.assertIn("reparse", str(ctx.exception))

    def test_r10_sensitivity_flip_after_approval_invalidates(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        path = self.temp / drafted["path"]
        path.write_text(
            path.read_text(encoding="utf-8").replace("sensitivity: internal-sanitized", "sensitivity: public"),
            encoding="utf-8",
        )
        self.assertEqual("not-effective", self.lane_of(drafted["identity"])["lane"])

    def test_r11_provenance_tamper_is_detected_against_the_ledger(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        path = self.temp / drafted["path"]
        path.write_text(
            path.read_text(encoding="utf-8").replace("Reviewer Person", "Someone Else"),
            encoding="utf-8",
        )
        lane = self.lane_of(drafted["identity"])
        self.assertEqual("not-effective", lane["lane"])
        self.assertTrue(any("provenance" in problem for problem in lane["problems"]))

    def test_r21_interrupted_chunk_leaves_only_completed_stamps_effective(self) -> None:
        first = self.draft()
        second = self.draft(metadata_type="CustomField", full_name="HarnessAlphaCase__c.Status__c")
        original_write = store.atomic_write
        calls = {"count": 0}

        def failing_write(path, text):
            calls["count"] += 1
            if calls["count"] > 1:
                raise OSError("simulated crash mid-chunk")
            return original_write(path, text)

        store.atomic_write = failing_write
        self.addCleanup(setattr, store, "atomic_write", original_write)
        with self.assertRaises(OSError):
            self.approve(
                [
                    f"{first['identity']}:{first['reviewedContentDigest']}",
                    f"{second['identity']}:{second['reviewedContentDigest']}",
                ]
            )
        store.atomic_write = original_write
        lanes = {entry["identity"]: entry["lane"] for entry in store.command_entry_status(argparse.Namespace(identity=None))["entries"]}
        # The journaled ledger records only what completed; the rest stays draft.
        self.assertEqual(1, sum(1 for lane in lanes.values() if lane == "approved-current"))
        self.assertEqual(1, sum(1 for lane in lanes.values() if lane == "draft"))
        self.assertEqual(1, len(store.read_ledger()))

    def test_r23_profile_patch_bump_changes_no_lane(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        path = self.temp / drafted["path"]
        path.write_text(
            path.read_text(encoding="utf-8").replace("version: 1.0.0", "version: 1.0.9"),
            encoding="utf-8",
        )
        # reviewedContentDigest binds the profile MAJOR only, so a patch bump is a no-op.
        self.assertEqual("approved-current", self.lane_of(drafted["identity"])["lane"])

    def test_r24_body_with_dashes_and_fenced_yaml_has_one_boundary(self) -> None:
        body = "## Purpose\n\nSee below.\n\n---\n\n```yaml\nkey: value\n---\nother: value\n```\n"
        text = "---\nschemaVersion: 1\n---\n\n" + body
        frontmatter, parsed = store.split_entry(text)
        self.assertEqual({"schemaVersion": 1}, frontmatter)
        self.assertIn("```yaml", parsed)
        self.assertIn("other: value", parsed)
        self.assertEqual(store.semantics_digest(parsed), store.semantics_digest(parsed + "\n"))

    def test_yaml_11_bool_landmines_stay_strings(self) -> None:
        frontmatter, _ = store.split_entry("---\nvalue: NO\nother: 'yes'\n---\n\n")
        self.assertEqual("NO", frontmatter["value"])


if __name__ == "__main__":
    unittest.main()


class CrossPlatformDeterminismTests(KnowledgeStoreFixture):
    """Windows-sensitive behavior. CI runs this suite on ubuntu-latest AND windows-latest,
    so these assertions are the cross-platform gate the review asked for (R-20 partial:
    correctness on Windows is covered here; Windows *latency* still needs a manual run)."""

    def test_entry_bytes_are_identical_across_repeated_drafts(self) -> None:
        first = self.draft()
        first_bytes = (self.temp / first["path"]).read_bytes()
        second = self.draft()
        self.assertEqual(first_bytes, (self.temp / second["path"]).read_bytes())
        self.assertEqual(first["reviewedContentDigest"], second["reviewedContentDigest"])

    def test_entries_are_written_with_lf_regardless_of_platform(self) -> None:
        drafted = self.draft()
        raw = (self.temp / drafted["path"]).read_bytes()
        self.assertNotIn(b"\r\n", raw)  # os.linesep must never leak into a digested file

    def test_crlf_and_lf_bodies_share_one_semantics_digest(self) -> None:
        lf = "## Purpose\n\nRoutes cases.\n"
        crlf = "## Purpose\r\n\r\nRoutes cases.\r\n"
        self.assertEqual(store.semantics_digest(lf), store.semantics_digest(crlf))

    def test_case_fold_collision_is_refused_not_silently_merged(self) -> None:
        drafted = self.draft()
        path = self.temp / drafted["path"]
        twin = path.with_name(path.name.upper())
        if twin.exists():  # case-insensitive filesystem: the collision is physical
            self.skipTest("filesystem is case-insensitive; collision cannot be staged")
        twin.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaises(store.StoreError) as ctx:
            store.command_entry_check(argparse.Namespace())
        self.assertTrue(
            "case-fold" in str(ctx.exception) or "round-trip" in str(ctx.exception)
        )

    def test_windows_reserved_device_names_get_a_digest_suffix(self) -> None:
        for reserved in ("CON", "PRN", "AUX", "NUL", "COM1", "LPT9"):
            with self.subTest(name=reserved):
                stem = store.safe_name(reserved, f"Flow:c:{reserved}")
                self.assertNotEqual(reserved.casefold(), stem.casefold())
                self.assertTrue(stem.upper().startswith(reserved))

    def test_identity_normalization_is_nfkc_and_path_budget_is_enforced(self) -> None:
        # Composed and decomposed spellings must resolve to one identity, not two files.
        composed = store.safe_name("Zażółć__c", "CustomField:c:Zażółć__c")
        decomposed = store.safe_name("Zaz\u0307o\u0301łc\u0301__c", "CustomField:c:Zaz\u0307o\u0301łc\u0301__c")
        self.assertTrue(composed and decomposed)
        # A very long API name is protected by truncation, so the path stays in budget...
        long_path = store.entry_path("Flow", None, "X" * 400)
        self.assertLessEqual(len(str(long_path.relative_to(store.ROOT))), store.PATH_BUDGET)
        # ...and the budget itself is a real backstop, not decoration.
        saved = store.PATH_BUDGET
        store.PATH_BUDGET = 20
        self.addCleanup(setattr, store, "PATH_BUDGET", saved)
        with self.assertRaises(store.StoreError) as ctx:
            store.entry_path("Flow", None, "X" * 400)
        self.assertIn("budget", str(ctx.exception))

    def test_atomic_write_replaces_an_existing_file(self) -> None:
        # os.replace over an existing target is the Windows-fragile operation in the writer.
        path = self.temp / "atomic-target.md"
        store.atomic_write(path, "first\n")
        store.atomic_write(path, "second\n")
        self.assertEqual("second\n", path.read_text(encoding="utf-8"))
        self.assertFalse(path.with_suffix(".tmp").exists())


class SourceFreshnessAxisTests(KnowledgeStoreFixture):
    """Approval and source freshness are two axes (owner decisions D1–D3, 2026-08-11).

    The point every case here defends: an edit to the source moves an entry along the freshness
    axis only. It never un-approves it. A source fragment that is GONE is the exception, and it
    is deliberately not on the freshness axis at all — there is no evidence left to be fresh or
    stale about, so the entry leaves the effective set entirely."""

    def approved(self) -> dict:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        return drafted

    @property
    def flow(self) -> Path:
        return self.temp / "force-app/main/default/flows/HarnessAlphaRouter.flow-meta.xml"

    def test_untouched_source_is_current_and_carries_no_advisory(self) -> None:
        lane = self.lane_of(self.approved()["identity"])
        self.assertEqual("approved-current", lane["lane"])
        self.assertTrue(lane["effective"])
        self.assertEqual("current", lane["freshness"])
        self.assertEqual([], lane["advisories"])

    def test_changed_source_stays_effective_and_names_the_path(self) -> None:
        identity = self.approved()["identity"]
        self.flow.write_text(
            FLOW_XML.replace("<status>Active</status>", "<status>Draft</status>"), encoding="utf-8"
        )
        lane = self.lane_of(identity)
        self.assertEqual("approved-drifted", lane["lane"])
        self.assertTrue(lane["effective"])  # D1: drift never revokes a human approval
        self.assertEqual("drifted", lane["freshness"])
        self.assertEqual(["SOURCE_DRIFT"], [item["code"] for item in lane["advisories"]])
        # The advisory has to say WHICH file moved; a bare flag sends the reader hunting.
        self.assertEqual(
            ["force-app/main/default/flows/HarnessAlphaRouter.flow-meta.xml"],
            lane["advisories"][0]["paths"],
        )

    def test_missing_source_is_not_effective_with_a_machine_readable_code(self) -> None:
        identity = self.approved()["identity"]
        self.flow.unlink()
        lane = self.lane_of(identity)
        # D3: this is an evidence failure, NOT drift. The distinction is the whole test.
        self.assertEqual("not-effective", lane["lane"])
        self.assertFalse(lane["effective"])
        self.assertEqual(["SOURCE_FRAGMENT_MISSING"], [item["code"] for item in lane["problemCodes"]])
        self.assertEqual([], lane["advisories"])
        self.assertNotEqual("drifted", lane["freshness"])

    def test_unreadable_source_is_not_effective_and_distinct_from_missing(self) -> None:
        identity = self.approved()["identity"]
        # The file exists — it just cannot be read. Reported as its own code, because
        # "someone deleted it" and "the checkout is broken" are different repairs.
        self.assertTrue(self.flow.exists())
        with unittest.mock.patch(
            "scripts.force_app_knowledge.file_digest", side_effect=PermissionError("denied")
        ):
            lane = self.lane_of(identity)
        self.assertEqual("not-effective", lane["lane"])
        self.assertFalse(lane["effective"])
        self.assertEqual(
            ["SOURCE_FRAGMENT_UNREADABLE"], [item["code"] for item in lane["problemCodes"]]
        )

    def test_a_drifted_envelope_is_valid_and_can_support_safe(self) -> None:
        drafted = self.approved()
        self.flow.write_text(
            FLOW_XML.replace("<status>Active</status>", "<status>Draft</status>"), encoding="utf-8"
        )
        envelope = self.temp / "output" / "drifted-envelope.json"
        envelope.parent.mkdir(parents=True, exist_ok=True)
        envelope.write_text(
            json.dumps({"entryRefs": [{"entryId": drafted["identity"]}]}), encoding="utf-8"
        )
        report = store.command_entry_verify_citations(
            argparse.Namespace(envelope=str(envelope), entry_ref=[])
        )
        # The gate consumers read is `invalid`. Drift must not touch it, or every design
        # grounded in a slightly-edited Flow silently loses its SAFE verdict.
        self.assertEqual(0, report["counts"]["invalid"])
        self.assertEqual(1, report["counts"]["ok"])
        self.assertEqual(1, report["counts"]["advisory"])

    def test_a_missing_source_citation_is_invalid_not_an_advisory(self) -> None:
        # The negative twin of the case above: the two must never collapse into each other.
        drafted = self.approved()
        self.flow.unlink()
        verdict = store.verify_entry_citations(self.temp, [{"entryId": drafted["identity"]}])[0]
        self.assertEqual("not-effective", verdict["verdict"])
        self.assertEqual("invalid", verdict["severity"])
        self.assertFalse(verdict["effective"])

    def test_effectiveness_has_exactly_one_definition(self) -> None:
        # Acceptance criterion 1: one constant decides. If a future lane is added to the
        # enum without a deliberate decision here, it is non-effective by default.
        self.assertEqual({"approved-current", "approved-drifted"}, set(store.EFFECTIVE_ENTRY_LANES))
        for lane in ("draft", "revoked", "not-effective", None):
            self.assertFalse(store.is_effective_entry_lane(lane))


class EntryCitationVerificationTests(KnowledgeStoreFixture):
    """Entry citation verdicts live in the store (v1 retirement P0), not the registry."""

    def test_verdicts_track_the_entry_lifecycle(self) -> None:
        drafted = self.draft()
        ref = {"entryId": drafted["identity"], "reviewedContentDigest": drafted["reviewedContentDigest"]}
        self.assertEqual("not-approved", store.verify_entry_citations(self.temp, [ref])[0]["verdict"])

        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        self.assertEqual("current", store.verify_entry_citations(self.temp, [ref])[0]["verdict"])

        flow = self.temp / "force-app/main/default/flows/HarnessAlphaRouter.flow-meta.xml"
        flow.write_text(FLOW_XML.replace("<status>Active</status>", "<status>Draft</status>"), encoding="utf-8")
        drifted = store.verify_entry_citations(self.temp, [ref])[0]
        self.assertEqual("drifted", drifted["verdict"])
        # Drift is a disclosure, not a demotion (owner decision D2, 2026-08-11): the citation
        # stays effective and severity-ok, and it carries the changed path so the consumer can
        # say WHICH source moved. The verdict string is unchanged so existing branches survive.
        self.assertEqual("ok", drifted["severity"])
        self.assertTrue(drifted["effective"])
        self.assertEqual(["SOURCE_DRIFT"], [item["code"] for item in drifted["advisories"]])
        self.assertIn(
            "force-app/main/default/flows/HarnessAlphaRouter.flow-meta.xml",
            drifted["advisories"][0]["paths"],
        )
        # The old text demanded re-approval before citing. Nothing may say that again.
        self.assertNotIn("re-approve", drifted["reason"].lower())

        store.command_entry_revoke(argparse.Namespace(identity=drafted["identity"], rationale="x"))
        self.assertEqual("revoked", store.verify_entry_citations(self.temp, [ref])[0]["verdict"])

    def test_missing_and_mismatched_citations_are_invalid(self) -> None:
        self.assertEqual(
            "missing", store.verify_entry_citations(self.temp, [{"entryId": "Flow:c:Nope"}])[0]["verdict"]
        )
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        stale = {"entryId": drafted["identity"], "reviewedContentDigest": "sha256:" + "0" * 64}
        verdict = store.verify_entry_citations(self.temp, [stale])[0]
        self.assertEqual("digest-mismatch", verdict["verdict"])
        self.assertEqual("invalid", verdict["severity"])

    def test_cli_requires_exactly_one_source_and_reads_envelopes(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        for bad in (
            argparse.Namespace(envelope=None, entry_ref=[]),
            argparse.Namespace(envelope="x.json", entry_ref=["Flow:c:Nope"]),
        ):
            with self.assertRaises(store.StoreError):
                store.command_entry_verify_citations(bad)
        envelope = self.temp / "output" / "envelope.json"
        envelope.parent.mkdir(parents=True, exist_ok=True)
        envelope.write_text(
            json.dumps(
                {
                    "entryRefs": [
                        {"entryId": drafted["identity"], "reviewedContentDigest": drafted["reviewedContentDigest"]},
                        "Flow:c:Nope",
                    ]
                }
            ),
            encoding="utf-8",
        )
        report = store.command_entry_verify_citations(
            argparse.Namespace(envelope=str(envelope), entry_ref=[])
        )
        self.assertEqual(2, report["citationCount"])
        self.assertEqual({"ok": 1, "warning": 0, "advisory": 0, "invalid": 1}, report["counts"])
        bare = store.command_entry_verify_citations(
            argparse.Namespace(envelope=None, entry_ref=[drafted["identity"]])
        )
        self.assertEqual("current", bare["citations"][0]["verdict"])
        with self.assertRaises(store.StoreError):
            store.command_entry_verify_citations(
                argparse.Namespace(envelope="/etc/hosts", entry_ref=[])
            )


    def test_entry_coverage_separates_gaps_from_unprofiled_types(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        report = store.command_entry_coverage(argparse.Namespace())
        self.assertEqual({"approved-current": 1}, report["lanes"]["Flow"])
        # CustomField/ValidationRule sources exist without entries -> real gaps
        self.assertIn("CustomField", report["missingEntryCounts"])
        # A type with no profile is listed as unprofiled, never as a coverage gap
        self.assertNotIn("CustomObject", report["missingEntryCounts"])


class SharedFactsProjectionTests(KnowledgeStoreFixture):
    """`entry-draft` and the read-only facts analyzer derive facts through ONE function.

    Phase 2 compares an approved entry's `factsDigest` against a fresh extraction of the same
    component. If the analyzer re-implemented the ~15 lines that turn a collector component into
    `{typeFacts, intentionalErrors, limitations, extractionCoverage, assurance}`, every
    disagreement between the two copies would be reported forever as artifact drift — the exact
    silent divergence phase 2 exists to detect, reproduced inside the detector. So there is one
    projection, and these tests pin both halves of it: draft output IS the helper's output, and
    the helper's output for the fixture corpus is byte-stable.

    GOLDEN_FACTS_DIGESTS were measured on the commit BEFORE the shared helper existed, by
    drafting the same four fixtures against the pre-refactor code and diffing the rendered
    entries: the refactor changed no byte of any draft. They are pinned here so a later edit to
    the projection cannot silently move what an approved corpus would be compared against.
    """

    GOLDEN_FACTS_DIGESTS = {
        "Flow:c:HarnessAlphaRouter":
            "sha256:acb434aaed85590cf9c2f37e14fd9c8c92fd1f3917ea9e4c29fd15af8392bdcd",
        "CustomField:c:HarnessAlphaCase__c.Status__c":
            "sha256:e41ff746ae5967e5e7a8ad609031796628d9262ed4202fffe31ff38e0a7116da",
        "ApexClass:c:HarnessAlphaService":
            "sha256:290eb2ee0a3ad29322e13917aaf691d37f17f7611659c0b53085193b48951e16",
        "ValidationRule:c:HarnessAlphaCase__c.Status_Required":
            "sha256:9f8038ba9e52d242862dba9d2b8aeb61dcdb3ce913139d9b43eaff5a38f8b869",
    }
    CASES = (
        ("Flow", "HarnessAlphaRouter"),
        ("CustomField", "HarnessAlphaCase__c.Status__c"),
        ("ApexClass", "HarnessAlphaService"),
        ("ValidationRule", "HarnessAlphaCase__c.Status_Required"),
    )

    def drafted_facts(self, metadata_type: str, full_name: str):
        result = self.draft(metadata_type=metadata_type, full_name=full_name)
        front, body = store.split_entry((store.ROOT / result["path"]).read_text(encoding="utf-8"))
        return result, front, body

    def test_draft_facts_are_exactly_the_shared_projection(self) -> None:
        for metadata_type, full_name in self.CASES:
            with self.subTest(metadataType=metadata_type):
                _result, front, _body = self.drafted_facts(metadata_type, full_name)
                component = store.collector_component(metadata_type, full_name)
                derived = store.derive_structured_facts(metadata_type, component, limitations=[])
                self.assertEqual(derived["typeFacts"], front["typeFacts"])
                self.assertEqual(derived["extractionCoverage"], front["extractionCoverage"])
                self.assertEqual(derived["assurance"], front["assurance"])
                self.assertEqual(derived["limitations"], front["limitations"])
                self.assertEqual(
                    derived["intentionalErrors"], front.get("intentionalErrors", []),
                    "the Flow adapter's intentional errors must survive the shared projection",
                )
                # The digest boundary itself, not only the fields it is built from.
                self.assertEqual(store.facts_digest(front), store.facts_digest(derived))

    def test_the_projection_digests_are_the_pre_refactor_digests(self) -> None:
        for metadata_type, full_name in self.CASES:
            with self.subTest(metadataType=metadata_type):
                result, front, body = self.drafted_facts(metadata_type, full_name)
                self.assertEqual(
                    self.GOLDEN_FACTS_DIGESTS[result["identity"]], store.facts_digest(front)
                )
                # The reviewed digest closes over factsDigest, so an unchanged facts digest with
                # a moved reviewed digest would mean the refactor leaked into semantics.
                self.assertEqual(
                    result["reviewedContentDigest"], store.reviewed_content_digest(front, body)
                )

    def test_a_flow_keeps_its_intentional_errors_and_their_assurance(self) -> None:
        component = store.collector_component("Flow", "HarnessAlphaRouter")
        derived = store.derive_structured_facts("Flow", component, limitations=[])
        [error] = derived["intentionalErrors"]
        self.assertEqual("flow-custom-error", error["kind"])
        self.assertEqual("customErrors", error["originTag"])
        self.assertEqual("Block_Discount", error["elementApiName"])
        # Presence of intentional errors is what adds the second coverage and assurance key;
        # dropping that step would weaken a digest-bound marker without moving any fact.
        self.assertEqual("full", derived["extractionCoverage"]["intentionalErrors"])
        self.assertEqual("source-exact", derived["assurance"]["intentionalErrors"])

    def test_truncated_extraction_still_marks_the_section_partial(self) -> None:
        # Coverage is digest-bound (contract §5.1): a full->partial regression is a material
        # weakening, so the truncation aggregates must keep deciding it inside the shared helper.
        for flag in ("referencesTruncated", "factsTruncated"):
            with self.subTest(flag=flag):
                component = {"metadataType": "CustomField", "facts": {"label": "L", flag: True}}
                derived = store.derive_structured_facts("CustomField", component)
                self.assertEqual("partial", derived["extractionCoverage"]["typeFacts"])
        clean = store.derive_structured_facts(
            "CustomField", {"metadataType": "CustomField", "facts": {"label": "L"}}
        )
        self.assertEqual("full", clean["extractionCoverage"]["typeFacts"])

    def test_limitations_are_carried_through_not_invented(self) -> None:
        """Limitations are human-governed and inside `factsDigest` — the collector cannot
        derive them. An analyzer that defaulted them to `[]` would report every entry whose
        reviewer wrote one as facts-changed, which is a false positive with a human cause."""

        component = store.collector_component("CustomField", "HarnessAlphaCase__c.Status__c")
        kept = store.derive_structured_facts(
            component=component, metadata_type="CustomField", limitations=["Picklist values not read."]
        )
        self.assertEqual(["Picklist values not read."], kept["limitations"])
        self.assertEqual([], store.derive_structured_facts("CustomField", component)["limitations"])

    def test_the_projection_is_pure(self) -> None:
        """No filesystem, no mutation of the caller's component. Both were real risks: the
        draft path this was lifted from reads source and writes an entry around these lines,
        and an adapter that returned an alias of the component's own lists would let a caller's
        later edit reach back into the inventory the analyzer is iterating."""

        component = store.collector_component("Flow", "HarnessAlphaRouter")
        before = copy.deepcopy(component)
        with unittest.mock.patch("builtins.open", side_effect=AssertionError("read the filesystem")):
            derived = store.derive_structured_facts("Flow", component, limitations=["keep me"])
        self.assertEqual(before, component, "the projection mutated the component it was given")
        derived["typeFacts"]["references"] = []
        derived["limitations"].append("mutated")
        self.assertEqual(before, component, "the result aliases the component's own containers")

    def test_an_unprofiled_type_is_refused_rather_than_projected_empty(self) -> None:
        with self.assertRaises(store.StoreError) as raised:
            store.derive_structured_facts("NotAType", {"facts": {}})
        self.assertIn("unsupported metadata type", str(raised.exception))


class AdapterFaithfulnessTests(unittest.TestCase):
    """An entry must carry what the collector extracted.

    Hand-listing which facts to KEEP silently lost real content: validation rules arrived as
    `conditionPresent: true` with no formula, fields lost their picklist values and rollup
    definitions, Apex lost its sharing model. Adapters now pass everything through, and any
    fact a profile does not declare fails validation loudly instead of vanishing.
    """

    def test_adapters_drop_nothing_that_is_not_declared_and_justified(self) -> None:
        for metadata_type, adapter in store.ADAPTERS.items():
            if metadata_type == "Flow":
                continue  # bespoke adapter; its exclusions are asserted below
            with self.subTest(metadataType=metadata_type):
                facts = {"alpha": 1, "beta": "two", "gamma": ["three"]}
                carried, _errors, _assurance = adapter({"facts": facts, "metadataType": metadata_type})
                for key in facts:
                    self.assertIn(key, carried, f"{metadata_type} silently dropped {key}")

    def test_every_flow_exclusion_states_a_reason(self) -> None:
        for metadata_type, exclusions in store.FACT_EXCLUSIONS.items():
            for key, reason in exclusions.items():
                with self.subTest(metadataType=metadata_type, fact=key):
                    self.assertTrue(reason.strip(), f"{metadata_type}.{key} is excluded without a reason")

    def test_numeric_xml_text_is_normalized_but_other_text_is_verbatim(self) -> None:
        adapter = store.ADAPTERS["CustomField"]
        carried, _, _ = adapter({"facts": {"length": "18", "label": "18 characters", "object": "X__c"}})
        self.assertEqual(18, carried["length"])
        self.assertEqual("18 characters", carried["label"])

    def test_validation_rule_entry_carries_the_rule_itself(self) -> None:
        component = {
            "metadataType": "ValidationRule",
            "facts": {
                "object": "ClientProfile__c",
                "active": True,
                "errorDisplayField": "Health_Score__c",
                "errorCatalog": [
                    {
                        "component": "Health_Score_In_Range",
                        "kind": "validation-rule",
                        "condition": "NOT(ISBLANK(Health_Score__c))",
                        "errorMessage": "Health Score must be between 0 and 100.",
                    }
                ],
            },
        }
        carried, errors, _ = store.ADAPTERS["ValidationRule"](component)
        self.assertEqual("NOT(ISBLANK(Health_Score__c))", carried["errorCatalog"][0]["condition"])
        self.assertIn("between 0 and 100", carried["errorCatalog"][0]["errorMessage"])
        # A validation rule's message is not a Flow Custom Error and never enters that index.
        self.assertEqual([], errors)

    def test_a_custom_error_behind_a_decision_renders_its_guard_path(self) -> None:
        """The collector emits `paths` as paths of hop OBJECTS, not of strings.

        `" -> ".join(path)` raised `TypeError: sequence item 0: expected str instance, dict found`
        on the first real Flow whose custom error sat behind a decision — an unhandled crash, so
        the entry could not be drafted at all. Every fixture Flow put its error on the trigger
        path with no decision above it, which is why 80 real components found this and the pilot
        did not."""

        component = {
            "metadataType": "Flow",
            "facts": {
                "processType": "AutoLaunchedFlow",
                "status": "Active",
                "errorCatalog": [
                    {
                        "component": "Invalid_Class_Change",
                        "kind": "custom-error",
                        "errorMessage": "This status change is not allowed.",
                        "triggerContext": "Service_Request__c / CreateAndUpdate / RecordBeforeSave",
                        "paths": [
                            [{"decision": "Validate_Status_Change", "default": True}],
                            [
                                {"decision": "Route_By_Type", "outcome": "Escalated",
                                 "outcomeLabel": "Escalated ticket"},
                                {"decision": "Validate_Status_Change", "outcome": "Blocked"},
                            ],
                        ],
                    }
                ],
            },
        }
        _carried, errors, _assurance = store.ADAPTERS["Flow"](component)
        self.assertEqual(1, len(errors))
        self.assertEqual(
            [
                "Validate_Status_Change [default]",
                "Route_By_Type [Escalated ticket] -> Validate_Status_Change [Blocked]",
            ],
            errors[0]["reachability"]["decisionGuards"],
        )

    def test_an_unrecognised_decision_hop_degrades_instead_of_raising(self) -> None:
        # A guard string is disclosure; losing the whole entry to gain punctuation is the wrong
        # trade, so an unexpected hop shape falls back rather than crashing the draft.
        self.assertEqual("", store.render_decision_path([{"unexpected": "shape"}]))
        self.assertEqual("A -> B", store.render_decision_path(
            [{"decision": "A"}, {"decision": "B"}]
        ))
        self.assertEqual("not-a-path", store.render_decision_path("not-a-path"))


class EdgeAssuranceTests(unittest.TestCase):
    """A kind-level heuristic must never be stored as source-exact.

    The collector sets its per-edge `heuristic` flag only for kinds that are heuristic
    *sometimes* (`queries-object` is structural from Flow XML, regex-derived from Apex). Reading
    only that flag meant kinds that are heuristic *always* — object-token, invokes-class,
    var-field-ref, soql-field — were stored source-exact: 414 of 595 edges in a 189-component
    probe corpus. The marker is inside factsDigest, so a human approved the false claim, and
    SAFE-CLAIM-001 v2 would then ground a work record on a regex match against a comment.
    """

    def test_kind_level_heuristics_are_never_stored_as_source_exact(self) -> None:
        component = {
            "metadataType": "ApexClass",
            "facts": {},
            "references": [
                {"kind": kind, "target": "Whatever__c"}
                for kind in sorted(relation_kinds.HEURISTIC_REF_KINDS)
            ],
        }
        carried, _errors, assurance = store.ADAPTERS["ApexClass"](component)
        for edge in carried["references"]:
            with self.subTest(kind=edge["kind"]):
                self.assertEqual(relation_kinds.SOURCE_DERIVED_HEURISTIC, edge["assurance"])
        self.assertEqual(relation_kinds.SOURCE_DERIVED_HEURISTIC, assurance["typeFacts"])

    def test_structural_kinds_stay_exact_unless_the_collector_flags_the_edge(self) -> None:
        component = {
            "metadataType": "ApexClass",
            "facts": {},
            "references": [
                {"kind": "operates-on", "target": "A__c"},
                # queries-object is structural from Flow XML and heuristic from an Apex regex,
                # so the per-edge flag carries what the kind alone cannot.
                {"kind": "queries-object", "target": "B__c"},
                {"kind": "queries-object", "target": "C__c", "heuristic": True},
            ],
        }
        carried, _errors, _assurance = store.ADAPTERS["ApexClass"](component)
        by_target = {edge["target"]: edge["assurance"] for edge in carried["references"]}
        self.assertEqual(relation_kinds.SOURCE_EXACT, by_target["A__c"])
        self.assertEqual(relation_kinds.SOURCE_EXACT, by_target["B__c"])
        self.assertEqual(relation_kinds.SOURCE_DERIVED_HEURISTIC, by_target["C__c"])

    def test_flow_edges_use_the_same_rule_as_every_other_type(self) -> None:
        # The Flow adapter is bespoke and derived assurance independently, which is exactly how
        # two implementations of one rule drift apart.
        carried, _errors, assurance = store.flow_type_facts(
            {"facts": {"processType": "AutoLaunchedFlow", "status": "Active"},
             "references": [{"kind": "launches-flow", "target": "Other"}]}
        )
        self.assertEqual(
            relation_kinds.SOURCE_DERIVED_HEURISTIC, carried["references"][0]["assurance"]
        )
        self.assertEqual(relation_kinds.SOURCE_DERIVED_HEURISTIC, assurance["typeFacts"])

    def test_every_declared_kind_resolves_to_a_declared_assurance(self) -> None:
        for kind in sorted(relation_kinds.ALL_REF_KINDS):
            with self.subTest(kind=kind):
                self.assertIn(
                    relation_kinds.edge_assurance(kind),
                    (relation_kinds.SOURCE_EXACT, relation_kinds.SOURCE_DERIVED_HEURISTIC),
                )


class ProfileSchemaCoverageTests(unittest.TestCase):
    """Every fact an adapter carries must be declared by its profile schema.

    typeFacts is additionalProperties:false, so an undeclared fact does not degrade — it fails
    the draft outright. Six such facts shipped undetected (summaryFilterFields,
    lookupFilterPresent, lookupFilterFields, externalSharingModel, compactLayoutAssignment,
    picklistScopes) because AdapterFaithfulnessTests proves pass-through but never validates the
    result against the schema that has to accept it.
    """

    SAMPLES = {
        "CustomField": {
            "object": "A__c", "type": "Summary", "summaryOperation": "sum",
            "summaryForeignKey": "B__c.A__c", "summarizedField": "B__c.Hours__c",
            "summaryFilterFields": ["B__c.Active__c"], "lookupFilterPresent": True,
            "lookupFilterFields": ["B__c.Status__c"],
        },
        "CustomObject": {
            "objectKind": "custom", "sharingModel": "ReadWrite",
            "externalSharingModel": "Private", "compactLayoutAssignment": "SYSTEM",
        },
        "RecordType": {
            "object": "A__c", "active": True,
            "picklistScopes": [{"picklist": "Status__c", "valueCount": 3, "defaults": ["New"]}],
        },
        "Flow": {
            "processType": "AutoLaunchedFlow", "status": "Active",
            "object": "A__c", "triggerType": "RecordAfterSave", "recordTriggerType": "Update",
            "variables": [
                {"name": "record", "dataType": "SObject", "objectType": "A__c",
                 "isInput": True, "isOutput": False, "isCollection": False}
            ],
            "dataOperations": [{"operation": "update", "object": "A__c", "element": "Set_Status"}],
            "errorCatalog": [
                {"kind": "custom-error", "component": "Block_Discount",
                 "componentLabel": "Block Discount", "errorMessage": "Discount too high: $Label.Cap",
                 "resolvedErrorMessage": "Discount too high: 20%",
                 "isFieldError": True, "fieldSelection": "Status__c",
                 "triggerContext": "after-save", "paths": [["Decision", "Yes"]],
                 "pathsTruncated": True}
            ],
        },
        "ApexClass": {
            "declarationKind": "class", "sharingModel": "with sharing",
            "superclass": "BaseHandler", "interfaces": ["Queueable"], "isTest": False,
            "annotations": ["@AuraEnabled"], "description": "Routes alpha cases.",
            "apiVersion": "64.0", "status": "Active", "soqlObjects": ["A__c"],
            "dmlOperations": ["update"], "dmlTargets": {"A__c": ["update"]},
        },
        "ApexTrigger": {
            "object": "A__c", "events": ["after update"], "annotations": [],
            "apiVersion": "64.0", "status": "Active", "soqlObjects": ["A__c"],
            "dmlOperations": ["insert"], "dmlTargets": {"B__c": ["insert"]},
            "description": "Delegates to the handler.",
        },
        "ValidationRule": {
            "object": "A__c", "active": True, "errorDisplayField": "Status__c",
            "errorMessagePresent": True,
            "errorCatalog": [
                {"component": "Status_Required", "kind": "validation-rule",
                 "errorMessage": "Status is required.", "fieldSelection": "Status__c",
                 "condition": "ISBLANK(Status__c)", "resolvedErrorMessage": "Status is required."}
            ],
        },
        "PermissionSet": {
            "label": "Alpha Ops", "description": "Grants alpha access.", "license": "Salesforce",
            "hasActivationRequired": False, "objectAccess": {"A__c": "CRE+VA"},
            "systemPermissions": ["ViewSetup"], "objectPermissionCount": 2,
            "fieldPermissionCount": 400, "classAccessCount": 1, "customPermissionCount": 1,
            "recordTypeCount": 1, "flowAccessCount": 1, "userPermissionCount": 1,
            "tabCount": 1, "pageAccessCount": 1, "applicationVisibilityCount": 1,
            "referencesTruncated": True, "truncatedFamilies": ["grants-field-edit"],
        },
        "CustomMetadata": {
            "type": "Routing__mdt", "record": "Default", "label": "Default",
            "protected": False, "fieldsPopulated": ["Threshold__c"],
            "values": [{"field": "Threshold__c", "value": 20}],
        },
        "LightningComponentBundle": {
            "isExposed": True, "targets": ["lightning__RecordPage"], "masterLabel": "Alpha Card",
            "description": "Shows the alpha case.",
            "targetConfigs": [{"targets": "lightning__RecordPage", "objects": ["A__c"]}],
            "apiProperties": ["recordId"], "wiredAdapters": ["getRecord"],
        },
        "FieldSet": {
            "object": "Account", "fullName": "Support_Fields", "label": "Support Fields",
            "description": "Fields the support console iterates.",
            "displayedFields": ["SupportTier__c", "Region__c"],
            "availableFields": ["EscalationNotes__c"],
        },
        "CompactLayout": {
            "object": "Case", "fullName": "Case_Highlights", "label": "Case Highlights",
            "fields": ["Subject", "Status", "Priority"],
        },
        "BusinessProcess": {
            "object": "Opportunity", "fullName": "EMEA_Sales",
            "description": "EMEA pipeline stages.", "isActive": True,
            "values": [{"fullName": "Prospecting", "default": True}, {"fullName": "Closed Won"}],
            "lifecycleField": "StageName",
        },
        "WebLink": {
            "object": "Account", "fullName": "Open_Billing_Portal", "label": "Open Billing Portal",
            "displayType": "button", "linkType": "url", "openType": "newWindow",
            "targetHost": "billing.example.com",
        },
        "DuplicateRule": {
            "object": "Contact", "label": "Standard Contact Duplicate Rule", "active": True,
            "sortOrder": "1", "actionOnInsert": "Allow", "actionOnUpdate": "Block",
            "securityOption": "EnforceSharingRules",
            "operationsOnInsert": ["Alert", "Report"], "operationsOnUpdate": ["Alert"],
            "matchRules": [
                {"matchingRule": "Standard_Contact_Match", "matchingRuleObjectType": "Contact",
                 "mappedFields": [{"input": "Email", "output": "Email"}]}
            ],
            "errorCatalog": [
                {"component": "Contact.Standard_Contact_Duplicate_Rule", "kind": "duplicate-alert",
                 "errorMessage": "You may be creating a duplicate contact.",
                 "resolvedErrorMessage": "You may be creating a duplicate contact."}
            ],
        },
        "MatchingRule": {
            "object": "Contact", "fullName": "Standard_Contact_Match",
            "label": "Standard Contact Match", "ruleStatus": "Active",
            "booleanFilter": "1 AND (2 OR 3)",
            "items": [
                {"field": "Email", "matchingMethod": "Exact", "blankValueBehavior": "NullNotAllowed"},
                {"field": "LastName", "matchingMethod": "FuzzyLastName", "blankValueBehavior": "MatchBlanks"},
            ],
        },
        "Queue": {
            "name": "Tier1_Support", "doesSendEmailToMembers": True,
            "memberCounts": {"publicGroups": 1, "users": 4}, "servesObjects": ["Case", "Lead"],
        },
        "Role": {
            "label": "EMEA Sales Manager", "caseAccessLevel": "Edit", "contactAccessLevel": "Read",
            "opportunityAccessLevel": "Edit", "mayForecastManagerShare": False,
            "description": "Manages the EMEA pipeline.",
        },
        "DelegateGroup": {
            "label": "Regional Admins", "loginAccess": True,
            "administersRoles": ["EMEA_Sales_Manager"],
            "assignablePermissionSetCount": 2, "assignableProfileCount": 1,
        },
        "PermissionSetGroup": {
            "label": "Support Agent Bundle", "status": "Updated",
            "permissionSetCount": 3, "mutingPermissionSetCount": 1,
        },
        "StaticResource": {
            "contentType": "application/zip", "cacheControl": "Public",
            "description": "Vendor charting bundle.",
        },
        "PlatformEventChannel": {"label": "Order Events", "channelType": "event"},
        "PlatformEventChannelMember": {
            "eventChannel": "OrderEvents__chn", "selectedEntity": "OrderShipped__e",
            "enrichedFields": ["OrderId__c", "Status__c"],
        },
        "GlobalValueSet": {
            "masterLabel": "Region", "description": "Shared sales regions.", "sorted": True,
            "values": [
                {"fullName": "EMEA", "label": "EMEA", "default": True, "isActive": True},
                {"fullName": "APAC", "label": "APAC"},
            ],
            "valueCount": 2,
        },
        "StandardValueSet": {
            "masterLabel": "Opportunity Stage", "sorted": False,
            "values": [
                {"fullName": "Prospecting", "label": "Prospecting", "probability": "10",
                 "forecastCategory": "Pipeline"},
                {"fullName": "Closed Won", "label": "Closed Won", "closed": True, "won": True,
                 "probability": "100", "forecastCategory": "Closed"},
            ],
            "valueCount": 12, "valuesTruncated": True,
        },
        "CustomLabel": {
            "value": "Case escalated to Tier 2.", "language": "en_US", "protected": True,
            "categories": "Support,Notifications", "shortDescription": "Escalation toast",
        },
        "CustomTab": {"label": "Status Page", "tabKind": "web", "urlHost": "status.example.com"},
        "CustomApplication": {
            "label": "Harness Console", "navType": "Console", "uiType": "Lightning",
            "formFactors": ["Large"], "tabs": ["standard-Case", "Engagement__c"],
            "hasUtilityBar": True,
            "overrides": [
                {
                    "action": "View", "content": "Case_Record_Page", "type": "Flexipage",
                    "object": "Case", "profile": "Support Agent", "formFactor": "Large",
                }
            ],
            "overrideCount": "73", "overridesTruncated": True, "factsTruncated": True,
        },
        "FlowDefinition": {
            "activeVersionNumber": "3", "active": True,
            "description": "Pins the active version of the router flow.",
        },
        "PathAssistant": {
            "label": "Opportunity Path", "active": True, "object": "Opportunity",
            "drivingField": "Opportunity.StageName", "recordType": "EMEA",
            "steps": [
                {"value": "Prospecting", "fields": ["Amount", "CloseDate"],
                 "guidance": "Qualify budget and timeline before advancing."}
            ],
        },
        "ListView": {
            "object": "Case", "fullName": "Tier1_Open_Cases", "label": "Tier1 Open Cases",
            "filterScope": "Queue", "queue": "Tier1_Support", "booleanFilter": "1 AND 2",
            "columns": ["CASES.CASE_NUMBER", "CASES.SUBJECT", "CASES.STATUS"],
            # Digit-string count exercises _normalize_fact coercion; the flags disclose a >50 cut.
            "columnCount": "63", "columnsTruncated": True, "factsTruncated": True,
            "filters": [
                {"field": "Status", "operator": "notEqual", "value": "Closed"},
                {"field": "Priority", "operator": "equals", "value": "High"},
            ],
        },
        "ReportType": {
            "label": "Cases with Engagements",
            "description": "Case rows joined to their engagement work.",
            "baseObject": "Case", "category": "cases", "deployed": True,
            # The join-path table's columns emit no edges — columnCount exceeding the edge
            # count is the documented limitation, not truncation.
            "tables": ["Case", "Case.Engagements__r"], "columnCount": 24,
        },
        "SharingRules": {
            "object": "Engagement__c",
            "criteriaRules": [
                {"name": "Share_EMEA", "label": "Share EMEA", "accessLevel": "Read",
                 "criteria": [{"field": "Region__c", "operator": "equals", "value": "EMEA"}],
                 "booleanFilter": "1",
                 "sharedTo": [{"direction": "sharedTo", "type": "group", "name": "Sales_All"}]},
            ],
            "ownerRules": [
                {"name": "Queue_To_Managers", "accessLevel": "Edit",
                 "parties": [
                     {"direction": "sharedTo", "type": "roleAndSubordinates",
                      "name": "EMEA_Sales_Manager"},
                     {"direction": "sharedFrom", "type": "queue", "name": "Tier1_Support"},
                 ]},
            ],
            "criteriaRuleCount": 72, "ownerRuleCount": 3,
            "rulesTruncated": True, "factsTruncated": True,
            "referencesTruncated": True, "truncatedFamilies": ["filters-field"],
        },
        "QuickAction": {
            "label": "Log Engagement", "actionType": "Create", "object": "Engagement__c",
            "targetRecordType": "Standard", "targetParentField": "Case__c",
            "fieldCount": 5, "overrideCount": "2", "successMessage": "Engagement logged.",
        },
        "MutingPermissionSet": {
            "label": "Mute Legacy Export",
            "mutedObjectAccess": {"Engagement__c": "D+MA"},
            "mutedSystemPermissions": ["DataExport", "ManageUsers"],
            "objectPermissionCount": 1, "fieldPermissionCount": "14", "classAccessCount": 1,
            "customPermissionCount": 1, "recordTypeCount": 1, "flowAccessCount": 1,
            "userPermissionCount": 2, "tabCount": 1, "pageAccessCount": 1,
            "applicationVisibilityCount": 1,
        },
        "Dashboard": {
            "folder": "Sales_Dashboards", "label": "EMEA Pipeline",
            "runningUserPolicy": "LoggedInUser", "componentCount": 6,
            "reports": ["Sales_Reports/EMEA_Pipeline_by_Stage"],
        },
        "EmailTemplate": {
            "folder": "Support_Templates", "templateType": "html",
            "subject": "Your case has been escalated", "encoding": "UTF-8",
            "letterhead": "Support_Letterhead", "relatedEntityType": "Case",
            "available": True,
        },
        "AuraDefinitionBundle": {
            "definitionTypes": ["cmp", "css", "design", "js"],
            "implements": ["flexipage:availableForAllPageTypes", "force:hasRecordId"],
            "extends": "c:harnessBaseCard",
        },
        "NamedCredential": {
            "label": "Billing API", "namedCredentialType": "SecuredEndpoint",
            "protocol": "NoAuthentication", "principalType": "NamedUser",
            "generateAuthorizationHeader": True, "allowMergeFieldsInBody": False,
            "allowMergeFieldsInHeader": False, "externalCredential": "Billing_OAuth",
            "endpointHost": "api.billing.example.com",
        },
        "ExternalCredential": {
            "label": "Billing OAuth", "authenticationProtocol": "OAuth",
            "authenticationProtocolVariant": "ClientCredentialsClientSecretBasic",
            "principals": [
                {"name": "Billing Principal", "type": "NamedPrincipal", "sequence": "1"}
            ],
        },
        "RemoteSiteSetting": {
            "isActive": True, "disableProtocolSecurity": False,
            "endpointHost": "legacy.billing.example.com",
        },
        "ExternalDataSource": {
            "label": "ERP Orders", "sourceType": "OData4", "principalType": "Identity",
            "protocol": "NoAuthentication", "isWritable": False,
            "endpointHost": "odata.erp.example.com",
        },
        "ExternalServiceRegistration": {
            "label": "Shipping Service", "registrationProviderType": "Custom",
            "namedCredential": "Shipping_API", "status": "Complete", "schemaPresent": True,
        },
        "ConnectedApp": {
            "label": "Field Mobile App", "oauthScopes": ["Api", "RefreshToken"],
            "isAdminApproved": True, "ipRelaxation": "ENFORCE",
            "callbackHost": "login.example.com", "canvasHost": "canvas.example.com",
            "samlConfigPresent": True,
        },
        "AuthProvider": {
            "label": "Corporate SSO", "providerType": "OpenIdConnect",
            "authorizeHost": "sso.example.com", "tokenHost": "sso.example.com",
            "executionUserPresent": True,
        },
        "CspTrustedSite": {
            "isActive": True, "context": "LEX",
            "directives": ["ConnectSrc", "ImgSrc"], "endpointHost": "cdn.example.com",
        },
        "CorsWhitelistOrigin": {"endpointHost": "app.example.com"},
        "Profile": {
            "label": "Support Agent", "custom": True, "userLicense": "Salesforce",
            "objectAccess": {"Engagement__c": "CRED+VA"},
            "systemPermissions": ["ViewSetup"],
            "objectPermissionCount": 3, "fieldPermissionCount": 120, "classAccessCount": 2,
            "customPermissionCount": 1, "recordTypeCount": 2, "flowAccessCount": 1,
            "userPermissionCount": 4, "tabCount": 6, "pageAccessCount": 1,
            "applicationVisibilityCount": 2,
            "layoutAssignmentCount": 40,
            "defaultRecordTypes": {"Engagement__c": "Engagement__c.Standard"},
            "defaultApplication": "Harness_Console",
            # Presence + digit-string count only — never the IP range values themselves.
            "loginIpRangesPresent": True, "loginIpRangeCount": "2", "loginHoursPresent": True,
            # The assigns-layout merge re-caps the combined edge list and must disclose
            # what it drops — including the assigns-layout family itself.
            "referencesTruncated": True,
            "truncatedFamilies": ["assigns-layout", "grants-field-edit"],
        },
        "Layout": {
            "object": "Engagement__c", "fieldCount": 34,
            "requiredOnLayout": ["Engagement__c.Status__c"],
            "readonlyOnLayout": ["Engagement__c.Total_Billed__c"],
            "sections": ["Information", "Billing"],
            "relatedLists": [
                {"name": "Engagement_Tasks__r", "fields": ["Subject__c", "Due_Date__c"]}
            ],
            "actionCount": 3,
            "referencesTruncated": True, "truncatedFamilies": ["places-field"],
        },
        "FlexiPage": {
            "label": "Engagement Record Page", "pageType": "RecordPage",
            "object": "Engagement__c",
            "template": "flexipage:recordHomeTemplateDesktop",
            "regionCount": 3, "componentCount": 8, "fieldInstanceCount": 6,
            "visibilityRuleFields": ["Engagement__c.Status__c"],
        },
        "Workflow": {
            "object": "Case",
            "rules": [
                {"name": "Escalate_Aged", "active": True,
                 "triggerType": "onCreateOrTriggeringUpdate",
                 "criteria": [{"field": "Status", "operator": "equals", "value": "New"}],
                 "actions": [{"name": "Notify_Owner", "type": "Alert"}]}
            ],
            "fieldUpdates": [
                {"name": "Set_Priority", "field": "Priority", "operation": "Literal",
                 "literalValue": "High", "reevaluateOnChange": False}
            ],
            "alerts": [
                {"name": "Notify_Owner", "template": "Support_Templates/Case_Escalated",
                 "recipientTypes": ["owner"], "senderType": "CurrentUser"}
            ],
            "outboundMessages": [
                {"name": "Sync_Billing", "endpointHost": "erp.example.com",
                 "fields": ["CaseNumber", "Status"], "includeSessionId": False}
            ],
            "tasks": [
                {"name": "Follow_Up", "assignedToType": "owner", "subject": "Follow up",
                 "status": "Not Started", "priority": "Normal", "dueDateOffset": "2"}
            ],
            "ruleCount": 1, "activeRuleCount": 1,
            # >100 field updates: digit-string true total plus the per-array flag and
            # the factsTruncated aggregate that maps coverage to "partial".
            "fieldUpdateCount": "130", "alertCount": 1,
            "fieldUpdatesTruncated": True, "factsTruncated": True,
            "referencesTruncated": True, "truncatedFamilies": ["references-field"],
        },
        "AssignmentRules": {
            "object": "Case",
            "rules": [
                {"name": "Standard Case Routing", "active": True,
                 "entries": [
                     {"order": 1,
                      "criteria": [{"field": "Case.Origin", "operator": "equals",
                                    "value": "Web"}],
                      "assignedToType": "Queue", "assignedTo": "Tier1_Support"}
                 ],
                 # A single rule with >100 entries: entryCount keeps the true total.
                 "entryCount": 148, "entriesTruncated": True}
            ],
            "ruleCount": 1, "factsTruncated": True,
            "referencesTruncated": True, "truncatedFamilies": ["filters-field"],
        },
        "AutoResponseRules": {
            "object": "Case",
            "rules": [
                {"name": "Web Auto Response", "active": True,
                 "entries": [
                     {"order": 1,
                      "criteria": [{"field": "Case.Origin", "operator": "equals",
                                    "value": "Web"}],
                      "template": "Support_Templates/Case_Received"}
                 ],
                 "entryCount": 1}
            ],
            "ruleCount": 1,
        },
        "EscalationRules": {
            "object": "Case",
            "rules": [
                {"name": "Aged Case Escalation", "active": True,
                 "entries": [
                     {"order": 1,
                      "criteria": [{"field": "Case.Priority", "operator": "equals",
                                    "value": "High"}],
                      "escalationActions": [
                          {"minutesToEscalation": "60", "notifyCaseOwner": True,
                           "assignedToType": "Queue", "assignedTo": "Tier2_Support"}
                      ]}
                 ],
                 "entryCount": 1}
            ],
            "ruleCount": 1,
        },
        "ApprovalProcess": {
            "object": "Engagement__c", "label": "Discount Approval", "active": True,
            "recordEditability": "AdminOnly", "allowRecall": True,
            "finalApprovalRecordLock": True, "finalRejectionRecordLock": False,
            "entryCriteria": {
                "criteria": [{"field": "Engagement__c.Discount__c",
                              "operator": "greaterThan", "value": "20"}],
                "booleanFilter": "1",
            },
            "steps": [
                {"order": 1, "name": "Manager_Review", "label": "Manager Review",
                 "approvers": [{"type": "relatedUserField", "field": "Manager__c"}],
                 "whenMultipleApprovers": "FirstResponse",
                 "rejectBehavior": "RejectRequest",
                 "approvalActions": [{"name": "Set_Status_Approved", "type": "FieldUpdate"}]}
            ],
            "actionSets": {
                "finalApproval": [{"name": "Set_Status_Approved", "type": "FieldUpdate"}],
                "finalRejection": [{"name": "Notify_Requestor", "type": "Alert"}],
            },
            "approvalPageFields": ["Name", "Discount__c"],
            "emailTemplate": "Support_Templates/Approval_Request",
            "allowedSubmitterTypes": ["owner"],
            # stepCount is the true total, computed before the 50-step cap slice.
            "stepCount": 1, "entryCriteriaPresent": True,
        },
        "Report": {
            "folder": "Sales_Reports", "label": "EMEA Pipeline by Stage",
            "format": "Summary", "reportType": "Opportunity", "scope": "organization",
            "columnCount": 6,
            "filters": [{"column": "Opportunity.Region__c", "operator": "equals",
                         "value": "EMEA"}],
            # Honest true total (D7): digit-string filterCount above the 50-item cap.
            "filterCount": "58", "filtersTruncated": True, "factsTruncated": True,
            "groupings": ["STAGE_NAME"], "hasChart": True,
            "timeFrame": {"dateColumn": "CLOSE_DATE", "interval": "INTERVAL_CURFY"},
            "referencesTruncated": True, "truncatedFamilies": ["references-field"],
        },
        "ApexPage": {
            "standardController": "Engagement__c",
            "extensions": ["EngagementExtension"],
            "actionMethods": ["save", "recalculate"],
            "label": "Engagement Edit", "apiVersion": "61.0",
        },
        "ApexComponent": {
            "controller": "BillingSummaryController",
            "actionMethods": ["refresh"],
            "label": "Billing Summary", "apiVersion": "61.0",
        },
    }

    def test_a_sample_exists_for_every_profiled_type(self) -> None:
        # The plan chose this test as "the standing test that would have caught all six"
        # undeclared properties. Three hand-written samples would not have caught a seventh:
        # Flow, Apex, PermissionSet, CustomMetadata and LWC were validated against their profile
        # schemas by no test and by no corpus. The set equality is what makes it standing — a
        # new profiled type cannot be added without a fixture that has to validate.
        self.assertEqual(set(store.PROFILES), set(self.SAMPLES))

    def test_adapter_output_validates_against_the_profile_schema(self) -> None:
        for metadata_type, facts in self.SAMPLES.items():
            with self.subTest(metadataType=metadata_type):
                carried, errors, _assurance = store.ADAPTERS[metadata_type](
                    {
                        "metadataType": metadata_type,
                        "facts": facts,
                        # An edge exercises the shape every profile declares and none of the
                        # hand-written samples reached.
                        "references": [{"kind": "operates-on", "target": "A__c"}],
                    }
                )
                schema = store.load_schema(store.PROFILES[metadata_type]["schema"])
                payload = {"typeFacts": carried, "intentionalErrors": errors}
                problems = sorted(
                    error.message
                    for error in Draft202012Validator(schema).iter_errors(payload)
                )
                self.assertEqual([], problems, f"{metadata_type}: {problems}")


class ErrorEnvelopeTests(KnowledgeStoreFixture):
    """Plan 2026-08-09 §3c.2: main() may never leak a raw traceback to stdout — every
    failure is a JSON envelope with errorType; unexpected types keep their traceback on
    stderr for the programmer."""

    def run_main(self, argv):
        import contextlib
        import io

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = store.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_malformed_identity_yields_an_envelope_not_a_traceback(self) -> None:
        purpose = self.temp / "p.md"
        purpose.write_text("One sentence.", encoding="utf-8")
        code, out, err = self.run_main(
            ["entry-describe", "--identity", "Flow:OnlyTwoParts", "--purpose-file", str(purpose)]
        )
        self.assertEqual(1, code)
        envelope = json.loads(out)
        self.assertEqual("ERROR", envelope["outcome"])
        self.assertNotEqual("StoreError", envelope["errorType"])
        self.assertIn("Traceback", err)

    def test_inline_purpose_describes_without_a_scratch_file(self) -> None:
        drafted = self.draft(purpose_file=None)
        result = store.command_entry_describe(
            argparse.Namespace(
                identity=drafted["identity"],
                purpose_file=None,
                purpose="Routes alpha cases to the correct queue on create.",
            )
        )
        self.assertEqual("DESCRIBED", result["outcome"])
        with self.assertRaises(store.StoreError):
            store.command_entry_describe(
                argparse.Namespace(identity=drafted["identity"], purpose_file=None, purpose=None)
            )
        with self.assertRaises(store.StoreError):
            store.command_entry_describe(
                argparse.Namespace(
                    identity=drafted["identity"], purpose_file="x.md", purpose="Both given."
                )
            )

    def test_sentence_counter_skips_abbreviations_and_echoes_the_split(self) -> None:
        text = (
            "Routes cases by type, e.g. billing disputes, to the right queue. "
            "Requires API v. 64.0 or later. Uses Acct. No. as the natural key."
        )
        self.assertEqual(3, len(store.split_sentences(text)))
        with self.assertRaises(store.StoreError) as ctx:
            purpose = self.temp / "long.md"
            purpose.write_text("One. Two. Three. Four. Five. Six. Seven. Eight. Nine.", encoding="utf-8")
            drafted = self.draft(purpose_file=None)
            store.command_entry_describe(
                argparse.Namespace(identity=drafted["identity"], purpose_file=str(purpose))
            )
        self.assertIn("Counted as:", str(ctx.exception))

    def test_entry_status_typo_is_a_named_error_not_an_empty_success(self) -> None:
        drafted = self.draft()
        with self.assertRaises(store.StoreError) as ctx:
            store.command_entry_status(argparse.Namespace(identity="Flow:c:NoSuchFlow"))
        self.assertIn("no entry matches", str(ctx.exception))
        with self.assertRaises(store.StoreError):
            store.command_entry_status(argparse.Namespace(identity="Flow:OnlyTwoParts"))
        result = store.command_entry_status(argparse.Namespace(identity=drafted["identity"]))
        self.assertEqual(1, len(result["entries"]))

    def test_domain_errors_keep_a_quiet_stderr(self) -> None:
        code, out, err = self.run_main(
            ["entry-draft", "--metadata-type", "NoSuchType", "--full-name", "X"]
        )
        self.assertEqual(1, code)
        envelope = json.loads(out)
        self.assertEqual("StoreError", envelope["errorType"])
        self.assertNotIn("Traceback", err)


class FeatureBindingResolverTests(KnowledgeStoreFixture):
    """Plan 2026-08-09 §F.4: approved-drifted binds too (same rule as retrieval §3.1);
    draft and revoked never do. binding_state's digest comparison — not the resolver —
    is what downgrades stale citations."""

    def drift_source(self) -> None:
        flow = self.temp / "force-app/main/default/flows/HarnessAlphaRouter.flow-meta.xml"
        flow.write_text(
            FLOW_XML.replace("Update</recordTriggerType>", "Create</recordTriggerType>"),
            encoding="utf-8",
        )

    def test_resolver_accepts_an_approved_drifted_entry(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        self.drift_source()
        self.assertEqual("approved-drifted", self.lane_of(drafted["identity"])["lane"])
        receipt = store._feature_binding_resolver(drafted["identity"])
        self.assertEqual(drafted["reviewedContentDigest"], receipt["reviewedContentDigest"])

    def test_resolver_still_rejects_draft_and_revoked(self) -> None:
        drafted = self.draft()
        with self.assertRaises(store.StoreError) as ctx:
            store._feature_binding_resolver(drafted["identity"])
        self.assertIn("draft", str(ctx.exception))
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        store.command_entry_revoke(
            argparse.Namespace(identity=drafted["identity"], rationale="mis-approved")
        )
        with self.assertRaises(store.StoreError):
            store._feature_binding_resolver(drafted["identity"])

    def test_binding_health_reports_drifted_not_unknown(self) -> None:
        # The confirmed bonus from the plan: feature-context's binding_health used to
        # collapse to "unknown" (resolver StoreError swallowed) for drifted bindings;
        # with the resolver accepting approved-drifted it must now say "drifted".
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        store.command_feature_open(
            argparse.Namespace(slug="binding-health", name="Binding Health")
        )
        ops = self.temp / "binding-health-ops.json"
        ops.write_text(
            json.dumps(
                {
                    "operations": [
                        {"kind": "binding", "op": "bind", "data": {"entryId": drafted["identity"]}},
                        {"kind": "section", "op": "replace",
                         "data": {"name": "Purpose and boundary", "text": "Routes."}},
                        {"kind": "section", "op": "replace",
                         "data": {"name": "Domain and data model", "text": "Flow."}},
                        {"kind": "section", "op": "replace",
                         "data": {"name": "Evidence map", "text": "FB-001."}},
                    ]
                }
            ),
            encoding="utf-8",
        )
        store.command_feature_record(
            argparse.Namespace(slug="binding-health", expected_version=0, operations_file=str(ops))
        )
        review = store.command_feature_review(argparse.Namespace(slug=["binding-health"]))
        pin = review["approveCommand"].split('--feature "')[1].rstrip('"')
        store.command_feature_approve(argparse.Namespace(feature=[pin]))
        # Source drift alone: the entry is approved-drifted, but the citation still matches
        # what was approved — before this fix the resolver's StoreError collapsed this to
        # "unknown"; now it is an honest "current". (The plan's bonus predicted "drifted"
        # here — imprecise: binding_state compares APPROVAL digests, and those move only
        # on re-approval, not on source drift. Reported as a deviation.)
        self.drift_source()
        context = store.command_feature_context(argparse.Namespace(slug="binding-health"))
        self.assertEqual({"FB-001": "current"}, context["bindingHealth"])
        # Re-approve the entry with different content: now the stored binding digest no
        # longer matches the live approval, and health must say "drifted", not "unknown".
        purpose = self.temp / "new-purpose.md"
        purpose.write_text("Routes alpha cases to the correct queue on create.", encoding="utf-8")
        store.command_entry_describe(
            argparse.Namespace(identity=drafted["identity"], purpose_file=str(purpose))
        )
        rereview = store.command_entry_review(argparse.Namespace(identity=[drafted["identity"]]))
        self.approve([pin.strip() for pin in rereview["approveCommand"].split("--entry ")[1:]])
        context = store.command_feature_context(argparse.Namespace(slug="binding-health"))
        self.assertEqual({"FB-001": "drifted"}, context["bindingHealth"])


class PackageExtensionPointTests(KnowledgeStoreFixture):
    """packageExtensionPoint (plan 2026-08-09, Problem 4): a conscious, human-approved
    classification in the envelope — digest-included like sensitivity, unlike orgUsage."""

    FIELD = {"recognized": True, "rule": "MP-EXT-001", "note": "vendor-documented field set"}

    def test_absence_keeps_the_digest_of_pre_field_entries(self) -> None:
        drafted = self.draft()
        frontmatter, body = store.split_entry(
            (self.temp / drafted["path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(
            drafted["reviewedContentDigest"], store.reviewed_content_digest(frontmatter, body)
        )
        stamped = copy.deepcopy(frontmatter)
        stamped["packageExtensionPoint"] = dict(self.FIELD)
        self.assertNotEqual(
            drafted["reviewedContentDigest"], store.reviewed_content_digest(stamped, body)
        )

    def test_schema_accepts_the_field_and_pins_its_shape(self) -> None:
        drafted = self.draft()
        frontmatter, body = store.split_entry(
            (self.temp / drafted["path"]).read_text(encoding="utf-8")
        )
        frontmatter["packageExtensionPoint"] = dict(self.FIELD)
        self.assertEqual([], store.validate_entry(frontmatter, body))
        frontmatter["packageExtensionPoint"] = {"recognized": True, "rule": "SOMETHING-ELSE"}
        self.assertTrue(store.validate_entry(frontmatter, body))

    def test_r10_clone_field_change_after_approval_invalidates(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        path = self.temp / drafted["path"]
        text = path.read_text(encoding="utf-8")
        frontmatter, body = store.split_entry(text)
        frontmatter["packageExtensionPoint"] = dict(self.FIELD)
        path.write_text(
            "---\n" + store.yaml.safe_dump(frontmatter, sort_keys=False) + "---\n\n" + body,
            encoding="utf-8",
        )
        self.assertNotEqual("approved-current", self.lane_of(drafted["identity"])["lane"])


class VersionedSchemaResolutionTests(KnowledgeStoreFixture):
    """Validation resolves the profile schema from the (id, version) the entry declares,
    against the append-only SCHEMA_REGISTRY — never from the current PROFILES row for the
    type (plan 2026-08-09 §2.1). A consolidation that repoints PROFILES must NOT
    re-validate existing entries against a schema they were not drafted with."""

    def test_every_current_profile_resolves_through_the_registry(self) -> None:
        for metadata_type, profile in store.PROFILES.items():
            with self.subTest(metadataType=metadata_type):
                self.assertEqual(
                    profile["schema"],
                    store.SCHEMA_REGISTRY.get(
                        (profile["id"], store.profile_major(profile["version"]))
                    ),
                )

    def test_existing_entry_survives_a_profiles_repoint_unchanged(self) -> None:
        drafted = self.draft()
        frontmatter, body = store.split_entry(
            (self.temp / drafted["path"]).read_text(encoding="utf-8")
        )
        # Simulate a §2.2 consolidation: Flow drafts now use a family profile whose schema
        # would reject the old typeFacts. The registry keeps the retired (id, version) row;
        # the entry's frontmatter is not touched.
        consolidated = {
            "id": "salesforce.automation-family",
            "version": "2.0.0",
            "schema": "knowledge-profile-customfield.schema.json",
        }
        with unittest.mock.patch.dict(
            store.PROFILES, {"Flow": consolidated}
        ), unittest.mock.patch.dict(
            store.SCHEMA_REGISTRY,
            {
                (consolidated["id"], store.profile_major(consolidated["version"])): (
                    consolidated["schema"]
                )
            },
        ):
            self.assertEqual([], store.validate_entry(frontmatter, body))

    def test_unregistered_profile_pair_is_a_named_problem(self) -> None:
        drafted = self.draft()
        frontmatter, body = store.split_entry(
            (self.temp / drafted["path"]).read_text(encoding="utf-8")
        )
        frontmatter["profile"]["version"] = "9.9.9"
        problems = store.validate_entry(frontmatter, body)
        self.assertTrue(
            any("no registered schema for profile" in problem for problem in problems),
            problems,
        )


class AgentDescriptionTests(KnowledgeStoreFixture):
    """The description is the one part of an entry a model writes rather than extracts."""

    def describe(self, identity: str, text: str):
        path = self.temp / "description.md"
        path.write_text(text, encoding="utf-8")
        return store.command_entry_describe(
            argparse.Namespace(identity=identity, purpose_file=str(path))
        )

    def test_undescribed_draft_carries_a_sentinel_and_cannot_be_approved(self) -> None:
        drafted = self.draft(purpose_file=None)
        body = (self.temp / drafted["path"]).read_text(encoding="utf-8")
        self.assertIn("<AGENT_DESCRIPTION>", body)
        review = store.command_entry_review(argparse.Namespace(identity=[drafted["identity"]]))
        self.assertEqual("NOTHING_TO_REVIEW", review["outcome"])
        self.assertTrue(any("sentinel" in problem for problem in review["problems"]))

    def test_describe_replaces_the_sentinel_and_unlocks_review(self) -> None:
        drafted = self.draft(purpose_file=None)
        described = self.describe(
            drafted["identity"],
            "Routes engagement records to the owning queue after save. Blocks the update when "
            "the discount exceeds the approved threshold.",
        )
        self.assertEqual("DESCRIBED", described["outcome"])
        self.assertTrue(described["replacedSentinel"])
        self.assertEqual(2, described["sentences"])
        review = store.command_entry_review(argparse.Namespace(identity=[drafted["identity"]]))
        self.assertEqual("REVIEW_READY", review["outcome"])

    def test_rewriting_a_description_invalidates_an_existing_approval(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        self.assertEqual("approved-current", self.lane_of(drafted["identity"])["lane"])
        result = self.describe(drafted["identity"], "A materially different description.")
        self.assertTrue(result["previousApprovalInvalidated"])
        self.assertEqual("draft", self.lane_of(drafted["identity"])["lane"])

    def test_description_length_is_bounded_and_emptiness_refused(self) -> None:
        drafted = self.draft(purpose_file=None)
        with self.assertRaises(store.StoreError):
            self.describe(drafted["identity"], "   ")
        with self.assertRaises(store.StoreError) as ctx:
            self.describe(drafted["identity"], " ".join(f"Sentence {i}." for i in range(20)))
        self.assertIn("1-8 sentences", str(ctx.exception))

    def test_describe_never_touches_extracted_facts(self) -> None:
        drafted = self.draft()
        before, _ = store.split_entry((self.temp / drafted["path"]).read_text(encoding="utf-8"))
        self.describe(drafted["identity"], "Rewritten description of the component.")
        after, body = store.split_entry((self.temp / drafted["path"]).read_text(encoding="utf-8"))
        self.assertEqual(before["typeFacts"], after["typeFacts"])
        self.assertEqual(before["intentionalErrors"], after["intentionalErrors"])
        self.assertIn("Rewritten description", body)

    def describe_with(self, identity: str, text: str, **kwargs):
        path = self.temp / "description.md"
        path.write_text(text, encoding="utf-8")
        namespace = argparse.Namespace(
            identity=identity, purpose_file=str(path),
            limitation=kwargs.get("limitation"),
            clear_limitations=kwargs.get("clear_limitations", False),
        )
        return store.command_entry_describe(namespace)

    def test_limitations_can_be_written_and_are_digest_bound(self) -> None:
        """`limitations` is required, digest-bound and printed to the approver — and had no writer.

        Measured on the first real store: `[]` on all 80 entries, while 26 of them carried an
        explicit source-limit caveat in their prose, where no consumer reads it. `entry-draft`
        hardcodes the field and no subcommand could set it."""

        drafted = self.draft()
        before, body = store.split_entry((self.temp / drafted["path"]).read_text(encoding="utf-8"))
        self.assertEqual([], before["limitations"])
        digest_before = store.facts_digest(before)

        result = self.describe_with(
            drafted["identity"], "States what the component does.",
            limitation=["Value set is not in this repository.", "Callers are not visible here."],
        )
        after, _ = store.split_entry((self.temp / drafted["path"]).read_text(encoding="utf-8"))
        self.assertEqual(
            ["Callers are not visible here.", "Value set is not in this repository."],
            after["limitations"], "limitations are stored sorted and de-duplicated",
        )
        self.assertEqual(after["limitations"], result["limitations"])
        self.assertNotEqual(
            digest_before, store.facts_digest(after),
            "a limitation that does not move factsDigest is not governed content",
        )
        self.assertEqual(before["typeFacts"], after["typeFacts"], "extracted facts were touched")

    def test_limitations_are_replaced_not_appended_and_can_be_cleared(self) -> None:
        # A limitation set is a statement about THIS text. Appending would silently carry a caveat
        # that the new description already answered.
        drafted = self.draft()
        self.describe_with(drafted["identity"], "First take.", limitation=["Stale caveat."])
        self.describe_with(drafted["identity"], "Second take.", limitation=["Current caveat."])
        after, _ = store.split_entry((self.temp / drafted["path"]).read_text(encoding="utf-8"))
        self.assertEqual(["Current caveat."], after["limitations"])

        self.describe_with(drafted["identity"], "Third take.", clear_limitations=True)
        cleared, _ = store.split_entry((self.temp / drafted["path"]).read_text(encoding="utf-8"))
        self.assertEqual([], cleared["limitations"])

        with self.assertRaises(store.StoreError):
            self.describe_with(
                drafted["identity"], "Fourth take.",
                limitation=["Something."], clear_limitations=True,
            )


class DraftLaneHonestyTests(KnowledgeStoreFixture):
    """Unfinished work and broken work must not look the same."""

    def test_undescribed_draft_reports_draft_with_the_reason(self) -> None:
        drafted = self.draft(purpose_file=None)
        lane = self.lane_of(drafted["identity"])
        self.assertEqual("draft", lane["lane"])
        self.assertTrue(any("sentinel" in problem for problem in lane["problems"]))

    def test_tampered_approved_entry_still_reports_not_effective(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        path = self.temp / drafted["path"]
        path.write_text(path.read_text(encoding="utf-8").replace("right queue", "other queue"), encoding="utf-8")
        self.assertEqual("not-effective", self.lane_of(drafted["identity"])["lane"])


class WorkflowReachabilityTests(unittest.TestCase):
    """Every executor command must be reachable from the public surface AND permitted.

    A command that exists but no prompt, skill or agent ever names is dead machinery; a
    command a prompt names but the guard denies is a broken prompt. Both failed silently
    until this test: the approval skill was not loaded by its own agent, and nothing on the
    public surface drafted or described an entry at all.
    """

    HARNESS = Path(__file__).resolve().parents[1]

    def surface_text(self) -> str:
        parts = []
        for pattern in (".github/prompts/*.prompt.md", ".github/skills/*/SKILL.md", ".github/agents/*.agent.md"):
            for path in sorted(self.HARNESS.glob(pattern)):
                parts.append(path.read_text(encoding="utf-8"))
        return "\n".join(parts)

    # Commands that belong to CI rather than to a person, with the reason.
    NOT_ON_PUBLIC_SURFACE = {
        "entry-check": "CI integrity gate, run by validate_harness",
        "feature-check": "CI integrity gate over features and their ledger, run by validate_harness",
    }

    def test_every_entry_command_is_named_on_the_public_surface(self) -> None:
        surface = self.surface_text()
        commands = set(store.build_parser()._subparsers._group_actions[0].choices)
        for command in sorted(commands - set(self.NOT_ON_PUBLIC_SURFACE)):
            with self.subTest(command=command):
                self.assertIn(
                    command, surface, f"{command} is not reachable from any prompt, skill or agent"
                )

    def test_ci_only_commands_are_declared_and_actually_run_by_ci(self) -> None:
        workflow = (self.HARNESS / ".github/workflows/harness-ci.yml").read_text(encoding="utf-8")
        validator = (self.HARNESS / "scripts/validate_harness.py").read_text(encoding="utf-8")
        for command, reason in self.NOT_ON_PUBLIC_SURFACE.items():
            with self.subTest(command=command):
                self.assertTrue(reason.strip())
                # Being NAMED in the validator is not being RUN by it. feature-check was named
                # in a prompt, in the role guard and in this file's own docstrings while being
                # executed by nothing — and the live tree failed it for a day while
                # validate_harness reported PASS. The pin is the argv, not the mention.
                self.assertTrue(
                    f'"scripts/knowledge_store.py", "{command}"' in validator
                    or f"python scripts/knowledge_store.py {command}" in workflow,
                    f"{command} is declared CI-only but no CI step runs it",
                )

    def test_every_grounding_subprocess_is_covered_by_the_timeout_handler(self) -> None:
        # §0.3 item 1: an uncaught TimeoutExpired surfaces as a bare traceback in two gates at
        # once, attributable to nothing. The handler exists — this asserts that the loop the
        # grounding commands are actually run in is the one wrapped by it, so adding a second
        # subprocess outside it cannot pass review by looking adjacent to the first.
        import ast

        source = (self.HARNESS / "scripts/validate_harness.py").read_text(encoding="utf-8")
        loops = [
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.For)
            and "feature-check" in {
                literal.value
                for literal in ast.walk(node.iter)
                if isinstance(literal, ast.Constant) and isinstance(literal.value, str)
            }
        ]
        self.assertEqual(1, len(loops), "the grounding command loop was not found")
        handlers = [
            handler
            for statement in ast.walk(loops[0])
            if isinstance(statement, ast.Try)
            for handler in statement.handlers
        ]
        self.assertTrue(
            any(
                isinstance(handler.type, ast.Attribute)
                and handler.type.attr == "TimeoutExpired"
                for handler in handlers
            ),
            "grounding commands run outside the subprocess.TimeoutExpired handler",
        )

    def test_the_curator_agent_loads_the_skills_its_prompts_use(self) -> None:
        agent = (self.HARNESS / ".github/agents/knowledge-curator.agent.md").read_text(encoding="utf-8")
        for skill in ("approve-knowledge-drafts", "search-knowledge"):
            with self.subTest(skill=skill):
                self.assertIn(skill, agent, f"knowledge-curator does not load {skill}")

    def test_each_workflow_step_is_permitted_for_the_curator_and_denied_elsewhere(self) -> None:
        from scripts import copilot_role_guard as guard

        mutations = [
            "python scripts/knowledge_store.py entry-draft --metadata-type Flow --full-name X",
            "python scripts/knowledge_store.py entry-describe --identity Flow:c:X --purpose-file d.md",
            "python scripts/knowledge_store.py entry-approve --entry Flow:c:X:sha256:" + "a" * 64,
        ]
        reads = [
            "python scripts/knowledge_store.py entry-context --identity Flow:c:X",
            "python scripts/knowledge_store.py entry-coverage",
            "python scripts/knowledge_store.py entry-review",
        ]
        for command in mutations:
            with self.subTest(command=command.split("py ")[1].split()[0]):
                self.assertTrue(guard.allowed_role_command(command, self.HARNESS, "knowledge-curator"))
                self.assertFalse(guard.allowed_role_command(command, self.HARNESS, "solution-designer"))
        for command in reads:
            with self.subTest(command=command.split("py ")[1].split()[0]):
                for role in ("knowledge-curator", "solution-designer", "guardrail-reviewer"):
                    self.assertTrue(guard.allowed_role_command(command, self.HARNESS, role))


class ReparseScopeTests(KnowledgeStoreFixture):
    """The symlink walk is the command's own cost, so it covers the tree the command writes.

    Unscoped, `feature-status` on one 500-byte file paid an rglob over the whole 15 k-entry
    artifact corpus — a corpus it does not read, cannot write, and whose symlinks are the entry
    commands' business (§6, R4)."""

    def link(self, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(self.temp)

    def test_a_symlink_in_the_artifact_corpus_does_not_block_a_feature_command(self) -> None:
        self.link(store.ARTIFACTS_ROOT / "Flow" / "c" / "escape.md")
        store.command_feature_open(
            argparse.Namespace(slug="scheduling", name="Scheduling")
        )
        from scripts import feature_knowledge as fk
        self.assertTrue(fk.feature_path("scheduling").is_file())

    def test_a_symlink_in_the_feature_tree_still_refuses_a_feature_command(self) -> None:
        self.link(store.FEATURES_ROOT / "escape.md")
        with self.assertRaises(store.StoreError) as raised:
            store.command_feature_check(argparse.Namespace())
        self.assertIn("reparse point", str(raised.exception))

    def test_a_symlink_in_the_artifact_corpus_still_refuses_an_entry_command(self) -> None:
        self.link(store.ARTIFACTS_ROOT / "Flow" / "c" / "escape.md")
        with self.assertRaises(store.StoreError):
            self.draft()


class IncrementalEntryCheckTests(KnowledgeStoreFixture):
    """`--changed-since` must skip the work, and must not skip the guarantees.

    Measured at 9 000 entries, the first version skipped 9 000 of 9 000 fragment re-digests and
    saved 1 % — because the cost is YAML parsing and jsonschema validation, not the re-digest it
    skipped. Skipping the whole per-entry pass takes the same corpus from 40.4 s to 0.43 s. What
    may never be skipped is the cross-entry pass and the answer for anything git cannot vouch
    for."""

    def commit(self) -> None:
        import subprocess

        for command in (
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"],
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "entries"],
        ):
            subprocess.run(command, cwd=self.temp, check=True, capture_output=True)

    def check(self, ref=None):
        return store.command_entry_check(argparse.Namespace(changed_since=ref))

    def approved_entry(self) -> dict:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        return drafted

    def test_an_unchanged_entry_is_never_opened(self) -> None:
        # The point of the fix, asserted where it cannot be faked by a timing claim: if the
        # per-entry pass ran at all, parsing would raise.
        self.approved_entry()
        self.commit()

        def explode(_text):
            raise AssertionError("an unchanged entry was parsed")

        with unittest.mock.patch.object(store, "split_entry", explode):
            result = self.check("HEAD")
        self.assertEqual("PASS", result["outcome"])
        self.assertEqual(1, result["entriesSkipped"])
        self.assertEqual(1, result["entries"])

    def test_a_changed_entry_is_still_checked_in_full(self) -> None:
        drafted = self.approved_entry()
        self.commit()
        path = self.temp / drafted["path"]
        path.write_text(path.read_text(encoding="utf-8").replace("right queue", "other queue"), encoding="utf-8")
        with self.assertRaises(store.StoreError) as raised:
            self.check("HEAD")
        self.assertIn("recomputed digest is not the latest ledger record", str(raised.exception))

    def test_an_untracked_entry_counts_as_changed(self) -> None:
        # `git diff` reports tracked paths only, so a brand-new entry — the commonest thing there
        # is to check — would otherwise be invisible to the ref and skipped unexamined.
        drafted = self.approved_entry()
        path = self.temp / drafted["path"]
        path.write_text(path.read_text(encoding="utf-8").replace("right queue", "other queue"), encoding="utf-8")
        with self.assertRaises(store.StoreError):
            self.check("HEAD")

    def test_the_cross_entry_checks_still_cover_skipped_entries(self) -> None:
        # §0.3: "a per-entry skip would silently destroy them". The skipped entry contributes its
        # identity — read off its path — so a second file claiming that identity still collides.
        drafted = self.approved_entry()
        self.commit()
        original = self.temp / drafted["path"]
        impostor = original.with_name("Impostor.md")
        impostor.write_text(original.read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaises(store.StoreError) as raised:
            result = self.check("HEAD")
            self.fail(f"the collision was not detected: {result}")
        self.assertIn(f"identity {drafted['identity']} resolves to two files", str(raised.exception))

    def test_an_unanswerable_ref_degrades_to_a_full_check(self) -> None:
        self.approved_entry()
        self.commit()
        result = self.check("no-such-ref")
        self.assertEqual(0, result["entriesSkipped"])
        self.assertIn("git could not report changes", result["gap"])

    def test_full_is_the_default_and_skips_nothing(self) -> None:
        self.approved_entry()
        self.commit()
        result = self.check()
        self.assertNotIn("entriesSkipped", result)
        self.assertNotIn("changedSince", result)

    def test_entry_check_writes_nothing(self) -> None:
        # A read-only gate that acquired a writer would put a new integrity hole inside the
        # command whose job is integrity.
        self.approved_entry()
        self.commit()
        before = {path: path.read_bytes() for path in sorted(self.temp.rglob("*")) if path.is_file()}
        self.check("HEAD")
        after = {path: path.read_bytes() for path in sorted(self.temp.rglob("*")) if path.is_file()}
        self.assertEqual(before, after)


class PathDerivedIdentityTests(KnowledgeStoreFixture):
    """An identity read off a path is what makes the whole-entry skip possible — and it is only
    allowed when the path can prove it. `entry_path()` derives the path FROM the identity, so
    the inverse is exact for plain ASCII names and lossy for everything else; the lossy cases
    must fall back to parsing rather than guess."""

    def test_a_plain_entry_path_round_trips_to_its_identity(self) -> None:
        drafted = self.draft()
        path = self.temp / drafted["path"]
        self.assertEqual(drafted["identity"], store.identity_from_entry_path(path))

    def test_an_escaped_or_truncated_name_refuses_to_answer(self) -> None:
        for full_name in ("Odd Name__c", "Ünicode__c", "A" * 120):
            with self.subTest(fullName=full_name):
                path = store.entry_path("Flow", None, full_name)
                self.assertIsNone(
                    store.identity_from_entry_path(path),
                    f"{full_name} claimed an identity its path cannot prove",
                )

    def test_a_path_outside_the_artifact_corpus_refuses_to_answer(self) -> None:
        self.assertIsNone(store.identity_from_entry_path(store.FEATURES_ROOT / "scheduling.md"))
        self.assertIsNone(store.identity_from_entry_path(store.ARTIFACTS_ROOT / "Flow" / "loose.md"))


class ReleaseCycleMaintenanceTests(KnowledgeStoreFixture):
    """One batch queue per release cycle, and a clock that never expires an approval.

    The failure mode this guards against is a maintenance report that behaves like a nag: a
    list of entries "due for review" because they are old. Under owner decision D4 age is a
    reporting dimension and nothing else — an approval does not decay, so an old
    `approved-current` entry generates no question at all, and an old drifted one generates an
    OPTION, not a task.
    """

    def rows(self, *specs) -> list[dict]:
        return [
            {
                "identity": identity,
                "lane": lane,
                "reviewedAt": "2026-01-01T00:00:00Z",
                "ageDays": age,
                "changedPaths": ["force-app/x.flow-meta.xml"] if lane == "approved-drifted" else [],
                "problemCodes": ["SOURCE_FRAGMENT_MISSING"] if lane == "not-effective" else [],
                "problemPaths": ["force-app/gone.flow-meta.xml"] if lane == "not-effective" else [],
            }
            for identity, lane, age in specs
        ]

    @property
    def now(self):
        return store.datetime(2026, 8, 11, tzinfo=store.timezone.utc)

    def test_age_alone_never_produces_a_question(self) -> None:
        summary = store.maintenance_summary(
            self.rows(
                ("Flow:c:Fresh", "approved-current", 3),
                ("Flow:c:Ancient", "approved-current", 900),
            ),
            30,
            self.now,
        )
        counts = summary["counts"]
        self.assertEqual(2, counts["currentNoAction"])
        # The old one is COUNTED so the shape of the corpus is visible...
        self.assertEqual(1, counts["olderCurrentNoAction"])
        # ...and listed NOWHERE, because a list is an implicit ask.
        self.assertEqual([], summary["optionalRefresh"])
        self.assertEqual([], summary["requiresDecision"])
        self.assertEqual("age never expires approval", summary["policy"])

    def test_drifted_splits_on_the_cycle_into_disclosure_and_option(self) -> None:
        summary = store.maintenance_summary(
            self.rows(
                ("Flow:c:RecentDrift", "approved-drifted", 5),
                ("Flow:c:OldDrift", "approved-drifted", 45),
            ),
            30,
            self.now,
        )
        self.assertEqual(1, summary["counts"]["driftedDisclosureOnly"])
        self.assertEqual(1, summary["counts"]["optionalRefresh"])
        self.assertEqual(
            ["Flow:c:OldDrift"], [item["identity"] for item in summary["optionalRefresh"]]
        )
        # It carries what a maintainer needs to decide — and no instruction to re-approve.
        entry = summary["optionalRefresh"][0]
        self.assertEqual(["force-app/x.flow-meta.xml"], entry["changedPaths"])
        self.assertEqual("approved-drifted", entry["lane"])
        self.assertEqual(45, entry["ageDays"])
        # Old drift is an option, never a blocker: it stays out of requiresDecision entirely.
        self.assertEqual([], summary["requiresDecision"])

    def test_broken_evidence_requires_a_decision_regardless_of_age(self) -> None:
        summary = store.maintenance_summary(
            self.rows(("Flow:c:Gone", "not-effective", 1)), 30, self.now
        )
        self.assertEqual(1, summary["counts"]["requiresDecision"])
        decision = summary["requiresDecision"][0]
        self.assertEqual(["SOURCE_FRAGMENT_MISSING"], decision["problemCodes"])
        self.assertEqual(["force-app/gone.flow-meta.xml"], decision["paths"])

    def test_lists_are_capped_and_say_so_while_counts_stay_complete(self) -> None:
        many = self.rows(*[(f"Flow:c:Drift{index:03d}", "approved-drifted", 100) for index in range(60)])
        summary = store.maintenance_summary(many, 30, self.now)
        self.assertEqual(60, summary["counts"]["optionalRefresh"])
        self.assertEqual(store.MAINTENANCE_LIST_CAP, len(summary["optionalRefresh"]))
        # A truncated list that does not say it is truncated reads as "that is all of them".
        self.assertEqual(60, summary["listTruncation"]["fullCounts"]["optionalRefresh"])

    def test_the_report_is_deterministic_and_takes_its_clock_as_input(self) -> None:
        rows = self.rows(("Flow:c:B", "approved-drifted", 60), ("Flow:c:A", "approved-drifted", 60))
        first = store.maintenance_summary(rows, 30, self.now)
        second = store.maintenance_summary(rows, 30, self.now)
        self.assertEqual(first, second)
        self.assertEqual("2026-08-11T00:00:00Z", first["asOf"])
        # Ties break on identity, so the queue does not reshuffle between runs.
        self.assertEqual(["Flow:c:A", "Flow:c:B"], [item["identity"] for item in first["optionalRefresh"]])

    def test_entry_coverage_carries_the_summary_and_writes_nothing(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        ledger_before = store.LEDGER_PATH.read_bytes()
        entry_before = (self.temp / drafted["path"]).read_bytes()
        result = store.command_entry_coverage(argparse.Namespace(review_cycle_days=30))
        self.assertEqual(30, result["maintenance"]["reviewCycleDays"])
        self.assertEqual(1, result["maintenance"]["counts"]["currentNoAction"])
        # D5: the maintenance pass is read-only. Nothing is refreshed, re-pinned or recorded.
        self.assertEqual(ledger_before, store.LEDGER_PATH.read_bytes())
        self.assertEqual(entry_before, (self.temp / drafted["path"]).read_bytes())


class StructuredFactsDeltaTests(unittest.TestCase):
    """The diff between two canonical facts payloads: keyed where identity exists, positional
    where order is semantic, and paths only — never values.

    Two properties carry the whole feature. Ordering-only differences must be invisible, or the
    report becomes a stream of false maintenance the moment a collector changes enumeration
    order; and the delta must be non-empty exactly when the digests differ, or a maintainer
    reading `FACTS_CHANGED` with no paths cannot tell a real change from a broken comparison.
    """

    def facts(self, **overrides):
        base = {
            "typeFacts": {"status": "Active", "references": [], "variables": []},
            "intentionalErrors": [],
            "limitations": [],
            "extractionCoverage": {"typeFacts": "full"},
            "assurance": {"typeFacts": "source-exact"},
        }
        base.update(overrides)
        return base

    def test_identical_facts_produce_no_paths(self) -> None:
        delta = store.structured_facts_delta(self.facts(), self.facts())
        self.assertEqual([], delta["deltaPaths"])
        self.assertEqual([], delta["changedSections"])
        self.assertEqual({"added": 0, "removed": 0, "changed": 0}, delta["deltaCounts"])

    def test_reordered_keyed_lists_and_scalar_sets_are_not_a_change(self) -> None:
        references = [
            {"kind": "writes-field", "target": "A__c.B__c", "assurance": "source-exact"},
            {"kind": "queries-object", "target": "A__c", "assurance": "source-exact"},
        ]
        variables = [{"apiName": "beta"}, {"apiName": "alpha"}]
        stored = self.facts(
            typeFacts={"references": list(references), "variables": list(variables)},
            limitations=["one", "two"],
        )
        current = self.facts(
            typeFacts={
                "references": list(reversed(references)), "variables": list(reversed(variables))
            },
            limitations=["two", "one"],
        )
        self.assertEqual([], store.structured_facts_delta(stored, current)["deltaPaths"])

    def test_operations_are_positional_because_execution_order_is_semantic(self) -> None:
        first = {"kind": "recordLookup", "object": "A__c", "elementApiName": "Get"}
        second = {"kind": "recordUpdate", "object": "A__c", "elementApiName": "Set"}
        stored = self.facts(typeFacts={"operations": [first, second]})
        current = self.facts(typeFacts={"operations": [second, first]})
        delta = store.structured_facts_delta(stored, current)
        self.assertTrue(delta["deltaPaths"], "a reordered operation list is a changed flow")
        self.assertTrue(all("/typeFacts/operations/" in row["path"] for row in delta["deltaPaths"]))

    def test_an_added_reference_names_its_composite_key_not_an_index(self) -> None:
        stored = self.facts(typeFacts={"references": []})
        current = self.facts(typeFacts={
            "references": [{"kind": "writes-field", "target": "Account.Status__c",
                            "assurance": "source-exact"}]
        })
        delta = store.structured_facts_delta(stored, current)
        self.assertEqual(
            [{"op": "added", "path": "/typeFacts/references/writes-field:Account.Status__c",
              "valueType": "object"}],
            delta["deltaPaths"],
        )
        self.assertEqual(["typeFacts"], delta["changedSections"])

    def test_assurance_and_coverage_regressions_are_reported(self) -> None:
        delta = store.structured_facts_delta(
            self.facts(),
            self.facts(assurance={"typeFacts": "source-derived-heuristic"},
                       extractionCoverage={"typeFacts": "partial"}),
        )
        paths = {row["path"] for row in delta["deltaPaths"]}
        self.assertEqual({"/assurance/typeFacts", "/extractionCoverage/typeFacts"}, paths)
        self.assertEqual(["assurance", "extractionCoverage"], delta["changedSections"])
        self.assertEqual(2, delta["deltaCounts"]["changed"])

    def test_intentional_error_changes_are_keyed_by_element(self) -> None:
        error = {"kind": "flow-custom-error", "elementApiName": "Block", "messageTemplate": "no",
                 "presentation": {"mode": "record"}}
        moved = {**error, "presentation": {"mode": "field", "field": "Status__c"}}
        delta = store.structured_facts_delta(
            self.facts(intentionalErrors=[error]), self.facts(intentionalErrors=[moved])
        )
        self.assertEqual(
            {"/intentionalErrors/flow-custom-error:Block/presentation/field",
             "/intentionalErrors/flow-custom-error:Block/presentation/mode"},
            {row["path"] for row in delta["deltaPaths"]},
        )

    def test_pointer_escaping_follows_rfc_6901(self) -> None:
        stored = self.facts(typeFacts={})
        current = self.facts(typeFacts={"a/b": 1, "c~d": 2})
        paths = {row["path"] for row in store.structured_facts_delta(stored, current)["deltaPaths"]}
        self.assertEqual({"/typeFacts/a~1b", "/typeFacts/c~0d"}, paths)
        # `~` is escaped before `/`, or the escape eats itself.
        self.assertEqual("~01", store._pointer_segment("~1"))

    def test_no_path_row_carries_a_value(self) -> None:
        """D9: the delta is paths, ops and JSON types. Copying old/new values would put picklist
        values, formulas and error message text into a maintenance report."""

        delta = store.structured_facts_delta(
            self.facts(), self.facts(typeFacts={"status": "SECRET-VALUE", "references": [],
                                                "variables": []})
        )
        blob = json.dumps(delta)
        self.assertNotIn("SECRET-VALUE", blob)
        self.assertEqual({"op", "path", "valueType"}, set(delta["deltaPaths"][0]))

    def test_the_path_list_is_capped_while_the_count_stays_complete(self) -> None:
        wide = {f"field{index:03d}": index for index in range(store.FACT_DELTA_PATH_CAP + 25)}
        delta = store.structured_facts_delta(self.facts(typeFacts={}), self.facts(typeFacts=wide))
        self.assertEqual(store.FACT_DELTA_PATH_CAP, len(delta["deltaPaths"]))
        self.assertTrue(delta["deltaTruncated"])
        self.assertEqual(store.FACT_DELTA_PATH_CAP + 25, delta["deltaPathCount"])
        self.assertEqual(store.FACT_DELTA_PATH_CAP + 25, delta["deltaCounts"]["added"])

    def test_the_delta_is_non_empty_exactly_when_the_digest_moves(self) -> None:
        pairs = [
            (self.facts(), self.facts()),
            (self.facts(), self.facts(assurance={"typeFacts": "source-derived-heuristic"})),
            (self.facts(limitations=["a", "b"]), self.facts(limitations=["b", "a"])),
            (self.facts(limitations=["a"]), self.facts(limitations=["a", "b"])),
            (self.facts(typeFacts={"operations": [{"kind": "recordLookup"}]}),
             self.facts(typeFacts={"operations": []})),
        ]
        for stored, current in pairs:
            with self.subTest(stored=stored, current=current):
                digests_differ = store.facts_digest(stored) != store.facts_digest(current)
                delta = store.structured_facts_delta(
                    store._canonical_facts(stored), store._canonical_facts(current)
                )
                self.assertEqual(digests_differ, bool(delta["deltaPaths"]))

    def test_paths_are_sorted_so_two_runs_agree(self) -> None:
        current = self.facts(typeFacts={"zeta": 1, "alpha": 2, "mu": 3})
        first = store.structured_facts_delta(self.facts(typeFacts={}), current)
        second = store.structured_facts_delta(self.facts(typeFacts={}), current)
        self.assertEqual(first, second)
        self.assertEqual(
            sorted(row["path"] for row in first["deltaPaths"]),
            [row["path"] for row in first["deltaPaths"]],
        )


class FactAnalysisTests(KnowledgeStoreFixture):
    """`entry-coverage --analyze-facts`: does today's collector still derive the approved facts?

    Byte drift cannot answer that question — a reformatted XML and a deleted comment both drift —
    and neither can a version comparison, because an adapter edited without a COLLECTOR_VERSION
    bump changes what is derived while every recorded version still matches. So the facts are
    re-derived from current source and compared at the exact `factsDigest` boundary.

    The invariants these tests exist to hold: a failure is NEVER counted as equivalent; the
    analysis changes no lane, no approval and no file; and none of it runs without the flag.
    """

    FLOW_FRAGMENT = "force-app/main/default/flows/HarnessAlphaRouter.flow-meta.xml"

    def setUp(self) -> None:
        super().setUp()
        self.flow = self.draft()
        self.field = self.draft(
            metadata_type="CustomField", full_name="HarnessAlphaCase__c.Status__c"
        )
        self.approve([
            f"{item['identity']}:{item['reviewedContentDigest']}" for item in (self.flow, self.field)
        ])

    def coverage(self, **overrides):
        args = argparse.Namespace(review_cycle_days=30, analyze_facts=None)
        for key, value in overrides.items():
            setattr(args, key, value)
        return store.command_entry_coverage(args)

    def drift_flow_comment_only(self) -> None:
        """A source edit the collector cannot see: bytes move, derived facts do not."""
        path = self.temp / self.FLOW_FRAGMENT
        path.write_text(
            path.read_text(encoding="utf-8") + "<!-- reformatted after approval -->\n",
            encoding="utf-8",
        )

    def drift_flow_materially(self) -> None:
        path = self.temp / self.FLOW_FRAGMENT
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "<status>Active</status>", "<status>Draft</status>"
            ),
            encoding="utf-8",
        )

    # --- D3: no cost, and no output, without the flag ---------------------------------

    def test_without_the_flag_no_analysis_runs_and_no_block_appears(self) -> None:
        def explode(*args, **kwargs):
            raise AssertionError("the analyzer ran on a plain coverage call")

        with unittest.mock.patch.object(store, "fact_analysis_report", explode):
            result = self.coverage()
        self.assertNotIn("factAnalysis", result)
        self.assertIn("maintenance", result)

    def test_an_absent_attribute_is_the_same_as_no_flag(self) -> None:
        # Every existing caller constructs the namespace without the new field.
        result = store.command_entry_coverage(argparse.Namespace(review_cycle_days=30))
        self.assertNotIn("factAnalysis", result)

    # --- modes and eligibility ---------------------------------------------------------

    def test_drifted_mode_analyzes_drifted_entries_only(self) -> None:
        self.drift_flow_comment_only()
        analysis = self.coverage(analyze_facts="drifted")["factAnalysis"]
        self.assertEqual("drifted", analysis["mode"])
        self.assertEqual(1, analysis["counts"]["eligible"])
        self.assertEqual([self.flow["identity"]],
                         [row["identity"] for row in analysis["factsEquivalent"]])
        # The approved-current field entry is excluded BY MODE, not by effectiveness.
        self.assertEqual({"ENTRY_NOT_SELECTED_BY_MODE": 1}, analysis["excludedCounts"])
        self.assertEqual(1, analysis["counts"]["excluded"])

    def test_a_comment_only_edit_is_drift_but_not_a_fact_change(self) -> None:
        self.drift_flow_comment_only()
        analysis = self.coverage(analyze_facts="drifted")["factAnalysis"]
        [row] = analysis["factsEquivalent"]
        self.assertEqual("FACTS_EQUIVALENT", row["analysisCode"])
        self.assertEqual("approved-drifted", row["lane"])
        self.assertIs(True, row["effective"], "drift never withdraws effectiveness (D2)")
        self.assertEqual("drifted", row["sourceFreshness"])
        self.assertEqual(row["storedFactsDigest"], row["currentFactsDigest"])
        # The claim is exactly "the extracted facts did not move" — never "nothing changed".
        self.assertIn("no extracted-fact change", row["interpretation"])
        self.assertNotIn("semantic", row["interpretation"])

    def test_a_material_source_change_is_reported_as_changed_with_paths(self) -> None:
        self.drift_flow_materially()
        analysis = self.coverage(analyze_facts="drifted")["factAnalysis"]
        [row] = analysis["factsChanged"]
        self.assertEqual("FACTS_CHANGED", row["analysisCode"])
        self.assertNotEqual(row["storedFactsDigest"], row["currentFactsDigest"])
        self.assertEqual(["typeFacts"], row["changedSections"])
        self.assertEqual([{"op": "changed", "path": "/typeFacts/status", "valueType": "string"}],
                         row["deltaPaths"])
        self.assertFalse(row["deltaTruncated"])
        self.assertEqual(0, analysis["counts"]["equivalent"])
        self.assertEqual(1, analysis["counts"]["changed"])

    def test_facts_changed_moves_no_lane_and_withdraws_no_approval(self) -> None:
        """D2 in the only form that matters: after the report, the store answers exactly as it
        did before it. `FACTS_CHANGED` is a finding, not a verdict and not a blocker."""

        self.drift_flow_materially()
        before = self.lane_of(self.flow["identity"])
        self.coverage(analyze_facts="all-approved")
        after = self.lane_of(self.flow["identity"])
        self.assertEqual(before, after)
        self.assertEqual("approved-drifted", after["lane"])
        self.assertTrue(after["effective"])

    def test_all_approved_covers_both_lanes(self) -> None:
        self.drift_flow_comment_only()
        analysis = self.coverage(analyze_facts="all-approved")["factAnalysis"]
        self.assertEqual(2, analysis["counts"]["eligible"])
        self.assertEqual(2, analysis["counts"]["equivalent"])
        self.assertEqual({}, analysis["excludedCounts"])
        self.assertEqual(
            {"approved-current", "approved-drifted"},
            {row["lane"] for row in analysis["factsEquivalent"]},
        )

    def test_all_approved_catches_an_assurance_change_on_untouched_source(self) -> None:
        """The drift no other mechanism can see: source bytes identical, every recorded
        collector version identical, and what the collector DERIVES has changed. `drifted` mode
        cannot find it by construction, which is why the release-time mode exists."""

        real = store.ADAPTERS["Flow"]

        def weakened(component):
            type_facts, errors, _assurance = real(component)
            return type_facts, errors, {"typeFacts": "source-derived-heuristic"}

        with unittest.mock.patch.dict(store.ADAPTERS, {"Flow": weakened}):
            drifted_mode = self.coverage(analyze_facts="drifted")["factAnalysis"]
            all_approved = self.coverage(analyze_facts="all-approved")["factAnalysis"]
        self.assertEqual(0, drifted_mode["counts"]["eligible"], "no entry is source-drifted")
        [row] = all_approved["factsChanged"]
        self.assertEqual(self.flow["identity"], row["identity"])
        self.assertEqual("approved-current", row["lane"])
        self.assertEqual("current", row["sourceFreshness"])
        self.assertEqual(["assurance"], row["changedSections"])
        self.assertEqual(row["storedCollectorVersion"],
                         all_approved["basis"]["currentCollectorVersion"])

    def test_a_draft_or_revoked_entry_is_excluded_and_counted_never_compared(self) -> None:
        store.command_entry_revoke(
            argparse.Namespace(identity=self.field["identity"], rationale="test")
        )
        self.draft(metadata_type="ApexClass", full_name="HarnessAlphaService")  # stays draft
        analysis = self.coverage(analyze_facts="all-approved")["factAnalysis"]
        self.assertEqual(2, analysis["excludedCounts"]["ENTRY_NOT_EFFECTIVE"])
        self.assertEqual(1, analysis["counts"]["eligible"])
        analyzed = {row["identity"] for row in
                    analysis["factsEquivalent"] + analysis["factsChanged"] + analysis["analysisFailures"]}
        self.assertEqual({self.flow["identity"]}, analyzed)

    def test_a_missing_source_fragment_stays_a_decision_and_is_never_equivalent(self) -> None:
        # D3: missing evidence is not drift. The entry leaves the effective lanes, so it is
        # excluded from the comparison and stays in the maintenance queue that asks for a human.
        (self.temp / self.FLOW_FRAGMENT).unlink()
        result = self.coverage(analyze_facts="all-approved")
        analysis = result["factAnalysis"]
        classified = {row["identity"] for row in analysis["factsEquivalent"]
                      + analysis["factsChanged"] + analysis["analysisFailures"]}
        self.assertNotIn(self.flow["identity"], classified)
        self.assertEqual(1, analysis["excludedCounts"]["ENTRY_NOT_EFFECTIVE"])
        self.assertEqual(
            [self.flow["identity"]],
            [row["identity"] for row in result["maintenance"]["requiresDecision"]],
        )

    # --- failures are never equivalence ------------------------------------------------

    def test_an_entry_whose_component_vanished_from_the_inventory_is_a_failure(self) -> None:
        real = store.ForceAppKnowledge if hasattr(store, "ForceAppKnowledge") else None
        self.assertIsNone(real, "the collector must stay a local import, not a module attribute")
        from scripts import force_app_knowledge

        original = force_app_knowledge.ForceAppKnowledge.inventory

        def without_the_flow(self_inner, *args, **kwargs):
            inventory = original(self_inner, *args, **kwargs)
            return {
                **inventory,
                "components": [
                    component for component in inventory["components"]
                    if component.get("metadataType") != "Flow"
                ],
            }

        with unittest.mock.patch.object(
            force_app_knowledge.ForceAppKnowledge, "inventory", without_the_flow
        ):
            analysis = self.coverage(analyze_facts="all-approved")["factAnalysis"]
        failures = [row for row in analysis["analysisFailures"]
                    if row["identity"] == self.flow["identity"]]
        self.assertEqual(["ENTRY_COMPONENT_NOT_FOUND"], [row["analysisCode"] for row in failures])
        self.assertEqual(1, analysis["counts"]["unavailable"])
        self.assertNotIn(self.flow["identity"],
                         {row["identity"] for row in analysis["factsEquivalent"]})

    def test_an_unavailable_inventory_reports_failure_rather_than_a_clean_zero(self) -> None:
        from scripts import force_app_knowledge

        def broken(*args, **kwargs):
            raise RuntimeError("source tree unreadable")

        with unittest.mock.patch.object(
            force_app_knowledge.ForceAppKnowledge, "inventory", broken
        ):
            result = self.coverage(analyze_facts="all-approved")
        analysis = result["factAnalysis"]
        self.assertEqual(0, analysis["counts"]["equivalent"])
        self.assertEqual(2, analysis["counts"]["unavailable"])
        self.assertIn("source tree unreadable", analysis["unavailableReason"])
        self.assertEqual(
            {"REEXTRACTION_UNAVAILABLE"}, {row["analysisCode"] for row in analysis["analysisFailures"]}
        )

    def test_a_candidate_outside_the_entrys_profile_is_invalid_not_changed(self) -> None:
        """A re-extraction the entry's own profile schema refuses is not evidence of drift — it
        is evidence the pipeline and the profile disagree, and phase 2 does not migrate schemas."""

        def off_profile(component):
            return {"status": ["not", "a", "string"]}, [], {"typeFacts": "source-exact"}

        with unittest.mock.patch.dict(store.ADAPTERS, {"Flow": off_profile}):
            analysis = self.coverage(analyze_facts="all-approved")["factAnalysis"]
        [row] = [item for item in analysis["analysisFailures"]
                 if item["identity"] == self.flow["identity"]]
        self.assertEqual("REEXTRACTION_INVALID", row["analysisCode"])
        self.assertEqual(1, analysis["counts"]["invalid"])
        self.assertIn("salesforce.flow@1.0.0", row["profile"])
        self.assertTrue(row["reason"])

    def test_a_collector_crash_is_a_controlled_failure(self) -> None:
        def crash(component):
            raise ValueError("adapter blew up")

        with unittest.mock.patch.dict(store.ADAPTERS, {"Flow": crash}):
            analysis = self.coverage(analyze_facts="all-approved")["factAnalysis"]
        [row] = [item for item in analysis["analysisFailures"]
                 if item["identity"] == self.flow["identity"]]
        self.assertEqual("REEXTRACTION_ERROR", row["analysisCode"])
        self.assertIn("adapter blew up", row["reason"])
        self.assertEqual(1, analysis["counts"]["error"])

    def test_every_row_is_classified_exactly_once_and_the_counts_add_up(self) -> None:
        self.drift_flow_materially()
        analysis = self.coverage(analyze_facts="all-approved")["factAnalysis"]
        counts = analysis["counts"]
        self.assertEqual(
            counts["analyzed"],
            counts["equivalent"] + counts["changed"] + counts["unavailable"] + counts["invalid"]
            + counts["error"],
        )
        self.assertEqual(counts["eligible"], counts["analyzed"])

    # --- batch shape, determinism, cost ------------------------------------------------

    def test_one_inventory_pass_and_no_per_entry_collector_lookup(self) -> None:
        """The N x scan runtime this command was rebuilt to avoid. `collector_component()`
        re-checks the source tree digest and may rebuild the whole inventory, so calling it once
        per entry restores exactly the cost the batch pass exists to remove."""

        from scripts import force_app_knowledge

        calls: list[str] = []
        original = force_app_knowledge.ForceAppKnowledge.inventory

        def counting(self_inner, *args, **kwargs):
            calls.append("inventory")
            return original(self_inner, *args, **kwargs)

        def forbidden(*args, **kwargs):
            raise AssertionError("collector_component() was called per entry")

        with unittest.mock.patch.object(
            force_app_knowledge.ForceAppKnowledge, "inventory", counting
        ), unittest.mock.patch.object(store, "collector_component", forbidden):
            self.coverage(analyze_facts="all-approved")
        self.assertEqual(1, len(calls))

    def test_two_runs_over_the_same_source_produce_the_same_block(self) -> None:
        self.drift_flow_materially()
        first = self.coverage(analyze_facts="all-approved")["factAnalysis"]
        second = self.coverage(analyze_facts="all-approved")["factAnalysis"]
        self.assertEqual(first, second)

    def test_lists_are_capped_while_counts_describe_the_population(self) -> None:
        # The classification itself is exercised above; this pins the batch envelope, so the
        # 60-row population is built by stubbing the per-entry analysis rather than by drafting
        # 60 fixtures (which would measure the collector, not the report).
        candidates = [
            (Path(f"entry-{index:03d}.md"), {"identity": f"Flow:c:Entry{index:03d}",
                                             "lane": "approved-drifted", "effective": True,
                                             "freshness": "drifted"})
            for index in range(60)
        ]

        def classify(path, lane, components):
            return {"identity": lane["identity"], "lane": lane["lane"], "effective": True,
                    "analysisCode": "FACTS_CHANGED"}

        with unittest.mock.patch.object(store, "analyze_entry_facts", classify):
            report = store.fact_analysis_report(
                "drifted", candidates, {}, {}, source_tree_digest="sha256:x"
            )
        self.assertEqual(60, report["counts"]["changed"])
        self.assertEqual(store.FACT_ANALYSIS_LIST_CAP, len(report["factsChanged"]))
        self.assertEqual(60, report["listTruncation"]["fullCounts"]["factsChanged"])
        self.assertEqual(store.FACT_ANALYSIS_LIST_CAP, report["listTruncation"]["cap"])
        # Sorted by identity, so the capped window is the same window on every run.
        self.assertEqual(
            [row["identity"] for row in report["factsChanged"]],
            sorted(row["identity"] for row in report["factsChanged"]),
        )

    def test_an_empty_corpus_answers_with_zeros_and_a_basis(self) -> None:
        for path in store.all_entry_paths():
            path.unlink()
        store.LEDGER_PATH.unlink()
        analysis = self.coverage(analyze_facts="all-approved")["factAnalysis"]
        self.assertEqual(0, analysis["counts"]["eligible"])
        self.assertEqual([], analysis["factsEquivalent"])
        self.assertTrue(analysis["basis"]["currentCollectorVersion"])
        self.assertTrue(analysis["basis"]["sourceTreeDigest"])
        self.assertIn(analysis["basis"]["workspaceStatus"], {"clean", "dirty", "unknown"})

    def test_the_report_states_its_own_boundary(self) -> None:
        analysis = self.coverage(analyze_facts="all-approved")["factAnalysis"]
        self.assertEqual(store.FACT_ANALYSIS_POLICY, analysis["policy"])
        self.assertIn("factsDigest", analysis["basis"]["comparedAt"])
        # The one sentence that must never be simplified into "the source did not change".
        self.assertIn("not that the artifact is", analysis["note"])
        self.assertIn("Purpose", analysis["note"])

    # --- D1/D12: the whole point is that it writes nothing ------------------------------

    def snapshot(self) -> dict[str, bytes]:
        """Every byte in the workspace except git internals and the derived inventory cache.

        Keys are POSIX, never `str(Path)`: the team runs Windows, where the native form is
        `.ai\\knowledge\\…` and every path assertion below silently stops matching. The bytes
        comparison would still have worked — but only by luck, because both snapshots would key
        the same way, so the test would have kept passing while its explicit
        "the ledger is in here" precondition quietly asserted nothing (caught by CI on
        windows-latest, 2026-08-11)."""

        return {
            path.relative_to(self.temp).as_posix(): path.read_bytes()
            for path in sorted(self.temp.rglob("*"))
            if path.is_file()
            and ".git/" not in path.relative_to(self.temp).as_posix() + "/"
            and not path.relative_to(self.temp).as_posix().startswith(".cache/")
        }

    def test_the_analysis_writes_nothing_authoritative(self) -> None:
        """The no-write proof, by bytes rather than by inspection: entries, the approval ledger,
        force-app source, config and any feature/org ledger are identical after both modes run.

        The one permitted change is `.cache/knowledge-proposals/` — the collector's derived
        inventory, which `entry-coverage` already refreshed before phase 2, is not authority and
        cannot be cited. Nothing else moves, and in particular no source pin is refreshed even
        when the facts come back equivalent (D12) and no approval artifact is produced."""

        self.drift_flow_materially()
        before = self.snapshot()
        self.assertIn(".ai/knowledge/artifacts-ledger.jsonl", before)
        self.assertTrue(any(name.startswith("force-app/") for name in before))
        for mode in store.FACT_ANALYSIS_MODES:
            with self.subTest(mode=mode):
                self.coverage(analyze_facts=mode)
                self.assertEqual(before, self.snapshot(), f"{mode} wrote to the workspace")
        # A refreshed source pin is the specific write a "the facts still match" result would
        # most plausibly tempt an implementer into (D12).
        front, _ = store.split_entry((self.temp / self.flow["path"]).read_text(encoding="utf-8"))
        freshness = store.source_fragment_freshness(front)
        self.assertEqual("drifted", freshness["status"], "the source pin was silently refreshed")
        # The approvals directory is non-empty because setUp approved through it; what must not
        # happen is the analysis ADDING an artifact of its own, so the file set is pinned too.
        approvals = [name for name in self.snapshot() if name.startswith("output/knowledge-approvals/")]
        self.assertEqual(
            [name for name in before if name.startswith("output/knowledge-approvals/")], approvals
        )

    def test_the_analysis_never_guesses_why_the_facts_moved(self) -> None:
        # D7: source and pipeline can move together, and an un-bumped adapter contradicts the
        # version, so the report shows the coordinates and refuses to name a cause.
        self.drift_flow_materially()
        analysis = self.coverage(analyze_facts="drifted")["factAnalysis"]
        [row] = analysis["factsChanged"]
        self.assertNotIn("changeOrigin", row)
        self.assertIn("storedCollectorVersion", row)
        self.assertIn("currentCollectorVersion", analysis["basis"])
        self.assertIn("sourceFreshness", row)
