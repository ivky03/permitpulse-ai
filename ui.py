"""Streamlit interface for durable PermitPulse assessments."""

from __future__ import annotations

import base64
import json
import os
from datetime import date, timedelta
from typing import Any
from uuid import uuid4

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
API_URL = os.getenv("PERMITPULSE_API_URL", "http://localhost:8000").rstrip("/")
TIMEOUT_SECONDS = 30


def api_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(f"{API_URL}{path}", params=params, timeout=TIMEOUT_SECONDS)
    if not response.ok:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise RuntimeError(str(detail))
    return response.json()


def api_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(f"{API_URL}{path}", json=payload, timeout=TIMEOUT_SECONDS)
    if not response.ok:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise RuntimeError(str(detail))
    return response.json()


def api_get_bytes(path: str, params: dict[str, Any] | None = None) -> bytes:
    response = requests.get(f"{API_URL}{path}", params=params, timeout=TIMEOUT_SECONDS)
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


def select_with_default(label: str, values: list[Any], default: Any, key: str) -> Any:
    options = [value for value in values if value not in (None, "")]
    if default not in options and default not in (None, ""):
        options.insert(0, default)
    index = options.index(default) if default in options else 0
    return st.selectbox(label, options, index=index, key=key)


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
        st.dataframe(evidence["comparables"], use_container_width=True, hide_index=True)
    st.caption(evidence["coverage_note"])

    st.subheader("Proposed checklist")
    plan = result["proposed_plan"]
    st.write(plan["summary"])
    trace = plan.get("agent_trace", {})
    if trace.get("mode") == "gemini_tool_calling":
        st.success(
            "Gemini planning agent used: " + ", ".join(trace.get("tool_calls", []))
        )
    elif plan.get("planner_warning"):
        st.warning(plan["planner_warning"])
    else:
        st.caption(
            "Deterministic planning fallback used; configure Gemini for agent mode."
        )
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
    "Assess one permit from entered fields or an uploaded document, let a grounded "
    "Gemini agent use ML and evidence tools, then approve or reject the report."
)

try:
    metadata = api_get("/api/v1/metadata")
except Exception as error:
    st.error(f"The API is unavailable at {API_URL}: {error}")
    st.stop()

with st.sidebar:
    st.header("Demo workspace")
    if metadata.get("public_demo"):
        if "workspace_id" not in st.session_state:
            st.session_state.workspace_id = f"demo-{uuid4().hex}"
        st.caption(f"Anonymous session: `{st.session_state.workspace_id[:18]}...`")
    else:
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
    st.caption(
        "Demo separation only - not authentication. Do not enter sensitive data."
    )

workspace_id = st.session_state.get("workspace_id")
if not workspace_id:
    st.info("Enter a demo workspace ID in the sidebar to begin or reopen history.")
    st.stop()

try:
    history_items = api_get("/api/v1/history", {"workspace_id": workspace_id})["items"]
except Exception as error:
    st.error(f"History could not be loaded: {error}")
    history_items = []

with st.sidebar:
    st.divider()
    app_view = st.radio(
        "View",
        ["Assess one permit", "Portfolio"],
        key="app_view",
    )

with st.sidebar:
    st.divider()
    st.subheader("Assessment history")
    if st.button("＋ New assessment", use_container_width=True):
        st.session_state.pop("result", None)
        st.session_state.pop("document_intake", None)
        st.session_state.app_view = "Assess one permit"
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
                st.session_state.app_view = "Assess one permit"
                st.rerun()
            except Exception as error:
                st.error(error)

