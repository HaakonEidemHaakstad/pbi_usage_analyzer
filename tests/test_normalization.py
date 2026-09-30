import unittest
from pbi_usage_analyzer.util import clean_name, norm, norm_key


class NormalizationTests(unittest.TestCase):
    def test_case_and_whitespace(self):
        self.assertEqual(norm("Beløp"), norm("BELØP"))
        self.assertEqual(norm("beløp"), norm("'beløp '"))
        self.assertEqual(norm_key(" Hovedbok ", "Beløp"), norm_key("hovedbok", "'beløp '"))

    def test_tmdl_quote_unescape(self):
        self.assertEqual(clean_name("'O''Brien'"), "O'Brien")


if __name__ == "__main__":
    unittest.main()
