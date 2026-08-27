import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader

from scripts import manage_demo_artifacts
from src.agent.planner import EvidencePlanner
from src.agent.workflow import PermitWorkflow
from src.services.pdf_report import PDFReportService
from src.services.persistence import HistoryStore, normalize_workspace_id

from tests.test_stage4_workflow import FakeRiskService


class Stage6PersistencePDFTests(unittest.TestCase):
    def test_durable_checkpoint_resumes_after_workflow_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.sqlite"
            reports = Path(directory) / "reports"
            first = PermitWorkflow(
                risk_service=FakeRiskService(),
                planner=EvidencePlanner(use_gemini=False),
                report_service=PDFReportService(reports),
                state_database_path=database,
            )
            paused = first.start(
                {"borough": "Queens"}, thread_id="durable-restart-test"
            )
            self.assertEqual(paused["status"], "awaiting_human_review")
            first.close()

            second = PermitWorkflow(
                risk_service=FakeRiskService(),
                planner=EvidencePlanner(use_gemini=False),
                report_service=PDFReportService(reports),
                state_database_path=database,
            )
            resumed = second.resume(
                "durable-restart-test", "approve", "Resumed after restart"
            )
            second.close()
            self.assertEqual(resumed["status"], "approved_report_ready")
            self.assertTrue(PDFReportService(reports).path_for("durable-restart-test").is_file())

    def test_pdf_is_generated_once_and_contains_reviewed_context(self) -> None:
        assessment = FakeRiskService().assess({})
        assessment["historical_evidence"]["comparables"] = [
            {
                "job_filing_number": "Q001",
                "filing_date": "2023-04-10",
                "borough": "Queens",
                "processing_days": 45,
                "issued_within_30_days": False,
                "similarity_score": 0.91,
            }
        ]
        plan = EvidencePlanner(use_gemini=False).create_plan(assessment)
        with tempfile.TemporaryDirectory() as directory:
            service = PDFReportService(Path(directory))
            first = service.generate_once(
                "pdf-once",
                {"borough": "Queens", "job_type": "Alteration"},
                assessment,
                plan,
                {"decision": "approve", "note": "Reviewed by the permit lead"},
            )
            modified = service.path_for("pdf-once").stat().st_mtime_ns
            second = service.generate_once(
                "pdf-once", {}, assessment, plan, {"decision": "approve", "note": "Changed"}
            )
            reader = PdfReader(service.path_for("pdf-once"))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            unchanged = service.path_for("pdf-once").stat().st_mtime_ns
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(modified, unchanged)
        self.assertIn("Permit Risk Assessment", text)
        self.assertIn("Reviewed by the permit lead", text)
        self.assertIn("Q001", text)

    def test_rejection_does_not_generate_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.sqlite"
            reports = Path(directory) / "reports"
            workflow = PermitWorkflow(
                risk_service=FakeRiskService(),
                planner=EvidencePlanner(use_gemini=False),
                report_service=PDFReportService(reports),
                state_database_path=database,
            )
            workflow.start({"borough": "Queens"}, thread_id="rejected-report")
            result = workflow.resume("rejected-report", "reject", "Needs correction")
            workflow.close()
            self.assertEqual(result["status"], "rejected")
            self.assertFalse(PDFReportService(reports).path_for("rejected-report").exists())

    def test_workspace_history_is_isolated(self) -> None:
        result = {
            "thread_id": "thread-one",
            "status": "awaiting_human_review",
            "assessment": {
                "prediction": {"risk_level": "high", "delay_probability": 0.8}
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            store = HistoryStore(Path(directory) / "state.sqlite")
            store.create(
                "workspace-one",
                {"borough": "Queens", "job_type": "Alteration"},
                result,
            )
            self.assertEqual(len(store.list("workspace-one")), 1)
            self.assertEqual(store.list("workspace-one")[0]["report_status"], "not_generated")
            self.assertEqual(store.list("workspace-two"), [])
            with self.assertRaises(KeyError):
                store.get("workspace-two", "thread-one")

    def test_workspace_id_validation(self) -> None:
        self.assertEqual(normalize_workspace_id("team_demo-1"), "team_demo-1")
        with self.assertRaises(ValueError):
            normalize_workspace_id("x")
        with self.assertRaises(ValueError):
            normalize_workspace_id("contains spaces")

    def test_runtime_artifact_bundle_verifies_before_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            for index, name in enumerate(manage_demo_artifacts.RUNTIME_FILES):
                (source / name).write_bytes(f"artifact-{index}".encode())
            bundle = root / "demo.tar.gz"
            with patch.object(manage_demo_artifacts, "ARTIFACTS", source):
                manifest = manage_demo_artifacts.build(bundle)
            with patch.object(manage_demo_artifacts, "ARTIFACTS", destination):
                installed = manage_demo_artifacts.install(bundle)
            self.assertEqual(installed["files"], manifest["files"])
            for name in manage_demo_artifacts.RUNTIME_FILES:
                self.assertEqual((destination / name).read_bytes(), (source / name).read_bytes())


if __name__ == "__main__":
    unittest.main()
