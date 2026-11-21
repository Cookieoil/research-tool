"""Offline smoke tests for the research toolkit.

Run either with pytest (``python -m pytest tests``) or directly
(``python tests/test_smoke.py``). No network access is required.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Allow running as a plain script from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research_tool.analyzers.link_analyzer import LinkAnalyzer
from research_tool.analyzers.risk_scorer import RiskScorer
from research_tool.config import get_settings
from research_tool.engines import ENGINE_REGISTRY
from research_tool.models.report import Finding, ResearchReport
from research_tool.orchestrator import Orchestrator
from research_tool.reporters import write_report
from research_tool.utils.cache import ResponseCache
from research_tool.utils.validators import (detect_kind, is_domain, is_email,
                                            is_ip, normalise_domain)


def test_validators() -> None:
    assert is_email("a@b.com")
    assert not is_email("nope")
    assert is_domain("example.com")
    assert not is_domain("not a domain")
    assert is_ip("8.8.8.8")
    assert normalise_domain("https://www.Example.com/path") == "example.com"
    assert detect_kind("a@b.com") == "email"
    assert detect_kind("example.com") == "domain"
    assert detect_kind("https://example.com") == "url"
    assert detect_kind("John Smith") == "name"


def test_risk_scorer() -> None:
    empty = ResearchReport(target="x")
    assert RiskScorer.score(empty) == 0

    report = ResearchReport(target="x")
    report.findings = [
        Finding(engine="credential_check", category="credential",
                title="Email risk score: 60/100", confidence=0.8,
                data={"risk_score": 60}),
        Finding(engine="credential_check", category="credential",
                title="Breach: LinkedIn", confidence=0.95),
    ]
    assert RiskScorer.score(report) == 70
    assert RiskScorer.label(70) == "MEDIUM"
    assert RiskScorer.label(0) == "NONE"


def test_link_analyzer() -> None:
    report = ResearchReport(target="x")
    report.findings = [
        Finding(engine="whois", category="domain", title="t1",
                url="https://a.example.com"),
        Finding(engine="whois", category="domain", title="t2",
                url="https://b.example.com"),
    ]
    summary = LinkAnalyzer.summarise(report)
    assert summary["total_findings"] == 2
    assert summary["by_engine"]["whois"] == 2


def test_orchestrator_plan() -> None:
    orch = Orchestrator(get_settings())
    assert "credential_check" in orch.plan("a@b.com")
    assert "whois" in orch.plan("example.com")
    assert orch.plan("example.com", ["whois"]) == ["whois"]
    orch.close()


def test_reports() -> None:
    report = ResearchReport(target="example.com", target_kind="domain",
                            engines_run=["whois"])
    report.findings = [Finding(engine="whois", category="domain",
                               title="Registrar: Example", confidence=0.9)]
    report.summary = "summary"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        for fmt, ext in (("markdown", ".md"), ("json", ".json")):
            path = write_report(report, fmt, out, stem="t")
            assert path.exists() and path.suffix == ext


def test_cache() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cache = ResponseCache(Path(tmp) / "c.db", ttl_seconds=60)
        cache.set("k", {"a": 1})
        assert cache.get("k") == {"a": 1}
        cache.delete("k")
        assert cache.get("k") is None
        cache.close()


def test_registry_complete() -> None:
    expected = {"search", "whois", "domain_intel", "social",
                "credential_check", "academic", "company", "web_scraper",
                "openalex", "orcid", "npi", "dark"}
    assert expected.issubset(set(ENGINE_REGISTRY))


def test_npi_name_parsing() -> None:
    from research_tool.engines.npi import split_name
    assert split_name("John Smith") == ("John", "Smith")
    assert split_name("John Q Smith") == ("John", "Smith")
    assert split_name("Smith, John") == ("John", "Smith")
    assert split_name("Madonna") == (None, "Madonna")


def test_search_engine_prefers_library() -> None:
    """The ``ddgs`` library path wins over the HTML-scrape fallback."""
    import research_tool.engines.search as search_mod
    engine = search_mod.SearchEngine(get_settings())

    lib = [Finding(engine="search", category="web", title="lib")]
    engine._ddg_library = lambda q, n: lib               # type: ignore[method-assign]
    engine._ddg_scrape = lambda q, n: [                  # type: ignore[method-assign]
        Finding(engine="search", category="web", title="scrape")
    ]
    assert engine._ddg_search("q", 5) == lib


def test_search_engine_offline_fallbacks() -> None:
    """Library records are normalised; failures degrade gracefully."""
    import research_tool.engines.search as search_mod
    engine = search_mod.SearchEngine(get_settings())

    class _FakeDDGS:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def text(self, query, **kwargs):  # noqa: ANN001, ANN003
            return [
                {"title": " T1 ", "href": "https://a", "body": "b1"},
                {"title": "", "href": "https://b", "body": "b2"},  # dropped
                "not-a-dict",                                      # dropped
            ]

    # Non-dict records are dropped; dict records are kept verbatim
    # (empty-title filtering happens later, in ``_ddg_library``).
    assert engine._ddgs_fetch(_FakeDDGS, "q", 5) == [
        {"title": " T1 ", "href": "https://a", "body": "b1"},
        {"title": "", "href": "https://b", "body": "b2"},
    ]

    class _BoomDDGS:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise RuntimeError("boom")

    assert engine._ddgs_fetch(_BoomDDGS, "q", 5) == []

    # A missing library means no library findings, not a crash.
    original = search_mod._ddgs_class
    search_mod._ddgs_class = lambda: None                # type: ignore[assignment]
    try:
        assert engine._ddg_library("q", 5) == []
    finally:
        search_mod._ddgs_class = original                 # type: ignore[assignment]


def test_onion_validators() -> None:
    from research_tool.utils.validators import is_onion, normalise_onion

    v3 = "duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion"
    assert is_onion(v3)
    assert is_onion(f"http://{v3}/search")
    assert is_onion(f"https://{v3}:8080/")
    assert not is_onion("example.com")
    assert not is_onion("jane@example.com")
    assert normalise_onion(f"http://{v3}/x?y=1") == v3
    assert detect_kind(v3) == "onion"
    assert detect_kind(f"http://{v3}/") == "onion"


def test_dark_engine_offline() -> None:
    """Dark engine degrades gracefully without a Tor proxy (no network)."""
    from research_tool.engines.dark import DarkEngine

    engine = DarkEngine(get_settings())
    v3 = "duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion"

    # Keyword target, no Tor configured -> informational 'skipped' finding.
    engine._onion_index = lambda: set()          # type: ignore[method-assign]
    keyword = engine.run("ransomware")
    assert any(f.data.get("status") == "skipped" for f in keyword)
    assert all(f.category == "darkweb" for f in keyword)

    # Onion target: address recognised + membership check (injected index).
    engine._onion_index = lambda: {v3}           # type: ignore[method-assign]
    onion = engine.run(v3)
    assert any(f.data.get("onion") == v3 for f in onion)
    assert any(f.data.get("indexed") is True for f in onion)

    # Scrape path degrades cleanly when the page cannot be fetched.
    engine._raw_get = lambda url, timeout=None, **kw: None   # type: ignore[method-assign]
    scraped = engine._scrape_onion(f"http://{v3}/")
    assert scraped[0].data.get("reachable") is False


def test_detect_tor_proxy() -> None:
    """A configured proxy wins; otherwise local ports are probed."""
    from research_tool.engines import dark as dark_mod

    settings = get_settings()
    original_proxy = settings.http.proxy
    try:
        settings.http.proxy = "socks5h://127.0.0.1:9999"
        assert dark_mod.detect_tor_proxy(settings) == "socks5h://127.0.0.1:9999"

        settings.http.proxy = None
        original_open = dark_mod._proxy_port_open
        dark_mod._proxy_port_open = lambda proxy, timeout=0.5: False
        try:
            assert dark_mod.detect_tor_proxy(settings) is None
        finally:
            dark_mod._proxy_port_open = original_open
    finally:
        settings.http.proxy = original_proxy


def test_social_engine_offline() -> None:
    """Names are not handles and soft-404 pages are suppressed (no network)."""
    from research_tool.engines.social import PLATFORMS, SocialEngine

    settings = get_settings()

    class _Resp:
        def __init__(self, text: str, status: int = 200):
            self.text = text
            self.status_code = status

    class _Session:
        def __init__(self, text: str, status: int = 200):
            self.headers: dict = {}
            self._text = text
            self._status = status

        def get(self, url, **kwargs):  # noqa: ANN001, ANN003
            return _Resp(self._text, self._status)

    # A display name (with a space) is not a username -> one 'skipped' finding.
    skipped = SocialEngine(settings).run("Fei-Fei Li")
    assert len(skipped) == 1 and skipped[0].data.get("status") == "skipped"

    # A 200 that is really a soft-404 is suppressed for that platform...
    soft = SocialEngine(settings, session=_Session("page not found"))
    assert soft._check("github", PLATFORMS["github"], "someone") is None
    # ...while an ordinary 200 is reported.
    clean = SocialEngine(settings, session=_Session("<html>profile</html>"))
    assert clean._check("github", PLATFORMS["github"], "someone") is not None
    # Every platform is reported when the body looks like a real profile.
    found = clean.run("someone")
    assert len(found) == len(PLATFORMS)
    assert all(f.engine == "social" for f in found)


def test_cli_force_utf8_stdio() -> None:
    """The CLI forces UTF-8 stdio so non-ASCII output cannot crash it."""
    import io

    from research_tool.cli import _force_utf8_stdio

    buf = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    _force_utf8_stdio(buf)
    assert buf.encoding.lower().replace("-", "") == "utf8"
    # A non-ASCII hyphen (U+2010) would raise under cp1252; now it encodes.
    buf.write("\u2010")
    buf.flush()


def _run_all() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
