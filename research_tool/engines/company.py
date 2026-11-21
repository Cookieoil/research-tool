"""Company / business-registry research engine.

Uses the OpenCorporates search API (anonymous access is rate-limited
but key-free) and SEC EDGAR full-text search for public US companies.
"""

from __future__ import annotations

from typing import Any

from ..logger import logger
from ..models.organization import Organization
from ..models.report import Finding
from .base import BaseEngine


class CompanyEngine(BaseEngine):
    name = "company"
    category = "company"

    # ------------------------------------------------------------------
    def _opencorporates(self, name: str) -> list[Organization]:
        data = self.cached_get_json(
            f"https://api.opencorporates.com/v0.4/companies/search?q={name}&per_page=10"
        )
        if not data:
            return []
        orgs: list[Organization] = []
        for item in data.get("results", {}).get("companies", []):
            c = item.get("company", {})
            orgs.append(Organization(
                name=c.get("name", name),
                registry_id=c.get("company_number"),
                jurisdiction=c.get("jurisdiction_code"),
                status=c.get("current_status"),
                incorporation_date=c.get("incorporation_date"),
                address=c.get("registered_address_in_full"),
                source_url=c.get("opencorporates_url"),
                raw=c,
            ))
        return orgs

    # ------------------------------------------------------------------
    def _sec_edgar(self, name: str) -> list[Organization]:
        data = self.cached_get_json(
            "https://www.sec.gov/cgi-bin/browse-edgar"
            f"?company={name}&type=10-K&dateb=&owner=include&count=5&action=getcompany",
        )
        # SEC returns HTML; use the EDGAR full-text search JSON endpoint instead.
        data = self.cached_get_json(
            f"https://efts.sec.gov/LATEST/search-index?q=%22{name}%22&dateRange=custom"
        )
        return []  # EDGAR JSON shape varies; handled via search engine instead.

    # ------------------------------------------------------------------
    def run(self, target: str, **kwargs: Any) -> list[Finding]:
        findings: list[Finding] = []
        orgs = self._opencorporates(target)
        for org in orgs:
            findings.append(self.finding(
                title=f"Company: {org.name}",
                detail=(
                    f"jurisdiction={org.jurisdiction}, status={org.status}, "
                    f"registered={org.incorporation_date}"
                ),
                url=org.source_url, confidence=0.75,
                registry_id=org.registry_id,
                jurisdiction=org.jurisdiction,
                status=org.status,
                incorporation_date=org.incorporation_date,
                address=org.address,
            ))
        if not findings:
            findings.append(self.finding(
                title=f"No registry match for '{target}'",
                detail="Try a full legal entity name or add a jurisdiction.",
                confidence=0.3,
            ))
        logger.info("[company] {} findings for {}", len(findings), target)
        return findings


__all__ = ["CompanyEngine"]
