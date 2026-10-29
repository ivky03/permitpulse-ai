"""Standalone Streamlit quality-audit page for the existing PermitPulse application.

Run via: streamlit run ui.py  -> Pages -> Agent Quality Audit
The existing FastAPI server must be running. No API key is persisted.
"""
from __future__ import annotations

import json
import os

import requests
import streamlit as st

from src.agent.quality_audit import (
    QUESTIONS, apply_human_review, collect_agent_answer,
    export_audit, run_judge, summarize, validate_import,
)

st.set_page_config(page_title="PermitPulse Agent Quality Audit", page_icon="🧪", layout="wide")
st.title("Agent Quality Audit")
st.caption(
    "Generate real PermitPulse Gemini answers, review their factual accuracy, then "
    "calibrate a separate LLM judge. No invented answers are treated as evaluation results."
)
st.warning(
    "Use synthetic/demo permit assessments only. This app sends assessment evidence "
    "to Gemini and, if enabled, Langfuse. Never enter real applicant information."
)

if "quality_cases" not in st.session_state:
    st.session_state.quality_cases = []
if "quality_assessment" not in st.session_state:
    st.session_state.quality_assessment = None

with st.sidebar:
    st.header("Runtime credentials")
    api_key = st.text_input("Gemini API key", type="password",
        help="Held only in this Streamlit session; never saved to Git or exported.")
    model = st.text_input("Gemini model", "gemini-2.5-flash")
    trace_enabled = st.checkbox("Enable Langfuse tracing (optional)")
    langfuse = None
    if trace_enabled:
        public_key = st.text_input("Langfuse public key", type="password")
        secret_key = st.text_input("Langfuse secret key", type="password")
        host = st.text_input("Langfuse host", "https://cloud.langfuse.com")
        st.caption("Trace inputs include synthetic assessment facts and candidate answers.")
        if public_key and secret_key and host:
            try:
                from langfuse import Langfuse
                langfuse = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
            except (ImportError, ValueError) as error:
                st.error(f"Langfuse unavailable: {type(error).__name__}.")
    if api_key:
        st.success("Runtime Gemini key entered. It will not be included in exports.")
    st.caption("Run only on a trusted, access-controlled HTTPS deployment.")

st.subheader("1 · Load an existing permit assessment")
st.write(
    "Use a previously created PermitPulse assessment (including its real ML risk "
    "and historical retrieval evidence). You can copy the thread ID from an existing result."
)
api_url = st.text_input("PermitPulse API URL",
    value=os.getenv("PERMITPULSE_API_URL", "http://localhost:8000"))
workspace = st.text_input("Demo workspace ID", value=st.session_state.get("workspace_id", ""))
thread_id = st.text_input("Assessment thread ID")
if st.session_state.get("result") and st.button("Use the assessment currently open in PermitPulse"):
    st.session_state.quality_assessment = st.session_state.result["assessment"]
    st.success("Loaded assessment already displayed in this session.")
if workspace and st.button("Find recent assessments"):
    try:
        configured = os.getenv("PERMITPULSE_API_URL", "http://localhost:8000").rstrip("/")
        history = requests.get(
            f"{configured}/api/v1/history",
            params={"workspace_id": workspace, "limit": 20}, timeout=20,
        )
        history.raise_for_status()
        st.session_state.quality_recent = history.json().get("items", [])
    except (requests.RequestException, ValueError) as error:
        st.error(f"Unable to fetch recent assessments: {error}")
recent = st.session_state.get("quality_recent", [])
if recent:
    selected = st.selectbox("Or choose a recent assessment",
        recent, format_func=lambda item: (
            str(item.get("project_name") or item.get("borough") or "Permit")
            + " · " + str(item.get("risk_level") or "unknown")
        ))
    if st.button("Load selected assessment"):
        try:
            configured = os.getenv("PERMITPULSE_API_URL", "http://localhost:8000").rstrip("/")
            response = requests.get(
                f"{configured}/api/v1/history/{selected['thread_id']}",
                params={"workspace_id": workspace}, timeout=20,
            )
            response.raise_for_status()
            st.session_state.quality_assessment = response.json()["assessment"]
            st.success("Loaded saved assessment.")
        except (requests.RequestException, KeyError, ValueError) as error:
            st.error(f"Unable to load: {error}")
if st.button("Load assessment by thread ID", disabled=not bool(workspace and thread_id)):
    try:
        # Only permit the configured API host: never forward credentials to this endpoint.
        configured = os.getenv("PERMITPULSE_API_URL", "http://localhost:8000").rstrip("/")
        if api_url.rstrip("/") != configured:
            raise ValueError("API URL must match the configured PermitPulse backend.")
        response = requests.get(
            f"{configured}/api/v1/history/{thread_id}",
            params={"workspace_id": workspace},
            timeout=20,
        )
        response.raise_for_status()
        assessment = response.json()["assessment"]
        st.session_state.quality_assessment = assessment
        st.success("Loaded a saved PermitPulse assessment.")
    except (requests.RequestException, ValueError, KeyError) as error:
        st.error(f"Could not load the assessment: {type(error).__name__}: {error}")

