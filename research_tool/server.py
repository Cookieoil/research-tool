"""Admin web server with server-verified password authentication.

Why this exists
---------------
The static GitHub Pages site cannot enforce access control: anything in
``docs/`` is public, and a browser-side flag such as ``localStorage.isAdmin``
can be flipped by anyone with DevTools. This module serves the same material
from a small FastAPI application whose authentication is verified **on the
server**:

* The admin password is checked against a salted PBKDF2-HMAC-SHA256 digest
  (``hmac.compare_digest`` for constant-time comparison).
* A successful login issues a random 256-bit session id in an ``HttpOnly``,
  ``SameSite=Strict`` cookie. The session lives in server memory; the cookie
  is HMAC-signed so it cannot be forged or edited.
* Every state-changing request needs a per-session CSRF token.
* Login attempts are rate-limited per client IP.
* API keys and other secrets stay in the server process; the browser never
  receives them. ``GET /api/config`` returns a masked view.

Run it with::

    python -m research_tool serve

Set ``RESEARCH_ADMIN_PASSWORD`` (or ``RESEARCH_ADMIN_PASSWORD_HASH`` produced
by ``python -m research_tool hash-password``) before starting. When neither is
set the server refuses to start, so there is no accidental "open" mode.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    FileResponse, HTMLResponse, JSONResponse, PlainTextResponse,
    RedirectResponse,
)
from starlette.concurrency import run_in_threadpool

from .config import Settings, get_settings
from .logger import logger
from .orchestrator import Orchestrator
from .reporters import write_report
from .utils.library import PaperLibrary, load_report_file
from .utils.masking import mask_config
from .utils.retention import purge_tool_data

# ---------------------------------------------------------------------------
# Password hashing (PBKDF2-HMAC-SHA256)
# ---------------------------------------------------------------------------
PBKDF2_ITERATIONS = 600_000
_HASH_SCHEME = "pbkdf2_sha256"
SESSION_COOKIE = "rt_session"
MAX_FORM_BYTES = 64 * 1024


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    """Return a salted PBKDF2 verifier string (never the password itself)."""
    if not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations)
    return "{}${}${}${}".format(
        _HASH_SCHEME, iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


# Bound the work factor parsed from a stored verifier so a crafted hash string
# cannot pin a CPU core (DoS) with an absurd iteration count.
_MIN_PBKDF2_ITERATIONS = 100_000
_MAX_PBKDF2_ITERATIONS = 2_000_000


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of *password* against a stored PBKDF2 verifier."""
    try:
        scheme, iterations, salt_b64, digest_b64 = stored.split("$", 3)
        if scheme != _HASH_SCHEME:
            return False
        rounds = int(iterations)
        if not (_MIN_PBKDF2_ITERATIONS <= rounds <= _MAX_PBKDF2_ITERATIONS):
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, rounds)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
@dataclass
class Session:
    session_id: str
    csrf: str
    created: float
    last_seen: float
    ip: str = ""
    user_agent: str = ""


class SessionStore:
    """In-memory session table with expiry and HMAC-signed cookie values."""

    def __init__(self, ttl_seconds: int, secret: bytes,
                 max_sessions: int = 256):
        self.ttl = max(60, int(ttl_seconds))
        self.secret = secret
        self.max_sessions = max(1, int(max_sessions))
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}

    # -- cookie signing ---------------------------------------------------
    def sign(self, session_id: str) -> str:
        sig = hmac.new(self.secret, session_id.encode("utf-8"),
                       hashlib.sha256).hexdigest()
        return f"{session_id}.{sig}"

    def unsign(self, value: str) -> str | None:
        if not value or "." not in value:
            return None
        session_id, sig = value.rsplit(".", 1)
        expected = hmac.new(self.secret, session_id.encode("utf-8"),
                            hashlib.sha256).hexdigest()
        return session_id if hmac.compare_digest(sig, expected) else None

    # -- lifecycle --------------------------------------------------------
    def _prune(self, now: float) -> None:
        expired = [sid for sid, s in self._sessions.items()
                   if now - s.created > self.ttl]
        for sid in expired:
            self._sessions.pop(sid, None)

    def create(self, ip: str, user_agent: str) -> Session:
        now = time.time()
        session = Session(
            session_id=secrets.token_urlsafe(32),
            csrf=secrets.token_urlsafe(32),
            created=now, last_seen=now, ip=ip, user_agent=user_agent,
        )
        with self._lock:
            self._prune(now)
            # Bound memory: evict the least-recently-seen session when full.
            while len(self._sessions) >= self.max_sessions:
                oldest = min(self._sessions.values(),
                             key=lambda s: s.last_seen)
                self._sessions.pop(oldest.session_id, None)
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        now = time.time()
        with self._lock:
            self._prune(now)
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if now - session.created > self.ttl:
                self._sessions.pop(session_id, None)
                return None
            session.last_seen = now
            return session

    def destroy(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)


