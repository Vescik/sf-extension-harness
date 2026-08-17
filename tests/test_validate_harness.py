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
    ado-context.md, names the git-agent bootstrap as the next action, and no longer
    instructs an automatic continuation into Solution Design."""

    def setUp(self) -> None:
        self.text = (ROOT / ".github/prompts/fetch-ado-item.prompt.md").read_text(
            encoding="utf-8"
        )

    def test_prompt_routes_to_fetch_skill_and_persists_context(self) -> None:
        self.assertIn("skills/fetch-ado-item/SKILL.md", self.text)
        self.assertIn("ado-context.md", self.text)

    def test_prompt_stops_with_git_bootstrap_as_next_action(self) -> None:
        self.assertIn("git-agent: start work item <ID>", self.text)
        self.assertIn("/solution-design itemId=<ID>", self.text)

    def test_prompt_no_longer_continues_into_designing(self) -> None:
        # The pre-split prompt linked the design skill and said to continue with
        # it; intake must not silently become designing again.
        self.assertNotIn("skills/solution-design/SKILL.md", self.text)
        self.assertNotIn("design.md first", self.text)


class TestGitBootstrapBeforeSolutionDesign(unittest.TestCase):
    """Pins the lightweight intake -> branch -> design lifecycle contract."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.git_skill = (ROOT / ".github/skills/git-workflow/SKILL.md").read_text(
            encoding="utf-8"
        )
        cls.git_agent = (ROOT / ".github/agents/git-agent.agent.md").read_text(
            encoding="utf-8"
        )
        cls.design_prompt = (ROOT / ".github/prompts/solution-design.prompt.md").read_text(
            encoding="utf-8"
        )

    def test_git_agent_owns_start_work_item(self) -> None:
        self.assertIn("start work item <ID>", self.git_skill)
        self.assertIn("start work item <ID>", self.git_agent)
        self.assertIn("/solution-design itemId=<ID>", self.git_skill)

    def test_start_is_exact_path_local_and_scoped_to_one_container(self) -> None:
        self.assertIn("Never use `git add .`", self.git_skill)
        self.assertRegex(self.git_skill.lower(), r"do\s+not push")
        # A concrete item gets a work-item branch; a Feature branch exists only
        # through the explicit prepared-Feature bootstrap, never through start work item.
        self.assertIn("work-item/<ID>-<stable-slug>", self.git_skill)

    def test_design_refuses_main_for_ado_item(self) -> None:
        self.assertIn("git-agent: start work item <ID>", self.design_prompt)
        self.assertIn("Designer never creates or switches branches", self.design_prompt)


