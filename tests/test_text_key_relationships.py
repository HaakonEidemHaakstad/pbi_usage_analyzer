import unittest
from pathlib import Path

from pbi_usage_analyzer import analyze_project, analysis_to_dict
from pbi_usage_analyzer.health.model import HealthSeverity
from pbi_usage_analyzer.health.rules import text_key_relationships
from pbi_usage_analyzer.model import ModelObject, ObjectRef, ObjectType
from pbi_usage_analyzer.parsers.relationships import Relationship
from tools.validation.export_consistency import consistency_errors

SCENARIO = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite/39_text_key_relationships'


def column(table, name, data_type):
    return ModelObject(ObjectRef(ObjectType.COLUMN, table, name), data_type=data_type)


def relationship(name, from_column, to_column, active='true'):
    return Relationship(name, from_column, to_column, 'oneDirection', active, 'relationships.tmdl', 4)


class TextKeyRuleUnitTests(unittest.TestCase):
    def test_string_endpoints(self):
        objects = (column('A', 'Code', 'string'), column('B', 'Code', 'string'), column('A', 'Id', 'int64'),
                   column('B', 'Id', 'int64'), column('B', 'Number', 'string'),
                   column('LocalDateTable_1', 'Date', 'string'))
        relationships = [
            relationship('Text', ('A', 'Code'), ('B', 'code')),
            relationship('Int', ('A', 'Id'), ('B', 'Id')),
            relationship('Mixed inactive', ('A', 'Id'), ('B', 'Number'), active='false'),
            relationship('Unknown', ('A', 'Missing'), ('B', 'Id')),
            relationship('Internal', ('A', 'Code'), ('LocalDateTable_1', 'Date')),
            relationship('', ('A', 'Code'), ('B', 'Code')),
        ]
        findings = text_key_relationships(relationships, objects)
        self.assertEqual([f.scope for f in findings], ['Text', 'Mixed inactive'])
        self.assertEqual(findings[0].evidence, ('A[Code] dataType: string', 'B[code] dataType: string'))
        self.assertEqual(findings[1].evidence, ('A[Id] dataType: int64', 'B[Number] dataType: string'))
        self.assertEqual((findings[0].severity, findings[0].confidence, findings[0].line),
                         (HealthSeverity.INFO, 'medium', 4))


class TextKeyRuleScenarioTests(unittest.TestCase):
    def test_scenario(self):
        result = analyze_project(SCENARIO)
        findings = [f for f in result.health_findings if f.rule_id == 'RELATIONSHIP_TEXT_KEY']
        self.assertEqual([f.scope for f in findings], ['SalesTerritory'])
        self.assertEqual(findings[0].evidence, ('Sales[TerritoryKey] dataType: string',
                                                'Territory Lookup[TerritoryKey] dataType: string'))
        self.assertTrue(findings[0].source_file.endswith('relationships.tmdl'))
        self.assertEqual(findings[0].line, 1)
        self.assertEqual(consistency_errors(analysis_to_dict(result)), [])


if __name__ == '__main__':
    unittest.main()
