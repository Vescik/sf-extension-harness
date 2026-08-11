"""The validator must degrade to named audit errors, never to a lost report.

Pins the 2026-08-04 deep-test fix: a malformed input file used to raise an uncaught
exception through a check_* function, discarding every already-collected finding
(25 confirmed crash sites). These tests state what must NOT happen again."""

from __future__ import annotations

import ast
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from scripts import validate_harness

ROOT = Path(__file__).resolve().parents[1]


class TempRootBase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def run_audit(self, check, **kwargs) -> validate_harness.Audit:
        audit = validate_harness.Audit()
        check(audit, **kwargs)
        return audit


class TestRunChecksWrapper(unittest.TestCase):
    def test_crash_becomes_named_error_and_later_checks_still_run(self) -> None:
        audit = validate_harness.Audit()
        ran: list[str] = []

        def boom(a: validate_harness.Audit) -> None:
            raise RuntimeError("kaput")

        def after(a: validate_harness.Audit) -> None:
            ran.append("after")
            a.require(True, "never fails")

        with redirect_stderr(io.StringIO()):
            validate_harness.run_checks(audit, [boom, after])
        self.assertEqual(ran, ["after"])
        self.assertTrue(
            any("boom crashed (RuntimeError: kaput)" in message for message in audit.errors),
            audit.errors,
        )


class TestLazyScriptsImportsForbidden(unittest.TestCase):
    """C6: `from scripts.… import …` inside a function body resolves only when the repo
    root is on sys.path — it broke `python scripts/validate_harness.py` (the CI
    invocation) as soon as .ai/knowledge/artifacts/ existed. Header imports carry the
    dual-mode fallback; function bodies must not import siblings at all."""

    def test_no_function_level_scripts_imports(self) -> None:
        tree = ast.parse((ROOT / "scripts/validate_harness.py").read_text(encoding="utf-8"))
        offenders = [
            inner.module
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for inner in ast.walk(node)
            if isinstance(inner, ast.ImportFrom) and (inner.module or "").startswith("scripts")
        ]
        self.assertEqual(offenders, [])

    def test_canonical_digest_bound_at_module_level(self) -> None:
        self.assertTrue(callable(validate_harness.canonical_digest))


class TestGuardedReads(TempRootBase):
    def test_required_text_records_unreadable(self) -> None:
        audit = validate_harness.Audit()
        self.assertEqual(validate_harness.required_text(self.root / "missing.md", audit), "")
        self.assertTrue(any("unreadable" in message for message in audit.errors), audit.errors)

    def test_frontmatter_records_unreadable(self) -> None:
        audit = validate_harness.Audit()
        self.assertEqual(validate_harness.frontmatter(self.root / "missing.md", audit), ({}, ""))
        self.assertTrue(any("unreadable" in message for message in audit.errors), audit.errors)

    def test_load_jsonc_records_unreadable(self) -> None:
        audit = validate_harness.Audit()
        self.assertEqual(validate_harness.load_jsonc(self.root / "missing.jsonc", audit), {})
        self.assertTrue(any("invalid JSONC" in message for message in audit.errors), audit.errors)


class TestSalesforceProjectShape(TempRootBase):
    def test_list_shaped_sfdx_project_is_reported_not_raised(self) -> None:
        (self.root / "sfdx-project.json").write_text("[]", encoding="utf-8")
        audit = self.run_audit(validate_harness.check_salesforce_project, root=self.root)
        self.assertTrue(
            any("must be a JSON object" in message for message in audit.errors), audit.errors
        )


class TestApplyPatch(unittest.TestCase):
    def test_applies_dotted_path(self) -> None:
        instance = {"completeness": {"status": "partial"}}
        validate_harness.apply_patch(instance, "completeness.status", "complete")
        self.assertEqual(instance["completeness"]["status"], "complete")

    def test_missing_key_raises_caught_types(self) -> None:
        with self.assertRaises(KeyError):
            validate_harness.apply_patch({}, "missing.deep.path", 1)
        with self.assertRaises(TypeError):
            validate_harness.apply_patch([], "missing.path", 1)


class GithubCopyBase(TempRootBase):
    def setUp(self) -> None:
        super().setUp()
        shutil.copytree(ROOT / ".github", self.root / ".github")

    def rewrite_frontmatter(self, rel: str, mutate) -> None:
        import yaml

        path = self.root / rel
        text = path.read_text(encoding="utf-8")
        _, body = text.split("---\n", 2)[1:]
        data = yaml.safe_load(text.split("---\n", 2)[1])
        mutate(data)
        path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\n" + body,
                        encoding="utf-8")


