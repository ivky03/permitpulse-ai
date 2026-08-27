import unittest
from datetime import date

import numpy as np
import pandas as pd

from src.modeling.baseline import HistoricalRateBaseline
from src.modeling.evaluation import choose_threshold, classification_metrics
from src.modeling.train import split_by_time


class ModelingTests(unittest.TestCase):
    def test_time_split_excludes_immature_recent_rows(self) -> None:
        frame = pd.DataFrame(
            {
                "filing_date": pd.to_datetime(
                    ["2023-12-31", "2024-06-01", "2025-02-01", "2026-08-10"]
                ),
                "delay_over_30_days": [1.0, 0.0, 1.0, 0.0],
            }
        )
        splits = split_by_time(frame, date(2026, 8, 26))
        self.assertEqual(len(splits["train"]), 1)
        self.assertEqual(len(splits["validation"]), 1)
        self.assertEqual(len(splits["test"]), 1)

    def test_threshold_meets_delay_recall_floor(self) -> None:
        target = np.array([1, 1, 1, 1, 1, 0, 0, 0])
        probabilities = np.array([0.95, 0.85, 0.75, 0.65, 0.55, 0.70, 0.40, 0.10])
        threshold = choose_threshold(target, probabilities, minimum_delay_recall=0.80)
        metrics = classification_metrics(target, probabilities, threshold)
        self.assertGreaterEqual(metrics["delay_recall"], 0.80)

    def test_historical_baseline_falls_back_for_unseen_group(self) -> None:
        features = pd.DataFrame(
            {
                "borough": ["Queens", "Queens", "Bronx"],
                "job_type": ["A", "A", "B"],
                "filing_review_type": ["Standard", "Standard", "Standard"],
            }
        )
        target = pd.Series([1, 0, 1])
        model = HistoricalRateBaseline(smoothing=1.0).fit(features, target)
        unseen = pd.DataFrame(
            {
                "borough": ["Manhattan"],
                "job_type": ["C"],
                "filing_review_type": ["Professional"],
            }
        )
        probability = model.predict_delay_probability(unseen).iloc[0]
        self.assertAlmostEqual(probability, target.mean())


if __name__ == "__main__":
    unittest.main()
