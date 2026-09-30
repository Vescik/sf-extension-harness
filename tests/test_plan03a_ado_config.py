"""Plan 03a: JSON authority and retained project/URL isolation, without ADO access."""
from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.ado_config import ado_config_error
from scripts import copilot_safety_hook as safety
from scripts import validate_harness


CONFIG = {"ado": {
    "organization": "example-org", "project": "Example Project",
    "allowedHttpsOrigins": ["https://dev.azure.com/example-org"],
}}


class AdoConfigTests(unittest.TestCase):
    def test_valid_configuration_and_nonado_prefix_remain_usable(self):
        config = deepcopy(CONFIG)
        config["ado"]["allowedHttpsOrigins"].append("https://docs.example.com/reference")
        self.assertIsNone(ado_config_error(config))
        config["ado"]["project"] = "Zespół Projektowy"
        self.assertIsNone(ado_config_error(config))

    def test_malformed_config_and_scope_values_fail_closed_without_echoing_values(self):
        for config in (None, [], {}, {"ado": None}, {"ado": []}):
            with self.subTest(config=config):
                self.assertIsNotNone(ado_config_error(config))
        for key in ("organization", "project"):
            for value in (None, 42, False, [], {}, "", " ", " prefix", "suffix ",
                          "a\nb", "<placeholder>", "TODO", "TBD", "CHANGEme", "REPLACE_ME",
                          "your-org-slug", "your-project-name", "https://secret.invalid/x"):
                config = deepcopy(CONFIG)
                config["ado"][key] = value
                with self.subTest(key=key, value=value):
                    error = ado_config_error(config)
                    self.assertIsNotNone(error)
                    self.assertIn(f"ado.{key}", error)
                    self.assertNotIn("secret.invalid", error)

    def test_stale_broad_or_malformed_origins_are_not_scope_authority(self):
        for origin in ("https://dev.azure.com", "https://dev.azure.com/other-org",
                       "https://almsearch.dev.azure.com/example-org",
                       "https://example-org.visualstudio.com", "http://example.com",
                       "https://user:secret@example.com", "https://example.com:443",
                       "https://example.com:", "HTTPS://example.com",
                       "https://example.com?", "https://example.com#", "https://example.com/a b"):
            config = deepcopy(CONFIG)
            config["ado"]["allowedHttpsOrigins"].append(origin)
            with self.subTest(origin=origin):
                self.assertIsNotNone(ado_config_error(config))
        for origins in (None, [], [False], [CONFIG["ado"]["allowedHttpsOrigins"][0]] * 2):
            config = deepcopy(CONFIG)
            config["ado"]["allowedHttpsOrigins"] = origins
            self.assertIsNotNone(ado_config_error(config))


