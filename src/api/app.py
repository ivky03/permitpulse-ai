"""FastAPI boundary for permit assessments and human review."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.agent.workflow import PermitWorkflow
from src.data.build_dataset import MODEL_FEATURES, NUMERIC_FEATURES


class AssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    features: dict[str, Any] = Field(min_length=1)
    exclude_job: str | None = None


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str
    note: str = ""


def create_app(workflow: PermitWorkflow | None = None) -> FastAPI:
    runtime: dict[str, PermitWorkflow] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if workflow is not None:
            runtime["workflow"] = workflow
        else:
            runtime["workflow"] = PermitWorkflow()
        yield

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
        }

    @app.post("/api/v1/assessments")
    def create_assessment(payload: AssessmentRequest) -> dict[str, Any]:
        try:
            return current_workflow().start(payload.features, payload.exclude_job)
        except (ValueError, FileNotFoundError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/v1/assessments/{thread_id}/decision")
    def decide(thread_id: str, payload: DecisionRequest) -> dict[str, Any]:
        if payload.decision not in {"approve", "reject"}:
            raise HTTPException(status_code=422, detail="decision must be approve or reject")
        try:
            return current_workflow().resume(
                thread_id, payload.decision, payload.note
            )
        except (ValueError, KeyError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    return app


app = create_app()