if st.session_state.quality_assessment:
    assessment = st.session_state.quality_assessment
    prediction = assessment.get("prediction", {})
    st.info(
        f"Saved assessment loaded. Risk: {prediction.get('risk_level', 'n/a')}; "
        f"delay probability: {prediction.get('delay_probability', 'n/a')}"
    )
    question = st.selectbox("Question to ask the actual agent", QUESTIONS + ["Custom"])
    if question == "Custom":
        question = st.text_input("Custom question", max_chars=500)
    if st.button("Generate agent response", disabled=not (api_key and question)):
        try:
            with st.spinner("Running PermitPulse's existing Gemini evidence agent..."):
                case = collect_agent_answer(
                    assessment, question, api_key, model=model,
                    langfuse=langfuse
                )
                st.session_state.quality_cases.append(case)
                if langfuse:
                    langfuse.flush()
            st.success("Captured a real Gemini agent answer. Review it below.")
        except Exception as error:
            st.error(f"Agent request failed: {type(error).__name__}: {error}")

st.divider()
st.subheader("2 · Review the observed responses")
uploaded = st.file_uploader("Import previous Agent Quality Audit JSON", type=["json"])
if uploaded is not None and st.button("Import reviewed cases"):
    try:
        obj = json.loads(uploaded.getvalue())
        st.session_state.quality_cases = validate_import(obj)
        st.success("Audit cases imported. Stored judge verdicts are cleared; rerun to verify.")
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        st.error(f"Invalid audit file: {error}")

for index, case in enumerate(st.session_state.quality_cases):
    with st.expander(
        f"{index + 1}. {case['question'][:75]} — {case.get('reference_label', 'UNREVIEWED')}",
        expanded=case.get("reference_label") == "UNREVIEWED"
    ):
        st.write("**Actual Gemini response**")
        st.write(case["candidate_answer"])
        st.write("**Agent tool calls:**", case.get("tool_calls", []))
        st.json(case["verified_evidence"], expanded=False)
        label = st.selectbox(
            "Your reference judgment", ["UNREVIEWED", "PASS", "FAIL"],
            index=["UNREVIEWED", "PASS", "FAIL"].index(case.get("reference_label", "UNREVIEWED")),
            key=f"label-{case['id']}"
        )
        rationale = st.text_area(
            "Evidence-based reason for your judgment",
            value=case.get("reviewer_note", ""), key=f"reason-{case['id']}"
        )
        if st.button("Save human review", key=f"save-{case['id']}"):
            try:
                st.session_state.quality_cases[index] = apply_human_review(case, label, rationale)
                st.success("Review saved; earlier judge result cleared.")
                st.rerun()
            except ValueError as error:
                st.error(str(error))
        verdict = case.get("judge")
        if verdict:
            st.write("**Independent LLM judge:**", verdict["verdict"])
            st.caption(verdict["reason"])
            if verdict["verdict"] != case["reference_label"]:
                st.error("Judge disagrees with your reference judgment.")

st.divider()
st.subheader("3 · Independently judge the reviewed cases")
if st.button("Run LLM judge", disabled=not api_key):
    reviewed = [c for c in st.session_state.quality_cases if c.get("reference_label") in ("PASS", "FAIL")]
    if not reviewed:
        st.warning("First review at least one real agent answer.")
    else:
        for case in reviewed:
            try:
                case["judge"] = run_judge(case, api_key, model=model, langfuse=langfuse)
                st.write(f"{case['id']}: {case['judge']['verdict']}")
            except Exception as error:
                case["judge"] = None
                st.error(f"Judge failed for {case['id']}: {type(error).__name__}: {error}")
        if langfuse:
            langfuse.flush()

summary = summarize(st.session_state.quality_cases)
a, b, c = st.columns(3)
a.metric("Observed agent responses", summary["captured"])
b.metric("Manually reviewed", summary["reviewed"])
c.metric("Real judge verdicts", summary["judged"])
if summary["agreement"] is not None:
    st.metric("Judge–reviewer agreement (small sample)", f"{summary['agreement']:.1%}")
    st.write("Confusion matrix:", summary["confusion_matrix"])
    st.write("False-accept rate:", summary["false_accept_rate"])
st.caption(summary["warning"])
st.download_button(
    "Download observed cases and labels (JSON)",
    data=json.dumps(export_audit(st.session_state.quality_cases), indent=2, default=str),
    file_name="permitpulse_agent_quality_audit.json",
    mime="application/json",
)
st.caption(
    "Judge prompts never receive human labels. Imported judge verdicts are discarded. "
    "These metrics are exploratory, not certified deployment safety results."
)
