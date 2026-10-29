"""Offline unit tests for the PermitPulse real-agent quality audit."""
import unittest
from unittest.mock import patch

from src.agent.quality_audit import (
    apply_human_review, collect_agent_answer, evidence_snapshot, export_audit,
    judge_input, summarize, validate_import,
)


def assessment():
    return {
        "prediction": {"delay_probability": 0.75, "risk_level": "high"},
        "historical_evidence": {
            "count": 20, "delayed_count": 15, "median_processing_days": 37,
            "scope": "same borough", "coverage_note": "Historical completed cases only",
            "comparables": [{"address": "Don't include project addresses"}],
        },
        "sensitivity_factors": [{"label": "borough", "risk_delta": 0.1}],
        "warnings": [],
        "project_context": {"name": "Private project"},
    }


def case(label="UNREVIEWED", judge=None):
    return {
        "id": "test-123", "source": "real_agent", "question": "Can the city guarantee approval?",
        "verified_evidence": evidence_snapshot(assessment()),
        "candidate_answer": "No, approval is not established.",
        "tool_calls": ["get_risk_prediction"], "reference_label": label,
        "reviewer_note": ("Reviewed evidence" if label != "UNREVIEWED" else ""),
        "judge": judge,
    }


class QualityAuditTests(unittest.TestCase):
    def test_evidence_bounded(self):
        data = evidence_snapshot(assessment())
        self.assertNotIn("comparables", data["historical_evidence"])
        self.assertNotIn("project_context", data)
        self.assertEqual(data["prediction"]["delay_probability"], 0.75)

    def test_hidden_human_label(self):
        c = case("FAIL")
        c["reviewer_note"] = "Highly sensitive private reviewer note"
        payload = judge_input(c)
        self.assertEqual(set(payload), {"question", "verified_evidence", "candidate_answer"})
        self.assertNotIn("private reviewer note", str(payload))

    def test_review_requires_rationale(self):
        with self.assertRaises(ValueError):
            apply_human_review(case(), "PASS", "   ")
        r = apply_human_review(case(), "PASS", "Matches source facts")
        self.assertEqual(r["reference_label"], "PASS")
        self.assertIsNone(r["judge"])
        self.assertIsNotNone(r["reviewed_at_utc"])

    def test_synthetic_case_cannot_be_labeled(self):
        with self.assertRaises(ValueError):
            apply_human_review({**case(), "source": "synthetic"}, "PASS", "Test")

    def test_confusion_matrix_and_coverage(self):
        rows = [
            {**case("PASS", {"verdict": "PASS"}), "id": "1"},
            {**case("FAIL", {"verdict": "PASS"}), "id": "2"},
            {**case("FAIL", {"verdict": "FAIL"}), "id": "3"},
            {**case("PASS", {"verdict": "FAIL"}), "id": "4"},
        ]
        summary = summarize(rows)
        self.assertTrue(summary["complete"])
        self.assertEqual(summary["agreement"], 0.5)
        self.assertEqual(summary["false_accept_rate"], 0.5)
        self.assertEqual(summary["false_reject_rate"], 0.5)

    def test_incomplete_report_not_certified(self):
        summary = summarize([case("UNREVIEWED")])
        self.assertFalse(summary["complete"])
        self.assertIsNone(summary["agreement"])

    def test_import_clears_old_judge_verdict(self):
        payload = export_audit([case("PASS", {"verdict": "PASS"})])
        imported = validate_import(payload)
        self.assertIsNone(imported[0]["judge"])
        self.assertEqual(imported[0]["reference_label"], "PASS")

    def test_collect_calls_real_existing_planner(self):
        # No network; verifies the expected integration and observed response contract.
        class FakeResponse:
            answer = "No guarantee."
        class FakePlanner:
            def __init__(self, use_gemini, client_factory):
                self.model = None
            def answer_question(self, source, question):
                self.called_question = question
                return {"answer": "No guarantee.", "tool_calls": ["get_risk_prediction"]}
        with patch("google.genai.Client", return_value=object()), patch(
            "src.agent.planner.EvidencePlanner", FakePlanner
        ):
            record = collect_agent_answer(assessment(), "Is approval certain?", "dummy")
        self.assertEqual(record["source"], "real_agent")
        self.assertEqual(record["reference_label"], "UNREVIEWED")
        self.assertEqual(record["tool_calls"], ["get_risk_prediction"])
        self.assertEqual(record["candidate_answer"], "No guarantee.")


if __name__ == "__main__":
    unittest.main()
