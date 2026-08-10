"""Architecture of the test suite itself.

One rule, learned the expensive way: a class that carries tests may never inherit from
another class that carries tests. Inheriting a test-bearing base silently re-runs every
inherited test in each subclass — test_knowledge_store.py used to collect 460 tests for
97 unique methods (363 accidental re-runs, ~72 s of duplicate work). Shared setUp and
helpers belong in a fixture class with NO test methods (KnowledgeStoreFixture,
FeatureFixture, OrgUsageBase are the pattern).
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent


class TestArchitectureTests(unittest.TestCase):
    def test_no_test_bearing_class_inherits_from_another(self) -> None:
        violations: list[str] = []
        for module_info in pkgutil.iter_modules([str(TESTS_DIR)]):
            if not module_info.name.startswith("test_"):
                continue
            module = importlib.import_module(f"tests.{module_info.name}")
            for name, cls in inspect.getmembers(module, inspect.isclass):
                if not issubclass(cls, unittest.TestCase) or cls.__module__ != module.__name__:
                    continue
                own_tests = any(attr.startswith("test_") for attr in vars(cls))
                if not own_tests:
                    continue
                for base in cls.__mro__[1:]:
                    if base in (unittest.TestCase, object):
                        continue
                    inherited = sorted(
                        attr for attr in vars(base) if attr.startswith("test_")
                    )
                    if inherited:
                        violations.append(
                            f"{module.__name__}.{name} inherits {len(inherited)} test(s) "
                            f"from {base.__module__}.{base.__name__} (e.g. {inherited[0]}) — "
                            "move shared setUp/helpers into a fixture class with no tests"
                        )
        self.assertEqual([], violations, "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
