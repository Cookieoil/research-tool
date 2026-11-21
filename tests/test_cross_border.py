"""Offline tests for the cross-border / restricted-region capabilities.

Run either with pytest (``python -m pytest tests``) or directly
(``python tests/test_cross_border.py``). No network access is required -
all HTTP is stubbed and every parser is fed local fixtures.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running as a plain script from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research_tool.config import get_settings
from research_tool.engines import ENGINE_REGISTRY
from research_tool.engines.regional_search import (REGION_ALIASES,
                                                   RegionalSearchEngine)
from research_tool.engines.regional_social import (REGIONAL_PLATFORMS,
                                                   RegionalSocialEngine)
from research_tool.engines.sanctions import (SanctionsEngine, parse_eu,
                                             parse_ofac, parse_uk, parse_un)
from research_tool.orchestrator import Orchestrator
from research_tool.utils.i18n import (Translator, detect_language,
                                      detect_script, generate_query_variants,
                                      normalize_text, romanize)


# --------------------------------------------------------------------------
# Stubs
# --------------------------------------------------------------------------
class _Resp:
    def __init__(self, text: str = "", status: int = 200,
                 payload: dict | None = None):
        self.text = text
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload if self._payload is not None else json.loads(self.text)


class _FakeSession:
    """Session returning a fixed payload for GET and POST."""

    def __init__(self, payload: dict, status: int = 200):
        self.headers: dict = {}
        self._payload = payload
        self._status = status

    def get(self, url, **kwargs):
        return _Resp(payload=self._payload, status=self._status)

    def post(self, url, **kwargs):
        return _Resp(payload=self._payload, status=self._status)


# --------------------------------------------------------------------------
# i18n
# --------------------------------------------------------------------------
def test_i18n_script_and_language() -> None:
    assert detect_script("\uae40\uc815\uc740") == "hangul"      # 김정은
    assert detect_script("\u4e2d\u56fd") == "han"              # 中国
    assert detect_script("\u0412\u043b\u0430\u0434\u0438\u043c\u0438\u0440") == "cyrillic"
    assert detect_script("\u0645\u062d\u0645\u062f") == "arabic"  # محمد
    assert detect_script("Kim Jong Un") == "latin"
    assert detect_script("") == "unknown"
    assert detect_language("\uae40\uc815\uc740") == "ko"
    assert detect_language("\u0412\u043b\u0430\u0434\u0438\u043c\u0438\u0440") == "ru"


def test_i18n_romanize() -> None:
    assert romanize("\uae40\uc815\uc740") == "gimjeongeun"
    assert romanize("\u0412\u043b\u0430\u0434\u0438\u043c\u0438\u0440") == "Vladimir"
    assert romanize("Already Latin") == "Already Latin"
    assert romanize("") == ""


def test_i18n_normalize() -> None:
    assert normalize_text("  Test\u200b  ") == "Test"
    assert normalize_text("") == ""
    # NFKC folds full-width Latin to ASCII.
    assert normalize_text("\uff21\uff22") == "AB"


def test_i18n_query_variants() -> None:
    # Latin target, no translator -> only the original variant.
    vs = generate_query_variants("Kim Jong Un", ["ko"])
    assert len(vs) == 1 and vs[0].method == "original"

    # Non-Latin target -> original + romanised.
    vs2 = generate_query_variants("\uae40\uc815\uc740", ["en"])
    methods = {v.method for v in vs2}
    assert methods == {"original", "romanized"}
    assert any(v.text == "gimjeongeun" for v in vs2)


def test_i18n_translator_backends() -> None:
    # MyMemory path.
    session = _FakeSession({"responseData": {"translatedText": "\ubc88\uc5ed"}})
    tr = Translator(backend="mymemory", session=session)
    assert tr.translate("hello", target="ko") == "\ubc88\uc5ed"

    # LibreTranslate path.
    session2 = _FakeSession({"translatedText": "\ubc88\uc5ed"})
    tr2 = Translator(backend="libretranslate", session=session2,
                     libretranslate_url="http://localhost:5000")
    assert tr2.translate("hello", target="ko") == "\ubc88\uc5ed"

    # MyMemory quota warnings are treated as failures.
    session3 = _FakeSession({"responseData": {
        "translatedText": "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE"}})
    tr3 = Translator(backend="mymemory", session=session3)
    assert tr3.translate("hello", target="ko") is None

    # A failed backend degrades to None, never raises.
    tr4 = Translator(backend="mymemory", session=_FakeSession({}, status=500))
    assert tr4.translate("hello", target="ko") is None


# --------------------------------------------------------------------------
# Regional search
# --------------------------------------------------------------------------
_BAIDU_HTML = """
<html><body>
<div class="result c-container"><h3 class="t">
  <a href="https://example.cn/a">\u4e2d\u56fd \u7ed3\u679c \u4e00</a></h3>
  <div class="c-abstract">\u6458\u8981\u4e00</div></div>
