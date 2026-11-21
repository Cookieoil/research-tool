"""Optional LLM-powered analysis.

If an OpenAI-compatible API key is supplied (via the ``OPENAI_API_KEY``
environment variable) and the ``openai`` package is installed, findings
can be summarised into a narrative. Otherwise a deterministic
rule-based summary is produced so the toolkit always works offline.
"""

from __future__ import annotations

import os
from collections import Counter

from ..logger import logger
from ..models.report import ResearchReport


class LLMAnalyzer:
    """Summarise a report, with graceful offline fallback."""

    def __init__(self, model: str = "gpt-4o-mini"):
        self.model = model
        self.api_key = os.environ.get("OPENAI_API_KEY")

    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        if not self.api_key:
            return False
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        return True

    # ------------------------------------------------------------------
    def _rule_based(self, report: ResearchReport) -> str:
        if not report.findings:
            return f"No findings were produced for target '{report.target}'."

        engines = Counter(f.engine for f in report.findings)
        categories = Counter(f.category for f in report.findings)
        lines = [
            f"Research summary for '{report.target}' ({report.target_kind}).",
            f"{len(report.findings)} findings across {len(engines)} engine(s): "
            + ", ".join(f"{e}={c}" for e, c in engines.items()) + ".",
            "Categories: " + ", ".join(f"{k}={v}" for k, v in categories.items()) + ".",
        ]
        breaches = [f for f in report.findings if f.title.startswith("Breach:")]
        if breaches:
            lines.append(
                f"⚠ {len(breaches)} breach exposure(s) detected: "
                + ", ".join(b.title.replace('Breach: ', '') for b in breaches[:10]) + "."
            )
        high_conf = [f for f in report.findings if f.confidence >= 0.8]
        if high_conf:
            lines.append(
                "High-confidence findings: "
                + "; ".join(f.title for f in high_conf[:5]) + "."
            )
        return " ".join(lines)

    # ------------------------------------------------------------------
    def summarise(self, report: ResearchReport) -> str:
        if not self.available:
            return self._rule_based(report)
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)
            bullets = "\n".join(
                f"- [{f.category}/{f.engine}] {f.title} (conf {f.confidence})"
                for f in report.findings[:100]
            )
            prompt = (
                f"You are a professional OSINT research analyst. Summarise the "
                f"following findings about the target '{report.target}' into a "
                f"concise, neutral paragraph. Note credential-verification gaps "
                f"and any breach exposure.\n\n{bullets}"
            )
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            return resp.choices[0].message.content.strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[llm] analysis failed, using rule-based summary: {}", exc)
            return self._rule_based(report)


__all__ = ["LLMAnalyzer"]
