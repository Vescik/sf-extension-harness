"""Run dependency-injected Node adapter tests; no real SDK authentication/network."""
from pathlib import Path
import shutil
import subprocess
import unittest


class JobExecutorTests(unittest.TestCase):
    def test_native_job_adapter(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for the native job adapter tests")
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([node, "--test", "tests/fixtures/salesforce_job_executor.test.mjs"],
                                cwd=root, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
