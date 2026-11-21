"""NPI Registry engine (US healthcare professional licensing).

Queries the CMS NPPES NPI Registry - the public, authoritative registry
of US healthcare providers. Returns the NPI number, enumerated name,
credential, specialty taxonomy and any state licence numbers on record.

API: https://npiregistry.cms.hhs.gov/api-page  (public, no key required).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from ..logger import logger
from ..models.report import Finding
from .base import BaseEngine

API = "https://npiregistry.cms.hhs.gov/api/"


def split_name(target: str) -> tuple[str | None, str | None]:
    """Parse a target into (first_name, last_name).

    Accepts "First Last" (middle names ignored) or "Last, First".
    """
    target = target.strip()
    if "," in target:
        last, _, first = target.partition(",")
        return (first.strip() or None, last.strip() or None)
    parts = target.split()
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return None, parts[0] if parts else None


class NpiEngine(BaseEngine):
    name = "npi"
    category = "credential"

    def run(self, target: str, *, state: str | None = None,
            limit: int = 10, **kwargs: Any) -> list[Finding]:
        first, last = split_name(target)
        if not last:
            logger.warning("[npi] could not parse a name from '{}'", target)
            return []

        params = {"version": "2.1", "limit": limit}
        if first:
            params["first_name"] = first
        params["last_name"] = last
        if state:
            params["state"] = state.upper()

        data = self.cached_get_json(f"{API}?{urlencode(params)}")
        if not data:
            logger.warning("[npi] lookup failed for '{}'", target)
            return []

        results = data.get("results") or []
        if not results:
            return [self.finding(
                title=f"No NPI registry match for '{target}'",
                detail="US healthcare providers only; add a state to narrow.",
                confidence=0.3, status="not_found",
            )]

        findings: list[Finding] = []
        for rec in results:
            basic = rec.get("basic", {}) or {}
            npi = rec.get("number")
            name = f"{basic.get('first_name', '')} {basic.get('last_name', '')}".strip()
            credential = basic.get("credential")
            taxonomies = rec.get("taxonomies") or []
            primary = next((t for t in taxonomies if t.get("primary")), None) or \
                (taxonomies[0] if taxonomies else {})
            licences = [
                f"{t.get('license')} ({t.get('state')})"
                for t in taxonomies if t.get("license")
            ]
            findings.append(self.finding(
                title=f"NPI {npi}: {name}"
                      + (f", {credential}" if credential else ""),
                detail=(
                    f"specialty={primary.get('desc')}, "
                    f"licences={', '.join(licences) or 'n/a'}, "
                    f"status={basic.get('status')}, "
                    f"enumerated={basic.get('enumeration_date')}"
                ),
                url=f"https://npiregistry.cms.hhs.gov/provider-view/{npi}",
                confidence=0.85,
                category="credential",
                status="verified",
                npi=npi,
                credential=credential,
                specialty=primary.get("desc"),
                licences=licences,
                enumeration_date=basic.get("enumeration_date"),
                provider_status=basic.get("status"),
                gender=basic.get("gender"),
            ))
        logger.info("[npi] {} findings for '{}'", len(findings), target)
        return findings


__all__ = ["NpiEngine", "split_name"]