class TestGitPostPushPRHandoff(unittest.TestCase):
    """Pins the no-CLI, post-success push handoff contract."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.git_skill = (ROOT / ".github/skills/git-workflow/SKILL.md").read_text(
            encoding="utf-8"
        )
        cls.git_agent = (ROOT / ".github/agents/git-agent.agent.md").read_text(
            encoding="utf-8"
        )

    def test_successful_push_returns_copyable_template_and_compare_link(self) -> None:
        self.assertIn("After a successful push", self.git_skill)
        self.assertIn(".github/pull_request_template.md", self.git_skill)
        self.assertIn("compare/<base>...<branch>?expand=1", self.git_skill)
        self.assertIn("complete PR description in one copyable Markdown code block", self.git_skill)

    def test_handoff_does_not_create_pr_or_require_github_cli(self) -> None:
        self.assertIn("Do not require GitHub CLI", self.git_skill)
        self.assertIn("This never creates the PR", self.git_agent)

    def test_failed_or_unknown_remote_is_not_misrepresented(self) -> None:
        self.assertIn("rejected, failed, or unverified push", self.git_skill)
        self.assertIn("Never guess an owner or repository", self.git_skill)


class TestPrepareDeliveryFeatureBoundaries(unittest.TestCase):
    """Multi-Story Feature delivery is strictly opt-in (plan 2026-08-12).

    Pins the safety-critical contract facts of /prepare-delivery-feature without
    pinning whole prose documents: the type gate, the narrow direct-child
    retrieval, the two-file write boundary, and the no-child-write /
    no-Feature-Health rules."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.prompt = (
            ROOT / ".github/prompts/prepare-delivery-feature.prompt.md"
        ).read_text(encoding="utf-8")
        cls.skill = (
            ROOT / ".github/skills/prepare-delivery-feature/SKILL.md"
        ).read_text(encoding="utf-8")
        cls.fetch_skill = (ROOT / ".github/skills/fetch-ado-item/SKILL.md").read_text(
            encoding="utf-8"
        )

    def test_prompt_frontmatter_names_and_targets(self) -> None:
        self.assertIn("name: prepare-delivery-feature", self.prompt)
        self.assertIn("agent: designer", self.prompt)

    def test_prompt_exposes_only_itemid_and_include(self) -> None:
        hint_line = next(
            line for line in self.prompt.splitlines() if line.startswith("argument-hint:")
        )
        self.assertEqual(
            'argument-hint: "itemId=<Feature ID> [include=all|<ID,ID,...>]"', hint_line
        )
        for hidden_option in ("mode=", "depth=", "childDetail=", "health=", "onStale="):
            self.assertNotIn(hidden_option, hint_line)

    def test_skill_is_internal_and_reuses_the_fetch_skill(self) -> None:
        self.assertIn("user-invocable: false", self.skill)
        # One retrieval procedure: the existing fetch skill, never a parallel client.
        self.assertIn("skills/fetch-ado-item/SKILL.md", self.skill.replace("../fetch-ado-item", "skills/fetch-ado-item"))
        self.assertIn("mode=direct-children", self.skill)
        self.assertIn("do not call `ado-readonly` directly", self.skill)

    def test_direct_child_mode_excludes_parent_siblings_grandchildren(self) -> None:
        self.assertIn("direct-children", self.fetch_skill)
        for token in ("parent", "siblings", "grandchildren"):
            self.assertIn(token, self.fetch_skill)
        self.assertIn(
            "`childDetail=full` is invalid with `direct-children`", self.fetch_skill
        )

    def test_prepare_owns_only_the_two_feature_files(self) -> None:
        self.assertIn("ado-context.md", self.skill)
        self.assertIn("delivery-map.md", self.skill)
        self.assertIn(
            "The only permitted tracked writes are the Feature's own `ado-context.md` "
            "and `delivery-map.md`.",
            self.skill,
        )

    def test_prepare_forbids_child_folder_writes(self) -> None:
        self.assertIn(
            "Never create, rename, refresh, or edit any child work-item folder or file",
            self.skill,
        )

    def test_prepare_never_calls_feature_health(self) -> None:
        self.assertIn("never invokes `/feature-health`", self.skill)

    def test_root_must_be_exactly_a_feature(self) -> None:
        self.assertIn("must be exactly `Feature`", self.skill)

    def test_include_ids_validated_against_fresh_direct_children(self) -> None:
        self.assertIn(
            "verify every ID against the freshly fetched direct non-container",
            self.skill,
        )

    def test_partial_discovery_preserves_and_never_creates_a_map(self) -> None:
        self.assertIn("preserve any existing\n`delivery-map.md` byte-for-byte", self.skill)
        self.assertIn("create no new map", self.skill)

    def test_same_input_prepare_is_a_no_op(self) -> None:
        self.assertIn("byte-identical", self.skill)


class TestSolutionDesignDeliveryMapRouting(unittest.TestCase):
    """Feature context reaches a Story only through a local delivery map."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.prompt = (ROOT / ".github/prompts/solution-design.prompt.md").read_text(
            encoding="utf-8"
        )
        cls.skill = (ROOT / ".github/skills/solution-design/SKILL.md").read_text(
            encoding="utf-8"
        )
        cls.fetch_prompt = (ROOT / ".github/prompts/fetch-ado-item.prompt.md").read_text(
            encoding="utf-8"
        )

    def test_zero_one_multiple_map_handling_is_defined(self) -> None:
        self.assertIn("Zero matches", self.skill)
        self.assertIn("Exactly one match", self.skill)
        self.assertIn("More than one match", self.skill)
        self.assertIn("`15001` never matches `5001`", self.skill)

    def test_one_match_records_feature_baseline_and_keeps_story_authority(self) -> None:
        self.assertIn("Prepared delivery context:", self.skill)
        self.assertIn("Feature ADO revision", self.skill)
        self.assertIn("acceptance criteria remain\n  authoritative", self.skill)

    def test_story_context_is_never_the_feature_link_target(self) -> None:
        self.assertIn(
            "never adds a pointer to a Story's `ado-context.md`",
            self.skill.replace("preparing a Feature never adds", "never adds"),
        )

    def test_feature_input_routes_to_prepare_not_design(self) -> None:
        self.assertIn("/prepare-delivery-feature itemId=<ID>", self.prompt)
        self.assertIn("/prepare-delivery-feature itemId=<ID>", self.skill)

    def test_fetch_routes_feature_to_prepare_without_auto_invoking(self) -> None:
        self.assertIn("/prepare-delivery-feature itemId=<ID>", self.fetch_prompt)
        self.assertIn("never invoked automatically", self.fetch_prompt)


class TestFeatureHealthStaysDecoupled(unittest.TestCase):
    """Feature Health is explicit and never edits guarded work-item folders."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.prompt = (ROOT / ".github/prompts/feature-health.prompt.md").read_text(
            encoding="utf-8"
        )
        cls.prepare_skill = (
            ROOT / ".github/skills/prepare-delivery-feature/SKILL.md"
        ).read_text(encoding="utf-8")

    def test_report_stays_in_output_and_no_work_item_write(self) -> None:
        self.assertIn("output/feature-health/", self.prompt)
        self.assertNotIn("link the report", self.prompt)
        self.assertIn("does not edit `work-items/` folders", self.prompt)

    def test_nothing_invokes_feature_health_automatically(self) -> None:
        self.assertIn("Nothing invokes\nthis check automatically", self.prompt)
        self.assertIn("never invokes `/feature-health`", self.prepare_skill)


