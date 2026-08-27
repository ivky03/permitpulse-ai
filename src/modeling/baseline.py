"""Simple historical-rate baseline that ML must beat."""

from __future__ import annotations

import pandas as pd


class HistoricalRateBaseline:
    """Smoothed delay rates for comparable filing groups."""

    def __init__(
        self,
        group_columns: tuple[str, ...] = (
            "borough",
            "job_type",
            "filing_review_type",
        ),
        smoothing: float = 100.0,
    ) -> None:
        self.group_columns = group_columns
        self.smoothing = smoothing
        self.global_rate_: float | None = None
        self.group_rates_: pd.Series | None = None

    def fit(self, features: pd.DataFrame, target: pd.Series) -> "HistoricalRateBaseline":
        frame = features.loc[:, self.group_columns].fillna("__MISSING__").copy()
        frame["target"] = target.to_numpy()
        self.global_rate_ = float(target.mean())
        grouped = frame.groupby(list(self.group_columns), dropna=False)["target"].agg(
            ["sum", "count"]
        )
        self.group_rates_ = (
            grouped["sum"] + self.smoothing * self.global_rate_
        ) / (grouped["count"] + self.smoothing)
        return self

    def predict_delay_probability(self, features: pd.DataFrame) -> pd.Series:
        if self.global_rate_ is None or self.group_rates_ is None:
            raise RuntimeError("HistoricalRateBaseline must be fitted before prediction")
        keys = pd.MultiIndex.from_frame(
            features.loc[:, self.group_columns].fillna("__MISSING__")
        )
        probabilities = self.group_rates_.reindex(keys).fillna(self.global_rate_)
        return pd.Series(probabilities.to_numpy(), index=features.index, dtype=float)
