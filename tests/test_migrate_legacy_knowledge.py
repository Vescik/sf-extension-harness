"""Disposable tests for the temporary legacy Knowledge migration kit.

These tests are part of the migration kit (master plan 2026-08-11 §11) and are removed with
`migrate_legacy_knowledge.py` and its guide before the final Knowledge-only commit. They run
against throwaway fixture corpora and a stubbed fake target — never a real org, ADO, MCP, or
the actual legacy checkout.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "migrate_legacy_knowledge", ROOT / "migrate_legacy_knowledge.py"
)
kit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(kit)


STORE_STUB = '''#!/usr/bin/env python3
"""knowledge_store stub: records calls; entry-draft/describe simulate the real writer."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
CALLS = ROOT / "calls.jsonl"
FAIL = ROOT / "fail-on.json"
argv = sys.argv[1:]
with CALLS.open("a", encoding="utf-8") as h:
    h.write(json.dumps(argv) + "\\n")
fail_on = json.loads(FAIL.read_text()) if FAIL.is_file() else {}
command = argv[0] if argv else ""
def flag(name):
    return argv[argv.index(name) + 1] if name in argv else None
if fail_on.get(command) and fail_on[command] in " ".join(argv):
    print("stub failure for " + command, file=sys.stderr)
    raise SystemExit(1)
if command == "entry-draft":
    mt, fn = flag("--metadata-type"), flag("--full-name")
    ns = flag("--namespace") or "c"
    path = ROOT / ".ai/knowledge/artifacts" / mt / ns / (fn + ".md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\\n"
        + "subject:\\n  metadataType: " + mt + "\\n  fullName: " + fn + "\\n  namespace: "
        + ("null" if ns == "c" else ns) + "\\n"
        + "lifecycle:\\n  state: draft\\n  contentDigest: sha256:stub" + fn + "\\n"
        + "---\\n\\n## Purpose\\n\\n<AGENT_DESCRIPTION>\\n",
        encoding="utf-8",
    )
    print(json.dumps({"outcome": "DRAFTED", "identity": mt + ":" + ns + ":" + fn}))
elif command == "entry-describe":
    print(json.dumps({"outcome": "DESCRIBED", "identity": flag("--identity")}))
elif command == "entry-status":
    print(json.dumps({"entries": [{"identity": flag("--identity"), "state": "draft"}]}))
elif command == "entry-review":
    print("review artifact: output/review/stub.md")
    print("approve with: python scripts/knowledge_store.py entry-approve --entry <id>:sha256:x")
else:
    print(json.dumps({"outcome": "STUB-" + command}))
'''

RESOLVE_STUB = '''#!/usr/bin/env python3
COLLECTOR_VERSION = "9.9.9-stub"
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
mapping = json.loads((ROOT / "resolve-map.json").read_text())
name = sys.argv[sys.argv.index("--name") + 1] if "--name" in sys.argv else ""
components = mapping.get(name, [])
print(json.dumps({"components": components, "selections": [
    {"input": name, "kind": "name",
     "resolution": "matched" if components else "unmatched"}]}))
