"""LangGraph workflow that pauses for a human decision."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, TypedDict
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from src.services.pdf_report import PDFReportService
from src.services.persistence import STATE_DATABASE_PATH
from src.services.risk_service import RiskService

from .planner import EvidencePlanner


class PermitState(TypedDict, total=False):
    thread_id: str
    request: dict[str, Any]
    project_context: dict[str, Any]
    exclude_job: str | None
    assessment: dict[str, Any]
    proposed_plan: dict[str, Any]
    review: dict[str, str]
    report_file: dict[str, Any]
    status: str


class PermitWorkflow:
    def __init__(
        self,
        risk_service: Any | None = None,
        planner: Any | None = None,
        checkpointer: Any | None = None,
        report_service: Any | None = None,
        state_database_path: Path = STATE_DATABASE_PATH,
    ) -> None:
        self.risk_service = risk_service or RiskService()
        self.planner = planner or EvidencePlanner()
        self.report_service = report_service or PDFReportService()
        self._checkpoint_connection: sqlite3.Connection | None = None
        if checkpointer is None:
            state_database_path.parent.mkdir(parents=True, exist_ok=True)
            self._checkpoint_connection = sqlite3.connect(
                state_database_path, check_same_thread=False, timeout=30
            )
            self._checkpoint_connection.execute("PRAGMA journal_mode=WAL")
            self._checkpoint_connection.execute("PRAGMA busy_timeout=30000")
            checkpointer = SqliteSaver(self._checkpoint_connection)
            checkpointer.setup()
        builder = StateGraph(PermitState)
        builder.add_node("assess", self._assess)
        builder.add_node("draft_plan", self._draft_plan)
        builder.add_node("human_review", self._human_review)
        builder.add_node("generate_report", self._generate_report)
        builder.add_node("finalize", self._finalize)
        builder.add_edge(START, "assess")
        builder.add_edge("assess", "draft_plan")
        builder.add_edge("draft_plan", "human_review")
        builder.add_conditional_edges(
            "human_review",
            self._review_route,
            {"approve": "generate_report", "reject": "finalize"},
        )
        builder.add_edge("generate_report", "finalize")
        builder.add_edge("finalize", END)
        self.graph = builder.compile(checkpointer=checkpointer)

    def _assess(self, state: PermitState) -> PermitState:
        assessment = self.risk_service.assess(
            state["request"], exclude_job=state.get("exclude_job")
        )
        return {
            # Model and pandas scalars must cross the checkpoint boundary as
            # ordinary JSON values so the workflow can be persisted safely.
            "assessment": json.loads(
                json.dumps(
                    assessment,
                    default=lambda value: (
                        value.item() if hasattr(value, "item") else str(value)
                    ),
                )
            )
        }

    def _draft_plan(self, state: PermitState) -> PermitState:
        return {"proposed_plan": self.planner.create_plan(state["assessment"])}

    @staticmethod
    def _human_review(state: PermitState) -> PermitState:
        decision = interrupt(
            {
                "question": "Approve this assessment and generate its PDF report?",
                "allowed_decisions": ["approve", "reject"],
                "proposed_plan": state["proposed_plan"],
            }
        )
        if not isinstance(decision, dict) or decision.get("decision") not in {
            "approve",
            "reject",
        }:
            raise ValueError("Decision must be 'approve' or 'reject'.")
        return {
            "review": {
                "decision": decision["decision"],
                "note": str(decision.get("note", "")).strip(),
            }
        }

    @staticmethod
    def _review_route(state: PermitState) -> str:
        return state["review"]["decision"]

    def _generate_report(self, state: PermitState) -> PermitState:
        try:
            report = self.report_service.generate_once(
                state["thread_id"],
                state["request"],
                state["assessment"],
                state["proposed_plan"],
                state["review"],
                state.get("project_context"),
            )
        except Exception as error:
            report = {
                "status": "failed",
                "error": f"{type(error).__name__}: {error}",
            }
        return {"report_file": report}

    @staticmethod
    def _finalize(state: PermitState) -> PermitState:
        if state["review"]["decision"] == "reject":
            status = "rejected"
        else:
            status = (
                "approved_report_ready"
                if state.get("report_file", {}).get("status") == "ready"
                else "approved_report_failed"
            )
        return {
            "status": status
        }

    @staticmethod
    def _config(thread_id: str) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": thread_id}}

    @staticmethod
    def _response(thread_id: str, result: dict[str, Any]) -> dict[str, Any]:
        interrupts = result.pop("__interrupt__", ())
        if interrupts:
            result["status"] = "awaiting_human_review"
            result["review_request"] = interrupts[0].value
        public = {
            key: result[key]
            for key in (
                "status",
                "assessment",
                "proposed_plan",
                "project_context",
                "review",
                "report_file",
                "review_request",
            )
            if key in result
        }
        return {"thread_id": thread_id, **public}

    def start(
        self,
        request: dict[str, Any],
        exclude_job: str | None = None,
        thread_id: str | None = None,
        project_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        thread_id = thread_id or str(uuid4())
        result = self.graph.invoke(
            {
                "thread_id": thread_id,
                "request": request,
                "project_context": project_context or {},
                "exclude_job": exclude_job,
            },
            config=self._config(thread_id),
        )
        return self._response(thread_id, dict(result))

    def resume(
        self,
        thread_id: str,
        decision: str,
        note: str = "",
    ) -> dict[str, Any]:
        result = self.graph.invoke(
            Command(
                resume={
                    "decision": decision,
                    "note": note,
                }
            ),
            config=self._config(thread_id),
        )
        return self._response(thread_id, dict(result))

    def close(self) -> None:
        if self._checkpoint_connection is not None:
            self._checkpoint_connection.close()
            self._checkpoint_connection = None
