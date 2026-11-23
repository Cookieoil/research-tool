"""Offline tests for the GitHub hosting integration.

Run with pytest (``python -m pytest tests``) or directly
(``python tests/test_github.py``). No network access is required - the GitHub
REST client is exercised through an injectable fake session.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research_tool.config import Settings
from research_tool.utils.github import (GitHubClient, GitHubError, ReportHost,
                                        build_index_html, build_index_markdown,
                                        markdown_to_html, pages_url, repo_slug,
                                        resolve_token)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, status_code: int = 200, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = (json.dumps(payload) if text is None and payload is not None
                     else (text or ""))

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON body")
        return self._payload


class FakeSession:
    """Minimal stand-in for ``requests.Session`` that records calls."""

    def __init__(self):
        self.calls: list[dict] = []
        self._routes: list[tuple[str, str, FakeResponse]] = []

    def route(self, method: str, contains: str,
              response: FakeResponse) -> "FakeSession":
        self._routes.append((method.upper(), contains, response))
        return self

    def request(self, method: str, url: str, headers=None, timeout=None,
                **kwargs):
        self.calls.append({"method": method.upper(), "url": url,
                           "json": kwargs.get("json")})
        best = None
        for m, contains, response in self._routes:
            if m == method.upper() and contains in url:
                if best is None or len(contains) > len(best[1]):
                    best = (m, contains, response)
        if best is None:
            raise AssertionError(f"no route for {method} {url}")
        return best[2]

    def paths(self, method: str) -> list[str]:
        return [c["url"].split("api.github.com", 1)[-1] for c in self.calls
                if c["method"] == method.upper()]


def _settings(root: Path) -> Settings:
    return Settings(**{
        "app": {
            "reports_dir": str(root / "data" / "reports"),
            "papers_dir": str(root / "data" / "papers"),
            "cache_dir": str(root / "data" / "cache"),
        },
        "github": {
            "enabled": True, "owner": "octo", "repo": "research-tool",
            "branch": "main", "site_dir": str(root / "docs"),
        },
        "privacy": {"ephemeral": False},
    })


def _report_dict(target: str = "Jane Doe") -> dict:
    return {
        "target": target, "target_kind": "name",
        "generated_at": "2026-11-21T09:00:00",
        "summary": f"{target} appears in public sources.",
        "risk_score": 20, "engines_run": ["search", "academic"],
        "errors": [],
        "findings": [
            {"engine": "academic", "category": "credential",
             "title": "Degree corroborated: MIT", "url": "https://e.edu/j",
             "confidence": 0.9, "data": {"status": "matched"}},
        ],
    }


def _seed_output(root: Path) -> None:
    reports = root / "data" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "report_jane_doe.json").write_text(
        json.dumps(_report_dict()), encoding="utf-8")
    (reports / "report_example.com.md").write_text(
        "# Research Report: example.com\n\n"
        "- **Generated:** 2026-11-20T10:00:00Z\n"
        "- **Findings:** 3\n- **Risk score:** 45/100 (MEDIUM)\n\n"
        "## Findings\n\n### 1. WHOIS record\n\ntext\n",
        encoding="utf-8")
    shelf = root / "data" / "papers" / "people"
    shelf.mkdir(parents=True, exist_ok=True)
    (shelf / "jane-doe_2026-11-21.md").write_text(
        "# Research Paper: Jane Doe\n\n## Abstract\n\nReviewed.\n",
        encoding="utf-8")
    (shelf / "jane-doe_2026-11-21.meta.json").write_text(json.dumps({
        "paper_id": "jane-doe_2026-11-21", "title": "Research Paper: Jane Doe",
        "target": "Jane Doe", "target_kind": "name", "topic": "people",
        "status": "final", "created_at": "2026-11-21T09:00:00",
        "risk_score": 20, "risk_label": "LOW", "findings": 4,
        "files": ["people/jane-doe_2026-11-21.md"],
    }), encoding="utf-8")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def test_resolve_token_precedence() -> None:
    assert resolve_token("  abc  ") == "abc"
    old = os.environ.pop("RESEARCH_GITHUB_TOKEN", None)
    try:
        os.environ["RESEARCH_GITHUB_TOKEN"] = "envtok"
        assert resolve_token() == "envtok"
        assert resolve_token("explicit") == "explicit"
    finally:
        os.environ.pop("RESEARCH_GITHUB_TOKEN", None)
        if old is not None:
            os.environ["RESEARCH_GITHUB_TOKEN"] = old


def test_pages_url_and_slug() -> None:
    assert pages_url("CookieOil", "research-tool") == \
        "https://cookieoil.github.io/research-tool/"
    assert repo_slug("octo", "repo") == "octo/repo"


def test_client_requires_token() -> None:
    client = GitHubClient("", owner="octo", repo="r", session=FakeSession())
    try:
        client.repo_exists()
        raised = False
    except GitHubError:
        raised = True
    assert raised


def test_config_github_defaults_and_env() -> None:
    settings = Settings()
    assert settings.github.repo == "research-tool"
    assert settings.github.branch == "main"
    assert settings.github.site_dir == "docs"
    # env override is layered on by load_settings' helper
    from research_tool.config import _apply_env_overrides
    old = os.environ.get("RESEARCH_GITHUB_REPO")
    try:
        os.environ["RESEARCH_GITHUB_REPO"] = "hosted-reports"
        data = _apply_env_overrides({})
        assert data["github"]["repo"] == "hosted-reports"
    finally:
        if old is None:
            os.environ.pop("RESEARCH_GITHUB_REPO", None)
        else:
            os.environ["RESEARCH_GITHUB_REPO"] = old


# ---------------------------------------------------------------------------
# Markdown -> HTML
# ---------------------------------------------------------------------------
def test_markdown_to_html_subset() -> None:
    md = ("# Title\n\n> **NOTE** · `x`\n\n"
          "| A | B |\n|---|---|\n| 1 | 2 |\n\n"
          "- **bold** with [link](https://e.com) and <https://a.com>\n\n"
          "```json\n{\"k\": 1}\n```\n")
    html = markdown_to_html(md)
    assert "<h1>Title</h1>" in html
    assert "<blockquote>" in html and "<strong>NOTE</strong>" in html
    assert "<table>" in html and "<th>A</th>" in html and "<td>2</td>" in html
    assert '<a href="https://e.com">link</a>' in html
    assert '<a href="https://a.com">https://a.com</a>' in html
    assert '<pre><code class="language-json">' in html
    assert "<ul>" in html and "<li>" in html


def test_markdown_to_html_escapes_html() -> None:
    html = markdown_to_html("hello <script>alert(1)</script> & bye")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&amp;" in html


def test_index_builders() -> None:
    entries = [
        {"kind": "report", "name": "report_jane.json", "target": "Jane Doe",
         "date": "2026-11-21", "risk": 20, "risk_label": "LOW",
         "findings": 4, "page": "reports/report_jane.html",
         "raw": "reports/report_jane.json"},
        {"kind": "paper", "name": "jane.md", "target": "Jane Doe",
         "date": "2026-11-21", "risk": 20, "risk_label": "LOW",
         "findings": 4, "page": "papers/people/jane.html",
         "raw": "papers/people/jane.md"},
    ]
    html = build_index_html(entries, title="Hosted reports",
                            generated_at=datetime(2026, 11, 21, 9, 0))
    assert "Hosted reports" in html and "report_jane.html" in html
    assert "risk-LOW" in html

    md = build_index_markdown(entries, title="Hosted reports")
    assert "| report |" in md and "papers/people/jane.md" in md


def test_index_groups_into_sections_and_merges_formats() -> None:
    entries = [
        {"kind": "report", "name": "report_x.json", "target": "X",
         "date": "2026-11-21", "risk": 0, "risk_label": "NONE",
         "findings": 3, "page": "reports/report_x.html",
         "raw": "reports/report_x.json"},
        {"kind": "paper", "name": "paper_a.md", "target": "Gacha",
         "date": "2026-11-21", "risk": 0, "risk_label": "NONE",
         "findings": 46, "topic": "gacha", "page": "papers/gacha/paper_a.html",
         "raw": "papers/gacha/paper_a.md"},
        {"kind": "paper", "name": "paper_a.pdf", "target": "Gacha",
         "date": "2026-11-21", "risk": 0, "risk_label": "NONE",
         "findings": 46, "topic": "gacha", "page": None,
         "raw": "papers/gacha/paper_a.pdf"},
    ]
    html = build_index_html(entries, title="Hosted")
    # One section per topic plus one for reports.
    assert html.count("<section") == 2
    assert 'class="tabs"' in html
    assert "Papers · gacha" in html and "Reports" in html
    # The three formats of one paper collapse into a single row.
    assert html.count("<tr>") - 2 == 2
    assert "papers/gacha/paper_a.pdf" in html

    md = build_index_markdown(entries, title="Hosted")
    assert "## Papers · gacha (1)" in md
    assert "## Reports (1)" in md
    assert "[pdf](papers/gacha/paper_a.pdf)" in md


def test_index_dedupes_links_and_renders_missing_values() -> None:
    # The .md and .json of one paper both render to the same .html page, so the
    # merged row must not repeat the "read" link. A standalone PDF has no
    # findings count and must show an em dash instead of "None".
    entries = [
        {"kind": "paper", "name": "paper_a.md", "target": "Gacha",
         "date": "2026-11-21", "risk": 0, "risk_label": "NONE",
         "findings": 46, "topic": "gacha",
         "page": "papers/gacha/paper_a.html", "raw": "papers/gacha/paper_a.md"},
        {"kind": "paper", "name": "paper_a.json", "target": "Gacha",
         "date": "2026-11-21", "risk": 0, "risk_label": "NONE",
         "findings": 46, "topic": "gacha",
         "page": "papers/gacha/paper_a.html", "raw": "papers/gacha/paper_a.json"},
        {"kind": "report", "name": "standalone.pdf", "target": "",
         "date": "2026-11-21", "risk": None, "risk_label": None,
         "findings": None, "topic": "gacha", "page": None,
         "raw": "reports/standalone.pdf"},
    ]
    html = build_index_html(entries, title="Hosted")
    assert html.count('href="papers/gacha/paper_a.html"') == 1
    assert "None" not in html
    # Reports carrying a topic get their own section.
    assert "Reports · gacha" in html

    md = build_index_markdown(entries, title="Hosted")
    assert md.count("(papers/gacha/paper_a.html)") == 1
    assert "None" not in md
    assert "## Reports · gacha (1)" in md


def test_index_puts_source_documents_in_their_own_section() -> None:
    entries = [
        {"kind": "paper", "name": "paper_a.md", "target": "Gacha",
         "date": "2026-11-21", "risk": 0, "risk_label": "NONE",
         "findings": 46, "topic": "gacha",
         "page": "papers/gacha/paper_a.html", "raw": "papers/gacha/paper_a.md"},
        {"kind": "report", "name": "report_gacha.json", "target": "Gacha",
         "date": "2026-11-21", "risk": 0, "risk_label": "NONE",
         "findings": 46, "topic": "", "page": "reports/report_gacha.html",
         "raw": "reports/report_gacha.json"},
        {"kind": "source", "name": "Vendor_Deck.pdf", "target": "",
         "date": "2026-11-21", "risk": None, "risk_label": None,
         "findings": None, "topic": "", "page": None,
         "raw": "reports/Vendor_Deck.pdf"},
    ]
    html = build_index_html(entries, title="Hosted")
    assert html.count("<section") == 3
    # Section order: papers, then reports, then sources last.
    order = [label for label in ("Papers · gacha", "Reports",
                                 "Source documents")
             if label in html]
    assert order == ["Papers · gacha", "Reports", "Source documents"]
    assert html.index("Papers · gacha") < html.index("Source documents")
    assert 'class="legend"' in html

    md = build_index_markdown(entries, title="Hosted")
    assert "## Source documents (1)" in md
    assert md.index("## Papers") < md.index("## Source documents")


# ---------------------------------------------------------------------------
# Collecting and building the site
# ---------------------------------------------------------------------------
def test_collect_reports_and_papers() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_output(root)
        host = ReportHost(_settings(root))

        reports = host.collect(reports=True, papers=False)
        assert {r.rel for r in reports} == {
            "reports/report_jane_doe.json", "reports/report_example.com.md"}
        jane = next(r for r in reports if r.rel.endswith(".json"))
        assert jane.entry["target"] == "Jane Doe"
        assert jane.entry["risk"] == 20
        assert jane.entry["findings"] == 1
        assert jane.page == "reports/report_jane_doe.html"

        papers = host.collect(reports=False, papers=True)
        assert [p.rel for p in papers] == ["papers/people/jane-doe_2026-11-21.md"]
        assert papers[0].entry["findings"] == 4
        assert papers[0].entry["date"] == "2026-11-21"
        assert papers[0].entry["risk_label"] == "LOW"


def test_collect_limit_and_empty() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        host = ReportHost(_settings(root))       # nothing written yet
        assert host.collect() == []
        _seed_output(root)
        # limit is applied per kind (reports and papers independently)
        assert len(host.collect(reports=True, papers=False, limit=1)) == 1
        assert len(host.collect(reports=False, papers=True, limit=1)) == 1
        assert len(host.collect()) == 3


def test_build_site_writes_pages_and_index() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_output(root)
        settings = _settings(root)
        build = ReportHost(settings).build_site()
        site = settings.site_path
        assert (site / "index.html").exists()
        assert (site / "README.md").exists()
        assert (site / "reports" / "report_jane_doe.json").exists()
        page = (site / "reports" / "report_jane_doe.html").read_text("utf-8")
        assert "Jane Doe" in page and "Degree corroborated" in page
        md_page = (site / "reports" / "report_example.com.html").read_text("utf-8")
        assert "<h1>" in md_page
        index = (site / "index.html").read_text("utf-8")
        assert "example.com" in index
        assert len(build.entries) == 3


# ---------------------------------------------------------------------------
# GitHub REST client (fake transport)
# ---------------------------------------------------------------------------
def _client(session: FakeSession) -> GitHubClient:
    return GitHubClient("tok", owner="octo", repo="research-tool",
                        branch="main", session=session)


def test_commit_files_empty_repo_creates_ref() -> None:
    session = (FakeSession()
               .route("GET", "git/ref/heads/main", FakeResponse(404, None))
               .route("POST", "git/blobs", FakeResponse(201, {"sha": "b1"}))
               .route("POST", "git/trees", FakeResponse(201, {"sha": "t1"}))
               .route("POST", "git/commits", FakeResponse(201, {"sha": "c1"}))
               .route("POST", "git/refs", FakeResponse(201, {"ref": "x"})))
    sha = _client(session).commit_files({"docs/index.html": "<h1>hi</h1>"}, "msg")
    assert sha == "c1"
    blob = next(c for c in session.calls if "git/blobs" in c["url"])
    assert base64.b64decode(blob["json"]["content"]) == b"<h1>hi</h1>"
    assert any("git/refs" in path for path in session.paths("POST"))


def test_commit_files_existing_branch_updates_ref() -> None:
    session = (FakeSession()
               .route("GET", "git/ref/heads/main",
                      FakeResponse(200, {"object": {"sha": "parent"}}))
               .route("GET", "git/commits/parent",
                      FakeResponse(200, {"tree": {"sha": "base"}}))
               .route("POST", "git/blobs", FakeResponse(201, {"sha": "b1"}))
               .route("POST", "git/trees", FakeResponse(201, {"sha": "t2"}))
               .route("POST", "git/commits", FakeResponse(201, {"sha": "c2"}))
               .route("PATCH", "git/refs/heads/main", FakeResponse(200, {})))
    sha = _client(session).commit_files({"a.md": "x"}, "msg")
    assert sha == "c2"
    tree = next(c for c in session.calls if "git/trees" in c["url"])
    assert tree["json"]["base_tree"] == "base"
    commit = next(c for c in session.calls
                  if c["method"] == "POST" and "git/commits" in c["url"])
    assert commit["json"]["parents"] == ["parent"]


def test_commit_files_rejects_api_error() -> None:
    session = (FakeSession()
               .route("GET", "git/ref/heads/main", FakeResponse(404, None))
               .route("POST", "git/blobs", FakeResponse(
                   403, {"message": "Resource not accessible by token"})))
    try:
        _client(session).commit_files({"a": "b"}, "m")
        raised = False
    except GitHubError as exc:
        raised = "403" in str(exc)
    assert raised


def test_enable_pages_creates_and_updates() -> None:
    create = (FakeSession()
              .route("GET", "repos/octo/research-tool/pages",
                     FakeResponse(404, None))
              .route("POST", "repos/octo/research-tool/pages",
                     FakeResponse(201, {"html_url": "https://x/pages/"})))
    result = _client(create).enable_pages(path="/docs")
    assert result and result["html_url"] == "https://x/pages/"
    post = next(c for c in create.calls if c["method"] == "POST")
    assert post["json"]["source"] == {"branch": "main", "path": "/docs"}

    update = (FakeSession()
              .route("GET", "repos/octo/research-tool/pages",
                     FakeResponse(200, {"html_url": "https://x/"}))
              .route("PUT", "repos/octo/research-tool/pages",
                     FakeResponse(204, None)))
    assert _client(update).enable_pages() is not None
    assert any(c["method"] == "PUT" for c in update.calls)


# ---------------------------------------------------------------------------
# End-to-end host flow (fake transport)
# ---------------------------------------------------------------------------
def _host_routes(session: FakeSession) -> FakeSession:
    return (session
            .route("GET", "git/ref/heads/main", FakeResponse(404, None))
            .route("POST", "git/blobs", FakeResponse(201, {"sha": "b"}))
            .route("POST", "git/trees", FakeResponse(201, {"sha": "t"}))
            .route("POST", "git/commits", FakeResponse(201, {"sha": "c9"}))
            .route("POST", "git/refs", FakeResponse(201, {"ref": "x"}))
            .route("GET", "repos/octo/research-tool/pages", FakeResponse(404, None))
            .route("POST", "repos/octo/research-tool/pages", FakeResponse(
                201, {"html_url": "https://octo.github.io/research-tool/"})))


def test_host_dry_run_makes_no_calls() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_output(root)
        session = FakeSession()
        result = ReportHost(_settings(root), client=_client(session)).host(
            dry_run=True, use_git=False)
        assert result["method"] == "dry-run"
        assert result["hosted"] == 3
        assert session.calls == []
        assert (root / "docs" / "index.html").exists()


def test_host_via_api_commits_and_enables_pages() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_output(root)
        session = _host_routes(FakeSession())
        result = ReportHost(_settings(root), client=_client(session)).host(
            use_git=False)
        assert result["method"] == "api"
        assert result["commit"] == "c9"
        assert result["pages"] == "https://octo.github.io/research-tool/"
        assert result["url"] == "https://octo.github.io/research-tool/"
        blobs = [c for c in session.calls if "git/blobs" in c["url"]]
        assert len(blobs) == len(result["files"]) >= 4


def test_host_ephemeral_refused() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_output(root)
        settings = _settings(root)
        settings.privacy.ephemeral = True
        try:
            ReportHost(settings, client=_client(FakeSession())).host(use_git=False)
            raised = False
        except GitHubError:
            raised = True
        assert raised


def test_host_skips_when_nothing_to_publish() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        session = FakeSession()
        result = ReportHost(_settings(root), client=_client(session)).host(
            use_git=False)
        assert result["hosted"] == 0
        assert result.get("skipped")
        assert session.calls == []


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------
def test_markdown_to_html_renders_chart_fences() -> None:
    """Chart fences become tables (shaded for heatmaps), never raw syntax."""
    md = ("```chart-heatmap\n"
          "title: Motive intensity\n"
          "caption: Figure 1. Who wants what [1].\n"
          "| Actor | Security |\n| Party | 3 |\n| Industry | 0 |\n```\n\n"
          "```chart-stats\n| $817M | Market |\n| 58.5M | Players |\n```\n")
    html = markdown_to_html(md)
    assert html.count("<table>") == 2
    assert "background:#" in html                  # heat shading applied
    assert 'class="legend"' in html                # caption styled
    assert "$817M" in html                         # KPI row kept as data
    assert "chart-heatmap" not in html and "chart-stats" not in html
    assert "| Party |" not in html


def test_collect_papers_reads_meta_shelf_and_skips_machine_folders() -> None:
    """Catalogue records live in _meta/<shelf>/, and pdfs/ is not a shelf."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_output(root)
        library = root / "data" / "papers"
        shelf = library / "people"
        record = shelf / "jane-doe_2026-11-21.meta.json"
        meta_dir = library / "_meta" / "people"
        meta_dir.mkdir(parents=True, exist_ok=True)
        record.replace(meta_dir / record.name)      # new layout
        mirror = library / "pdfs"
        mirror.mkdir(parents=True, exist_ok=True)
        (mirror / "Jane_Doe_2026.pdf").write_bytes(b"%PDF-1.4 mirror")

        papers = ReportHost(_settings(root)).collect(reports=False, papers=True)
        assert [p.rel for p in papers] == \
            ["papers/people/jane-doe_2026-11-21.md"]
        assert papers[0].entry["findings"] == 4
        assert papers[0].entry["topic"] == "people"