references = metadata["reference_values"]
categories = metadata["categories"]
if app_view == "Portfolio":
    st.subheader("Permit portfolio")
    st.caption(
        "Prioritize filings by model risk and needed-by date. Portfolio ordering is "
        "planning support, not a permit or compliance decision."
    )
    try:
        portfolio = api_get("/api/v1/portfolio", {"workspace_id": workspace_id})
    except Exception as error:
        st.error(f"Portfolio could not be loaded: {error}")
        portfolio = {"summary": {}, "items": []}

    items = portfolio.get("items", [])
    if not items:
        st.info("This workspace has no assessments yet.")
        if st.button("Load six demo projects", type="primary"):
            try:
                api_post(f"/api/v1/portfolio/demo?workspace_id={workspace_id}", {})
                st.rerun()
            except Exception as error:
                st.error(f"Demo portfolio failed: {error}")
    else:
        summary = portfolio["summary"]
        first, second, third = st.columns(3)
        first.metric("Portfolio filings", summary["total"])
        second.metric("High risk", summary["high_risk"])
        third.metric("Unassigned", summary["unassigned"])

        distribution = pd.DataFrame(
            {
                "Risk level": ["High", "Moderate", "Low"],
                "Filings": [
                    summary["high_risk"],
                    summary["moderate_risk"],
                    summary["low_risk"],
                ],
            }
        ).set_index("Risk level")
        st.bar_chart(distribution, horizontal=True, height=220)

        risk_filter = st.selectbox("Risk filter", ["All", "High", "Moderate", "Low"])
        visible = [
            item
            for item in items
            if risk_filter == "All" or item.get("risk_level") == risk_filter.lower()
        ]
        portfolio_frame = pd.DataFrame(
            [
                {
                    "Project": item.get("project_name"),
                    "Needed by": item.get("permit_needed_by"),
                    "Risk": str(item.get("risk_level") or "unknown").title(),
                    "Delay probability": item.get("delay_probability"),
                    "Owner": item.get("mitigation_owner"),
                    "Workflow": item.get("status", "").replace("_", " ").title(),
                }
                for item in visible
            ]
        )
        st.dataframe(
            portfolio_frame,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Delay probability": st.column_config.ProgressColumn(
                    format="percent", min_value=0.0, max_value=1.0
                )
            },
        )
        selected_project = st.selectbox(
            "Open an assessment",
            visible,
            format_func=lambda item: (
                f"{item.get('project_name')} - "
                f"{float(item.get('delay_probability') or 0):.0%}"
            ),
        )
        if st.button("Review selected assessment", type="primary"):
            try:
                st.session_state.result = api_get(
                    f"/api/v1/history/{selected_project['thread_id']}",
                    {"workspace_id": workspace_id},
                )
                st.session_state.app_view = "Assess one permit"
                st.rerun()
            except Exception as error:
                st.error(error)

    st.divider()
    st.subheader("Import a small portfolio")
    template = pd.DataFrame(
        [
            {
                "project_name": "Example project",
                "permit_needed_by": (date.today() + timedelta(days=45)).isoformat(),
                "mitigation_owner": "Project Manager",
                "borough": references["borough"],
                "job_type": references["job_type"],
                "filing_review_type": references["filing_review_type"],
                "building_type": references["building_type"],
                "initial_cost": references["initial_cost"],
                "total_construction_floor_area": references[
                    "total_construction_floor_area"
                ],
            }
        ]
    )
    st.download_button(
        "Download CSV template",
        template.to_csv(index=False),
        file_name="permitpulse-portfolio-template.csv",
        mime="text/csv",
    )
    upload = st.file_uploader(
        "Upload portfolio CSV",
        type=["csv"],
        help=f"Maximum {metadata['max_portfolio_items']} filings per upload.",
    )
    if upload is not None and st.button("Assess uploaded portfolio"):
        try:
            frame = pd.read_csv(upload)
            required = {
                "project_name",
                "permit_needed_by",
                "borough",
                "job_type",
                "filing_review_type",
                "building_type",
                "initial_cost",
                "total_construction_floor_area",
            }
            missing = sorted(required - set(frame.columns))
            if missing:
                raise ValueError(f"Missing CSV columns: {missing}")
            if len(frame) > metadata["max_portfolio_items"]:
                raise ValueError("The CSV contains too many rows for one upload.")
            batch = []
            for row in frame.to_dict("records"):
                features = dict(references)
                features.update(
                    {
                        column: row[column]
                        for column in required
                        if column not in {"project_name", "permit_needed_by"}
                    }
                )
                batch.append(
                    {
                        "features": features,
                        "project_context": {
                            "project_name": row["project_name"],
                            "permit_needed_by": row["permit_needed_by"],
                            "mitigation_owner": row.get(
                                "mitigation_owner", "Unassigned"
                            ),
                            "review_status": "new",
                        },
                    }
                )
            api_post(
                "/api/v1/portfolio/assess",
                {"workspace_id": workspace_id, "items": batch},
            )
            st.rerun()
        except Exception as error:
            st.error(f"Portfolio import failed: {error}")
    st.stop()