<div class="result c-container"><h3 class="t">
  <a href="https://example.cn/b">\u7ed3\u679c\u4e8c</a></h3></div>
</body></html>
"""


def test_regional_search_parsing() -> None:
    eng = RegionalSearchEngine(get_settings())
    results = eng._extract_results(_BAIDU_HTML, "baidu", 10)
    assert len(results) == 2
    assert results[0][1] == "https://example.cn/a"
    assert results[0][2] == "\u6458\u8981\u4e00"
    # limit is respected
    assert len(eng._extract_results(_BAIDU_HTML, "baidu", 1)) == 1


def test_regional_search_source_selection() -> None:
    eng = RegionalSearchEngine(get_settings())
    assert eng._select_sources("cn", None) == ["baidu"]
    assert eng._select_sources("korea", None) == ["naver"]
    assert eng._select_sources(None, ["yandex"]) == ["yandex"]
    assert set(eng._select_sources(None, None)) == {
        "baidu", "naver", "yandex", "searx"}
    # Unknown region -> no sources -> informational finding.
    unknown = eng.run("x", region="atlantis")
    assert unknown and unknown[0].data.get("status") == "skipped"


def test_regional_search_run_offline() -> None:
    eng = RegionalSearchEngine(get_settings())
    eng._translator = None                      # keep it fully offline
    eng.cached_get = lambda url, **kw: _Resp(_BAIDU_HTML)
    findings = eng.run("\u4e2d\u56fd", sources=["baidu"])
    assert len(findings) == 2
    assert findings[0].engine == "regional_search"
    assert findings[0].data["source"] == "baidu"
    assert findings[0].data["region"] == "cn"
    # Unreachable source -> graceful "not_found" finding.
    eng.cached_get = lambda url, **kw: None
    assert eng.run("x", sources=["baidu"])[0].data.get("status") == "not_found"


def test_regional_search_searx_json() -> None:
    eng = RegionalSearchEngine(get_settings())
    eng._translator = None
    eng._searx_instances = lambda: ["https://searx.example"]
    eng.cached_get_json = lambda url, **kw: {
        "results": [{"title": "Result", "url": "https://x.example", "content": "snip"}],
    }
    findings = eng.run("query", sources=["searx"])
    assert findings and findings[0].url == "https://x.example"


# --------------------------------------------------------------------------
# Regional social
# --------------------------------------------------------------------------
def test_regional_social_offline() -> None:
    settings = get_settings()

    class _All404:
        headers: dict = {}
        def get(self, url, **kw):
            return _Resp("", 404)
    assert RegionalSocialEngine(settings, session=_All404()).run("nobody") == []

    # 200 but body contains a "not found" marker -> suppressed.
    class _Marked:
        headers: dict = {}
        def get(self, url, **kw):
            return _Resp("<html>page not found</html>", 200)
    eng2 = RegionalSocialEngine(settings, session=_Marked())
    assert eng2._check("vk", "VKontakte", "ru",
                       "https://vk.com/{username}", "x") is None

    # 200 with clean body -> reported.
    class _Clean:
        headers: dict = {}
        def get(self, url, **kw):
            return _Resp("<html>profile</html>", 200)
    found = RegionalSocialEngine(settings, session=_Clean()).run("someone")
    assert len(found) == len(REGIONAL_PLATFORMS)
    assert all(f.engine == "regional_social" for f in found)


def test_regional_social_rejects_display_name() -> None:
    """A display name (with a space) is reported as a gap, not as profiles."""
    out = RegionalSocialEngine(get_settings()).run("Fei-Fei Li")
    assert len(out) == 1 and out[0].data.get("status") == "skipped"


# --------------------------------------------------------------------------
# Sanctions
# --------------------------------------------------------------------------
_OFAC_CSV = (
    '"1","BIN LADEN, Usama","individual","SDGT","","","","","","","",""\n'
    '"2","TEST ENTITY","entity","IRAN","","","","","","","",""\n'
)
_UN_XML = (
    '<CONSOLIDATED_LIST><INDIVIDUAL DATAID="99">'
    '<FIRST_NAME>KIM</FIRST_NAME><SECOND_NAME>JONG</SECOND_NAME>'
    '<THIRD_NAME>UN</THIRD_NAME></INDIVIDUAL></CONSOLIDATED_LIST>'
)
_EU_XML = (
    '<export><sanctionEntity logicalId="123">'
    '<nameAlias wholeName="Kim Jong Un"/></sanctionEntity></export>'
)
_UK_CSV = ("Name 1,Name 2,Name 6,Group Type,Regime,Unique ID\n"
           "KIM,JONG,UN,Individual,DPRK,GBR-1\n")


def _entries() -> list[dict]:
    return parse_ofac(_OFAC_CSV) + parse_un(_UN_XML) + parse_eu(_EU_XML) + parse_uk(_UK_CSV)


def test_sanctions_parsers() -> None:
    ofac = parse_ofac(_OFAC_CSV)
    assert ofac and ofac[0]["name"] == "BIN LADEN, Usama"
    assert ofac[0]["list"] == "OFAC SDN"
    un = parse_un(_UN_XML)
    assert un and un[0]["name"] == "KIM JONG UN"
    eu = parse_eu(_EU_XML)
    assert eu and eu[0]["name"] == "Kim Jong Un"
    uk = parse_uk(_UK_CSV)
    assert uk and "KIM" in uk[0]["name"]
    # Malformed input never raises.
    assert parse_un("<<<not xml") == []
    assert parse_eu("nope") == []


def test_sanctions_matching() -> None:
    eng = SanctionsEngine(get_settings())
    entries = _entries()
    matches = eng._match("Kim Jong Un", entries, 0.8)
    assert matches and all(score >= 0.8 for score, _ in matches)
    # Non-Latin target is transliterated before matching.
    forms = eng._candidate_forms("\uae40\uc815\uc740")
    assert "gimjeongeun" in forms and "\uae40\uc815\uc740" in forms
    # Unrelated name -> no match.
    assert eng._match("Totally Unrelated Person", entries, 0.8) == []


def test_sanctions_short_form_no_false_positive() -> None:
    """A tiny initial form must not "match" an unrelated long entity name."""
    eng = SanctionsEngine(get_settings())
    entries = [
        {"name": "GAZPROM NEFT SHELF LIMITED LIABILITY COMPANY",
         "list": "OFAC SDN", "program": "", "id": "52122", "type": "-0-"},
        {"name": "Association of Citizens for the Support of Lies",
         "list": "EU", "program": "", "id": "2196", "type": "Entity"},
    ]
    # "Fei-Fei Li" yields an initial form like "f li"; the old raw-substring
    # rule scored it 0.92 against "...shel-f li-mited...". Now: no match.
    assert eng._match("Fei-Fei Li", entries, 0.9) == []
    # Genuine whole-token / extended-name matches still score strongly.
    assert eng._score("kim jong un", "kim jong un jr") == 0.92
    assert eng._score("kim jong un", "bin laden usama") < 0.8


def test_sanctions_source_filter_and_run() -> None:
    eng = SanctionsEngine(get_settings())
    eng._all_entries = _entries                 # offline
    eng._want_opensanctions = lambda source: False   # no network
    filtered = eng._filter_sources(_entries(), ["ofac"])
    assert filtered and all(e["list"] == "OFAC SDN" for e in filtered)
    matched = eng.run("Kim Jong Un", threshold=0.8)
    assert matched and matched[0].data["status"] == "matched"
    assert matched[0].category == "sanctions"
    none = eng.run("Nobody At All Here", threshold=0.9)
    assert none[0].data["status"] == "not_found"
    eng._all_entries = lambda: []               # no data -> skipped
    assert eng.run("x")[0].data["status"] == "skipped"


# --------------------------------------------------------------------------
# Bypass improvements
# --------------------------------------------------------------------------
class _HtmlSession:
    """A session whose GET returns a fixed HTML body."""

    def __init__(self, html: str, status: int = 200):
        self.headers: dict = {}
        self._html = html
        self._status = status

    def get(self, url, **kw):
        return _Resp(self._html, self._status)


def test_proxy_user_agent_rotation() -> None:
    from research_tool.utils import proxy
    settings = get_settings()
    original = settings.http.user_agent_rotation
    try:
        settings.http.user_agent_rotation = True
        assert proxy.pick_user_agent(settings) in proxy._BROWSER_USER_AGENTS
        assert proxy.mobile_user_agent() in proxy._MOBILE_USER_AGENTS
        settings.http.user_agent_rotation = False
        assert proxy.pick_user_agent(settings) == settings.http.user_agent
    finally:
        settings.http.user_agent_rotation = original


def test_i18n_google_backend() -> None:
    html = '<html><body><div class="result-container">\ubc88\uc5ed</div></body></html>'
    tr = Translator(backend="google", session=_HtmlSession(html))
    assert tr.translate("hello", target="ko") == "\ubc88\uc5ed"
    # No result container -> graceful None.
    tr2 = Translator(backend="google", session=_HtmlSession("<html></html>"))
    assert tr2.translate("hello", target="ko") is None


def test_sanctions_permutations() -> None:
    eng = SanctionsEngine(get_settings())
    forms = eng._candidate_forms("Kim Jong Un")
    for expected in ("un jong kim", "un kim", "kim un", "k un", "kim j u"):
        assert expected in forms, expected
    # A "Last, First" entry (normalised to "un kim") now matches via permutation.
    entries = [{"name": "UN, KIM", "list": "TEST", "program": "",
                "id": "", "type": ""}]
    assert eng._match("Kim Jong Un", entries, 0.8)


def test_i18n_google_json_backend() -> None:
    # The primary Google backend uses the translate_a/single nested array.
    session = _FakeSession([[["\ubc88\uc5ed", "hello", None, None, 10]], None, "en"])
    tr = Translator(backend="google", session=session)
    assert tr.translate("hello", target="ko") == "\ubc88\uc5ed"


def test_sanctions_opensanctions_offline() -> None:
    eng = SanctionsEngine(get_settings())
    eng._all_entries = lambda: []
    eng._opensanctions_key = lambda: "test-key"
    payload = {"results": [{"id": "NK-1", "caption": "Kim Jong Un",
                            "schema": "Person",
                            "datasets": ["us_ofac_sdn", "un_sc_sanctions"],
                            "score": 0.97}]}
    eng.cached_get = lambda url, **kw: _Resp(payload=payload)
    findings = eng.run("Kim Jong Un", source=["opensanctions"])
    assert findings and findings[0].data["sanctions_list"] == "OpenSanctions"
    assert findings[0].data["status"] == "matched"
    # API 401 (bad key) + no local lists -> "skipped".
    eng.cached_get = lambda url, **kw: _Resp("", 401)
    assert eng.run("x", source=["opensanctions"])[0].data["status"] == "skipped"
    # Without a key, OpenSanctions is skipped entirely (no request made).
    eng2 = SanctionsEngine(get_settings())
    eng2._opensanctions_key = lambda: None
    assert eng2._want_opensanctions(None) is False


def test_regional_search_mobile_and_searx_html() -> None:
    # Mobile sources pass a mobile User-Agent header.
    eng = RegionalSearchEngine(get_settings())
    eng._translator = None
    captured: dict = {}

    def fake_get(url, **kw):
        captured.update(kw)
        return _Resp(_BAIDU_HTML)

    eng.cached_get = fake_get
    eng.run("\u4e2d\u56fd", sources=["baidu"])
    assert captured.get("headers", {}).get("User-Agent")

    # SearXNG JSON disabled -> HTML fallback path.
    eng2 = RegionalSearchEngine(get_settings())
    eng2._translator = None
    eng2._searx_instances = lambda: ["https://searx.example"]
    eng2.cached_get_json = lambda url, **kw: None
    searx_html = ('<html><article class="result"><h3>'
                  '<a href="https://x.example">Title</a></h3>'
                  '<p class="content">snip</p></article></html>')
    eng2.cached_get = lambda url, **kw: _Resp(searx_html)
    findings = eng2.run("query", sources=["searx"])
    assert findings and findings[0].url == "https://x.example"


def test_regional_search_block_detection() -> None:
    eng = RegionalSearchEngine(get_settings())
    eng._translator = None
    captcha = ('<html><title>\u9a8c\u8bc1</title>'
               '<body>wappass.baidu.com/static/captcha</body></html>')
    eng.cached_get = lambda url, **kw: _Resp(captcha)
    out = eng.run("x", sources=["baidu"])
    assert out[0].data.get("status") == "blocked"


def test_regional_search_naver_challenge() -> None:
    """Naver's mobile captcha wall is flagged, not parsed as results."""
    eng = RegionalSearchEngine(get_settings())
    eng._translator = None
    challenge = ('<html><body><a href="/antibot/captcha">'
                 'And solve an image challenge instead.</a></body></html>')
    eng.cached_get = lambda url, **kw: _Resp(challenge)
    out = eng.run("query", sources=["naver"])
    assert out and out[0].data.get("status") == "blocked"


