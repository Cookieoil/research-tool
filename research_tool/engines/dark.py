"""Dark web / dark net engine.

Provides reach into Tor hidden services (``.onion``):

  * a clearnet-accessible **index** of known onion addresses (Ahmia),
    used to check whether a service is publicly listed - works with no
    Tor and no API key;
  * best-effort **keyword search** across onion search engines, performed
    through a Tor SOCKS proxy;
  * direct **fetching/analysis of ``.onion`` pages** (title, meta
    description, emails, linked onion services, forms) over Tor.

Everything degrades gracefully: without a Tor proxy the engine still runs
in index-only mode and clearly reports what was skipped rather than
failing. Only publicly reachable services are touched; nothing here
bypasses authentication or accesses private data.

Tor is supplied via ``RESEARCH_HTTP_PROXY`` (or the ``--tor`` CLI flag) and
auto-detected on the common local ports (9050 = Tor daemon, 9150 = Tor
Browser). SOCKS support requires ``PySocks``.
"""

from __future__ import annotations

import re
import socket
from typing import Any
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup

from ..config import Settings
from ..logger import logger
from ..models.report import Finding
from ..utils.validators import is_onion, normalise_onion
from .base import BaseEngine

# Matches an onion host anywhere in a page/URL.
_ONION_HOST_RE = re.compile(r"([a-z2-7]{16}|[a-z2-7]{56})\.onion", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _proxy_host_port(proxy: str) -> tuple[str, int] | None:
    """Extract ``(host, port)`` from a proxy URL, or ``None``."""
    try:
        parsed = urlparse(proxy)
    except ValueError:
        return None
    if parsed.hostname and parsed.port:
        return parsed.hostname, parsed.port
    return None


def _proxy_port_open(proxy: str, timeout: float = 0.5) -> bool:
    """True when a TCP connection to the proxy endpoint succeeds."""
    host_port = _proxy_host_port(proxy)
    if not host_port:
        return False
    try:
        with socket.create_connection(host_port, timeout=timeout):
            return True
    except OSError:
        return False


def detect_tor_proxy(settings: Settings) -> str | None:
    """Return a usable Tor SOCKS proxy, or ``None`` if none is reachable.

    A proxy set in ``settings.http.proxy`` always wins. Otherwise the common
    local Tor ports are probed: 9050 (Tor daemon) and 9150 (Tor Browser).
    """
    if settings.http.proxy:
        return settings.http.proxy
    for candidate in (settings.darkweb.tor_proxy, *settings.darkweb.tor_alt_proxies):
        if _proxy_port_open(candidate):
            return candidate
    return None


class DarkEngine(BaseEngine):
    """Search the dark web and analyse ``.onion`` services."""

    name = "dark"
    category = "darkweb"

    def __init__(self, settings: Settings, session=None, cache=None):
        super().__init__(settings, session, cache)
        self._tor_resolved = False
        self._tor_value: str | None = None

    # ------------------------------------------------------------------
    # Plumbing
    # ------------------------------------------------------------------
    def _tor_proxy(self) -> str | None:
        """The Tor SOCKS proxy to use (resolved once per engine instance)."""
        if not self._tor_resolved:
            self._tor_value = detect_tor_proxy(self.settings)
            self._tor_resolved = True
        return self._tor_value

    def _tor_available(self) -> bool:
        """True when a Tor SOCKS proxy is reachable (configured or local)."""
        return self._tor_proxy() is not None

    def _tor_session(self) -> requests.Session | None:
        """A session routed through Tor, or ``None`` when Tor is absent.

        When the main session is already proxied (via ``http.proxy``) it is
        reused; otherwise a lightweight Tor-routed session is created.
        """
        proxy = self._tor_proxy()
        if not proxy:
            return None
        if proxy == self.settings.http.proxy:
            return self.session
        session = requests.Session()
        session.proxies.update({"http": proxy, "https": proxy})
        session.headers.update(self.session.headers)
        session.verify = self.session.verify
        return session

    def _raw_get(self, url: str, timeout: int | None = None, *,
                 via_tor: bool = False):
        """GET without populating the cache (returns None on error)."""
        session = self._tor_session() if via_tor else self.session
        if session is None:
            return None
        try:
            return session.get(
                url, timeout=timeout or self.settings.http.timeout
            )
        except Exception as exc:  # noqa: BLE001 - network errors vary
            logger.debug("[dark] request failed {}: {}", url, exc)
            return None

    def _onion_index(self) -> set[str]:
        """Return the set of onion hosts published by the configured index.

        The (large) index page is fetched once and only the parsed host set
        is cached, keeping the cache small.
        """
        index_url = self.settings.darkweb.index_url
        cache_key = f"onion-index {index_url}"
        if self.cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return set(cached)

        resp = self._raw_get(index_url, timeout=self.settings.http.timeout)
        hosts: set[str] = set()
        if resp is not None and resp.status_code == 200:
            hosts = {m.group(0).lower() for m in _ONION_HOST_RE.finditer(resp.text)}
        if self.cache and hosts:
            self.cache.set(cache_key, sorted(hosts))
        logger.debug("[dark] onion index: {} hosts", len(hosts))
        return hosts

    # ------------------------------------------------------------------
    # Tor-only capabilities
    # ------------------------------------------------------------------
    def _search_tor(self, query: str, limit: int) -> list[Finding]:
        """Best-effort keyword search across onion search engines via Tor.

        Onion search engines render results server-side, so onion hosts are
        harvested from anchor tags (link text becomes the title) and, as a
        fallback, from any bare onion address in the page. Each engine's own
        address is ignored.
        """
        findings: list[Finding] = []
        seen: set[str] = set()

        def _record(host: str, title: str | None, href: str | None) -> bool:
            if host == engine_host or host in seen:
                return False
            seen.add(host)
            link = href if (href or "").lower().startswith("http") else f"http://{host}/"
            findings.append(self.finding(
                title=(title or host)[:200],
                detail="Onion service discovered via dark-web search",
                url=link, confidence=0.5, category="darkweb",
                onion=host, source="tor-search", query=query,
            ))
            return len(findings) >= limit

        for template in self.settings.darkweb.search_endpoints:
            url = template.format(query=quote_plus(query))
            resp = self._raw_get(url, via_tor=True)
            if resp is None or resp.status_code != 200:
                continue
            engine_host = (urlparse(url).hostname or "").lower()
            soup = BeautifulSoup(resp.text, "lxml")

            for anchor in soup.find_all("a", href=True):
                href = anchor["href"]
                match = _ONION_HOST_RE.search(href)
                if match and _record(match.group(0).lower(),
                                     anchor.get_text(strip=True), href):
                    return findings

            for match in _ONION_HOST_RE.finditer(resp.text):
                if _record(match.group(0).lower(), None, None):
                    return findings
        return findings

    def _scrape_onion(self, url: str) -> list[Finding]:
        """Fetch and analyse a ``.onion`` page (requires Tor)."""
        findings: list[Finding] = []
        resp = self._raw_get(url, via_tor=True)
        if resp is None or resp.status_code != 200:
            findings.append(self.finding(
                title=f"Could not reach {url}",
                detail=("No Tor proxy detected" if not self._tor_available()
                        else "Service unreachable over Tor"),
                url=url, confidence=0.2, category="darkweb", reachable=False,
                status="skipped" if not self._tor_available() else "unreachable",
            ))
            return findings

        soup = BeautifulSoup(resp.text, "lxml")
        title = soup.title.get_text(strip=True) if soup.title else None
        desc_el = soup.find("meta", attrs={"name": "description"})
        description = desc_el.get("content") if desc_el else None
        findings.append(self.finding(
            title=f"Onion service: {title or url}",
            detail=description, url=url, confidence=0.7, category="darkweb",
            page_title=title, meta_description=description, reachable=True,
        ))

        text = soup.get_text(" ", strip=True)
        emails = sorted(set(_EMAIL_RE.findall(text)))
        if emails:
            findings.append(self.finding(
                title=f"{len(emails)} email(s) on onion page",
                detail=", ".join(emails[:15]), url=url,
                confidence=0.5, category="identity", emails=emails,
            ))

        onion_links = sorted({
            match.group(0).lower()
            for anchor in soup.find_all("a", href=True)
            for match in [_ONION_HOST_RE.search(anchor["href"])] if match
        })
        if onion_links:
            findings.append(self.finding(
                title=f"{len(onion_links)} linked onion service(s)",
                detail=", ".join(onion_links[:25]), url=url,
                confidence=0.6, category="darkweb", onion_links=onion_links,
            ))

        forms = soup.find_all("form")
        if forms:
            findings.append(self.finding(
                title=f"{len(forms)} form(s) on onion page",
                detail="Indicates an interactive service (login, market, forum, ...)",
                url=url, confidence=0.4, category="darkweb",
            ))
        return findings

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def run(self, target: str, *, limit: int = 10, **kwargs: Any) -> list[Finding]:
        target = target.strip()
        if is_onion(target):
            return self._run_onion(target, limit)
        return self._run_keyword(target, limit)

    def _run_onion(self, target: str, limit: int) -> list[Finding]:
        host = normalise_onion(target)
        url = (target if target.lower().startswith(("http://", "https://"))
               else f"http://{host}/")
        findings: list[Finding] = [self.finding(
            title=f"Onion address: {host}",
            detail="Tor hidden service (v2/v3 .onion) address recognised",
            confidence=0.9, category="darkweb", onion=host,
        )]

        # Index membership - clearnet, no Tor needed.
        hosts = self._onion_index()
        if hosts:
            listed = host in hosts
            findings.append(self.finding(
                title=("Listed in dark-web index" if listed
                       else "Not found in dark-web index"),
                detail=f"Public onion index contains {len(hosts)} services",
                url=self.settings.darkweb.index_url,
                confidence=0.7 if listed else 0.5,
                category="darkweb", onion=host, indexed=listed,
                status="verified" if listed else "not_found",
            ))

        # Direct fetch over Tor.
        if self._tor_available():
            findings.extend(self._scrape_onion(url))
        else:
            findings.append(self.finding(
                title="Tor proxy not detected",
                detail=("Start Tor Browser (socks5h://127.0.0.1:9150) or the Tor "
                        "daemon (socks5h://127.0.0.1:9050) and re-run with --tor "
                        "to fetch .onion services; index lookup works without Tor."),
                url=url, confidence=0.3, category="darkweb", onion=host,
                status="skipped",
            ))

        logger.info("[dark] {} findings for onion {}", len(findings), host)
        return findings

    def _run_keyword(self, target: str, limit: int) -> list[Finding]:
        findings: list[Finding] = [self.finding(
            title=f"Dark-web search: {target}",
            detail="Querying dark-web sources for the target",
            confidence=0.3, category="darkweb", query=target,
        )]
        if self._tor_available():
            results = self._search_tor(target, limit)
            if results:
                findings.extend(results)
            else:
                findings.append(self.finding(
                    title="No dark-web results",
                    detail=("Tor was reachable but no onion search engine "
                            "returned a result for this query."),
                    confidence=0.3, category="darkweb", status="not_found",
                ))
        else:
            findings.append(self.finding(
                title="Dark-web keyword search requires Tor",
                detail=("No Tor SOCKS proxy detected. Start Tor Browser "
                        "(socks5h://127.0.0.1:9150) or the Tor daemon "
                        "(socks5h://127.0.0.1:9050), then re-run with --tor. "
                        "Only the onion index works without Tor."),
                confidence=0.3, category="darkweb", status="skipped",
            ))
        logger.info("[dark] {} findings for '{}'", len(findings), target)
        return findings


__all__ = ["DarkEngine", "detect_tor_proxy"]