if "result" not in st.session_state:
    st.subheader("Assess one permit")
    entry_mode = st.radio(
        "How do you want to provide the permit?",
        ["Enter fields", "Upload PDF or image"],
        horizontal=True,
    )
    intake = st.session_state.get("document_intake")
    if entry_mode == "Upload PDF or image":
        st.caption(
            "Gemini extracts candidate fields. You must inspect and confirm them "
            "before "
            "the ML model runs. Document instructions are treated as untrusted data."
        )
        st.warning(
            "The uploaded file is sent to the configured Google Gemini API for "
            "extraction and is not stored by PermitPulse. Use demo documents only; "
            "do not upload confidential or personal information."
        )
        if not metadata.get("gemini_configured"):
            st.info("Add GOOGLE_API_KEY to the API's local .env and restart it first.")
        uploaded_document = st.file_uploader(
            "Permit application or project brief",
            type=["pdf", "png", "jpg", "jpeg"],
            help=f"PDF, PNG, or JPEG; maximum {metadata['max_document_mb']} MB.",
        )
        if uploaded_document is not None and st.button(
            "Extract fields with Gemini",
            type="primary",
            disabled=not metadata.get("gemini_configured"),
        ):
            try:
                content = uploaded_document.getvalue()
                if len(content) > metadata["max_document_mb"] * 1024 * 1024:
                    raise ValueError("The document exceeds the local demo size limit.")
                mime = uploaded_document.type or {
                    ".pdf": "application/pdf",
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                }.get(os.path.splitext(uploaded_document.name)[1].lower())
                st.session_state.document_intake = api_post(
                    "/api/v1/agent/document-intake",
                    {
                        "filename": uploaded_document.name,
                        "mime_type": mime,
                        "content_base64": base64.b64encode(content).decode("ascii"),
                    },
                )
                for key in (
                    "one-borough",
                    "one-job-type",
                    "one-review-type",
                    "one-building-type",
                ):
                    st.session_state.pop(key, None)
                st.rerun()
            except Exception as error:
                st.error(f"Document extraction failed: {error}")
        intake = st.session_state.get("document_intake")
        if intake:
            st.success(
                f"Extracted with {intake['generated_by']}. Confirm every field below."
            )
            st.dataframe(
                pd.DataFrame(intake["field_evidence"]),
                use_container_width=True,
                hide_index=True,
            )
            if intake["missing_required_fields"]:
                st.warning(
                    "Not found in the document: "
                    + ", ".join(intake["missing_required_fields"])
                    + ". Select the correct values below before continuing."
                )
            for warning in intake.get("warnings", []):
                st.warning(warning)

    defaults = intake if entry_mode == "Upload PDF or image" and intake else None
    default_features = defaults["features"] if defaults else references
    default_project = defaults["project_context"] if defaults else {}
    with st.form("assessment"):
        st.caption(
            "Fields not shown use training reference values. Uploaded values remain "
            "editable and are never sent to the ML model before your confirmation."
        )
        left, right = st.columns(2)
        with left:
            project_name = st.text_input(
                "Project name",
                value=default_project.get("project_name", "Demo project"),
            )
            default_needed = default_project.get("permit_needed_by")
            try:
                default_needed_date = date.fromisoformat(default_needed)
            except (TypeError, ValueError):
                default_needed_date = date.today() + timedelta(days=45)
            needed_by = st.date_input("Permit needed by", value=default_needed_date)
            borough = select_with_default(
                "Borough",
                categories["borough"],
                default_features["borough"],
                "one-borough",
            )
            job_type = select_with_default(
                "Job type",
                categories["job_type"],
                default_features["job_type"],
                "one-job-type",
            )
            review = select_with_default(
                "Review type",
                categories["filing_review_type"],
                default_features["filing_review_type"],
                "one-review-type",
            )
            building = select_with_default(
                "Building type",
                categories["building_type"],
                default_features["building_type"],
                "one-building-type",
            )
        with right:
            mitigation_owner = st.text_input(
                "Mitigation owner",
                value=default_project.get("mitigation_owner", "Project Manager"),
            )
            initial_cost = st.number_input(
                "Initial cost ($)",
                min_value=0.0,
                value=float(default_features["initial_cost"] or 0),
            )
            floor_area = st.number_input(
                "Construction floor area",
                min_value=0.0,
                value=float(default_features["total_construction_floor_area"] or 0),
            )
            general_work = st.checkbox(
                "General construction work",
                value=default_features.get("general_construction_work_type_") == "YES",
            )
            plumbing_work = st.checkbox(
                "Plumbing work",
                value=default_features.get("plumbing_work_type") == "YES",
            )
            mechanical_work = st.checkbox(
                "Mechanical systems work",
                value=default_features.get("mechanical_systems_work_type_") == "YES",
            )
            structural_work = st.checkbox(
                "Structural work",
                value=default_features.get("structural_work_type_") == "YES",
            )
        exclude_job = st.text_input(
            "Current filing number (optional; excluded from comparables)"
        )
        confirmed = st.checkbox(
            "I reviewed these inputs and confirm they are correct",
            value=entry_mode == "Enter fields",
        )
        submitted = st.form_submit_button(
            "Analyze with Permit Planning Agent", type="primary"
        )

    if submitted:
        if not confirmed:
            st.error("Confirm the displayed fields before running the assessment.")
            st.stop()
        features = dict(default_features)
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
                    "project_context": {
                        "project_name": project_name,
                        "permit_needed_by": needed_by.isoformat(),
                        "mitigation_owner": mitigation_owner,
                        "review_status": "new",
                    },
                },
            )
            st.rerun()
        except Exception as error:
            st.error(f"Assessment failed: {error}")

