import unittest

from src.data.audit import markdown_table, quote_soql


class AuditHelperTests(unittest.TestCase):
    def test_quote_soql_escapes_single_quote(self) -> None:
        self.assertEqual(quote_soql("O'Brien"), "'O''Brien'")

    def test_markdown_table_handles_missing_and_pipes(self) -> None:
        rendered = markdown_table(["A", "B"], [[None, "x|y"]])
        self.assertIn("—", rendered)
        self.assertIn(r"x\|y", rendered)


if __name__ == "__main__":
    unittest.main()

