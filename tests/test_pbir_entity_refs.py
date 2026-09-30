import unittest
from pathlib import Path

from pbi_usage_analyzer import analyze_project, analysis_to_dict
from pbi_usage_analyzer.model import EvidenceType, Status
from tools.validation.export_consistency import consistency_errors

SUITE = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite'


class PbirEntityRefTests(unittest.TestCase):
    def setUp(self):
        self.result = analyze_project(SUITE / '31_pbir_entity_refs')
        self.statuses = {f.ref.label: f.status for f in self.result.findings}
        self.direct = {e.target.label for e in self.result.graph.evidence
                       if e.evidence_type == EvidenceType.DIRECT_REPORT_USE}

    def test_entity_source_refs_resolve_structurally(self):
        for label in ('Sales[Revenue]', 'Sales[Filter Only]', 'Sales[Region]', 'Sales[Channel]'):
            with self.subTest(label=label):
                self.assertIn(label, self.direct)
                self.assertEqual(self.statuses[label], Status.USED)
        self.assertEqual(self.statuses['Sales[Amount]'], Status.USED)  # via Revenue

    def test_hierarchy_levels(self):
        self.assertIn('Dates[Calendar]', self.direct)
        self.assertIn('Dates[Month]', self.direct)
        for label in ('Dates[Year]', 'Dates[Month]', 'Dates[Day]'):
            self.assertEqual(self.statuses[label], Status.USED, label)
        self.assertEqual(self.statuses['Dates[Other]'], Status.LIKELY_UNUSED)

    def test_auto_date_variation_protects_business_column(self):
        self.assertIn('Sales[OrderDate]', self.direct)

    def test_nothing_stale_or_raw_and_unused_stays_unused(self):
        report = self.result.context.report
        self.assertEqual(report.stale, [])
        self.assertEqual(report.raw_hits, [])
        self.assertEqual(self.statuses['Sales[Unused]'], Status.LIKELY_UNUSED)
        self.assertEqual(self.statuses['Sales[Idle]'], Status.LIKELY_UNUSED)
        self.assertEqual(consistency_errors(analysis_to_dict(self.result)), [])


if __name__ == '__main__':
    unittest.main()
