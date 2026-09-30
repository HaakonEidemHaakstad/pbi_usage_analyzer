import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = """
import json
from pathlib import Path
from pbi_usage_analyzer import analyze_project, analysis_to_dict
suite = Path('tools/validation/validation_suite')
exports = {p.name: analysis_to_dict(analyze_project(p)) for p in sorted(suite.iterdir()) if p.is_dir()}
print(json.dumps(exports, sort_keys=True))
"""


class DeterminismTests(unittest.TestCase):
    def test_exports_do_not_depend_on_hash_seed(self):
        # Seeds 1 and 3 ordered set-based hierarchy levels differently before
        # levels were kept in declaration order.
        outputs = []
        for seed in ('1', '3'):
            env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH=str(ROOT))
            completed = subprocess.run([sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
                                       capture_output=True, text=True, check=True)
            outputs.append(completed.stdout)
        self.assertEqual(outputs[0], outputs[1])


if __name__ == '__main__':
    unittest.main()
