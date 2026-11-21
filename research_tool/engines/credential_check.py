"""Credential / breach-check engine.

Combines:
  * email syntax validation
  * MX-record deliverability check (dnspython)
  * HaveIBeenPwned breach lookup (requires an API key)
  * disposable-domain heuristic
"""

from __future__ import annotations

from typing import Any

from ..logger import logger
from ..models.credential import Breach, CredentialCheck
from ..models.report import Finding
from ..utils.validators import is_email
from .base import BaseEngine

# A small subset of well-known disposable-email providers.
DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
    "throwawaymail.com", "yopmail.com", "trashmail.com", "getnada.com",
    "sharklasers.com", "temp-mail.org", "dispostable.com",
}


class CredentialCheckEngine(BaseEngine):
    name = "credential_check"
    category = "credential"

    # ------------------------------------------------------------------
    def _mx_check(self, email: str) -> bool | None:
        domain = email.split("@")[-1]
        try:
            import dns.resolver
        except ImportError:
            return None
        try:
            answers = dns.resolver.resolve(domain, "MX")
            return len(answers) > 0
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------
    def _hibp(self, email: str) -> tuple[list[Breach], bool]:
        key = self.settings.api_keys.hibp
        if not key:
            return [], False
        url = f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}?truncateResponse=false"
        headers = {"hibp-api-key": key, "user-agent": self.settings.http.user_agent}
        try:
            resp = self.session.get(url, headers=headers, timeout=self.settings.http.timeout)
        except Exception:  # noqa: BLE001
            return [], False
        if resp.status_code == 404:
            return [], False
        if resp.status_code != 200:
            logger.warning("[credential_check] HIBP returned {}", resp.status_code)
            return [], False
        breaches: list[Breach] = []
        for item in resp.json():
            breaches.append(Breach(
                name=item.get("Name", "unknown"),
                domain=item.get("Domain"),
                breach_date=item.get("BreachDate"),
                pwn_count=item.get("PwnCount"),
                data_classes=item.get("DataClasses", []),
                description=item.get("Description"),
                is_verified=item.get("IsVerified"),
            ))
        return breaches, True

    # ------------------------------------------------------------------
    def analyse(self, email: str) -> CredentialCheck:
        check = CredentialCheck(email=email)
        check.syntax_valid = is_email(email)
        if not check.syntax_valid:
            return check

        domain = email.split("@")[-1].lower()
        check.disposable = domain in DISPOSABLE_DOMAINS
        check.mx_valid = self._mx_check(email)
        check.sources.append("syntax")
        if check.mx_valid is not None:
            check.sources.append("dns-mx")
        if check.disposable is not None:
            check.sources.append("disposable-list")

        breaches, breached = self._hibp(email)
        if breached or breaches:
            check.breached = True
            check.breaches = breaches
            check.breach_count = len(breaches)
            check.sources.append("hibp")

        check.risk_score = self._risk(check)
        return check

    @staticmethod
    def _risk(check: CredentialCheck) -> int:
        score = 0
        if not check.syntax_valid:
            score += 50
        if check.mx_valid is False:
            score += 30
        if check.disposable:
            score += 20
        score += min(check.breach_count * 10, 60)
        return min(score, 100)

    # ------------------------------------------------------------------
    def run(self, target: str, **kwargs: Any) -> list[Finding]:
        if not is_email(target):
            logger.warning("[credential_check] '{}' is not an email", target)
            return []
        check = self.analyse(target)
        findings: list[Finding] = [self.finding(
            title=f"Email risk score: {check.risk_score}/100",
            detail=(
                f"syntax_valid={check.syntax_valid}, mx_valid={check.mx_valid}, "
                f"disposable={check.disposable}, breaches={check.breach_count}"
            ),
            confidence=0.8,
            **check.model_dump(mode="json"),
        )]
        for breach in check.breaches:
            findings.append(self.finding(
                title=f"Breach: {breach.name}",
                detail=breach.description,
                url=f"https://haveibeenpwned.com/PwnedWebsites#{breach.name}",
                confidence=0.95, category="credential",
                breach_date=breach.breach_date,
                pwn_count=breach.pwn_count,
                data_classes=breach.data_classes,
            ))
        return findings


__all__ = ["CredentialCheckEngine", "DISPOSABLE_DOMAINS"]
