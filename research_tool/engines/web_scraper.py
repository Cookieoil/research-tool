"""Generic web scraping / page-analysis engine.

Fetches a URL and extracts useful research signals: page title,
meta description, emails, phone numbers, social links and outbound
links. Works for static HTML; JS-heavy pages degrade gracefully.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..logger import logger
from ..models.report import Finding
from ..utils.validators import is_safe_url, is_url
from .base import BaseEngine

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


class WebScraperEngine(BaseEngine):
    name = "web_scraper"
    category = "web"

    def _scrape(self, url: str) -> list[Finding]:
        resp = self.cached_get(url)
        if resp is None or resp.status_code != 200:
            return [self.finding(
                title=f"Could not fetch {url}",
                detail="Non-200 or network error", url=url, confidence=0.2,
            )]

        if getattr(resp, "truncated", False):
            logger.warning("[web_scraper] response capped at size limit: {}", url)

        soup = BeautifulSoup(resp.text, "lxml")
        findings: list[Finding] = []

        title = soup.title.get_text(strip=True) if soup.title else None
        desc_el = soup.find("meta", attrs={"name": "description"})
        description = desc_el.get("content") if desc_el else None

        findings.append(self.finding(
            title=f"Page: {title or url}",
            detail=description, url=url, confidence=0.7,
            page_title=title, meta_description=description,
        ))

        text = soup.get_text(" ", strip=True)
        emails = sorted(set(_EMAIL_RE.findall(text)))
        if emails:
            findings.append(self.finding(
                title=f"{len(emails)} email(s) on page",
                detail=", ".join(emails[:15]),
                url=url, confidence=0.6, category="identity", emails=emails,
            ))

        phones = sorted(set(m.strip() for m in _PHONE_RE.findall(text)))
        phones = [p for p in phones if len(re.sub(r"\D", "", p)) >= 8]
        if phones:
            findings.append(self.finding(
                title=f"{len(phones)} phone-like string(s) on page",
                detail=", ".join(phones[:10]),
                url=url, confidence=0.4, category="identity", phones=phones,
            ))

        social_links: list[str] = []
        outbound: list[str] = []
        host = urlparse(url).netloc
        for a in soup.find_all("a", href=True):
            href = urljoin(url, a["href"])
            if any(p in href for p in ("twitter.com", "linkedin.com", "facebook.com",
                                        "instagram.com", "github.com", "youtube.com")):
                social_links.append(href)
            elif urlparse(href).netloc and urlparse(href).netloc != host:
                outbound.append(href)

        if social_links:
            findings.append(self.finding(
                title=f"{len(social_links)} social link(s)",
                detail=", ".join(sorted(set(social_links))[:15]),
                url=url, confidence=0.6, category="identity",
                social_links=sorted(set(social_links)),
            ))
        if outbound:
            findings.append(self.finding(
                title=f"{len(set(outbound))} outbound link(s)",
                url=url, confidence=0.5,
                outbound=sorted(set(outbound))[:50],
            ))
        return findings

    def run(self, target: str, **kwargs: Any) -> list[Finding]:
        url = target if is_url(target) else f"https://{target}"
        if not is_url(url):
            logger.warning("[web_scraper] '{}' is not a URL", target)
            return []
        # SSRF guard: never fetch loopback/private/link-local addresses
        # (cloud metadata endpoints such as 169.254.169.254 included).
        if not is_safe_url(url, resolve=True):
            logger.warning("[web_scraper] blocked unsafe/private URL: {}", url)
            return [self.finding(
                title=f"Blocked unsafe URL: {url}",
                detail="Target resolves to a private, loopback or link-local "
                       "address. Set an explicit allowlist if this is intended.",
                url=url, confidence=0.1,
            )]
        return self._scrape(url)


__all__ = ["WebScraperEngine"]