def test_regional_search_filters_nav_hrefs() -> None:
    """Navigation/challenge anchors are dropped from the selector path."""
    eng = RegionalSearchEngine(get_settings())
    junk = (
        "?ssc=tab.m.all&nso=p%3A1d",
        "https://m.search.naver.com/search.naver?sm=tab_clk&ssc=tab.m_ur.all",
        "https://m.keep.naver.com/",
        "https://msearch.shopping.naver.com/search/all?query=x",
        "https://m.help.naver.com/support/alias/search/integration_m/x.naver",
    )
    real = (
        "https://news.example.kr/article/1",
        "https://ko.wikipedia.org/wiki/%ED%8E%98%EC%9D%B4",
    )
    html = ('<html><body>'
            + "".join(f'<li class="bx"><a href="{h}">Nav item</a></li>'
                      for h in junk)
            + "".join(f'<li class="bx"><a href="{h}">Real result title</a></li>'
                      for h in real)
            + '</body></html>')
    urls = [r[1] for r in eng._extract_results(html, "naver", 10)]
    assert set(real) <= set(urls)
    assert not any(j in urls for j in junk)


def test_render_html_disabled_by_default() -> None:
    settings = get_settings()
    original = settings.http.render_js
    try:
        settings.http.render_js = False
        assert RegionalSearchEngine(settings).render_html("https://x") is None
    finally:
        settings.http.render_js = original


