"""HTTP client factory with optional proxy / Tor routing.

Also provides User-Agent rotation (to reduce bot-fingerprinting on regional
indices such as Baidu/Naver/Yandex) and an optional headless-browser
renderer (Playwright) for JS-heavy or bot-challenged pages.
"""

from __future__ import annotations

import random
from typing import Any, Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..logger import logger

# A small pool of realistic browser User-Agent strings. Rotating these
# reduces bot-fingerprinting on regional indices.
_BROWSER_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
]

# Mobile UAs - regional search uses these against mobile endpoints
# (m.baidu.com / m.search.naver.com), which serve plain HTML.
_MOBILE_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
]


def browser_user_agent() -> str:
    """A random desktop browser User-Agent."""
    return random.choice(_BROWSER_USER_AGENTS)


def mobile_user_agent() -> str:
    """A random mobile browser User-Agent."""
    return random.choice(_MOBILE_USER_AGENTS)


def pick_user_agent(settings: Any) -> str:
    """The User-Agent to use, honouring the ``http.user_agent_rotation`` flag."""
    cfg = settings.http
    if getattr(cfg, "user_agent_rotation", False):
        return browser_user_agent()
    return cfg.user_agent


# --------------------------------------------------------------------------
# Proxy rotation
# --------------------------------------------------------------------------
# Public, frequently-updated proxy lists (plain "host:port" per line).
_FREE_PROXY_SOURCES: tuple[tuple[str, str], ...] = (
    ("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
     "http"),
    ("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
     "socks5h"),
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
     "http"),
)


def fetch_free_proxies(*, timeout: int = 15, limit: int = 200) -> list[str]:
    """Harvest a pool of public proxy URLs from well-known GitHub lists.

    Best-effort: public proxies are unreliable by nature, so this is opt-in
    (``http.proxy_pool_auto``) and simply returns ``[]`` on any failure.
    """
    proxies: list[str] = []
    for url, scheme in _FREE_PROXY_SOURCES:
        try:
            resp = requests.get(url, timeout=timeout)
        except requests.RequestException as exc:
            logger.debug("free-proxy list {} failed: {}", url, exc)
            continue
        if resp.status_code != 200:
            continue
        for line in resp.text.splitlines():
            line = line.strip()
            if line and ":" in line and " " not in line:
                proxies.append(f"{scheme}://{line}")
        if len(proxies) >= limit:
            break
    unique = list(dict.fromkeys(proxies))
    logger.info("harvested {} free proxies", len(unique))
    return unique[:limit]


class ProxyRotator:
    """Rotates outbound requests across a pool of proxy URLs.

    A proxy that yields a block/challenge is retired so the next attempt uses
    a different exit IP - the practical bypass for IP-based captchas.
    """

    def __init__(self, proxies: Iterable[str] | None = None):
        self._proxies: list[str] = list(dict.fromkeys(
            p for p in (proxies or []) if p))
        self._dead: set[str] = set()
        self._index = 0

    def __bool__(self) -> bool:
        return bool(self.alive)

    def __len__(self) -> int:
        return len(self.alive)

    @property
    def alive(self) -> list[str]:
        return [p for p in self._proxies if p not in self._dead]

    def next(self) -> str | None:
        alive = self.alive
        if not alive:
            return None
        proxy = alive[self._index % len(alive)]
        self._index += 1
        return proxy

    def retire(self, proxy: str | None) -> None:
        if proxy:
            self._dead.add(proxy)

    def add(self, proxies: Iterable[str]) -> None:
        for p in proxies:
            if p and p not in self._proxies:
                self._proxies.append(p)


def proxy_rotator_from_settings(settings: Any) -> ProxyRotator:
    """Build a :class:`ProxyRotator` from the ``http`` config."""
    cfg = settings.http
    pool = list(getattr(cfg, "proxy_pool", None) or [])
    if getattr(cfg, "proxy_pool_auto", False):
        pool.extend(fetch_free_proxies())
    return ProxyRotator(pool)


