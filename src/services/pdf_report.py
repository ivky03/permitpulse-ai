"""Generate a durable, evidence-bound PDF after human approval."""

from __future__ import annotations

import hashlib
import html
import os
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from dotenv import load_dotenv

from src.modeling.train import ROOT


load_dotenv()
REPORT_DIRECTORY = Path(
    os.getenv("PERMITPULSE_REPORT_DIR", str(ROOT / "artifacts" / "reports"))
)
NAVY = colors.HexColor("#16324F")
TEAL = colors.HexColor("#0F766E")
PALE_TEAL = colors.HexColor("#E8F5F2")
PALE_BLUE = colors.HexColor("#EDF4FA")
INK = colors.HexColor("#1F2937")
MUTED = colors.HexColor("#5B6673")
LINE = colors.HexColor("#D8E1E8")
AMBER = colors.HexColor("#B45309")


def ascii_text(value: Any) -> str:
    """Keep user/data text safe for Helvetica and ReportLab paragraphs."""
    text = str(value if value not in (None, "") else "Not provided")
    replacements = {"\u2014": "-", "\u2013": "-", "\u2011": "-", "\u2022": "-"}
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "replace").decode()
    return html.escape(text)


def money(value: Any) -> str:
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return "Not provided"


def number(value: Any) -> str:
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return "Not provided"


def days(value: Any) -> str:
    try:
        return f"{float(value):g} days"
    except (TypeError, ValueError):
        return "N/A"


class _PageTemplate:
    def __init__(self, assessment_id: str) -> None:
        self.assessment_id = ascii_text(assessment_id[:12])

    def __call__(self, canvas, document) -> None:
        canvas.saveState()
        width, height = letter
        canvas.setStrokeColor(LINE)
        canvas.line(0.62 * inch, height - 0.48 * inch, width - 0.62 * inch, height - 0.48 * inch)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(NAVY)
        canvas.drawString(0.62 * inch, height - 0.37 * inch, "PERMITPULSE AI")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(width - 0.62 * inch, height - 0.37 * inch, f"Assessment {self.assessment_id}")
        canvas.line(0.62 * inch, 0.48 * inch, width - 0.62 * inch, 0.48 * inch)
        canvas.drawString(0.62 * inch, 0.31 * inch, "Planning support - not a compliance determination")
        canvas.drawRightString(width - 0.62 * inch, 0.31 * inch, f"Page {document.page}")
        canvas.restoreState()


