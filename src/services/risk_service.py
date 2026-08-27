"""Evidence-backed permit-delay prediction service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from src.data.build_dataset import LEAKAGE_FIELDS, MODEL_FEATURES
from src.modeling.train import ROOT
from src.retrieval.comparables import ComparableStore, DATABASE_PATH


MODEL_PATH = ROOT / "artifacts" / "permit_delay_model.joblib"


def feature_label(column: str) -> str:
    if column == "commmunity_board":
        return "Community Board"
    return column.strip("_").replace("_", " ").title()


def coerce_to_reference(value: Any, reference: Any) -> Any:
    if value in (None, "") or reference is None:
        return value
    if isinstance(reference, bool):
        return str(value).strip().lower() in {"true", "1", "yes"}
    if isinstance(reference, (int, float)) and not isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if isinstance(reference, str):
        text = str(value).strip()
        if reference in {"YES", "NO"} and text.upper() in {"YES", "NO"}:
            return text.upper()
        return text
    return value


def prepare_input(
    request: dict[str, Any],
    selected_features: list[str],
    profile: dict[str, Any] | None = None,
) -> pd.DataFrame:
    leakage = sorted(LEAKAGE_FIELDS.intersection(request))
    if leakage:
        raise ValueError(f"Post-outcome fields are forbidden at prediction time: {leakage}")
    unknown = sorted(set(request) - set(MODEL_FEATURES))
    if unknown:
        raise ValueError(f"Unknown prediction fields: {unknown}")
    references = (profile or {}).get("reference_values", {})
    return pd.DataFrame(
        [
            {
                column: coerce_to_reference(
                    request.get(column), references.get(column)
                )
                for column in selected_features
            }
        ],
        columns=selected_features,
    )


def input_warnings(
    request: dict[str, Any],
    selected_features: list[str],
    profile: dict[str, Any],
    training_end: str,
) -> list[str]:
    warnings = [
        f"Model training data ends on {training_end}; processing conditions may have changed."
    ]
    missing = [column for column in selected_features if request.get(column) in (None, "")]
    if missing:
        warnings.append(
            f"{len(missing)} model inputs were missing and handled by the training-time imputer."
        )
    for column, bounds in profile.get("numeric_bounds", {}).items():
        value = request.get(column)
        if value in (None, ""):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            warnings.append(f"{feature_label(column)} is not numeric.")
            continue
        if number < bounds["p01"] or number > bounds["p99"]:
            warnings.append(
                f"{feature_label(column)} is outside the central 98% of training values."
            )
    for column, known_values in profile.get("categories", {}).items():
        value = coerce_to_reference(
            request.get(column), profile.get("reference_values", {}).get(column)
        )
        if value not in (None, "") and value not in known_values:
            warnings.append(f"{feature_label(column)} was not observed during training.")
    return warnings


def local_sensitivity(
    model: Any,
    prepared: pd.DataFrame,
    reference_values: dict[str, Any],
    limit: int = 5,
) -> list[dict[str, Any]]:
    original_probability = float(model.predict_proba(prepared)[:, 1][0])
    scenarios = []
    columns = []
    for column in prepared.columns:
        observed = prepared.iloc[0][column]
        reference = reference_values.get(column)
        if pd.isna(observed) or reference is None or observed == reference:
            continue
        scenario = prepared.copy()
        scenario.at[scenario.index[0], column] = reference
        scenarios.append(scenario)
        columns.append(column)
    if not scenarios:
        return []
    scenario_frame = pd.concat(scenarios, ignore_index=True)
    probabilities = model.predict_proba(scenario_frame)[:, 1]
    factors = []
    for column, probability in zip(columns, probabilities, strict=True):
        delta = original_probability - float(probability)
        factors.append(
            {
                "feature": column,
                "label": feature_label(column),
                "observed_value": prepared.iloc[0][column],
                "reference_value": reference_values[column],
                "risk_delta": round(delta, 4),
                "direction": "increased risk" if delta > 0 else "decreased risk",
            }
        )
    factors.sort(key=lambda factor: abs(factor["risk_delta"]), reverse=True)
    return factors[:limit]


class RiskService:
    def __init__(
        self,
        model_path: Path = MODEL_PATH,
        database_path: Path = DATABASE_PATH,
    ) -> None:
        if not model_path.exists():
            raise FileNotFoundError(
                "Model artifact is missing. Run `python -m src.modeling.train` first."
            )
        self.artifact = joblib.load(model_path)
        required = {"input_profile", "training_period", "categorical_features"}
        missing = sorted(required - set(self.artifact))
        if missing:
            raise ValueError(
                f"Model artifact predates Stage 3 ({missing}); retrain it before prediction."
            )
        self.store = ComparableStore(database_path)

    def assess(
        self,
        request: dict[str, Any],
        exclude_job: str | None = None,
    ) -> dict[str, Any]:
        selected = self.artifact["selected_features"]
        prepared = prepare_input(request, selected, self.artifact["input_profile"])
        probability = float(self.artifact["model"].predict_proba(prepared)[:, 1][0])
        threshold = float(self.artifact["threshold"])
        if probability >= threshold:
            risk_level = "high"
        elif probability >= max(0.35, threshold - 0.18):
            risk_level = "moderate"
        else:
            risk_level = "low"
        warnings = input_warnings(
            request,
            selected,
            self.artifact["input_profile"],
            self.artifact["training_period"]["end"],
        )
        return {
            "prediction": {
                "delay_probability": round(probability, 4),
                "on_time_probability": round(1.0 - probability, 4),
                "threshold": threshold,
                "risk_level": risk_level,
                "risk_alert": probability >= threshold,
                "target": "first permit not issued within 30 days",
            },
            "sensitivity_factors": local_sensitivity(
                self.artifact["model"],
                prepared,
                self.artifact["input_profile"]["reference_values"],
            ),
            "sensitivity_note": (
                "One feature is replaced with its training reference at a time. "
                "Effects are local, non-additive, and not causal."
            ),
            "historical_evidence": self.store.retrieve(
                request, limit=12, exclude_job=exclude_job
            ),
            "warnings": warnings,
            "model_context": {
                "model_name": self.artifact["model_name"],
                "training_period": self.artifact["training_period"],
                "observation_date": self.artifact["observation_date"],
            },
        }
