import base64
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from src.agent.intake import (
    decode_document,
    normalize_extraction,
    validate_document_signature,
)
from src.agent.planner import EvidencePlanner, unsupported_numeric_claims
from src.agent.workflow import PermitWorkflow
from src.api.app import create_app
from src.services.pdf_report import PDFReportService
from src.services.persistence import HistoryStore
from tests.test_stage4_workflow import FakeRiskService


class FakeGeminiPlanner(EvidencePlanner):
    def __init__(self, answer: str, calls: list[str]) -> None:
        super().__init__(use_gemini=True)
        self.answer = answer
        self.calls = calls
        self.seen_requests: list[str] = []

    def _gemini_answer(self, assessment, request):
        self.seen_requests.append(request)
        return self.answer, self.calls


class FakeIntakeAgent:
    def extract(self, filename, mime_type, content, metadata):
        return {
            "document": {"filename": filename, "mime_type": mime_type},
            "features": {"borough": "Queens"},
            "extracted_features": {"borough": "Queens"},
            "project_context": {"project_name": "Uploaded clinic"},
            "field_evidence": [],
            "missing_required_fields": ["job_type"],
            "warnings": [],
            "requires_confirmation": True,
            "generated_by": "fake-gemini",
        }


class FailingGeminiPlanner(EvidencePlanner):
    def __init__(self) -> None:
        super().__init__(use_gemini=True)

    def _gemini_answer(self, assessment, request):
        raise ConnectionError("provider unavailable")


class Stage10AgenticIntakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assessment = FakeRiskService().assess({})

    def test_grounded_tool_calling_plan_is_accepted(self) -> None:
        planner = FakeGeminiPlanner(
            "The model shows 82% risk; 12 comparables had a 45-day median.",
            ["get_risk_prediction", "find_comparable_permits"],
        )
        plan = planner.create_plan(self.assessment)
        self.assertEqual(plan["generated_by"], "gemini-2.5-flash")
        self.assertEqual(plan["agent_trace"]["mode"], "gemini_tool_calling")

    def test_missing_required_tool_forces_deterministic_fallback(self) -> None:
        planner = FakeGeminiPlanner(
            "The model shows 82% risk.", ["get_risk_prediction"]
        )
        plan = planner.create_plan(self.assessment)
        self.assertEqual(plan["generated_by"], "deterministic_fallback")
        self.assertIn("required evidence tools", plan["planner_warning"])

    def test_unsupported_number_is_rejected(self) -> None:
        claims = unsupported_numeric_claims(
            "Risk is 99% even though evidence says 82%.", self.assessment
        )
        self.assertEqual(claims, ["99"])

    def test_equivalent_precision_and_trailing_punctuation_are_allowed(self) -> None:
        assessment = dict(self.assessment)
        assessment["prediction"] = dict(self.assessment["prediction"])
        assessment["prediction"]["delay_probability"] = 0.9373
        assessment["historical_evidence"] = dict(self.assessment["historical_evidence"])
        assessment["historical_evidence"]["comparables"] = [{"processing_days": 31}]
        claims = unsupported_numeric_claims(
            "The risk is 93.73%. One comparable took 31, days.", assessment
        )
        self.assertEqual(claims, [])

    def test_follow_up_question_reports_tools_and_grounding(self) -> None:
        planner = FakeGeminiPlanner(
            "Review the 82% risk and the 45-day comparable median.",
            ["get_risk_prediction", "find_comparable_permits"],
        )
        result = planner.answer_question(self.assessment, "What should I review?")
        self.assertTrue(result["grounded"])
        self.assertIn("get_risk_prediction", result["tool_calls"])

    def test_provider_failure_becomes_recoverable_agent_error(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Please retry"):
            FailingGeminiPlanner().answer_question(
                self.assessment, "What should I review?"
            )

    def test_document_normalization_never_guesses_missing_core_fields(self) -> None:
        artifact = FakeRiskService().artifact
        metadata = {
            "reference_values": artifact["input_profile"]["reference_values"],
            "categories": artifact["input_profile"]["categories"],
        }
        result = normalize_extraction(
            {
                "features": {
                    "borough": "Queens",
                    "job_type": "Invented job type",
                    "initial_cost": "$250,000",
                    "filing_status": "Approved",
                },
                "project_context": {"project_name": "Clinic"},
                "field_evidence": [
                    {"field": "borough", "source": "Page 1", "confidence": "high"}
                ],
            },
            metadata,
        )
        self.assertEqual(result["extracted_features"]["initial_cost"], 250_000.0)
        self.assertNotIn("filing_status", result["extracted_features"])
        self.assertIn("job_type", result["missing_required_fields"])
        self.assertTrue(result["requires_confirmation"])
        self.assertTrue(any("outside" in item for item in result["warnings"]))

    def test_document_decoder_rejects_invalid_base64(self) -> None:
        with self.assertRaises(ValueError):
            decode_document("not-base64!!")

    def test_document_signature_must_match_mime_type(self) -> None:
        validate_document_signature(b"%PDF-1.7 sample", "application/pdf")
        with self.assertRaises(ValueError):
            validate_document_signature(b"not really a PDF", "application/pdf")

    def test_document_and_agent_question_api_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "state.sqlite"
            planner = FakeGeminiPlanner(
                "The 82% risk is supported by a 45-day comparable median.",
                ["get_risk_prediction", "find_comparable_permits"],
            )
            workflow = PermitWorkflow(
                risk_service=FakeRiskService(),
                planner=planner,
                report_service=PDFReportService(root / "reports"),
                state_database_path=database,
            )
            with TestClient(
                create_app(workflow, HistoryStore(database), FakeIntakeAgent())
            ) as client:
                intake = client.post(
                    "/api/v1/agent/document-intake",
                    json={
                        "filename": "permit.pdf",
                        "mime_type": "application/pdf",
                        "content_base64": base64.b64encode(b"fake-pdf").decode(),
                    },
                )
                self.assertEqual(intake.status_code, 200)
                self.assertTrue(intake.json()["requires_confirmation"])
                created = client.post(
                    "/api/v1/assessments",
                    json={
                        "workspace_id": "agent-test",
                        "features": {"borough": "Queens"},
                    },
                ).json()
                answer = client.post(
                    f"/api/v1/assessments/{created['thread_id']}/agent-question",
                    json={
                        "workspace_id": "agent-test",
                        "question": "What should I review?",
                    },
                )
                self.assertEqual(answer.status_code, 200)
                self.assertTrue(answer.json()["grounded"])
                self.assertEqual(len(answer.json()["messages"]), 2)
                second = client.post(
                    f"/api/v1/assessments/{created['thread_id']}/agent-question",
                    json={
                        "workspace_id": "agent-test",
                        "question": "What can I do next?",
                    },
                )
                self.assertEqual(second.status_code, 200)
                self.assertEqual(len(second.json()["messages"]), 4)
                self.assertIn("What should I review?", planner.seen_requests[-1])
                self.assertIn("45-day comparable median", planner.seen_requests[-1])
                chat = client.get(
                    f"/api/v1/assessments/{created['thread_id']}/agent-chat",
                    params={"workspace_id": "agent-test"},
                )
                self.assertEqual(chat.status_code, 200)
                self.assertEqual(
                    [message["role"] for message in chat.json()["messages"]],
                    ["user", "assistant", "user", "assistant"],
                )
            workflow.close()


if __name__ == "__main__":
    unittest.main()
