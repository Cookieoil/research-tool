"""Security regression tests for the research toolkit.

Covers the four guarantees the project must keep:

1. **No API keys in the client/code.** Source files, generated documentation
   and published papers contain no hardcoded credentials; secrets are masked
   in ``config`` output and redacted in logs.
2. **Real admin authentication.** Admin access is verified *server-side* with
   a salted PBKDF2 password verifier and HMAC-signed, HttpOnly sessions. There
   is no ``localStorage.isAdmin`` flag (or any client-supplied flag) that grants
   access, and CSRF tokens are required for state-changing requests.
3. **No full public database.** Anonymous requests cannot read the bulk
   ``/api/papers`` catalogue, raw JSON reports or ``data/``; the static-site
   builder excludes raw JSON by default; GitHub hosting defaults to private.
4. **Defence in depth.** XSS-safe links, path-traversal guards, SSRF blocking,
   XML bomb rejection, Excel formula-injection escaping, cache encryption
   fail-fast and log redaction.

Run with ``python tests/test_security.py`` (or pytest). No network access.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from research_tool.config import Settings
from research_tool.engines.base import _safe_cache_key
from research_tool.engines.sanctions import _safe_xml_fromstring
from research_tool.logger import redact
from research_tool.models.report import Finding, ResearchReport
from research_tool.reporters import _safe_stem, write_report
from research_tool.reporters.excel_report import _safe_cell
from research_tool.server import (
    SESSION_COOKIE,
    LoginThrottle,
    SessionStore,
    create_app,
    hash_password,
    verify_password,
)
from research_tool.utils import crypto
from research_tool.utils.cache import ResponseCache
from research_tool.utils.github import ReportHost, markdown_to_html
from research_tool.utils.library import _contained
from research_tool.utils.masking import mask_config
from research_tool.utils.validators import is_private_host, is_safe_url, safe_href

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# High-confidence credential formats only, so ordinary research prose in
# papers/ and docs/ cannot trip the scanner.
_SECRET_PATTERNS = {
    "openai_sk": re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
    "github_token": re.compile(
        r"\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"),
    "google_api": re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    "aws_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "slack": re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}

_SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules",
              "build", "dist"}
_TEXT_EXTS = {".py", ".md", ".yaml", ".yml", ".html", ".txt", ".json",
              ".toml", ".cfg", ".ini", ".sh", ".ps1"}
_SELF_FILES = {"test_security.py", "_scan_secrets.py"}


def _iter_text_files():
    """Yield every text file that could ship to a client or a public site."""
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in _TEXT_EXTS:
            continue
        if path.name in _SELF_FILES:
            continue
        yield path


# ---------------------------------------------------------------------------
# 1. No API keys in the client / code
# ---------------------------------------------------------------------------
def test_no_hardcoded_api_keys_anywhere() -> None:
    """No source file, doc, paper or data dump contains a real credential."""
    hits: list[tuple[str, str, str]] = []
    for path in _iter_text_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, pattern in _SECRET_PATTERNS.items():
            for match in pattern.finditer(text):
                hits.append((name, str(path.relative_to(PROJECT_ROOT)),
                             match.group(0)[:24]))
    assert not hits, f"hardcoded credentials found: {hits}"


def test_committed_config_has_no_secret_values() -> None:
    """Every secret slot in the committed config.yaml is empty."""
    import yaml

    data = yaml.safe_load(
        (PROJECT_ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    leaves: list[tuple[str, object]] = []

    def walk(node: object, prefix: str = "") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{prefix}{key}.")
        else:
            leaves.append((prefix.rstrip("."), node))

    walk(data)
    secret_keys = {
        "token", "api_key", "apikey", "deepl_key", "opensanctions_key",
        "censys_id", "censys_secret", "hibp", "shodan", "serpapi", "hunter",
        "tor_control_password", "admin_password", "admin_password_hash",
        "session_secret", "proxy", "proxy_pool", "encryption_key",
    }
    leaks = [(key, value) for key, value in leaves
             if key.split(".")[-1] in secret_keys and value]
    assert not leaks, f"config.yaml stores secret values: {leaks}"


def test_config_yaml_keeps_github_token_null() -> None:
    import yaml

    data = yaml.safe_load(
        (PROJECT_ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    assert not data.get("github", {}).get("token")


def test_mask_config_hides_every_secret_slot() -> None:
    """mask_config scrubs api keys, tokens, admin secrets and proxy creds."""
    raw = {
        "api_keys": {"serpapi": "live-serpapi-key", "hibp": "live-hibp-key"},
        "github": {"token": "ghp_abcdefghijklmnopqrstuvwxyz012345"},
        "i18n": {"deepl_key": "deepl-secret"},
        "sanctions": {"opensanctions_key": "os-secret"},
        "http": {
            "tor_control_password": "tor-pass",
            "proxy": "http://alice:hunter2@proxy.example:8080",
            "proxy_pool": ["socks5h://bob:swordfish@proxy.example:1080"],
        },
        "server": {
            "admin_password": "admin-pass",
            "admin_password_hash": "pbkdf2_sha256$...",
            "session_secret": "session-secret",
        },
        "papers": {"default_topic": "gacha"},  # non-secret untouched
    }
    masked = mask_config(raw)
    serialised = repr(masked)
    for secret in ("live-serpapi-key", "live-hibp-key",
                   "ghp_abcdefghijklmnopqrstuvwxyz012345", "deepl-secret",
                   "os-secret", "tor-pass", "hunter2", "swordfish",
                   "admin-pass", "session-secret"):
        assert secret not in serialised, f"{secret} leaked through mask_config"
    assert masked["papers"]["default_topic"] == "gacha"


def test_log_redaction_covers_headers_and_token_prefixes() -> None:
    """redact() scrubs bearer tokens, prefixed tokens and proxy credentials."""
    message = (
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz "
        "token=ghp_0123456789abcdefghijklmnopqrstuvwxyz "
        "proxy http://alice:hunter2@proxy.example:8080 "
        "mail alice@example.com"
    )
    redacted = redact(message)
    for secret in ("abcdefghijklmnopqrstuvwxyz",
                   "ghp_0123456789abcdefghijklmnopqrstuvwxyz",
                   "hunter2", "alice@example.com"):
        assert secret not in redacted, f"{secret} survived redaction"
    assert "Bearer [redacted]" in redacted
    assert "token=[redacted]" in redacted


def test_log_redaction_masks_standalone_prefixed_tokens() -> None:
    redacted = redact("leaked ghp_0123456789abcdefghijklmnopqrstuvwxyz here")
    assert "ghp_0123456789abcdefghijklmnopqrstuvwxyz" not in redacted
    assert "[redacted-token]" in redacted


def test_cache_key_never_contains_api_key() -> None:
    """Engine cache keys redact secret query parameters."""
    key = _safe_cache_key(
        "https://serpapi.com/search.json",
        {"q": "Jane Doe", "api_key": "super-secret-key", "num": 10},
    )
    assert "super-secret-key" not in key
    assert "Jane+Doe" in key or "Jane%20Doe" in key
    assert "api_key" in key


# ---------------------------------------------------------------------------
# 2. Server-side admin authentication (no localStorage flag)
# ---------------------------------------------------------------------------
_PASSWORD = "correct horse battery staple"


def _server_settings(root: Path, password: str | None = _PASSWORD,
                     allow_public_read: bool = False) -> Settings:
    return Settings(**{
        "app": {
            "reports_dir": str(root / "data" / "raw"),
            "papers_dir": str(root / "papers"),
            "cache_dir": str(root / "data" / "cache"),
        },
        "github": {"site_dir": str(root / "docs")},
        "server": {
            "admin_password": password,
            "session_secret": "unit-test-session-secret",
            "max_login_attempts": 3,
            "lockout_seconds": 60,
            "allow_public_read": allow_public_read,
        },
    })


def _build_client(root: Path, password: str | None = _PASSWORD):
    settings = _server_settings(root, password)
    app = create_app(settings)
    return TestClient(app, follow_redirects=False), settings


def test_password_hash_is_salted_and_unique() -> None:
    first = hash_password("hunter2")
    second = hash_password("hunter2")
    assert first != second, "salt must be random per hash"
    assert first.startswith("pbkdf2_sha256$")
    assert "hunter2" not in first


def test_password_verification_rejects_wrong_input() -> None:
    verifier = hash_password("hunter2")
    assert verify_password("hunter2", verifier) is True
    assert verify_password("hunter3", verifier) is False
    assert verify_password("", verifier) is False
    assert verify_password("hunter2", "not-a-verifier") is False


def test_server_refuses_to_start_without_password() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        settings = _server_settings(Path(tmp), password=None)
        raised = False
        try:
            create_app(settings)
        except RuntimeError:
            raised = True
        assert raised, "server must not start without an admin password"


def test_unauthenticated_requests_are_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client, _ = _build_client(Path(tmp))
        for path in ("/api/me", "/api/papers", "/api/reports",
                     "/api/config", "/reports/report.json"):
            response = client.get(path)
            assert response.status_code == 401, (path, response.status_code)
        root = client.get("/")
        assert root.status_code in (302, 303)
        assert root.headers.get("location", "").endswith("/login")


def test_login_sets_httponly_strict_cookie() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client, _ = _build_client(Path(tmp))
        response = client.post("/api/auth/login", json={"password": _PASSWORD})
        assert response.status_code == 200
        body = response.json()
        assert body["authenticated"] is True
        assert body["csrf_token"]
        cookie = response.headers.get("set-cookie", "")
        assert SESSION_COOKIE in cookie
        assert "httponly" in cookie.lower()
        assert "samesite=strict" in cookie.lower()
        me = client.get("/api/me")
        assert me.status_code == 200
        assert me.json()["authenticated"] is True


def test_wrong_password_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client, _ = _build_client(Path(tmp))
        response = client.post("/api/auth/login", json={"password": "wrong"})
        assert response.status_code == 401
        assert "set-cookie" not in {k.lower() for k in response.headers}


def test_login_is_rate_limited() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client, _ = _build_client(Path(tmp))
        for _ in range(3):
            assert client.post("/api/auth/login",
                               json={"password": "nope"}).status_code == 401
        blocked = client.post("/api/auth/login", json={"password": _PASSWORD})
        assert blocked.status_code == 429
        assert "retry-after" in {k.lower() for k in blocked.headers}


def test_forged_session_cookie_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client, _ = _build_client(Path(tmp))
        # Arbitrary unsigned cookie.
        client.cookies.set(SESSION_COOKIE, "forged-session.0123456789abcdef")
        assert client.get("/api/me").status_code == 401
        # Correctly signed cookie for a session that does not exist.
        store = SessionStore(60, b"unit-test-session-secret")
        client.cookies.set(SESSION_COOKIE, store.sign("nonexistent-session"))
        assert client.get("/api/me").status_code == 401


def test_client_side_admin_flag_does_not_authenticate() -> None:
    """No localStorage-style flag, header or cookie can bypass the server."""
    with tempfile.TemporaryDirectory() as tmp:
        client, _ = _build_client(Path(tmp))
        for headers in ({"X-Admin": "true"},
                        {"X-Is-Admin": "true"},
                        {"Authorization": "Bearer admin"}):
            assert client.get("/api/papers", headers=headers).status_code == 401
        client.cookies.set("isAdmin", "true")
        client.cookies.set("admin", "true")
        client.cookies.set("role", "admin")
        assert client.get("/api/papers").status_code == 401


def test_csrf_required_for_state_changing_requests() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client, _ = _build_client(Path(tmp))
        login = client.post("/api/auth/login", json={"password": _PASSWORD})
        token = login.json()["csrf_token"]
        # Missing CSRF token.
        assert client.post("/api/auth/logout").status_code == 403
        # Valid token succeeds and revokes the session.
        ok = client.post("/api/auth/logout", headers={"X-CSRF-Token": token})
        assert ok.status_code == 200
        assert client.get("/api/me").status_code == 401


def test_session_store_signs_and_detects_tampering() -> None:
    store = SessionStore(60, b"secret")
    signed = store.sign("session-id")
    assert store.unsign(signed) == "session-id"
    assert store.unsign("session-id.tampered") is None
    assert store.unsign("garbage") is None


def test_login_throttle_blocks_then_resets() -> None:
    throttle = LoginThrottle(max_attempts=2, lockout_seconds=60)
    assert throttle.blocked_for("203.0.113.9") == 0
    throttle.fail("203.0.113.9")
    throttle.fail("203.0.113.9")
    assert throttle.blocked_for("203.0.113.9") > 0
    throttle.success("203.0.113.9")
    assert throttle.blocked_for("203.0.113.9") == 0


def test_login_page_never_leaks_the_password() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client, _ = _build_client(Path(tmp), password="s3cret-admin-pass")
        page = client.get("/login").text
        assert "s3cret-admin-pass" not in page
        assert "localStorage" in page  # explains there is no client-side flag


def test_security_headers_are_sent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client, _ = _build_client(Path(tmp))
        response = client.get("/login")
        headers = {k.lower(): v for k, v in response.headers.items()}
        assert headers.get("x-content-type-options") == "nosniff"
        assert headers.get("x-frame-options") == "DENY"
        assert headers.get("referrer-policy") == "no-referrer"
        assert "default-src 'none'" in headers.get("content-security-policy", "")
        assert headers.get("cache-control") == "no-store"


# ---------------------------------------------------------------------------
# 3. No full public database
# ---------------------------------------------------------------------------
def test_github_defaults_are_private_and_exclude_raw_json() -> None:
    settings = Settings()
    gh = settings.github
    assert gh.enabled is False
    assert gh.visibility == "private"
    assert gh.pages is False
    assert gh.host_reports is False
    assert gh.host_raw_json is False


def test_report_host_excludes_raw_json_when_asked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        settings = _server_settings(root)
        reports = settings.reports_path
        (reports / "report_a.json").write_text("{}", encoding="utf-8")
        (reports / "report_a.md").write_text("# a", encoding="utf-8")
        host = ReportHost(settings)
        everything = host.collect(reports=True, papers=False)
        safe = host.collect(reports=True, papers=False,
                            include_raw_json=False)
        everything_names = {item.source.name for item in everything}
        safe_names = {item.source.name for item in safe}
        assert "report_a.json" in everything_names
        assert "report_a.json" not in safe_names
        assert "report_a.md" in safe_names


def test_static_site_build_excludes_raw_json() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        settings = _server_settings(root)
        reports = settings.reports_path
        (reports / "report_b.json").write_text(
            '{"target": "x", "findings": []}', encoding="utf-8")
        (reports / "report_b.md").write_text("# b", encoding="utf-8")
        host = ReportHost(settings)
        host.build_site(reports=True, papers=False, include_raw_json=False)
        published = list(host.site_dir.rglob("*.json"))
        assert not published, f"raw JSON leaked into the site: {published}"


def test_gitignore_blocks_database_and_secret_files() -> None:
    text = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("data/cache/", "data/raw/*", "*.db", "*.sqlite",
                    ".env", ".env.*", "papers/**/*.json",
                    "papers/**/*.meta.json", "papers/INDEX.json"):
        assert pattern in text, f".gitignore missing {pattern!r}"


def test_public_mode_serves_only_human_readable_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        settings = _server_settings(root, allow_public_read=True)
        papers = settings.papers_path
        (papers / "topic").mkdir(parents=True, exist_ok=True)
        (papers / "topic" / "paper.md").write_text("# paper", encoding="utf-8")
        (papers / "topic" / "paper.json").write_text(
            '{"secret": "catalogue"}', encoding="utf-8")
        app = create_app(settings)
        client = TestClient(app, follow_redirects=False)
        assert client.get("/papers/topic/paper.md").status_code == 200
        assert client.get("/papers/topic/paper.json").status_code == 404


def test_path_traversal_on_paper_route_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        settings = _server_settings(root, allow_public_read=True)
        app = create_app(settings)
        client = TestClient(app, follow_redirects=False)
        for attempt in ("../secrets.md", "..%2Fsecrets.md",
                        "topic/../../secrets.md"):
            response = client.get(f"/papers/{attempt}")
            assert response.status_code in (404, 400), attempt


def test_reports_route_requires_authentication() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        settings = _server_settings(root)
        reports = settings.reports_path
        (reports / "report_c.json").write_text("{}", encoding="utf-8")
        app = create_app(settings)
        client = TestClient(app, follow_redirects=False)
        response = client.get("/reports/report_c.json")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# 4. Defence in depth: XSS, path traversal, SSRF, XML, Excel, cache
# ---------------------------------------------------------------------------
def test_safe_href_blocks_script_and_dangerous_schemes() -> None:
    for hostile in (
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "java\tscript:alert(1)",
        "vbscript:msgbox(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "//evil.example/x",
        "about:blank",
    ):
        assert safe_href(hostile) == "#", hostile


def test_safe_href_allows_http_mailto_and_relative() -> None:
    for benign in ("https://example.com/a?b=1", "http://example.com",
                   "mailto:analyst@example.com", "reports/a.html",
                   "./a.html", "../a.html", "/a.html", "#anchor"):
        assert safe_href(benign) == benign, benign


def test_markdown_to_html_neutralises_javascript_links() -> None:
    html = markdown_to_html("[click](javascript:alert(1))")
    assert "javascript:" not in html.lower()
    assert 'href="#"' in html


def test_markdown_to_html_escapes_raw_html() -> None:
    html = markdown_to_html("<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_generated_html_has_content_security_policy() -> None:
    html = markdown_to_html("# Title\n\nBody")
    # markdown_to_html returns a fragment; the page wrapper adds the CSP.
    from research_tool.utils.github import html_document

    page = html_document("Title", html)
    assert "Content-Security-Policy" in page
    assert "default-src 'none'" in page
    assert "frame-ancestors 'none'" in page


def test_safe_stem_strips_path_separators() -> None:
    for hostile in ("..\\..\\evil", "../../evil", "C:\\Windows\\evil",
                    "a/b", "a\\b", "..", "."):
        stem = _safe_stem(hostile)
        assert ".." not in stem or stem == "report"
        assert "/" not in stem and "\\" not in stem and ":" not in stem
        assert stem


def test_write_report_refuses_escape_via_stem() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        out = root / "reports"
        out.mkdir()
        report = ResearchReport(target="x")
        # A stem containing traversal must be sanitised, never escape.
        path = write_report(report, "json", out, stem="..\\..\\evil")
        assert path.resolve().is_relative_to(out.resolve())


def test_library_contained_rejects_escape() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        raised = False
        try:
            _contained(root, root / ".." / "outside.txt")
        except ValueError:
            raised = True
        assert raised, "_contained accepted a path outside its root"


def test_is_safe_url_blocks_private_and_loopback() -> None:
    for hostile in ("http://127.0.0.1/", "http://localhost/",
                    "http://169.254.169.254/latest/meta-data/",
                    "http://10.0.0.1/", "http://192.168.1.1/",
                    "http://[::1]/", "file:///etc/passwd",
                    "ftp://example.com/"):
        assert is_safe_url(hostile) is False, hostile
    assert is_safe_url("https://example.com/") is True
    assert is_safe_url("http://127.0.0.1/", allow_private=True) is True
    assert is_private_host("127.0.0.1") is True
    assert is_private_host("example.com") is False


def test_sanctions_rejects_doctype_and_entity_declarations() -> None:
    bomb = (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE lolz [\n'
        '  <!ENTITY lol "lol">\n'
        '  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">\n'
        ']>\n'
        '<lolz>&lol2;</lolz>'
    )
    assert _safe_xml_fromstring(bomb) is None
    external = (
        '<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        '<foo>&xxe;</foo>'
    )
    assert _safe_xml_fromstring(external) is None


def test_sanctions_parses_plain_xml() -> None:
    root = _safe_xml_fromstring("<root><child>ok</child></root>")
    assert root is not None
    assert root.find("child").text == "ok"


def test_excel_formula_injection_is_escaped() -> None:
    for hostile in ("=SUM(A1:A2)", "+1+1", "-1+1", "@SUM(A1)",
                    "\t=cmd", "\r=cmd"):
        escaped = _safe_cell(hostile)
        assert escaped.startswith("'"), hostile
    # Ordinary text is untouched.
    assert _safe_cell("Jane Doe") == "Jane Doe"
    assert _safe_cell(42) == 42


def test_cache_encryption_fails_fast_without_key() -> None:
    old = os.environ.pop("RESEARCH_ENCRYPTION_KEY", None)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            raised = False
            try:
                ResponseCache(Path(tmp) / "cache.db", encrypt=True)
            except crypto.CryptoError:
                raised = True
            assert raised, "cache accepted encrypt=True without a key"
    finally:
        if old is not None:
            os.environ["RESEARCH_ENCRYPTION_KEY"] = old


def test_published_docs_have_no_external_scripts() -> None:
    docs = PROJECT_ROOT / "docs"
    if not docs.is_dir():
        return
    for page in docs.rglob("*.html"):
        text = page.read_text(encoding="utf-8", errors="ignore")
        lowered = text.lower()
        assert "<script" not in lowered, f"inline script in {page}"
        assert "cdn.jsdelivr" not in lowered, f"external CDN in {page}"
        assert "mermaid.esm" not in lowered, f"mermaid runtime in {page}"
        assert "mermaid@" not in lowered, f"mermaid CDN in {page}"
        assert "content-security-policy" in lowered, f"no CSP in {page}"


def _run_all() -> int:
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001 - report and continue
            failures += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())




