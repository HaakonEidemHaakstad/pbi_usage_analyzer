import os
import tempfile
import time
import unittest
from pathlib import Path

from pbi_usage_analyzer import analyze_project
from pbi_usage_analyzer.model import Status
from tools.validation.large_model import build_large_project


class LargeModelTests(unittest.TestCase):
    def test_generated_model_classifies_expected_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            result = analyze_project(build_large_project(Path(folder), tables=6, visuals=24))
        statuses = {f.ref.label: f.status for f in result.findings}
        self.assertEqual(statuses['T1[C1]'], Status.USED)            # relationship endpoint
        self.assertEqual(statuses['T1[M1_1]'], Status.USED)          # visual measure
        self.assertEqual(statuses['T0[C49]'], Status.MANUAL_REVIEW)  # T1 appends T0 (query level)
        self.assertEqual(statuses['T5[C49]'], Status.LIKELY_UNUSED)  # last table: nothing references it
        self.assertEqual({d.code for d in result.diagnostics}, {'M_LINEAGE_INCOMPLETE'})

    @unittest.skipUnless(os.environ.get('PBI_PERF'), 'set PBI_PERF=1 to run the timing check')
    def test_default_large_model_time(self):
        with tempfile.TemporaryDirectory() as folder:
            project = build_large_project(Path(folder))
            start = time.perf_counter()
            analyze_project(project)
            elapsed = time.perf_counter() - start
        # About 1 s after indexing (5.4 s before) on a development laptop.
        self.assertLess(elapsed, 3.0)


if __name__ == '__main__':
    unittest.main()
