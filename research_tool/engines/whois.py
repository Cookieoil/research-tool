"""WHOIS domain registration engine."""

from __future__ import annotations

from typing import Any

from ..logger import logger
from ..models.report import Finding
from ..utils.validators import is_domain, normalise_domain
from .base import BaseEngine


class WhoisEngine(BaseEngine):
    name = "whois"
    category = "domain"

    def run(self, target: str, **kwargs: Any) -> list[Finding]:
        domain = normalise_domain(target)
        if not is_domain(domain):
            logger.warning("[whois] '{}' is not a valid domain", target)
            return []

        try:
            import whois  # python-whois
        except ImportError:
            logger.warning("[whois] python-whois not installed")
            return []

        try:
            record = whois.whois(domain)
        except Exception as exc:  # noqa: BLE001 - third-party lib raises broadly
            logger.warning("[whois] lookup failed for {}: {}", domain, exc)
            return []

        if not record or not record.get("domain_name"):
            return [self.finding(
                title=f"No WHOIS record for {domain}",
                confidence=0.4, domain=domain,
            )]

        findings: list[Finding] = []

        def _first(value: Any) -> Any:
            if isinstance(value, list):
                return value[0] if value else None
            return value

        registrar = _first(record.get("registrar"))
        creation = _first(record.get("creation_date"))
        expiry = _first(record.get("expiration_date"))
        name_servers = record.get("name_servers") or []

        findings.append(self.finding(
            title=f"Registrar: {registrar or 'unknown'}",
            detail=f"Domain {domain} registered via {registrar or 'unknown'}",
            confidence=0.9, domain=domain,
            registrar=registrar,
            creation_date=str(creation) if creation else None,
            expiration_date=str(expiry) if expiry else None,
            name_servers=list(name_servers),
            emails=list(record.get("emails") or []),
            org=record.get("org"),
            country=record.get("country"),
        ))

        if creation:
            findings.append(self.finding(
                title=f"Created: {creation}",
                category="domain", confidence=0.85, domain=domain,
            ))
        if expiry:
            findings.append(self.finding(
                title=f"Expires: {expiry}",
                category="domain", confidence=0.85, domain=domain,
            ))
        return findings


__all__ = ["WhoisEngine"]
