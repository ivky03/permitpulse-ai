"""Stage 2: train and evaluate 30-day permit-delay risk models."""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

from src.data.build_dataset import LEAKAGE_FIELDS, MODEL_FEATURES, NUMERIC_FEATURES

from .baseline import HistoricalRateBaseline
from .evaluation import choose_threshold, classification_metrics


ROOT = Path(__file__).resolve().parents[2]
TARGET_COLUMN = "issued_within_30_days"
TARGET_DAYS = 30
VALIDATION_START = pd.Timestamp("2024-01-01")
TEST_START = pd.Timestamp("2025-01-01")
MINIMUM_DELAY_RECALL = 0.80


def find_full_dataset() -> Path:
    candidates = sorted(
        path
        for path in (ROOT / "data" / "processed").glob(
            "dob_now_filings_model_*.csv.gz"
        )
        if "_sample_" not in path.name
    )
    if not candidates:
        raise FileNotFoundError(
            "No full processed dataset found. Run `python -m src.data.build_dataset` first."
        )
    return candidates[-1]


def load_model_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    frame["filing_date"] = pd.to_datetime(frame["filing_date"], errors="raise")
    frame[TARGET_COLUMN] = pd.to_numeric(frame[TARGET_COLUMN], errors="coerce")
    # The product predicts delay risk, so 1 means no first permit within 30 days.
    frame["delay_over_30_days"] = 1 - frame[TARGET_COLUMN]
    return frame


def split_by_time(
    frame: pd.DataFrame, observation_date: date
) -> dict[str, pd.DataFrame]:
    mature_end = pd.Timestamp(observation_date - timedelta(days=TARGET_DAYS))
    labeled = frame.loc[frame["delay_over_30_days"].notna()].copy()
    splits = {
        "train": labeled.loc[labeled["filing_date"] < VALIDATION_START],
        "validation": labeled.loc[
            (labeled["filing_date"] >= VALIDATION_START)
            & (labeled["filing_date"] < TEST_START)
        ],
        "test": labeled.loc[
            (labeled["filing_date"] >= TEST_START)
            & (labeled["filing_date"] <= mature_end)
        ],
    }
    if any(split.empty for split in splits.values()):
        raise ValueError("At least one time split is empty; inspect the configured dates")
    return splits


def select_features(train: pd.DataFrame) -> tuple[list[str], list[str], list[str]]:
    blocked = LEAKAGE_FIELDS | {
        "job_filing_number",
        "filing_date",
        "processing_days",
        TARGET_COLUMN,
        "issued_within_60_days",
        "issued_within_90_days",
        "delay_over_30_days",
    }
    candidates = [column for column in MODEL_FEATURES if column not in blocked]
    selected = [
        column
        for column in candidates
        if train[column].nunique(dropna=True) > 1
        and train[column].isna().mean() < 0.99
    ]
    numeric = [column for column in selected if column in NUMERIC_FEATURES]
    categorical = [column for column in selected if column not in NUMERIC_FEATURES]
    if blocked.intersection(selected):
        raise AssertionError("Leakage field entered the selected feature list")
    return selected, categorical, numeric


def logistic_pipeline(categorical: list[str], numeric: list[str]) -> Pipeline:
    preprocessing = ColumnTransformer(
        [
            (
                "categorical",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        (
                            "encoder",
                            OneHotEncoder(
                                handle_unknown="infrequent_if_exist",
                                min_frequency=50,
                            ),
                        ),
                    ]
                ),
                categorical,
            ),
            (
                "numeric",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scaler", StandardScaler()),
                    ]
                ),
                numeric,
            ),
        ]
    )
    return Pipeline(
        [
            ("preprocessing", preprocessing),
            (
                "classifier",
                LogisticRegression(max_iter=300, solver="lbfgs", random_state=42),
            ),
        ]
    )


def gradient_boosting_pipeline(
    categorical: list[str], numeric: list[str]
) -> Pipeline:
    preprocessing = ColumnTransformer(
        [
            (
                "categorical",
                Pipeline(
                    [
                        (
                            "encoder",
                            OrdinalEncoder(
                                handle_unknown="use_encoded_value",
                                unknown_value=np.nan,
                                encoded_missing_value=np.nan,
                            ),
                        )
                    ]
                ),
                categorical,
            ),
            (
                "numeric",
                Pipeline([("imputer", SimpleImputer(strategy="median"))]),
                numeric,
            ),
        ]
    )
    categorical_mask = [True] * len(categorical) + [False] * len(numeric)
    return Pipeline(
        [
            ("preprocessing", preprocessing),
            (
                "classifier",
                HistGradientBoostingClassifier(
                    learning_rate=0.08,
                    max_iter=150,
                    max_leaf_nodes=31,
                    l2_regularization=1.0,
                    categorical_features=categorical_mask,
                    random_state=42,
                ),
            ),
        ]
    )


