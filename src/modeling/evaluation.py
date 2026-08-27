"""Business-aware evaluation helpers for permit-delay models."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


def choose_threshold(
    y_true: np.ndarray,
    probabilities: np.ndarray,
    minimum_delay_recall: float = 0.80,
) -> float:
    """Maximize precision while catching at least the required delayed cases."""
    candidates: list[tuple[float, float, float]] = []
    for threshold in np.arange(0.05, 0.951, 0.01):
        predictions = (probabilities >= threshold).astype(int)
        recall = recall_score(y_true, predictions, zero_division=0)
        if recall >= minimum_delay_recall:
            precision = precision_score(y_true, predictions, zero_division=0)
            candidates.append((precision, float(threshold), recall))
    if not candidates:
        return 0.50
    # Precision is primary. When tied, prefer the higher threshold.
    return round(max(candidates, key=lambda item: (item[0], item[1]))[1], 2)


def classification_metrics(
    y_true: np.ndarray,
    probabilities: np.ndarray,
    threshold: float,
) -> dict[str, Any]:
    predictions = (probabilities >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, predictions, labels=[0, 1]).ravel()
    return {
        "rows": int(len(y_true)),
        "delay_rate": float(np.mean(y_true)),
        "threshold": float(threshold),
        "roc_auc": float(roc_auc_score(y_true, probabilities)),
        "average_precision": float(average_precision_score(y_true, probabilities)),
        "brier_score": float(brier_score_loss(y_true, probabilities)),
        "accuracy": float(accuracy_score(y_true, predictions)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, predictions)),
        "delay_precision": float(precision_score(y_true, predictions, zero_division=0)),
        "delay_recall": float(recall_score(y_true, predictions, zero_division=0)),
        "delay_f1": float(f1_score(y_true, predictions, zero_division=0)),
        "false_clear_rate": float(fn / (fn + tp)) if fn + tp else 0.0,
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }
