import tempfile
import unittest
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from src.agent.planner import EvidencePlanner, deterministic_plan
from src.agent.workflow import PermitWorkflow
from src.api.app import create_app
from src.data.build_dataset import MODEL_FEATURES
from src.services.pdf_report import PDFReportService
from src.services.persistence import HistoryStore


class FakeRiskService:
    def __init__(self) -> None:
        references = {feature: None for feature in MODEL_FEATURES}
        references.update(
            {
                "borough": "Queens",
                "job_type": "Alteration",
                "filing_review_type": "Standard Plan Examination",
                "building_type": "Other",
                "initial_cost": 100_000.0,
                "total_construction_floor_area": 1_000.0,
            }
        )
        self.artifact = {
            "model_name": "fake_model",
            "training_period": {"start": "2020-01-01", "end": "2023-12-31"},
            "input_profile": {
                "reference_values": references,
                "categories": {
                    "borough": ["Queens"],
                    "job_type": ["Alteration"],
                    "filing_review_type": ["Standard Plan Examination"],
                    "building_type": ["Other"],
                },
            },
        }

    def assess(self, request, exclude_job=None):
        return {
            "prediction": {
                "delay_probability": np.float64(0.82),
                "on_time_probability": 0.18,
                "threshold": 0.53,
                "risk_level": "high",
                "risk_alert": True,
                "target": "first permit not issued within 30 days",
            },
            "sensitivity_factors": [
                {
                    "label": "Review Type",
                    "risk_delta": 0.2,
                    "observed_value": "Standard",
                    "reference_value": "Professional",
                    "direction": "increased risk",
                }
            ],
            "sensitivity_note": "Local, non-causal sensitivity.",
            "historical_evidence": {
                "scope": "job type + review type",
                "count": 12,
                "median_processing_days": 45.0,
                "p25_processing_days": 35.0,
                "p75_processing_days": 70.0,
                "delayed_count": 9,
                "comparables": [],
                "coverage_note": "Completed cases only.",
            },
            "warnings": [],
            "model_context": {"model_name": "fake_model"},
        }


class Stage4WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.database = Path(self.directory.name) / "state.sqlite"
        self.reports = Path(self.directory.name) / "reports"
        self.workflow = PermitWorkflow(
            risk_service=FakeRiskService(),
            planner=EvidencePlanner(use_gemini=False),
            report_service=PDFReportService(self.reports),
            state_database_path=self.database,
        )

    def tearDown(self) -> None:
        self.workflow.close()
        self.directory.cleanup()

    def test_plan_is_grounded_in_assessment(self) -> None:
        assessment = FakeRiskService().assess({})
        plan = deterministic_plan(assessment)
        self.assertIn("82.0%", plan["summary"])
        self.assertIn("45", plan["summary"])
        self.assertEqual(plan["generated_by"], "deterministic_fallback")

    def test_workflow_pauses_then_resumes_after_approval(self) -> None:
        paused = self.workflow.start({"borough": "Queens"}, thread_id="test-approve")
        self.assertEqual(paused["status"], "awaiting_human_review")
        self.assertIn("review_request", paused)
        resumed = self.workflow.resume("test-approve", "approve", "Looks valid")
        self.assertEqual(resumed["status"], "approved_report_ready")
        self.assertTrue(self.workflow.report_service.path_for("test-approve").is_file())
        self.assertEqual(resumed["review"]["note"], "Looks valid")
        self.assertIsInstance(
            resumed["assessment"]["prediction"]["delay_probability"], float
        )

    def test_workflow_can_be_rejected(self) -> None:
        self.workflow.start({"borough": "Queens"}, thread_id="test-reject")
        resumed = self.workflow.resume("test-reject", "reject")
        self.assertEqual(resumed["status"], "rejected")

    def test_api_runs_assessment_and_review_contract(self) -> None:
        with TestClient(create_app(self.workflow, HistoryStore(self.database))) as client:
            health = client.get("/health")
            self.assertEqual(health.json(), {"status": "ok"})
            created = client.post(
                "/api/v1/assessments",
                json={
                    "workspace_id": "test-workspace",
                    "features": {"borough": "Queens"},
                },
            )
            self.assertEqual(created.status_code, 200)
            body = created.json()
            decision = client.post(
                f"/api/v1/assessments/{body['thread_id']}/decision",
                json={
                    "workspace_id": "test-workspace",
                    "decision": "approve",
                    "note": "Reviewed",
                },
            )
            self.assertEqual(decision.status_code, 200)
            self.assertEqual(
                decision.json()["status"], "approved_report_ready"
            )
            download = client.get(
                f"/api/v1/assessments/{body['thread_id']}/report",
                params={"workspace_id": "test-workspace"},
            )
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download.headers["content-type"], "application/pdf")
            self.assertTrue(download.content.startswith(b"%PDF"))
            history = client.get(
                "/api/v1/history", params={"workspace_id": "test-workspace"}
            )
            self.assertEqual(len(history.json()["items"]), 1)


if __name__ == "__main__":
    unittest.main()
