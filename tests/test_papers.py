"""Offline tests for the finalized-paper library.

Run either with pytest (``python -m pytest tests``) or directly
(``python tests/test_papers.py``). No network access is required.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research_tool.config import Settings
from research_tool.models.paper import PaperMeta
from research_tool.models.report import Finding, ResearchReport
from research_tool.reporters.paper_report import PaperReporter, source_urls
from research_tool.utils.library import (ARCHIVE_DIR, INDEX_FILE, INDEX_JSON,
                                         META_DIR, PDF_MIRROR_DIR,
                                         TOPIC_BY_KIND, PaperLibrary,
                                         load_report_file, normalise_formats,
                                         slugify)


def _report(target: str = "Jane Doe") -> ResearchReport:
    report = ResearchReport(target=target, target_kind="name",
                            engines_run=["search", "academic"])
    report.findings = [
        Finding(engine="academic", category="credential",
                title="Degree corroborated: MIT",
                detail="MIT registry lists Jane Doe.",
                url="https://registry.example.edu/jane", confidence=0.9),
        Finding(engine="search", category="identity",
                title="Public profile | Example",
                url="https://example.com/jane", confidence=0.6),
        Finding(engine="search", category="identity",
                title="Duplicate source for the same URL",
                url="https://example.com/jane", confidence=0.5),
        Finding(engine="academic", category="credential",
                title="No registry match for certification",
                confidence=0.3, data={"status": "not_found"}),
    ]
    report.summary = "Jane Doe appears in public academic and web sources."
    report.risk_score = 20
    report.errors = ["search: rate limited once"]
    return report


def _meta(report: ResearchReport) -> PaperMeta:
    return PaperMeta(
        paper_id="jane-doe_2026-11-21",
        title="Research Paper: Jane Doe",
        target=report.target,
        target_kind=report.target_kind,
        topic="people",
        author="Test Analyst",
        tags=["osint"],
        created_at=datetime(2026, 11, 21, 9, 0),
        risk_score=report.risk_score,
        risk_label="LOW",
        findings=len(report.findings),
        engines=list(report.engines_run),
        sources=len(source_urls(report)),
        files=["people/jane-doe_2026-11-21.md"],
    )


def test_slugify_and_formats() -> None:
    assert slugify("Jane Doe") == "jane-doe"
    assert slugify("  Kim Jong-un! ") == "kim-jong-un"
    assert slugify("Reign of Nightfall: Part II") == "reign-of-nightfall-part-ii"
    assert slugify("김정은").startswith("paper-")
    assert TOPIC_BY_KIND["domain"] == "domains"
    assert normalise_formats(["md", "PDF", "markdown"]) == ["markdown", "pdf"]
    try:
        normalise_formats(["excel"])
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_publish_layout_record_and_index() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lib = PaperLibrary(Path(tmp), author="Test Analyst")
        meta = lib.publish(_report(), formats=["markdown", "json"],
                           tags=["osint"], include_raw=True,
                           title="Jane Doe | OSINT review",
                           published_at=datetime(2026, 11, 21, 9, 0))

        assert meta.paper_id == "jane-doe_2026-11-21"
        assert meta.topic == "people"
        assert meta.status == "final"
        assert meta.abstract == "Jane Doe appears in public academic and web sources."
        assert meta.files == ["people/jane-doe_2026-11-21.md",
                              f"{META_DIR}/people/jane-doe_2026-11-21.json"]

        paper = Path(tmp) / meta.files[0]
        text = paper.read_text(encoding="utf-8")
        assert "Finalized research paper" in text
        assert "## Abstract" in text
        assert "## References" in text
        assert "https://example.com/jane" in text
        assert "## Appendix A" in text        # include_raw appendix

        # Documents stay on the shelf; the record lives in _meta/<topic>/.
        assert not (Path(tmp) / "people" / "jane-doe_2026-11-21.json").exists()
        record = (Path(tmp) / META_DIR / "people" /
                  "jane-doe_2026-11-21.meta.json")
        assert record.exists()
        assert json.loads(record.read_text(encoding="utf-8"))["paper_id"] == \
            meta.paper_id

        index = (Path(tmp) / INDEX_FILE).read_text(encoding="utf-8")
        assert meta.paper_id in index and "Jane Doe" in index
        assert "Jane Doe \\| OSINT review" in index     # pipes escaped
        payload = json.loads((Path(tmp) / INDEX_JSON).read_text(encoding="utf-8"))
        assert payload["active"][0]["paper_id"] == meta.paper_id
        assert lib.root == Path(tmp)


def test_desk_research_metadata_overrides_osint_boilerplate() -> None:
    report = _report()
    report.metadata = {
        "methodology": "Desk research across peer-reviewed and industry sources.",
        "risk_explanation": "Not applicable: no target-identity risk is assessed.",
        "limitations": ["Company-reported demographics are not peer-reviewed."],
    }
    text = PaperReporter().render_markdown(report, _meta(report))
    assert "Desk research across peer-reviewed" in text
    assert "Not applicable: no target-identity risk" in text
    assert "Company-reported demographics are not peer-reviewed." in text
    assert "Name matches (including sanctions screening)" not in text


def test_publish_versions_and_find() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lib = PaperLibrary(Path(tmp))
        first = lib.publish(_report(), tags=["osint", "credential"],
                            published_at=datetime(2026, 11, 21, 9, 0))
        second = lib.publish(_report(), status="draft",
                             tags=["osint", "credential"],
                             published_at=datetime(2026, 11, 21, 9, 0))
        assert second.paper_id == f"{first.paper_id}_v2"
        assert second.status == "draft"

        assert [m.paper_id for m in lib.find(query="osint")] == \
            [second.paper_id, first.paper_id]
        assert [m.paper_id for m in lib.find(topic="people",
                                             status="draft")] == \
            [second.paper_id]
        assert lib.find(query="no-such-target") == []
        # Archived papers stay out of the default listing.
        lib.archive(first.paper_id)
        assert [m.paper_id for m in lib.find()] == [second.paper_id]
        assert [m.paper_id for m in lib.find(include_archived=True)] == \
            [second.paper_id, first.paper_id]
def test_archive_moves_documents_and_record() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        lib = PaperLibrary(base)
        meta = lib.publish(_report(), formats=["markdown"],
                           published_at=datetime(2026, 11, 21))
        archived = lib.archive(meta.paper_id)

        assert archived.status == "archived"
        assert not (base / "people" / f"{meta.paper_id}.md").exists()
        assert (base / ARCHIVE_DIR / "people" / f"{meta.paper_id}.md").exists()
        assert (base / ARCHIVE_DIR / "people" /
                f"{meta.paper_id}.meta.json").exists()
        assert archived.files == \
            [f"{ARCHIVE_DIR}/people/{meta.paper_id}.md"]
        index = (base / INDEX_FILE).read_text(encoding="utf-8")
        assert "## Archived papers" in index
        assert f"`{meta.paper_id}`" in index

        assert lib.archive(meta.paper_id).status == "archived"   # idempotent
        try:
            lib.archive("does-not-exist")
            raised = False
        except FileNotFoundError:
            raised = True
        assert raised


def test_load_report_file_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        report = _report()

        raw = base / "raw.json"
        raw.write_text(json.dumps(report.to_dict(), indent=2),
                       encoding="utf-8")
        loaded, saved = load_report_file(raw)
        assert loaded.target == "Jane Doe"
        assert len(loaded.findings) == len(report.findings)
        assert saved == {}

        lib = PaperLibrary(base / "papers")
        meta = lib.publish(report, formats=["json"],
                           published_at=datetime(2026, 11, 21))
        loaded, saved = load_report_file(base / "papers" / meta.files[0])
        assert loaded.target == "Jane Doe"
        assert saved["paper_id"] == meta.paper_id

        bad = base / "bad.json"
        bad.write_text('{"hello": "world"}', encoding="utf-8")
        try:
            load_report_file(bad)
            raised = False
        except ValueError:
            raised = True
        assert raised


def test_paper_reporter_formats() -> None:
    report = _report()
    meta = _meta(report)
    markdown = PaperReporter().render_markdown(report, meta)
    assert "## Abstract" in markdown
    assert "## References" in markdown
    assert "F1" in markdown and "[1]" in markdown
    assert "No registry match" in markdown
    # the manuscript must not carry CLI scaffolding
    assert "Document control" not in markdown
    assert "Engine:" not in markdown
    assert "Recorded data" not in markdown
    assert source_urls(report) == [
        "https://registry.example.edu/jane", "https://example.com/jane"]

    payload = json.loads(PaperReporter().render_bytes(report, meta, "json"))
    assert payload["meta"]["paper_id"] == meta.paper_id
    assert payload["report"]["target"] == "Jane Doe"
    assert "## Abstract" in payload["paper_markdown"]

    try:
        pdf = PaperReporter().render_bytes(report, meta, "pdf",
                                           include_raw=True)
    except RuntimeError:          # reportlab not installed
        pdf = b""
    if pdf:
        assert pdf.startswith(b"%PDF")
def test_republish_after_archive_gets_new_version() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lib = PaperLibrary(Path(tmp))
        first = lib.publish(_report(), published_at=datetime(2026, 11, 21, 9))
        lib.archive(first.paper_id)

        again = lib.publish(_report(), published_at=datetime(2026, 11, 21, 10))
        assert again.paper_id == f"{first.paper_id}_v2"
        assert [m.paper_id for m in lib.find()] == [again.paper_id]

        lib.archive(again.paper_id)     # must target the active v2, not v1
        archived = {m.paper_id for m in lib.find(include_archived=True,
                                                 status="archived")}
        assert archived == {first.paper_id, again.paper_id}
        assert (Path(tmp) / ARCHIVE_DIR / "people" /
                f"{again.paper_id}.md").exists()


def test_purge_keeps_papers_by_default() -> None:
    import os
    import time

    from research_tool.utils.retention import purge_tool_data

    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings()
        settings.app.papers_dir = str(Path(tmp) / "papers")
        settings.app.reports_dir = str(Path(tmp) / "reports")
        settings.app.cache_dir = str(Path(tmp) / "cache")
        settings.logging.log_file = None

        lib = PaperLibrary(settings.papers_path)
        meta = lib.publish(_report(), published_at=datetime(2026, 11, 21))
        paper = settings.papers_path / meta.files[0]
        old = time.time() - 24 * 3600
        os.utime(paper, (old, old))
        rules = settings.papers_path / "ORGANISATION.md"
        rules.write_text("rules", encoding="utf-8")
        template = settings.papers_path / "_templates" / "TEMPLATE.md"
        template.parent.mkdir(parents=True, exist_ok=True)
        template.write_text("template", encoding="utf-8")

        summary = purge_tool_data(settings, older_than_hours=0)
        assert "papers" not in summary
        assert paper.exists()

        summary = purge_tool_data(settings, older_than_hours=0,
                                  include_papers=True)
        assert "papers" in summary and summary["papers"] >= 1
        assert not paper.exists()
        assert rules.exists() and template.exists()


def test_cli_papers_and_publish_from() -> None:
    import research_tool.cli as cli_mod
    from typer.testing import CliRunner

    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings()
        settings.app.papers_dir = str(Path(tmp) / "papers")
        settings.app.reports_dir = str(Path(tmp) / "reports")
        settings.app.cache_dir = str(Path(tmp) / "cache")
        settings.cache.backend = "memory"
        settings.logging.log_file = None

        original = cli_mod.get_settings
        original_logger = cli_mod.setup_logger
        cli_mod.get_settings = lambda: settings      # type: ignore[assignment]
        cli_mod.setup_logger = lambda **kwargs: None  # type: ignore[assignment]
        try:
            runner = CliRunner()
            env = {"COLUMNS": "200", "LINES": "50"}
            empty = runner.invoke(cli_mod.app, ["papers"], env=env)
            assert empty.exit_code == 0, empty.output
            assert "No papers found" in empty.output

            raw = Path(tmp) / "report.json"
            raw.write_text(json.dumps(_report().to_dict(), indent=2),
                           encoding="utf-8")
            result = runner.invoke(cli_mod.app, [
                "publish", "--from", str(raw), "--format", "markdown",
                "--topic", "people", "--tags", "osint"], env=env)
            assert result.exit_code == 0, result.output
            assert "Finalized paper published" in result.output

            papers_dir = Path(tmp) / "papers"
            assert (papers_dir / INDEX_FILE).exists()
            assert list((papers_dir / "people").glob("*.md"))

            listed = runner.invoke(cli_mod.app, ["papers", "--query", "jane"],
                                   env=env)
            assert listed.exit_code == 0, listed.output
            assert "jane-doe_" in listed.output
            assert "no papers found" not in listed.output.lower()

            record = next((papers_dir / META_DIR / "people").glob("*.meta.json"))
            paper_id = record.name[:-len(".meta.json")]
            archived = runner.invoke(cli_mod.app,
                                     ["archive-paper", paper_id, "-y"], env=env)
            assert archived.exit_code == 0, archived.output
            assert (papers_dir / ARCHIVE_DIR / "people").exists()
        finally:
            cli_mod.get_settings = original        # type: ignore[assignment]
            cli_mod.setup_logger = original_logger  # type: ignore[assignment]


def _academic_markdown() -> str:
    return (
        "# A Test Manuscript: Typesetting Check\n\n"
        "## Abstract\n\n"
        "An abstract paragraph that mentions Đổi Mới and an arrow (→) so the "
        "Unicode font path is exercised.\n\n"
        "## 1. Introduction\n\n"
        "A justified body paragraph with **bold**, *italic*, `code` and a "
        "[link](https://example.org).\n\n"
        "> A callout that must render as a box, not as a literal quote marker.\n\n"
        "| Layer | Actor | Score |\n|---|---|---:|\n"
        "| Party | Politburo | 3 |\n| Regulator | ABEI | 1 |\n\n"
        "- A bullet item.\n- Another bullet item.\n\n"
        "1. First numbered item\n2. Second numbered item\n\n"
        "## References\n\n"
        "[1] World Bank (2026). *A reference entry.* https://example.org/wb\n"
    )


def test_academic_pdf_parser_and_inline_markup() -> None:
    from research_tool.reporters.academic_pdf import (inline_markup,
                                                      parse_blocks,
                                                      strip_markdown)

    blocks, front = parse_blocks(_academic_markdown())
    kinds = [block[0] for block in blocks]
    assert front["title"] == "A Test Manuscript: Typesetting Check"
    for kind in ("h", "p", "table", "list", "quote", "code"):
        if kind != "code":                       # no fenced block in the sample
            assert kind in kinds, kinds
    table = next(block for block in blocks if block[0] == "table")
    assert table[1] == ["Layer", "Actor", "Score"]
    assert table[2][1] == ["Regulator", "ABEI", "1"]
    numbered = [b for b in blocks if b[0] == "list" and b[2]]
    assert numbered and numbered[0][1] == ["First numbered item",
                                          "Second numbered item"]
    markup = inline_markup("a **bold** and `code` and *ital*")
    assert "<b>bold</b>" in markup and "<i>ital</i>" in markup
    assert strip_markdown("**FINALIZED RESEARCH PAPER** · x") == \
        "FINALIZED RESEARCH PAPER · x"


def test_academic_pdf_has_no_markdown_leaks() -> None:
    from research_tool.reporters.academic_pdf import render_manuscript

    pdf = render_manuscript(_academic_markdown(),
                            subtitle="Working paper · FINAL",
                            meta_line="Analyst · Paper ID test_2026-11-22",
                            keywords="testing, typesetting")
    assert pdf.startswith(b"%PDF")
    try:
        from io import BytesIO

        from PyPDF2 import PdfReader
    except ImportError:                          # PDF parser is optional
        return
    text = "\n".join(page.extract_text() or ""
                     for page in PdfReader(BytesIO(pdf)).pages)
    for leak in ("|---|---|", "```", "**", "> **"):
        assert leak not in text, leak
    assert "Đổi Mới" in text and "→" in text     # Unicode font path
    assert "Page 1 of" in text                   # running footer
    assert "A bullet item." in text


def test_pdf_mirror_shelf_uses_readable_names() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lib = PaperLibrary(Path(tmp))
        meta = lib.publish(_report(), formats=["markdown", "pdf"],
                           title="Jane Doe | OSINT review",
                           published_at=datetime(2026, 11, 21, 9, 0))
        assert f"{meta.topic}/jane-doe_2026-11-21.pdf" in meta.files
        mirror = Path(tmp) / PDF_MIRROR_DIR
        names = [path.name for path in mirror.glob("*.pdf")]
        assert names == ["Jane_Doe_OSINT_review_2026.pdf"], names
        # rebuild prunes nothing that is still referenced
        lib.rebuild_pdf_mirror()
        assert [p.name for p in mirror.glob("*.pdf")] == names


def _chart_markdown() -> str:
    return (
        "# Visual Capability Check\n\n"
        "## Abstract\n\nA paper that shows figures as well as prose.\n\n"
        "## 1. Panels\n\n"
        "```chart-stats\n"
        "title: Headline figures\n"
        "| $817M | Market |\n| 58.5M | Players |\n```\n\n"
        "```chart-bars\n"
        "title: Female share (percent)\n"
        "| Franchise | Female |\n| Genshin | 45 |\n| Blue Archive | 10 |\n```\n\n"
        "```chart-line\n"
        "title: Rank (higher is worse)\n"
        "| Month | Rank |\n| June | 78 |\n| November | 153 |\n```\n\n"
        "```chart-heatmap\n"
        "| Actor | Security |\n| Party | 3 |\n| Industry | 0 |\n```\n\n"
        "```chart-timeline\n"
        "| 9 Nov 2024 | Decree 147 issued |\n| 18 Feb 2025 | Resolution 176 |\n"
        "```\n\n"
        "## References\n\n[1] Example source.\n")


def test_chart_parser_handles_options_and_headerless_tables() -> None:
    from research_tool.reporters.charts import parse_chart_block

    options, header, rows = parse_chart_block(
        "title: T\ncaption: C\n| A | B |\n| x | 1 |\n| y | 2 |")
    assert options == {"title": "T", "caption": "C"}
    assert header == ["A", "B"] and rows == [["x", "1"], ["y", "2"]]

    # the KPI panel and the timeline have no header row: nothing is swallowed
    options, _header, rows = parse_chart_block(
        "| $817M | Market |\n| 58.5M | Players |", has_header=False)
    assert options == {} and len(rows) == 2 and rows[0][0] == "$817M"


def test_chart_blocks_render_without_leaking_syntax() -> None:
    from research_tool.reporters.academic_pdf import render_manuscript
    from research_tool.reporters.charts import CHART_KINDS

    pdf = render_manuscript(_chart_markdown(), meta_line="Chart test")
    assert pdf.startswith(b"%PDF")
    try:
        from io import BytesIO

        from PyPDF2 import PdfReader
    except ImportError:                          # PDF parser is optional
        return
    text = "\n".join(page.extract_text() or ""
                     for page in PdfReader(BytesIO(pdf)).pages)
    for kind in CHART_KINDS:
        assert kind not in text, kind
    assert "```" not in text and "| Genshin |" not in text
    # the visuals themselves are drawn (values and labels survive)
    assert "$817M" in text and "58.5M" in text
    assert "45" in text and "Genshin" in text
    assert "Security" in text and "Decree 147 issued" in text


def test_heatmap_shades_and_rejects_empty_input() -> None:
    from research_tool.reporters.academic_pdf import build_styles
    from research_tool.reporters.charts import (bar_chart, heatmap,
                                                line_chart, stat_panel)

    styles = build_styles()
    table = heatmap(["Actor", "Security"], [["Party", "3"], ["Industry", "0"]],
                    styles, avail=400)
    assert table is not None
    # a non-numeric series yields no chart rather than a broken one
    assert bar_chart(["A", "B"], [["x", "n/a"]], width=400) is None
    assert line_chart(["A", "B"], [["x", "n/a"]], width=400) is None
    assert stat_panel([], styles, avail=400) is None


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