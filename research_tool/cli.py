"""Command-line interface for the Credential Research Toolkit.

Usage examples
--------------
    python -m research_tool search "Jane Doe"
    python -m research_tool whois example.com
    python -m research_tool credential john@example.com
    python -m research_tool full "John Smith" --format pdf
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import get_settings
from .engines import ENGINE_REGISTRY
from .engines.dark import detect_tor_proxy
from .logger import setup_logger
from .orchestrator import Orchestrator
from .reporters import write_report
from .reporters.markdown_report import MarkdownReporter
from .utils import github as github_utils
from .utils.library import PaperLibrary, load_report_file
from .utils.masking import mask_config
from .utils.retention import purge_tool_data

def _force_utf8_stdio(*streams: object) -> None:
    """Make stdout/stderr UTF-8 so non-Latin findings never crash the CLI.

    Findings, names and translated titles routinely contain non-Latin text or
    Unicode punctuation (for example a non-ASCII hyphen, U+2010). When
    output is *redirected* (a pipe or a file) Windows encodes with the locale
    code page - often cp1252 - so ``rich`` and ``loguru`` would raise
    ``UnicodeEncodeError`` and abort the run. Reconfiguring the streams to
    UTF-8 keeps output correct on modern terminals and non-fatal everywhere
    else. Never raises: a stream that cannot be reconfigured is left as-is.
    """
    for stream in streams or (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError, OSError):
            pass


# Configure before the Console (and later the logger) emit anything.
_force_utf8_stdio()

app = typer.Typer(
    name="research",
    help="Full-spectrum credential & OSINT research toolkit.",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


@app.callback()
def _global_options(
    ephemeral: bool = typer.Option(
        False, "--ephemeral",
        help="Keep nothing on disk: in-memory cache, no report or log files."),
    no_persist: bool = typer.Option(
        False, "--no-persist", help="Alias for --ephemeral."),
    authorized: bool = typer.Option(
        False, "--i-have-authorization",
        help="Confirm you are authorised to research this target (required "
             "when ethics.require_attestation is enabled)."),
) -> None:
    """Global privacy & authorisation options."""
    if ephemeral or no_persist:
        os.environ["RESEARCH_EPHEMERAL"] = "1"
    if authorized:
        os.environ["RESEARCH_AUTHORIZED"] = "1"


def _has_socks() -> bool:
    """True when PySocks is installed (required for SOCKS/Tor proxies)."""
    return importlib.util.find_spec("socks") is not None


def _bootstrap(verbose: bool = False, tor: bool = False) -> Orchestrator:
    settings = get_settings()
    if (settings.ethics.require_attestation
            and os.environ.get("RESEARCH_AUTHORIZED") != "1"):
        console.print(
            "[red]Authorisation attestation required.[/red] Re-run with "
            "[bold]--i-have-authorization[/bold] once you have confirmed you "
            "are authorised to research this target.")
        raise typer.Exit(code=2)
    if tor:
        proxy = detect_tor_proxy(settings)
        if proxy:
            settings.http.proxy = proxy
        else:
            console.print(
                "[yellow]Warning:[/yellow] --tor requested but no local Tor was "
                "detected on 127.0.0.1:9050/9150. Continuing without Tor - the "
                "'dark' engine will report what it cannot reach."
            )
    if (settings.http.proxy and settings.http.proxy.startswith("socks")
            and not _has_socks()):
        console.print(
            "[yellow]Warning:[/yellow] SOCKS proxy is configured but PySocks "
            "is not installed - run [bold]pip install PySocks[/bold]."
        )
    level = "DEBUG" if verbose else settings.logging.level
    log_file = None if settings.privacy.ephemeral else settings.logging.log_file
    if settings.privacy.ephemeral and settings.logging.log_file:
        console.print("[dim]Ephemeral mode: log file disabled.[/dim]")
    setup_logger(
        level=level,
        log_file=log_file,
        rotation=settings.logging.rotation,
        retention=settings.logging.retention,
        redact_pii=settings.logging.redact_pii,
    )
    return Orchestrator(settings)


def _print_report(report) -> None:
    console.print(Panel.fit(
        f"[bold]{report.target}[/bold]  ({report.target_kind})\n"
        f"Findings: [cyan]{len(report.findings)}[/cyan]   "
        f"Risk: [yellow]{report.risk_score}/100[/yellow]   "
        f"Engines: {', '.join(report.engines_run) or 'none'}",
        title="Research Result",
    ))
    if report.summary:
        console.print(Panel(report.summary, title="Summary", border_style="green"))
    if not report.findings:
        console.print("[dim]No findings.[/dim]")
        return
    table = Table(show_lines=False, header_style="bold magenta")
    table.add_column("#", justify="right", width=4)
    table.add_column("Engine", style="cyan", width=16)
    table.add_column("Category", width=12)
    table.add_column("Finding", overflow="fold")
    table.add_column("Conf", justify="right", width=5)
    for i, f in enumerate(report.findings, 1):
        table.add_row(str(i), f.engine, f.category, f.title, f"{f.confidence:.2f}")
    console.print(table)
    if report.errors:
        console.print(Panel("\n".join(report.errors), title="Errors",
                            border_style="red"))


def _write_if(fmt: Optional[str], report, orch: Orchestrator) -> None:
    if not fmt:
        return
    if orch.settings.privacy.ephemeral:
        console.print(
            "[yellow]Ephemeral mode:[/yellow] report not written to disk. "
            "Printing Markdown to stdout instead.")
        console.print(MarkdownReporter().render(report))
        return
    path = write_report(report, fmt, orch.settings.reports_path,
                        encrypt=orch.settings.reporting.encrypt)
    label = "Report encrypted" if orch.settings.reporting.encrypt \
        else "Report written"
    console.print(f"[green]{label}:[/green] {path}")


def _paper_library(settings) -> PaperLibrary:
    """Build a :class:`PaperLibrary` from the effective settings."""
    return PaperLibrary(settings.papers_path,
                        author=settings.papers.author,
                        default_status=settings.papers.default_status)


# ----------------------------------------------------------------------
@app.command()
def search(
    target: str = typer.Argument(..., help="Search query / name / subject"),
    limit: int = typer.Option(10, help="Max results per query"),
    fmt: Optional[str] = typer.Option(None, "--format", "-f", help="Write report: markdown|pdf|excel|json"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run a web/news search."""
    orch = _bootstrap(verbose)
    report = orch.run_engine("search", target, limit=limit)
    _print_report(report)
    _write_if(fmt, report, orch)


