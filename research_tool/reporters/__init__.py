"""Report writers for the research toolkit."""

from pathlib import Path

from ..models.report import ResearchReport
from .excel_report import ExcelReporter
from .markdown_report import MarkdownReporter
from .paper_report import PaperReporter
from .pdf_report import PdfReporter


_EXT = {"md": ".md", "markdown": ".md", "pdf": ".pdf",
        "xlsx": ".xlsx", "excel": ".xlsx", "json": ".json"}


def _render_bytes(report: ResearchReport, fmt: str) -> bytes:
    if fmt in ("md", "markdown"):
        return MarkdownReporter().render_bytes(report)
    if fmt == "pdf":
        return PdfReporter().render_bytes(report)
    if fmt in ("xlsx", "excel"):
        return ExcelReporter().render_bytes(report)
    if fmt == "json":
        import json
        return json.dumps(report.to_dict(), indent=2).encode("utf-8")
    raise ValueError(f"Unsupported report format: {fmt}")


def write_report(report: ResearchReport, fmt: str, out_dir: Path,
                 stem: str | None = None, encrypt: bool = False) -> Path:
    """Write *report* in the requested format and return the file path.

    When *encrypt* is true the rendered report is encrypted at rest and
    written as ``<stem>.<ext>.enc`` (needs ``RESEARCH_ENCRYPTION_KEY``).
    """
    fmt = fmt.lower()
    stem = stem or f"report_{report.target.replace('/', '_').replace(' ', '_')}"
    if fmt not in _EXT:
        raise ValueError(f"Unsupported report format: {fmt}")
    out_dir = Path(out_dir)

    if encrypt:
        from ..utils import crypto

        blob = crypto.encrypt_bytes(_render_bytes(report, fmt))
        path = out_dir / f"{stem}{_EXT[fmt]}.enc"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
        return path

    if fmt in ("md", "markdown"):
        return MarkdownReporter().write(report, out_dir / f"{stem}.md")
    if fmt == "pdf":
        return PdfReporter().write(report, out_dir / f"{stem}.pdf")
    if fmt in ("xlsx", "excel"):
        return ExcelReporter().write(report, out_dir / f"{stem}.xlsx")
    # json
    import json
    path = out_dir / f"{stem}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return path


__all__ = ["MarkdownReporter", "PdfReporter", "ExcelReporter",
           "PaperReporter", "write_report"]
