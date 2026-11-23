# Security Policy

This document describes the security model of the Credential Research Toolkit,
the guarantees the code is expected to keep, and how to report a vulnerability.

The toolkit handles personal data and API credentials, so the design assumes
that **anything shipped to a browser or committed to a public repository is
public**. Every control below exists to keep secrets, credentials and the full
research database out of those channels.

---

## 1. Reporting a vulnerability

Please **do not** open a public issue for a security problem.

- Open a private security advisory on the repository
  (`Security` → `Advisories` → `Report a vulnerability`), or
- Email the maintainer with a description, reproduction steps and the affected
  version/commit.

We aim to acknowledge reports within 5 working days. Please give us a
reasonable window to ship a fix before any public disclosure.

---

## 2. Guarantees the code must keep

### 2.1 No API keys in client code or generated output

- Secrets are read from environment variables or `config.yaml`, never hardcoded.
- The static site under `docs/` and every generated HTML page contain **no**
  credentials and make **no** API calls.
- `python -m research_tool config` masks every secret field
  (`research_tool/utils/masking.py`).
- Log records are redacted (`research_tool/logger.py`): emails, phone numbers,
  `key=value` secrets, `Bearer`/`ApiKey` headers, `ghp_`/`sk-` tokens and
  proxy credentials (`user:pass@host`).
- Engine HTTP caches key on a **redacted** URL
  (`research_tool/engines/base.py::_safe_cache_key`), so an API key passed as a
  query parameter never lands in the SQLite cache.

### 2.2 Admin access is verified on the server

The toolkit ships an optional FastAPI admin server (`research_tool/server.py`,
started with `python -m research_tool serve`). It is the only supported way to
expose the toolkit over HTTP.

- The admin password is verified server-side against a salted
  **PBKDF2-HMAC-SHA256** digest (200 000+ iterations) using
  `hmac.compare_digest`.
- The password may be supplied as `RESEARCH_ADMIN_PASSWORD` or, preferably, as a
  pre-computed verifier in `RESEARCH_ADMIN_PASSWORD_HASH`
  (`python -m research_tool hash-password`).
- Sessions are random 256-bit identifiers stored server-side, delivered in an
  `HttpOnly`, `SameSite=Strict` cookie (`Secure` when served over HTTPS).
- Every state-changing request requires a synchronizer CSRF token.
- Login attempts are rate-limited per client IP and lock out after repeated
  failures.
- **There is no `localStorage` flag, cookie or header that grants admin
  access.** Changing `isAdmin` in DevTools does nothing; the server ignores all
  client-supplied role state.

### 2.3 No full public database

- `github.enabled` defaults to `false`, `github.visibility` defaults to
  `private`, and `github.pages` / `github.host_reports` default to `false`.
- `github host` excludes raw `.json` database dumps unless `--raw-json` is
  passed explicitly.
- The committed `.gitignore` keeps `data/cache/`, `data/raw/`, `*.db`,
  `*.sqlite*`, `.env*`, `papers/INDEX.json`, `papers/**/*.json` and
  `papers/**/*.meta.json` out of Git.
- Anonymous readers of the admin server only ever see curated `.md`/`.pdf`
  views; bulk catalogues (`/api/papers`, `/api/config`), raw JSON and engine
  controls require an authenticated session. With `server.allow_public_read:
  false` (the default) everything requires a session.

### 2.4 Defence in depth

| Risk | Control |
|---|---|
| Stored/reflected XSS | `safe_href()` allows only `http`/`https`/`mailto`/relative links; `javascript:`, `data:`, `vbscript:` and `file:` are neutralised. Generated pages carry a strict CSP. |
| Path traversal | Report stems are slugified; every write is resolved and checked with `is_relative_to()` (`reporters/__init__.py`, `utils/library.py`, `server.py`). |
| SSRF | `is_safe_url()` blocks loopback, link-local, RFC1918, multicast and non-HTTP(S) targets unless explicitly allowed. |
| XML bombs / XXE | Sanctions XML is size-bounded and rejected if it contains `<!DOCTYPE` or `<!ENTITY`. |
| Spreadsheet formula injection | Cells beginning with `=`, `+`, `-`, `@`, tab or CR are prefixed with `'` in the Excel export. |
| Weak cache encryption | `cache.encrypt: true` fails fast when `RESEARCH_ENCRYPTION_KEY` is missing instead of silently caching plaintext. |
| Unpinned third-party JS | Generated pages and committed docs contain no external scripts or CDNs. |

---

## 3. Running the security suite

```powershell
python tests/test_security.py
```

The suite is offline and covers secret scanning, config masking, log redaction,
admin authentication (PBKDF2, sessions, CSRF, rate limiting, forged cookies),
public-database exposure, XSS, path traversal, SSRF, XML bombs, Excel injection
and cache encryption. It runs on every push and pull request via
`.github/workflows/security.yml`.

---

## 4. Hardening checklist for deployments

- [ ] Serve the admin server over HTTPS and set `server.cookie_secure: true`.
- [ ] Set `RESEARCH_ADMIN_PASSWORD_HASH` (not a plaintext password) and a stable
      `RESEARCH_SESSION_SECRET`.
- [ ] Keep `server.allow_public_read: false` unless you deliberately want a
      read-only public view.
- [ ] Keep the GitHub repository **private** and `github.host_reports: false`.
- [ ] Rotate any API key that was ever committed to a public repository.
- [ ] Run `python -m research_tool config` after configuration changes and
      confirm no secret is printed.
- [ ] Review `git ls-files` for `*.json`, `*.db`, `*.env` and `.pem` files before
      publishing a repository.
