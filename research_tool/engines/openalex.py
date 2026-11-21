"""OpenAlex author-research engine.

OpenAlex is a free, open catalogue of scholarly works and authors. It is
ideal for corroborating academic standing: publication counts, citation
metrics, affiliations and the researcher's ORCID iD.

API: https://docs.openalex.org  (no key required; a ``mailto`` is sent to
join the polite pool).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

from ..logger import logger
from ..models.report import Finding
from .base import BaseEngine

API = "https://api.openalex.org/authors"
MAILTO = "research-tool@example.com"


class OpenAlexEngine(BaseEngine):
    name = "openalex"
    category = "credential"

    def run(self, target: str, *, limit: int = 10, **kwargs: Any) -> list[Finding]:
        url = f"{API}?search={quote_plus(target)}&per_page={limit}&mailto={MAILTO}"
        data = self.cached_get_json(url)
        if not data or not data.get("results"):
            logger.info("[openalex] no authors for '{}'", target)
            return [self.finding(
                title=f"No OpenAlex author match for '{target}'",
                detail="Try a full name as it appears on publications.",
                confidence=0.3, status="not_found",
            )]

        findings: list[Finding] = []
        for author in data["results"]:
            display = author.get("display_name", "unknown")
            orcid = (author.get("orcid") or "").rsplit("/", 1)[-1] or None
            insts = [
                i.get("display_name")
                for i in (author.get("last_known_institutions") or [])
                if i.get("display_name")
            ]
            stats = author.get("summary_stats", {}) or {}
            findings.append(self.finding(
                title=f"Author: {display}",
                detail=(
                    f"works={author.get('works_count')}, "
                    f"citations={author.get('cited_by_count')}, "
                    f"h-index={stats.get('h_index')}, "
                    f"affiliations={', '.join(insts) or 'n/a'}"
                ),
                url=author.get("id"),
                confidence=0.7,
                category="credential",
                display_name=display,
                orcid=orcid,
                works_count=author.get("works_count"),
                cited_by_count=author.get("cited_by_count"),
                h_index=stats.get("h_index"),
                institutions=insts,
            ))
            if orcid:
                findings.append(self.finding(
                    title=f"ORCID iD: {orcid}",
                    detail="Authoritative researcher identifier",
                    url=f"https://orcid.org/{orcid}",
                    confidence=0.85,
                    category="credential",
                    orcid=orcid,
                ))
        logger.info("[openalex] {} findings for '{}'", len(findings), target)
        return findings


__all__ = ["OpenAlexEngine"]
