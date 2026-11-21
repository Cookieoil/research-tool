"""PDF report writer built on reportlab."""

from __future__ import annotations

from pathlib import Path

from ..analyzers.risk_scorer import RiskScorer
from ..models.report import ResearchReport


class PdfReporter:
    def render_bytes(self, report: ResearchReport) -> bytes:
        from io import BytesIO

        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib.units import cm
            from reportlab.platypus import (Paragraph, SimpleDocTemplate,
                                            Spacer)
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "reportlab is required for PDF output: pip install reportlab"
            ) from exc

        styles = getSampleStyleSheet()
        buf = BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4,
                                leftMargin=2 * cm, rightMargin=2 * cm,
                                topMargin=2 * cm, bottomMargin=2 * cm)
        story = [
            Paragraph(f"Research Report: {_esc(report.target)}", styles["Title"]),
            Spacer(1, 0.4 * cm),
            Paragraph(
                f"Target kind: {_esc(report.target_kind)} &nbsp;|&nbsp; "
                f"Findings: {len(report.findings)} &nbsp;|&nbsp; "
                f"Risk: {report.risk_score}/100 "
                f"({RiskScorer.label(report.risk_score)})",
                styles["Normal"],
            ),
            Paragraph(
                f"Generated: {report.generated_at.isoformat()}Z",
                styles["Normal"],
            ),
            Spacer(1, 0.5 * cm),
        ]

        if report.summary:
            story.append(Paragraph("Summary", styles["Heading1"]))
            story.append(Paragraph(_esc(report.summary), styles["BodyText"]))
            story.append(Spacer(1, 0.4 * cm))

        story.append(Paragraph("Findings", styles["Heading1"]))
        for i, f in enumerate(report.findings, 1):
            story.append(Paragraph(
                f"{i}. {_esc(f.title)}", styles["Heading3"]
            ))
            meta = f"engine={f.engine} | category={f.category} | confidence={f.confidence}"
            story.append(Paragraph(_esc(meta), styles["Italic"]))
            if f.detail:
                story.append(Paragraph(_esc(f.detail), styles["BodyText"]))
            if f.url:
                story.append(Paragraph(_esc(f.url), styles["BodyText"]))
            story.append(Spacer(1, 0.3 * cm))

        doc.build(story)
        return buf.getvalue()

    def write(self, report: ResearchReport, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.render_bytes(report))
        return path


def _esc(text: str) -> str:
    """Escape minimal XML entities for reportlab paragraphs."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


__all__ = ["PdfReporter"]
