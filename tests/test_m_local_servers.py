import unittest
from pathlib import Path

from pbi_usage_analyzer import analyze_project, analysis_to_dict
from pbi_usage_analyzer.health.model import HealthSeverity
from pbi_usage_analyzer.health.rules import LOCAL_SERVER
from tools.validation.export_consistency import consistency_errors

SCENARIO = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite/38_m_local_servers'


class LocalServerPatternTests(unittest.TestCase):
    def test_local_values(self):
        for value in ('localhost', 'LOCALHOST', 'localhost:3306', 'localhost,1433', 'localhost\\SQLEXPRESS',
                      '127.0.0.1', '127.0.0.1:5432', '::1', '[::1]:8080', '(local)', '(localdb)\\MSSQLLocalDB',
                      'http://localhost', 'https://localhost:8443/api?x=1', 'http://user@127.0.0.1/odata',
                      'driver={X};server=localhost;database=db', 'Data Source=(local)\\SQL2019;Initial Catalog=x',
                      'Host = 127.0.0.1 ;Port=5432', 'Server=tcp:localhost,1433'):
            with self.subTest(value=value):
                self.assertTrue(LOCAL_SERVER.search(value))

    def test_other_values(self):
        for value in ('sql-prod.contoso.com', 'localhostname', 'localhost.contoso.com', 'my-localhost',
                      'Hosted on localhost previously', '.', '.\\data.csv', '\\\\localhost\\share',
                      'http://localhost.contoso.com/api', 'https://example.com/?server=localhost',
                      'server=sql01;database=localhost', '127.0.0', '1127.0.0.1'):
            with self.subTest(value=value):
                self.assertFalse(LOCAL_SERVER.search(value))


class LocalServerRuleScenarioTests(unittest.TestCase):
    def test_scenario(self):
        result = analyze_project(SCENARIO)
        findings = {f.scope: f for f in result.health_findings if f.rule_id == 'POWERQUERY_LOCAL_SERVER'}
        self.assertEqual(set(findings), {'Api', 'Orders', 'Sales'})
        orders = findings['Orders']
        self.assertEqual((orders.severity, orders.confidence, orders.line), (HealthSeverity.WARNING, 'high', 8))
        self.assertTrue(orders.source_file.endswith('Orders.tmdl'))
        self.assertEqual(orders.evidence, (
            'line 8: (localdb)\\MSSQLLocalDB',
            'line 9: driver={MariaDB ODBC 3.1 Driver};server=127.0.0.1;database=aw_ops'))
        self.assertEqual(findings['Sales'].evidence, ('line 8: localhost:3306',))
        self.assertEqual(findings['Api'].line, 6)
        self.assertEqual(consistency_errors(analysis_to_dict(result)), [])


if __name__ == '__main__':
    unittest.main()
