import contextlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools' / 'casestudy'))
import adventureworks_good as good  # noqa: E402
from test_casestudy_sources import RAW  # noqa: E402


class GoodTwinSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.raw_dir = root / 'AdventureWorks Raw Data'
        cls.raw_dir.mkdir()
        for name, text in RAW.items():
            (cls.raw_dir / name).write_bytes(text.encode('latin-1' if 'Customer' in name else 'utf-8'))
        cls.out = root / 'good'
        cls.manifest = good.build(cls.raw_dir, cls.out)
        cls.raw = good.load_raw(cls.raw_dir)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_warehouse_sql_executes_with_keys(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript(good.schema_sql('sqlite'))
        db.executescript(good.data_sql(self.raw, 'sqlite'))
        counts = {t: db.execute(f'select count(*) from {t}').fetchone()[0] for t in good.TABLES}
        self.assertEqual(counts, self.manifest['mariadb'])
        self.assertEqual(counts['fact_sales'], 4)        # all three years (1 + 2 + 1 rows) in one table
        self.assertEqual(counts['dim_customer'], 2)      # junk/footer rows excluded
        self.assertEqual(db.execute("select FirstName, LastName from dim_customer where CustomerKey = 11001")
                         .fetchone(), ('Ana', 'Peña'))
        with self.assertRaises(sqlite3.IntegrityError):  # primary key declared
            db.execute("insert into dim_territory values (1, 'x', 'y', 'z')")
        schema = (self.out / 'mariadb' / '01_schema.sql').read_text(encoding='utf-8')
        self.assertIn('PRIMARY KEY (OrderNumber, OrderLineItem)', schema)
        self.assertIn('TerritoryKey INT NOT NULL', schema)

    def test_excel_tables_have_numeric_prices(self):
        book = load_workbook(self.out / 'excel' / 'Products.xlsx')
        self.addCleanup(book.close)
        self.assertEqual(book.sheetnames, ['ProductData', 'SubcategoryData'])
        self.assertEqual(list(book['ProductData'].tables), ['Products'])
        self.assertEqual(list(book['SubcategoryData'].tables), ['Subcategories'])
        first = next(book['ProductData'].iter_rows(min_row=2, values_only=True))
        self.assertEqual((first[0], first[-1]), (214, 34.99))

    def test_returns_folder_and_other_files(self):
        folder = self.out / 'csv' / 'returns'
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         ['README.txt', 'returns_2020.csv', 'returns_2021.csv'])
        self.assertEqual((folder / 'returns_2021.csv').read_text(encoding='utf-8'),
                         'ReturnDate,TerritoryKey,ProductKey,ReturnQuantity\n2021-03-02,2,215,2\n')
        categories = json.loads((self.out / 'json' / 'categories.json').read_text(encoding='utf-8'))
        self.assertIn({'CategoryKey': 3, 'CategoryName': 'Clothing'}, categories)  # one source of truth
        self.assertTrue((self.out / 'csv' / 'calendar.csv').is_file())
        self.assertIn('returns/README.txt', self.manifest['csv'])

    def test_duplicate_order_lines_are_rejected(self):
        raw = {**self.raw, 'sales_2021': self.raw['sales_2021'] + [self.raw['sales_2020'][0]]}
        with self.assertRaises(ValueError):
            good.table_rows(raw)

    def test_cli_refuses_existing_output(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(good.main([str(self.raw_dir), '--out', str(self.out)]), 2)


if __name__ == '__main__':
    unittest.main()
