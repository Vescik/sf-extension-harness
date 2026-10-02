"""Run the wiki connector's isolated HTTP contract tests with the pinned package."""
from pathlib import Path
import shutil
import subprocess
import unittest


class WikiConnectorTests(unittest.TestCase):
    def test_wiki_connector(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for wiki connector tests")
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [node, "--test", "tests/fixtures/ado_wiki_tools.test.mjs", "tests/fixtures/ado_wiki_links.test.mjs"],
            cwd=root, capture_output=True, text=True, timeout=45, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
