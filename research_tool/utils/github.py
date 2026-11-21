"""Publish research output to GitHub (repository + GitHub Pages).

The toolkit keeps its output on disk: ``data/reports/`` holds raw findings and
``data/papers/`` holds finalized papers. This module is an *opt-in* bridge that
**hosts** that output on GitHub - it builds a small static site from the reports
(and papers), commits it to a repository and serves it through GitHub Pages.

Design notes
------------
* No new dependencies - it speaks the GitHub REST API with ``requests``.
* Nothing is uploaded unless the caller explicitly runs ``github host``. The
  engines and ``publish`` never touch the network on their own.
* Commits are atomic: a run writes every file in a single commit through the
  Git Data API (blobs -> tree -> commit -> ref), never one commit per file.
* A token is resolved from ``RESEARCH_GITHUB_TOKEN`` / ``GH_TOKEN`` /
  ``GITHUB_TOKEN`` or the ``gh`` CLI (``gh auth token``) and is never logged.

This module deliberately contains no anti-forensic behaviour: publishing is an
accountable, explicit act that uploads report content under the operator's own
GitHub identity.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import requests

from ..config import Settings
from ..logger import logger

GITHUB_API = "https://api.github.com"
DEFAULT_SITE_DIR = "docs"
DEFAULT_REMOTE = "origin"
TOKEN_ENV_VARS = ("RESEARCH_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")

# Report/paper files that can be hosted. ``.enc`` blobs are never published.
REPORT_EXTS = {".md", ".markdown", ".json", ".pdf", ".xlsx"}
PAPER_EXTS = {".md", ".markdown", ".json", ".pdf"}


class GitHubError(RuntimeError):
    """Raised for any GitHub API / configuration problem."""


# ---------------------------------------------------------------------------
# Credentials & small helpers
# ---------------------------------------------------------------------------
def resolve_token(explicit: str | None = None) -> str | None:
    """Return a GitHub token, or ``None``.

    Order: *explicit* argument, then ``RESEARCH_GITHUB_TOKEN`` / ``GH_TOKEN`` /
    ``GITHUB_TOKEN``, then the ``gh`` CLI's stored token (``gh auth token``).
    """
    if explicit and explicit.strip():
        return explicit.strip()
    for name in TOKEN_ENV_VARS:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    try:
        proc = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    token = proc.stdout.strip()
    return token or None


def pages_url(owner: str, repo: str) -> str:
    """Return the GitHub Pages URL for ``owner/repo``."""
    return f"https://{owner.lower()}.github.io/{repo}/"


def repo_slug(owner: str, repo: str) -> str:
    """Return the canonical ``owner/repo`` slug."""
    return f"{owner}/{repo}"


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _esc_attr(text: str) -> str:
    return _esc(text).replace('"', "&quot;")


# ---------------------------------------------------------------------------
# Markdown -> HTML (a deliberately small, safe subset)
# ---------------------------------------------------------------------------
# It only needs to render what the toolkit's own MarkdownReporter /
# PaperReporter emit: headings, blockquotes, pipe tables, bullet lists,
# fenced code and the inline bold/italic/code/link/autolink forms.
_INLINE_RE = re.compile(
    r"`([^`]+)`"
    r"|\[([^\]]+)\]\(([^)\s]+)\)"
    r"|<(https?://[^>\s]+)>"
    r"|\*\*([^*]+)\*\*"
    r"|\*([^*\s][^*]*?)\*"
)


def _inline(text: str) -> str:
    """Render inline Markdown (escaping everything else)."""
    out: list[str] = []
    last = 0
    for match in _INLINE_RE.finditer(text):
        out.append(_esc(text[last:match.start()]))
        code, label, href, autolink, bold, italic = match.groups()
        if code is not None:
            out.append(f"<code>{_esc(code)}</code>")
        elif label is not None:
            out.append(f'<a href="{_esc_attr(href)}">{_inline(label)}</a>')
        elif autolink is not None:
            out.append(f'<a href="{_esc_attr(autolink)}">{_esc(autolink)}</a>')
        elif bold is not None:
            out.append(f"<strong>{_inline(bold)}</strong>")
        else:
            out.append(f"<em>{_inline(italic)}</em>")
        last = match.end()
    out.append(_esc(text[last:]))
    return "".join(out)


def _split_row(row: str) -> list[str]:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [cell.strip().replace("\\|", "|")
            for cell in re.split(r"(?<!\\)\|", row)]


def _table_html(header: list[str], body: list[list[str]]) -> str:
    parts = ["<table><thead><tr>"]
    parts += [f"<th>{_inline(cell)}</th>" for cell in header]
    parts.append("</tr></thead><tbody>")
    for row in body:
        parts.append("<tr>")
        parts += [f"<td>{_inline(cell)}</td>" for cell in row]
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def markdown_to_html(text: str) -> str:
    """Convert the toolkit's Markdown subset to a safe HTML fragment."""
    lines = str(text).replace("\r\n", "\n").split("\n")
    out: list[str] = []
    list_open = False
    code_open = False
    code_lang = ""
    code_buf: list[str] = []
    index = 0
    total = len(lines)

    def close_list() -> None:
        nonlocal list_open
        if list_open:
            out.append("</ul>")
            list_open = False

    while index < total:
        line = lines[index]
        stripped = line.strip()

        if stripped.startswith("```"):
            if code_open:
                cls = (f' class="language-{_esc_attr(code_lang)}"'
                       if code_lang else "")
                out.append(
                    f"<pre><code{cls}>{_esc(chr(10).join(code_buf))}</code></pre>")
                code_open, code_lang, code_buf = False, "", []
            else:
                close_list()
                code_open, code_lang, code_buf = True, stripped[3:].strip(), []
            index += 1
            continue
        if code_open:
            code_buf.append(line)
            index += 1
            continue

        # pipe table (needs a delimiter row immediately after the header)
        if (stripped.startswith("|") and index + 1 < total
                and re.match(r"^\|[\s:\-|]+\|$", lines[index + 1].strip())):
            close_list()
            header = _split_row(stripped)
            body: list[list[str]] = []
            cursor = index + 2
            while cursor < total and lines[cursor].strip().startswith("|"):
                body.append(_split_row(lines[cursor].strip()))
                cursor += 1
            out.append(_table_html(header, body))
            index = cursor
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            close_list()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            index += 1
            continue

        if stripped.startswith(">"):
            close_list()
            quoted: list[str] = []
            while index < total and lines[index].strip().startswith(">"):
                quoted.append(lines[index].strip()[1:].strip())
                index += 1
            out.append(f"<blockquote>{_inline(' '.join(quoted))}</blockquote>")
            continue

        bullet = re.match(r"^[-*+]\s+(.*)$", stripped)
        if bullet:
            if not list_open:
                out.append("<ul>")
                list_open = True
            out.append(f"<li>{_inline(bullet.group(1))}</li>")
            index += 1
            continue

        if not stripped:
            close_list()
            index += 1
            continue

        close_list()
        out.append(f"<p>{_inline(stripped)}</p>")
        index += 1

    if code_open:
        out.append(f"<pre><code>{_esc(chr(10).join(code_buf))}</code></pre>")
    close_list()
    return "\n".join(out)


