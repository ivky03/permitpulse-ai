import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import numpy as np

from scripts import bootstrap_runtime, manage_demo_artifacts
from src.agent.planner import EvidencePlanner
from src.agent.workflow import PermitWorkflow
from src.api.app import create_app
from src.mcp import server as mcp_server
from src.modeling.portfolio_evaluation import (
    calibration_bins,
    expected_calibration_error,
    top_fraction_metrics,
)
from src.services.pdf_report import PDFReportService
from src.services.persistence import HistoryStore
from src.services.portfolio import (
    normalize_project_context,
    portfolio_summary,
    rank_portfolio,
)
from src.services.procore_adapter import DemoProcoreAdapter

from tests.test_stage4_workflow import FakeRiskService


class Stage7PortfolioMCPTests(unittest.TestCase):
    def make_runtime(self, directory: str) -> tuple[PermitWorkflow, HistoryStore]:
        root = Path(directory)
        database = root / "state.sqlite"
        workflow = PermitWorkflow(
            risk_service=FakeRiskService(),
            planner=EvidencePlanner(use_gemini=False),
            report_service=PDFReportService(root / "reports"),
            state_database_path=database,
        )
        return workflow, HistoryStore(database)

    def test_portfolio_context_and_ranking(self) -> None:
        context = normalize_project_context(
            {
                "project_name": "School renovation",
                "permit_needed_by": "2026-10-01",
                "mitigation_owner": "A. Chen",
            }
        )
        self.assertEqual(context["review_status"], "new")
        items = rank_portfolio(
            [
                {**context, "risk_level": "moderate", "delay_probability": 0.7},
                {
                    **context,
                    "project_name": "Earlier high risk",
                    "permit_needed_by": "2026-09-01",
                    "risk_level": "high",
                    "delay_probability": 0.8,
                    "status": "awaiting_human_review",
                },
            ]
        )
        self.assertEqual(items[0]["project_name"], "Earlier high risk")
        self.assertEqual(portfolio_summary(items)["high_risk"], 1)
        with self.assertRaises(ValueError):
            normalize_project_context({"permit_needed_by": "next Tuesday"})

    def test_portfolio_api_and_approved_procore_draft(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow, history = self.make_runtime(directory)
            with TestClient(create_app(workflow, history)) as client:
                created = client.post(
                    "/api/v1/portfolio/assess",
                    json={
                        "workspace_id": "portfolio-test",
                        "items": [
                            {
                                "features": {"borough": "Queens"},
                                "project_context": {
                                    "project_name": "Queens clinic",
                                    "permit_needed_by": "2026-09-15",
                                    "mitigation_owner": "Permit lead",
                                },
                            }
                        ],
                    },
                )
                self.assertEqual(created.status_code, 200)
                item = created.json()["items"][0]
                blocked = client.get(
                    f"/api/v1/assessments/{item['thread_id']}/procore-draft",
                    params={"workspace_id": "portfolio-test"},
                )
                self.assertEqual(blocked.status_code, 409)
                approved = client.post(
                    f"/api/v1/assessments/{item['thread_id']}/decision",
                    json={
                        "workspace_id": "portfolio-test",
                        "decision": "approve",
                        "note": "Reviewed against project schedule",
                    },
                )
                self.assertEqual(approved.status_code, 200)
                draft = client.get(
                    f"/api/v1/assessments/{item['thread_id']}/procore-draft",
                    params={"workspace_id": "portfolio-test"},
                )
                self.assertEqual(draft.status_code, 200)
                self.assertEqual(
                    draft.json()["integration_status"],
                    "draft_only_no_external_write",
                )
                self.assertEqual(draft.json()["project"]["name"], "Queens clinic")
            workflow.close()

    def test_procore_adapter_never_writes_and_requires_approval(self) -> None:
        with self.assertRaises(ValueError):
            DemoProcoreAdapter().build_risk_draft({"status": "rejected"})

    def test_mcp_tools_are_read_only_and_callable(self) -> None:
        tools = asyncio.run(mcp_server.mcp.list_tools())
        names = {tool.name for tool in tools}
        self.assertEqual(
            names,
            {
                "assess_permit_risk",
                "find_comparable_permits",
                "prioritize_permit_portfolio",
            },
        )
        self.assertTrue(all(tool.annotations.read_only_hint for tool in tools))
        with patch.object(mcp_server, "risk_service", return_value=FakeRiskService()):
            result = asyncio.run(
                mcp_server.mcp.call_tool(
                    "assess_permit_risk", {"features": {"borough": "Queens"}}
                )
            )
        self.assertEqual(result.structured_content["prediction"]["risk_level"], "high")

    def test_mcp_contract_cases_reference_only_declared_tools(self) -> None:
        cases = json.loads(
            (Path(__file__).parent / "fixtures" / "mcp_tool_contract_cases.json")
            .read_text(encoding="utf-8")
        )
        declared = {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}
        self.assertTrue(cases)
        self.assertTrue(
            all(case["expected_tool"] in declared | {None} for case in cases)
        )

    def test_portfolio_evaluation_helpers(self) -> None:
        target = np.array([0, 1, 1, 0])
        probabilities = np.array([0.1, 0.9, 0.8, 0.2])
        top = top_fraction_metrics(target, probabilities, 0.5)
        self.assertEqual(top["delays_found"], 2)
        bins = calibration_bins(target, probabilities, bins=2)
        self.assertEqual(len(bins), 2)
        self.assertGreaterEqual(expected_calibration_error(bins), 0.0)

    def test_bootstrap_skips_download_when_artifacts_are_present(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory)
            for name in manage_demo_artifacts.RUNTIME_FILES:
                (artifacts / name).write_bytes(b"test")
            with patch.object(manage_demo_artifacts, "ARTIFACTS", artifacts):
                self.assertTrue(bootstrap_runtime.artifacts_present())
                self.assertEqual(
                    bootstrap_runtime.bootstrap(),
                    "Runtime artifacts already present.",
                )


if __name__ == "__main__":
    unittest.main()
