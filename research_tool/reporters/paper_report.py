"""Finalized research-paper writer (Markdown / PDF / JSON).

A *report* (``data/raw/``) records the raw information the engines found.
A *paper* (``papers/``) is the curated, citable write-up: abstract,
methodology, findings grouped by category, risk assessment, source register,
limitations and provenance. Papers follow the library rules in
``papers/ORGANISATION.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..analyzers.risk_scorer import RiskScorer
from ..models.paper import PaperMeta
from ..models.report import Finding, ResearchReport

_FORMAT_BY_SUFFIX = {".md": "markdown", ".pdf": "pdf", ".json": "json"}

# Optional ``report.metadata`` keys. They let desk/literature research replace
# the OSINT-specific boilerplate (credentials, identity matches, engine runs)
# with method-appropriate narrative while keeping the standard paper layout.
META_METHODOLOGY = "methodology"
META_LIMITATIONS = "limitations"
META_RISK = "risk_explanation"


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


def _meta_text(report: ResearchReport, key: str) -> str | None:
    """Return a non-empty string from ``report.metadata[key]``, else ``None``."""
    value = (report.metadata or {}).get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _meta_list(report: ResearchReport, key: str) -> list[str]:
    """Return ``report.metadata[key]`` as a list of non-empty strings."""
    value = (report.metadata or {}).get(key)
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


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
        """Render the paper as a research-paper manuscript (Markdown).

        Structure: title, a one-line document record, keywords, abstract,
        numbered sections, one prose paragraph per finding
        (`**F1 - claim.** detail *(confidence)* [n]`), an interpretation note,
        limitations, an optional raw appendix and a numbered reference list.
        CLI scaffolding (a document-control table, `engine=` debug strings,
        `Recorded data` fences, a "Risk score: 0/100" section) is deliberately
        not emitted: the manuscript must read as a research paper.
        """
        urls = source_urls(report)
        source_number = {url: index for index, url in enumerate(urls, 1)}

        grouped: dict[str, list[tuple[int, Finding]]] = {}
        for index, finding in enumerate(report.findings, 1):
            grouped.setdefault(finding.category or "uncategorised", []).append(
                (index, finding))

        status_label = meta.status.upper()
        document_line = (
            f"*Finalized research paper · Paper ID `{meta.paper_id}` · "
            f"Status {status_label} · Topic `{meta.topic}`*")
        abstract = meta.abstract or _default_abstract(report)

        lines: list[str] = [f"# {meta.title}", "", document_line, ""]
        if meta.tags:
            lines += [f"**Keywords:** {', '.join(meta.tags)}", ""]
        lines += ["## Abstract", "", abstract, ""]

        lines += ["## 1. Scope and method", ""]
        methodology = _meta_text(report, META_METHODOLOGY)
        if methodology:
            lines += [methodology, ""]
        else:
            lines += [
                f"This paper consolidates the findings recorded for "
                f"**{report.target}** (target kind: `{report.target_kind}`) by "
                f"the Credential Research Toolkit. "
                f"{len(report.engines_run)} engine(s) ran: "
                f"{', '.join(f'`{engine}`' for engine in report.engines_run) or 'none'}. "
                f"{len(report.findings)} finding(s) were normalised from public "
                f"sources, scored and grouped by category below.", "",
                "Every finding carries a 0-1 confidence value, reproduced "
                "below. A statement is described as *corroborated by public "
                "sources* where a source is listed, and as *verified* only "
                "where an authoritative registry is cited.", ""]
        if report.errors:
            lines += ["**Collection notes (source errors during the run):**", ""]
            lines += [f"- {error}" for error in report.errors]
            lines += [""]

        section = 1
        lines += ["## 2. Findings", ""]
        if not grouped:
            lines += ["_No findings were recorded._", ""]
        else:
            lines += [
                f"The {len(report.findings)} finding(s) are grouped by theme. "
                f"`F#` identifies the finding in the machine-readable JSON "
                f"record, and each trailing number points at the reference "
                f"list at the end of the paper.", ""]
            for category, items in grouped.items():
                section += 1
                lines += [f"### 2.{section - 1} "
                          f"{category.replace('_', ' ').title()} "
                          f"({len(items)})", ""]
                for number, finding in items:
                    citation = (f" [{source_number[finding.url]}]"
                                if finding.url in source_number else "")
                    confidence = _confidence_label(finding.confidence)
                    detail = _cell(finding.detail) if finding.detail else ""
                    lines += [
                        f"**F{number} — {_cell(finding.title)}.** {detail}"
                        f" *({confidence} confidence)*{citation}".replace(
                            "  ", " ").strip(), ""]


        risk_note = _meta_text(report, META_RISK)
        label = RiskScorer.label(report.risk_score)
        section += 1
        lines += [f"## {section}. Interpretation and confidence", ""]
        if risk_note:
            lines += [risk_note, ""]
        elif report.risk_score == 0 and report.target_kind not in (
                "name", "email", "username"):
            lines += [
                "No adverse-signal assessment of an individual or organisation "
                "is in scope for this paper, so the toolkit's 0-100 score has "
                "no subject to grade. The findings above are descriptive and "
                "carry the confidence reported with each one.", ""]
        else:
            lines += [f"The recorded risk score is {report.risk_score}/100 "
                      f"({label}). {_risk_explanation(report)}", ""]

        custom_limitations = _meta_list(report, META_LIMITATIONS)
        lines += [f"## {section + 1}. Limitations", ""]
        if custom_limitations:
            lines += [f"- {item}" for item in custom_limitations]
        else:
            lines += [
                "- Findings are drawn from public sources and carry only the "
                "confidence reported with each one.",
                "- A credential is *corroborated by public sources*; it is not "
                "*verified* unless an authoritative registry is cited.",
                "- Name matches (including sanctions screening) are leads for "
                "review, not proof of identity."]
        lines += [
            "- Absence of a finding is not proof of absence; sources that "
            "were skipped or blocked are noted above.",
            "- Public data changes; re-run the engines before relying on a "
            "paper that is no longer current.",
            "- Non-English source material is translated into English; "
            "original wording is kept only as a marked secondary reference.",
            ""]
        if report.errors:
            lines.append(f"- {len(report.errors)} source error(s) occurred "
                         "during collection (listed in section 1).")
            lines.append("")

        if include_raw:
            lines += ["## Appendix A — raw findings", "", "```json",
                      json.dumps(report.to_dict(), indent=2,
                                 ensure_ascii=False), "```", ""]

        lines += ["## References", ""]
        if urls:
            lines += [f"[{index}] {url}"
                      for index, url in enumerate(urls, 1)]
        else:
            lines += ["_No source URLs were recorded with the findings._"]
        lines.append("")
        return "\n".join(lines)

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
        """Typeset the paper as a publication-grade PDF.

        The Markdown manuscript is rendered first, then passed through the
        academic typesetting engine (title block, justified serif body,
        booktabs tables, running header/footer, formal references). Every
        output format therefore stays consistent with one Markdown source.
        """
        from .academic_pdf import render_paper_pdf

        markdown = self.render_markdown(report, meta, include_raw=include_raw)
        return render_paper_pdf(markdown, meta)

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


__all__ = ["PaperReporter", "source_urls"]