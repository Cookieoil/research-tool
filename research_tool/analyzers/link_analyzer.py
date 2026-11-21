"""Entity / link analysis: group findings and surface relationships."""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from urllib.parse import urlparse

from ..models.report import Finding, ResearchReport


class LinkAnalyzer:
    """Build simple relationship maps from report findings."""

    @staticmethod
    def domains(findings: list[Finding]) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for f in findings:
            if f.url:
                netloc = urlparse(f.url).netloc
                if netloc:
                    counts[netloc] += 1
        return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))

    @staticmethod
    def by_category(findings: list[Finding]) -> dict[str, list[Finding]]:
        grouped: dict[str, list[Finding]] = defaultdict(list)
        for f in findings:
            grouped[f.category].append(f)
        return dict(grouped)

    @staticmethod
    def by_engine(findings: list[Finding]) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for f in findings:
            counts[f.engine] += 1
        return dict(counts)

    @classmethod
    def summarise(cls, report: ResearchReport) -> dict[str, Any]:
        return {
            "total_findings": len(report.findings),
            "by_engine": cls.by_engine(report.findings),
            "by_category": {k: len(v) for k, v in cls.by_category(report.findings).items()},
            "top_domains": list(cls.domains(report.findings).items())[:10],
        }


__all__ = ["LinkAnalyzer"]