class TestCustomizationsHostileFrontmatter(GithubCopyBase):
    def test_null_tools_recorded_not_raised(self) -> None:
        self.rewrite_frontmatter(
            ".github/agents/reviewer.agent.md",
            lambda data: data.update(tools=None),
        )
        audit = self.run_audit(validate_harness.check_customizations, root=self.root)
        self.assertTrue(
            any("tools must be an array" in message for message in audit.errors), audit.errors
        )

    def test_unhashable_tools_recorded_not_raised(self) -> None:
        self.rewrite_frontmatter(
            ".github/agents/developer.agent.md",
            lambda data: data.update(tools=[{"a": 1}]),
        )
        audit = self.run_audit(validate_harness.check_customizations, root=self.root)
        self.assertTrue(
            any("tools must be an array" in message for message in audit.errors), audit.errors
        )

    def test_date_valued_hooks_serialize_without_raising(self) -> None:
        import datetime

        self.rewrite_frontmatter(
            ".github/agents/reviewer.agent.md",
            lambda data: data.setdefault("hooks", {}).update(probe=datetime.date(2026, 1, 1)),
        )
        audit = self.run_audit(validate_harness.check_customizations, root=self.root)
        self.assertNotIn(
            "reviewer role guard is required", audit.errors
        )  # original hooks content still present; the date must not abort serialization


class TestInventoryIsDiscoveredNotCountPinned(GithubCopyBase):
    """D7 (lightweight-validation plan): structural discovery, no exact totals.

    A legitimate new prompt/skill must validate on its own shape; only real defects
    (duplicate public names, invalid routing) may fail."""

    PROMPT = (
        "---\n"
        "name: probe-temp\n"
        "description: Temporary probe prompt for the count-pin regression test\n"
        "argument-hint: none\n"
        "agent: agent\n"
        "---\n"
        "Use the [probe skill](../skills/fetch-ado-item/SKILL.md).\n"
    )

    def test_valid_additional_prompt_changes_no_expectation(self) -> None:
        before = self.run_audit(validate_harness.check_customizations, root=self.root).errors
        (self.root / ".github/prompts/probe-temp.prompt.md").write_text(
            self.PROMPT, encoding="utf-8"
        )
        after = self.run_audit(validate_harness.check_customizations, root=self.root).errors
        self.assertEqual(before, after)

    def test_duplicate_public_command_names_still_fail(self) -> None:
        # fetch-ado-item exists as both a prompt and an (internal) skill; making the skill
        # public collides the slash-command namespace and must fail loudly.
        self.rewrite_frontmatter(
            ".github/skills/fetch-ado-item/SKILL.md",
            lambda data: data.update({"user-invocable": True}),
        )
        audit = self.run_audit(validate_harness.check_customizations, root=self.root)
        self.assertIn("public slash-command names collide", audit.errors)


class TestPlaceholdersBinaryFile(TempRootBase):
    def test_binary_asset_is_skipped_not_a_crash(self) -> None:
        github = self.root / ".github"
        github.mkdir()
        (github / "probe.bin").write_bytes(b"\xff\xfe\x00\xffnot-utf8")
        (github / "placeholders.md").write_text(
            "\n".join(sorted(validate_harness.EXPECTED_HUMAN_PLACEHOLDERS)), encoding="utf-8"
        )
        audit = self.run_audit(validate_harness.check_placeholders, root=self.root)
        self.assertEqual(audit.errors, [])


class TestRetiredSurfaceScan(TempRootBase):
    """A retired surface must be unreachable, and the scan must prove it rather than pass idly."""

    MANIFEST = {
        "schemaVersion": 1,
        "retired": [
            {
                "name": "ghost-lane",
                "retiredIn": "P1",
                "retiredOn": "2026-08-05",
                "replacement": "the replacement lane",
                "tokens": ["ghost-lane"],
                "historicalAllowlist": ["docs/history.md"],
            }
        ],
    }

    def seed(self, files: dict[str, str]) -> None:
        (self.root / "config").mkdir(parents=True, exist_ok=True)
        (self.root / "config" / "retired-surfaces.json").write_text(
            json.dumps(self.MANIFEST), encoding="utf-8"
        )
        for relative, text in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)

    def test_live_reference_to_a_retired_surface_fails(self) -> None:
        self.seed({".github/prompts/live.md": "Run ghost-lane first.\n"})
        audit = self.run_audit(validate_harness.check_retired_surfaces, root=self.root)
        self.assertTrue(audit.errors)
        self.assertIn("ghost-lane", audit.errors[0])
        self.assertIn(".github/prompts/live.md", audit.errors[0])

    def test_historical_document_may_keep_describing_it(self) -> None:
        self.seed({"docs/history.md": "The ghost-lane skill was retired in P1.\n"})
        audit = self.run_audit(validate_harness.check_retired_surfaces, root=self.root)
        self.assertEqual(audit.errors, [])
        self.assertEqual(audit.checks, 1)

    def test_missing_manifest_is_an_audit_error_not_a_crash(self) -> None:
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        audit = self.run_audit(validate_harness.check_retired_surfaces, root=self.root)
        self.assertTrue(audit.errors)


