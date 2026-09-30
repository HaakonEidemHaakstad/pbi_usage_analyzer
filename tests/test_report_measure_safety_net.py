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
        # "Total" and "Orphan" appear in files that never name their table;
        # "Revenue Growth rate" is only a substring.
        for label in ('Sales[Total]', 'Sales[Growth]', 'Sales[Orphan]', 'Sales[Never]'):
            with self.subTest(label=label):
                self.assertEqual(self.statuses[label], Status.LIKELY_UNUSED)
                self.assertNotIn(label, self.raw)

    def test_structured_use_is_not_duplicated(self):
        self.assertEqual(self.statuses['Sales[Structured]'], Status.USED)
        self.assertNotIn('Sales[Structured]', self.raw)
        self.assertEqual(consistency_errors(analysis_to_dict(self.result)), [])


class ReportColumnSafetyNetTests(unittest.TestCase):
    def setUp(self):
        suite = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite'
        self.result = analyze_project(suite / '30_report_column_safety_net')
        self.statuses = {f.ref.label: f.status for f in self.result.findings}

    def test_credible_forms_need_review(self):
        for label in ('Sales[Net Amount]', 'Sales[Region]', 'Products[Name]', 'Sales[Code]', 'Sales[Year]'):
            with self.subTest(label=label):
                self.assertEqual(self.statuses[label], Status.MANUAL_REVIEW)

    def test_substrings_keys_and_tableless_names_do_not_protect(self):
        # Substrings: "amount" in "Net Amount", "c1" in "c10", "notes" in a title.
        # JSON key "name" in every page file; Customers is never named.
        for label in ('Sales[Amount]', 'Customers[Name]', 'Sales[Notes]', 'Sales[C1]', 'Sales[C10]'):
            with self.subTest(label=label):
                self.assertEqual(self.statuses[label], Status.LIKELY_UNUSED)

    def test_budget_total_title_without_table(self):
        suite = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite'
        statuses = {f.ref.label: f.status for f in analyze_project(suite / '29_report_measure_safety_net').findings}
        self.assertEqual(statuses['Budget[Total]'], Status.LIKELY_UNUSED)


class QualifiedFieldTextTests(unittest.TestCase):
    def test_dotted_boundaries(self):
        from pbi_usage_analyzer.parsers.pbir import _dotted_occurs
        for text in ('sales.amount', 'sum(sales.amount)', 'x\nsales.amount\ny'):
            with self.subTest(text=text):
                self.assertTrue(_dotted_occurs(text, 'sales.amount'))
        for text in ('mysales.amount', 'x.sales.amount', 'sales.amount2', 'sales.amount_x', 'sales.amounts'):
            with self.subTest(text=text):
                self.assertFalse(_dotted_occurs(text, 'sales.amount'))

    def test_escaping_and_boundaries(self):
        from pbi_usage_analyzer.parsers.pbir import _qualified_field_refs
        self.assertEqual(_qualified_field_refs("sum('bob''s'[rate [%]]])"), {("bob's", 'rate [%]')})
        self.assertEqual(_qualified_field_refs('x + sales [total]'), {('sales', 'total')})
        self.assertEqual(_qualified_field_refs('mysales[total]'), {('mysales', 'total')})
        for text in ('x.sales[total]', "it's[total]", '[total]'):
            with self.subTest(text=text):
                self.assertEqual(_qualified_field_refs(text), set())


if __name__ == '__main__':
    unittest.main()
