"""Streamlit interface for durable PermitPulse assessments."""

from __future__ import annotations

import os
from typing import Any

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv


load_dotenv()
API_URL = os.getenv("PERMITPULSE_API_URL", "http://localhost:8000").rstrip("/")
TIMEOUT_SECONDS = 30


def api_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(
        f"{API_URL}{path}", params=params, timeout=TIMEOUT_SECONDS
    )
    if not response.ok:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise RuntimeError(str(detail))
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


def api_get_bytes(path: str, params: dict[str, Any] | None = None) -> bytes:
    response = requests.get(
        f"{API_URL}{path}", params=params, timeout=TIMEOUT_SECONDS
    )
    if not response.ok:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise RuntimeError(str(detail))
    return response.content


def select_value(label: str, values: list[Any], reference: Any) -> Any:
    options = [value for value in values if value not in (None, "")]
    if reference not in options and reference not in (None, ""):
        options.insert(0, reference)
    index = options.index(reference) if reference in options else 0
    return st.selectbox(label, options, index=index)


def history_label(item: dict[str, Any]) -> str:
    probability = item.get("delay_probability")
    risk = (item.get("risk_level") or "unknown").title()
    percentage = f"{probability:.0%}" if probability is not None else "N/A"
    place = item.get("borough") or "Unknown"
    job = item.get("job_type") or "Filing"
    return f"{risk} · {percentage} · {place} {job}"