class TestDependencyAdmission(unittest.TestCase):
    """DEP-01 must be able to fail. A gate that cannot see a real import proves nothing."""

    def test_live_tree_admits_every_third_party_python_import(self) -> None:
        audit = validate_harness.Audit()
        validate_harness.check_dependency_admissions(audit)
        self.assertEqual(audit.errors, [])
        self.assertGreater(audit.checks, 0)

    def test_extension_modules_are_not_mistaken_for_third_party(self) -> None:
        detected = set(validate_harness.third_party_python_imports(ROOT))
        self.assertIn("jsonschema", detected)
        self.assertIn("yaml", detected)
        for stdlib_extension in ("math", "unicodedata", "hashlib"):
            self.assertNotIn(stdlib_extension, detected)

    def test_admission_records_are_schema_valid_and_named_by_digest(self) -> None:
        import hashlib as _hashlib

        from jsonschema import Draft202012Validator

        schema = json.loads(
            (ROOT / "schemas/dependency-admission.schema.json").read_text(encoding="utf-8")
        )
        records = sorted((ROOT / "config/dependency-admissions").glob("*/*.json"))
        self.assertTrue(records, "the rebuild admits at least one pre-existing exception")
        for path in records:
            record = json.loads(path.read_text(encoding="utf-8"))
            errors = list(Draft202012Validator(schema).iter_errors(record))
            self.assertEqual(errors, [], f"{path.name}: {[e.message for e in errors][:3]}")
            canonical = f"{record['ecosystem']}:{record['packageName'].lower()}"
            self.assertEqual(
                record["nameDigest12"],
                _hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12],
            )
            self.assertEqual(path.name, f"{record['safeSlug']}--{record['nameDigest12']}.json")


class TestForceAppGitPolicy(unittest.TestCase):
    """Two-sided force-app ignore contract (owner decision 2026-08-11).

    Salesforce source under force-app/ is versioned; only local/generated tooling
    state stays ignored. Both sides are pinned so the broad force-app ignore cannot
    silently return, and a git failure can never masquerade as trackability."""

    def test_normal_salesforce_source_is_trackable(self) -> None:
        self.assertEqual(
            validate_harness.git_check_ignore("force-app/main/default/classes/TrackedCanary.cls"),
            1,
        )

    def test_generated_lwc_jsconfig_stays_ignored(self) -> None:
        self.assertEqual(
            validate_harness.git_check_ignore("force-app/main/default/lwc/jsconfig.json"),
            0,
        )

    def test_git_error_is_not_read_as_trackable(self) -> None:
        original = validate_harness.git_check_ignore
        validate_harness.git_check_ignore = lambda path: 128
        try:
            audit = validate_harness.Audit()
            validate_harness.check_ci(audit)
        finally:
            validate_harness.git_check_ignore = original
        self.assertIn(
            "Salesforce source path is unexpectedly ignored: "
            "force-app/main/default/classes/TrackedCanary.cls",
            audit.errors,
        )


class TestFetchPromptIntakeBoundary(unittest.TestCase):
    """The public fetch prompt is intake-only (owner decision 2026-08-11).

    Pins the key boundary of the ado-context split without pinning generated
    Markdown wording: the prompt routes to the fetch skill, persists
    ado-context.md, names /solution-design as the next action, and no longer
    instructs an automatic continuation into Solution Design."""

    def setUp(self) -> None:
        self.text = (ROOT / ".github/prompts/fetch-ado-item.prompt.md").read_text(
            encoding="utf-8"
        )

    def test_prompt_routes_to_fetch_skill_and_persists_context(self) -> None:
        self.assertIn("skills/fetch-ado-item/SKILL.md", self.text)
        self.assertIn("ado-context.md", self.text)

    def test_prompt_stops_with_design_command_as_next_action(self) -> None:
        self.assertIn("/solution-design itemId=<ID>", self.text)

    def test_prompt_no_longer_continues_into_designing(self) -> None:
        # The pre-split prompt linked the design skill and said to continue with
        # it; intake must not silently become designing again.
        self.assertNotIn("skills/solution-design/SKILL.md", self.text)
        self.assertNotIn("design.md first", self.text)


if __name__ == "__main__":
    unittest.main()
