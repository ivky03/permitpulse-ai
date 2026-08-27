import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from src.data.build_dataset import (
    LEAKAGE_FIELDS,
    MODEL_FEATURES,
    clean_snapshot,
    label_within_target,
    open_gzip_text,
    parse_number,
)


class BuildDatasetTests(unittest.TestCase):
    def test_model_features_block_known_leakage_fields(self) -> None:
        self.assertTrue(LEAKAGE_FIELDS.isdisjoint(MODEL_FEATURES))

    def test_fixed_horizon_label_distinguishes_negative_from_censored(self) -> None:
        observed = date(2026, 8, 26)
        self.assertTrue(
            label_within_target(
                date(2026, 8, 1), date(2026, 8, 11), observed, 30
            )
        )
        self.assertFalse(
            label_within_target(date(2026, 7, 1), None, observed, 30)
        )
        self.assertIsNone(
            label_within_target(date(2026, 8, 20), None, observed, 30)
        )

    def test_parse_number_handles_currency_and_bad_values(self) -> None:
        self.assertEqual(parse_number("$1,250.50"), 1250.5)
        self.assertIsNone(parse_number("unknown"))

    def test_cleaner_quarantines_all_ambiguous_duplicate_ids(self) -> None:
        rows = [
            {"job_filing_number": "A1", "filing_date": "2026-01-01"},
            {"job_filing_number": "A1", "filing_date": "2026-01-02"},
            {
                "job_filing_number": "B1",
                "filing_date": "2026-01-01",
                "first_permit_date": "2026-01-11",
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw.jsonl.gz"
            with open_gzip_text(raw, "wt") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")
            stats = clean_snapshot(
                raw,
                root / "clean.csv.gz",
                root / "quarantine.jsonl.gz",
                root / "cohorts.csv",
                date(2026, 8, 26),
            )
            self.assertEqual(stats["clean_rows"], 1)
            self.assertEqual(stats["duplicate_job_filing_number"], 2)
            self.assertEqual(stats["duplicate_ids_quarantined"], 1)


if __name__ == "__main__":
    unittest.main()