def test_proxy_rotator() -> None:
    from research_tool.utils.proxy import (ProxyRotator,
                                           proxy_rotator_from_settings)
    rot = ProxyRotator(["http://a:1", "http://b:2", "http://a:1"])  # de-duped
    assert len(rot) == 2 and bool(rot)
    assert rot.next() in ("http://a:1", "http://b:2")
    rot.retire("http://a:1")
    assert len(rot) == 1
    assert rot.next() == "http://b:2"
    rot.retire("http://b:2")
    assert rot.next() is None and not rot
    # Settings-driven rotator (empty pool by default).
    assert len(proxy_rotator_from_settings(get_settings())) == 0


def test_regional_search_generic_fallback() -> None:
    eng = RegionalSearchEngine(get_settings())
    html = ('<html><body><nav><a href="/login">Login</a></nav>'
            '<a href="https://example.org/article-one">A meaningful article title</a>'
            '<a href="https://example.org/article-two">Another meaningful title</a>'
            '</body></html>')
    results = eng._extract_results(html, "baidu", 10)
    urls = [r[1] for r in results]
    assert "https://example.org/article-one" in urls
    assert not any("login" in u for u in urls)


def test_regional_search_serpapi_fallback() -> None:
    eng = RegionalSearchEngine(get_settings())
    eng._translator = None
    eng.settings.api_keys.serpapi = "test-key"
    try:
        eng.cached_get = lambda url, **kw: _Resp("<html>no results</html>")
        eng.cached_get_json = lambda url, **kw: {
            "organic_results": [{"title": "SerpAPI hit",
                                 "link": "https://s.example", "snippet": "s"}],
        }
        out = eng.run("query", sources=["baidu"])
        assert any(f.url == "https://s.example" for f in out)
    finally:
        eng.settings.api_keys.serpapi = None