'''
# read_collector_version reads the real file's constant line; keep the stub's regex-visible.
RESOLVE_STUB = RESOLVE_STUB.replace(
    'COLLECTOR_VERSION = "9.9.9-stub"', 'COLLECTOR_VERSION = "9.9.9-stub"', 1
)


def entry_text(metadata_type: str, full_name: str, purpose: str | None,
               fragment: tuple[str, str] | None = None,
               content_digest: str = "sha256:legacy", limitations: list[str] | None = None) -> str:
    frag = ""
    if fragment:
        frag = (
            "source:\n  fragments:\n"
            f"  - path: {fragment[0]}\n    sourceDigest: {fragment[1]}\n"
        )
    lims = ""
    if limitations:
        lims = "limitations:\n" + "".join(f"- {item}\n" for item in limitations)
    body = f"## Purpose\n\n{purpose}\n" if purpose else "## Purpose\n\n<AGENT_DESCRIPTION>\n"
    return (
        "---\n"
        f"subject:\n  metadataType: {metadata_type}\n  fullName: {full_name}\n  namespace: null\n"
        "profile:\n  id: salesforce.apex\n  version: 1.0.0\n"
        f"lifecycle:\n  state: approved\n  contentDigest: {content_digest}\n"
        f"{frag}{lims}"
        "---\n\n" + body
    )


class KitFixture(unittest.TestCase):
    """Builds a disposable fake target (git repo + stub executors) and legacy corpora."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.target = base / "fake-target"
        (self.target / "scripts").mkdir(parents=True)
        (self.target / "force-app").mkdir()
        (self.target / "force-app" / "Foo.cls").write_text("class Foo {}\n", encoding="utf-8")
        (self.target / "scripts" / "knowledge_store.py").write_text(STORE_STUB, encoding="utf-8")
        (self.target / "scripts" / "force_app_knowledge.py").write_text(
            RESOLVE_STUB, encoding="utf-8"
        )
        (self.target / "resolve-map.json").write_text("{}", encoding="utf-8")
        (self.target / ".gitignore").write_text(
            "output/\ncalls.jsonl\nfail-on.json\nresolve-map.json\n.ai/\n", encoding="utf-8"
        )
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("-c", "user.email=kit@test", "-c", "user.name=kit", "commit", "-q", "-m", "seed")
        self.legacy = base / "legacy"
        self.knowledge = self.legacy / ".ai" / "knowledge"
        self.knowledge.mkdir(parents=True)
        (self.knowledge / "README.md").write_text("# Knowledge Index\n", encoding="utf-8")

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=self.target, text=True, capture_output=True, check=True
        )
        return result.stdout.strip()

    # -- helpers -------------------------------------------------------------

    def add_legacy_entry(self, full_name: str, **kwargs) -> None:
        path = self.knowledge / "artifacts" / "ApexClass" / "c" / f"{full_name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(entry_text("ApexClass", full_name, **kwargs), encoding="utf-8")

    def resolvable(self, *names: str) -> None:
        mapping = {
            name: [{"metadataType": "ApexClass", "fullName": name}] for name in names
        }
        (self.target / "resolve-map.json").write_text(json.dumps(mapping), encoding="utf-8")

    def target_fragment(self) -> tuple[str, str]:
        blob = (self.target / "force-app" / "Foo.cls").read_bytes()
        return ("force-app/Foo.cls", kit.sha256_bytes(blob))

    def plan(self) -> dict:
        return kit.build_plan(self.legacy, self.target)

    def plan_to_disk(self) -> Path:
        code = kit.run_plan(self.legacy, self.target, echo=lambda *_: None)
        self.assertEqual(0, code)
        runs = sorted((self.target / "output" / "knowledge-migration").iterdir())
        return runs[-1] / "manifest.json"

    def calls(self) -> list[list[str]]:
        path = self.target / "calls.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def stage(self, manifest: Path, answers: list[str]) -> int:
        feed = iter(answers)
        return kit.stage(manifest, self.target, ask=lambda _: next(feed), echo=lambda *_: None)


class PathSafetyTests(KitFixture):
    def test_unsafe_paths_are_rejected(self) -> None:
        for raw in ("", "   ", '"   "', str(self.legacy / "missing")):
            with self.subTest(raw=raw):
                with self.assertRaises(kit.MigrationError):
                    kit.validate_legacy_root(raw, self.target)
        with self.assertRaises(kit.MigrationError):
            kit.validate_legacy_root(str(self.target), self.target)  # target itself
        with self.assertRaises(kit.MigrationError):
            kit.validate_legacy_root(str(self.target / "scripts"), self.target)  # inside target
        with self.assertRaises(kit.MigrationError):
            kit.validate_legacy_root(str(self.target.parent), self.target)  # target nested inside

    @unittest.skipIf(os.name == "nt", "POSIX permission semantics")
    def test_unreadable_path_is_rejected(self) -> None:
        locked = self.legacy / "locked"
        locked.mkdir()
        locked.chmod(0)
        try:
            with self.assertRaises(kit.MigrationError):
                kit.validate_legacy_root(str(locked), self.target)
        finally:
            locked.chmod(stat.S_IRWXU)

    def test_quoted_valid_path_is_accepted(self) -> None:
        resolved = kit.validate_legacy_root(f'  "{self.legacy}"  ', self.target)
        self.assertEqual(self.legacy.resolve(), resolved)


class LayoutAndPlanTests(KitFixture):
    def test_interactive_flow_prompts_then_plans(self) -> None:
        answers = iter(["not-a-real-path", str(self.legacy), "y"])
        lines: list[str] = []
        code = kit.interactive_plan(
            self.target, ask=lambda _: next(answers), echo=lambda *a: lines.append(" ".join(map(str, a)))
        )
        self.assertEqual(0, code)
        self.assertTrue(any("invalid path" in line for line in lines))
        self.assertTrue((self.target / "output" / "knowledge-migration").is_dir())

    def test_unsupported_layout_reports_paths_and_writes_nothing(self) -> None:
        (self.knowledge / "claims-index.json").write_text("{}", encoding="utf-8")
        lines: list[str] = []
        code = kit.run_plan(self.legacy, self.target, echo=lambda *a: lines.append(" ".join(map(str, a))))
        self.assertEqual(2, code)
        self.assertTrue(any("UNSUPPORTED_LAYOUT" in line for line in lines))
        self.assertTrue(any("claims-index.json" in line for line in lines))
        self.assertFalse((self.target / "output").exists())

    def test_missing_knowledge_dir_is_unsupported(self) -> None:
        bare = self.legacy.parent / "bare"
        bare.mkdir()
        code = kit.run_plan(bare, self.target, echo=lambda *_: None)
        self.assertEqual(2, code)

    def test_empty_corpus_reports_zero_entries(self) -> None:
        plan = self.plan()
        self.assertEqual(0, plan["header"]["artifactEntries"])
        manifest = self.plan_to_disk()
        report = (manifest.parent / "report.md").read_text(encoding="utf-8")
        self.assertIn("Empty corpus", report)

    def test_plan_writes_only_ignored_output(self) -> None:
        self.resolvable("Alpha")
        self.add_legacy_entry("Alpha", purpose="Real prose.", fragment=self.target_fragment())
        before = {p for p in self.target.rglob("*") if p.is_file() and ".git" not in p.parts}
        self.plan_to_disk()
        after = {p for p in self.target.rglob("*") if p.is_file() and ".git" not in p.parts}
        new_paths = after - before
        self.assertTrue(new_paths)
        for path in new_paths:
            self.assertIn("output", path.parts, path)
        self.assertEqual("", self.git("status", "--porcelain"))

    def test_manifest_never_contains_entry_bodies(self) -> None:
        secret = "UNIQUE-PROSE-SENTENCE-9317 that must stay out of the manifest"
        self.resolvable("Alpha")
        self.add_legacy_entry("Alpha", purpose=secret, fragment=self.target_fragment())
        manifest = self.plan_to_disk()
        self.assertNotIn(secret, manifest.read_text(encoding="utf-8"))
        self.assertNotIn(secret, (manifest.parent / "report.md").read_text(encoding="utf-8"))


class ClassificationTests(KitFixture):
    def test_all_six_classes(self) -> None:
        frag = self.target_fragment()
        self.resolvable("Exact", "Reapprove", "Present", "Clash")
        self.add_legacy_entry("Exact", purpose="Prose.", fragment=frag)
        self.add_legacy_entry(
            "Reapprove", purpose="Prose.", fragment=("force-app/Foo.cls", "sha256:stale")
        )
        self.add_legacy_entry("OrgOnly", purpose=None, content_digest="sha256:o")
        (self.knowledge / "artifacts-org-ledger.jsonl").write_text(
            json.dumps({"identity": "ApexClass:c:OrgOnly"}) + "\n", encoding="utf-8"
        )
        self.add_legacy_entry("Present", purpose="Prose.", fragment=frag,
                              content_digest="sha256:same")
        present = self.target / ".ai/knowledge/artifacts/ApexClass/c/Present.md"
        present.parent.mkdir(parents=True)
        present.write_text(
            entry_text("ApexClass", "Present", "Prose.", content_digest="sha256:same"),
            encoding="utf-8",
        )
        self.add_legacy_entry("Clash", purpose="Prose.", fragment=frag,
                              content_digest="sha256:legacy-side")
        (self.target / ".ai/knowledge/artifacts/ApexClass/c/Clash.md").write_text(
            entry_text("ApexClass", "Clash", "Different.", content_digest="sha256:target-side"),
            encoding="utf-8",
        )
        self.add_legacy_entry("Ghost", purpose="Prose.",
                              fragment=("force-app/Gone.cls", "sha256:gone"))

        by_identity = {
            row["legacyIdentity"]: row["class"] for row in self.plan()["records"]
        }
        self.assertEqual("EXACT_REVIEW_CANDIDATE", by_identity["ApexClass:c:Exact"])
        self.assertEqual("REAPPROVAL_CANDIDATE", by_identity["ApexClass:c:Reapprove"])
        self.assertEqual("ORG_REFRESH_ONLY", by_identity["ApexClass:c:OrgOnly"])
        self.assertEqual("ALREADY_PRESENT", by_identity["ApexClass:c:Present"])
        self.assertEqual("CONFLICT", by_identity["ApexClass:c:Clash"])
        self.assertEqual("QUARANTINE", by_identity["ApexClass:c:Ghost"])

    def test_legacy_approval_is_provenance_only(self) -> None:
        self.resolvable("Alpha")
        self.add_legacy_entry("Alpha", purpose="Prose.", fragment=self.target_fragment())
        (self.knowledge / "artifacts-ledger.jsonl").write_text(
            json.dumps(
                {
                    "action": "approve",
                    "identity": "ApexClass:c:Alpha",
                    "reviewedBy": "Legacy Reviewer",
                    "reviewedAt": "2026-08-01T00:00:00Z",
                    "reviewedContentDigest": "sha256:old",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        plan = self.plan()
        row = plan["records"][0]
        self.assertEqual("EXACT_REVIEW_CANDIDATE", row["class"])  # not auto-approved
        self.assertIn("provenance", row["legacyApproval"]["note"])


class StageTests(KitFixture):
    def stageable_corpus(self) -> Path:
        self.resolvable("Alpha", "Beta")
        frag = self.target_fragment()
        self.add_legacy_entry("Alpha", purpose="Alpha prose.", fragment=frag,
                              limitations=["known limit"])
        self.add_legacy_entry("Beta", purpose="Beta prose.", fragment=frag)
        return self.plan_to_disk()

    def test_stage_success_uses_only_the_documented_sequence(self) -> None:
        manifest = self.stageable_corpus()
        code = self.stage(manifest, ["all", "2"])
        self.assertEqual(0, code)
        commands = [call[0] for call in self.calls() if call]
        self.assertEqual({"entry-draft", "entry-describe", "entry-status"}, set(commands))
        self.assertNotIn("entry-approve", commands)
        self.assertFalse((self.target / ".ai/knowledge/artifacts-ledger.jsonl").exists())
        outcomes = (manifest.parent / "stage-outcomes.jsonl").read_text(encoding="utf-8")
        self.assertEqual(2, outcomes.count("staged-draft"))
        describe = next(call for call in self.calls() if call[0] == "entry-describe")
        self.assertIn("--limitation", describe)

    def test_stage_requires_exact_typed_confirmation(self) -> None:
        manifest = self.stageable_corpus()
        code = self.stage(manifest, ["all", "999"])
        self.assertEqual(1, code)
        self.assertEqual([], [c for c in self.calls() if c and c[0] == "entry-draft"])

    def test_stage_refuses_dirty_worktree(self) -> None:
        manifest = self.stageable_corpus()
        (self.target / "force-app" / "dirty.cls").write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(kit.MigrationError, "dirty"):
            self.stage(manifest, ["all", "2"])

    def test_stage_refuses_tampered_manifest(self) -> None:
        manifest = self.stageable_corpus()
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["records"][0]["class"] = "EXACT_REVIEW_CANDIDATE"
        payload["records"][0]["legacyIdentity"] = "ApexClass:c:Injected"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(kit.MigrationError, "digest mismatch"):
            self.stage(manifest, ["all", "2"])

    def test_stage_refuses_changed_target_source(self) -> None:
        manifest = self.stageable_corpus()
        (self.target / "force-app" / "Foo.cls").write_text("class Foo { void x(){} }\n")
        self.git("add", "-A")
        self.git("-c", "user.email=kit@test", "-c", "user.name=kit", "commit", "-q", "-m", "drift")
        with self.assertRaisesRegex(kit.MigrationError, "re-run plan"):
            self.stage(manifest, ["all", "2"])

    def test_stage_refuses_changed_legacy_corpus(self) -> None:
        manifest = self.stageable_corpus()
        self.add_legacy_entry("Gamma", purpose="Late arrival.")
        with self.assertRaisesRegex(kit.MigrationError, "legacy corpus changed"):
            self.stage(manifest, ["all", "2"])

    def test_conflict_rows_are_never_stageable(self) -> None:
        self.resolvable("Clash")
        self.add_legacy_entry("Clash", purpose="Prose.", fragment=self.target_fragment(),
                              content_digest="sha256:legacy-side")
        clash = self.target / ".ai/knowledge/artifacts/ApexClass/c/Clash.md"
        clash.parent.mkdir(parents=True)
        clash.write_text(
            entry_text("ApexClass", "Clash", "Other.", content_digest="sha256:target-side"),
            encoding="utf-8",
        )
        manifest = self.plan_to_disk()
        code = self.stage(manifest, [])
        self.assertEqual(0, code)  # "nothing stageable" — and no executor calls at all
        self.assertEqual([], self.calls())

    def test_partial_failure_stops_wave_and_keeps_drafts(self) -> None:
        manifest = self.stageable_corpus()
        (self.target / "fail-on.json").write_text(
            json.dumps({"entry-describe": "ApexClass:c:Beta"}), encoding="utf-8"
        )
        code = self.stage(manifest, ["all", "2"])
        self.assertEqual(1, code)
        self.assertTrue((self.target / ".ai/knowledge/artifacts/ApexClass/c/Alpha.md").is_file())
        self.assertTrue((self.target / ".ai/knowledge/artifacts/ApexClass/c/Beta.md").is_file())
        # resume: clear the fault, re-stage — Alpha and Beta both exist now, so both skip
        (self.target / "fail-on.json").unlink()
        code = self.stage(manifest, ["all", "2"])
        self.assertEqual(0, code)
        draft_calls = [c for c in self.calls() if c and c[0] == "entry-draft"]
        self.assertEqual(2, len(draft_calls))  # no duplicate drafts on resume

    def test_repeated_stage_is_idempotent(self) -> None:
        manifest = self.stageable_corpus()
        self.assertEqual(0, self.stage(manifest, ["all", "2"]))
        first = len([c for c in self.calls() if c and c[0] == "entry-draft"])
        self.assertEqual(0, self.stage(manifest, ["all", "2"]))
        second = len([c for c in self.calls() if c and c[0] == "entry-draft"])
        self.assertEqual(first, second)


class PrepareReviewTests(KitFixture):
    def test_prepare_review_renders_but_never_approves(self) -> None:
        self.resolvable("Alpha")
        self.add_legacy_entry("Alpha", purpose="Prose.", fragment=self.target_fragment())
        manifest = self.plan_to_disk()
        self.assertEqual(0, self.stage(manifest, ["all", "1"]))
        lines: list[str] = []
        code = kit.prepare_review(manifest, self.target, echo=lambda *a: lines.append(" ".join(map(str, a))))
        self.assertEqual(0, code)
        commands = [c[0] for c in self.calls() if c]
        self.assertIn("entry-review", commands)
        self.assertNotIn("entry-approve", commands)
        self.assertTrue(any("HUMAN-ONLY" in line for line in lines))

    def test_prepare_review_requires_stage_outcomes(self) -> None:
        self.resolvable("Alpha")
        self.add_legacy_entry("Alpha", purpose="Prose.", fragment=self.target_fragment())
        manifest = self.plan_to_disk()
        with self.assertRaisesRegex(kit.MigrationError, "run stage first"):
            kit.prepare_review(manifest, self.target, echo=lambda *_: None)


class GuideAgreementTests(unittest.TestCase):
    def test_guide_and_script_agree(self) -> None:
        guide = (ROOT / "MIGRATE-LEGACY-KNOWLEDGE.md").read_text(encoding="utf-8")
        self.assertTrue((ROOT / "migrate_legacy_knowledge.py").is_file())
        self.assertIn("python migrate_legacy_knowledge.py", guide)
        for command in ("plan --legacy-root", "stage --manifest", "prepare-review --manifest"):
            self.assertIn(command, guide)
        self.assertIn("entry-approve", guide)  # named as the human-only step
        self.assertIn("delete `migrate_legacy_knowledge.py`", guide)


if __name__ == "__main__":
    unittest.main()
