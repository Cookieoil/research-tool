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
                              "people/jane-doe_2026-11-21.json"]

        paper = Path(tmp) / meta.files[0]
        text = paper.read_text(encoding="utf-8")
        assert "FINALIZED RESEARCH PAPER" in text
        assert "## Abstract" in text
        assert "## 4. Source register" in text
        assert "https://example.com/jane" in text
        assert "## Appendix A" in text        # include_raw appendix

        record = Path(tmp) / "people" / "jane-doe_2026-11-21.meta.json"
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
    assert "## 4. Source register" in markdown
    assert "F1" in markdown and "S1" in markdown
    assert "No registry match" in markdown
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

            record = next((papers_dir / "people").glob("*.meta.json"))
            paper_id = record.name[:-len(".meta.json")]
            archived = runner.invoke(cli_mod.app,
                                     ["archive-paper", paper_id, "-y"], env=env)
            assert archived.exit_code == 0, archived.output
            assert (papers_dir / ARCHIVE_DIR / "people").exists()
        finally:
            cli_mod.get_settings = original        # type: ignore[assignment]
            cli_mod.setup_logger = original_logger  # type: ignore[assignment]


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