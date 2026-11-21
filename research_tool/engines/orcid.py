"""ORCID researcher-identity engine.

ORCID is the authoritative registry of researcher identifiers. Looking a
name up here corroborates academic identity, affiliations and (where the
researcher has published it) a contact email.

API: https://info.orcid.org/documentation/api/  (public, no key required).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

from ..logger import logger
from ..models.report import Finding
from .base import BaseEngine

API = "https://pub.orcid.org/v3.0/expanded-search/"
JSON_HEADERS = {"Accept": "application/json"}


class OrcidEngine(BaseEngine):
    name = "orcid"
    category = "credential"

    def run(self, target: str, *, limit: int = 10, **kwargs: Any) -> list[Finding]:
        url = f"{API}?q={quote_plus(target)}&rows={limit}"
        data = self.cached_get_json(url, headers=JSON_HEADERS)
        if data is None:
            logger.warning("[orcid] lookup failed for '{}'", target)
            return []

        results = data.get("expanded-result") or []
        if not results:
            return [self.finding(
                title=f"No ORCID record for '{target}'",
                detail=f"{data.get('num-found', 0)} total matches; none returned.",
                confidence=0.3, status="not_found",
            )]

        findings: list[Finding] = []
        for rec in results:
            orcid_id = rec.get("orcid-id")
            given = rec.get("given-names") or ""
            family = rec.get("family-names") or ""
            name = (rec.get("credit-name") or f"{given} {family}").strip()
            emails = rec.get("email") or []
            institutions = rec.get("institution-name") or []
            findings.append(self.finding(
                title=f"ORCID: {name}",
                detail=(
                    f"id={orcid_id}, affiliations="
                    f"{', '.join(institutions) or 'n/a'}"
                    + (f", email={', '.join(emails)}" if emails else "")
                ),
                url=f"https://orcid.org/{orcid_id}" if orcid_id else None,
                confidence=0.8,
                category="credential",
                orcid=orcid_id,
                name=name,
                emails=emails,
                institutions=institutions,
            ))
        logger.info("[orcid] {} findings for '{}'", len(findings), target)
        return findings


__all__ = ["OrcidEngine"]