class TestPreparedFeatureScopeNormalization(unittest.TestCase):
    """Corrective plan 2026-08-12 P1: direct-children is the canonical prepared-Feature
    projection, same revision does not imply equivalent scope, and the one-time
    normalization needs complete fresh direct-child evidence."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fetch_skill = (ROOT / ".github/skills/fetch-ado-item/SKILL.md").read_text(
            encoding="utf-8"
        )
        cls.prepare_skill = (
            ROOT / ".github/skills/prepare-delivery-feature/SKILL.md"
        ).read_text(encoding="utf-8")

    def test_projection_scope_participates_in_same_revision_equivalence(self) -> None:
        self.assertIn("Projection scope is part of that equivalence", self.fetch_skill)
        self.assertIn("not automatically equivalent", self.fetch_skill)

    def test_prepare_owns_one_time_normalization_to_direct_children(self) -> None:
        self.assertIn("canonical scope normalization", self.prepare_skill)
        self.assertIn("even at the same revision", self.prepare_skill)
        self.assertIn(
            "`updated` for this first normalization and `unchanged` on the next identical",
            self.prepare_skill,
        )

    def test_normalization_requires_complete_fresh_evidence(self) -> None:
        self.assertIn("On complete fresh direct-child evidence", self.prepare_skill)
        self.assertIn(
            "complete, fresh direct-child enumeration", self.fetch_skill
        )

    def test_partial_evidence_never_narrows_tracked_context(self) -> None:
        self.assertIn("Partial or stale direct-child evidence never triggers", self.fetch_skill)
        self.assertIn("On partial evidence, no normalization happens at all", self.prepare_skill)
        self.assertIn(
            "must not claim canonical reprojection completed", self.prepare_skill
        )


class TestSolutionDesignRoutingPrecedesDiscovery(unittest.TestCase):
    """Corrective plan 2026-08-12 P2: local type/map routing happens before package
    docs and any Knowledge/Salesforce discovery."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.skill = (ROOT / ".github/skills/solution-design/SKILL.md").read_text(
            encoding="utf-8"
        )
        cls.prompt = (ROOT / ".github/prompts/solution-design.prompt.md").read_text(
            encoding="utf-8"
        )

    def test_skill_defines_local_routing_stage_before_discovery_stage(self) -> None:
        stage1 = self.skill.index("Stage 1 — local routing")
        stage2 = self.skill.index("Stage 2 — design discovery")
        self.assertLess(stage1, stage2)
        # Package docs are read in Stage 2, after routing — not before it.
        self.assertLess(stage2, self.skill.index("docs/package-concept.md"))

    def test_no_remote_call_decides_type_or_membership(self) -> None:
        self.assertIn("Knowledge, Salesforce, or Feature Health call", self.skill)
        self.assertIn("stop before any design context is loaded", self.skill)

    def test_prompt_pins_routing_before_docs_and_remote_discovery(self) -> None:
        self.assertIn(
            "before reading the package design documents or making any Knowledge or\n"
            "Salesforce call",
            self.prompt,
        )

    def test_written_requirements_stay_lightweight(self) -> None:
        self.assertIn("go straight to Stage 2", self.skill)


class TestDesignerCapabilitySurfaceUnchanged(unittest.TestCase):
    """The three-lane Designer keeps the exact pre-change tools and hook."""

    BASELINE_TOOLS = (
        "tools: ['read', 'edit/editFiles', 'vscode/askQuestions', 'knowledge/*', "
        "'ado-readonly/*', 'salesforce-readonly/review_org_identity', "
        "'salesforce-readonly/review_installed_packages', "
        "'salesforce-readonly/review_object_contract', "
        "'salesforce-readonly/review_soql_query']"
    )
    BASELINE_HOOK = "command: python3 scripts/copilot_role_guard.py --role designer"

    def setUp(self) -> None:
        self.text = (ROOT / ".github/agents/designer.agent.md").read_text(encoding="utf-8")

    def test_tools_array_is_byte_identical_to_baseline(self) -> None:
        self.assertIn(self.BASELINE_TOOLS, self.text)

    def test_role_guard_hook_is_unchanged(self) -> None:
        self.assertIn(self.BASELINE_HOOK, self.text)

    def test_designer_names_three_entry_points(self) -> None:
        self.assertIn("three separate entry points", self.text)
        for lane in ("/fetch-ado-item", "/prepare-delivery-feature", "/solution-design"):
            self.assertIn(lane, self.text)