class PDFReportService:
    def __init__(self, report_directory: Path = REPORT_DIRECTORY) -> None:
        self.report_directory = Path(report_directory)
        self.report_directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _file_key(thread_id: str) -> str:
        return hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:24]

    def path_for(self, thread_id: str) -> Path:
        return self.report_directory / f"permitpulse-assessment-{self._file_key(thread_id)}.pdf"

    @staticmethod
    def download_name(thread_id: str) -> str:
        safe = "".join(character for character in thread_id if character.isalnum())[:12]
        return f"permitpulse-assessment-{safe or 'report'}.pdf"

    @staticmethod
    def _styles() -> dict[str, ParagraphStyle]:
        base = getSampleStyleSheet()
        return {
            "title": ParagraphStyle(
                "ReportTitle", parent=base["Title"], fontName="Helvetica-Bold",
                fontSize=22, leading=26, textColor=NAVY, alignment=TA_LEFT,
                spaceAfter=6,
            ),
            "subtitle": ParagraphStyle(
                "Subtitle", parent=base["Normal"], fontSize=9.5, leading=14,
                textColor=MUTED, spaceAfter=16,
            ),
            "section": ParagraphStyle(
                "Section", parent=base["Heading2"], fontName="Helvetica-Bold",
                fontSize=13, leading=16, textColor=NAVY, spaceBefore=12, spaceAfter=7,
            ),
            "body": ParagraphStyle(
                "Body", parent=base["BodyText"], fontSize=9.2, leading=13,
                textColor=INK, spaceAfter=6,
            ),
            "small": ParagraphStyle(
                "Small", parent=base["BodyText"], fontSize=7.7, leading=10,
                textColor=MUTED,
            ),
            "card_label": ParagraphStyle(
                "CardLabel", parent=base["Normal"], fontName="Helvetica-Bold",
                fontSize=7.5, leading=9, textColor=MUTED, alignment=TA_CENTER,
            ),
            "card_value": ParagraphStyle(
                "CardValue", parent=base["Normal"], fontName="Helvetica-Bold",
                fontSize=16, leading=19, textColor=NAVY, alignment=TA_CENTER,
            ),
            "table": ParagraphStyle(
                "TableText", parent=base["Normal"], fontSize=7.2, leading=9,
                textColor=INK,
            ),
            "table_head": ParagraphStyle(
                "TableHead", parent=base["Normal"], fontName="Helvetica-Bold",
                fontSize=7.1, leading=8.5, textColor=colors.white,
            ),
            "callout": ParagraphStyle(
                "Callout", parent=base["BodyText"], fontSize=8.5, leading=12,
                textColor=INK, leftIndent=7, rightIndent=7, spaceBefore=4, spaceAfter=4,
            ),
        }

    @staticmethod
    def _p(styles: dict[str, ParagraphStyle], text: Any, style: str = "body") -> Paragraph:
        return Paragraph(ascii_text(text), styles[style])

    def _build_story(
        self,
        thread_id: str,
        request: dict[str, Any],
        assessment: dict[str, Any],
        plan: dict[str, Any],
        review: dict[str, str],
        generated_at: str,
    ) -> list[Any]:
        styles = self._styles()
        p = lambda text, style="body": self._p(styles, text, style)
        prediction = assessment["prediction"]
        evidence = assessment["historical_evidence"]
        context = assessment.get("model_context", {})
        story: list[Any] = [
            p("Permit Risk Assessment", "title"),
            p(
                f"Human-reviewed planning report | Generated {generated_at} | "
                f"Assessment ID {thread_id}",
                "subtitle",
            ),
        ]

        cards = Table(
            [[
                [p("30-DAY DELAY RISK", "card_label"), p(f"{prediction['delay_probability']:.1%}", "card_value")],
                [p("RISK LEVEL", "card_label"), p(str(prediction["risk_level"]).title(), "card_value")],
                [p("COMPARABLE MEDIAN", "card_label"), p(days(evidence.get("median_processing_days")), "card_value")],
            ]],
            colWidths=[2.18 * inch] * 3,
        )
        cards.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE),
            ("BOX", (0, 0), (-1, -1), 0.8, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.8, colors.white),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ]))
        story.extend([cards, Spacer(1, 10), p("Filing snapshot", "section")])

        snapshot = [
            ["Borough", request.get("borough"), "Job type", request.get("job_type")],
            ["Review type", request.get("filing_review_type"), "Building type", request.get("building_type")],
            ["Initial cost", money(request.get("initial_cost")), "Floor area", number(request.get("total_construction_floor_area"))],
        ]
        snapshot_rows = [[p(a, "small"), p(b, "table"), p(c, "small"), p(d, "table")] for a, b, c, d in snapshot]
        snapshot_table = Table(snapshot_rows, colWidths=[0.82 * inch, 2.42 * inch, 0.82 * inch, 2.42 * inch])
        snapshot_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), PALE_TEAL),
            ("BACKGROUND", (2, 0), (2, -1), PALE_TEAL),
            ("GRID", (0, 0), (-1, -1), 0.5, LINE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.extend([snapshot_table, p("Assessment summary", "section"), p(plan["summary"])])
        story.append(p(
            f"The model alert threshold is {prediction['threshold']:.0%}. The planning target is: "
            f"{prediction['target']}.",
            "callout",
        ))

        story.append(p("Why the estimate moved", "section"))
        factors = assessment.get("sensitivity_factors", [])
        if factors:
            factor_data = [[p(label, "table_head") for label in ["Input", "Observed", "Training reference", "Risk difference", "Direction"]]]
            for factor in factors:
                factor_data.append([
                    p(factor.get("label"), "table"),
                    p(factor.get("observed_value"), "table"),
                    p(factor.get("reference_value"), "table"),
                    p(f"{float(factor.get('risk_delta', 0)):+.1%}", "table"),
                    p(factor.get("direction"), "table"),
                ])
            factor_table = Table(factor_data, colWidths=[1.18 * inch, 1.32 * inch, 1.42 * inch, 0.9 * inch, 1.35 * inch], repeatRows=1)
            factor_table.setStyle(self._table_style())
            story.append(factor_table)
        else:
            story.append(p("No non-reference sensitivity fields were available."))
        story.append(p(assessment.get("sensitivity_note", ""), "small"))

        story.extend([p("Historical evidence", "section"), p(
            f"Match scope: {evidence.get('scope')}. {evidence.get('delayed_count', 0)} of "
            f"{evidence.get('count', 0)} displayed completed cases missed 30 days. "
            f"Processing-time range: p25 {evidence.get('p25_processing_days', 'N/A')} days, "
            f"median {evidence.get('median_processing_days', 'N/A')} days, and "
            f"p75 {evidence.get('p75_processing_days', 'N/A')} days."
        ), p(evidence.get("coverage_note", ""), "small")])

        comparables = evidence.get("comparables", [])
        if comparables:
            story.append(PageBreak())
            story.append(p("Comparable completed filings", "section"))
            comparable_data = [[p(label, "table_head") for label in ["Filing", "Date", "Borough", "Processing days", "Within 30?", "Similarity"]]]
            for row in comparables:
                comparable_data.append([
                    p(row.get("job_filing_number"), "table"),
                    p(row.get("filing_date"), "table"),
                    p(row.get("borough"), "table"),
                    p(row.get("processing_days"), "table"),
                    p("Yes" if row.get("issued_within_30_days") else "No", "table"),
                    p(f"{float(row.get('similarity_score', 0)):.3f}", "table"),
                ])
            comparable_table = Table(
                comparable_data,
                colWidths=[1.55 * inch, 0.9 * inch, 0.82 * inch, 1.0 * inch, 0.8 * inch, 0.83 * inch],
                repeatRows=1,
            )
            comparable_table.setStyle(self._table_style())
            story.extend([comparable_table, p(
                "Similarity supports comparison, not causation. These are completed cases and do not represent unresolved filings.",
                "small",
            )])

        story.append(p("Reviewed follow-up checklist", "section"))
        action_blocks = []
        for index, item in enumerate(plan.get("recommended_actions", []), start=1):
            action_blocks.append(KeepTogether([
                p(f"{index}. {item.get('owner')}: {item.get('action')}", "body"),
                p(f"Evidence: {item.get('evidence')}", "small"),
                Spacer(1, 4),
            ]))
        story.extend(action_blocks or [p("No follow-up actions were generated.")])
        story.extend([p(f"Timing: {plan.get('timing')}", "callout"), p("Human review", "section")])
        review_table = Table(
            [[p("Decision", "small"), p("Approved - PDF generated", "table")],
             [p("Reviewer note", "small"), p(review.get("note") or "No reviewer note provided.", "table")]],
            colWidths=[1.05 * inch, 5.43 * inch],
        )
        review_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), PALE_TEAL),
            ("GRID", (0, 0), (-1, -1), 0.5, LINE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("PADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(review_table)

        story.append(p("Warnings, limits, and model context", "section"))
        warnings = assessment.get("warnings", []) or ["No additional input warnings were generated."]
        for warning in warnings:
            story.append(p(f"- {warning}"))
        story.append(p(f"- {plan.get('guardrail')}"))
        training = context.get("training_period", {})
        story.append(p(
            f"Model: {context.get('model_name', 'Not provided')} | Training period: "
            f"{training.get('start', 'N/A')} to {training.get('end', 'N/A')} | "
            f"Data observation date: {context.get('observation_date', 'N/A')}",
            "small",
        ))
        story.append(Spacer(1, 10))
        disclaimer = Table([[p(
            "This report supports internal planning. It is not a compliance finding, permit decision, issuance guarantee, legal advice, or instruction to contact an agency automatically.",
            "callout",
        )]], colWidths=[6.48 * inch])
        disclaimer.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF7ED")),
            ("BOX", (0, 0), (-1, -1), 0.8, AMBER),
            ("PADDING", (0, 0), (-1, -1), 7),
        ]))
        story.append(disclaimer)
        return story

    @staticmethod
    def _table_style() -> TableStyle:
        return TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("GRID", (0, 0), (-1, -1), 0.45, LINE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE_BLUE]),
        ])

    def generate_once(
        self,
        thread_id: str,
        request: dict[str, Any],
        assessment: dict[str, Any],
        plan: dict[str, Any],
        review: dict[str, str],
    ) -> dict[str, Any]:
        path = self.path_for(thread_id)
        if not path.exists():
            generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            temporary = path.with_suffix(".pdf.tmp")
            document = SimpleDocTemplate(
                str(temporary), pagesize=letter,
                leftMargin=0.7 * inch, rightMargin=0.7 * inch,
                topMargin=0.65 * inch, bottomMargin=0.62 * inch,
                title="PermitPulse AI Permit Risk Assessment",
                author="PermitPulse AI",
            )
            template = _PageTemplate(thread_id)
            document.build(
                self._build_story(thread_id, request, assessment, plan, review, generated_at),
                onFirstPage=template,
                onLaterPages=template,
            )
            temporary.replace(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return {
            "status": "ready",
            "filename": self.download_name(thread_id),
            "sha256": digest,
            "size_bytes": path.stat().st_size,
        }
