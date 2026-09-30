import unittest

from pbi_usage_analyzer.analysis.classify import classify
from pbi_usage_analyzer.model import DependencyGraph, Evidence, EvidenceType, ModelObject, ObjectRef, ObjectType, Status


class GraphTests(unittest.TestCase):
    def test_transitive_dax_usage(self):
        graph = DependencyGraph()
        measure_a = ObjectRef(ObjectType.MEASURE, "T", "A")
        measure_b = ObjectRef(ObjectType.MEASURE, "T", "B")
        column_c = ObjectRef(ObjectType.COLUMN, "T", "C")
        for ref in (measure_a, measure_b, column_c):
            graph.add_object(ModelObject(ref=ref))
        graph.add_evidence(Evidence(None, measure_a, EvidenceType.DIRECT_REPORT_USE, "visual"))
        graph.add_evidence(Evidence(measure_a, measure_b, EvidenceType.DAX_DEPENDENCY, "A uses B"))
        graph.add_evidence(Evidence(measure_b, column_c, EvidenceType.DAX_DEPENDENCY, "B uses C"))
        findings = {f.ref: f for f in classify(graph)}
        self.assertEqual(findings[column_c].status, Status.USED)

    def test_query_dependency_is_manual_not_used(self):
        graph = DependencyGraph()
        col = ObjectRef(ObjectType.COLUMN, "Upstream", "X")
        graph.add_object(ModelObject(ref=col))
        graph.add_evidence(Evidence(ObjectRef(ObjectType.QUERY, "Downstream"), col, EvidenceType.POWERQUERY_QUERY_DEPENDENCY, "query dependency", confidence="medium"))
        findings = {f.ref: f for f in classify(graph)}
        self.assertEqual(findings[col].status, Status.MANUAL_REVIEW)


if __name__ == "__main__":
    unittest.main()
