"""FastAPI boundary for permit assessments and human review."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections import defaultdict, deque
import os
from threading import Lock
from time import monotonic
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

load_dotenv()

from src.agent.workflow import PermitWorkflow
from src.data.build_dataset import MODEL_FEATURES, NUMERIC_FEATURES
from src.services.portfolio import (
    MAX_PORTFOLIO_ITEMS,
    demo_portfolio,
    normalize_project_context,
    portfolio_summary,
    rank_portfolio,
)
from src.services.persistence import HistoryStore, normalize_workspace_id
from src.services.procore_adapter import DemoProcoreAdapter


PUBLIC_DEMO = os.getenv("PERMITPULSE_PUBLIC_DEMO", "false").lower() == "true"
PUBLIC_RATE_LIMIT = int(os.getenv("PERMITPULSE_RATE_LIMIT_PER_MINUTE", "30"))


class MinuteRateLimiter:
    """Small process-local guardrail for the portfolio demo."""

    def __init__(self, limit: int) -> None:
        self.limit = max(1, limit)
        self.requests: dict[str, deque[float]] = defaultdict(deque)
        self.lock = Lock()

    def allow(self, identity: str) -> bool:
        now = monotonic()
        with self.lock:
            recent = self.requests[identity]
            while recent and now - recent[0] >= 60:
                recent.popleft()
            if len(recent) >= self.limit:
                return False
            recent.append(now)
            return True


class ProjectContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_name: str = "Unnamed project"
    permit_needed_by: str | None = None
    mitigation_owner: str = "Unassigned"
    review_status: str = "new"


class AssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    features: dict[str, Any] = Field(min_length=1)
    workspace_id: str
    exclude_job: str | None = None
    project_context: ProjectContextRequest | None = None


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str
    note: str = ""
    workspace_id: str


class PortfolioItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    features: dict[str, Any] = Field(min_length=1)
    exclude_job: str | None = None
    project_context: ProjectContextRequest


class PortfolioAssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    items: list[PortfolioItemRequest] = Field(
        min_length=1, max_length=MAX_PORTFOLIO_ITEMS
    )


def create_app(
    workflow: PermitWorkflow | None = None,
    history_store: HistoryStore | None = None,
) -> FastAPI:
    runtime: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        runtime["workflow"] = workflow or PermitWorkflow()
        runtime["history"] = history_store or HistoryStore()
        yield
        if workflow is None:
            runtime["workflow"].close()

    app = FastAPI(
        title="PermitPulse AI API",
        version="1.0.0",
        description="Evidence-backed permit-delay planning with human approval.",
        lifespan=lifespan,
    )
    limiter = MinuteRateLimiter(PUBLIC_RATE_LIMIT)

    @app.middleware("http")
    async def public_demo_rate_limit(request, call_next):
        if (
            PUBLIC_DEMO
            and request.method == "POST"
            and request.url.path.startswith("/api/v1/")
        ):
            identity = request.client.host if request.client else "unknown"
            if not limiter.allow(identity):
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": (
                            "Public demo rate limit reached. Wait one minute and retry."
                        )
                    },
                    headers={"Retry-After": "60"},
                )
        return await call_next(request)

    def current_workflow() -> PermitWorkflow:
        if "workflow" not in runtime:
            raise HTTPException(status_code=503, detail="Runtime is not ready.")
        return runtime["workflow"]

    def current_history() -> HistoryStore:
        if "history" not in runtime:
            raise HTTPException(status_code=503, detail="History store is not ready.")
        return runtime["history"]

    def create_one(
        workspace_id: str,
        features: dict[str, Any],
        exclude_job: str | None,
        project_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        context = normalize_project_context(project_context)
        result = current_workflow().start(
            features,
            exclude_job=exclude_job,
            project_context=context,
        )
        current_history().create(workspace_id, features, result)
        return result

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/metadata")
    def metadata() -> dict[str, Any]:
        active = current_workflow()
        artifact = active.risk_service.artifact
        profile = artifact["input_profile"]
        return {
            "features": list(MODEL_FEATURES),
            "numeric_features": sorted(NUMERIC_FEATURES),
            "reference_values": profile["reference_values"],
            "categories": profile["categories"],
            "model_name": artifact["model_name"],
            "training_period": artifact["training_period"],
            "target": "first permit not issued within 30 days",
            "workspace_notice": (
                "Workspace IDs separate demo history; they are not authentication."
            ),
            "public_demo": PUBLIC_DEMO,
            "max_portfolio_items": MAX_PORTFOLIO_ITEMS,
        }

    @app.post("/api/v1/assessments")
    def create_assessment(payload: AssessmentRequest) -> dict[str, Any]:
        try:
            workspace_id = normalize_workspace_id(payload.workspace_id)
            context = (
                payload.project_context.model_dump()
                if payload.project_context is not None
                else None
            )
            return create_one(
                workspace_id, payload.features, payload.exclude_job, context
            )
        except (ValueError, FileNotFoundError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/v1/assessments/{thread_id}/decision")
    def decide(thread_id: str, payload: DecisionRequest) -> dict[str, Any]:
        if payload.decision not in {"approve", "reject"}:
            raise HTTPException(status_code=422, detail="decision must be approve or reject")
        try:
            workspace_id = normalize_workspace_id(payload.workspace_id)
            current_history().get(workspace_id, thread_id)
            result = current_workflow().resume(
                thread_id,
                payload.decision,
                payload.note,
            )
            current_history().update(workspace_id, result)
            return result
        except (ValueError, KeyError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/v1/history")
    def list_history(workspace_id: str, limit: int = 30) -> dict[str, Any]:
        try:
            return {
                "workspace_id": normalize_workspace_id(workspace_id),
                "items": current_history().list(workspace_id, limit),
            }
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/v1/history/{thread_id}")
    def get_history(thread_id: str, workspace_id: str) -> dict[str, Any]:
        try:
            return current_history().get(workspace_id, thread_id)
        except (ValueError, KeyError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/api/v1/portfolio")
    def get_portfolio(workspace_id: str) -> dict[str, Any]:
        try:
            workspace_id = normalize_workspace_id(workspace_id)
            items = rank_portfolio(current_history().list(workspace_id, 100))
            return {
                "workspace_id": workspace_id,
                "summary": portfolio_summary(items),
                "items": items,
            }
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/v1/portfolio/assess")
    def assess_portfolio(payload: PortfolioAssessmentRequest) -> dict[str, Any]:
        try:
            workspace_id = normalize_workspace_id(payload.workspace_id)
            results = [
                create_one(
                    workspace_id,
                    item.features,
                    item.exclude_job,
                    item.project_context.model_dump(),
                )
                for item in payload.items
            ]
            items = rank_portfolio(current_history().list(workspace_id, 100))
            return {
                "workspace_id": workspace_id,
                "created": len(results),
                "summary": portfolio_summary(items),
                "items": items,
            }
        except (ValueError, FileNotFoundError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/v1/portfolio/demo")
    def load_demo_portfolio(workspace_id: str) -> dict[str, Any]:
        try:
            workspace_id = normalize_workspace_id(workspace_id)
            references = current_workflow().risk_service.artifact["input_profile"][
                "reference_values"
            ]
            demo_items = demo_portfolio(references)
            for item in demo_items:
                create_one(
                    workspace_id,
                    item["features"],
                    None,
                    item["project_context"],
                )
            items = rank_portfolio(current_history().list(workspace_id, 100))
            return {
                "workspace_id": workspace_id,
                "created": len(demo_items),
                "summary": portfolio_summary(items),
                "items": items,
            }
        except (ValueError, FileNotFoundError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/v1/assessments/{thread_id}/report")
    def download_report(thread_id: str, workspace_id: str) -> FileResponse:
        try:
            result = current_history().get(workspace_id, thread_id)
        except (ValueError, KeyError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        report = result.get("report_file", {})
        if result.get("status") != "approved_report_ready" or report.get("status") != "ready":
            raise HTTPException(status_code=404, detail="An approved PDF report is not available.")
        path = current_workflow().report_service.path_for(thread_id)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="The PDF report file is missing.")
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=report["filename"],
        )

    @app.get("/api/v1/assessments/{thread_id}/procore-draft")
    def get_procore_draft(thread_id: str, workspace_id: str) -> dict[str, Any]:
        try:
            record = current_history().get(workspace_id, thread_id)
            return DemoProcoreAdapter().build_risk_draft(record)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    return app


app = create_app()
