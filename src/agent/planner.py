"""Draft a bounded action plan from model evidence."""

from __future__ import annotations

import json
import os
from typing import Any


def deterministic_plan(assessment: dict[str, Any]) -> dict[str, Any]:
    prediction = assessment["prediction"]
    evidence = assessment["historical_evidence"]
    probability = prediction["delay_probability"]
    level = prediction["risk_level"]
    median = evidence.get("median_processing_days")
    factors = assessment.get("sensitivity_factors", [])[:3]
    factor_names = [factor["label"] for factor in factors]

    if level == "high":
        timing = "Review today"
        first_action = "Hold a permit-readiness review with the project and design leads."
    elif level == "moderate":
        timing = "Review within two business days"
        first_action = "Check the filing package and near-term schedule contingency."
    else:
        timing = "Monitor at the next project review"
        first_action = "Keep the normal permit follow-up cadence and watch for changes."

    comparable_text = (
        f"The {evidence['count']} retrieved completed comparables had a median of "
        f"{median:g} days to first permit."
        if evidence.get("count") and median is not None
        else "No sufficiently similar completed cases were available."
    )
    return {
        "summary": (
            f"Model v1 estimates {probability:.1%} risk of missing the 30-day target "
            f"({level} risk). {comparable_text}"
        ),
        "timing": timing,
        "recommended_actions": [
            {
                "action": first_action,
                "owner": "Project manager",
                "evidence": "Model risk level and the 30-day planning target.",
            },
            {
                "action": "Review the retrieved comparable filings and confirm whether their scope is truly similar.",
                "owner": "Project manager",
                "evidence": comparable_text,
            },
            {
                "action": "Validate the influential filing inputs with the design professional before changing the schedule.",
                "owner": "Design lead",
                "evidence": (
                    "Largest local sensitivity fields: " + ", ".join(factor_names)
                    if factor_names
                    else "No non-reference sensitivity fields were available."
                ),
            },
        ],
        "guardrail": (
            "This is a planning checklist, not a compliance finding, issuance guarantee, "
            "or instruction to contact an agency automatically."
        ),
        "generated_by": "deterministic_fallback",
    }


class EvidencePlanner:
    """Optionally use Gemini to rewrite only the plan summary."""

    def __init__(self, use_gemini: bool | None = None) -> None:
        configured = bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))
        self.use_gemini = configured if use_gemini is None else use_gemini
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    def create_plan(self, assessment: dict[str, Any]) -> dict[str, Any]:
        plan = deterministic_plan(assessment)
        if not self.use_gemini:
            return plan
        try:
            from google import genai

            client = genai.Client()
            prompt = (
                "Rewrite the following permit-risk planning summary in at most 80 words. "
                "Use only the supplied facts. Do not add probabilities, legal/compliance "
                "claims, agency instructions, or guarantees. Return plain text only.\n\n"
                + json.dumps(
                    {
                        "summary": plan["summary"],
                        "warnings": assessment.get("warnings", []),
                        "guardrail": plan["guardrail"],
                    },
                    default=str,
                )
            )
            response = client.models.generate_content(model=self.model, contents=prompt)
            if response.text and response.text.strip():
                plan["summary"] = response.text.strip()
                plan["generated_by"] = self.model
        except Exception as error:  # The product remains usable without an LLM.
            plan["planner_warning"] = (
                f"Gemini was unavailable; deterministic wording was used ({type(error).__name__})."
            )
        return plan
