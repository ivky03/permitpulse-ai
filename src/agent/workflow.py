"""LangGraph workflow that pauses for a human decision."""

from __future__ import annotations

import json
from typing import Any, TypedDict
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from src.services.risk_service import RiskService

from .planner import EvidencePlanner


class PermitState(TypedDict, total=False):
    request: dict[str, Any]
    exclude_job: str | None
    assessment: dict[str, Any]
    proposed_plan: dict[str, Any]
    review: dict[str, str]
    status: str


class PermitWorkflow:
    def __init__(
        self,
        risk_service: Any | None = None,
        planner: Any | None = None,
        checkpointer: Any | None = None,
    ) -> None:
        self.risk_service = risk_service or RiskService()
        self.planner = planner or EvidencePlanner()
        builder = StateGraph(PermitState)
        builder.add_node("assess", self._assess)
        builder.add_node("draft_plan", self._draft_plan)
        builder.add_node("human_review", self._human_review)
        builder.add_node("finalize", self._finalize)
        builder.add_edge(START, "assess")
        builder.add_edge("assess", "draft_plan")
        builder.add_edge("draft_plan", "human_review")
        builder.add_edge("human_review", "finalize")
        builder.add_edge("finalize", END)
        self.graph = builder.compile(checkpointer=checkpointer or InMemorySaver())

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
                "question": "Approve this planning checklist?",
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
    def _finalize(state: PermitState) -> PermitState:
        return {
            "status": (
                "approved_for_human_follow_up"
                if state["review"]["decision"] == "approve"
                else "rejected"
            )
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
                "review",
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
    ) -> dict[str, Any]:
        thread_id = thread_id or str(uuid4())
        result = self.graph.invoke(
            {"request": request, "exclude_job": exclude_job},
            config=self._config(thread_id),
        )
        return self._response(thread_id, dict(result))

    def resume(self, thread_id: str, decision: str, note: str = "") -> dict[str, Any]:
        result = self.graph.invoke(
            Command(resume={"decision": decision, "note": note}),
            config=self._config(thread_id),
        )
        return self._response(thread_id, dict(result))
