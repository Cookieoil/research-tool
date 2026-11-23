"""Domain intelligence: DNS records, SSL/CT logs and Shodan host data."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..logger import logger
from ..models.report import Finding
from ..utils.validators import is_domain, normalise_domain
from .base import BaseEngine

RECORD_TYPES = ("A", "AAAA", "MX", "NS", "TXT", "SOA", "CNAME")


class DomainIntelEngine(BaseEngine):
    name = "domain_intel"
    category = "domain"

    # ------------------------------------------------------------------
    def _dns_records(self, domain: str) -> list[Finding]:
        try:
            import dns.resolver  # dnspython
        except ImportError:
            logger.warning("[domain_intel] dnspython not installed")
            return []

        # Some environments list slow/unreachable nameservers first, so a
        # long timeout would stall every query. Use a short per-try timeout
        # and query all record types concurrently.
        per_try = 3
        lifetime = 5

        def query(rtype: str) -> tuple[str, list[str]]:
            resolver = dns.resolver.Resolver()
            resolver.timeout = per_try
            resolver.lifetime = lifetime
            try:
                answers = resolver.resolve(domain, rtype)
            except Exception:  # noqa: BLE001 - dns raises many exception types
                return rtype, []
            return rtype, [r.to_text() for r in answers]

        findings: list[Finding] = []
        with ThreadPoolExecutor(max_workers=len(RECORD_TYPES)) as pool:
            for rtype, values in pool.map(query, RECORD_TYPES):
                if not values:
                    continue
                findings.append(self.finding(
                    title=f"{rtype} records ({len(values)})",
                    detail=", ".join(values[:10]),
                    confidence=0.9, domain=domain, record_type=rtype, values=values,
                ))
        return findings

    # ------------------------------------------------------------------
    def _cert_transparency(self, domain: str) -> list[Finding]:
        """Query crt.sh for issued certificates (subdomain discovery)."""
        data = self.cached_get_json(
            f"https://crt.sh/?q=%25.{domain}&output=json"
        )
        if not data:
            return []
        subdomains: set[str] = set()
        for entry in data:
            for name in str(entry.get("name_value", "")).splitlines():
                name = name.strip().lower().lstrip("*.")
                # Skip malformed entries (e.g. "user@example.com" from CN fields).
                if "@" in name or " " in name:
                    continue
                if not name.endswith(domain):
                    continue
                if not all(c.isalnum() or c in ".-" for c in name):
                    continue
                subdomains.add(name)
        if not subdomains:
            return []
        return [self.finding(
            title=f"{len(subdomains)} subdomains from certificate transparency",
            detail=", ".join(sorted(subdomains)[:25]),
            confidence=0.8, domain=domain, subdomains=sorted(subdomains),
        )]

    # ------------------------------------------------------------------
    def _shodan(self, domain: str) -> list[Finding]:
        key = self.settings.api_keys.shodan
        if not key:
            return []
        data = self.cached_get_json(
            f"https://api.shodan.io/dns/domain/{domain}",
            params={"key": key},
        )
        if not data:
            return []
        subdomains = data.get("subdomains", [])
        records = data.get("data", [])
        return [self.finding(
            title=f"Shodan: {len(subdomains)} subdomains, {len(records)} DNS records",
            confidence=0.75, domain=domain,
            subdomains=subdomains, records=records,
        )]

    # ------------------------------------------------------------------
    def run(self, target: str, **kwargs: Any) -> list[Finding]:
        domain = normalise_domain(target)
        if not is_domain(domain):
            logger.warning("[domain_intel] '{}' is not a valid domain", target)
            return []
        findings: list[Finding] = []
        findings.extend(self._dns_records(domain))
        findings.extend(self._cert_transparency(domain))
        findings.extend(self._shodan(domain))
        logger.info("[domain_intel] {} findings for {}", len(findings), domain)
        return findings


__all__ = ["DomainIntelEngine"]
