from __future__ import annotations

import argparse
import unittest
import unittest.mock
from pathlib import Path

from scripts import copilot_role_guard as guard
from scripts import force_app_knowledge
from scripts import knowledge_search
from scripts import knowledge_store


# Subcommands that exist in the CLI parsers but are deliberately NOT reachable through the
# role guard. Adding a parser subcommand that appears in neither the guard allowlists nor
# this map fails the contract tests below: every new command needs an explicit decision.
INTENTIONALLY_UNGUARDED = {
    "force_app_knowledge": {},
    "knowledge_store": {},
    "knowledge_search": {},
}

# Parser flags the guard deliberately does not accept for a guarded subcommand.
# Empty today: the guard mirrors every parser flag. Add entries only with a rationale.
INTENTIONALLY_EXCLUDED_FLAGS: dict[str, dict[str, set[str]]] = {
    "force_app_knowledge": {},
    "knowledge_store": {},
    "knowledge_search": {},
}


def subcommand_parsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    raise AssertionError("parser has no subcommands")


def option_strings(parser: argparse.ArgumentParser) -> set[str]:
    return {
        option
        for action in parser._actions
        for option in action.option_strings
        if option not in {"-h", "--help"}
    }


class GuardParserContractTests(unittest.TestCase):
    """Pin the role-guard allowlists to the argparse surface of the guarded CLIs.

    The guard re-implements flag validation instead of importing the parsers (it must stay
    dependency-free and fail closed), which historically drifted when a parser grew a flag
    the guard did not know about. These tests make that drift a CI failure in both
    directions.
    """

    def contract(self, script_name: str, parser: argparse.ArgumentParser, guarded: dict[str, frozenset]) -> None:
        parsers = subcommand_parsers(parser)
        unguarded = INTENTIONALLY_UNGUARDED[script_name]
        excluded = INTENTIONALLY_EXCLUDED_FLAGS[script_name]

        self.assertEqual(
            set(),
            set(guarded) & set(unguarded),
            f"{script_name}: a subcommand cannot be both guarded and intentionally unguarded",
        )
        self.assertEqual(
            set(parsers),
            set(guarded) | set(unguarded),
            f"{script_name}: every parser subcommand needs a guard allowlist entry or an "
            "INTENTIONALLY_UNGUARDED declaration (and stale entries must be removed)",
        )
        for command, guard_flags in guarded.items():
            parser_flags = option_strings(parsers[command])
            self.assertEqual(
                set(),
                set(guard_flags) - parser_flags,
                f"{script_name} {command}: guard allows flags the parser does not define",
            )
            self.assertEqual(
                set(),
                parser_flags - set(guard_flags) - excluded.get(command, set()),
                f"{script_name} {command}: parser defines flags the guard would silently "
                "deny; allow them or declare them in INTENTIONALLY_EXCLUDED_FLAGS",
            )

    def test_force_app_knowledge_guard_mirrors_parser(self) -> None:
        self.contract(
            "force_app_knowledge",
            force_app_knowledge.build_parser(),
            guard.FORCE_APP_COMMAND_FLAGS,
        )

    def test_knowledge_store_guard_mirrors_parser(self) -> None:
        self.contract(
            "knowledge_store",
            knowledge_store.build_parser(),
            guard.KNOWLEDGE_STORE_COMMAND_FLAGS,
        )

    def test_knowledge_search_guard_mirrors_parser(self) -> None:
        self.contract(
            "knowledge_search",
            knowledge_search.build_parser(),
            guard.KNOWLEDGE_SEARCH_COMMAND_FLAGS,
        )

    def test_salesforce_read_lane_stays_retired(self) -> None:
        # Owner decision 2026-08-04: the CLI record-read lane was retired in favor of
        # review_soql_query on the facade. A reappearing script or guard surface means an
        # accidental resurrection, not a merge artifact to keep.
        root = Path(__file__).resolve().parents[1]
        self.assertFalse((root / "scripts" / "salesforce_read.py").exists())
        self.assertFalse(hasattr(guard, "salesforce_read_command_allowed"))
        self.assertFalse(hasattr(guard, "SALESFORCE_READ_FLAGS"))

    def test_knowledge_search_is_read_only_for_every_role(self) -> None:
        # Search never mutates canonical Knowledge; `build` only writes the ignored cache.
        for role in guard.ALLOWED_PREFIXES:
            with self.subTest(role=role):
                self.assertTrue(
                    guard.knowledge_search_command_allowed(["search", "--text", "x"], role)
                )
                self.assertTrue(guard.knowledge_search_command_allowed(["build", "--check"], role))
                self.assertFalse(guard.knowledge_search_command_allowed(["search", "--rm"], role))

    def test_knowledge_store_mutation_commands_are_role_bound(self) -> None:
        # Entry mutations stay with the knowledge roles; reads stay universal. The approve
        # and revoke commands additionally require the safety hook's chat confirmation.
        self.assertEqual(
            frozenset({
                "entry-draft", "entry-describe", "entry-approve", "entry-revoke",
                "feature-open", "feature-record", "feature-approve", "feature-revoke",
                "entry-org-attach", "entry-org-detach",
            }),
            guard.KNOWLEDGE_STORE_MUTATION_COMMANDS,
        )
        # Org attach is narrower still: config-investigator only — the org-facing role. These
        # two commands deliberately spend no chat click (owner D-3 2026-08-03: the human
        # approved the instrument, not each number); the verb-partition test in
        # test_safety_hooks asserts the click-free half, this pins the role half.
        self.assertEqual(frozenset({"config-investigator"}), guard.ORG_ATTACH_ROLES)
        self.assertEqual(
            frozenset({"entry-org-attach", "entry-org-detach"}), guard.ORG_ATTACH_COMMANDS
        )
        self.assertLessEqual(guard.ORG_ATTACH_COMMANDS, guard.KNOWLEDGE_STORE_MUTATION_COMMANDS)
        # Reads stay universal, matching the entry-review precedent.
        for read_only in ("entry-review", "feature-review", "feature-status", "feature-check"):
            self.assertNotIn(read_only, guard.KNOWLEDGE_STORE_MUTATION_COMMANDS)
        self.assertLessEqual(
            guard.KNOWLEDGE_STORE_MUTATION_COMMANDS,
            set(guard.KNOWLEDGE_STORE_COMMAND_FLAGS),
        )

    def valueless_flags(self, parser: argparse.ArgumentParser) -> set[str]:
        """Every `store_true`-style flag any subcommand of this parser declares."""
        found: set[str] = set()
        for subparser in subcommand_parsers(parser).values():
            for action in subparser._actions:
                if action.option_strings and action.nargs == 0:
                    found.update(
                        option for option in action.option_strings if option.startswith("--")
                    )
        return found - {"--help"}

    def test_valueless_flag_sets_cover_every_boolean_the_parsers_declare(self) -> None:
        # A boolean missing from these sets is a fail-open: the guard skips the token after it
        # without validating, so `build --full --rm` was allowed outright. Deriving the
        # expectation from argparse means a future store_true cannot be forgotten by hand.
        for label, parser, declared in (
            ("knowledge_search", knowledge_search.build_parser(), guard.KNOWLEDGE_SEARCH_VALUELESS_FLAGS),
            ("knowledge_store", knowledge_store.build_parser(), guard.KNOWLEDGE_STORE_VALUELESS_FLAGS),
        ):
            with self.subTest(cli=label):
                self.assertLessEqual(
                    self.valueless_flags(parser),
                    set(declared),
                    f"{label}: boolean flags missing from the valueless set fail open",
                )

    def test_a_token_after_a_boolean_flag_is_still_validated(self) -> None:
        # The membership test above cannot catch a missing branch in the guard's own loop: the
        # flag would legitimately sit in the set while the loop skipped past the token after it.
        # This is the behavioural pin. `build --full --rm` was allowed outright before the fix.
        role = sorted(guard.KNOWLEDGE_MUTATION_ROLES)[0]
        self.assertFalse(guard.knowledge_search_command_allowed(["build", "--full", "--rm"], role))
        self.assertTrue(guard.knowledge_search_command_allowed(["build", "--full"], role))
        # A flag that genuinely takes a value still consumes it.
        self.assertTrue(
            guard.knowledge_store_command_allowed(["entry-check", "--changed-since", "HEAD"], role)
        )

    def test_review_cycle_days_is_allowed_and_consumes_exactly_one_value(self) -> None:
        """The maintenance window flag, pinned on both sides of the guard/parser contract.

        Arity matters here beyond tidiness: a value-taking flag the guard believes is boolean
        lets the token after it through unvalidated, which is the fail-open shape that shipped
        once already (`build --full --rm`). So this asserts the flag is accepted WITH its value,
        that the value is genuinely consumed, and that the flag has not been added to the
        valueless set by mistake.
        """

        role = sorted(guard.KNOWLEDGE_MUTATION_ROLES)[0]
        self.assertTrue(
            guard.knowledge_store_command_allowed(
                ["entry-coverage", "--review-cycle-days", "30"], role
            )
        )
        self.assertTrue(guard.knowledge_store_command_allowed(["entry-coverage"], role))
        self.assertNotIn("--review-cycle-days", set(guard.KNOWLEDGE_STORE_VALUELESS_FLAGS))
        # An unknown flag is still refused — the allowlist is the gate, not the value shape.
        self.assertFalse(
            guard.knowledge_store_command_allowed(["entry-coverage", "--bogus", "1"], role)
        )
        # Consuming the NEXT token as the value is the guard's existing contract for every
        # value-taking flag (`--changed-since --rm` behaves identically); that is deliberate,
        # and argparse rejects the malformed value immediately afterwards. Pinned here so a
        # future reader does not mistake it for a hole this flag opened.
        self.assertEqual(
            guard.knowledge_store_command_allowed(["entry-check", "--changed-since", "--rm"], role),
            guard.knowledge_store_command_allowed(
                ["entry-coverage", "--review-cycle-days", "--rm"], role
            ),
        )
        # And the parser enforces the range, so an out-of-band window cannot reach the report.
        parser = knowledge_store.build_parser()
        parsed = parser.parse_args(["entry-coverage", "--review-cycle-days", "7"])
        self.assertEqual(7, parsed.review_cycle_days)
        self.assertEqual(30, parser.parse_args(["entry-coverage"]).review_cycle_days)
        for bad in ("0", "366", "x"):
            with self.subTest(value=bad), self.assertRaises(SystemExit):
                parser.parse_args(["entry-coverage", "--review-cycle-days", bad])

    def test_analyze_facts_is_reachable_read_only_and_value_bound(self) -> None:
        """The facts analysis stays inside the read-only grant, on both hosts.

        It re-derives facts in memory and compares digests — no entry, ledger, source pin or
        approval artifact is written (phase 2 D1) — so widening the guard to a mutation role
        would grant write capability for a read. The flag takes a value, so the guard must
        consume that value: a value-taking flag the guard treats as boolean lets the next token
        through unvalidated, which is the fail-open shape that shipped once already.
        """

        for role in sorted(guard.ALLOWED_PREFIXES):
            with self.subTest(role=role):
                for mode in ("drifted", "all-approved"):
                    self.assertTrue(
                        guard.knowledge_store_command_allowed(
                            ["entry-coverage", "--review-cycle-days", "30", "--analyze-facts", mode],
                            role,
                        )
                    )
                # `--flag=value` is how the same command is written on Windows shells often
                # enough that the guard has a branch for it; both forms must agree.
                self.assertTrue(
                    guard.knowledge_store_command_allowed(
                        ["entry-coverage", "--analyze-facts=drifted"], role
                    )
                )
        self.assertNotIn("--analyze-facts", set(guard.KNOWLEDGE_STORE_VALUELESS_FLAGS))
        self.assertNotIn("entry-coverage", guard.KNOWLEDGE_STORE_MUTATION_COMMANDS)
        # The parser is the value gate: the guard allows the flag, argparse decides the mode.
        parser = knowledge_store.build_parser()
        self.assertIsNone(parser.parse_args(["entry-coverage"]).analyze_facts)
        self.assertEqual(
            "all-approved",
            parser.parse_args(["entry-coverage", "--analyze-facts", "all-approved"]).analyze_facts,
        )
        self.assertEqual(("drifted", "all-approved"), knowledge_store.FACT_ANALYSIS_MODES)
        for bad in ("current", "ALL-APPROVED", "", "true"):
            with self.subTest(value=bad), self.assertRaises(SystemExit):
                parser.parse_args(["entry-coverage", "--analyze-facts", bad])

    def test_the_store_guard_has_the_branch_its_first_boolean_will_need(self) -> None:
        # knowledge_store declares no boolean yet, so this exercises the loop against a
        # simulated one. Without the branch the guard consumes `--rm` as `--flag`'s value and
        # returns True — the exact fail-open the search guard shipped with.
        role = sorted(guard.KNOWLEDGE_MUTATION_ROLES)[0]
        with unittest.mock.patch.dict(
            guard.KNOWLEDGE_STORE_COMMAND_FLAGS, {"entry-status": frozenset({"--flag"})}
        ), unittest.mock.patch.object(
            guard, "KNOWLEDGE_STORE_VALUELESS_FLAGS", frozenset({"--flag"})
        ):
            self.assertTrue(guard.knowledge_store_command_allowed(["entry-status", "--flag"], role))
            self.assertFalse(
                guard.knowledge_store_command_allowed(["entry-status", "--flag", "--rm"], role)
            )

    def test_role_grants_are_pinned(self) -> None:
        # Knowledge mutation stays with the knowledge roles: read commands for everyone,
        # propose/approve-claim only where a human confirmation flow exists. Widening a role
        # here must be a deliberate, reviewed change.
        self.assertEqual(
            frozenset({"config-investigator", "knowledge-curator"}),
            guard.KNOWLEDGE_MUTATION_ROLES,
        )
        self.assertEqual(
            frozenset({"config-investigator", "knowledge-curator"}),
            guard.FORCE_APP_KNOWLEDGE_ROLES,
        )
        # The curator never gains the org-usage attach lane (contract §6.6). Its only org
        # surface is the review_soql_query facade MCP tool (owner decision 2026-08-04) —
        # never an org terminal command.
        self.assertNotIn("knowledge-curator", guard.ORG_ATTACH_ROLES)


if __name__ == "__main__":
    unittest.main()
