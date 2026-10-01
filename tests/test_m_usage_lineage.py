"""Usage-aware M lineage: upstream columns follow the status of the column they feed."""
import unittest

from pbi_usage_analyzer.analysis.classify import classify
from pbi_usage_analyzer.model import DependencyGraph, Evidence, EvidenceType, ModelObject, ObjectRef, ObjectType, Status
from pbi_usage_analyzer.parsers.m_lineage import ColumnDemand, parse_column_lineage
from pbi_usage_analyzer.util import norm


def one_output(name):
    return ColumnDemand(frozenset({norm(name)}))


class PerOutputDemandTests(unittest.TestCase):
    def lineage(self, source):
        lineage = parse_column_lineage(source, {norm(t): t for t in ('A', 'B', 'Orders', 'Customers')}, 'Output')
        self.assertIsNotNone(lineage)
        return lineage

    def test_combine_maps_one_output_to_each_input(self):
        lineage = self.lineage('let C = Table.Combine({A, B}), T = Table.TransformColumnTypes(C, {{"Region", type text}}) in T')
        demands = lineage.demands(one_output('Amount'))
        for table in ('A', 'B'):
            self.assertTrue(demands[table].feeds('amount'))
            self.assertFalse(demands[table].feeds('Region'))
            # The conversion still needs Region whatever is demanded.
            self.assertIn('region', demands[table].required)

    def test_rename_maps_output_back_to_source_name(self):
        demands = self.lineage('Table.RenameColumns(A, {{"raw", "Amount"}})').demands(one_output('Amount'))
        self.assertTrue(demands['A'].feeds('raw'))
        self.assertFalse(demands['A'].feeds('Amount'))

    def test_added_column_flows_from_its_generator_reads(self):
        lineage = self.lineage('Table.AddColumn(Table.SelectRows(A, each [Active]), "Total", each [Price] * [Qty])')
        total = lineage.demands(one_output('Total'))['A']
        self.assertTrue(total.feeds('Price') and total.feeds('Qty'))
        self.assertFalse(total.feeds('Active'))  # Filter reads are requirements, not output.
        self.assertIn('active', total.required)
        other = lineage.demands(one_output('Other'))['A']
        self.assertFalse(other.feeds('Price'))
        self.assertIn('price', other.required)

    def test_expanded_alias_feeds_only_its_inner_field(self):
        lineage = self.lineage(
            'let J = Table.NestedJoin(Orders, {"CustomerKey"}, Customers, {"Key"}, "D"), '
            'E = Table.ExpandTableColumn(J, "D", {"Name", "City"}, {"CustomerName", "CustomerCity"}) in E')
        name = lineage.demands(one_output('CustomerName'))
        self.assertTrue(name['Customers'].feeds('Name'))
        self.assertFalse(name['Customers'].feeds('City'))
        self.assertTrue(name['Customers'].accepts('City'))  # Expanded names stay required.
        self.assertFalse(name['Orders'].feeds('Amount'))
        amount = lineage.demands(one_output('Amount'))
        self.assertTrue(amount['Orders'].feeds('Amount'))
        self.assertFalse(amount['Customers'].feeds('Name'))

    def test_all_output_demand_is_unchanged(self):
        lineage = self.lineage('Table.Combine({A, B})')
        self.assertTrue(lineage.demands()['A'].feeds('anything'))

    def test_unsupported_source_has_no_lineage(self):
        self.assertIsNone(parse_column_lineage('CustomFunction(A)', {'a': 'A'}, 'Output'))


class LineageClassificationTests(unittest.TestCase):
    def setUp(self):
        self.graph = DependencyGraph()
        self.down = {n: ObjectRef(ObjectType.COLUMN, 'Sales', n) for n in ('Used', 'Review', 'Unused')}
        self.up = {n: ObjectRef(ObjectType.COLUMN, 'Sales 2024', n) for n in self.down}
        self.raw = {n: ObjectRef(ObjectType.COLUMN, 'Raw', n) for n in self.down}
        for ref in [*self.down.values(), *self.up.values(), *self.raw.values()]:
            self.graph.add_object(ModelObject(ref))
        self.graph.add_evidence(Evidence(None, self.down['Used'], EvidenceType.DIRECT_REPORT_USE, 'visual'))
        self.graph.add_evidence(Evidence(None, self.down['Review'], EvidenceType.RAW_REPORT_REFERENCE, 'raw', confidence='low'))
        for name in self.down:
            self.graph.add_evidence(Evidence(self.down[name], self.up[name], EvidenceType.POWERQUERY_COLUMN_LINEAGE, 'lineage'))
            self.graph.add_evidence(Evidence(self.up[name], self.raw[name], EvidenceType.POWERQUERY_COLUMN_LINEAGE, 'lineage'))

    def statuses(self):
        return {f.ref: f.status for f in classify(self.graph)}

    def test_status_follows_lineage_through_two_hops(self):
        statuses = self.statuses()
        for table in (self.up, self.raw):
            self.assertEqual(statuses[table['Used']], Status.USED)
            self.assertEqual(statuses[table['Review']], Status.MANUAL_REVIEW)
            self.assertEqual(statuses[table['Unused']], Status.LIKELY_UNUSED)

    def test_other_evidence_still_protects_an_unused_feed(self):
        self.graph.add_evidence(Evidence(None, self.raw['Unused'], EvidenceType.POWERQUERY_COLUMN_DEPENDENCY,
                                         'required by an M step', confidence='medium'))
        self.assertEqual(self.statuses()[self.raw['Unused']], Status.MANUAL_REVIEW)

    def test_lineage_never_downgrades(self):
        self.graph.add_evidence(Evidence(None, self.up['Unused'], EvidenceType.DIRECT_REPORT_USE, 'visual'))
        statuses = self.statuses()
        self.assertEqual(statuses[self.up['Unused']], Status.USED)
        self.assertEqual(statuses[self.raw['Unused']], Status.USED)


if __name__ == '__main__':
    unittest.main()
