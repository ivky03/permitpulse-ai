"""Read-only MCP server over the tested PermitPulse risk services."""

from __future__ import annotations

import argparse
import logging
from functools import lru_cache
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from src.modeling.train import ROOT
from src.services.portfolio import (
    MAX_PORTFOLIO_ITEMS,
    normalize_project_context,
    portfolio_summary,
    rank_portfolio,
)
from src.services.risk_service import RiskService


logger = logging.getLogger(__name__)
READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
mcp = MCPServer(
    "permitpulse",
    title="PermitPulse AI",
    description=(
        "Read-only permit schedule-risk intelligence backed by a frozen model "
        "and NYC DOB comparable filings."
    ),
    instructions=(
        "Treat results as planning support. Never describe delay risk as a permit "
        "decision, compliance finding, or issuance guarantee."
    ),
    version="1.0.0",
)


@lru_cache(maxsize=1)
def risk_service() -> RiskService:
    return RiskService()


def compact_assessment(assessment: dict[str, Any]) -> dict[str, Any]:
    return {
        "prediction": assessment["prediction"],
        "sensitivity_factors": assessment.get("sensitivity_factors", []),
        "historical_evidence": assessment["historical_evidence"],
        "warnings": assessment.get("warnings", []),
        "model_context": assessment.get("model_context", {}),
        "disclaimer": (
            "Planning support only. This is not a permit decision, compliance "
            "finding, or issuance guarantee."
        ),
    }


@mcp.tool(
    name="assess_permit_risk",
    title="Assess permit delay risk",
    description=(
        "Estimate the risk that a filing will miss the 30-day first-permit target. "
        "Inputs must contain only facts available at filing time. Returns model "
        "evidence and warnings; it performs no external write."
    ),
    annotations=READ_ONLY,
    structured_output=True,
)
def assess_permit_risk(
    features: dict[str, Any], exclude_job: str | None = None
) -> dict[str, Any]:
    return compact_assessment(risk_service().assess(features, exclude_job=exclude_job))


@mcp.tool(
    name="find_comparable_permits",
    title="Find comparable completed permits",
    description=(
        "Retrieve comparable completed NYC DOB filings and their observed first-permit "
        "processing times. Completed-case evidence can be selective and is not causal."
    ),
    annotations=READ_ONLY,
    structured_output=True,
)
def find_comparable_permits(
    features: dict[str, Any], exclude_job: str | None = None
) -> dict[str, Any]:
    assessment = risk_service().assess(features, exclude_job=exclude_job)
    return {
        **assessment["historical_evidence"],
        "disclaimer": (
            "Comparable processing times include only filings with an observed first "
            "permit and do not guarantee the timing of another filing."
        ),
    }


@mcp.tool(
    name="prioritize_permit_portfolio",
    title="Prioritize a permit portfolio",
    description=(
        "Assess and rank up to 25 permit filings for human review. Each item requires "
        "features and may include project_context. Ranking uses risk level, needed-by "
        "date, and probability; it does not approve or modify any project."
    ),
    annotations=READ_ONLY,
    structured_output=True,
)
def prioritize_permit_portfolio(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items or len(items) > MAX_PORTFOLIO_ITEMS:
        raise ValueError(
            f"Portfolio must contain 1-{MAX_PORTFOLIO_ITEMS} filings."
        )
    ranked = []
    for index, item in enumerate(items, start=1):
        features = item.get("features")
        if not isinstance(features, dict) or not features:
            raise ValueError(f"Portfolio item {index} requires a non-empty features object.")
        context = normalize_project_context(item.get("project_context"))
        assessment = risk_service().assess(
            features, exclude_job=item.get("exclude_job")
        )
        prediction = assessment["prediction"]
        evidence = assessment["historical_evidence"]
        ranked.append(
            {
                **context,
                "risk_level": prediction["risk_level"],
                "delay_probability": prediction["delay_probability"],
                "comparable_count": evidence["count"],
                "comparable_median_days": evidence["median_processing_days"],
                "warnings": assessment.get("warnings", []),
            }
        )
    ranked = rank_portfolio(ranked)
    return {
        "summary": portfolio_summary(ranked),
        "items": ranked,
        "ranking_policy": (
            "Risk level first, then earliest permit-needed date, then probability."
        ),
        "disclaimer": "Human review is required before any mitigation or external action.",
    }


@mcp.resource(
    "permitpulse://model-card",
    name="permitpulse-model-card",
    title="PermitPulse model card",
    description="Target, evaluation, limitations, and model-selection evidence.",
    mime_type="text/markdown",
)
def model_card() -> str:
    return (ROOT / "reports" / "stage2_model.md").read_text(encoding="utf-8")


@mcp.resource(
    "permitpulse://portfolio-evaluation",
    name="permitpulse-portfolio-evaluation",
    title="PermitPulse portfolio evaluation",
    description="Operational prioritization, calibration, and subgroup evaluation.",
    mime_type="text/markdown",
)
def portfolio_evaluation() -> str:
    path = ROOT / "reports" / "portfolio_evaluation.md"
    if not path.exists():
        return "Run `python -m src.modeling.portfolio_evaluation` to create this report."
    return path.read_text(encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8003)
    args = parser.parse_args()
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