@app.command()
def social(
    username: str = typer.Argument(..., help="Username (without @)"),
    fmt: Optional[str] = typer.Option(None, "--format", "-f"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Enumerate public profiles for a username."""
    orch = _bootstrap(verbose)
    report = orch.run_engine("social", username)
    _print_report(report)
    _write_if(fmt, report, orch)


@app.command()
def whois(
    domain: str = typer.Argument(..., help="Domain name, e.g. example.com"),
    fmt: Optional[str] = typer.Option(None, "--format", "-f"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """WHOIS registration lookup."""
    orch = _bootstrap(verbose)
    report = orch.run_engine("whois", domain)
    _print_report(report)
    _write_if(fmt, report, orch)


@app.command()
def domain(
    target: str = typer.Argument(..., help="Domain name"),
    fmt: Optional[str] = typer.Option(None, "--format", "-f"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """DNS / certificate-transparency / Shodan domain intelligence."""
    orch = _bootstrap(verbose)
    report = orch.run_engine("domain_intel", target)
    _print_report(report)
    _write_if(fmt, report, orch)



@app.command()
def credential(
    email: str = typer.Argument(..., help="Email address to check"),
    fmt: Optional[str] = typer.Option(None, "--format", "-f"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Email syntax / MX / breach exposure check."""
    orch = _bootstrap(verbose)
    report = orch.run_engine("credential_check", email)
    _print_report(report)
    _write_if(fmt, report, orch)


@app.command()
def academic(
    name: str = typer.Argument(..., help="Holder name"),
    issuer: Optional[str] = typer.Option(None, help="Issuing institution"),
    kind: str = typer.Option("academic", help="academic|certification|license"),
    fmt: Optional[str] = typer.Option(None, "--format", "-f"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Corroborate an academic / professional credential."""
    orch = _bootstrap(verbose)
    report = orch.run_engine("academic", name, issuer=issuer, kind=kind)
    _print_report(report)
    _write_if(fmt, report, orch)


@app.command()
def company(
    name: str = typer.Argument(..., help="Company / legal entity name"),
    fmt: Optional[str] = typer.Option(None, "--format", "-f"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Business-registry lookup (OpenCorporates)."""
    orch = _bootstrap(verbose)
    report = orch.run_engine("company", name)
    _print_report(report)
    _write_if(fmt, report, orch)


@app.command()
def scrape(
    url: str = typer.Argument(..., help="URL to analyse"),
    fmt: Optional[str] = typer.Option(None, "--format", "-f"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Scrape a page for emails, phones, social and outbound links."""
    orch = _bootstrap(verbose)
    report = orch.run_engine("web_scraper", url)
    _print_report(report)
    _write_if(fmt, report, orch)


@app.command()
def full(
    target: str = typer.Argument(..., help="Any target: name, email, domain, username, url"),
    engines: Optional[str] = typer.Option(
        None, help="Comma-separated engine subset, e.g. search,whois"
    ),
    fmt: Optional[str] = typer.Option(
        None, "--format", "-f", help="Write report: markdown|pdf|excel|json"
    ),
    tor: bool = typer.Option(False, "--tor", help="Route through local Tor (socks5h://127.0.0.1:9050)"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run all applicable engines and build a full report."""
    orch = _bootstrap(verbose, tor=tor)
    engine_list = [e.strip() for e in engines.split(",")] if engines else None
    report = orch.run_full(target, engines=engine_list)
    _print_report(report)
    _write_if(fmt, report, orch)


@app.command()
def dark(
    target: str = typer.Argument(..., help="Keyword, domain, or .onion address"),
    limit: int = typer.Option(10, help="Max dark-web search results"),
    tor: bool = typer.Option(False, "--tor", help="Route through local Tor (socks5h://127.0.0.1:9050)"),
    fmt: Optional[str] = typer.Option(None, "--format", "-f"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Dark-web / .onion search and analysis (Tor)."""
    orch = _bootstrap(verbose, tor=tor)
    report = orch.run_engine("dark", target, limit=limit)
    _print_report(report)
    _write_if(fmt, report, orch)


@app.command()
def regional_search(
    target: str = typer.Argument(..., help="Search query / name / subject"),
    region: Optional[str] = typer.Option(
        None, "--region", "-r", help="Region alias: cn | kr | ru | global"),
    sources: Optional[str] = typer.Option(
        None, "--sources", help="Comma-separated: baidu,naver,yandex,searx"),
    limit: int = typer.Option(10, help="Max results per source"),
    translate: bool = typer.Option(
        True, "--translate/--no-translate",
        help="Translate non-Latin result titles back to English"),
    fmt: Optional[str] = typer.Option(None, "--format", "-f"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Search regional (non-anglophone) web indices (Baidu/Naver/Yandex/SearXNG)."""
    orch = _bootstrap(verbose)
    src = [s.strip() for s in sources.split(",")] if sources else None
    report = orch.run_engine("regional_search", target, region=region,
                             sources=src, limit=limit,
                             translate_results=translate)
    _print_report(report)
    _write_if(fmt, report, orch)


@app.command()
def regional_social(
    username: str = typer.Argument(..., help="Username (without @)"),
    fmt: Optional[str] = typer.Option(None, "--format", "-f"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Enumerate regional social platforms (VK / Weibo / Zhihu / LINE / ...)."""
    orch = _bootstrap(verbose)
    report = orch.run_engine("regional_social", username)
    _print_report(report)
    _write_if(fmt, report, orch)


@app.command()
def sanctions(
    target: str = typer.Argument(..., help="Person or organisation name"),
    source: Optional[str] = typer.Option(
        None, "--source", "-s",
        help="Comma-separated: ofac,un,eu,uk,opensanctions"),
    threshold: float = typer.Option(
        0.8, help="Fuzzy-match threshold (0..1; higher = stricter)"),
    limit: int = typer.Option(10, help="Max matches to report"),
    fmt: Optional[str] = typer.Option(None, "--format", "-f"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Screen a name against OFAC / UN / EU / UK sanctions lists."""
    orch = _bootstrap(verbose)
    src = [s.strip() for s in source.split(",")] if source else None
    report = orch.run_engine("sanctions", target, source=src,
                             threshold=threshold, limit=limit)
    _print_report(report)
    _write_if(fmt, report, orch)


@app.command()
def engines() -> None:
    """List available engines and their enabled state."""
    settings = get_settings()
    table = Table(title="Available Engines", header_style="bold magenta")
    table.add_column("Name", style="cyan")
    table.add_column("Enabled")
    table.add_column("Class")
    for name, cls in ENGINE_REGISTRY.items():
        enabled = getattr(settings.engines, name, True)
        table.add_row(name, "[green]yes[/green]" if enabled else "[red]no[/red]",
                      cls.__name__)
    console.print(table)


@app.command()
def config() -> None:
    """Show the effective configuration (secrets masked)."""
    settings = get_settings()
    # mask_config covers every secret slot: api_keys, deepl_key,
    # opensanctions_key, tor_control_password, github.token, server secrets
    # and proxy URLs with embedded credentials.
    console.print_json(json.dumps(mask_config(settings.model_dump()),
                                  default=str))


@app.command()
def researcher(
    name: str = typer.Argument(..., help="Researcher name as on publications"),
    limit: int = typer.Option(10, help="Max author records"),
    fmt: Optional[str] = typer.Option(None, "--format", "-f"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """OpenAlex author profile (works, citations, h-index, ORCID)."""
    orch = _bootstrap(verbose)
    report = orch.run_engine("openalex", name, limit=limit)
    _print_report(report)
    _write_if(fmt, report, orch)


@app.command()
def orcid(
    name: str = typer.Argument(..., help="Researcher name"),
    limit: int = typer.Option(10, help="Max ORCID records"),
    fmt: Optional[str] = typer.Option(None, "--format", "-f"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """ORCID researcher-identity registry lookup."""
    orch = _bootstrap(verbose)
    report = orch.run_engine("orcid", name, limit=limit)
    _print_report(report)
    _write_if(fmt, report, orch)


@app.command()
def license(
    name: str = typer.Argument(..., help='Provider name, e.g. "John Smith"'),
    state: Optional[str] = typer.Option(None, help="US state code, e.g. NY"),
    limit: int = typer.Option(10, help="Max provider records"),
    fmt: Optional[str] = typer.Option(None, "--format", "-f"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """NPI Registry lookup (US healthcare provider licensing)."""
    orch = _bootstrap(verbose)
    report = orch.run_engine("npi", name, state=state, limit=limit)
    _print_report(report)
    _write_if(fmt, report, orch)


@app.command()
def publish(
    target: Optional[str] = typer.Argument(
        None, help="Target to research (omit with --from to finalize a report)"),
    from_report: Optional[str] = typer.Option(
        None, "--from",
        help="Finalize an existing JSON report instead of running engines."),
    engines: Optional[str] = typer.Option(
        None, help="Comma-separated engine subset for the research run"),
    title: Optional[str] = typer.Option(
        None, help="Paper title (default: 'Research Paper: <target>')"),
    topic: Optional[str] = typer.Option(
        None, "--topic", "-t",
        help="Topic shelf/folder (default: derived from target kind)"),
    author: Optional[str] = typer.Option(
        None, "--author", "-a",
        help="Author / analyst credited on the paper"),
    tags: Optional[str] = typer.Option(
        None, help="Comma-separated tags for lookup"),
    abstract: Optional[str] = typer.Option(
        None, help="Abstract override (default: report summary)"),
    status: Optional[str] = typer.Option(
        None, help="draft | final (default: papers.default_status)"),
    formats: Optional[str] = typer.Option(
        None, "--format", "-f",
        help="Comma-separated: markdown,pdf,json (default: papers.formats)"),
    include_raw: Optional[bool] = typer.Option(
        None, "--include-raw/--no-raw",
        help="Append the raw-findings appendix (default: papers.include_raw)"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Finalize research into the paper library (papers/).

    Reports in data/raw/ only hold the information the engines found.
    A finalized paper is the curated, citable write-up: it follows the
    library's naming/topic rules and is registered in the paper index.
    """
    settings = get_settings()
    if settings.privacy.ephemeral:
        console.print(
            "[red]publish is incompatible with ephemeral mode:[/red] the "
            "paper library is written to disk. Drop --ephemeral to "
            "finalize a paper.")
        raise typer.Exit(code=2)
    orch = _bootstrap(verbose)

    source_report: Optional[str] = None
    saved_meta: dict = {}
    if from_report:
        path = Path(from_report)
        if not path.exists():
            console.print(f"[red]Not found:[/red] {path}")
            raise typer.Exit(code=1)
        try:
            report, saved_meta = load_report_file(path)
        except (ValueError, OSError) as exc:
            console.print(f"[red]Could not read report:[/red] {exc}")
            raise typer.Exit(code=1)
        source_report = str(path)
    else:
        if not target:
            console.print(
                "[red]Provide a TARGET or --from <report.json>.[/red]")
            raise typer.Exit(code=2)
        engine_list = ([e.strip() for e in engines.split(",")]
                       if engines else None)
        report = orch.run_full(target, engines=engine_list)

    _print_report(report)

    fmt_list = ([f.strip() for f in formats.split(",") if f.strip()]
                if formats else list(orch.settings.papers.formats))
    tag_list = ([t.strip() for t in tags.split(",") if t.strip()]
                if tags else saved_meta.get("tags"))
    use_raw = (orch.settings.papers.include_raw if include_raw is None
               else include_raw)
    lib = _paper_library(orch.settings)
    try:
        meta = lib.publish(
            report,
            formats=fmt_list,
            topic=topic or saved_meta.get("topic"),
            title=title or saved_meta.get("title"),
            author=author,
            abstract=abstract or saved_meta.get("abstract"),
            tags=tag_list,
            status=status,
            include_raw=use_raw,
            source_report=source_report,
        )
    except (ValueError, OSError) as exc:
        console.print(f"[red]Publish failed:[/red] {exc}")
        raise typer.Exit(code=1)

    table = Table(title="Finalized paper published",
                  header_style="bold magenta")
    table.add_column("Field", style="cyan")
    table.add_column("Value", overflow="fold")
    for label, value in (
        ("Paper ID", meta.paper_id),
        ("Title", meta.title),
        ("Topic shelf", meta.topic),
        ("Status", meta.status),
        ("Author", meta.author),
        ("Risk", f"{meta.risk_score}/100 ({meta.risk_label})"),
        ("Findings / sources", f"{meta.findings} / {meta.sources}"),
        ("Files", ", ".join(meta.files)),
    ):
        table.add_row(label, value)
    console.print(table)
    console.print(f"[green]Library:[/green] {orch.settings.papers_path}")
    console.print(
        f"[dim]Index: {orch.settings.papers_path / 'INDEX.md'} "
        "(auto-generated)[/dim]")


@app.command()
def papers(
    topic: Optional[str] = typer.Option(
        None, "--topic", "-t",
        help="Filter by topic shelf (e.g. people, domains, general)"),
    query: Optional[str] = typer.Option(
        None, "--query", "-q",
        help="Free-text search over titles, targets, abstracts and tags"),
    status: Optional[str] = typer.Option(
        None, "--status", help="draft | final | archived"),
    archived: bool = typer.Option(
        False, "--archived", help="Include archived papers in the listing"),
    rebuild: bool = typer.Option(
        False, "--rebuild-index",
        help="Regenerate INDEX.md / INDEX.json from the records first"),
    limit: int = typer.Option(50, help="Max rows to show"),
) -> None:
    """Find finalized papers in the library (browse the catalogue)."""
    settings = get_settings()
    lib = _paper_library(settings)
    if rebuild:
        index_path = lib.rebuild_index()
        console.print(f"[green]Index rebuilt:[/green] {index_path}")
    status_filter = status.strip().lower() if status else None
    include_archived = archived or status_filter == "archived"
    records = lib.find(topic=topic, query=query, status=status_filter,
                       include_archived=include_archived, limit=limit)
    if not records:
        console.print(
            "[dim]No papers found.[/dim] Finalize one with "
            '[bold]python -m research_tool publish "<target>" -f markdown'
            "[/bold].")
        console.print(f"[dim]Library: {settings.papers_path}[/dim]")
        return
    table = Table(title=f"Finalized papers ({len(records)})",
                  header_style="bold magenta")
    table.add_column("Paper ID", style="cyan", overflow="fold")
    table.add_column("Title", overflow="fold")
    table.add_column("Topic", width=12)
    table.add_column("Status", width=10)
    table.add_column("Published", width=11)
    table.add_column("Risk", justify="right", width=14)
    table.add_column("Findings", justify="right", width=8)
    for record in records:
        colour = {"archived": "dim", "draft": "yellow"}.get(
            record.status, "green")
        table.add_row(
            record.paper_id, record.title, record.topic,
            f"[{colour}]{record.status}[/{colour}]",
            record.created_at.strftime("%Y-%m-%d"),
            f"{record.risk_score}/100 ({record.risk_label})",
            str(record.findings))
    console.print(table)
    console.print(
        f"[dim]Library: {settings.papers_path} · Index: "
        f"{settings.papers_path / 'INDEX.md'}[/dim]")


@app.command("archive-paper")
def archive_paper(
    paper_id: str = typer.Argument(
        ..., help="Paper ID, e.g. jane-doe_2026-11-21"),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Do not ask for confirmation."),
) -> None:
    """Move a paper (with all its files) to the library's _archive/ shelf."""
    settings = get_settings()
    lib = _paper_library(settings)
    if not yes:
        typer.confirm(f"Archive paper '{paper_id}'?", abort=True)
    try:
        meta = lib.archive(paper_id)
    except (FileNotFoundError, OSError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    console.print(
        f"[green]Archived:[/green] {meta.paper_id} -> "
        f"{settings.papers_path / '_archive' / meta.topic}")
    console.print(
        f"[dim]Index rebuilt: {settings.papers_path / 'INDEX.md'}[/dim]")


@app.command()
def purge(
    older_than_hours: Optional[int] = typer.Option(
        None, "--older-than-hours",
        help="Only purge items older than this (default: "
             "privacy.retention_hours)."),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Do not ask for confirmation."),
    include_papers: bool = typer.Option(
        False, "--include-papers",
        help="Also purge the finalized-paper library (off by default: "
             "papers are deliberate deliverables)."),
) -> None:
    """Securely delete this toolkit's cache, reports, logs and audit log.

    Finalized papers in papers/ are kept unless --include-papers is
    given explicitly.
    """
    settings = get_settings()
    hours = (older_than_hours if older_than_hours is not None
             else settings.privacy.retention_hours)
    if not yes:
        extra = " INCLUDING finalized papers" if include_papers else ""
        typer.confirm(
            f"Permanently delete tool data older than {hours}h{extra}?",
            abort=True)
    summary = purge_tool_data(settings, older_than_hours=older_than_hours,
                              include_papers=include_papers)
    table = Table(title="Purge summary", header_style="bold magenta")
    table.add_column("Area", style="cyan")
    table.add_column("Files removed", justify="right")
    for area, count in summary.items():
        table.add_row(area, str(count))
    console.print(table)


@app.command()
def keygen(
    key_bytes: int = typer.Option(
        48, "--bytes", help="Key length in bytes (minimum 32)."),
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="Print only the raw key."),
) -> None:
    """Generate a random master key for encryption at rest."""
    import secrets

    key = base64.urlsafe_b64encode(
        secrets.token_bytes(max(32, key_bytes))).decode("ascii")
    if quiet:
        console.print(key)
        return
    console.print(Panel.fit(f"[bold]{key}[/bold]",
                            title="RESEARCH_ENCRYPTION_KEY",
                            border_style="green"))
    console.print(
        "Export it before running so cache/report encryption works:\n"
        f'  [cyan]PowerShell:[/cyan] $env:RESEARCH_ENCRYPTION_KEY = "{key}"\n'
        f'  [cyan]bash:[/cyan]       export RESEARCH_ENCRYPTION_KEY="{key}"\n\n'
        "[yellow]Keep it in a password manager and never commit it.[/yellow] "
        "Losing the key makes encrypted cache/reports unrecoverable.")


@app.command()
def decrypt(
    path: str = typer.Argument(..., help="Path to an encrypted .enc file"),
    out: Optional[str] = typer.Option(
        None, "--out", "-o", help="Output path (default: strip the .enc)."),
) -> None:
    """Decrypt a report/blob written with reporting.encrypt (needs the key)."""
    from .utils import crypto

    src = Path(path)
    if not src.exists():
        console.print(f"[red]Not found:[/red] {src}")
        raise typer.Exit(code=1)
    try:
        data = crypto.decrypt_bytes(src.read_bytes())
    except crypto.CryptoError as exc:
        console.print(f"[red]Decryption failed:[/red] {exc}")
        raise typer.Exit(code=1)
    if out:
        dest = Path(out)
    elif src.suffix == ".enc":
        dest = src.with_suffix("")
    else:
        dest = src.with_name(src.name + ".dec")
    dest.write_bytes(data)
    console.print(f"[green]Decrypted:[/green] {dest}")


@app.command()
def hash_password(
    password: Optional[str] = typer.Option(
        None, "--password", "-p", prompt=True, hide_input=True,
        confirmation_prompt=True,
        help="Password to hash (prompted securely when omitted)."),
) -> None:
    """Hash an admin password for RESEARCH_ADMIN_PASSWORD_HASH.

    The output is a salted PBKDF2-HMAC-SHA256 verifier. Store it in an
    environment variable; the plaintext password never has to be kept.
    """
    from .server import hash_password as _hash

    try:
        verifier = _hash(password or "")
    except ValueError as exc:
        console.print(f"[red]Cannot hash password:[/red] {exc}")
        raise typer.Exit(code=1)
    console.print(Panel.fit(
        verifier, title="RESEARCH_ADMIN_PASSWORD_HASH", border_style="green"))
    console.print(
        "Export it before starting the server (keep it out of version "
        "control):\n"
        f'  [cyan]PowerShell:[/cyan] $env:RESEARCH_ADMIN_PASSWORD_HASH = "{verifier}"\n'
        f'  [cyan]bash:[/cyan]       export RESEARCH_ADMIN_PASSWORD_HASH="{verifier}"')


@app.command()
def serve(
    host: Optional[str] = typer.Option(
        None, "--host", help="Bind address (default: server.host)."),
    port: Optional[int] = typer.Option(
        None, "--port", help="Bind port (default: server.port)."),
) -> None:
    """Run the admin web server (server-verified password authentication).

    Requires RESEARCH_ADMIN_PASSWORD or RESEARCH_ADMIN_PASSWORD_HASH. The
    server refuses to start without one, so there is no accidental open mode.
    """
    from .server import run_server

    settings = get_settings()
    if not (settings.server.admin_password
            or settings.server.admin_password_hash):
        console.print(
            "[red]No admin password configured.[/red] Set "
            "RESEARCH_ADMIN_PASSWORD, or generate a verifier with "
            "`python -m research_tool hash-password` and set "
            "RESEARCH_ADMIN_PASSWORD_HASH.")
        raise typer.Exit(code=1)
    console.print(
        f"[green]Starting admin server[/green] on "
        f"http://{host or settings.server.host}:{port or settings.server.port}")
    try:
        run_server(settings, host=host, port=port)
    except ImportError as exc:
        console.print(
            f"[red]Missing web-server dependency:[/red] {exc}\n"
            "Install it with: [cyan]pip install -r requirements.txt[/cyan]")
        raise typer.Exit(code=1)


# ----------------------------------------------------------------------
# GitHub hosting (repository + GitHub Pages)
# ----------------------------------------------------------------------
github_app = typer.Typer(
    name="github",
    help="Publish this toolkit's reports/papers to GitHub (repo + Pages).",
    no_args_is_help=True,
    add_completion=False,
)


def _github_table(title: str) -> Table:
    table = Table(title=title, header_style="bold magenta")
    table.add_column("Field", style="cyan")
    table.add_column("Value", overflow="fold")
    return table


@github_app.command()
def status() -> None:
    """Show the GitHub target, credentials and GitHub Pages state."""
    settings = get_settings()
    gh = settings.github
    token = github_utils.resolve_token(gh.token)
    table = _github_table("GitHub hosting")
    table.add_row("Enabled", "yes" if gh.enabled else "no")
    table.add_row("Repository", f"{gh.owner or '(token user)'}/{gh.repo}")
    table.add_row("Branch", gh.branch)
    table.add_row("Site folder", gh.site_dir)
    table.add_row("Token", "[green]found[/green]" if token
                  else "[yellow]not found[/yellow]")
    table.add_row(f"Remote '{gh.remote}'",
                  github_utils.git_remote_url(settings.root, gh.remote)
                  or "[dim]not set[/dim]")
    if token and gh.repo:
        try:
            client = github_utils.GitHubClient(
                token, owner=gh.owner, repo=gh.repo, branch=gh.branch)
            if not gh.owner:
                client.owner = client.whoami()
            exists = client.repo_exists()
            table.add_row("Repository exists",
                          "[green]yes[/green]" if exists else "[red]no[/red]")
            if exists:
                site = client.pages()
                table.add_row("GitHub Pages",
                              (site or {}).get("html_url") or "[dim]off[/dim]")
            if client.owner:
                table.add_row("Site URL",
                              github_utils.pages_url(client.owner, gh.repo))
        except github_utils.GitHubError as exc:
            table.add_row("API", f"[red]{exc}[/red]")
    console.print(table)


@github_app.command()
def connect(
    repo: Optional[str] = typer.Option(None, "--repo", "-r",
                                       help="Repository as owner/name"),
    visibility: Optional[str] = typer.Option(
        None, "--visibility", help="public | private (when creating the repo)"),
    remote: Optional[str] = typer.Option(None, help="git remote name"),
    branch: Optional[str] = typer.Option(None, help="branch to publish"),
    push: bool = typer.Option(False, "--push/--no-push",
                              help="Push the current checkout after linking"),
) -> None:
    """Create/link the GitHub repo and set this checkout's git remote."""
    settings = get_settings()
    owner = name = None
    if repo:
        parts = repo.split("/", 1)
        owner = parts[0] or None
        name = parts[1] if len(parts) > 1 else None
        if not (owner and name):
            console.print("[red]--repo must be owner/name[/red]")
            raise typer.Exit(code=2)
    try:
        result = github_utils.ReportHost(settings).connect(
            owner=owner, repo=name, visibility=visibility, remote=remote,
            branch=branch, push=push)
    except github_utils.GitHubError as exc:
        console.print(f"[red]Connect failed:[/red] {exc}")
        raise typer.Exit(code=1)
    table = _github_table("GitHub connection")
    for step in result["steps"]:
        mark = "[green]ok[/green]" if step["ok"] else "[red]fail[/red]"
        table.add_row(step["step"], f"{mark}  {step['detail']}")
    table.add_row("Repository", result["repo"])
    table.add_row("Site URL", result["url"])
    console.print(table)
    if not result["pushed"]:
        console.print(
            "[dim]Next:[/dim] [bold]python -m research_tool github host[/bold] "
            "(publishes the reports and enables Pages).")


@github_app.command()
def host(
    everything: bool = typer.Option(False, "--all",
                                     help="Host reports and papers together"),
    reports: Optional[bool] = typer.Option(
        None, "--reports/--no-reports", help="Include data/raw/ output"),
    papers: Optional[bool] = typer.Option(
        None, "--papers/--no-papers", help="Include papers/ (finalized)"),
    limit: Optional[int] = typer.Option(None, help="Max items per kind"),
    message: Optional[str] = typer.Option(None, "-m", "--message",
                                          help="Commit message"),
    pages: Optional[bool] = typer.Option(
        None, "--pages/--no-pages", help="Enable/refresh GitHub Pages"),
    branch: Optional[str] = typer.Option(None, help="Branch to publish to"),
    raw_json: Optional[bool] = typer.Option(
        None, "--raw-json/--no-raw-json",
        help="Also publish machine-readable .json dumps (full database)"),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Build the site but do not upload"),
) -> None:
    """Build a static site from the reports/papers and publish it to GitHub."""
    settings = get_settings()
    gh = settings.github
    do_reports = everything or (gh.host_reports if reports is None else reports)
    do_papers = everything or (gh.host_papers if papers is None else papers)
    enable_pages = gh.pages if pages is None else pages
    include_raw_json = gh.host_raw_json if raw_json is None else raw_json
    if include_raw_json and gh.visibility != "private" and not dry_run:
        console.print(
            "[yellow]Warning:[/yellow] publishing raw .json dumps to a "
            "repository whose visibility is not 'private' exposes the full "
            "database. Prefer [cyan]--no-raw-json[/cyan] or set "
            "github.visibility: private.")
    try:
        result = github_utils.ReportHost(settings).host(
            reports=do_reports, papers=do_papers, limit=limit, message=message,
            enable_pages=enable_pages, dry_run=dry_run, branch=branch,
            include_raw_json=include_raw_json)
    except github_utils.GitHubError as exc:
        console.print(f"[red]Host failed:[/red] {exc}")
        raise typer.Exit(code=1)
    if result.get("skipped"):
        console.print(f"[yellow]{result['skipped']}.[/yellow] Run some engines "
                      "with --format first (or run 'publish').")
        return
    table = _github_table("Site preview (dry run)" if dry_run
                          else "Hosted on GitHub")
    table.add_row("Items", str(result["hosted"]))
    table.add_row("Site folder", result["site_dir"])
    table.add_row("Files", str(len(result["files"])))
    table.add_row("Method", result.get("method") or "—")
    if result.get("commit"):
        table.add_row("Commit", result["commit"][:12])
    if result.get("pages"):
        table.add_row("GitHub Pages", "[green]enabled[/green]")
    if result.get("pages_error"):
        table.add_row("Pages error", f"[yellow]{result['pages_error']}[/yellow]")
    if result.get("url"):
        table.add_row("Site URL", result["url"])
    console.print(table)
    if dry_run:
        console.print("[dim]Dry run: nothing uploaded. Review the site folder, "
                      "then re-run without --dry-run.[/dim]")
    elif result.get("method") == "api":
        console.print("[dim]The site was committed through the GitHub API - run "
                      "`git pull` before your next local commit.[/dim]")


app.add_typer(github_app, name="github")

def main() -> None:
    app()


if __name__ == "__main__":
    main()
