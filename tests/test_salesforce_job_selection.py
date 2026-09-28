"""Native job selection uses synthetic local caches only; no Salesforce calls."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from scripts.salesforce_job_selection import select_job
from scripts.salesforce_operation_policy import PolicyError
from scripts.salesforce_operation_session import OperationSession, SessionError
from tests.salesforce_policy_fixture import ROWS


class JobSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / ".sf").mkdir()
        self.now = datetime.now(timezone.utc)
        self.job1 = "0Af000000000001AAA"
        self.job2 = "0Af000000000002AAA"

    def cache(self, entries, filename="deploy-cache.json"):
        (self.home / ".sf" / filename).write_text(json.dumps(entries), encoding="utf-8")

    def entry(self, target="dev-sbx", seconds=0, **extra):
        return {"target-org": target, "timestamp": (self.now - timedelta(seconds=seconds)).isoformat(), **extra}

    def select(self, args):
        return select_job(["sf", *args.split()], self.home, ROWS)

    def test_latest_snapshot_survives_cache_and_alias_changes(self):
        self.cache({self.job1: self.entry(seconds=5), self.job2: self.entry(seconds=1)})
        result = self.select("project deploy report --use-most-recent --json")
        self.cache({self.job1: self.entry("production")})
        self.assertEqual(result["job"]["jobId"], self.job2)
        self.assertEqual(result["job"]["username"], ROWS[0]["username"])
        self.assertNotIn("--use-most-recent", result["parts"])
        self.assertEqual(result["parts"][4:8], ["--job-id", self.job2, "--target-org", ROWS[0]["username"]])

    def test_quick_selects_actual_newest_not_an_older_validation(self):
        self.cache({self.job1: self.entry(seconds=5, **{"dry-run": True}),
                    self.job2: self.entry(seconds=1, **{"dry-run": False})})
        result = self.select("project deploy quick -r --async")
        self.assertEqual(result["job"]["jobId"], self.job2)
        self.assertEqual(result["job"]["options"]["waitMinutes"], 0)

    def test_expired_jobs_and_stable_equal_timestamp_selection(self):
        self.cache({self.job1: self.entry(seconds=4 * 86400), self.job2: self.entry(seconds=1)})
        self.assertEqual(self.select("project deploy report -r")["job"]["jobId"], self.job2)
        self.cache({self.job1: self.entry(seconds=1), self.job2: self.entry(seconds=1)})
        self.assertEqual(self.select("project deploy report -r")["job"]["jobId"], self.job1)

    def test_cached_target_wins_but_conflicting_explicit_target_is_denied(self):
        self.cache({self.job1: self.entry("production")})
        self.assertEqual(self.select(f"project deploy report -i {self.job1}")["job"]["id"], ROWS[2]["id"])
        with self.assertRaisesRegex(PolicyError, "conflicts"):
            self.select(f"project deploy report -i {self.job1} -o dev-sbx")

    def test_uncached_explicit_report_cancel_quick_require_resolved_target(self):
        for action in ("report", "cancel", "quick"):
            with self.subTest(action=action):
                result = self.select(f"project deploy {action} -i {self.job1} -o dev-sbx")
                self.assertEqual(result["job"]["username"], ROWS[0]["username"])
                with self.assertRaises(PolicyError):
                    self.select(f"project deploy {action} -i {self.job1}")
        with self.assertRaisesRegex(PolicyError, "requires a current"):
            self.select(f"project deploy resume -i {self.job1} -o dev-sbx")

    def test_fifteen_character_id_resolves_one_eighteen_character_entry(self):
        self.cache({self.job1: self.entry()})
        self.assertEqual(self.select(f"project deploy resume -i {self.job1[:15]}")["job"]["jobId"], self.job1)
        self.cache({self.job1: self.entry(), self.job1[:15] + "BBB": self.entry()})
        with self.assertRaisesRegex(PolicyError, "Multiple"):
            self.select(f"project deploy report -i {self.job1[:15]}")

    def test_sandbox_latest_and_name_pin_parent_and_process(self):
        process = "0GR000000000001AAA"
        entry = {"timestamp": self.now.isoformat(), "prodOrgUsername": "dev-sbx",
                 "sandboxProcessObject": {"Id": process, "SandboxName": "Child"}}
        self.cache({"Child": entry}, "sandbox-create-cache.json")
        for arguments in ("org resume sandbox -l", "env:resume:sandbox --name Child", f"org resume sandbox -i {process}"):
            with self.subTest(arguments=arguments):
                selected = self.select(arguments)
                self.assertEqual(selected["job"]["jobId"], process)
                self.assertEqual(selected["targets"], [ROWS[0]["username"]])
        with self.assertRaisesRegex(PolicyError, "conflicts"):
            self.select("org resume sandbox -l -o qa-sbx")

    def test_options_and_cache_secrets_are_not_copied(self):
        self.cache({self.job1: self.entry(clientSecret="never-return", manifest="sensitive", wait=99999, api="REST")})
        selected = self.select("deploy:metadata:quick -r -w 2 --api-version 66.0")
        self.assertEqual(selected["job"]["options"], {"waitMinutes": 2, "async": False, "apiVersion": "66.0", "rest": True})
        self.assertNotIn("never-return", json.dumps(selected))
        self.assertNotIn("sensitive", json.dumps(selected))

    def test_unreviewed_options_selectors_and_waits_fail_closed(self):
        self.cache({self.job1: self.entry()})
        for extra in ("--flags-dir flags", "--coverage-formatters json", "--wait 121", "--wait 1.5", "--wait 0", "--async", "--target-org=", "--use-most-recent=true", f"--job-id {self.job1}", "--wait 1 --wait 2"):
            with self.subTest(extra=extra), self.assertRaises(PolicyError):
                self.select(f"project deploy report -r {extra}")
        with self.assertRaises(PolicyError):
            self.select("project deploy quick -r --async --wait 2")

    def test_malformed_missing_future_and_oversized_cache_fail_closed(self):
        for entries in ({}, {self.job1: self.entry(timestamp="invalid")},
                        {self.job1: self.entry(timestamp="2099-01-01T00:00:00Z")},
                        {self.job1: self.entry(timestamp="2026-09-28T01:00:00")},
                        {self.job1: self.entry(**{"target-org": "missing"})}):
            with self.subTest(entries=entries), self.assertRaises(PolicyError):
                self.cache(entries)
                self.select("project deploy report -r")
        cache = self.home / ".sf/deploy-cache.json"
        cache.write_text(" " * 1_000_001)
        with self.assertRaises(PolicyError):
            self.select("project deploy report -r")

    def test_selection_does_not_write_cache(self):
        self.cache({self.job1: self.entry()})
        cache = self.home / ".sf/deploy-cache.json"
        before = cache.read_bytes()
        self.select("project deploy cancel -r --async")
        self.assertEqual(cache.read_bytes(), before)

    def test_unsupported_scratch_is_explicit_and_other_commands_unchanged(self):
        with self.assertRaisesRegex(PolicyError, "scratch resume is not supported"):
            self.select("org resume scratch --use-most-recent")
        self.assertIsNone(self.select("project retrieve start -o dev-sbx"))


class NativeJobSessionIntegrationTests(unittest.TestCase):
    """Use the actual selector and policy, replacing only local auth inventory/UI."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.home = Path(self.temp.name) / "home"
        (self.root / "config").mkdir(parents=True)
        (self.home / ".sf").mkdir(parents=True)
        self.config = {"salesforce": {"orgs": [
            {"alias": row["aliases"][0], "environment": "prod" if index == 2 else "dev",
             "expectedOrganizationId": row["id"], "expectedInstanceHost": row["host"]}
            for index, row in enumerate(ROWS)]}}
        self.config_path = self.root / "config/harness.local.json"
        self.config_path.write_text(json.dumps(self.config))
        self.job = "0Af000000000001AAA"
        self.events = []
        self.answers = []

    def cache(self, target="dev-sbx", *, age_days=0, job=None):
        path = self.home / ".sf/deploy-cache.json"
        path.write_text(json.dumps({job or self.job: {"target-org": target,
            "timestamp": (datetime.now(timezone.utc) - timedelta(days=age_days)).isoformat()}}))

    def ask(self, event):
        self.events.append(event)
        return {"promptId": event["promptId"], "value": self.answers.pop(0) if self.answers else None}

    def prepare(self, args, ask=None):
        session = OperationSession(self.root, ask or self.ask, home=self.home, env={}, inventory=lambda *_: ROWS)
        return session.prepare({"arguments": args.split()})

    def test_latest_report_resume_cancel_have_frozen_id_and_no_selector_forwarded(self):
        self.cache()
        for action in ("report", "resume", "cancel"):
            with self.subTest(action=action):
                output = self.prepare(f"project deploy {action} --use-most-recent")
                execution = output["execution"]
                self.assertEqual(execution["kind"], "job")
                self.assertEqual(execution["job"]["jobId"], self.job)
                self.assertEqual(execution["job"]["username"], ROWS[0]["username"])
                self.assertNotIn("--use-most-recent", execution["arguments"])
                self.assertEqual(execution["targets"][0]["environment"], "dev")
        self.assertEqual(self.events, [])

    def test_quick_confirmation_binds_resolved_id_and_unknown_environment_separately(self):
        self.cache()
        self.config["salesforce"]["orgs"].pop(0)
        self.config_path.write_text(json.dumps(self.config))
        before = self.config_path.read_bytes()
        self.answers = ["stage", True]
        output = self.prepare("deploy:metadata:quick -r --async")
        self.assertEqual([event["type"] for event in self.events], ["environment", "confirmDeploy"])
        for event in self.events:
            self.assertIn(self.job, event["arguments"])
            self.assertNotIn("-r", event["arguments"])
        self.assertEqual(output["execution"]["targets"][0]["environment"], "stage")
        self.assertTrue(output["execution"]["job"]["options"]["async"])
        self.assertEqual(self.config_path.read_bytes(), before)

    def test_prod_mismatched_explicit_target_and_expired_cache_never_reach_dialog(self):
        for target, age, args in (
            ("production", 0, "project deploy quick -r"),
            ("production", 0, "project deploy report -r -o dev-sbx"),
            ("dev-sbx", 4, "project deploy report -r"),
        ):
            with self.subTest(target=target, age=age), self.assertRaises((SessionError, PolicyError)):
                self.cache(target, age_days=age)
                self.prepare(args)
        self.assertEqual(self.events, [])

    def test_latest_cache_drift_during_dialog_blocks_instead_of_reselecting(self):
        self.cache()
        def changing_answer(event):
            self.events.append(event)
            self.cache("production", job="0Af000000000002AAA")
            return {"promptId": event["promptId"], "value": True}
        with self.assertRaisesRegex(SessionError, "changed during"):
            self.prepare("project deploy quick -r", ask=changing_answer)
        self.assertEqual(self.events[0]["type"], "confirmDeploy")
        self.assertIn(self.job, self.events[0]["arguments"])

    def test_cache_drift_after_prepare_does_not_mutate_execution(self):
        self.cache()
        output = self.prepare("project deploy report -r")
        self.cache("production", job="0Af000000000002AAA")
        self.assertEqual(output["execution"]["job"]["jobId"], self.job)
        self.assertEqual(output["execution"]["job"]["id"], ROWS[0]["id"])

    def test_sandbox_name_is_concrete_process_with_parent_classification(self):
        process = "0GR000000000001AAA"
        entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "prodOrgUsername": "dev-sbx",
                 "sandboxProcessObject": {"Id": process, "SandboxName": "Child"}}
        cache = self.home / ".sf/sandbox-create-cache.json"
        cache.write_text(json.dumps({"Child": entry}))
        output = self.prepare("org resume sandbox --name Child")
        self.assertEqual(output["execution"]["job"]["jobId"], process)
        self.assertNotIn("--name", output["execution"]["arguments"])
        self.assertEqual(output["execution"]["targets"][0]["id"], ROWS[0]["id"])
        entry["prodOrgUsername"] = "production"
        cache.write_text(json.dumps({"Child": entry}))
        with self.assertRaisesRegex(SessionError, "Production CLI"):
            self.prepare("org resume sandbox -l")

    def test_flag_files_and_canceled_quick_never_produce_execution(self):
        self.cache()
        with self.assertRaises((PolicyError, SessionError)):
            self.prepare("project deploy report -r --flags-dir flags")
        self.answers = [None]
        with self.assertRaisesRegex(SessionError, "confirmed|canceled"):
            self.prepare("project deploy quick -r")


if __name__ == "__main__":
    unittest.main()
