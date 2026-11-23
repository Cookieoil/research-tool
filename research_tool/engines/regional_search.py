"""Regional / cross-border search engine.

Reaches search indices that matter outside the anglophone web, so a target
can be researched in the language and jurisdiction where it actually lives
(essential for restricted regions such as the DPRK, China, Russia, Iran):

  * **Baidu** (China, ``zh``)
  * **Naver** (South Korea, ``ko``)
  * **Yandex** (Russia / CIS, ``ru``)
  * **SearXNG** public instances (meta-search; also reachable over Tor)

Each source is queried in its own language: the target is translated (and,
for non-Latin input, romanised) via :mod:`research_tool.utils.i18n` before
the request, and non-Latin result titles are translated back to English for
the report. Every step degrades gracefully - a blocked or missing source
simply yields no findings instead of failing the run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from ..logger import logger
from ..models.report import Finding
from ..utils.i18n import (QueryVariant, detect_script, generate_query_variants,
                          translator_from_settings)
from ..utils.proxy import (mobile_user_agent, proxy_rotator_from_settings,
                           renew_tor_circuit, set_session_proxy)
from .base import BaseEngine


@dataclass(frozen=True)
class RegionalSource:
    """A regional search endpoint and how to parse its result page."""

    key: str
    name: str
    region: str
    language: str
    url_template: str
    parser: str                       # "baidu" | "naver" | "yandex" | "searx"
    mobile: bool = False              # send a mobile User-Agent
    engine_label: str = "regional_search"


# Per-source request templates. ``{query}`` and ``{limit}`` are substituted.
# Baidu/Naver use their **mobile** endpoints (m.*), which serve plain HTML and
# are far less likely to present a JS bot-challenge than the desktop sites.
REGIONAL_SOURCES: dict[str, RegionalSource] = {
    "baidu": RegionalSource(
        key="baidu", name="Baidu", region="cn", language="zh-CN",
        url_template="https://m.baidu.com/s?word={query}&rn={limit}",
        parser="baidu", mobile=True,
    ),
    "naver": RegionalSource(
        key="naver", name="Naver", region="kr", language="ko",
        url_template="https://m.search.naver.com/search.naver?query={query}&count={limit}",
        parser="naver", mobile=True,
    ),
    "yandex": RegionalSource(
        key="yandex", name="Yandex", region="ru", language="ru",
        url_template="https://yandex.com/search/?text={query}",
        parser="yandex", mobile=True,
    ),
    "searx": RegionalSource(
        key="searx", name="SearXNG", region="global", language="en",
        url_template="{base}/search?q={query}&format=json",
        parser="searx",
    ),
}

# SerpAPI engine ids for the regional sources (used as a clean fallback when
# direct scraping is blocked and a RESEARCH_SERPAPI_KEY is configured).
_SERPAPI_ENGINES: dict[str, str] = {
    "baidu": "baidu", "naver": "naver", "yandex": "yandex",
}

# Region alias -> source key(s), so ``--region kr`` selects Naver etc.
REGION_ALIASES: dict[str, list[str]] = {
    "cn": ["baidu"], "china": ["baidu"],
    "kr": ["naver"], "korea": ["naver"],
    "ru": ["yandex"], "russia": ["yandex"],
    "global": ["searx"],
}

# Default public SearXNG instances (JSON API). Many instances disable the
# JSON API; those that fail are skipped silently.
DEFAULT_SEARX_INSTANCES: list[str] = [
    "https://searx.be",
    "https://search.bus-hit.me",
    "https://searxng.site",
    "https://priv.au",
]

# CSS selectors tried in order when harvesting result anchors. Both desktop
# and mobile markups are covered so a source keeps working across layouts.
_PARSER_SELECTORS: dict[str, list[str]] = {
    "baidu": [
        "div.result.c-container h3.t a",
        "div.result h3.t a",
        "h3.t a",
        "div.result h3 a",
        # mobile (m.baidu.com)
        "div.c-result a.c-title",
        "div.c-container a.c-title",
        "a.c-title",
        "div.c-result h3 a",
    ],
    "naver": [
        "a.link_tit",
        "a.total_tit",
        "ul.lst_total a",
        "div.total_area a.total_tit",
        ".api_txt_lines.total_tit",
        # mobile (m.search.naver.com)
        "li.bx a",
        "a.api_txt_lines",
    ],
    "yandex": [
        "li.serp-item a.OrganicTitle-Link",
        "a.organic__url",
        "li.serp-item h2 a",
        "a.Link_theme_normal",
        "a.serp-item__title-link",
        "li.serp-item a",
    ],
    # SearXNG HTML fallback (used when an instance disables the JSON API).
    "searx": [
        "article.result h3 a",
        "div.result h3 a",
        ".result .result_header a",
        ".result h3 a",
        "h3 a",
    ],
}

_SNIPPET_SELECTORS: dict[str, list[str]] = {
    "baidu": ["div.c-abstract", "span.content-right_8Zs40", "div.c-span-last",
              "div.c-abstract-wrap"],
    "naver": ["a.link_tit + .dsc_txt", "span.dsc_txt", "div.total_dsc",
              ".api_txt_lines + .dsc_txt"],
    "yandex": ["div.OrganicTextContentSpan", "span.OrganicTextContentSpan",
               "div.text-container"],
    "searx": ["p.content", ".result .content", ".result_content"],
}

# Cap how many non-Latin result titles we machine-translate back to English.
_TRANSLATE_CAP = 12

# Markers that a response is really a bot-challenge / captcha wall rather than
# a result page. When one is seen the source is flagged so the caller can
# advise routing through Tor / a proxy (which defeats IP-based blocking).
_BLOCK_MARKERS = (
    "wappass.baidu.com", "captcha", "verify", "verification", "\u9a8c\u8bc1",
    "unusual traffic", "are you a robot", "robot check", "security check",
    "cf-challenge", "just a moment", "access denied",
)

# Challenge *endpoints*: reliable when they appear in the response URL (e.g. a
# redirect to wappass, or an /antibot wall).
_STRONG_URL_MARKERS = (
    "antibot", "/captcha", "wappass", "geo.captcha-delivery.com",
    "challenge-platform", "px-captcha",
)
# Specific, unambiguous challenge phrases - safe to search across the *whole*
# body. A bare "captcha" must NOT be (ordinary result pages link to a captcha
# help page in their chrome), but these phrases only appear on a real wall,
# some of which keep their markers past the first few KB.
_STRONG_TEXT_MARKERS = (
    "solve an image challenge", "image challenge", "\uc774\ubbf8\uc9c0 \ucc4c\ub9b0\uc9c0",
    "\uc790\ub3d9\uc785\ub825 \ubc29\uc9c0", "\ub85c\ubd07\uc774 \uc544\ub2d9\ub2c8\ub2e4",
    "verify you are human", "checking your browser before accessing",
    "please complete the security check",
)

# Href prefixes/substrings that mark navigation / utility / challenge links
# rather than search results (shared by every parser path).
_SKIP_HREF_PREFIXES = ("javascript:", "#", "mailto:", "tel:", "void(", "?")
_SKIP_HREF_SUBSTR = ("/login", "/signin", "/signup", "/register", "/privacy",
                     "/terms", "/cookie", "/help", "/about", "/settings",
                     "/support", ".help.", "/antibot", "/captcha",
                     # search-engine internal navigation (never a result)
                     "search.naver?", "keep.naver.com", "shopping.naver.com")


def _is_skip_href(href: str) -> bool:
    """True when *href* is navigation / utility / challenge, not a result."""
    low = href.lower()
    return (low.startswith(_SKIP_HREF_PREFIXES)
            or any(s in low for s in _SKIP_HREF_SUBSTR))


class RegionalSearchEngine(BaseEngine):
    """Search regional (non-anglophone) web indices for a target."""

    name = "regional_search"
    category = "web"

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._translator = translator_from_settings(self.settings, self.session, self.cache)
        self._rotator = None
        self._current_proxy = self.settings.http.proxy

    # ------------------------------------------------------------------
    # Exit-IP rotation (bypass for IP-based captchas)
    # ------------------------------------------------------------------
    def _get_rotator(self):
        if self._rotator is None:
            self._rotator = proxy_rotator_from_settings(self.settings)
        return self._rotator

    def _rotation_budget(self) -> int:
        """How many times we may switch exit IP for one request."""
        rotator = self._get_rotator()
        if len(rotator) > 0:
            return min(max(len(rotator), 2), 5)
        if getattr(self.settings.http, "tor_control_port", None):
            return 3
        return 0

    def _rotate(self) -> bool:
        """Switch to a fresh exit IP. Returns True when a rotation happened."""
        rotator = self._get_rotator()
        if len(rotator) > 0:
            rotator.retire(self._current_proxy)
            nxt = rotator.next()
            if nxt:
                set_session_proxy(self.session, nxt)
                self._current_proxy = nxt
                logger.info("[regional_search] rotated to proxy {}", nxt)
                return True
        port = getattr(self.settings.http, "tor_control_port", None)
        if port and renew_tor_circuit(
                port, getattr(self.settings.http, "tor_control_password", None)):
            return True
        return False

    # ------------------------------------------------------------------
    # Query construction (language-aware)
    # ------------------------------------------------------------------
    def _target_languages(self) -> list[str]:
        cfg = getattr(self.settings, "i18n", None)
        langs = getattr(cfg, "target_languages", None) if cfg else None
        return list(langs) if langs else ["ko", "zh-CN", "ru", "ar", "fa"]

    def _variant_for(self, target: str, language: str) -> QueryVariant:
        """Pick the best query variant for *language* (translated or original)."""
        variants = generate_query_variants(
            target, [language], self._translator,
        )
        want = language.split("-")[0].lower()
        for v in variants:
            if v.method == "translated" and v.language.split("-")[0].lower() == want:
                return v
        # No translation available - prefer a same-language original, else the
        # romanised form, else the raw target.
        for v in variants:
            if v.language.split("-")[0].lower() == want:
                return v
        for v in variants:
            if v.method == "romanized":
                return v
        return variants[0]

    def _translate_back(self, text: str) -> str | None:
        if not self._translator or not text:
            return None
        if detect_script(text) in ("latin", "unknown"):
            return None
        return self._translator.translate(text, target="en")

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    def _extract_results(self, html: str, parser: str,
                         limit: int) -> list[tuple[str, str, str | None]]:
        soup = BeautifulSoup(html, "lxml")
        anchors: list[Any] = []
        for selector in _PARSER_SELECTORS.get(parser, []):
            anchors = soup.select(selector)
            if anchors:
                break

        results: list[tuple[str, str, str | None]] = []
        seen: set[str] = set()
        for anchor in anchors:
            href = (anchor.get("href") or "").strip()
            title = anchor.get_text(" ", strip=True)
            if not href or not title or href in seen or _is_skip_href(href):
                continue
            seen.add(href)
            snippet: str | None = None
            container = anchor.find_parent(["div", "li"])
            if container is not None:
                for ssel in _SNIPPET_SELECTORS.get(parser, []):
                    node = container.select_one(ssel)
                    if node is not None:
                        snippet = node.get_text(" ", strip=True) or None
                        break
            results.append((title, href, snippet))
            if len(results) >= limit:
                break
        if not results:
            # All specific selectors failed (layout changed) - fall back to a
            # heuristic harvest so a redesign doesn't zero out the source.
            results = self._generic_results(soup, limit)
        return results

    @staticmethod
    def _generic_results(soup: Any,
                         limit: int) -> list[tuple[str, str, str | None]]:
        """Last-resort: harvest plausible result anchors from any page.

        Filters out navigation/utility/JS links and keeps anchors that look
        like search results (external-looking href, sensible title length).
        """
        results: list[tuple[str, str, str | None]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = (anchor.get("href") or "").strip()
            title = anchor.get_text(" ", strip=True)
            if not href or href in seen or not title:
                continue
            if _is_skip_href(href):
                continue
            if not (6 <= len(title) <= 200):
                continue
            seen.add(href)
            results.append((title, href, None))
            if len(results) >= limit:
                break
        return results

    def _findings_from(self, source: RegionalSource, variant: QueryVariant,
                       results: list[tuple[str, str, str | None]],
                       translate_results: bool) -> list[Finding]:
        findings: list[Finding] = []
        translated_budget = _TRANSLATE_CAP if translate_results else 0
        for title, href, snippet in results:
            data: dict[str, Any] = {
                "source": source.key,
                "region": source.region,
                "language": source.language,
                "query": variant.text,
                "query_method": variant.method,
                "original_title": title,
            }
            if snippet:
                data["snippet"] = snippet
            display_title = title
            if translated_budget > 0:
                back = self._translate_back(title)
                if back:
                    data["translated_title"] = back
                    display_title = f"{back} [{title}]"
                    translated_budget -= 1
            findings.append(self.finding(
                title=display_title, detail=snippet, url=href,
                confidence=0.5, category="web", **data,
            ))
        return findings

    # ------------------------------------------------------------------
    # Source selection
    # ------------------------------------------------------------------
    def _searx_instances(self) -> list[str]:
        cfg = getattr(self.settings, "regional_search", None)
        instances = getattr(cfg, "searx_instances", None) if cfg else None
        return list(instances) if instances else list(DEFAULT_SEARX_INSTANCES)

    def _select_sources(self, region: str | None,
                        sources: list[str] | None) -> list[str]:
        if sources:
            return [s.strip().lower() for s in sources
                    if s.strip().lower() in REGIONAL_SOURCES]
        if region:
            keys = REGION_ALIASES.get(region.strip().lower(), [])
            if not keys:
                logger.warning("[regional_search] unknown region '{}'", region)
            return keys
        return list(REGIONAL_SOURCES.keys())

    # ------------------------------------------------------------------
    # Per-source execution
    # ------------------------------------------------------------------
    @staticmethod
    def _looks_blocked(resp: Any) -> bool:
        """True when a response is a bot-challenge / captcha wall."""
        if resp is None:
            return False
        url = (getattr(resp, "url", "") or "").lower()
        body = (getattr(resp, "text", "") or "").lower()
        if any(m in url for m in _BLOCK_MARKERS + _STRONG_URL_MARKERS):
            return True
        if any(m in body for m in _STRONG_TEXT_MARKERS):
            return True
        return any(m in body[:4000] for m in _BLOCK_MARKERS)

    def _serpapi(self, source: RegionalSource, variant: QueryVariant,
                 limit: int) -> list[tuple[str, str, str | None]]:
        """Query the same regional engine through SerpAPI (needs a key)."""
        key = self.settings.api_keys.serpapi
        engine = _SERPAPI_ENGINES.get(source.key)
        if not key or not engine:
            return []
        data = self.cached_get_json(
            "https://serpapi.com/search.json",
            params={"q": variant.text, "api_key": key,
                    "num": limit, "engine": engine},
        )
        if not data or not isinstance(data, dict):
            return []
        results: list[tuple[str, str, str | None]] = []
        for item in (data.get("organic_results") or [])[:limit]:
            title = (item.get("title") or "").strip()
            href = (item.get("link") or "").strip()
            if title and href:
                results.append((title, href, item.get("snippet") or None))
        return results

    def _fetch_results(self, source: RegionalSource, variant: QueryVariant,
                       limit: int) -> tuple[list[tuple[str, str, str | None]], bool]:
        """Fetch + parse results. Returns ``(results, blocked)``.

        Escalation ladder:

          1. plain HTTP (mobile UA for ``m.*`` endpoints), **rotating the exit
             IP** (proxy pool / Tor circuit) whenever a captcha or network
             error is seen - the bypass for IP-based blocking;
          2. a headless-browser render (when ``http.render_js`` is enabled);
          3. SerpAPI for the same engine (when a SerpAPI key is configured).

        ``blocked`` is True when a captcha / bot-challenge was served.
        """
        url = source.url_template.format(
            query=quote_plus(variant.text), limit=limit)
        blocked = False
        rotations = self._rotation_budget()
        while True:
            headers = ({"User-Agent": mobile_user_agent()}
                       if source.mobile else None)
            resp = self.cached_get(url, headers=headers)
            if resp is None:
                if rotations > 0 and self._rotate():
                    rotations -= 1
                    continue
                logger.debug("[regional_search] {} unreachable for '{}'",
                             source.key, url)
                break
            if resp.status_code != 200:
                logger.debug("[regional_search] {} HTTP {} for '{}'",
                             source.key, resp.status_code, url)
                break
            if self._looks_blocked(resp):
                blocked = True
                # Never cache a captcha page - it would mask a working retry
                # (e.g. after switching exit IP) for the whole cache TTL.
                if self.cache:
                    self.cache.delete(f"GET {url}")
                if rotations > 0 and self._rotate():
                    rotations -= 1
                    continue
                logger.warning(
                    "[regional_search] {} served a bot-challenge/captcha; set "
                    "http.proxy_pool or http.tor_control_port, or use --tor / "
                    "RESEARCH_HTTP_PROXY.", source.key)
                break
            results = self._extract_results(resp.text, source.parser, limit)
            if results:
                return results, False
            break

        # Escalate to a real browser (defeats JS challenges).
        html = self.render_html(url)
        if html:
            results = self._extract_results(html, source.parser, limit)
            if results:
                logger.debug("[regional_search] {} rendered via browser",
                             source.key)
                return results, False

        # Escalate to SerpAPI (clean and reliable; needs a key).
        results = self._serpapi(source, variant, limit)
        if results:
            logger.debug("[regional_search] {} via SerpAPI", source.key)
            return results, False

        return [], blocked

    def _run_source(self, source: RegionalSource, target: str, limit: int,
                    translate_results: bool) -> tuple[list[Finding], bool]:
        variant = self._variant_for(target, source.language)
        if source.parser == "searx":
            return self._run_searx(source, variant, limit, translate_results), False
        results, blocked = self._fetch_results(source, variant, limit)
        return (self._findings_from(source, variant, results, translate_results),
                blocked)

    @staticmethod
    def _searx_json_results(data: Any,
                            limit: int) -> list[tuple[str, str, str | None]]:
        if not data or not isinstance(data, dict):
            return []
        results: list[tuple[str, str, str | None]] = []
        for item in (data.get("results") or [])[:limit]:
            title = (item.get("title") or "").strip()
            href = (item.get("url") or "").strip()
            if title and href:
                results.append((title, href, item.get("content") or None))
        return results

    def _run_searx(self, source: RegionalSource, variant: QueryVariant,
                   limit: int, translate_results: bool) -> list[Finding]:
        """Query SearXNG instances via the JSON API, then HTML as a fallback."""
        findings: list[Finding] = []
        query = quote_plus(variant.text)
        for instance in self._searx_instances():
            base = instance.rstrip("/")
            # 1. JSON API (disabled on many public instances).
            data = self.cached_get_json(
                source.url_template.format(base=base, query=query, limit=limit))
            results = self._searx_json_results(data, limit)
            # 2. HTML fallback (then a browser render if still empty).
            if not results:
                html = self._fetch_html(f"{base}/search?q={query}")
                if html:
                    results = self._extract_results(html, "searx", limit)
            if results:
                findings.extend(self._findings_from(
                    source, variant, results, translate_results))
                break
        return findings

    def _fetch_html(self, url: str) -> str | None:
        resp = self.cached_get(url)
        if resp is not None and resp.status_code == 200:
            return resp.text
        return self.render_html(url)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def run(self, target: str, *, region: str | None = None,
            sources: list[str] | None = None, limit: int = 10,
            translate_results: bool = True, **kwargs: Any) -> list[Finding]:
        """Query regional search indices for *target*.

        ``region`` selects a jurisdiction alias (``cn``/``kr``/``ru``/
        ``global``); ``sources`` selects engines explicitly
        (``baidu``/``naver``/``yandex``/``searx``). With neither, all
        sources are queried.
        """
        target = (target or "").strip()
        if not target:
            return []
        keys = self._select_sources(region, sources)
        if not keys:
            return [self.finding(
                title="No regional source selected",
                detail="Pass a known --region or --sources value.",
                confidence=0.2, status="skipped",
            )]
        findings: list[Finding] = []
        blocked_any = False
        for key in keys:
            source = REGIONAL_SOURCES[key]
            try:
                got, blocked = self._run_source(
                    source, target, limit, translate_results)
            except Exception as exc:  # noqa: BLE001 - isolate per source
                logger.debug("[regional_search] {} failed: {}", key, exc)
                continue
            findings.extend(got)
            blocked_any = blocked_any or blocked
        if not findings:
            if blocked_any:
                detail = ("At least one regional source served a bot-challenge "
                          "(captcha). Re-run through Tor or a proxy "
                          "(--tor / RESEARCH_HTTP_PROXY), or set "
                          "http.render_js: true for a real browser.")
                status = "blocked"
            else:
                detail = "Regional sources returned nothing or were unreachable."
                status = "not_found"
            findings.append(self.finding(
                title=f"No regional results for '{target}'",
                detail=detail, confidence=0.3, status=status,
            ))
        logger.info("[regional_search] {} findings for '{}'",
                    len(findings), target)
        return findings


__all__ = [
    "RegionalSearchEngine", "RegionalSource",
    "REGIONAL_SOURCES", "REGION_ALIASES", "DEFAULT_SEARX_INSTANCES",
]