class LoginThrottle:
    """Per-IP login attempt limiter (slows password guessing)."""

    def __init__(self, max_attempts: int, lockout_seconds: int,
                 max_keys: int = 4096):
        self.max_attempts = max(1, int(max_attempts))
        self.lockout = max(1, int(lockout_seconds))
        self.max_keys = max(1, int(max_keys))
        self._lock = threading.Lock()
        self._failures: dict[str, list[float]] = {}

    def _prune(self, ip: str, now: float) -> None:
        cutoff = now - self.lockout
        self._failures[ip] = [t for t in self._failures.get(ip, [])
                              if t > cutoff]

    def blocked_for(self, ip: str) -> int:
        """Seconds until *ip* may try again (0 = allowed)."""
        now = time.time()
        with self._lock:
            self._prune(ip, now)
            failures = self._failures.get(ip, [])
            if len(failures) >= self.max_attempts:
                return max(1, int(self.lockout - (now - failures[0])))
            return 0

    def fail(self, ip: str) -> None:
        with self._lock:
            now = time.time()
            self._prune(ip, now)
            if len(self._failures) >= self.max_keys and ip not in self._failures:
                # Bound memory under a distributed/rotating-key attack.
                self._failures.pop(next(iter(self._failures)), None)
            self._failures.setdefault(ip, []).append(now)

    def success(self, ip: str) -> None:
        with self._lock:
            self._failures.pop(ip, None)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _safe_file(root: Path, relative: str,
               allowed_exts: set[str]) -> Path | None:
    """Resolve *relative* under *root* or return ``None`` (path traversal)."""
    try:
        base = root.resolve()
        candidate = (base / relative).resolve()
    except (OSError, ValueError):
        return None
    if not candidate.is_relative_to(base) or not candidate.is_file():
        return None
    if candidate.suffix.lower() not in allowed_exts:
        return None
    return candidate


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _csrf_input(token: str) -> str:
    return (f'<input type="hidden" name="csrf" value="{_esc(token)}">')


# File types the admin UI may serve vs. what anonymous readers may see.
ADMIN_EXTS = {".md", ".pdf", ".html", ".json", ".xlsx", ".csv", ".txt", ".enc"}
PUBLIC_EXTS = {".md", ".pdf"}


def _paper_file(record: Any, *, allowed: set[str] | None = None) -> str:
    """Pick a human-readable file from a paper record's ``files`` list.

    ``record.files`` also contains the machine-readable ``.json`` copy kept in
    ``_meta/``; prefer a rendered document so dashboard links open something a
    person can actually read (and so public links only expose allowed types).
    """
    files = [str(f) for f in (getattr(record, "files", None) or [])]
    for suffix in (".md", ".html", ".pdf"):
        for candidate in files:
            if candidate.lower().endswith(suffix):
                if allowed is None or Path(candidate).suffix.lower() in allowed:
                    return candidate
    for candidate in files:
        if allowed is None or Path(candidate).suffix.lower() in allowed:
            return candidate
    return ""


def _client_ip(request: Request) -> str:
    # Do not trust X-Forwarded-For unless a reverse proxy is explicitly
    # configured; the direct peer address is the safe default.
    return request.client.host if request.client else "unknown"


def _user_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")[:300]


