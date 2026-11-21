"""Base class shared by all research engines."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import requests

from ..config import Settings
from ..logger import logger
from ..models.report import Finding
from ..utils.cache import ResponseCache
from ..utils.proxy import build_session


class BaseEngine(ABC):
    """Common plumbing: HTTP session, cache and Finding helpers.

    Subclasses implement :meth:`run` and should call :meth:`cached_get`
    for network access so results are transparently cached.
    """

    name: str = "base"
    category: str = "general"

    def __init__(self, settings: Settings, session: requests.Session | None = None,
                 cache: ResponseCache | None = None):
        self.settings = settings
        self.session = session or build_session(settings)
        self.cache = cache

    # ------------------------------------------------------------------
    # Networking
    # ------------------------------------------------------------------
    def cached_get(self, url: str, *, timeout: int | None = None,
                   **kwargs: Any) -> requests.Response | None:
        """GET with caching. Returns None on failure."""
        timeout = timeout or self.settings.http.timeout
        cache_key = f"GET {url}"
        if self.cache:
            hit = self.cache.get(cache_key)
            if hit is not None:
                logger.debug("[{}] cache hit {}", self.name, url)
                return _FakeResponse(hit.get("status", 200), hit.get("text", ""))
        try:
            resp = self.session.get(url, timeout=timeout, **kwargs)
        except requests.RequestException as exc:
            logger.debug("[{}] request failed {}: {}", self.name, url, exc)
            return None
        if self.cache and resp.status_code == 200:
            self.cache.set(cache_key, {"status": resp.status_code, "text": resp.text})
        return resp

    def cached_get_json(self, url: str, **kwargs: Any) -> Any | None:
        resp = self.cached_get(url, **kwargs)
        if resp is None:
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    def render_html(self, url: str, *, timeout_ms: int = 20000) -> str | None:
        """Render *url* with a headless browser, or ``None`` when unavailable.

        The bypass for JS-challenged / JS-rendered pages. Requires
        ``http.render_js: true`` and the optional Playwright package; returns
        ``None`` (never raises) otherwise, so callers can fall back to plain
        HTTP. The rendered page is cached like any other response.
        """
        if not getattr(self.settings.http, "render_js", False):
            return None
        from ..utils.proxy import browser_user_agent, render_html
        cache_key = f"RENDER {url}"
        if self.cache:
            hit = self.cache.get(cache_key)
            if hit is not None:
                return hit.get("html")
        logger.debug("[{}] rendering {} with Playwright", self.name, url)
        html = render_html(url, proxy=self.settings.http.proxy,
                           user_agent=browser_user_agent(), timeout_ms=timeout_ms)
        if self.cache and html:
            self.cache.set(cache_key, {"html": html})
        return html

    # ------------------------------------------------------------------
    # Findings
    # ------------------------------------------------------------------
    def finding(self, title: str, *, detail: str | None = None,
                url: str | None = None, confidence: float = 0.5,
                category: str | None = None, **data: Any) -> Finding:
        return Finding(
            engine=self.name,
            category=category or self.category,
            title=title,
            detail=detail,
            url=url,
            confidence=confidence,
            data=data,
        )

    # ------------------------------------------------------------------
    @abstractmethod
    def run(self, target: str, **kwargs: Any) -> list[Finding]:
        """Analyse *target* and return a list of Findings."""
        raise NotImplementedError


class _FakeResponse:
    """Minimal response object returned from cache hits."""

    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text

    def json(self) -> Any:
        import json as _json
        return _json.loads(self.text)


__all__ = ["BaseEngine"]