def render_report(result: dict[str, Any]) -> str:
    rows = []
    for name, model_result in result["models"].items():
        test = model_result["test"]
        rows.append(
            "| {name} | {ap:.3f} | {auc:.3f} | {precision:.3f} | {recall:.3f} | "
            "{f1:.3f} | {brier:.3f} | {threshold:.2f} |".format(
                name=name.replace("_", " ").title(),
                ap=test["average_precision"],
                auc=test["roc_auc"],
                precision=test["delay_precision"],
                recall=test["delay_recall"],
                f1=test["delay_f1"],
                brier=test["brier_score"],
                threshold=model_result["threshold"],
            )
        )
    split_rows = "\n".join(
        f"| {name.title()} | {values['rows']:,} | {values['start']} | "
        f"{values['end']} | {values['delay_rate']:.2%} |"
        for name, values in result["splits"].items()
    )
    metric_rows = "\n".join(rows)
    return f"""# PermitPulse AI — Stage 2 Model Evaluation

Target: **risk that the first permit is not issued within 30 days**

Winner: **{result['winner'].replace('_', ' ').title()}**

Selection rule: highest validation average precision

## Time-based split

| Split | Rows | Start | End | Delay rate |
| --- | ---: | --- | --- | ---: |
{split_rows}

The model learns from the past and is tested on later filings. A random split
was intentionally rejected because construction policy and processing behavior
change over time.

## Test results

| Model | Avg precision | ROC AUC | Delay precision | Delay recall | Delay F1 | Brier | Threshold |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
{metric_rows}

The threshold is chosen on validation data to maximize precision while catching
at least {result['minimum_delay_recall']:.0%} of delayed filings. It is then
frozen before the test set is scored.

## Interpretation

- `Average precision` measures ranking quality for delayed filings; higher is better.
- `ROC AUC` measures separation between delayed and on-time filings; higher is better.
- `Delay precision` is the share of risk alerts that were actually delayed.
- `Delay recall` is the share of delayed filings that the system caught.
- `Brier score` measures probability error; lower is better.
- The historical-rate baseline groups past cases by borough, job type, and
  review type. ML must add value beyond that transparent rule.

The artifact under `artifacts/` is generated locally and excluded from Git.
`reports/model_metrics.json` records the complete machine-readable result.
"""


def run(data_path: Path, observation_date: date) -> dict[str, Any]:
    frame = load_model_frame(data_path)
    splits = split_by_time(frame, observation_date)
    selected, categorical, numeric = select_features(splits["train"])
    x = {name: split.loc[:, selected] for name, split in splits.items()}
    y = {
        name: split["delay_over_30_days"].astype(int)
        for name, split in splits.items()
    }

    models: dict[str, Any] = {
        "historical_rate_baseline": HistoricalRateBaseline(),
        "logistic_regression": logistic_pipeline(categorical, numeric),
        "gradient_boosting": gradient_boosting_pipeline(categorical, numeric),
    }
    results: dict[str, Any] = {}
    fitted: dict[str, Any] = {}
    for name, model in models.items():
        if isinstance(model, HistoricalRateBaseline):
            model.fit(x["train"], y["train"])
            validation_probability = model.predict_delay_probability(
                x["validation"]
            ).to_numpy()
            test_probability = model.predict_delay_probability(x["test"]).to_numpy()
        else:
            model.fit(x["train"], y["train"])
            validation_probability = model.predict_proba(x["validation"])[:, 1]
            test_probability = model.predict_proba(x["test"])[:, 1]
        threshold = choose_threshold(
            y["validation"].to_numpy(),
            validation_probability,
            MINIMUM_DELAY_RECALL,
        )
        results[name] = {
            "threshold": threshold,
            "validation": classification_metrics(
                y["validation"].to_numpy(), validation_probability, threshold
            ),
            "test": classification_metrics(
                y["test"].to_numpy(), test_probability, threshold
            ),
        }
        fitted[name] = model

    winner = max(
        results,
        key=lambda name: results[name]["validation"]["average_precision"],
    )
    split_summary = {
        name: {
            "rows": int(len(split)),
            "start": split["filing_date"].min().date().isoformat(),
            "end": split["filing_date"].max().date().isoformat(),
            "delay_rate": float(split["delay_over_30_days"].mean()),
        }
        for name, split in splits.items()
    }
    output = {
        "target": "delay_over_30_days",
        "observation_date": observation_date.isoformat(),
        "dataset": str(data_path.relative_to(ROOT)),
        "split_policy": {
            "train_end_exclusive": VALIDATION_START.date().isoformat(),
            "validation_end_exclusive": TEST_START.date().isoformat(),
            "test_maturity_cutoff": (
                observation_date - timedelta(days=TARGET_DAYS)
            ).isoformat(),
        },
        "minimum_delay_recall": MINIMUM_DELAY_RECALL,
        "selected_features": selected,
        "categorical_features": categorical,
        "numeric_features": numeric,
        "splits": split_summary,
        "models": results,
        "winner": winner,
    }

    (ROOT / "artifacts").mkdir(exist_ok=True)
    artifact = {
        "model": fitted[winner],
        "model_name": winner,
        "threshold": results[winner]["threshold"],
        "selected_features": selected,
        "target": output["target"],
        "observation_date": output["observation_date"],
    }
    joblib.dump(artifact, ROOT / "artifacts" / "permit_delay_model.joblib")
    (ROOT / "artifacts" / "model_metadata.json").write_text(
        json.dumps({key: value for key, value in artifact.items() if key != "model"}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    (ROOT / "reports" / "model_metrics.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    (ROOT / "reports" / "stage2_model.md").write_text(
        render_report(output), encoding="utf-8"
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-path", type=Path, default=None)
    parser.add_argument(
        "--observation-date", type=date.fromisoformat, default=date(2026, 8, 26)
    )
    args = parser.parse_args()
    result = run(args.data_path or find_full_dataset(), args.observation_date)
    summary = {
        "winner": result["winner"],
        "splits": result["splits"],
        "test_metrics": {
            name: values["test"] for name, values in result["models"].items()
        },
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