def test_regional_search_rotation_on_block() -> None:
    from research_tool.utils.proxy import ProxyRotator
    eng = RegionalSearchEngine(get_settings())
    eng._translator = None
    eng._rotator = ProxyRotator(["http://p1:1", "http://p2:2", "http://p3:3"])
    eng._current_proxy = None
    calls = {"n": 0}

    def fake_get(url, **kw):
        calls["n"] += 1
        if calls["n"] == 1:                 # first exit IP -> captcha
            return _Resp("<html>wappass.baidu.com captcha</html>")
        return _Resp(_BAIDU_HTML)           # rotated exit IP -> results

    eng.cached_get = fake_get
    out = eng.run("\u4e2d\u56fd", sources=["baidu"])
    assert calls["n"] >= 2                  # it rotated and retried
    assert len(out) == 2                    # results came from the retry


def test_sanctions_bulk_parse() -> None:
    from research_tool.engines.sanctions import parse_opensanctions_bulk
    text = (
        '{"id":"NK-1","schema":"Person","properties":'
        '{"name":["Kim Jong Un"],"alias":["Kim Jong-un"]}}\n'
        'this is not json\n'
        '{"id":"NK-2","schema":"Organization","properties":'
        '{"name":["Korea Mining"]}}\n'
    )
    entries = parse_opensanctions_bulk(text)
    names = [e["name"] for e in entries]
    assert "Kim Jong Un" in names and "Kim Jong-un" in names
    assert "Korea Mining" in names
    assert all(e["list"] == "OpenSanctions" for e in entries)