async def _read_form(request: Request) -> dict[str, str]:
    """Parse an ``application/x-www-form-urlencoded`` body with a size cap."""
    body = await request.body()
    if len(body) > MAX_FORM_BYTES:
        raise HTTPException(status_code=413, detail="form body too large")
    parsed = parse_qs(body.decode("utf-8", errors="replace"),
                      keep_blank_values=True)
    return {k: v[0] for k, v in parsed.items() if v}


_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; font: 15px/1.5 -apple-system, Segoe UI, Roboto, sans-serif;
       background: #f6f7f9; color: #1f2328; }
header { background: #1f2328; color: #fff; padding: 14px 22px; }
header a { color: #fff; text-decoration: none; margin-right: 14px; }
main { max-width: 980px; margin: 24px auto; padding: 0 18px; }
.card { background: #fff; border: 1px solid #d0d7de; border-radius: 10px;
        padding: 18px; margin-bottom: 18px; }
label { display: block; margin: 10px 0 4px; font-weight: 600; }
input[type=text], input[type=password], select, textarea {
  width: 100%; padding: 9px 10px; border: 1px solid #d0d7de;
  border-radius: 7px; font: inherit; }
button { margin-top: 12px; padding: 9px 16px; border: 0; border-radius: 7px;
         background: #1f883d; color: #fff; font: inherit; cursor: pointer; }
button.danger { background: #cf222e; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 7px 8px; border-bottom: 1px solid #eaeef2; }
.muted { color: #656d76; }
.error { color: #cf222e; font-weight: 600; }
@media (prefers-color-scheme: dark) {
  body { background: #0d1117; color: #e6edf3; }
  .card { background: #161b22; border-color: #30363d; }
  th, td { border-color: #30363d; }
}
"""


def _render_page(title: str, body: str, *, nav: str = "") -> str:
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<meta http-equiv=\"Content-Security-Policy\" "
        "content=\"default-src 'none'; style-src 'unsafe-inline'; "
        "img-src 'self' data:; form-action 'self'; base-uri 'none'; "
        "frame-ancestors 'none'\">"
        "<meta name=\"referrer\" content=\"no-referrer\">"
        f"<title>{_esc(title)}</title><style>{_CSS}</style></head><body>"
        f"<header><strong>Research Toolkit Admin</strong>{nav}</header>"
        f"<main>{body}</main></body></html>"
    )


def _resolve_admin_verifier(settings: Settings) -> str:
    """Return a PBKDF2 verifier for the configured admin password."""
    server = settings.server
    if server.admin_password_hash:
        return server.admin_password_hash
    if server.admin_password:
        # Hash the plaintext config value once so the plaintext is not kept
        # in memory for the lifetime of the process.
        return hash_password(server.admin_password)
    raise RuntimeError(
        "No admin password configured. Set RESEARCH_ADMIN_PASSWORD or "
        "RESEARCH_ADMIN_PASSWORD_HASH before starting the server.")


def _session_secret(settings: Settings) -> bytes:
    raw = settings.server.session_secret
    if raw:
        return raw.encode("utf-8")
    logger.warning(
        "server.session_secret is unset; generating an ephemeral secret "
        "(sessions will not survive a restart). Set RESEARCH_SESSION_SECRET "
        "for a stable deployment.")
    return secrets.token_bytes(32)


def _media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".md": "text/markdown; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".pdf": "application/pdf",
        ".xlsx": "application/vnd.openxmlformats-officedocument."
                 "spreadsheetml.sheet",
    }.get(suffix, "application/octet-stream")


def _login_page(error: str = "") -> str:
    body = (
        '<div class="card" style="max-width:430px;margin:40px auto;">'
        '<h1>Admin sign in</h1>'
        + (f'<p class="error">{_esc(error)}</p>' if error else "")
        + '<form method="post" action="/login">'
        '<label for="password">Admin password</label>'
        '<input id="password" type="password" name="password" '
        'autocomplete="current-password" required>'
        '<button type="submit">Sign in</button>'
        '</form>'
        '<p class="muted">Password verification happens on the server. '
        'No admin flag is stored in localStorage.</p>'
        '</div>'
    )
    return _render_page("Sign in", body)


def _dashboard(settings: Settings, session: Session) -> str:
    library = PaperLibrary(settings.papers_path,
                           author=settings.papers.author,
                           default_status=settings.papers.default_status)
    paper_rows = "".join(
        "<tr><td>{title}</td><td>{topic}</td><td>{status}</td>"
        "<td><a href=\"/papers/{file}\">open</a></td></tr>".format(
            title=_esc(record.title),
            topic=_esc(record.topic),
            status=_esc(record.status),
            file=_esc(_paper_file(record)),
        )
        for record in library.records()
    ) or '<tr><td colspan="4" class="muted">No papers yet.</td></tr>'

    report_files = sorted(
        (p for p in settings.reports_path.glob("*") if p.is_file()),
        key=lambda p: p.stat().st_mtime, reverse=True)
    report_rows = "".join(
        "<tr><td>{name}</td><td><a href=\"/reports/{name}\">open</a></td></tr>"
        .format(name=_esc(path.name))
        for path in report_files[:100]
    ) or '<tr><td colspan="2" class="muted">No reports yet.</td></tr>'

    csrf = _csrf_input(session.csrf)
    body = f"""
<div class="card">
  <h2>Run research</h2>
  <form method="post" action="/run">
    {csrf}
    <label for="target">Target</label>
    <input id="target" type="text" name="target" required
           placeholder="name, email, domain or URL">
    <label for="engine">Engine</label>
    <select id="engine" name="engine">
      <option value="full">Full run (all engines)</option>
      <option value="search">search</option>
      <option value="whois">whois</option>
      <option value="domain_intel">domain_intel</option>
      <option value="social">social</option>
      <option value="credential_check">credential_check</option>
      <option value="academic">academic</option>
      <option value="company">company</option>
      <option value="web_scraper">web_scraper</option>
      <option value="openalex">openalex</option>
      <option value="orcid">orcid</option>
      <option value="npi">npi</option>
      <option value="dark">dark</option>
      <option value="regional_search">regional_search</option>
      <option value="regional_social">regional_social</option>
      <option value="sanctions">sanctions</option>
    </select>
    <label for="format">Save report as</label>
    <select id="format" name="format">
      <option value="markdown">markdown</option>
      <option value="json">json</option>
      <option value="pdf">pdf</option>
      <option value="excel">excel</option>
    </select>
    <button type="submit">Run</button>
  </form>
</div>

<div class="card">
  <h2>Finalized papers</h2>
  <table><thead><tr><th>Title</th><th>Topic</th><th>Status</th><th>File</th>
  </tr></thead><tbody>{paper_rows}</tbody></table>
  <form method="post" action="/archive">
    {csrf}
    <label for="paper_id">Archive a paper by id</label>
    <input id="paper_id" type="text" name="paper_id" required>
    <button class="danger" type="submit">Archive</button>
  </form>
</div>

<div class="card">
  <h2>Raw reports</h2>
  <table><thead><tr><th>File</th><th>Open</th></tr></thead>
  <tbody>{report_rows}</tbody></table>
  <form method="post" action="/publish">
    {csrf}
    <label for="from_report">Finalize a report into a paper</label>
    <input id="from_report" type="text" name="from_report"
           placeholder="report_&lt;target&gt;.json" required>
    <label for="title">Title (optional)</label>
    <input id="title" type="text" name="title">
    <label for="formats">Formats</label>
    <input id="formats" type="text" name="formats" value="markdown">
    <button type="submit">Publish</button>
  </form>
</div>

<div class="card">
  <h2>Maintenance</h2>
  <form method="post" action="/purge">
    {csrf}
    <label><input type="checkbox" name="confirm" value="yes" required>
    Securely purge cache, reports and logs</label>
    <button class="danger" type="submit">Purge</button>
  </form>
</div>
"""
    nav = (
        ' <a href="/">Dashboard</a>'
        ' <a href="/api/papers">Papers API</a>'
        ' <a href="/api/config">Config</a>'
        ' <form method="post" action="/logout" style="display:inline">'
        f'{_csrf_input(session.csrf)}'
        '<button type="submit" style="margin-left:12px">Sign out</button>'
        '</form>'
    )
    return _render_page("Admin dashboard", body, nav=nav)


def _public_index(settings: Settings) -> str:
    library = PaperLibrary(settings.papers_path,
                           author=settings.papers.author,
                           default_status=settings.papers.default_status)
    rows = "".join(
        "<tr><td>{title}</td><td>{topic}</td>"
        "<td><a href=\"/papers/{file}\">open</a></td></tr>".format(
            title=_esc(record.title), topic=_esc(record.topic),
            file=_esc(_paper_file(record, allowed=PUBLIC_EXTS)))
        for record in library.records() if record.status != "archived"
    ) or '<tr><td colspan="3" class="muted">No papers published.</td></tr>'
    body = (
        '<div class="card"><h2>Published papers</h2>'
        '<table><thead><tr><th>Title</th><th>Topic</th><th>File</th></tr>'
        f'</thead><tbody>{rows}</tbody></table></div>'
    )
    return _render_page("Research papers", body)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------
def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the admin FastAPI application."""
    settings = settings or get_settings()
    server = settings.server
    verifier = _resolve_admin_verifier(settings)
    sessions = SessionStore(server.session_ttl_minutes * 60,
                            _session_secret(settings))
    throttle = LoginThrottle(server.max_login_attempts,
                             server.lockout_seconds)

    app = FastAPI(title="Research Toolkit Admin", docs_url=None,
                  redoc_url=None, openapi_url=None)

    # ---- auth helpers ---------------------------------------------------
    def _session_from(request: Request) -> Session | None:
        raw = request.cookies.get(SESSION_COOKIE)
        if not raw:
            return None
        session_id = sessions.unsign(raw)
        if not session_id:
            return None
        session = sessions.get(session_id)
        if session is None:
            return None
        # Bind the session to the client fingerprint; a stolen cookie used
        # from another address/user-agent is rejected.
        if session.ip != _client_ip(request):
            return None
        if session.user_agent != _user_agent(request):
            return None
        return session

    def _require_session(request: Request) -> Session:
        session = _session_from(request)
        if session is None:
            raise HTTPException(status_code=401, detail="authentication required")
        return session

    def _check_csrf(request: Request, session: Session,
                    form: dict[str, str] | None = None) -> None:
        token = request.headers.get(server.csrf_header)
        if not token and form:
            token = form.get("csrf")
        if not token or not hmac.compare_digest(token, session.csrf):
            raise HTTPException(status_code=403, detail="invalid CSRF token")

    def _set_cookie(response: Any, session: Session) -> None:
        secure = bool(server.cookie_secure)
        response.set_cookie(
            SESSION_COOKIE, sessions.sign(session.session_id),
            max_age=sessions.ttl, httponly=True, samesite="strict",
            secure=secure, path="/",
        )

    # ---- middleware: security headers ----------------------------------
    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        response = await call_next(request)
        headers = response.headers
        headers["X-Content-Type-Options"] = "nosniff"
        headers["X-Frame-Options"] = "DENY"
        headers["Referrer-Policy"] = "no-referrer"
        headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        headers.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; "
            "img-src 'self' data:; form-action 'self'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )
        headers.setdefault("Cache-Control", "no-store")
        return response

    # ---- authentication -------------------------------------------------
    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        if _session_from(request):
            return RedirectResponse("/", status_code=303)
        return HTMLResponse(_login_page())

    @app.post("/login")
    async def login(request: Request):
        ip = _client_ip(request)
        wait = throttle.blocked_for(ip)
        if wait:
            return HTMLResponse(
                _login_page(f"Too many attempts. Try again in {wait}s."),
                status_code=429, headers={"Retry-After": str(wait)})
        form = await _read_form(request)
        password = form.get("password", "")
        if not password or not verify_password(password, verifier):
            throttle.fail(ip)
            logger.warning("Failed admin login from {}", ip)
            return HTMLResponse(_login_page("Invalid password."),
                                status_code=401)
        throttle.success(ip)
        session = sessions.create(ip, _user_agent(request))
        response = RedirectResponse("/", status_code=303)
        _set_cookie(response, session)
        return response

    @app.post("/api/auth/login")
    async def api_login(request: Request):
        ip = _client_ip(request)
        wait = throttle.blocked_for(ip)
        if wait:
            return JSONResponse(
                {"error": "too many attempts", "retry_after": wait},
                status_code=429, headers={"Retry-After": str(wait)})
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="invalid JSON body")
        password = str(payload.get("password", ""))
        if not password or not verify_password(password, verifier):
            throttle.fail(ip)
            return JSONResponse({"error": "invalid password"}, status_code=401)
        throttle.success(ip)
        session = sessions.create(ip, _user_agent(request))
        response = JSONResponse({"authenticated": True,
                                 "csrf_token": session.csrf,
                                 "expires_in": sessions.ttl})
        _set_cookie(response, session)
        return response

    @app.get("/api/me")
    def api_me(request: Request):
        session = _session_from(request)
        if session is None:
            return JSONResponse({"authenticated": False}, status_code=401)
        return {"authenticated": True, "csrf_token": session.csrf,
                "expires_in": sessions.ttl}

    @app.post("/logout")
    async def logout(request: Request):
        session = _session_from(request)
        if session is not None:
            form = await _read_form(request)
            _check_csrf(request, session, form)
            sessions.destroy(session.session_id)
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @app.post("/api/auth/logout")
    def api_logout(request: Request):
        session = _require_session(request)
        _check_csrf(request, session)
        sessions.destroy(session.session_id)
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    # ---- pages & files --------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        session = _session_from(request)
        if session is not None:
            return HTMLResponse(_dashboard(settings, session))
        if server.allow_public_read:
            return HTMLResponse(_public_index(settings))
        return RedirectResponse("/login", status_code=303)

    @app.get("/papers/{file_path:path}")
    def serve_paper(file_path: str, request: Request):
        session = _session_from(request)
        if session is None and not server.allow_public_read:
            return RedirectResponse("/login", status_code=303)
        allowed = ADMIN_EXTS if session is not None else PUBLIC_EXTS
        path = _safe_file(settings.papers_path, file_path, allowed)
        if path is None:
            raise HTTPException(status_code=404, detail="not found")
        response = FileResponse(path, media_type=_media_type(path))
        if path.suffix.lower() == ".html":
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "img-src 'self' data:; base-uri 'none'; "
                "frame-ancestors 'none'")
        return response

    @app.get("/reports/{file_path:path}")
    def serve_report(file_path: str, request: Request):
        _require_session(request)
        path = _safe_file(settings.reports_path, file_path, ADMIN_EXTS)
        if path is None:
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(path, media_type=_media_type(path))

    # ---- read-only JSON API --------------------------------------------
    def _library() -> PaperLibrary:
        return PaperLibrary(settings.papers_path,
                            author=settings.papers.author,
                            default_status=settings.papers.default_status)

    @app.get("/api/papers")
    def api_papers(request: Request):
        _require_session(request)
        return {"papers": [record.model_dump(mode="json")
                           for record in _library().records()]}

    @app.get("/api/reports")
    def api_reports(request: Request):
        _require_session(request)
        files = sorted(
            (p for p in settings.reports_path.glob("*") if p.is_file()),
            key=lambda p: p.stat().st_mtime, reverse=True)
        return {"reports": [
            {"name": p.name, "size": p.stat().st_size,
             "modified": p.stat().st_mtime}
            for p in files
        ]}

    @app.get("/api/config")
    def api_config(request: Request):
        _require_session(request)
        return mask_config(settings.model_dump())

    # ---- state-changing actions ----------------------------------------
    def _error_page(message: str, status: int = 400) -> HTMLResponse:
        body = (f'<div class="card"><p class="error">{_esc(message)}</p>'
                '<p><a href="/">Back to dashboard</a></p></div>')
        return HTMLResponse(_render_page("Error", body), status_code=status)

    def _execute_run(target: str, engine: str, fmt: str) -> Path:
        orch = Orchestrator(settings)
        try:
            if engine and engine != "full":
                report = orch.run_engine(engine, target)
            else:
                report = orch.run_full(target)
            return write_report(report, fmt, settings.reports_path,
                                encrypt=settings.reporting.encrypt)
        finally:
            orch.close()

    @app.post("/run")
    async def run_form(request: Request):
        session = _require_session(request)
        form = await _read_form(request)
        _check_csrf(request, session, form)
        target = (form.get("target") or "").strip()
        if not target:
            return _error_page("Target is required.")
        engine = (form.get("engine") or "full").strip()
        fmt = (form.get("format") or "markdown").strip()
        try:
            path = await run_in_threadpool(_execute_run, target, engine, fmt)
        except Exception:  # noqa: BLE001 - surface a safe message
            logger.exception("server run failed")
            return _error_page("Run failed (see server logs).", status=500)
        return RedirectResponse(f"/reports/{path.name}", status_code=303)

    @app.post("/api/run")
    async def api_run(request: Request):
        session = _require_session(request)
        _check_csrf(request, session)
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="invalid JSON body")
        target = str(payload.get("target", "")).strip()
        if not target:
            raise HTTPException(status_code=400, detail="target is required")
        engine = str(payload.get("engine", "full")).strip()
        fmt = str(payload.get("format", "markdown")).strip()
        try:
            path = await run_in_threadpool(_execute_run, target, engine, fmt)
        except Exception:  # noqa: BLE001
            logger.exception("api run failed")
            raise HTTPException(status_code=500, detail="Internal error")
        return {"report": path.name}

    @app.post("/publish")
    async def publish_form(request: Request):
        session = _require_session(request)
        form = await _read_form(request)
        _check_csrf(request, session, form)
        name = (form.get("from_report") or "").strip()
        source = _safe_file(settings.reports_path, name, ADMIN_EXTS)
        if source is None:
            return _error_page("Report not found.", status=404)
        try:
            report, _meta = load_report_file(source)
            formats = [f.strip() for f in
                       (form.get("formats") or "markdown").split(",")
                       if f.strip()]
            title = (form.get("title") or "").strip() or None
            _library().publish(report, formats=formats, title=title,
                               include_raw=False, source_report=str(source))
        except Exception:  # noqa: BLE001
            logger.exception("server publish failed")
            return _error_page("Publish failed (see server logs).", status=500)
        return RedirectResponse("/", status_code=303)

    @app.post("/archive")
    async def archive_form(request: Request):
        session = _require_session(request)
        form = await _read_form(request)
        _check_csrf(request, session, form)
        paper_id = (form.get("paper_id") or "").strip()
        if not paper_id:
            return _error_page("paper_id is required.")
        try:
            _library().archive(paper_id)
        except FileNotFoundError as exc:
            return _error_page(str(exc), status=404)
        except Exception:  # noqa: BLE001
            logger.exception("server archive failed")
            return _error_page("Archive failed (see server logs).", status=500)
        return RedirectResponse("/", status_code=303)

    @app.post("/purge")
    async def purge_form(request: Request):
        session = _require_session(request)
        form = await _read_form(request)
        _check_csrf(request, session, form)
        if form.get("confirm") not in {"yes", "on", "true", "1"}:
            return _error_page("Confirmation is required.")
        try:
            summary = purge_tool_data(settings)
        except Exception:  # noqa: BLE001
            logger.exception("server purge failed")
            return _error_page("Purge failed (see server logs).", status=500)
        logger.info("admin purge completed: {}", summary)
        return RedirectResponse("/", status_code=303)

    return app


def run_server(settings: Settings | None = None,
               host: str | None = None, port: int | None = None) -> None:
    """Run the admin server with uvicorn (blocking)."""
    settings = settings or get_settings()
    import uvicorn  # imported lazily so the CLI stays usable without it

    app = create_app(settings)
    uvicorn.run(app, host=host or settings.server.host,
                port=port or settings.server.port, log_level="info")


__all__ = [
    "create_app", "run_server", "hash_password", "verify_password",
    "mask_config", "SessionStore", "LoginThrottle",
]
