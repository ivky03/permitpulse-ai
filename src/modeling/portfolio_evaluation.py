"""Evaluate PermitPulse as a limited-capacity portfolio prioritization system."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import precision_score, recall_score

from src.modeling.baseline import HistoricalRateBaseline
from src.modeling.train import (
    ROOT,
    find_full_dataset,
    load_model_frame,
    split_by_time,
)
from src.services.risk_service import MODEL_PATH


REVIEW_FRACTION = 0.20


def top_fraction_metrics(
    target: np.ndarray, probabilities: np.ndarray, fraction: float = REVIEW_FRACTION
) -> dict[str, Any]:
    if not 0 < fraction <= 1:
        raise ValueError("fraction must be greater than 0 and at most 1")
    count = max(1, int(np.ceil(len(target) * fraction)))
    selected = np.argsort(-probabilities, kind="stable")[:count]
    found = int(target[selected].sum())
    total_delays = int(target.sum())
    return {
        "review_fraction": fraction,
        "reviewed_rows": count,
        "delays_found": found,
        "delays_found_per_100_reviews": 100.0 * found / count,
        "share_of_all_delays_caught": found / total_delays if total_delays else 0.0,
    }


def calibration_bins(
    target: np.ndarray, probabilities: np.ndarray, bins: int = 10
) -> list[dict[str, Any]]:
    frame = pd.DataFrame({"target": target, "probability": probabilities})
    frame["bin"] = pd.qcut(
        frame["probability"], q=bins, labels=False, duplicates="drop"
    )
    grouped = frame.groupby("bin", observed=True).agg(
        rows=("target", "size"),
        mean_predicted=("probability", "mean"),
        observed_delay_rate=("target", "mean"),
    )
    return [
        {
            "bin": int(index) + 1,
            "rows": int(row["rows"]),
            "mean_predicted": float(row["mean_predicted"]),
            "observed_delay_rate": float(row["observed_delay_rate"]),
        }
        for index, row in grouped.iterrows()
    ]


def subgroup_metrics(
    frame: pd.DataFrame,
    target: np.ndarray,
    probabilities: np.ndarray,
    threshold: float,
    column: str,
    minimum_rows: int = 2_000,
) -> list[dict[str, Any]]:
    predictions = probabilities >= threshold
    output = []
    values = frame[column].fillna("Missing").astype(str)
    for value, indexes in values.groupby(values).groups.items():
        positions = frame.index.get_indexer(indexes)
        positions = positions[positions >= 0]
        if len(positions) < minimum_rows:
            continue
        group_target = target[positions]
        group_prediction = predictions[positions]
        output.append(
            {
                "value": value,
                "rows": int(len(positions)),
                "delay_rate": float(group_target.mean()),
                "delay_precision": float(
                    precision_score(group_target, group_prediction, zero_division=0)
                ),
                "delay_recall": float(
                    recall_score(group_target, group_prediction, zero_division=0)
                ),
            }
        )
    return sorted(output, key=lambda item: (-item["rows"], item["value"]))


def expected_calibration_error(rows: list[dict[str, Any]]) -> float:
    total = sum(row["rows"] for row in rows)
    if not total:
        return 0.0
    return sum(
        row["rows"]
        * abs(row["mean_predicted"] - row["observed_delay_rate"])
        for row in rows
    ) / total


def render_figure(result: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")
    figure, axes = plt.subplots(1, 2, figsize=(13, 5.2))

    strategies = result["operational_prioritization"]
    names = ["Random", "Historical baseline", "PermitPulse"]
    values = [
        strategies["random_expected"]["delays_found_per_100_reviews"],
        strategies["historical_rate_baseline"]["delays_found_per_100_reviews"],
        strategies["permitpulse"]["delays_found_per_100_reviews"],
    ]
    bars = axes[0].bar(names, values, color=["#94A3B8", "#38BDF8", "#0F766E"])
    axes[0].set_title("Delayed filings found per 100 reviews")
    axes[0].set_ylabel("Actual delayed filings")
    axes[0].set_ylim(0, 100)
    axes[0].bar_label(bars, labels=[f"{value:.1f}" for value in values], padding=3)
    axes[0].text(
        0.5,
        -0.17,
        "Review capacity: highest-risk 20% of future-period filings",
        transform=axes[0].transAxes,
        ha="center",
        fontsize=9,
        color="#475569",
    )

    calibration = result["calibration"]
    predicted = [row["mean_predicted"] for row in calibration["bins"]]
    observed = [row["observed_delay_rate"] for row in calibration["bins"]]
    axes[1].plot([0, 1], [0, 1], linestyle="--", color="#94A3B8", label="Perfect")
    axes[1].plot(
        predicted,
        observed,
        marker="o",
        color="#0F766E",
        linewidth=2,
        label="PermitPulse",
    )
    axes[1].set_title("Probability calibration by risk decile")
    axes[1].set_xlabel("Mean predicted delay probability")
    axes[1].set_ylabel("Observed delay rate")
    axes[1].set_xlim(0, 1)
    axes[1].set_ylim(0, 1)
    axes[1].legend()
    axes[1].text(
        0.5,
        -0.17,
        f"Expected calibration error: {calibration['expected_calibration_error']:.3f}",
        transform=axes[1].transAxes,
        ha="center",
        fontsize=9,
        color="#475569",
    )

    figure.suptitle("PermitPulse portfolio evaluation", fontsize=16, fontweight="bold")
    figure.tight_layout()
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def markdown_table(rows: list[dict[str, Any]]) -> str:
    return "\n".join(
        "| {value} | {rows:,} | {rate:.1%} | {precision:.1%} | {recall:.1%} |".format(
            value=row["value"].replace("|", "\\|"),
            rows=row["rows"],
            rate=row["delay_rate"],
            precision=row["delay_precision"],
            recall=row["delay_recall"],
        )
        for row in rows
    )


def render_report(result: dict[str, Any]) -> str:
    operational = result["operational_prioritization"]
    subgroup_sections = []
    for column, rows in result["subgroups"].items():
        subgroup_sections.append(
            f"### {column.replace('_', ' ').title()}\n\n"
            "| Group | Rows | Delay rate | Alert precision | Alert recall |\n"
            "| --- | ---: | ---: | ---: | ---: |\n"
            f"{markdown_table(rows)}\n"
        )
    return f"""# PermitPulse portfolio evaluation

