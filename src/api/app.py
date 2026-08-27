"""FastAPI boundary for permit assessments and human review."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

load_dotenv()

from src.agent.workflow import PermitWorkflow
from src.data.build_dataset import MODEL_FEATURES, NUMERIC_FEATURES
from src.services.persistence import HistoryStore, normalize_workspace_id


class AssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    features: dict[str, Any] = Field(min_length=1)
    workspace_id: str
    exclude_job: str | None = None


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str
    note: str = ""
    workspace_id: str


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

    def current_workflow() -> PermitWorkflow:
        if "workflow" not in runtime:
            raise HTTPException(status_code=503, detail="Runtime is not ready.")
        return runtime["workflow"]

    def current_history() -> HistoryStore:
        if "history" not in runtime:
            raise HTTPException(status_code=503, detail="History store is not ready.")
        return runtime["history"]

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
        }

    @app.post("/api/v1/assessments")
    def create_assessment(payload: AssessmentRequest) -> dict[str, Any]:
        try:
            workspace_id = normalize_workspace_id(payload.workspace_id)
            result = current_workflow().start(payload.features, payload.exclude_job)
            current_history().create(workspace_id, payload.features, result)
            return result
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

    return app


app = create_app()
