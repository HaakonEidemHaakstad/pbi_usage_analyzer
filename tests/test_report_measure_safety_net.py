import unittest
from pathlib import Path

from pbi_usage_analyzer import analyze_project, analysis_to_dict
from pbi_usage_analyzer.model import EvidenceType, Status
from tools.validation.export_consistency import consistency_errors


class ReportMeasureSafetyNetTests(unittest.TestCase):
    def setUp(self):
        suite = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite'
        self.result = analyze_project(suite / '29_report_measure_safety_net')
        self.statuses = {f.ref.label: f.status for f in self.result.findings}
        self.raw = {}
        for ev in self.result.graph.evidence:
            if ev.evidence_type == EvidenceType.RAW_REPORT_REFERENCE:
                self.raw.setdefault(ev.target.label, []).append(ev)

    def test_credible_unparsed_measure_references_need_review(self):
        for label, visual in (('Sales[Revenue]', 'Visual1'), ('Sales[Gross Margin]', 'Visual2'),
                              ("Sales[Bob's Helper]", 'Visual4')):
            with self.subTest(label=label):
                self.assertEqual(self.statuses[label], Status.MANUAL_REVIEW)
                self.assertEqual(len(self.raw[label]), 1)
                self.assertIn(visual, self.raw[label][0].source_file)

    def test_weak_text_does_not_protect_measures(self):
        # "Total" is not unique (Budget[Total]); "Revenue Growth rate" is only a substring;
        # "Orphan" appears in a file that never names its table.
        for label in ('Sales[Total]', 'Sales[Growth]', 'Sales[Orphan]', 'Sales[Never]'):
            with self.subTest(label=label):
                self.assertEqual(self.statuses[label], Status.LIKELY_UNUSED)
                self.assertNotIn(label, self.raw)

    def test_structured_use_is_not_duplicated(self):
        self.assertEqual(self.statuses['Sales[Structured]'], Status.USED)
        self.assertNotIn('Sales[Structured]', self.raw)
        self.assertEqual(consistency_errors(analysis_to_dict(self.result)), [])


class QualifiedMeasurePatternTests(unittest.TestCase):
    def test_escaping_and_boundaries(self):
        from pbi_usage_analyzer.model import ObjectRef, ObjectType
        from pbi_usage_analyzer.parsers.pbir import _qualified_measure_pattern
        quoted = _qualified_measure_pattern(ObjectRef(ObjectType.MEASURE, "Bob's", 'Rate [%]'))
        self.assertTrue(quoted.search("sum('bob''s'[rate [%]]])"))
        plain = _qualified_measure_pattern(ObjectRef(ObjectType.MEASURE, 'Sales', 'Total'))
        self.assertTrue(plain.search('x + sales [total]'))
        for text in ('mysales[total]', 'x.sales[total]', 'sales[total amount]'):
            with self.subTest(text=text):
                self.assertIsNone(plain.search(text))


if __name__ == '__main__':
    unittest.main()