def set_session_proxy(session: requests.Session, proxy: str | None) -> None:
    """Point *session* at *proxy* (or clear it when ``proxy`` is falsy)."""
    session.proxies = {}
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})


def renew_tor_circuit(port: int = 9051, password: str | None = None,
                      controller: str = "127.0.0.1") -> bool:
    """Ask a local Tor daemon for a fresh circuit (SIGNAL NEWNYM).

    Requires the optional ``stem`` package and a control port; returns
    ``False`` (never raises) when unavailable.
    """
    try:
        from stem import Signal
        from stem.control import Controller
    except ImportError:
        logger.debug("stem not installed; cannot renew Tor circuit")
        return False
    try:
        with Controller.from_port(address=controller, port=port) as ctl:
            if password:
                ctl.authenticate(password=password)
            else:
                ctl.authenticate()
            ctl.signal(Signal.NEWNYM)
        logger.info("Tor circuit renewed (NEWNYM)")
        return True
    except Exception as exc:  # noqa: BLE001 - stem raises many types
        logger.debug("Tor circuit renewal failed: {}", exc)
        return False


def build_session(settings: Any, *, proxy: str | None = None) -> requests.Session:
    """Create a requests Session honouring the HTTP config section.

    Supports an optional SOCKS/Tor proxy (requires ``requests[socks]``).
    ``proxy`` overrides the configured ``http.proxy`` for this session.
    """
    http_cfg = settings.http
    session = requests.Session()

    retry = Retry(
        total=http_cfg.retries,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD", "POST"}),
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    session.headers.update({"User-Agent": pick_user_agent(settings)})

    effective = proxy or http_cfg.proxy
    if effective:
        session.proxies.update({"http": effective, "https": effective})
        logger.info("Outbound proxy configured: {}", effective)

    session.verify = http_cfg.verify_ssl
    return session


def build_mobile_session(settings: Any) -> requests.Session:
    """A session whose User-Agent is a mobile browser.

    Used for mobile regional endpoints (``m.baidu.com`` /
    ``m.search.naver.com``) that serve plain, JS-free HTML.
    """
    session = build_session(settings)
    session.headers.update({"User-Agent": mobile_user_agent()})
    return session


def render_html(url: str, *, proxy: str | None = None,
                user_agent: str | None = None,
                timeout_ms: int = 20000) -> str | None:
    """Render *url* with headless Chromium via Playwright.

    Returns the fully-rendered HTML, or ``None`` when Playwright (or its
    browser) is not installed, or the page cannot be loaded. This is the
    bypass for JS-challenged / JS-rendered pages; it is entirely optional
    and never raises.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.debug("playwright not installed; JS rendering unavailable")
        return None
    try:
        with sync_playwright() as p:
            launch_kwargs: dict[str, Any] = {"headless": True}
            if proxy:
                launch_kwargs["proxy"] = {"server": proxy}
            browser = p.chromium.launch(**launch_kwargs)
            try:
                context = (browser.new_context(user_agent=user_agent)
                           if user_agent else browser.new_context())
                page = context.new_page()
                page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                return page.content()
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 - playwright raises many types
        logger.debug("playwright render failed for {}: {}", url, exc)
        return None


def safe_get(session: requests.Session, url: str, *, timeout: int = 20,
             **kwargs: Any) -> requests.Response | None:
    """GET a URL, returning None instead of raising on network errors."""
    try:
        return session.get(url, timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        logger.debug("Request failed for {}: {}", url, exc)
        return None


__all__ = [
    "build_session", "build_mobile_session", "safe_get", "render_html",
    "pick_user_agent", "browser_user_agent", "mobile_user_agent",
    "ProxyRotator", "proxy_rotator_from_settings", "fetch_free_proxies",
    "set_session_proxy", "renew_tor_circuit",
]
