import contextlib
import filecmp
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools' / 'casestudy'))
import adventureworks_mess as case  # noqa: E402

RAW = {
    'AdventureWorks Calendar Lookup.csv': 'Date\n2020-01-01\n2021-06-01\n2022-12-31\n',
    'AdventureWorks Customer Lookup.csv': (
        'CustomerKey,Prefix,FirstName,LastName,BirthDate,MaritalStatus,Gender,EmailAddress,AnnualIncome,'
        'TotalChildren,EducationLevel,Occupation,HomeOwner\n'
        '11000,MR.,JOSÉ,O\'NEIL,1966-04-08,M,M,jose@adventure-works.com,90000,2,Bachelors,Professional,Y\n'
        '11001,MRS.,ANA,PEÑA,,S,F,ana@adventure-works.com,,0,Graduate Degree,Management,N\n'
        '30---,m,,,1900-01-01,,,,,,,,\n'
        ',,,,,,,,,,,,\n'
        'Export date 20230101 14:59:17,,,,,,,,,,,,\n'),
    'AdventureWorks Product Categories Lookup.csv': 'ProductCategoryKey,CategoryName\n1,Bikes\n3,Clothing\n',
    'AdventureWorks Product Lookup.csv': (
        'ProductKey,ProductSubcategoryKey,ProductSKU,ProductName,ModelName,ProductDescription,ProductColor,'
        'ProductSize,ProductStyle,ProductCost,ProductPrice\n'
        '214,31,HL-U509-R,"Sport-100 Helmet, Red",Sport-100,"Light, snap-on.",Red,0,0,13.0863,34.99\n'
        '215,31,SH-M897,Men\'s Sports Shorts,Shorts,Shorts.,Black,M,M,24.7459,59.99\n'),
    'AdventureWorks Product Subcategories Lookup.csv': 'ProductSubcategoryKey,SubcategoryName,ProductCategoryKey\n31,Helmets,3\n',
    'AdventureWorks Returns Data.csv': 'ReturnDate,TerritoryKey,ProductKey,ReturnQuantity\n2020-01-18,1,214,1\n2021-03-02,2,215,2\n',
    'AdventureWorks Sales Data 2020.csv': (
        'OrderDate,StockDate,OrderNumber,ProductKey,CustomerKey,TerritoryKey,OrderLineItem,OrderQuantity\n'
        '2020-01-01,2019-09-21,SO1,214,11000,1,1,1\n'),
    'AdventureWorks Sales Data 2021.csv': (
        'OrderDate,StockDate,OrderNumber,ProductKey,CustomerKey,TerritoryKey,OrderLineItem,OrderQuantity\n'
        '2021-01-01,2020-10-17,SO2,215,11001,2,1,3\n2021-02-01,2020-10-17,SO3,214,11000,1,1,1\n'),
    'AdventureWorks Sales Data 2022.csv': (
        'OrderDate,StockDate,OrderNumber,ProductKey,CustomerKey,TerritoryKey,OrderLineItem,OrderQuantity\n'
        '2022-01-01,2021-12-13,SO4,214,11001,2,1,2\n'),
    'AdventureWorks Territory Lookup.csv': (
        'SalesTerritoryKey,Region,Country,Continent\n1,Northwest,United States,North America\n2,France,France,Europe\n'),
    'Product Category Sales (Unpivot Demo).csv': 'Date,Product Category,North Region\n7/1/2022,Bikes,10\n',
}


class CaseStudySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.raw_dir = root / 'AdventureWorks Raw Data'
        cls.raw_dir.mkdir()
        for name, text in RAW.items():
            encoding = 'latin-1' if 'Customer' in name else 'utf-8'
            (cls.raw_dir / name).write_bytes(text.encode(encoding))
        (root / 'Largest companies').mkdir()
        (root / 'Largest companies' / 'Largest companies.csv').write_text('Rank, Firm\n1, BlackRock\n')
        cls.out = root / 'out'
        cls.manifest = case.build(cls.raw_dir, cls.out)
        cls.raw = case.load_raw(cls.raw_dir)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_sql_executes_and_views_join(self):
        db = sqlite3.connect(':memory:')
        db.executescript(case.schema_sql('sqlite'))
        db.executescript(case.data_sql(self.raw, 'sqlite'))
        db.executescript(case.views_sql('sqlite'))
        counts = {t: db.execute(f'select count(*) from {t}').fetchone()[0] for t in case.TABLES}
        self.assertEqual(counts, self.manifest['mariadb'])
        self.assertEqual(counts['customers'], 2)            # junk and footer rows excluded
        self.assertEqual(counts['stg_customers_raw'], 5)    # but kept in staging
        row = db.execute("select revenue, region, last_name from v_sales_report").fetchone()
        self.assertEqual(row, (2 * 34.99, 'France', 'Peña'))  # text territory key joins; latin-1 decoded
        self.assertEqual(db.execute('select sum(quantity) from v_sales_by_month').fetchone()[0], 6)
        self.assertEqual(db.execute("select product_name from dim_product where product_key = 215").fetchone()[0],
                         "Men's Sports Shorts")

    def test_mariadb_files_match_sqlite_statements(self):
        keep = lambda text: [l for l in text.split('\n') if l and not l.startswith(('USE ', 'SET NAMES'))]
        self.assertEqual(keep((self.out / 'mariadb' / '02_data.sql').read_text(encoding='utf-8')),
                         keep(case.data_sql(self.raw, 'sqlite')))
        schema = (self.out / 'mariadb' / '01_schema.sql').read_text(encoding='utf-8')
        self.assertIn('territory_key VARCHAR(10)', schema)
        self.assertIn('CHARSET=utf8mb4', schema)

    def test_literal_escaping(self):
        self.assertEqual(case.sql_literal("O'Neil"), "'O''Neil'")
        self.assertEqual(case.sql_literal('a\\b'), "'a\\\\b'")
        self.assertEqual(case.sql_literal('a\\b', dialect='sqlite'), "'a\\b'")
        self.assertEqual(case.sql_literal(''), 'NULL')
        with self.assertRaises(ValueError):
            case.sql_literal('30---', numeric=True)

    def test_excel_layout_traps(self):
        products = load_workbook(self.out / 'excel' / 'Product Master.xlsx')['Products']
        self.assertEqual(products['A4'].value, 'ProductKey')    # header below title rows
        self.assertEqual(products['K5'].value, '$34.99')         # price stored as text
        returns = load_workbook(self.out / 'excel' / 'Returns by Year.xlsx')
        self.assertEqual(returns.sheetnames, ['2020', '2021', 'Summary'])
        last = list(returns['2021'].iter_rows(values_only=True))[-1]
        self.assertEqual(last, ('TOTAL', None, None, 2))        # totals row inside the data

    def test_csv_and_json_traps(self):
        archive = self.out / 'csv' / 'sales_archive'
        self.assertTrue(filecmp.cmp(archive / 'AdventureWorks Sales Data 2020.csv',
                                    archive / 'AdventureWorks Sales Data 2020 - Copy.csv', shallow=False))
        latin = (self.out / 'csv' / 'Customer Lookup (latin1).csv').read_bytes()
        self.assertIn('JOSÉ'.encode('latin-1'), latin)
        self.assertTrue((self.out / 'csv' / 'Largest companies.csv').is_file())
        categories = json.loads((self.out / 'json' / 'product_categories.json').read_text())
        self.assertIn({'id': 3, 'name': 'Apparel'}, categories)  # conflicts with Excel "Clothing"
        territories = json.loads((self.out / 'json' / 'territories.json').read_text())
        regions = [r for c in territories['continents'] for k in c['countries'] for r in k['regions']]
        self.assertEqual(sorted(r['key'] for r in regions), [1, 2])

    def test_refuses_to_overwrite_without_force(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(case.main([str(self.raw_dir), '--out', str(self.out)]), 2)
        self.assertIn('--force', err.getvalue())


if __name__ == '__main__':
    unittest.main()
