"""Markdown report writer (the default format)."""

from __future__ import annotations

from pathlib import Path

from ..analyzers.risk_scorer import RiskScorer
from ..models.report import ResearchReport


class MarkdownReporter:
    def render(self, report: ResearchReport) -> str:
        lines: list[str] = []
        lines.append(f"# Research Report: {report.target}")
        lines.append("")
        lines.append(f"- **Target kind:** {report.target_kind}")
        lines.append(f"- **Generated:** {report.generated_at.isoformat()}Z")
        lines.append(f"- **Engines run:** {', '.join(report.engines_run) or 'none'}")
        lines.append(f"- **Findings:** {len(report.findings)}")
        lines.append(
            f"- **Risk score:** {report.risk_score}/100 "
            f"({RiskScorer.label(report.risk_score)})"
        )
        lines.append("")

        if report.summary:
            lines.append("## Summary")
            lines.append("")
            lines.append(report.summary)
            lines.append("")

        if report.errors:
            lines.append("## Errors")
            lines.append("")
            for err in report.errors:
                lines.append(f"- {err}")
            lines.append("")

        lines.append("## Findings")
        lines.append("")
        for i, f in enumerate(report.findings, 1):
            lines.append(f"### {i}. {f.title}")
            lines.append("")
            lines.append(
                f"*engine:* `{f.engine}` | *category:* `{f.category}` | "
                f"*confidence:* {f.confidence}"
            )
            if f.detail:
                lines.append("")
                lines.append(f.detail)
            if f.url:
                lines.append("")
                lines.append(f"[source]({f.url})")
            lines.append("")
        return "\n".join(lines)

    def render_bytes(self, report: ResearchReport) -> bytes:
        return self.render(report).encode("utf-8")

    def write(self, report: ResearchReport, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.render_bytes(report))
        return path


__all__ = ["MarkdownReporter"]