![Operational prioritization and calibration](figures/portfolio_evaluation.png)

Evaluation population: **{result['test_rows']:,} future-period filings** from
{result['test_period']['start']} through {result['test_period']['end']}.

## Limited-capacity review

Assume a project team can inspect only the highest-ranked {result['review_fraction']:.0%}
of filings. `Delays per 100 reviews` translates model ranking into workload value.

| Strategy | Reviewed | Delays found | Delays per 100 reviews | Share of all delays caught |
| --- | ---: | ---: | ---: | ---: |
| Random expected | {operational['random_expected']['reviewed_rows']:,} | {operational['random_expected']['delays_found']:,.1f} | {operational['random_expected']['delays_found_per_100_reviews']:.1f} | {operational['random_expected']['share_of_all_delays_caught']:.1%} |
| Historical-rate baseline | {operational['historical_rate_baseline']['reviewed_rows']:,} | {operational['historical_rate_baseline']['delays_found']:,} | {operational['historical_rate_baseline']['delays_found_per_100_reviews']:.1f} | {operational['historical_rate_baseline']['share_of_all_delays_caught']:.1%} |
| PermitPulse | {operational['permitpulse']['reviewed_rows']:,} | {operational['permitpulse']['delays_found']:,} | {operational['permitpulse']['delays_found_per_100_reviews']:.1f} | {operational['permitpulse']['share_of_all_delays_caught']:.1%} |