def test_build_site_prunes_stale_pages() -> None:
    """A site rebuild must remove pages for papers no longer in the library."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_output(root)
        settings = _settings(root)
        host = ReportHost(settings)
        host.build_site()
        site = settings.site_path
        stale = site / "papers" / "people" / "removed-paper_2026-11-20.md"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text("# old paper\n", encoding="utf-8")
        host.build_site()                    # rebuild prunes it
        assert not stale.exists()
        assert (site / "papers" / "people" / "jane-doe_2026-11-21.md").exists()


def test_cli_exposes_github_commands() -> None:
    from typer.testing import CliRunner

    from research_tool import cli as cli_mod

    runner = CliRunner()
    env = {"COLUMNS": "200", "LINES": "60"}   # keep Rich from truncating help
    result = runner.invoke(cli_mod.app, ["github", "--help"], env=env)
    assert result.exit_code == 0, result.output
    for command in ("status", "connect", "host"):
        assert command in result.output
    helped = runner.invoke(cli_mod.app, ["github", "host", "--help"], env=env)
    assert helped.exit_code == 0
    assert "dry-run" in helped.output


def test_cli_config_masks_github_token() -> None:
    import os as _os
    from typer.testing import CliRunner

    from research_tool import cli as cli_mod

    old = _os.environ.get("RESEARCH_GITHUB_TOKEN")
    fresh = cli_mod.get_settings.cache_clear
    try:
        _os.environ["RESEARCH_GITHUB_TOKEN"] = "super-secret-token"
        fresh()                        # drop the cached settings
        result = CliRunner().invoke(cli_mod.app, ["config"])
        assert result.exit_code == 0, result.output
        assert "***set***" in result.output
        assert "super-secret-token" not in result.output
    finally:
        if old is None:
            _os.environ.pop("RESEARCH_GITHUB_TOKEN", None)
        else:
            _os.environ["RESEARCH_GITHUB_TOKEN"] = old
        fresh()


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


