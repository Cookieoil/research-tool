"""Web / news search engine.

Search order (all degrade gracefully):
  1. the ``ddgs`` library - DuckDuckGo's maintained client, which solves
     the anti-bot challenge that now blocks plain HTML scraping;
  2. a direct HTML scrape of DuckDuckGo's ``html``/``lite`` endpoints;
  3. Google via SerpAPI when a key is configured.

Steps 1-2 require no API key. When the ``ddgs`` package is not installed
the engine transparently falls back to scraping.
"""

from __future__ import annotations

import importlib
from functools import lru_cache
from typing import Any
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from ..logger import logger
from ..models.report import Finding
from .base import BaseEngine

DDG_HTML = "https://html.duckduckgo.com/html/?q={query}"
DDG_LITE = "https://lite.duckduckgo.com/lite/?q={query}"


@lru_cache(maxsize=1)
def _ddgs_class() -> type | None:
    """Return the ``DDGS`` class from the ``ddgs`` package.

    Falls back to the legacy ``duckduckgo_search`` import name so either
    package works. Returns ``None`` when neither is installed, in which
    case the engine degrades to HTML scraping.
    """
    for module_name in ("ddgs", "duckduckgo_search"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        cls = getattr(module, "DDGS", None)
        if cls is not None:
            return cls
    return None


class SearchEngine(BaseEngine):
    name = "search"
    category = "web"

    # ------------------------------------------------------------------
    def _ddg_search(self, query: str, limit: int) -> list[Finding]:
        """Query DuckDuckGo, preferring the ``ddgs`` library."""
        findings = self._ddg_library(query, limit)
        if findings:
            return findings

        if _ddgs_class() is None:
            logger.warning(
                "[search] 'ddgs' not installed; using HTML scraping "
                "(pip install ddgs for reliable results)"
            )
        scraped = self._ddg_scrape(query, limit)
        if not scraped:
            logger.debug("[search] no DuckDuckGo results for '{}'", query)
        return scraped

    # ------------------------------------------------------------------
    def _ddg_library(self, query: str, limit: int) -> list[Finding]:
        """Search via the ``ddgs`` library (handles the DDG anti-bot)."""
        ddgs_cls = _ddgs_class()
        if ddgs_cls is None:
            return []

        cache_key = f"ddgs text {limit} {query}"
        raw = self.cache.get(cache_key) if self.cache else None
        if raw is None:
            raw = self._ddgs_fetch(ddgs_cls, query, limit)
            if self.cache and raw:
                self.cache.set(cache_key, raw)
        if not raw:
            return []

        findings: list[Finding] = []
        for item in raw:
            title = str(item.get("title") or "").strip()
            href = item.get("href") or item.get("url")
            if not title or not href:
                continue
            findings.append(self.finding(
                title=title,
                detail=(item.get("body") or None),
                url=href,
                confidence=0.6,
                source="ddgs",
                query=query,
            ))
        return findings

    # ------------------------------------------------------------------
    def _ddgs_fetch(self, ddgs_cls: type, query: str,
                    limit: int) -> list[dict[str, Any]]:
        """Call the library and normalise its records (never raises)."""
        proxy = self.settings.http.proxy or None
        timeout = self.settings.http.timeout or 20
        try:
            with ddgs_cls(proxy=proxy, timeout=timeout) as ddgs:
                results = ddgs.text(query, max_results=limit)
        except Exception as exc:  # noqa: BLE001 - library/network errors vary
            logger.debug("[search] ddgs library failed for '{}': {}", query, exc)
            return []
        normalised: list[dict[str, Any]] = []
        for item in results or []:
            if not isinstance(item, dict):
                continue
            normalised.append({
                "title": item.get("title") or "",
                "href": item.get("href") or item.get("url") or "",
                "body": item.get("body") or item.get("snippet") or "",
            })
        return normalised

    # ------------------------------------------------------------------
    def _ddg_scrape(self, query: str, limit: int) -> list[Finding]:
        """Fallback: scrape DuckDuckGo's HTML endpoints directly."""
        findings: list[Finding] = []
        url = DDG_HTML.format(query=quote_plus(query))
        resp = self.cached_get(url)
        if resp is None or resp.status_code != 200:
            # Fall back to the lite endpoint.
            resp = self.cached_get(DDG_LITE.format(query=quote_plus(query)))
        if resp is None or resp.status_code != 200:
            logger.debug("[search] DuckDuckGo HTML scrape blocked")
            return findings

        soup = BeautifulSoup(resp.text, "lxml")
        for result in soup.select(".result, .web-result, tr")[:limit]:
            link = result.select_one("a.result__a, a.result-link, a")
            if not link or not link.get("href"):
                continue
            href = link["href"]
            title = link.get_text(strip=True)
            if not title:
                continue
            snippet_el = result.select_one(".result__snippet, .result-snippet")
            snippet = snippet_el.get_text(strip=True) if snippet_el else None
            findings.append(self.finding(
                title=title, detail=snippet, url=href,
                confidence=0.5, query=query,
            ))
        return findings

    # ------------------------------------------------------------------
    def _serpapi_search(self, query: str, limit: int) -> list[Finding]:
        key = self.settings.api_keys.serpapi
        if not key:
            return []
        from urllib.parse import urlencode
        params = urlencode({"q": query, "api_key": key, "num": limit, "engine": "google"})
        data = self.cached_get_json(f"https://serpapi.com/search.json?{params}")
        if not data:
            return []
        findings = []
        for item in data.get("organic_results", [])[:limit]:
            findings.append(self.finding(
                title=item.get("title", ""),
                detail=item.get("snippet"),
                url=item.get("link"),
                confidence=0.6,
                source="serpapi",
                query=query,
            ))
        return findings

    # ------------------------------------------------------------------
    def run(self, target: str, *, limit: int = 10, extra_queries: list[str] | None = None,
            **kwargs: Any) -> list[Finding]:
        queries = [target]
        if extra_queries:
            queries.extend(extra_queries)

        findings: list[Finding] = []
        seen: set[str] = set()
        for query in queries:
            for f in self._ddg_search(query, limit) + self._serpapi_search(query, limit):
                key = (f.url or "") + f.title
                if key in seen:
                    continue
                seen.add(key)
                findings.append(f)
        logger.info("[search] {} results for '{}'", len(findings), target)
        return findings


__all__ = ["SearchEngine"]
