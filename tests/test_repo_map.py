from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import render_repo_map, validate_harness
from scripts.render_repo_map import (
    RepoMapError,
    build_model,
    frontmatter,
    one_liner,
    render,
    render_md,
    word_count,
)

ROOT = Path(__file__).resolve().parents[1]


class RepoMapParsingTests(unittest.TestCase):
    def test_frontmatter_parses_yaml_header_and_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.md"
            path.write_text(
                "---\nname: sample\ndescription: One thing. Two thing.\n---\nBody text\n",
                encoding="utf-8",
            )
            data, body = frontmatter(path)
        self.assertEqual("sample", data["name"])
        self.assertEqual("Body text\n", body)

    def test_frontmatter_rejects_unterminated_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.md"
            path.write_text("---\nname: broken\n", encoding="utf-8")
            with self.assertRaisesRegex(RepoMapError, "unterminated"):
                frontmatter(path)

    def test_one_liner_takes_first_sentence_and_truncates(self) -> None:
        self.assertEqual("Short summary", one_liner("Short summary. More detail follows."))
        long = " ".join(f"w{i}" for i in range(30))
        self.assertTrue(one_liner(long).endswith(" …"))
        self.assertLessEqual(len(one_liner(long).split()), render_repo_map.ONE_LINER_WORDS + 1)


class RepoMapRenderTests(unittest.TestCase):
    def test_model_and_md_are_deterministic_and_match_committed_artifacts(self) -> None:
        first = build_model()
        second = build_model()
        self.assertEqual(first, second)
        md = render_md(first)
        self.assertEqual(md, render_md(second))
        self.assertEqual(md, (ROOT / ".ai/repo-map.md").read_text(encoding="utf-8"))
        committed = json.loads((ROOT / ".ai/repo-map.json").read_text(encoding="utf-8"))
        self.assertEqual(committed["wordCount"], word_count(md))
        # Coverage: every agent, skill, prompt, instruction, and contract is indexed.
        self.assertEqual(8, len(first["agents"]))
        self.assertEqual(21, len(first["skills"]))
        self.assertEqual(17, len(first["prompts"]))
        self.assertEqual(3, len(first["contracts"]))

    def test_word_budget_is_enforced(self) -> None:
        with mock.patch.object(render_repo_map, "WORD_BUDGET", 50):
            with self.assertRaisesRegex(RepoMapError, "word budget"):
                render_md(build_model())

    def test_seed_must_cover_tracked_top_level_directories(self) -> None:
        seed = json.loads((ROOT / "config/repo-map-seed.json").read_text(encoding="utf-8"))
        seed["directories"] = [
            entry for entry in seed["directories"] if entry["path"] != "scripts"
        ]
        with tempfile.TemporaryDirectory() as tmp:
            trimmed = Path(tmp) / "seed.json"
            trimmed.write_text(json.dumps(seed), encoding="utf-8")
            with mock.patch.object(render_repo_map, "SEED_PATH", trimmed):
                with self.assertRaisesRegex(RepoMapError, "lacks top-level"):
                    build_model()

    def test_seed_rejects_untracked_directory_entries(self) -> None:
        seed = json.loads((ROOT / "config/repo-map-seed.json").read_text(encoding="utf-8"))
        seed["directories"].append({"path": "no-such-dir", "purpose": "ghost"})
        with tempfile.TemporaryDirectory() as tmp:
            extended = Path(tmp) / "seed.json"
            extended.write_text(json.dumps(seed), encoding="utf-8")
            with mock.patch.object(render_repo_map, "SEED_PATH", extended):
                with self.assertRaisesRegex(RepoMapError, "no tracked files"):
                    build_model()

    def test_check_mode_detects_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            md_copy = Path(tmp) / "repo-map.md"
            json_copy = Path(tmp) / "repo-map.json"
            md_copy.write_text(
                (ROOT / ".ai/repo-map.md").read_text(encoding="utf-8") + "tampered\n",
                encoding="utf-8",
            )
            json_copy.write_text(
                (ROOT / ".ai/repo-map.json").read_text(encoding="utf-8"), encoding="utf-8"
            )
            with mock.patch.object(render_repo_map, "MAP_MD_PATH", md_copy), mock.patch.object(
                render_repo_map, "MAP_JSON_PATH", json_copy
            ):
                with self.assertRaisesRegex(RepoMapError, "drifted"):
                    render(check=True)

    def test_committed_artifacts_pass_check_mode(self) -> None:
        result = render(check=True)
        self.assertEqual("check", result["mode"])
        self.assertLessEqual(result["words"], render_repo_map.WORD_BUDGET)


class KnowledgeConsumerSetTests(unittest.TestCase):
    """§7 Set A — membership now lives in validate_harness.SET_A_SURFACES (owner decision
    2026-08-10: the gate no longer parses the historical master plan; the tuple in the
    validator is the single source of truth and its git diff is the review trail).
    These two tests keep the gate honest: the live tree passes, and a surface silently
    dropping the step-1 lookup fails BY NAME — the failure mode the original design was
    built against (a green gate measuring the wrong list)."""

    def audit_root(self, root: Path) -> list[str]:
        audit = validate_harness.Audit()
        validate_harness.check_knowledge_consumer_sets(audit, root)
        return audit.errors

    def test_live_tree_carries_both_tokens_on_every_set_a_surface(self) -> None:
        self.assertEqual([], self.audit_root(ROOT))
        for name in validate_harness.SET_A_SURFACES:
            text = validate_harness.consumer_surface_path(ROOT, name).read_text(encoding="utf-8")
            self.assertIn(validate_harness.SET_A_CALL, text, name)
            self.assertIn(validate_harness.SET_A_HYDRATION_RULE, text, name)

    def test_set_a_surface_dropping_the_entry_lookup_fails_by_name(self) -> None:
        for name in validate_harness.SET_A_SURFACES:
            with self.subTest(surface=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                shutil.copytree(ROOT / ".github", root / ".github")
                path = validate_harness.consumer_surface_path(root, name)
                path.write_text(
                    path.read_text(encoding="utf-8").replace(
                        validate_harness.SET_A_CALL, "RETIRED-LOOKUP"
                    ),
                    encoding="utf-8",
                )
                errors = self.audit_root(root)
                self.assertTrue(errors, f"reverting {name} went unnoticed")
                self.assertTrue(
                    any("Set A" in m and name.removesuffix(".agent.md") in m for m in errors),
                    errors,
                )


if __name__ == "__main__":
    unittest.main()
