import tempfile
import unittest
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from src.modeling.profile import build_input_profile
from src.retrieval.comparables import ComparableStore, INDEX_COLUMNS, similarity_score
from src.services.risk_service import input_warnings, local_sensitivity, prepare_input


class NumericRiskModel:
    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        risk = np.clip(pd.to_numeric(frame["initial_cost"]) / 1_000.0, 0.0, 1.0)
        return np.column_stack([1.0 - risk, risk])


class Stage3EvidenceTests(unittest.TestCase):
    def test_profile_uses_training_only_reference_values(self) -> None:
        train = pd.DataFrame({"borough": ["Queens", "Queens", "Bronx"], "cost": [10, 20, 30]})
        profile = build_input_profile(train, ["borough"], ["cost"])
        self.assertEqual(profile["reference_values"]["borough"], "Queens")
        self.assertEqual(profile["reference_values"]["cost"], 20.0)

    def test_prediction_rejects_leakage_field(self) -> None:
        with self.assertRaisesRegex(ValueError, "forbidden"):
            prepare_input(
                {"borough": "Queens", "first_permit_date": "2026-01-01"},
                ["borough"],
            )

    def test_local_sensitivity_reports_direction(self) -> None:
        prepared = pd.DataFrame([{"initial_cost": 800.0}])
        factors = local_sensitivity(
            NumericRiskModel(), prepared, {"initial_cost": 200.0}
        )
        self.assertEqual(factors[0]["direction"], "increased risk")
        self.assertAlmostEqual(factors[0]["risk_delta"], 0.6)

    def test_warning_flags_unseen_category_and_outlier(self) -> None:
        warnings = input_warnings(
            {"borough": "Unknown", "initial_cost": 5_000},
            ["borough", "initial_cost"],
            {
                "categories": {"borough": ["Queens", "Bronx"]},
                "numeric_bounds": {"initial_cost": {"p01": 10, "p99": 1_000}},
            },
            "2023-12-31",
        )
        self.assertTrue(any("not observed" in warning for warning in warnings))
        self.assertTrue(any("central 98%" in warning for warning in warnings))

    def test_similarity_rewards_matching_business_fields(self) -> None:
        request = {
            "borough": "Queens",
            "job_type": "Alteration",
            "filing_review_type": "Standard Plan Examination",
            "initial_cost": 100_000,
        }
        close = {**request, "building_type": "Other"}
        distant = {**request, "borough": "Bronx", "initial_cost": 10}
        self.assertGreater(similarity_score(request, close), similarity_score(request, distant))

    def test_duckdb_store_returns_summary_and_excludes_current_job(self) -> None:
        rows = []
        for index in range(20):
            row = {column: None for column in INDEX_COLUMNS}
            row.update(
                {
                    "job_filing_number": f"Q{index:03d}",
                    "filing_date": f"2025-01-{index + 1:02d}",
                    "borough": "Queens",
                    "job_type": "Alteration",
                    "filing_review_type": "Standard Plan Examination",
                    "building_type": "Other",
                    "initial_cost": 100_000 + index,
                    "total_construction_floor_area": 1_000,
                    "processing_days": 20 + index,
                    "issued_within_30_days": int(20 + index <= 30),
                }
            )
            rows.append(row)
        frame = pd.DataFrame(rows)
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "test.duckdb"
            connection = duckdb.connect(str(database))
            connection.register("source", frame)
            connection.execute("CREATE TABLE comparable_filings AS SELECT * FROM source")
            connection.close()
            result = ComparableStore(database).retrieve(rows[0], exclude_job="Q000")
        self.assertEqual(result["count"], 12)
        self.assertNotIn("Q000", {row["job_filing_number"] for row in result["comparables"]})
        self.assertIsNotNone(result["median_processing_days"])


if __name__ == "__main__":
    unittest.main()
