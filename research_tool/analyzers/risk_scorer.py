"""Aggregate a report's findings into an overall risk score."""

from __future__ import annotations

from ..models.report import ResearchReport

_BREACH_CAP = 40
_GAP_CAP = 20


class RiskScorer:
    """Compute a 0-100 risk score from a report's findings.

    Risk reflects *adverse* signals rather than raw finding volume:
    an explicit engine-supplied ``risk_score``, breach exposure, and
    credential gaps (unverified / not-found).
    """

    @staticmethod
    def score(report: ResearchReport) -> int:
        if not report.findings:
            return 0

        # 1. Explicit risk supplied by an engine (max wins).
        score = max(
            (int(f.data.get("risk_score", 0) or 0) for f in report.findings),
            default=0,
        )

        # 2. Breach exposure.
        breaches = sum(1 for f in report.findings if f.title.startswith("Breach:"))
        score += min(breaches * 10, _BREACH_CAP)

        # 3. Credential gaps (unverified / not found).
        gaps = sum(
            1 for f in report.findings
            if f.data.get("status") in {"unverified", "not_found"}
            or f.title.startswith("No registry match")
            or f.title.startswith("No WHOIS record")
        )
        score += min(gaps * 5, _GAP_CAP)

        return int(min(score, 100))

    @staticmethod
    def label(score: int) -> str:
        if score >= 75:
            return "HIGH"
        if score >= 40:
            return "MEDIUM"
        if score > 0:
            return "LOW"
        return "NONE"


__all__ = ["RiskScorer"]
