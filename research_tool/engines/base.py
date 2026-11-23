"""Base class shared by all research engines."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urlencode, urljoin

import requests

from ..config import Settings
from ..logger import logger
from ..models.report import Finding
from ..utils.cache import ResponseCache
from ..utils.proxy import build_session
from ..utils.validators import is_safe_url

# Redirects are followed manually so every hop is re-checked against the SSRF
# guard. The body is capped so a hostile endpoint cannot exhaust memory.
MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 5 * 1024 * 1024

# Query parameters whose values must never be written into a cache key.
_SENSITIVE_PARAMS = {
    "api_key", "apikey", "key", "token", "access_token", "secret",
    "hibp-api-key", "deepl-auth-key", "authorization",
}


def _safe_cache_key(url: str, params: dict[str, Any] | None) -> str:
    """Build a cache key that redacts secret query parameters."""
    if not params:
        return f"GET {url}"
    redacted = {
        name: ("[redacted]" if str(name).lower() in _SENSITIVE_PARAMS else value)
        for name, value in params.items()
    }
    return f"GET {url}?{urlencode(sorted(redacted.items()), doseq=True)}"


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
                   params: dict[str, Any] | None = None,
                   cache_key: str | None = None,
                   max_bytes: int = MAX_RESPONSE_BYTES,
                   **kwargs: Any) -> requests.Response | None:
        """GET with caching. Returns None on failure.

        ``params`` are sent as query parameters and redacted from the cache
        key, so API keys never reach the on-disk cache. ``cache_key`` lets a
        caller supply an explicit, secret-free key.
        """
        timeout = timeout or self.settings.http.timeout
        key = cache_key or _safe_cache_key(url, params)
        if self.cache:
            hit = self.cache.get(key)
            if hit is not None:
                logger.debug("[{}] cache hit {}", self.name, url)
                return _FakeResponse(hit.get("status", 200), hit.get("text", ""))
        # Follow redirects manually: ``requests`` would otherwise follow a
        # ``302 Location: http://169.254.169.254/`` straight past the initial
        # is_safe_url() check (SSRF via redirect).
        current = url
        resp = None
        for _hop in range(MAX_REDIRECTS + 1):
            if not is_safe_url(current, resolve=True):
                logger.warning("[{}] blocked unsafe URL: {}", self.name, current)
                return None
            try:
                resp = self.session.get(current, timeout=timeout,
                                        params=params, allow_redirects=False,
                                        stream=True, **kwargs)
            except requests.RequestException as exc:
                logger.debug("[{}] request failed {}: {}", self.name, current, exc)
                return None
            if not resp.is_redirect:
                break
            location = resp.headers.get("Location", "")
            _close(resp)
            if not location:
                return None
            current = urljoin(current, location)
            params = None          # query params belong to the original request
        else:
            logger.warning("[{}] too many redirects: {}", self.name, url)
            return None
        try:
            raw = resp.raw.read(max_bytes + 1, decode_content=True)
        except Exception:  # noqa: BLE001 - a broken stream counts as a failure
            raw = b""
        finally:
            _close(resp)
        truncated = len(raw) > max_bytes
        text = raw[:max_bytes].decode(resp.encoding or "utf-8", errors="replace")
        capped = _CappedResponse(resp.status_code, text, dict(resp.headers),
                                 current, truncated)
        if self.cache and capped.status_code == 200:
            self.cache.set(key, {"status": capped.status_code, "text": text})
        return capped

    def cached_get_json(self, url: str, *, params: dict[str, Any] | None = None,
                        cache_key: str | None = None,
                        **kwargs: Any) -> Any | None:
        resp = self.cached_get(url, params=params, cache_key=cache_key, **kwargs)
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


def _close(resp: Any) -> None:
    """Best-effort close of a streaming response."""
    try:
        resp.close()
    except Exception:  # noqa: BLE001 - closing is best-effort
        pass


class _FakeResponse:
    """Minimal response object returned from cache hits or capped fetches."""

    def __init__(self, status_code: int, text: str,
                 headers: dict[str, str] | None = None,
                 url: str = "", truncated: bool = False):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self.url = url
        self.truncated = truncated
        self.encoding = "utf-8"
        self.content = text.encode("utf-8", errors="replace")

    def json(self) -> Any:
        import json as _json
        return _json.loads(self.text)


class _CappedResponse(_FakeResponse):
    """Response-like object with a size-capped body and safe metadata."""


__all__ = ["BaseEngine"]