result = st.session_state.get("result")
if result:
    render_result(result)
    st.subheader("Ask the Permit Planning Agent")
    if metadata.get("gemini_configured"):
        try:
            chat_messages = api_get(
                f"/api/v1/assessments/{result['thread_id']}/agent-chat",
                {"workspace_id": workspace_id},
            )["messages"]
        except Exception as error:
            chat_messages = []
            st.error(f"Agent conversation could not be loaded: {error}")
        if not chat_messages:
            st.caption(
                "Ask follow-up questions about this assessment. The conversation is "
                "saved with this workspace and assessment."
            )
        for message in chat_messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
                if message.get("tool_calls"):
                    st.caption("Tools used: " + ", ".join(message["tool_calls"]))
        with st.form(f"agent-chat-{result['thread_id']}", clear_on_submit=True):
            question = st.text_input(
                "Continue the conversation",
                placeholder="Can I do something to lower the risk?",
            )
            ask_agent = st.form_submit_button("Send", type="primary")
        if ask_agent:
            try:
                api_post(
                    f"/api/v1/assessments/{result['thread_id']}/agent-question",
                    {"workspace_id": workspace_id, "question": question},
                )
                st.rerun()
            except Exception as error:
                st.error(f"Agent question failed: {error}")
    else:
        st.info(
            "Configure GOOGLE_API_KEY and restart the API to enable Gemini "
            "tool-calling "
            "briefings, document extraction, and grounded follow-up questions."
        )
    if result.get("status") == "awaiting_human_review":
        st.info(
            "Approval freezes the displayed inputs, evidence, checklist, and reviewer "
            "note "
            "into a downloadable PDF. Rejection creates no PDF."
        )
        note = st.text_area("Reviewer note (included in the PDF)")
        approve, reject = st.columns(2)
        decision = None
        if approve.button(
            "Approve & generate PDF", type="primary", use_container_width=True
        ):
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
                procore_draft = api_get(
                    f"/api/v1/assessments/{result['thread_id']}/procore-draft",
                    {"workspace_id": workspace_id},
                )
                st.download_button(
                    "Download integration-ready risk draft",
                    data=json.dumps(procore_draft, indent=2) + "\n",
                    file_name=(
                        f"permitpulse-integration-draft-{result['thread_id'][:12]}.json"
                    ),
                    mime="application/json",
                )
                st.caption(
                    "Draft integration payload only. PermitPulse performs no external "
                    "write."
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
