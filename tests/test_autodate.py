import shutil
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from pbi_usage_analyzer.analysis.build_graph import build_graph
from pbi_usage_analyzer.analysis.classify import classify
from pbi_usage_analyzer.discovery import discover_project
from pbi_usage_analyzer.model import EvidenceType, ObjectType, Status
from pbi_usage_analyzer.parsers.powerquery import _extract_partition_m_sources, _selected_columns
from pbi_usage_analyzer.reporting.excel_report import write_excel
from pbi_usage_analyzer.reporting.text_report import generate_text


class AutoDateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        fixture = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite/08_autodate_scope_guard'
        self.root = Path(self.tmp.name) / 'project'
        shutil.copytree(fixture, self.root)
        project = discover_project(self.root)
        self.model = project.model_folder
        self.report = project.report_folder
        self.tables = self.model / 'definition/tables'

    def analyze(self):
        ctx = build_graph(self.report, self.model)
        findings = classify(ctx.graph)
        return ctx, findings, {(f.ref.table, f.ref.name): f.status for f in findings}

    def test_synthetic_scope_and_business_counts(self):
        ctx, findings, statuses = self.analyze()
        self.assertEqual(statuses[('Sales', 'Date')], Status.MANUAL_REVIEW)
        for name in ('Amount', 'Customer'):
            self.assertEqual(statuses[('Sales', name)], Status.LIKELY_UNUSED)
        for name in ('Date', 'Year'):
            self.assertEqual(statuses[('LocalDateTable_test', name)], Status.INTERNAL)
        column_edges = [e for e in ctx.graph.evidence
                        if e.evidence_type == EvidenceType.POWERQUERY_COLUMN_DEPENDENCY]
        self.assertEqual([e.target.name for e in column_edges], ['Date'])
        self.assertTrue(column_edges[0].source_file)
        self.assertIn('2 av 3 kolonner (66.7 %)', generate_text('test', findings, ctx))
        output = Path(self.tmp.name) / 'audit.xlsx'
        write_excel(output, 'test', findings, ctx)
        book = load_workbook(output)
        self.addCleanup(book.close)
        summary = dict(book['Summary'].iter_rows(min_row=2, values_only=True))
        self.assertEqual(summary['Model columns'], 3)
        self.assertEqual(book['Column analysis'].max_row, 6)
        self.assertEqual(book['Likely unused columns'].max_row, 3)

    def test_relationship_protects_only_backing_column(self):
        internal = self.tables / 'LocalDateTable_test.tmdl'
        internal.write_text(internal.read_text().split('    partition ')[0] + '''    partition calendar = calculated
        source = CALENDAR(MIN(Sales[Date]), MAX(Sales[Date]))
''')
        business = self.tables / 'Sales.tmdl'
        business.write_text(business.read_text() + '\n    column OtherDate\n        dataType: dateTime\n        sourceColumn: OtherDate\n')
        (self.model / 'definition/relationships.tmdl').write_text('''relationship date_link
    fromColumn: 'sales'.'DATE '
    toColumn: LocalDateTable_test.Date
''')
        ctx, _, statuses = self.analyze()
        self.assertEqual(statuses[('Sales', 'Date')], Status.USED)
        self.assertEqual(statuses[('Sales', 'Amount')], Status.LIKELY_UNUSED)
        self.assertFalse(ctx.powerquery.evidence)
        self.assertEqual(statuses[('Sales', 'OtherDate')], Status.LIKELY_UNUSED)

    def test_unresolved_internal_query_warns_without_blanket_edges(self):
        p = self.tables / 'LocalDateTable_test.tmdl'
        p.write_text(p.read_text().replace('Table.SelectColumns(Source, {"Date"})', 'CustomFunction(Source)'))
        ctx, findings, _ = self.analyze()
        self.assertTrue(ctx.warnings)
        self.assertIn('backing column could not be resolved', generate_text('test', findings, ctx))
        self.assertFalse(any(e.target.object_type == ObjectType.COLUMN and
                             e.evidence_type == EvidenceType.POWERQUERY_QUERY_DEPENDENCY
                             for e in ctx.graph.evidence))

    def test_template_and_source_column_mapping(self):
        p = self.tables / 'LocalDateTable_test.tmdl'
        p.write_text(p.read_text().replace('LocalDateTable_test', 'DateTableTemplate_test')
                     .replace('Source = Sales', 'Source = #"Événements"')
                     .replace('{"Date"}', '{"DATE "}') + '\n    measure Helper = 1\n')
        p = self.tables / 'Sales.tmdl'
        p.write_text(p.read_text().replace('table Sales', "table 'Événements'")
                     .replace('column Date', "column 'Display Date'"))
        _, _, statuses = self.analyze()
        self.assertEqual(statuses[('Événements', 'Display Date')], Status.MANUAL_REVIEW)
        self.assertEqual(statuses[('Événements', 'Amount')], Status.LIKELY_UNUSED)
        self.assertEqual(statuses[('DateTableTemplate_test', 'Helper')], Status.INTERNAL)

    def test_ordinary_query_keeps_existing_conservative_behavior(self):
        p = self.tables / 'LocalDateTable_test.tmdl'
        p.write_text(p.read_text().replace('LocalDateTable_test', 'BusinessQuery'))
        _, _, statuses = self.analyze()
        for name in ('Date', 'Amount', 'Customer'):
            self.assertEqual(statuses[('Sales', name)], Status.MANUAL_REVIEW)

    def test_multiple_partitions_do_not_claim_complete_projection(self):
        p = self.tables / 'LocalDateTable_test.tmdl'
        p.write_text(p.read_text() + '''
    partition extra = m
        source = Sales
''')
        ctx, _, _ = self.analyze()
        self.assertFalse(ctx.powerquery.projected_columns)
        self.assertTrue(ctx.warnings)
        self.assertFalse(any(
            e.target.object_type == ObjectType.COLUMN
            and e.evidence_type in {EvidenceType.POWERQUERY_COLUMN_DEPENDENCY,
                                    EvidenceType.POWERQUERY_QUERY_DEPENDENCY}
            for e in ctx.graph.evidence
        ))

    def test_unresolved_selection_does_not_match_another_table(self):
        p = self.tables / 'LocalDateTable_test.tmdl'
        p.write_text(p.read_text().replace('{"Date"}', '{"MissingDate"}'))
        (self.tables / 'Other.tmdl').write_text('''table Other
    column MissingDate
        dataType: dateTime
        sourceColumn: MissingDate
''')
        ctx, _, statuses = self.analyze()
        self.assertIn('Unresolved auto-date source column: Sales[MissingDate]', ctx.warnings)
        self.assertEqual(statuses[('Other', 'MissingDate')], Status.LIKELY_UNUSED)
        self.assertFalse(any(e.evidence_type == EvidenceType.POWERQUERY_COLUMN_DEPENDENCY
                             for e in ctx.graph.evidence))

    def test_independent_internal_queries_keep_their_own_column_scope(self):
        original = (self.tables / 'LocalDateTable_test.tmdl').read_text()
        (self.tables / 'LocalDateTable_other.tmdl').write_text(
            original.replace('LocalDateTable_test', 'LocalDateTable_other')
                    .replace('Source = Sales', 'Source = Other')
                    .replace('{"Date"}', '{"ShipDate"}')
        )
        (self.tables / 'Other.tmdl').write_text('''table Other
    column ShipDate
        dataType: dateTime
        sourceColumn: ShipDate
    column Date
        dataType: dateTime
        sourceColumn: Date
''')
        ctx, _, statuses = self.analyze()
        self.assertEqual(statuses[('Sales', 'Date')], Status.MANUAL_REVIEW)
        self.assertEqual(statuses[('Other', 'ShipDate')], Status.MANUAL_REVIEW)
        self.assertEqual(statuses[('Other', 'Date')], Status.LIKELY_UNUSED)
        self.assertFalse(ctx.warnings)

    def test_projection_requires_complete_supported_shape(self):
        source = 'let Source = Sales, Selected = Table.SelectColumns(Source, {"Date"}) in Selected'
        self.assertEqual(_selected_columns(source, 'Sales'), {'Date'})
        for unsupported in (source.replace('in Selected', 'in Source'),
                            source + '\n// Table.SelectColumns(Source, {"Amount"})',
                            source.replace('in Selected', ', Extra = OtherQuery in Extra')):
            self.assertIsNone(_selected_columns(unsupported, 'Sales'))
        self.assertIsNone(_selected_columns(source, 'OtherQuery'))

    def test_only_m_partition_sources_are_extracted(self):
        text = '''table T
    partition one = m
        source = Sales
    partition two = calculated
        source = MIN(Sales[Date])
    annotation unrelated
        source = Other
'''
        self.assertEqual(_extract_partition_m_sources(text), ['Sales'])
