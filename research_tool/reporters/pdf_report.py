"""PDF report writer (raw reports) built on the academic typesetting engine.

A raw report answers "what did the engines find?". It is typeset with the same
research-paper conventions as a finalized paper (title block, summary, a
findings table, detail sections, source URLs) instead of dumping
``engine=... | category=...`` debug strings into the page.
"""

from __future__ import annotations

from pathlib import Path

from ..analyzers.risk_scorer import RiskScorer
from ..models.report import ResearchReport


class PdfReporter:
    """Render a raw :class:`ResearchReport` as a readable PDF."""

    def render_markdown(self, report: ResearchReport) -> str:
        """Build the manuscript that the academic engine typesets."""
        label = RiskScorer.label(report.risk_score)
        lines: list[str] = [f"# Research Report: {report.target}", ""]
        if report.summary:
            lines += ["## Summary", "", report.summary, ""]
        if report.errors:
            lines += ["## Collection notes", ""]
            lines += [f"- {error}" for error in report.errors]
            lines += [""]
        lines += ["## Findings", ""]
        if not report.findings:
            lines += ["_No findings were recorded._", ""]
            return "\n".join(lines)
        lines += ["| # | Engine | Category | Confidence | Finding |",
                  "|---|---|---|---:|---|"]
        for number, finding in enumerate(report.findings, 1):
            title = str(finding.title).replace("|", "\\|").replace("\n", " ")
            category = str(finding.category).replace("|", "\\|")
            lines.append(
                f"| {number} | {finding.engine} | {category} | "
                f"{finding.confidence:.2f} | {title} |")
        lines += [""]
        for number, finding in enumerate(report.findings, 1):
            lines += [f"### {number}. {finding.title}", ""]
            if finding.detail:
                lines += [finding.detail, ""]
            if finding.url:
                lines += [f"<{finding.url}>", ""]
        return "\n".join(lines)

    def render_bytes(self, report: ResearchReport) -> bytes:
        from .academic_pdf import render_manuscript

        label = RiskScorer.label(report.risk_score)
        meta_line = (
            f"Target kind: {report.target_kind}  ·  "
            f"Findings: {len(report.findings)}  ·  "
            f"Risk: {report.risk_score}/100 ({label})  ·  "
            f"Generated {report.generated_at:%Y-%m-%d %H:%M} UTC")
        return render_manuscript(
            self.render_markdown(report),
            title=f"Research Report: {report.target}",
            meta_line=meta_line,
            header_right="RESEARCH REPORT",
        )

    def write(self, report: ResearchReport, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.render_bytes(report))
        return path


__all__ = ["PdfReporter"]