class TestWorkItemFeatureBranchModel(unittest.TestCase):
    """Plan 2026-08-16 (Work Item and Feature Branch Delivery Model): `work-item/` is
    the only standard concrete ADO delivery namespace; `feature/` is reserved for an
    explicitly prepared multi-Story ADO Feature; commits carry explicit Work Item
    ownership plus a link-only raw AB# reference; PR linking is per delivery container."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.git_skill = (ROOT / ".github/skills/git-workflow/SKILL.md").read_text(
            encoding="utf-8"
        )
        cls.git_agent = (ROOT / ".github/agents/git-agent.agent.md").read_text(
            encoding="utf-8"
        )
        cls.design_skill = (ROOT / ".github/skills/solution-design/SKILL.md").read_text(
            encoding="utf-8"
        )
        cls.prepare_skill = (
            ROOT / ".github/skills/prepare-delivery-feature/SKILL.md"
        ).read_text(encoding="utf-8")
        cls.template = (ROOT / ".github/pull_request_template.md").read_text(
            encoding="utf-8"
        )

    def test_branch_namespaces_are_work_item_feature_chore_only(self) -> None:
        self.assertIn("work-item/<work-item-id>-<slug>", self.git_skill)
        self.assertIn("feature/<feature-id>-<slug>", self.git_skill)
        self.assertIn("chore/<short-description>", self.git_skill)
        # The old namespaces are retired: no fix/ branch kind, no integration/ line.
        self.assertNotIn("fix/<work-item-id>", self.git_skill)
        self.assertNotIn("integration/<", self.git_skill)

    def test_feature_branch_requires_prepared_feature_and_explicit_human_choice(self) -> None:
        self.assertIn("start feature <Feature ID>", self.git_skill)
        self.assertIn("start feature <Feature ID>", self.git_agent)
        self.assertIn("delivery-map.md", self.git_skill)
        # A parent relation alone never creates a Feature branch.
        self.assertIn("parent relation alone never", self.git_skill)

    def test_commit_attribution_is_explicit_on_feature_branches(self) -> None:
        self.assertIn("commit work item <ID>", self.git_skill)
        self.assertIn("commit feature <Feature ID>", self.git_skill)
        self.assertIn("[WI-<ID>]", self.git_skill)
        # ADO-backed commits carry the link-only raw AB# reference.
        self.assertIn("AB#<ID>", self.git_skill)

    def test_commits_and_prs_never_use_state_transition_keywords(self) -> None:
        for keyword in ("Fixes", "Resolves", "Closes"):
            self.assertIn(keyword, self.git_skill)  # named in order to be forbidden
        self.assertIn("state-transition", self.git_skill)

    def test_pr_linking_is_per_delivery_container(self) -> None:
        # Standalone/child PR: exactly one matching AB#. Final Feature PR: the Feature
        # plus the included children taken mechanically from the delivery map.
        self.assertIn("Azure Boards Feature: AB#", self.git_skill)
        self.assertIn("Included Work Items", self.git_skill)

    def test_pr_template_has_adaptive_work_item_and_feature_modes(self) -> None:
        self.assertIn("Azure Boards Feature: AB#", self.template)
        self.assertIn("Included Work Items", self.template)
        # Work Item mode stays: one delivering Work Item, no transition keywords.
        self.assertIn("AB#<id>", self.template)

    def test_final_feature_merge_preserves_work_item_commits_or_stops(self) -> None:
        self.assertIn("merge commit", self.git_skill)
        self.assertIn("Do not squash the final Feature PR", self.git_skill)

    def test_design_stage_accepts_work_item_or_matching_feature_branch(self) -> None:
        self.assertIn("work-item/<id>-<slug>", self.design_skill)
        self.assertIn("feature/<feature-id>-<slug>", self.design_skill)

    def test_prepare_returns_the_two_explicit_delivery_choices(self) -> None:
        self.assertIn("git-agent: start feature", self.prepare_skill)
        self.assertIn("/fetch-ado-item itemId=<first-included-ID>", self.prepare_skill)


if __name__ == "__main__":
    unittest.main()
