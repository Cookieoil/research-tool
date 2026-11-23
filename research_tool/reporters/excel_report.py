"""Excel (xlsx) report writer built on openpyxl/pandas."""

from __future__ import annotations

from pathlib import Path

from ..models.report import ResearchReport

# Cells beginning with these characters are interpreted as formulas by Excel.
# OSINT findings are attacker-influenced text, so neutralise them. Leading
# whitespace is stripped before the check so " =CMD|..." and "\n=CMD|..." cannot
# slip past the guard; "|" covers DDE-style payloads.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n", "|")


def _safe_cell(value: object) -> object:
    """Prefix formula-looking strings so Excel treats them as text."""
    if isinstance(value, str) and value.lstrip().startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


class ExcelReporter:
    def render_bytes(self, report: ResearchReport) -> bytes:
        from io import BytesIO

        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "pandas is required for Excel output: pip install pandas openpyxl"
            ) from exc

        rows = [
            {
                "engine": _safe_cell(f.engine),
                "category": _safe_cell(f.category),
                "title": _safe_cell(f.title),
                "detail": _safe_cell(f.detail),
                "url": _safe_cell(f.url),
                "confidence": f.confidence,
            }
            for f in report.findings
        ]
        df = pd.DataFrame(rows, columns=[
            "engine", "category", "title", "detail", "url", "confidence"
        ])

        meta = pd.DataFrame([{
            "target": _safe_cell(report.target),
            "target_kind": _safe_cell(report.target_kind),
            "generated_at": report.generated_at.isoformat(),
            "findings": len(report.findings),
            "risk_score": report.risk_score,
            "engines_run": _safe_cell(", ".join(report.engines_run)),
            "summary": _safe_cell(report.summary),
        }])

        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            meta.to_excel(writer, sheet_name="Overview", index=False)
            df.to_excel(writer, sheet_name="Findings", index=False)
        return buf.getvalue()

    def write(self, report: ResearchReport, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.render_bytes(report))
        return path


__all__ = ["ExcelReporter"]