def test_sanctions_bulk_offline() -> None:
    eng = SanctionsEngine(get_settings())
    eng.settings.sanctions.opensanctions_bulk = True
    try:
        eng._all_entries = lambda: []
        eng._opensanctions_key = lambda: None
        bulk = ('{"id":"NK-1","schema":"Person",'
                '"properties":{"name":["Kim Jong Un"]}}\n')
        eng.session = _HtmlSession(bulk)    # stands in for the bulk download
        out = eng.run("Kim Jong Un")
        assert out and out[0].data["sanctions_list"] == "OpenSanctions"
        assert out[0].data["status"] == "matched"
    finally:
        eng.settings.sanctions.opensanctions_bulk = False


# --------------------------------------------------------------------------
# Wiring: config, registry, orchestrator
# --------------------------------------------------------------------------
def test_config_cross_border_sections() -> None:
    settings = get_settings()
    assert settings.i18n.enabled is True
    assert "ko" in settings.i18n.target_languages
    assert settings.sanctions.sources.get("ofac") is True
    assert settings.engines.regional_search is True
    assert settings.engines.regional_social is True
    assert settings.engines.sanctions is True


def test_registry_and_plan_cross_border() -> None:
    for name in ("regional_search", "regional_social", "sanctions"):
        assert name in ENGINE_REGISTRY
    orch = Orchestrator(get_settings())
    name_plan = orch.plan("John Smith")
    assert "regional_search" in name_plan
    assert "regional_social" in name_plan
    assert "sanctions" in name_plan
    assert "sanctions" in orch.plan("a@b.com")
    assert "regional_social" in orch.plan("someusername")
    orch.close()


# --------------------------------------------------------------------------
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
