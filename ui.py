"""Streamlit interface for the PermitPulse planning workflow."""

from __future__ import annotations

import os
from typing import Any

import pandas as pd
import requests
import streamlit as st


API_URL = os.getenv("PERMITPULSE_API_URL", "http://localhost:8000").rstrip("/")
TIMEOUT_SECONDS = 30


def api_get(path: str) -> dict[str, Any]:
    response = requests.get(f"{API_URL}{path}", timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def api_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(
        f"{API_URL}{path}", json=payload, timeout=TIMEOUT_SECONDS
    )
    if not response.ok:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise RuntimeError(str(detail))
    return response.json()


def select_value(label: str, values: list[Any], reference: Any) -> Any:
    options = [value for value in values if value not in (None, "")]
    if reference not in options and reference not in (None, ""):
        options.insert(0, reference)
    index = options.index(reference) if reference in options else 0
    return st.selectbox(label, options, index=index)


def render_result(result: dict[str, Any]) -> None:
    assessment = result["assessment"]
    prediction = assessment["prediction"]
    evidence = assessment["historical_evidence"]
    first, second, third = st.columns(3)
    first.metric("30-day delay risk", f"{prediction['delay_probability']:.1%}")
    second.metric("Risk level", prediction["risk_level"].title())
    median = evidence.get("median_processing_days")
    third.metric("Comparable median", f"{median:g} days" if median is not None else "N/A")

    st.subheader("Why the model moved")
    factors = assessment.get("sensitivity_factors", [])
    if factors:
        st.dataframe(
            pd.DataFrame(factors)[
                ["label", "observed_value", "reference_value", "risk_delta", "direction"]
            ],
            use_container_width=True,
            hide_index=True,
        )
    st.caption(assessment["sensitivity_note"])

    st.subheader("Historical evidence")
    st.write(
        f"Match scope: {evidence['scope']}. {evidence['delayed_count']} of "
        f"{evidence['count']} displayed completed cases missed 30 days."
    )
    if evidence["comparables"]:
        st.dataframe(evidence["comparables"], use_container_width=True, hide_index=True)
    st.caption(evidence["coverage_note"])

    st.subheader("Proposed checklist")
    plan = result["proposed_plan"]
    st.write(plan["summary"])
    st.write(f"**Timing:** {plan['timing']}")
    for item in plan["recommended_actions"]:
        st.markdown(f"- **{item['owner']}:** {item['action']}  \n  _Evidence: {item['evidence']}_")
    st.caption(plan["guardrail"])
    for warning in assessment.get("warnings", []):
        st.warning(warning)


st.set_page_config(page_title="PermitPulse AI", page_icon="🏗️", layout="wide")
st.title("PermitPulse AI")
st.write("Estimate 30-day permit-delay risk, inspect evidence, then approve or reject a follow-up checklist.")

try:
    metadata = api_get("/api/v1/metadata")
except Exception as error:
    st.error(f"The API is unavailable at {API_URL}: {error}")
    st.stop()

references = metadata["reference_values"]
categories = metadata["categories"]
with st.form("assessment"):
    st.caption(
        "For this portfolio demo, fields not shown below use their training reference value. "
        "The API still accepts every filing-time feature."
    )
    left, right = st.columns(2)
    with left:
        borough = select_value("Borough", categories["borough"], references["borough"])
        job_type = select_value("Job type", categories["job_type"], references["job_type"])
        review = select_value(
            "Review type",
            categories["filing_review_type"],
            references["filing_review_type"],
        )
        building = select_value(
            "Building type", categories["building_type"], references["building_type"]
        )
    with right:
        initial_cost = st.number_input(
            "Initial cost ($)", min_value=0.0, value=float(references["initial_cost"] or 0)
        )
        floor_area = st.number_input(
            "Construction floor area",
            min_value=0.0,
            value=float(references["total_construction_floor_area"] or 0),
        )
        general_work = st.checkbox("General construction work", value=True)
        plumbing_work = st.checkbox("Plumbing work")
        mechanical_work = st.checkbox("Mechanical systems work")
        structural_work = st.checkbox("Structural work")
    exclude_job = st.text_input("Current filing number (optional; excluded from comparables)")
    submitted = st.form_submit_button("Assess permit risk", type="primary")

if submitted:
    features = dict(references)
    features.update(
        {
            "borough": borough,
            "job_type": job_type,
            "filing_review_type": review,
            "building_type": building,
            "initial_cost": initial_cost,
            "total_construction_floor_area": floor_area,
            "general_construction_work_type_": "Yes" if general_work else "No",
            "plumbing_work_type": "Yes" if plumbing_work else "No",
            "mechanical_systems_work_type_": "Yes" if mechanical_work else "No",
            "structural_work_type_": "Yes" if structural_work else "No",
        }
    )
    try:
        st.session_state.result = api_post(
            "/api/v1/assessments",
            {"features": features, "exclude_job": exclude_job or None},
        )
    except Exception as error:
        st.error(f"Assessment failed: {error}")

result = st.session_state.get("result")
if result:
    render_result(result)
    if result.get("status") == "awaiting_human_review":
        note = st.text_input("Reviewer note (optional)")
        approve, reject = st.columns(2)
        decision = None
        if approve.button("Approve for human follow-up", type="primary"):
            decision = "approve"
        if reject.button("Reject checklist"):
            decision = "reject"
        if decision:
            try:
                st.session_state.result = api_post(
                    f"/api/v1/assessments/{result['thread_id']}/decision",
                    {"decision": decision, "note": note},
                )
                st.rerun()
            except Exception as error:
                st.error(f"Decision failed: {error}")
    else:
        st.success(f"Workflow status: {result['status'].replace('_', ' ')}")
        if result.get("review", {}).get("note"):
            st.write(f"Reviewer note: {result['review']['note']}")