This is a retrospective prioritization simulation, not proof that an intervention
caused a permit to arrive sooner.

## Calibration

Expected calibration error across risk deciles: **{result['calibration']['expected_calibration_error']:.3f}**.
Calibration should be monitored after deployment because agency processing conditions
can change after the training period.

## Subgroup performance

These slices expose where alert precision or recall differs. They do not establish
fairness or causation; small groups under 2,000 future-period rows are omitted.

{chr(10).join(subgroup_sections)}

## False-negative review

At the frozen threshold, PermitPulse missed **{result['false_negatives']['rows']:,}**
actual delayed filings. The machine-readable report lists their largest borough,
job-type, and review-type concentrations for targeted error analysis.

## Decision boundary

- The evaluation uses the untouched future-period test set.
- Portfolio ranking does not authorize an external action.
- Completed comparables remain selective evidence.
- Model probabilities are planning estimates, not permit decisions or guarantees.
"""


def run(data_path: Path, observation_date: date) -> dict[str, Any]:
    artifact = joblib.load(MODEL_PATH)
    frame = load_model_frame(data_path)
    splits = split_by_time(frame, observation_date)
    selected = artifact["selected_features"]
    train = splits["train"]
    test = splits["test"].reset_index(drop=True)
    target = test["delay_over_30_days"].astype(int).to_numpy()
    probabilities = artifact["model"].predict_proba(test[selected])[:, 1]

    baseline = HistoricalRateBaseline()
    baseline.fit(train[selected], train["delay_over_30_days"].astype(int))
    baseline_probabilities = baseline.predict_delay_probability(test[selected]).to_numpy()

    reviewed_rows = max(1, int(np.ceil(len(test) * REVIEW_FRACTION)))
    delay_rate = float(target.mean())
    random_expected = {
        "review_fraction": REVIEW_FRACTION,
        "reviewed_rows": reviewed_rows,
        "delays_found": reviewed_rows * delay_rate,
        "delays_found_per_100_reviews": 100.0 * delay_rate,
        "share_of_all_delays_caught": REVIEW_FRACTION,
    }
    calibration = calibration_bins(target, probabilities)
    predictions = probabilities >= float(artifact["threshold"])
    false_negative_frame = test.loc[(target == 1) & ~predictions]
    false_negative_groups = {}
    for column in ("borough", "job_type", "filing_review_type"):
        false_negative_groups[column] = {
            str(key): int(value)
            for key, value in false_negative_frame[column]
            .fillna("Missing")
            .value_counts()
            .head(10)
            .items()
        }

    result = {
        "review_fraction": REVIEW_FRACTION,
        "test_rows": len(test),
        "test_period": artifact["test_period"],
        "operational_prioritization": {
            "random_expected": random_expected,
            "historical_rate_baseline": top_fraction_metrics(
                target, baseline_probabilities
            ),
            "permitpulse": top_fraction_metrics(target, probabilities),
        },
        "calibration": {
            "expected_calibration_error": expected_calibration_error(calibration),
            "bins": calibration,
        },
        "subgroups": {
            column: subgroup_metrics(
                test,
                target,
                probabilities,
                float(artifact["threshold"]),
                column,
            )
            for column in ("borough", "job_type", "filing_review_type")
        },
        "false_negatives": {
            "rows": int(len(false_negative_frame)),
            "largest_groups": false_negative_groups,
        },
    }
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "portfolio_evaluation.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    render_figure(result, reports / "figures" / "portfolio_evaluation.png")
    (reports / "portfolio_evaluation.md").write_text(
        render_report(result), encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-path", type=Path, default=None)
    parser.add_argument(
        "--observation-date", type=date.fromisoformat, default=date(2026, 8, 26)
    )
    args = parser.parse_args()
    result = run(args.data_path or find_full_dataset(), args.observation_date)
    print(json.dumps(result["operational_prioritization"], indent=2))


if __name__ == "__main__":
    main()