_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; font: 16px/1.55 -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
       color: #1f2328; background: #ffffff; }
header { background: #0d1117; color: #f0f6fc; padding: 1.4rem 1.6rem; }
header h1 { margin: 0 0 .25rem; font-size: 1.5rem; }
header p { margin: 0; color: #adbac7; font-size: .92rem; }
main { max-width: 62rem; margin: 0 auto; padding: 1.6rem; }
nav { font-size: .9rem; margin: .4rem 0 1.2rem; }
nav a { margin-right: .9rem; }
a { color: #0969da; text-decoration: none; }
a:hover { text-decoration: underline; }
h1, h2, h3 { line-height: 1.25; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: .93rem; }
th, td { border: 1px solid #d0d7de; padding: .4rem .55rem; text-align: left; vertical-align: top; }
th { background: #f6f8fa; }
code { background: #eff1f3; padding: .1rem .3rem; border-radius: 4px; font-size: .9em; }
pre { background: #f6f8fa; padding: .8rem; border-radius: 8px; overflow-x: auto; }
pre code { background: none; padding: 0; }
blockquote { margin: 1rem 0; padding: .3rem 1rem; border-left: 4px solid #d0d7de; color: #57606a; }
.pill { display: inline-block; padding: .05rem .5rem; border-radius: 999px;
        font-size: .78rem; font-weight: 600; }
.risk-NONE, .risk-LOW { background: #dafbe1; color: #1a7f37; }
.risk-MEDIUM { background: #fff8c5; color: #7d4e00; }
.risk-HIGH { background: #ffebe9; color: #cf222e; }
footer { border-top: 1px solid #d0d7de; margin-top: 2rem; padding: 1rem 1.6rem;
         color: #57606a; font-size: .85rem; }
"""


def html_document(title: str, body: str, *, subtitle: str = "",
                  nav: str = "") -> str:
    """Wrap an HTML fragment in a small, self-contained styled document."""
    sub = f"<p>{_esc(subtitle)}</p>" if subtitle else ""
    nav_html = f"<nav>{nav}</nav>" if nav else ""
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<meta name=\"robots\" content=\"noindex\">\n"
        f"<title>{_esc(title)}</title>\n<style>{_CSS}</style>\n</head>\n<body>\n"
        f"<header><h1>{_esc(title)}</h1>{sub}</header>\n"
        f"<main>{nav_html}{body}</main>\n"
        "<footer>Hosted with the Credential Research Toolkit. Findings are "
        "corroborated by public sources; absence of a finding is not proof of "
        "absence.</footer>\n</body>\n</html>\n"
    )


def _risk_pill(score: int, label: str | None = None) -> str:
    name = (label or "").upper()
    if name not in ("NONE", "LOW", "MEDIUM", "HIGH"):
        from ..analyzers.risk_scorer import RiskScorer
        name = RiskScorer.label(score)
    return f'<span class="pill risk-{name}">{score}/100 {name}</span>'


def _sorted_entries(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(list(entries),
                  key=lambda e: (e.get("kind", ""), str(e.get("date", "")),
                                 e.get("name", "")),
                  reverse=True)


def build_index_html(entries: Iterable[dict[str, Any]], *, title: str,
                     generated_at: datetime | None = None,
                     subtitle: str = "") -> str:
    """Build the landing page whose table links every hosted item."""
    stamp = (generated_at or datetime.utcnow()).strftime("%Y-%m-%d %H:%M UTC")
    rows = _sorted_entries(entries)
    body: list[str] = [
        f"<p><strong>{len(rows)}</strong> item(s) hosted · "
        f"generated {_esc(stamp)}.</p>",
        "<table><thead><tr><th>Kind</th><th>Item</th><th>Target</th>"
        "<th>Date</th><th>Risk</th><th>Findings</th><th>Links</th>"
        "</tr></thead><tbody>",
    ]
    for entry in rows:
        links: list[str] = []
        if entry.get("page"):
            links.append(f'<a href="{_esc_attr(entry["page"])}">read</a>')
        if entry.get("raw"):
            links.append(f'<a href="{_esc_attr(entry["raw"])}">raw</a>')
        risk = entry.get("risk")
        risk_html = (_risk_pill(int(risk), entry.get("risk_label"))
                     if risk is not None else "—")
        body.append(
            "<tr>"
            f"<td>{_esc(entry.get('kind', ''))}</td>"
            f"<td>{_esc(entry.get('name', ''))}</td>"
            f"<td>{_esc(entry.get('target', '') or '—')}</td>"
            f"<td>{_esc(entry.get('date', '') or '—')}</td>"
            f"<td>{risk_html}</td>"
            f"<td>{entry.get('findings', '—')}</td>"
            f"<td>{' · '.join(links) or '—'}</td>"
            "</tr>")
    body.append("</tbody></table>")
    return html_document(title, "\n".join(body), subtitle=subtitle,
                         nav=f'<a href="./">{_esc("All items")}</a>')


def build_index_markdown(entries: Iterable[dict[str, Any]], *, title: str,
                         generated_at: datetime | None = None) -> str:
    """Build a Markdown companion index (``docs/README.md``)."""
    stamp = (generated_at or datetime.utcnow()).strftime("%Y-%m-%d %H:%M UTC")
    rows = _sorted_entries(entries)
    lines = [
        f"# {title}", "",
        "> **Auto-generated by `python -m research_tool github host`.** "
        f"Generated {stamp} · {len(rows)} item(s).", "",
        "| Kind | Item | Target | Date | Risk | Findings | Links |",
        "|---|---|---|---|---:|---:|---|",
    ]
    for entry in rows:
        links: list[str] = []
        if entry.get("page"):
            links.append(f"[read]({entry['page']})")
        if entry.get("raw"):
            links.append(f"[raw]({entry['raw']})")
        lines.append(
            f"| {_esc_md(entry.get('kind'))} | {_esc_md(entry.get('name'))} "
            f"| {_esc_md(entry.get('target')) or '—'} "
            f"| {entry.get('date') or '—'} | {entry.get('risk', '—')} "
            f"| {entry.get('findings', '—')} | {' · '.join(links) or '—'} |")
    lines += ["", "Reports are raw engine output; papers are finalized, "
              "reviewed write-ups. Organisation rules: "
              "`data/papers/ORGANISATION.md`.", ""]
    return "\n".join(lines)


def _esc_md(text: object) -> str:
    return (str(text or "").replace("|", "\\|").replace("\n", " ").strip())


# ---------------------------------------------------------------------------
# GitHub REST client (a thin, explicit wrapper - no hidden side effects)
# ---------------------------------------------------------------------------
class GitHubClient:
    """Minimal GitHub REST client used by the ``github`` CLI commands.

    The ``session`` argument is injectable so the behaviour is testable
    offline with a fake transport.
    """

    def __init__(self, token: str, owner: str | None = None, repo: str = "",
                 branch: str = "main", *, timeout: int = 30,
                 session: requests.Session | None = None,
                 user_agent: str = "research-tool"):
        self.token = (token or "").strip()
        self.owner = owner
        self.repo = repo
        self.branch = branch or "main"
        self.timeout = timeout
        self.user_agent = user_agent
        self._session = session or requests.Session()

    # ---- low level ----------------------------------------------------
    def _slug(self) -> str:
        if not (self.owner and self.repo):
            raise GitHubError(
                "GitHub owner/repo is not configured. Set github.owner and "
                "github.repo in config.yaml (or RESEARCH_GITHUB_OWNER / "
                "RESEARCH_GITHUB_REPO).")
        return repo_slug(self.owner, self.repo)

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": self.user_agent,
        }

    def request(self, method: str, path: str, *, expect: tuple[int, ...] = (200,),
                tolerate: tuple[int, ...] = (), **kwargs) -> requests.Response:
        """Send a request and raise a readable :class:`GitHubError` on failure."""
        if not self.token:
            raise GitHubError(
                "No GitHub token available. Export RESEARCH_GITHUB_TOKEN "
                "(or GITHUB_TOKEN), or run 'gh auth login' so 'gh auth token' "
                "works, then retry.")
        url = path if path.startswith("http") else f"{GITHUB_API}{path}"
        try:
            resp = self._session.request(method, url, headers=self._headers(),
                                         timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise GitHubError(f"GitHub request failed ({method} {path}): {exc}") from exc
        if resp.status_code in tolerate or resp.status_code in expect:
            return resp
        raise GitHubError(
            f"GitHub API {method} {path} -> {resp.status_code}: "
            f"{self._detail(resp)}")

    @staticmethod
    def _detail(resp: requests.Response) -> str:
        try:
            payload = resp.json()
        except (ValueError, AttributeError):
            return (resp.text or "").strip()[:300] or "no response body"
        if isinstance(payload, dict):
            msg = payload.get("message", "")
            errors = payload.get("errors")
            if errors:
                return f"{msg} ({errors})"[:400]
            return msg or "unexpected response"
        return str(payload)[:300]

    # ---- identity & repository ---------------------------------------
    def whoami(self) -> str:
        """Return the login of the authenticated user."""
        data = self.request("GET", "/user").json()
        return data["login"]

    def repo_exists(self) -> bool:
        """True when ``owner/repo`` already exists and is reachable."""
        slug = self._slug()
        resp = self.request("GET", f"/repos/{slug}", tolerate=(404,))
        return resp.status_code == 200

    def create_repo(self, *, private: bool = False, description: str = "",
                    homepage: str = "") -> dict[str, Any]:
        """Create ``owner/repo`` (idempotent: returns {} if it already exists)."""
        if not self.owner:
            self.owner = self.whoami()
        if self.repo_exists():
            return {}
        payload: dict[str, Any] = {
            "name": self.repo,
            "private": bool(private),
            "has_issues": True,
            "has_wiki": False,
            "auto_init": False,
        }
        if description:
            payload["description"] = description
        if homepage:
            payload["homepage"] = homepage
        if self.owner.lower() != self.whoami().lower():
            return self.request("POST", f"/orgs/{self.owner}/repos",
                                expect=(201,), json=payload).json()
        return self.request("POST", "/user/repos", expect=(201,),
                            json=payload).json()

    def default_branch(self) -> str:
        return self.request("GET", f"/repos/{self._slug()}").json().get(
            "default_branch", self.branch)

    def remote_url(self) -> str:
        return f"https://github.com/{self._slug()}.git"

    # ---- writing (Git Data API: one atomic commit) --------------------
    def _head_sha(self, branch: str) -> str | None:
        """Return the tip commit of *branch* (``None`` for an empty repo)."""
        resp = self.request("GET", f"/repos/{self._slug()}/git/ref/heads/{branch}",
                            tolerate=(404, 409))
        if resp.status_code != 200:
            return None
        return resp.json().get("object", {}).get("sha")

    def commit_files(self, files: dict[str, bytes | str], message: str,
                     branch: str | None = None) -> str:
        """Commit *files* (repo-relative path -> content) in one commit.

        Returns the new commit SHA. Works for both an existing branch and a
        brand-new (empty) repository.
        """
        slug = self._slug()
        branch = branch or self.branch
        parent = self._head_sha(branch)
        base_tree: str | None = None
        if parent:
            commit_obj = self.request(
                "GET", f"/repos/{slug}/git/commits/{parent}").json()
            base_tree = commit_obj.get("tree", {}).get("sha")

        tree: list[dict[str, str]] = []
        for path, content in files.items():
            data = content if isinstance(content, bytes) else str(content).encode("utf-8")
            blob = self.request(
                "POST", f"/repos/{slug}/git/blobs", expect=(201,),
                json={"content": base64.b64encode(data).decode("ascii"),
                      "encoding": "base64"}).json()
            tree.append({"path": path.replace("\\", "/"), "mode": "100644",
                         "type": "blob", "sha": blob["sha"]})

        tree_payload: dict[str, Any] = {"tree": tree}
        if base_tree:
            tree_payload["base_tree"] = base_tree
        new_tree = self.request("POST", f"/repos/{slug}/git/trees",
                                expect=(201,), json=tree_payload).json()["sha"]

        new_commit = self.request(
            "POST", f"/repos/{slug}/git/commits", expect=(201,),
            json={"message": message, "tree": new_tree,
                  "parents": [parent] if parent else []}).json()

        if parent:
            self.request("PATCH", f"/repos/{slug}/git/refs/heads/{branch}",
                         json={"sha": new_commit["sha"], "force": False})
        else:
            self.request("POST", f"/repos/{slug}/git/refs", expect=(201,),
                         json={"ref": f"refs/heads/{branch}",
                               "sha": new_commit["sha"]})
        logger.info("[github] committed {} file(s) to {}/{}@{}",
                    len(files), self.owner, self.repo, branch)
        return new_commit["sha"]

    # ---- GitHub Pages -------------------------------------------------
    def pages(self) -> dict[str, Any] | None:
        """Return the Pages site object, or ``None`` when Pages is off."""
        resp = self.request("GET", f"/repos/{self._slug()}/pages",
                            tolerate=(404,))
        return resp.json() if resp.status_code == 200 else None

    def enable_pages(self, *, branch: str | None = None,
                     path: str = "/docs") -> dict[str, Any] | None:
        """Create or update the Pages site to serve ``path`` on ``branch``.

        Returns the resulting Pages object (or ``None`` if the API accepted the
        update without returning a body). Raises :class:`GitHubError` on a real
        failure (e.g. a private repo on a plan without private Pages).
        """
        slug = self._slug()
        branch = branch or self.branch
        source = {"branch": branch,
                  "path": path if path.startswith("/") else f"/{path}"}
        existing = self.pages()
        if existing is None:
            resp = self.request("POST", f"/repos/{slug}/pages",
                                expect=(201, 204), tolerate=(409,),
                                json={"source": source})
            if resp.status_code == 409:      # already enabled - update it
                resp = self.request("PUT", f"/repos/{slug}/pages",
                                    expect=(204,), json={"source": source})
        else:
            resp = self.request("PUT", f"/repos/{slug}/pages",
                                expect=(204,), json={"source": source})
        try:
            return resp.json()
        except (ValueError, AttributeError):
            return self.pages()

# ---------------------------------------------------------------------------
# Git helpers (used when a git remote is configured)
# ---------------------------------------------------------------------------
def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, timeout=180, check=False)


def git_available() -> bool:
    """True when a ``git`` executable is on PATH."""
    try:
        return _git(["--version"], Path.cwd()).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def git_remote_url(repo_root: Path, remote: str = DEFAULT_REMOTE) -> str | None:
    """Return the URL of *remote* configured in *repo_root*, or ``None``."""
    try:
        proc = _git(["remote", "get-url", remote], repo_root)
    except (OSError, subprocess.SubprocessError):
        return None
    url = proc.stdout.strip()
    return url if proc.returncode == 0 and url else None


# ---------------------------------------------------------------------------
# Collecting reports / papers into a hostable site
# ---------------------------------------------------------------------------
@dataclass
class HostedFile:
    """One report/paper file selected for hosting."""

    source: Path
    kind: str                       # "report" | "paper"
    rel: str                        # site-relative POSIX path of the raw file
    page: str | None = None         # site-relative POSIX path of its HTML page
    entry: dict[str, Any] = field(default_factory=dict)


def _base_entry(path: Path, kind: str, page: str | None,
                raw: str) -> dict[str, Any]:
    return {"kind": kind, "name": path.name, "target": "", "date": "",
            "risk": None, "risk_label": None, "findings": None,
            "page": page, "raw": raw}


def _enrich_from_json(entry: dict[str, Any], path: Path) -> None:
    """Fill *entry* from a report/paper JSON document (best effort)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    meta: dict[str, Any] | None = None
    if isinstance(data, dict) and isinstance(data.get("report"), dict):
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else None
        data = data["report"]
    if not isinstance(data, dict):
        return
    source = meta or data
    entry["target"] = source.get("target") or entry["target"]
    stamp = source.get("created_at") or source.get("generated_at") or ""
    entry["date"] = str(stamp)[:10] or entry["date"]
    if source.get("risk_score") is not None:
        entry["risk"] = source["risk_score"]
        entry["risk_label"] = source.get("risk_label")
    if meta and meta.get("findings") is not None:
        entry["findings"] = meta["findings"]
    elif isinstance(data.get("findings"), list):
        entry["findings"] = len(data["findings"])


_RISK_MD_RE = re.compile(r"Risk score[^\d]{0,6}(\d{1,3})\s*/\s*100(?:\s*\(([A-Z]+)\))?")
_FINDINGS_MD_RE = re.compile(r"Findings[^\d]{0,6}(\d{1,4})")
_DATE_MD_RE = re.compile(r"(?:Generated|Published \(UTC\))[^\d]{0,8}(\d{4}-\d{2}-\d{2})")


def _enrich_from_markdown(entry: dict[str, Any], text: str) -> None:
    """Fill *entry* from the rendered Markdown (best effort)."""
    heading = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if heading:
        title = heading.group(1).strip()
        for prefix in ("Research Report:", "Research Paper:"):
            if title.lower().startswith(prefix.lower()):
                title = title[len(prefix):].strip()
                break
        entry["target"] = entry["target"] or title
    risk = _RISK_MD_RE.search(text)
    if risk:
        entry["risk"] = int(risk.group(1))
        entry["risk_label"] = risk.group(2)
    findings = _FINDINGS_MD_RE.search(text)
    if findings:
        entry["findings"] = int(findings.group(1))
    date = _DATE_MD_RE.search(text)
    if date:
        entry["date"] = date.group(1)


def _enrich_from_paper_meta(entry: dict[str, Any], meta_path: Path) -> None:
    """Fill *entry* from a paper's ``.meta.json`` catalogue record."""
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(meta, dict):
        return
    entry["target"] = meta.get("target") or entry["target"]
    entry["date"] = str(meta.get("created_at") or "")[:10] or entry["date"]
    if meta.get("risk_score") is not None:
        entry["risk"] = meta["risk_score"]
        entry["risk_label"] = meta.get("risk_label")
    if meta.get("findings") is not None:
        entry["findings"] = meta["findings"]


@dataclass
class SiteBuild:
    """Result of rendering the reports/papers into a static site."""

    site_dir: Path
    entries: list[dict[str, Any]]
    files: list[Path]


class ReportHost:
    """Select reports/papers, render them into a site and publish to GitHub."""

    def __init__(self, settings: Settings, client: GitHubClient | None = None):
        self.settings = settings
        self._client = client

    @property
    def site_dir(self) -> Path:
        return self.settings.resolve(self.settings.github.site_dir)

    def client(self) -> GitHubClient:
        """Return (lazily building) the GitHub client for the configured repo."""
        if self._client is None:
            gh = self.settings.github
            token = resolve_token(gh.token)
            if not token:
                raise GitHubError(
                    "No GitHub token found. Export RESEARCH_GITHUB_TOKEN (or "
                    "GITHUB_TOKEN), or run 'gh auth login' so that 'gh auth "
                    "token' returns one, then retry.")
            owner = gh.owner or GitHubClient(token).whoami()
            self._client = GitHubClient(token, owner=owner, repo=gh.repo,
                                        branch=gh.branch)
        return self._client

    # ---- gathering ----------------------------------------------------
    @staticmethod
    def _newest_first(paths: list[Path]) -> list[Path]:
        return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)

    def _collect_reports(self, limit: int | None) -> list[HostedFile]:
        root = self.settings.reports_path
        paths = [p for p in root.iterdir()
                 if p.is_file() and p.suffix.lower() in REPORT_EXTS]
        paths = self._newest_first(paths)
        if limit:
            paths = paths[:limit]
        hosted: list[HostedFile] = []
        for path in paths:
            suffix = path.suffix.lower()
            rel = f"reports/{path.name}"
            page = (f"reports/{path.stem}.html"
                    if suffix in (".md", ".markdown", ".json") else None)
            entry = _base_entry(path, "report", page, rel)
            if suffix == ".json":
                _enrich_from_json(entry, path)
            elif suffix in (".md", ".markdown"):
                try:
                    _enrich_from_markdown(
                        entry, path.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    pass
            if not entry["date"]:
                entry["date"] = datetime.fromtimestamp(
                    path.stat().st_mtime).strftime("%Y-%m-%d")
            hosted.append(HostedFile(path, "report", rel, page, entry))
        return hosted

    def _collect_papers(self, limit: int | None) -> list[HostedFile]:
        root = self.settings.papers_path
        if not root.exists():
            return []
        paths: list[Path] = []
        for shelf in sorted(root.iterdir()):
            if not shelf.is_dir() or shelf.name.startswith("_"):
                continue
            for path in shelf.iterdir():
                if not path.is_file() or path.name.endswith(".meta.json"):
                    continue
                if path.suffix.lower() in PAPER_EXTS:
                    paths.append(path)
        paths = self._newest_first(paths)
        if limit:
            paths = paths[:limit]
        hosted: list[HostedFile] = []
        for path in paths:
            suffix = path.suffix.lower()
            shelf = path.parent.name
            rel = f"papers/{shelf}/{path.name}"
            page = (f"papers/{shelf}/{path.stem}.html"
                    if suffix in (".md", ".markdown", ".json") else None)
            entry = _base_entry(path, "paper", page, rel)
            meta_path = path.with_name(path.stem + ".meta.json")
            if meta_path.exists():
                _enrich_from_paper_meta(entry, meta_path)
            if suffix == ".json":
                _enrich_from_json(entry, path)
            elif suffix in (".md", ".markdown"):
                try:
                    _enrich_from_markdown(
                        entry, path.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    pass
            if not entry["date"]:
                entry["date"] = datetime.fromtimestamp(
                    path.stat().st_mtime).strftime("%Y-%m-%d")
            hosted.append(HostedFile(path, "paper", rel, page, entry))
        return hosted

    def collect(self, *, reports: bool = True, papers: bool = True,
                limit: int | None = None) -> list[HostedFile]:
        """Return the report/paper files selected for hosting."""
        hosted: list[HostedFile] = []
        if reports:
            hosted += self._collect_reports(limit)
        if papers:
            hosted += self._collect_papers(limit)
        return hosted

    # ---- rendering ----------------------------------------------------
    def _subtitle(self) -> str:
        gh = self.settings.github
        label = repo_slug(gh.owner, gh.repo) if gh.owner else gh.repo
        return f"{label} · GitHub Pages"

    def _root_prefix(self, rel: str) -> str:
        depth = len(Path(rel).parts) - 1
        return "../" * depth if depth else "./"

    def _render_json_report(self, text: str) -> str:
        try:
            data = json.loads(text)
        except ValueError:
            return f"<pre>{_esc(text)}</pre>"
        if isinstance(data, dict) and isinstance(data.get("report"), dict):
            data = data["report"]
        if not isinstance(data, dict):
            return f"<pre>{_esc(text)}</pre>"
        parts: list[str] = []
        if data.get("summary"):
            parts.append(f"<h2>Summary</h2><p>{_inline(str(data['summary']))}</p>")
        findings = data.get("findings")
        if isinstance(findings, list) and findings:
            parts.append(
                "<h2>Findings</h2><table><thead><tr><th>#</th><th>Engine</th>"
                "<th>Category</th><th>Title</th><th>Conf</th><th>Source</th>"
                "</tr></thead><tbody>")
            for number, finding in enumerate(findings, 1):
                if not isinstance(finding, dict):
                    continue
                url = finding.get("url")
                src = (f'<a href="{_esc_attr(url)}">link</a>' if url else "—")
                parts.append(
                    f"<tr><td>{number}</td>"
                    f"<td>{_esc(finding.get('engine', ''))}</td>"
                    f"<td>{_esc(finding.get('category', ''))}</td>"
                    f"<td>{_inline(str(finding.get('title', '')))}</td>"
                    f"<td>{_esc(finding.get('confidence', ''))}</td>"
                    f"<td>{src}</td></tr>")
            parts.append("</tbody></table>")
        parts.append(f"<h2>Raw JSON</h2><pre>{_esc(text)}</pre>")
        return "\n".join(parts)

    def _render_page(self, item: HostedFile) -> str:
        text = item.source.read_text(encoding="utf-8", errors="replace")
        if item.source.suffix.lower() == ".json":
            body = self._render_json_report(text)
        else:
            body = markdown_to_html(text)
        up = self._root_prefix(item.rel)
        nav = (f'<a href="{up}index.html">All items</a> '
               f'<a href="{_esc_attr(Path(item.rel).name)}">Raw file</a>')
        return html_document(item.entry.get("target") or item.source.name, body,
                             subtitle=f"{item.kind} · {item.source.name}", nav=nav)

    def build_site(self, *, reports: bool = True, papers: bool = True,
                   limit: int | None = None,
                   site_dir: Path | str | None = None) -> SiteBuild:
        """Render the selected reports/papers into a static site on disk."""
        site = Path(site_dir) if site_dir else self.site_dir
        site.mkdir(parents=True, exist_ok=True)
        items = self.collect(reports=reports, papers=papers, limit=limit)
        written: list[Path] = []
        entries: list[dict[str, Any]] = []
        for item in items:
            dest = site / Path(item.rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(item.source.read_bytes())
            written.append(dest)
            if item.page:
                page_path = site / Path(item.page)
                page_path.parent.mkdir(parents=True, exist_ok=True)
                page_path.write_text(self._render_page(item), encoding="utf-8")
                written.append(page_path)
            entries.append(item.entry)
        title = "Research Reports & Papers"
        (site / "index.html").write_text(
            build_index_html(entries, title=title, subtitle=self._subtitle()),
            encoding="utf-8")
        written.append(site / "index.html")
        (site / "README.md").write_text(
            build_index_markdown(entries, title=title), encoding="utf-8")
        written.append(site / "README.md")
        logger.info("[github] built site with {} item(s) in {}",
                    len(entries), site)
        return SiteBuild(site, entries, written)

    # ---- publishing ---------------------------------------------------
    def _commit_via_git(self, rel_files: dict[str, bytes], message: str,
                        branch: str, remote: str) -> None:
        root = self.settings.root
        _git(["add", "--", *sorted(rel_files)], root)
        _git(["commit", "-m", message], root)
        push = _git(["push", remote, f"HEAD:{branch}"], root)
        if push.returncode != 0:
            raise GitHubError(
                f"'git push {remote}' failed: "
                f"{(push.stderr or push.stdout).strip()[:300]}")

    def host(self, *, reports: bool = True, papers: bool = True,
             limit: int | None = None, message: str | None = None,
             enable_pages: bool = True, dry_run: bool = False,
             branch: str | None = None,
             use_git: bool | None = None) -> dict[str, Any]:
        """Build the site and publish it to GitHub (commit + Pages)."""
        gh = self.settings.github
        if self.settings.privacy.ephemeral:
            raise GitHubError(
                "Cannot host in ephemeral mode: hosting writes files and "
                "uploads them. Drop --ephemeral.")
        build = self.build_site(reports=reports, papers=papers, limit=limit)
        branch = branch or gh.branch
        result: dict[str, Any] = {
            "hosted": len(build.entries), "site_dir": str(build.site_dir),
            "files": [_rel(self.settings.root, p) for p in build.files],
            "branch": branch, "commit": None, "method": None, "url": None,
            "pages": None, "dry_run": bool(dry_run),
        }
        if not build.entries:
            result["skipped"] = "no reports or papers to host"
            return result
        if dry_run:
            result["method"] = "dry-run"
            return result

        rel_files = {_rel(self.settings.root, p): p.read_bytes()
                     for p in build.files}
        remote = git_remote_url(self.settings.root, gh.remote)
        if use_git is None:
            use_git = (bool(remote) and git_available()
                       and (self.settings.root / ".git").exists())
        if use_git:
            self._commit_via_git(rel_files, message or gh.commit_message,
                                 branch, gh.remote)
            result["method"] = "git"
        else:
            client = self.client()
            result["commit"] = client.commit_files(
                rel_files, message or gh.commit_message, branch=branch)
            result["method"] = "api"

        if enable_pages:
            client = self.client()
            try:
                client.enable_pages(branch=branch,
                                    path=f"/{gh.site_dir.strip('/')}")
                result["pages"] = pages_url(client.owner, client.repo)
            except GitHubError as exc:
                result["pages_error"] = str(exc)
        owner = (self._client.owner if self._client else None) or gh.owner
        if owner:
            result["url"] = pages_url(owner, gh.repo)
        return result

    def connect(self, *, owner: str | None = None, repo: str | None = None,
                visibility: str | None = None, remote: str | None = None,
                branch: str | None = None, push: bool = False,
                description: str | None = None) -> dict[str, Any]:
        """Link this checkout to GitHub: git init, repo, remote, optional push."""
        gh = self.settings.github
        owner = owner or gh.owner
        repo = repo or gh.repo
        remote = remote or gh.remote
        branch = branch or gh.branch
        root = self.settings.root
        steps: list[dict[str, Any]] = []

        def record(name: str, ok: bool, detail: str = "") -> None:
            steps.append({"step": name, "ok": bool(ok), "detail": detail})

        if (root / ".git").exists():
            record("git repository", True, "already initialised")
        else:
            proc = _git(["init", "-b", branch], root)
            if proc.returncode != 0:            # older git without -b
                _git(["init"], root)
                _git(["checkout", "-b", branch], root)
            record("git init", (root / ".git").exists(), f"branch {branch}")

        client = self.client()
        if owner:
            client.owner = owner
        if repo:
            client.repo = repo
        client.branch = branch
        created = bool(client.create_repo(
            private=((visibility or gh.visibility) != "public"),
            description=description or gh.description,
            homepage=pages_url(client.owner, client.repo)))
        record("GitHub repo", True,
               f"{repo_slug(client.owner, client.repo)} "
               f"({'created' if created else 'already exists'})")

        url = client.remote_url()
        if git_remote_url(root, remote):
            _git(["remote", "set-url", remote, url], root)
            record(f"remote '{remote}'", True, f"-> {url}")
        else:
            add = _git(["remote", "add", remote, url], root)
            record(f"remote '{remote}'", add.returncode == 0, url)

        try:
            helper = subprocess.run(["gh", "auth", "setup-git"],
                                    capture_output=True, text=True,
                                    timeout=60, check=False)
            record("git credentials", helper.returncode == 0, "gh auth setup-git")
        except (OSError, subprocess.SubprocessError):
            record("git credentials", False, "gh CLI not found")

        pushed = False
        if push:
            proc = _git(["push", "-u", remote, branch], root)
            pushed = proc.returncode == 0
            record("git push", pushed,
                   f"{remote} {branch}" if pushed
                   else (proc.stderr or proc.stdout).strip()[:200])
        return {"repo": repo_slug(client.owner, client.repo), "remote": url,
                "branch": branch, "created": created, "pushed": pushed,
                "url": pages_url(client.owner, client.repo), "steps": steps}


def _rel(root: Path, path: Path) -> str:
    """Return *path* relative to *root* (POSIX), or its absolute form."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


__all__ = [
    "GitHubClient", "GitHubError", "HostedFile", "ReportHost", "SiteBuild",
    "markdown_to_html", "html_document", "build_index_html",
    "build_index_markdown", "resolve_token", "pages_url", "repo_slug",
    "git_available", "git_remote_url", "GITHUB_API", "DEFAULT_SITE_DIR",
    "TOKEN_ENV_VARS", "REPORT_EXTS", "PAPER_EXTS",
]
