"""Create a safe, draft-only record for a future Procore integration."""

from __future__ import annotations

from typing import Any


SCHEMA_VERSION = "permitpulse.procore-risk-draft.v1"


class DemoProcoreAdapter:
    """Builds a portable draft and intentionally performs no external write."""

    def build_risk_draft(self, record: dict[str, Any]) -> dict[str, Any]:
        if record.get("status") != "approved_report_ready":
            raise ValueError("A Procore-ready draft requires an approved assessment.")
        assessment = record["assessment"]
        prediction = assessment["prediction"]
        context = record.get("project_context", {})
        plan = record["proposed_plan"]
        report = record.get("report_file", {})
        request = record.get("request", {})
        return {
            "schema_version": SCHEMA_VERSION,
            "integration_status": "draft_only_no_external_write",
            "source": {
                "system": "PermitPulse AI",
                "assessment_id": record["thread_id"],
                "model_name": assessment.get("model_context", {}).get("model_name"),
            },
            "project": {
                "name": context.get("project_name", "Unnamed project"),
                "permit_needed_by": context.get("permit_needed_by"),
                "borough": request.get("borough"),
                "job_type": request.get("job_type"),
            },
            "risk": {
                "risk_type": "Permit Schedule Risk",
                "title": "First permit may miss the 30-day planning target",
                "probability": prediction["delay_probability"],
                "risk_level": prediction["risk_level"],
                "impact_category": "Schedule",
                "response_strategy": "Mitigate",
                "status": "Draft",
                "owner": context.get("mitigation_owner", "Unassigned"),
                "reviewer_note": record.get("review", {}).get("note", ""),
            },
            "recommended_actions": plan.get("recommended_actions", []),
            "evidence": {
                "comparable_scope": assessment["historical_evidence"].get("scope"),
                "comparable_count": assessment["historical_evidence"].get("count"),
                "median_processing_days": assessment["historical_evidence"].get(
                    "median_processing_days"
                ),
                "report_filename": report.get("filename"),
                "report_sha256": report.get("sha256"),
            },
            "disclaimer": (
                "Draft integration payload only. It has not been written to Procore "
                "and is not a permit decision or compliance finding."
            ),
        }
