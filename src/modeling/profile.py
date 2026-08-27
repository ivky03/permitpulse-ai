"""Training-data profile used for safe online predictions."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def scalar(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


def build_input_profile(
    train: pd.DataFrame,
    categorical: list[str],
    numeric: list[str],
) -> dict[str, Any]:
    reference_values: dict[str, Any] = {}
    categories: dict[str, list[Any]] = {}
    numeric_bounds: dict[str, dict[str, float]] = {}

    for column in categorical:
        observed = train[column].dropna()
        reference_values[column] = scalar(observed.mode().iloc[0]) if len(observed) else None
        categories[column] = [scalar(value) for value in sorted(observed.unique(), key=str)]

    for column in numeric:
        observed = pd.to_numeric(train[column], errors="coerce").dropna()
        reference_values[column] = scalar(observed.median()) if len(observed) else None
        if len(observed):
            numeric_bounds[column] = {
                "p01": float(observed.quantile(0.01)),
                "p99": float(observed.quantile(0.99)),
            }

    return {
        "reference_values": reference_values,
        "categories": categories,
        "numeric_bounds": numeric_bounds,
        "missing_rates": {
            column: float(train[column].isna().mean())
            for column in (*categorical, *numeric)
        },
    }
