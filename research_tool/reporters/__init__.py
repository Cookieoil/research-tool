"""Report writers for the research toolkit."""

import re
from pathlib import Path

from ..models.report import ResearchReport
from .excel_report import ExcelReporter
from .markdown_report import MarkdownReporter
from .paper_report import PaperReporter
from .pdf_report import PdfReporter

# Characters that are unsafe in a filename on Windows or POSIX. Backslashes,
# colons and drive letters are included so a crafted target cannot escape the
# output directory via ``..\\..\\`` or ``C:\\``.
_UNSAFE_STEM = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_stem(value: str) -> str:
    """Return a filesystem-safe stem (no separators, no traversal)."""
    stem = _UNSAFE_STEM.sub("_", str(value)).strip("._-")
    return stem[:120] or "report"


def _contained(out_dir: Path, name: str) -> Path:
    """Join *name* to *out_dir* and refuse anything that escapes it."""
    base = out_dir.resolve()
    dest = (base / name).resolve()
    if not dest.is_relative_to(base):
        raise ValueError(f"Refusing to write outside {base}: {name!r}")
    return dest


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
    # Sanitise the stem so a hostile target (``..\\..\\evil``) cannot escape
    # the output directory on Windows.
    stem = _safe_stem(stem or f"report_{report.target}")
    if fmt not in _EXT:
        raise ValueError(f"Unsupported report format: {fmt}")
    out_dir = Path(out_dir)

    if encrypt:
        from ..utils import crypto

        blob = crypto.encrypt_bytes(_render_bytes(report, fmt))
        path = _contained(out_dir, f"{stem}{_EXT[fmt]}.enc")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
        return path

    if fmt in ("md", "markdown"):
        return MarkdownReporter().write(
            report, _contained(out_dir, f"{stem}.md"))
    if fmt == "pdf":
        return PdfReporter().write(report, _contained(out_dir, f"{stem}.pdf"))
    if fmt in ("xlsx", "excel"):
        return ExcelReporter().write(
            report, _contained(out_dir, f"{stem}.xlsx"))
    # json
    import json
    path = _contained(out_dir, f"{stem}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return path


__all__ = ["MarkdownReporter", "PdfReporter", "ExcelReporter",
           "PaperReporter", "write_report"]
