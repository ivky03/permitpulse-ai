"""Portfolio-level validation, ranking, and demo inputs."""

from __future__ import annotations

from datetime import date
from typing import Any


MAX_PORTFOLIO_ITEMS = 25
ALLOWED_REVIEW_STATUSES = {
    "new",
    "awaiting_review",
    "mitigation_open",
    "monitoring",
    "no_action",
}
RISK_ORDER = {"high": 0, "moderate": 1, "low": 2}


def normalize_project_context(value: dict[str, Any] | None) -> dict[str, Any]:
    value = value or {}
    project_name = str(value.get("project_name") or "Unnamed project").strip()[:120]
    needed_by = str(value.get("permit_needed_by") or "").strip()
    if needed_by:
        try:
            date.fromisoformat(needed_by)
        except ValueError as error:
            raise ValueError("permit_needed_by must use YYYY-MM-DD format.") from error
    owner = str(value.get("mitigation_owner") or "Unassigned").strip()[:80]
    status = str(value.get("review_status") or "new").strip().lower()
    if status not in ALLOWED_REVIEW_STATUSES:
        raise ValueError(
            "review_status must be one of: "
            + ", ".join(sorted(ALLOWED_REVIEW_STATUSES))
        )
    return {
        "project_name": project_name,
        "permit_needed_by": needed_by or None,
        "mitigation_owner": owner or "Unassigned",
        "review_status": status,
    }


def rank_portfolio(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(item: dict[str, Any]) -> tuple[Any, ...]:
        probability = item.get("delay_probability")
        return (
            RISK_ORDER.get(str(item.get("risk_level", "")).lower(), 9),
            item.get("permit_needed_by") or "9999-12-31",
            -float(probability if probability is not None else -1),
            str(item.get("project_name") or ""),
        )

    return sorted(items, key=key)


def portfolio_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(items),
        "high_risk": sum(item.get("risk_level") == "high" for item in items),
        "moderate_risk": sum(
            item.get("risk_level") == "moderate" for item in items
        ),
        "low_risk": sum(item.get("risk_level") == "low" for item in items),
        "awaiting_human_review": sum(
            item.get("status") == "awaiting_human_review" for item in items
        ),
        "unassigned": sum(
            item.get("mitigation_owner") == "Unassigned" for item in items
        ),
    }


def demo_portfolio(reference_values: dict[str, Any]) -> list[dict[str, Any]]:
    scenarios = [
        (
            "Queens Medical Office",
            "2026-09-12",
            "M. Rivera",
            {"borough": "Queens", "initial_cost": 8_000},
        ),
        (
            "Bronx School Renovation",
            "2026-09-18",
            "Unassigned",
            {"borough": "Bronx", "initial_cost": 2_500_000},
        ),
        (
            "Brooklyn Retail Fit-out",
            "2026-10-01",
            "A. Chen",
            {"borough": "Brooklyn", "initial_cost": 350_000},
        ),
        (
            "Manhattan Lobby Upgrade",
            "2026-10-14",
            "J. Patel",
            {"borough": "Manhattan", "initial_cost": 125_000},
        ),
        (
            "Queens Warehouse Alteration",
            "2026-11-03",
            "Unassigned",
            {"borough": "Queens", "initial_cost": 1_100_000},
        ),
        (
            "Staten Island Storefront",
            "2026-11-21",
            "K. Lewis",
            {"borough": "Staten Island", "initial_cost": 75_000},
        ),
    ]
    items = []
    for project, needed_by, owner, overrides in scenarios:
        features = dict(reference_values)
        features.update(overrides)
        items.append(
            {
                "features": features,
                "project_context": {
                    "project_name": project,
                    "permit_needed_by": needed_by,
                    "mitigation_owner": owner,
                    "review_status": "new",
                },
            }
        )
    return items