def render_result(result: dict[str, Any]) -> None:
    assessment = result["assessment"]
    prediction = assessment["prediction"]
    evidence = assessment["historical_evidence"]
    first, second, third = st.columns(3)
    first.metric("30-day delay risk", f"{prediction['delay_probability']:.1%}")
    second.metric("Risk level", prediction["risk_level"].title())
    median = evidence.get("median_processing_days")
    third.metric(
        "Comparable median", f"{median:g} days" if median is not None else "N/A"
    )

    st.subheader("Why the model moved")
    factors = assessment.get("sensitivity_factors", [])
    if factors:
        st.dataframe(
            pd.DataFrame(factors)[
                [
                    "label",
                    "observed_value",
                    "reference_value",
                    "risk_delta",
                    "direction",
                ]
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
        st.dataframe(
            evidence["comparables"], use_container_width=True, hide_index=True
        )
    st.caption(evidence["coverage_note"])

    st.subheader("Proposed checklist")
    plan = result["proposed_plan"]
    st.write(plan["summary"])
    st.write(f"**Timing:** {plan['timing']}")
    for item in plan["recommended_actions"]:
        st.markdown(
            f"- **{item['owner']}:** {item['action']}  \n"
            f"  _Evidence: {item['evidence']}_"
        )
    st.caption(plan["guardrail"])
    for warning in assessment.get("warnings", []):
        st.warning(warning)


st.set_page_config(page_title="PermitPulse AI", page_icon="🏗️", layout="wide")
st.title("PermitPulse AI")
st.write(
    "Estimate 30-day permit-delay risk, inspect evidence, then approve or reject "
    "a human-reviewed downloadable report."
)

try:
    metadata = api_get("/api/v1/metadata")
except Exception as error:
    st.error(f"The API is unavailable at {API_URL}: {error}")
    st.stop()

with st.sidebar:
    st.header("Demo workspace")
    default_workspace = st.query_params.get("workspace", "")
    workspace_input = st.text_input(
        "Workspace ID",
        value=st.session_state.get("workspace_id", default_workspace),
        placeholder="vignesh-demo",
        help="3-64 letters, numbers, underscores or hyphens.",
    )
    if st.button("Open workspace", type="primary", use_container_width=True):
        try:
            history = api_get("/api/v1/history", {"workspace_id": workspace_input})
            st.session_state.workspace_id = history["workspace_id"]
            st.query_params["workspace"] = history["workspace_id"]
            st.session_state.pop("result", None)
            st.rerun()
        except Exception as error:
            st.error(error)
    st.caption("Demo separation only—not authentication. Do not enter sensitive data.")

workspace_id = st.session_state.get("workspace_id")
if not workspace_id:
    st.info("Enter a demo workspace ID in the sidebar to begin or reopen history.")
    st.stop()

try:
    history_items = api_get(
        "/api/v1/history", {"workspace_id": workspace_id}
    )["items"]
except Exception as error:
    st.error(f"History could not be loaded: {error}")
    history_items = []

with st.sidebar:
    st.divider()
    st.subheader("Assessment history")
    if st.button("＋ New assessment", use_container_width=True):
        st.session_state.pop("result", None)
        st.rerun()
    if not history_items:
        st.caption("No assessments yet.")
    for item in history_items:
        if st.button(
            history_label(item),
            key=f"history-{item['thread_id']}",
            use_container_width=True,
        ):
            try:
                st.session_state.result = api_get(
                    f"/api/v1/history/{item['thread_id']}",
                    {"workspace_id": workspace_id},
                )
                st.rerun()
            except Exception as error:
                st.error(error)

references = metadata["reference_values"]
categories = metadata["categories"]
if "result" not in st.session_state:
    st.subheader("New permit assessment")
    with st.form("assessment"):
        st.caption(
            "For this portfolio demo, fields not shown use their training reference "
            "value. The API still accepts every filing-time feature."
        )
        left, right = st.columns(2)
        with left:
            borough = select_value(
                "Borough", categories["borough"], references["borough"]
            )
            job_type = select_value(
                "Job type", categories["job_type"], references["job_type"]
            )
            review = select_value(
                "Review type",
                categories["filing_review_type"],
                references["filing_review_type"],
            )
            building = select_value(
                "Building type",
                categories["building_type"],
                references["building_type"],
            )
        with right:
            initial_cost = st.number_input(
                "Initial cost ($)",
                min_value=0.0,
                value=float(references["initial_cost"] or 0),
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
        exclude_job = st.text_input(
            "Current filing number (optional; excluded from comparables)"
        )
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
                "general_construction_work_type_": "YES" if general_work else "NO",
                "plumbing_work_type": "YES" if plumbing_work else "NO",
                "mechanical_systems_work_type_": "YES" if mechanical_work else "NO",
                "structural_work_type_": "YES" if structural_work else "NO",
            }
        )
        try:
            st.session_state.result = api_post(
                "/api/v1/assessments",
                {
                    "workspace_id": workspace_id,
                    "features": features,
                    "exclude_job": exclude_job or None,
                },
            )
            st.rerun()
        except Exception as error:
            st.error(f"Assessment failed: {error}")

result = st.session_state.get("result")
if result:
    render_result(result)
    if result.get("status") == "awaiting_human_review":
        st.info(
            "Approval freezes the displayed inputs, evidence, checklist, and reviewer note "
            "into a downloadable PDF. Rejection creates no PDF."
        )
        note = st.text_area("Reviewer note (included in the PDF)")
        approve, reject = st.columns(2)
        decision = None
        if approve.button("Approve & generate PDF", type="primary", use_container_width=True):
            decision = "approve"
        if reject.button("Reject - no PDF", use_container_width=True):
            decision = "reject"
        if decision:
            try:
                st.session_state.result = api_post(
                    f"/api/v1/assessments/{result['thread_id']}/decision",
                    {
                        "workspace_id": workspace_id,
                        "decision": decision,
                        "note": note,
                    },
                )
                st.rerun()
            except Exception as error:
                st.error(f"Decision failed: {error}")
    else:
        status = result["status"]
        if status == "approved_report_ready":
            st.success("Approved. The reviewed PDF report is ready.")
            try:
                report_bytes = api_get_bytes(
                    f"/api/v1/assessments/{result['thread_id']}/report",
                    {"workspace_id": workspace_id},
                )
                st.download_button(
                    "Download approved PDF",
                    data=report_bytes,
                    file_name=result["report_file"]["filename"],
                    mime="application/pdf",
                    type="primary",
                )
            except Exception as error:
                st.error(f"PDF download failed: {error}")
        elif status == "approved_report_failed":
            detail = result.get("report_file", {}).get("error", "Unknown error")
            st.error(f"Approved, but the PDF could not be generated: {detail}")
        elif status == "rejected":
            st.warning("Rejected by the reviewer. No PDF was generated.")
        else:
            st.warning(f"Workflow status: {status.replace('_', ' ')}")
        if result.get("review", {}).get("note"):
            st.write(f"**Reviewer note:** {result['review']['note']}")
