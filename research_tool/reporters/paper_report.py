"""Finalized research-paper writer (Markdown / PDF / JSON).

A *report* (``data/reports/``) records the raw information the engines found.
A *paper* (``data/papers/``) is the curated, citable write-up: abstract,
methodology, findings grouped by category, risk assessment, source register,
limitations and provenance. Papers follow the library rules in
``data/papers/ORGANISATION.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..analyzers.risk_scorer import RiskScorer
from ..models.paper import PaperMeta
from ..models.report import Finding, ResearchReport

_FORMAT_BY_SUFFIX = {".md": "markdown", ".pdf": "pdf", ".json": "json"}


def source_urls(report: ResearchReport) -> list[str]:
    """Unique source URLs in first-seen order (the paper's source register)."""
    urls: list[str] = []
    for finding in report.findings:
        if finding.url and finding.url not in urls:
            urls.append(finding.url)
    return urls


def _confidence_label(value: float) -> str:
    if value >= 0.8:
        return "high"
    if value >= 0.5:
        return "moderate"
    return "low"


def _cell(text: object) -> str:
    """Make a value safe inside a Markdown table cell."""
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def _default_abstract(report: ResearchReport) -> str:
    if report.summary:
        return report.summary
    if not report.findings:
        return (f"No findings were recorded for {report.target} by the engines "
                f"that ran.")
    return (
        f"This paper consolidates {len(report.findings)} findings recorded for "
        f"{report.target} ({report.target_kind}) by "
        f"{len(report.engines_run)} engine(s). Overall risk is "
        f"{report.risk_score}/100 ({RiskScorer.label(report.risk_score)})."
    )


def _risk_explanation(report: ResearchReport) -> str:
    label = RiskScorer.label(report.risk_score)
    if label == "HIGH":
        return ("The score reflects strong adverse signals (explicit engine "
                "risk, breach exposure and/or credential gaps). Treat the "
                "target as high-exposure and corroborate before acting.")
    if label == "MEDIUM":
        return ("The score reflects material adverse signals (breach "
                "exposure and/or credential gaps). Review the source "
                "register before drawing conclusions.")
    if label == "LOW":
        return ("The score reflects limited adverse signals. It is not a "
                "clean bill of health: absence of a finding is not proof of "
                "absence.")
    return ("No adverse signals were recorded. This does not prove the "
            "target is risk-free; it means the engines that ran found "
            "nothing adverse.")


class PaperReporter:
    """Render a :class:`ResearchReport` as a finalized research paper."""

    def render_markdown(self, report: ResearchReport,
                        meta: PaperMeta,
                        include_raw: bool = False) -> str:
        urls = source_urls(report)
        src_index = {url: i for i, url in enumerate(urls, 1)}
        used_by: dict[str, list[str]] = {url: [] for url in urls}

        grouped: dict[str, list[tuple[int, Finding]]] = {}
        for i, finding in enumerate(report.findings, 1):
            grouped.setdefault(finding.category or "uncategorised", []).append(
                (i, finding))
            if finding.url in used_by:
                used_by[finding.url].append(f"F{i}")

        status_label = meta.status.upper()
        kind_label = ("FINALIZED RESEARCH PAPER" if meta.status == "final"
                      else "RESEARCH PAPER (DRAFT)")
        abstract = meta.abstract or _default_abstract(report)

        lines: list[str] = [
            f"# {meta.title}",
            "",
            f"> **{kind_label}** · Paper ID `{meta.paper_id}` · "
            f"Status **{status_label}** · Topic shelf `{meta.topic}`",
            "",
            "| Document control | Value |",
            "|---|---|",
            f"| Target | `{_cell(report.target)}` |",
            f"| Target kind | {report.target_kind} |",
            f"| Topic shelf | `{meta.topic}` |",
            f"| Status | {status_label} |",
            f"| Author / analyst | {_cell(meta.author)} |",
            f"| Published (UTC) | {meta.created_at:%Y-%m-%d %H:%M} |",
            f"| Engines run | {', '.join(meta.engines) or 'none'} |",
            f"| Findings | {meta.findings} |",
            f"| Sources cited | {meta.sources} |",
            f"| Risk score | {meta.risk_score}/100 ({meta.risk_label}) |",
            f"| Tags | {', '.join(meta.tags) or '—'} |",
            f"| Library file(s) | "
            f"{', '.join(f'`{f}`' for f in meta.files) or '—'} |",
            "",
            "## Abstract",
            "",
            abstract,
            "",
            "## 1. Scope and methodology",
            "",
            f"This paper consolidates the findings recorded for "
            f"**{report.target}** (target kind: `{report.target_kind}`) by the "
            f"Credential Research Toolkit. "
            f"{len(report.engines_run)} engine(s) ran: "
            f"{', '.join(f'`{e}`' for e in report.engines_run) or 'none'}. "
            f"{len(report.findings)} finding(s) were normalised from public "
            f"sources and scored.",
            "",
            "Every finding carries a 0–1 confidence value. A statement is "
            "described as *corroborated by public sources* only where a "
            "source is listed; it is *verified* only where an authoritative "
            "registry is cited. Engine output is reproduced without "
            "embellishment.",
            "",
        ]

        if report.errors:
            lines += ["**Collection notes (engine errors during the run):**", ""]
            lines += [f"- {err}" for err in report.errors]
            lines += [""]

        lines += ["## 2. Findings", ""]
        if not grouped:
            lines += ["_No findings were recorded._", ""]
        else:
            lines += [
                f"The {len(report.findings)} finding(s) are grouped by "
                f"category below. `F#` is the finding identifier and `S#` "
                f"refers to the source register in §4.",
                "",
            ]
            section = 0
            for category, items in grouped.items():
                section += 1
                lines += [
                    f"### 2.{section} {category.replace('_', ' ').title()} "
                    f"({len(items)})",
                    "",
                    "| ID | Finding | Engine | Confidence | Source |",
                    "|---|---|---|---:|---|",
                ]
                for number, finding in items:
                    source = (f"S{src_index[finding.url]}"
                              if finding.url in src_index else "—")
                    lines.append(
                        f"| F{number} | {_cell(finding.title)} | "
                        f"`{finding.engine}` | {finding.confidence:.2f} "
                        f"({_confidence_label(finding.confidence)}) | "
                        f"{source} |")
                lines.append("")
                lines += self._markdown_details(items)

        lines += [
            "## 3. Risk assessment",
            "",
            f"**Risk score: {report.risk_score}/100 "
            f"({RiskScorer.label(report.risk_score)}).** "
            f"{_risk_explanation(report)}",
            "",
        ]
        by_engine: dict[str, int] = {}
        for finding in report.findings:
            by_engine[finding.engine] = by_engine.get(finding.engine, 0) + 1
        if by_engine:
            lines += [
                "Findings by engine: "
                + ", ".join(f"`{name}` ({count})"
                            for name, count in by_engine.items())
                + ".",
                "",
            ]

        lines += ["## 4. Source register", ""]
        if urls:
            lines += ["| ID | Source | Used by |", "|---|---|---|"]
            for url in urls:
                lines.append(
                    f"| S{src_index[url]} | <{url}> | "
                    f"{', '.join(used_by[url]) or '—'} |")
            lines.append("")
        else:
            lines += ["_No source URLs were recorded with the findings._", ""]

        lines += [
            "## 5. Limitations and confidence",
            "",
            "- Findings are drawn from public sources and carry only the "
            "confidence reported by each engine.",
            "- A credential is *corroborated by public sources*; it is not "
            "*verified* unless an authoritative registry is cited.",
            "- Name matches (including sanctions screening) are leads for "
            "review, not proof of identity.",
            "- Absence of a finding is not proof of absence; engines that "
            "were skipped or blocked are noted in the findings.",
            "- Public data changes. Re-run the engines before relying on a "
            "paper that is no longer current.",
            "- Non-English source material is translated into English; "
            "original wording is kept only as a clearly marked secondary "
            "reference.",
        ]
        if report.errors:
            lines.append(f"- {len(report.errors)} engine error(s) occurred "
                         "during collection (listed in §1).")
        lines += [""]

        if include_raw:
            lines += [
                "## Appendix A — raw findings",
                "",
                "```json",
                json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
                "```",
                "",
            ]

        lines += [
            "## 6. Provenance",
            "",
            f"- **Paper ID:** `{meta.paper_id}`",
            f"- **Status:** {status_label}",
            f"- **Report generated (UTC):** "
            f"{report.generated_at:%Y-%m-%d %H:%M}",
            "- **Raw report:** "
            + (f"`{meta.source_report}`" if meta.source_report
               else "not linked (engines were run for this paper)"),
            "- **Library rules:** `data/papers/ORGANISATION.md`",
            "- **Library index:** `data/papers/INDEX.md`",
            "",
        ]
        return "\n".join(lines)

    @staticmethod
    def _markdown_details(items: list[tuple[int, Finding]]) -> list[str]:
        """Render the narrative/detail block for one category's findings."""
        lines: list[str] = []
        for number, finding in items:
            if not (finding.detail or finding.data):
                continue
            lines.append(f"**F{number} — {finding.title}**")
            lines.append("")
            lines.append(
                f"- *Engine:* `{finding.engine}` · *category:* "
                f"`{finding.category}` · *confidence:* "
                f"{finding.confidence:.2f} "
                f"({_confidence_label(finding.confidence)})")
            if finding.url:
                lines.append(f"- *Source:* <{finding.url}>")
            if finding.detail:
                lines.append(f"- *Detail:* {finding.detail}")
            if finding.data:
                lines.append("- *Recorded data:*")
                lines.append("")
                lines.append("```json")
                lines.append(json.dumps(finding.data, indent=2,
                                        ensure_ascii=False, default=str))
                lines.append("```")
            lines.append("")
        return lines

    def render_json(self, report: ResearchReport, meta: PaperMeta,
                    include_raw: bool = False) -> bytes:
        payload = {
            "meta": meta.to_dict(),
            "paper_markdown": self.render_markdown(
                report, meta, include_raw=include_raw),
            "report": report.to_dict(),
        }
        return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")

    def render_pdf(self, report: ResearchReport, meta: PaperMeta,
                   include_raw: bool = False) -> bytes:
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
        status_label = meta.status.upper()
        kind_label = ("FINALIZED RESEARCH PAPER" if meta.status == "final"
                      else "RESEARCH PAPER (DRAFT)")
        abstract = meta.abstract or _default_abstract(report)

        story = [
            Paragraph(_esc(meta.title), styles["Title"]),
            Spacer(1, 0.3 * cm),
            Paragraph(
                f"{kind_label} &nbsp;|&nbsp; Paper ID "
                f"{_esc(meta.paper_id)} &nbsp;|&nbsp; Status {status_label} "
                f"&nbsp;|&nbsp; Topic {_esc(meta.topic)}",
                styles["Italic"],
            ),
            Spacer(1, 0.4 * cm),
            Paragraph(
                f"Target: {_esc(report.target)} ({_esc(report.target_kind)}) "
                f"&nbsp;|&nbsp; Author: {_esc(meta.author)}",
                styles["Normal"],
            ),
            Paragraph(
                f"Published: {meta.created_at:%Y-%m-%d %H:%M} UTC "
                f"&nbsp;|&nbsp; Engines: "
                f"{_esc(', '.join(meta.engines) or 'none')}",
                styles["Normal"],
            ),
            Paragraph(
                f"Findings: {meta.findings} &nbsp;|&nbsp; Sources: "
                f"{meta.sources} &nbsp;|&nbsp; Risk: {meta.risk_score}/100 "
                f"({meta.risk_label})",
                styles["Normal"],
            ),
            Spacer(1, 0.5 * cm),
            Paragraph("Abstract", styles["Heading1"]),
            Paragraph(_esc(abstract), styles["BodyText"]),
            Spacer(1, 0.4 * cm),
            Paragraph("1. Scope and methodology", styles["Heading1"]),
            Paragraph(
                _esc(
                    f"This paper consolidates {len(report.findings)} "
                    f"finding(s) recorded for {report.target} by "
                    f"{len(report.engines_run)} engine(s): "
                    f"{', '.join(report.engines_run) or 'none'}. Every "
                    "finding carries a 0-1 confidence value; statements are "
                    "corroborated by public sources where a source is "
                    "listed, and verified only where an authoritative "
                    "registry is cited."),
                styles["BodyText"],
            ),
            Spacer(1, 0.4 * cm),
            Paragraph("2. Findings", styles["Heading1"]),
        ]

        if not report.findings:
            story.append(Paragraph("No findings were recorded.",
                                   styles["BodyText"]))
        for i, finding in enumerate(report.findings, 1):
            story.append(Paragraph(
                f"F{i}. {_esc(finding.title)}", styles["Heading3"]))
            story.append(Paragraph(
                _esc(f"engine={finding.engine} | category={finding.category} "
                     f"| confidence={finding.confidence:.2f} "
                     f"({_confidence_label(finding.confidence)})"),
                styles["Italic"],
            ))
            if finding.detail:
                story.append(Paragraph(_esc(finding.detail),
                                       styles["BodyText"]))
            if finding.url:
                story.append(Paragraph(_esc(finding.url), styles["BodyText"]))
            story.append(Spacer(1, 0.25 * cm))

        story += [
            Paragraph("3. Risk assessment", styles["Heading1"]),
            Paragraph(
                _esc(f"Risk score: {report.risk_score}/100 "
                     f"({RiskScorer.label(report.risk_score)}). "
                     f"{_risk_explanation(report)}"),
                styles["BodyText"],
            ),
            Spacer(1, 0.4 * cm),
            Paragraph("4. Source register", styles["Heading1"]),
        ]
        urls = source_urls(report)
        if urls:
            for i, url in enumerate(urls, 1):
                story.append(Paragraph(f"S{i}. {_esc(url)}",
                                       styles["BodyText"]))
        else:
            story.append(Paragraph("No source URLs were recorded.",
                                   styles["BodyText"]))
        story += [
            Spacer(1, 0.4 * cm),
            Paragraph("5. Limitations and confidence", styles["Heading1"]),
            Paragraph(
                _esc("Findings are drawn from public sources and carry only "
                     "the engine-reported confidence. Credentials are "
                     "corroborated by public sources, not verified, unless a "
                     "registry is cited. Name matches are leads, not "
                     "identity proof. Absence of a finding is not proof of "
                     "absence. Public data changes; re-run the engines "
                     "before relying on a paper that is no longer current."),
                styles["BodyText"],
            ),
            Spacer(1, 0.4 * cm),
        ]
        if include_raw:
            story.append(Paragraph("Appendix A — raw findings",
                                   styles["Heading1"]))
            raw_json = json.dumps(report.to_dict(), indent=2,
                                  ensure_ascii=False, default=str)
            for chunk in _split_for_pdf(raw_json):
                story.append(Paragraph(_esc(chunk).replace("\n", "<br/>"),
                                       styles["BodyText"]))
            story.append(Spacer(1, 0.4 * cm))
        story += [
            Paragraph("6. Provenance", styles["Heading1"]),
            Paragraph(
                _esc(f"Paper ID: {meta.paper_id} | Status: {status_label} | "
                     f"Report generated: {report.generated_at:%Y-%m-%d %H:%M} "
                     f"| Raw report: {meta.source_report or 'not linked'}"),
                styles["BodyText"],
            ),
        ]

        doc.build(story)
        return buf.getvalue()

    def render_bytes(self, report: ResearchReport, meta: PaperMeta,
                     fmt: str = "markdown",
                     include_raw: bool = False) -> bytes:
        fmt = fmt.lower()
        if fmt in ("md", "markdown"):
            return self.render_markdown(
                report, meta, include_raw=include_raw).encode("utf-8")
        if fmt == "pdf":
            return self.render_pdf(report, meta, include_raw=include_raw)
        if fmt == "json":
            return self.render_json(report, meta, include_raw=include_raw)
        raise ValueError(f"Unsupported paper format: {fmt}")

    def write(self, report: ResearchReport, meta: PaperMeta, path: Path,
              include_raw: bool = False) -> Path:
        fmt = _FORMAT_BY_SUFFIX.get(Path(path).suffix.lower())
        if fmt is None:
            raise ValueError(
                f"Unsupported paper file suffix: {Path(path).suffix}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.render_bytes(report, meta, fmt,
                                           include_raw=include_raw))
        return path


def _esc(text: str) -> str:
    """Escape minimal XML entities for reportlab paragraphs."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _split_for_pdf(text: str, size: int = 3500) -> list[str]:
    """Split long text so reportlab never receives an over-sized paragraph."""
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]


__all__ = ["PaperReporter", "source_urls"]