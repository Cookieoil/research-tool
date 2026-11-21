"""Excel (xlsx) report writer built on openpyxl/pandas."""

from __future__ import annotations

from pathlib import Path

from ..models.report import ResearchReport


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
                "engine": f.engine,
                "category": f.category,
                "title": f.title,
                "detail": f.detail,
                "url": f.url,
                "confidence": f.confidence,
            }
            for f in report.findings
        ]
        df = pd.DataFrame(rows, columns=[
            "engine", "category", "title", "detail", "url", "confidence"
        ])

        meta = pd.DataFrame([{
            "target": report.target,
            "target_kind": report.target_kind,
            "generated_at": report.generated_at.isoformat(),
            "findings": len(report.findings),
            "risk_score": report.risk_score,
            "engines_run": ", ".join(report.engines_run),
            "summary": report.summary,
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
