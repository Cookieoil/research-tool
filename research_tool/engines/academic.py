"""Academic / professional credential verification engine.

Performs source-guided web searches against accreditation bodies and
public registries to corroborate a claimed credential. This is a
best-effort corroboration helper, not an authoritative lookup, and
clearly labels every finding with its confidence.
"""

from __future__ import annotations

from typing import Any

from ..logger import logger
from ..models.credential import Credential
from ..models.report import Finding
from .base import BaseEngine
from .search import SearchEngine

# Well-known verification portals we surface as candidate sources.
VERIFICATION_SOURCES = {
    "academic": [
        ("National Student Clearinghouse", "https://studentclearinghouse.org"),
        ("World Higher Education Database (WHED)", "https://www.whed.net"),
        ("CHEA accredited institutions", "https://www.chea.org"),
    ],
    "certification": [
        ("ISC2 (CISSP/CSSLP)", "https://www.isc2.org"),
        ("PMI (PMP)", "https://www.pmi.org"),
        ("CompTIA", "https://www.comptia.org"),
        ("Microsoft Learn credentials", "https://learn.microsoft.com/credentials"),
        ("AWS Certification", "https://aws.amazon.com/certification"),
    ],
    "license": [
        ("US state medical boards (FSMB)", "https://www.fsmb.org"),
        ("NCEES (engineering)", "https://ncees.org"),
        ("State bar associations", "https://www.americanbar.org"),
    ],
}


class AcademicEngine(BaseEngine):
    name = "academic"
    category = "credential"

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._search = SearchEngine(self.settings, self.session, self.cache)

    def verify(self, holder: str, issuer: str | None = None,
               kind: str = "academic") -> Credential:
        cred = Credential(kind=kind, holder=holder, issuer=issuer, title=kind)
        query = " ".join(filter(None, [holder, issuer, "credential verification"]))
        results = self._search.run(query, limit=8)
        if results:
            cred.notes.append(f"{len(results)} corroborating web results found")
            cred.source_url = results[0].url
        return cred

    def run(self, target: str, *, issuer: str | None = None,
            kind: str = "academic", **kwargs: Any) -> list[Finding]:
        findings: list[Finding] = []
        cred = self.verify(target, issuer=issuer, kind=kind)

        findings.append(self.finding(
            title=f"Credential profile: {target}",
            detail=f"kind={kind}, issuer={issuer or 'unspecified'}",
            confidence=0.5, holder=target, kind=kind, issuer=issuer,
            status=cred.status,
        ))

        # Suggest authoritative verification portals.
        for name, url in VERIFICATION_SOURCES.get(kind, VERIFICATION_SOURCES["academic"]):
            findings.append(self.finding(
                title=f"Verify via {name}",
                detail=f"Consult {name} to confirm the credential",
                url=url, confidence=0.6, category="credential",
                source_portal=name,
            ))

        # Surface corroborating search hits.
        query = " ".join(filter(None, [target, issuer, "credential verification"]))
        for hit in self._search.run(query, limit=6):
            findings.append(self.finding(
                title=f"Corroboration: {hit.title}",
                detail=hit.detail, url=hit.url,
                confidence=0.4, category="credential", kind=kind,
            ))
        logger.info("[academic] {} findings for {}", len(findings), target)
        return findings


__all__ = ["AcademicEngine", "VERIFICATION_SOURCES"]