class AdoHookTests(unittest.TestCase):
    def invoke(self, root, payload):
        event = {"tool_name": "ado-readonly/search_wiki", "tool_input": payload}
        output = StringIO()
        with patch.object(safety, "HARNESS_ROOT", root), \
                patch("sys.stdin", StringIO(json.dumps(event))), redirect_stdout(output):
            self.assertEqual(0, safety.main())
        result = json.loads(output.getvalue())
        return "allow" if result.get("continue") else result["hookSpecificOutput"]["permissionDecision"]

    def test_real_config_load_ignores_absent_empty_and_conflicting_legacy_env(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            path = root / "config/harness.local.json"
            for env in ({}, {"ADO_ORGANIZATION": ""}, {"ADO_ORGANIZATION": " "},
                        {"ADO_ORGANIZATION": "other-org"}):
                with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                    path.write_text(json.dumps(CONFIG))
                    self.assertEqual("allow", self.invoke(root, {"project": ["Example Project"]}))
                    self.assertEqual("deny", self.invoke(root, {"project": ["Other Project"]}))
                    path.write_text('{"ado": null}')
                    self.assertEqual("deny", self.invoke(root, {"project": ["Example Project"]}))
                    path.write_text('{')
                    self.assertEqual("deny", self.invoke(root, {"project": ["Example Project"]}))

    def test_project_must_be_the_vendor_top_level_parameter(self):
        for payload in ({}, {"project": []}, {"project": ["Example Project", "Other Project"]},
                        {"project": [None]}, {"project": {"name": "Example Project"}},
                        {"projectName": "Example Project"}, {"projectId": "Example Project"},
                        {"extra": {"project": "Example Project"}}):
            with self.subTest(payload=payload):
                self.assertIsNotNone(safety.ado_scope_error(CONFIG, payload))
        for value in ("Example Project", ["Example Project"]):
            self.assertIsNone(safety.ado_scope_error(CONFIG, {"project": value}))

    def test_url_cannot_override_org_project_or_origin(self):
        for url in (
            "https://dev.azure.com/example-org/OtherProject/_wiki/wikis/wiki/12/Page",
            "https://dev.azure.com/example-org/Example%20Project/OtherProject/_wiki/wikis/wiki/12/Page",
            "https://dev.azure.com/example-org/Example%20Project/%5fwiki/wikis/wiki/OtherProject/_wiki/wikis/other/12/Page",
            "https://example-org.visualstudio.com/OtherProject/_wiki/wikis/wiki/12/Page",
            "https://dev.azure.com/other-org/Example%20Project/_apis/wit/workitems/1",
            "https://dev.azure.com/example-org-evil/Example%20Project/_apis/wit/workitems/1",
            "https://dev.azure.com/example-org/Example%20Project/../OtherProject/_wiki",
            "https://dev.azure.com/example-org/Example%20Project/%2e%2e/OtherProject/_wiki",
            "https://dev.azure.com/example-org/Example%20Project%2fOtherProject/_wiki",
            "https://dev.azure.com/example-org/Example%20Project/%5cOtherProject/_wiki",
            "http://dev.azure.com/example-org/Example%20Project/_wiki",
            "https://secret@dev.azure.com/example-org/Example%20Project/_wiki",
            "https://dev.azure.com:443/example-org/Example%20Project/_wiki",
            "https://example.com/Example%20Project/_wiki",
            "ftp://dev.azure.com/example-org/Example%20Project/_wiki",
        ):
            with self.subTest(url=url):
                self.assertIsNotNone(safety.ado_scope_error(CONFIG, {"project": "Example Project", "url": url}))
        self.assertIsNone(safety.ado_scope_error(CONFIG, {"project": "Example Project", "url":
            "https://dev.azure.com/example-org/Example%20Project/_wiki/wikis/wiki?pagePath=%2FHome"}))


class AdoWiringTests(unittest.TestCase):
    def audit_with(self, relative, mutate):
        original = validate_harness.load_json
        def changed(path, audit):
            data = original(path, audit)
            if path == validate_harness.ROOT / relative:
                data = deepcopy(data)
                mutate(data)
            return data
        audit = validate_harness.Audit()
        with patch.object(validate_harness, "load_json", changed):
            validate_harness.check_settings_and_mcp(audit)
        return audit.errors

    def test_current_wiring_passes_and_direct_vendor_or_env_cannot_return(self):
        self.assertEqual([], self.audit_with(".vscode/mcp.json", lambda data: None))
        for args in (["node_modules/@azure-devops/mcp/dist/index.js", "${env:ADO_ORGANIZATION}"],
                     ["scripts/start_ado_mcp.mjs", "other-org"]):
            errors = self.audit_with(".vscode/mcp.json", lambda data:
                data["servers"]["ado-readonly"].update(args=args))
            self.assertTrue(any("local-config launcher" in error for error in errors), errors)
        errors = self.audit_with("package.json", lambda data:
            data["dependencies"].update({"@azure-devops/mcp": "latest"}))
        self.assertTrue(any("pinned to 2.8.1" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
