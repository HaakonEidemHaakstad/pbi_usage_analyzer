"""The plain-text summary report."""
import unittest
from pathlib import Path

from pbi_usage_analyzer import analyze_project
from pbi_usage_analyzer.reporting.text_report import generate_text

SUITE = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite'


def report(name, **options):
    result = analyze_project(SUITE / name, **options)
    return generate_text(result.project.project_name, result.findings, result.context,
                         result.health_findings, result.health_filter_scope)


class TextReportTests(unittest.TestCase):
    def test_table_columns_stay_aligned_with_long_table_names(self):
        text = report('41_m_usage_aware_lineage')
        block = text.split('CLEANUP CANDIDATES BY TABLE')[1].split('\n\n')[0].splitlines()[2:]
        rows = [line for line in block if line.endswith('%')]
        self.assertTrue(rows)
        self.assertEqual(len({len(row) for row in rows}), 1)  # the Share column ends in one place

    def test_review_items_include_measures_and_say_why(self):
        text = report('41_m_usage_aware_lineage')
        review = text.split('ITEMS REQUIRING REVIEW')[1].split('RECOMMENDED NEXT STEPS')[0]
        self.assertIn('Sales[Code]: Referenced by Sales[Unused Code] (Sales[Unused Code] is Likely unused)', review)
        self.assertIn('Raw 2024[Code]: via Sales[Unused Code] -> DAX -> Sales[Code] -> Power Query', review)
        measures = report('43_legacy_report_format').split('ITEMS REQUIRING REVIEW')[1]
        self.assertIn('Sales[Total]:', measures)  # measures were missing from this list before

    def test_model_health_is_grouped_by_rule_with_relationship_endpoints(self):
        text = report('18_relationship_health')
        health = text.split('MODEL HEALTH')[1].split('RECOMMENDED NEXT STEPS')[0]
        self.assertRegex(health, r'\[Warning\] Bidirectional relationship \[RELATIONSHIP_BIDIRECTIONAL\] - \d+ finding')
        self.assertIn(' -> ', health)
        self.assertNotIn('Health rule filter', health)  # unfiltered: no filter lines
        self.assertIn("sheet 'Model health'", health)

    def test_filtered_reports_still_state_the_filter(self):
        text = report('18_relationship_health', health_severities=['info'])
        self.assertIn('Health severity filter: info', text)

    def test_report_punctuation_is_plain_ascii(self):
        for name in ('18_relationship_health', '37_duplicate_measures', '41_m_usage_aware_lineage'):
            with self.subTest(name=name):
                self.assertEqual([c for c in report(name) if ord(c) > 127], [])


if __name__ == '__main__':
    unittest.main()
