"""Run the node check of the editor's field-rules module (no JS test runner)."""

import shutil
import subprocess
import unittest
from pathlib import Path

CHECK = Path(__file__).parent / "js" / "doris_rules_check.mjs"


@unittest.skipUnless(shutil.which("node"), "node is not installed in this environment")
class DorisRulesJsTests(unittest.TestCase):
    def test_rules_module_matches_the_policy(self):
        done = subprocess.run(["node", str(CHECK)], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("doris_rules ok", done.stdout)

    def test_picker_new_search_clears_stale_panels(self):
        check = Path(__file__).parent / "js" / "icd11_picker_check.mjs"
        done = subprocess.run(["node", str(check)], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("icd11_picker ok", done.stdout)

    def test_date_precision_clear_and_auto_search(self):
        check = Path(__file__).parent / "js" / "doris_fields_check.mjs"
        done = subprocess.run(["node", str(check)], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("doris_fields ok", done.stdout)


if __name__ == "__main__":
    unittest.main()
