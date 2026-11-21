"""Finalized research-paper library: layout, naming, index and lookup.

``data/reports/`` holds raw research output (what the engines found).
``data/papers/`` is the curated library of *finalized* papers. This module
enforces the organisation rules documented in ``data/papers/ORGANISATION.md``
so every writer produces the same layout:

    <library>/<topic>/<slug>_<YYYY-MM-DD>[_vN].<ext>
    <library>/<topic>/<paper_id>.meta.json      # catalogue record
    <library>/_archive/<topic>/                 # superseded papers
    <library>/_templates/                       # authoring template
    <library>/INDEX.md + INDEX.json             # auto-generated catalogue

``INDEX.md`` / ``INDEX.json`` are rebuilt from the ``.meta.json`` records and
must never be hand-edited.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from ..analyzers.risk_scorer import RiskScorer
from ..logger import logger
from ..models.paper import PaperMeta
from ..models.report import ResearchReport
from ..reporters.paper_report import PaperReporter, source_urls

INDEX_FILE = "INDEX.md"
INDEX_JSON = "INDEX.json"
ARCHIVE_DIR = "_archive"
TEMPLATES_DIR = "_templates"
META_SUFFIX = ".meta.json"

# Default topic ("shelf") for each detected target kind.
TOPIC_BY_KIND: dict[str, str] = {
    "name": "people",
    "email": "people",
    "username": "people",
    "domain": "domains",
    "url": "domains",
    "ip": "domains",
    "onion": "domains",
}
DEFAULT_TOPIC = "general"

PAPER_EXT: dict[str, str] = {
    "markdown": ".md", "md": ".md", "pdf": ".pdf", "json": ".json",
}


def slugify(text: str, max_length: int = 60) -> str:
    """Return a filesystem-safe, lower-kebab slug for *text*.

    Non-ASCII text is transliterated where possible; if nothing ASCII remains
    a short stable hash is used so non-Latin targets still get a usable name.
    """
    folded = unicodedata.normalize("NFKD", text).encode(
        "ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", folded).strip("-").lower()
    if not slug:
        import hashlib

        slug = "paper-" + hashlib.sha1(
            text.encode("utf-8")).hexdigest()[:8]
    return slug[:max_length].strip("-") or "paper"


def normalise_formats(formats: Iterable[str] | None) -> list[str]:
    """Validate/expand an iterable of paper formats."""
    chosen: list[str] = []
    for fmt in formats or ["markdown"]:
        fmt = str(fmt).strip().lower()
        if fmt == "md":
            fmt = "markdown"
        if fmt not in ("markdown", "pdf", "json"):
            raise ValueError(
                f"Unsupported paper format '{fmt}' "
                "(use markdown, pdf or json)")
        if fmt not in chosen:
            chosen.append(fmt)
    return chosen or ["markdown"]


def load_report_file(path: str | Path) -> tuple[ResearchReport, dict[str, Any]]:
    """Load a saved report JSON produced by ``--format json`` or ``publish``.

    Returns the :class:`ResearchReport` plus any paper metadata that was
    stored beside it (empty for a plain report).
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON report must contain an object")
    meta: dict[str, Any] = {}
    if isinstance(data.get("report"), dict):     # a published paper JSON
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        data = data["report"]
    try:
        report = ResearchReport.model_validate(data)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"not a research report: {exc}") from exc
    return report, meta
class PaperLibrary:
    """Read/write access to the finalized-paper library."""

    def __init__(self, root: str | Path, *,
                 author: str = "None-Bias Research Agent",
                 default_status: str = "final"):
        self.root = Path(root)
        self.author = author
        self.default_status = default_status

    # ---- layout ------------------------------------------------------
    def ensure_layout(self) -> Path:
        """Create the library root, archive shelf and template folder."""
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / ARCHIVE_DIR).mkdir(exist_ok=True)
        (self.root / TEMPLATES_DIR).mkdir(exist_ok=True)
        return self.root

    def topic_path(self, topic: str | None = None) -> Path:
        """Return (and create) the directory for a topic shelf."""
        name = slugify(topic) if topic else DEFAULT_TOPIC
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _unique_id(self, folder: Path, base: str,
                   archive_folder: Path | None = None) -> str:
        """Return *base*, or ``base_v2``/``base_v3``… if already taken.

        IDs already used by an archived paper stay reserved, so archiving and
        re-publishing on the same date cannot create two records with the
        same paper ID.
        """
        exts = (".md", ".pdf", ".json", META_SUFFIX)
        folders = [folder] + ([archive_folder] if archive_folder else [])

        def taken(candidate: str) -> bool:
            return any((f / f"{candidate}{ext}").exists()
                       for f in folders for ext in exts)

        candidate = base
        version = 1
        while taken(candidate):
            version += 1
            candidate = f"{base}_v{version}"
        return candidate

    # ---- publishing --------------------------------------------------
    def publish(self, report: ResearchReport, *,
                formats: Iterable[str] | None = None,
                topic: str | None = None,
                title: str | None = None,
                author: str | None = None,
                abstract: str | None = None,
                tags: Iterable[str] | None = None,
                status: str | None = None,
                include_raw: bool = False,
                source_report: str | None = None,
                published_at: datetime | None = None) -> PaperMeta:
        """Write a finalized paper (documents + record + rebuilt index).

        ``topic``/``title``/``author`` default to the library settings and the
        report target. Re-publishing the same target on the same date creates
        a new version (``_v2``, ``_v3``…) instead of overwriting anything.
        """
        self.ensure_layout()
        shelf = slugify(topic) if topic else TOPIC_BY_KIND.get(
            report.target_kind, DEFAULT_TOPIC)
        folder = self.topic_path(shelf)
        stamp = published_at or datetime.utcnow()
        paper_id = self._unique_id(
            folder, f"{slugify(report.target)}_{stamp:%Y-%m-%d}",
            self.root / ARCHIVE_DIR / shelf)
        title = (title or f"Research Paper: {report.target}").strip()
        status = (status or self.default_status).lower()
        if status not in {"draft", "final"}:
            raise ValueError("status must be 'draft' or 'final'")
        formats = normalise_formats(formats)
        urls = source_urls(report)
        files = [f"{shelf}/{paper_id}{PAPER_EXT[fmt]}" for fmt in formats]
        meta = PaperMeta(
            paper_id=paper_id,
            title=title,
            target=report.target,
            target_kind=report.target_kind,
            topic=shelf,
            status=status,
            author=author or self.author,
            abstract=abstract or report.summary,
            tags=list(tags or []),
            created_at=stamp,
            risk_score=report.risk_score,
            risk_label=RiskScorer.label(report.risk_score),
            findings=len(report.findings),
            engines=list(report.engines_run),
            sources=len(urls),
            source_report=str(source_report) if source_report else None,
            files=files,
        )
        reporter = PaperReporter()
        for fmt, rel in zip(formats, files):
            reporter.write(report, meta, self.root / rel,
                           include_raw=include_raw)
        (folder / f"{paper_id}{META_SUFFIX}").write_text(
            json.dumps(meta.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8")
        self.rebuild_index()
        logger.info("[paper-library] published {} ({})", paper_id, shelf)
        return meta
# ---- reading -----------------------------------------------------
    def records(self, include_archived: bool = True) -> list[PaperMeta]:
        """Load every ``*.meta.json`` catalogue record in the library."""
        found: list[PaperMeta] = []
        if not self.root.exists():
            return found
        for path in sorted(self.root.rglob(f"*{META_SUFFIX}")):
            rel_parts = path.relative_to(self.root).parts
            if not include_archived and ARCHIVE_DIR in rel_parts:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                found.append(PaperMeta.model_validate(data))
            except (OSError, ValueError, TypeError) as exc:
                logger.warning(
                    "[paper-library] unreadable record {}: {}",
                    path.name, exc)
        return found

    def find(self, *, topic: str | None = None, query: str | None = None,
             status: str | None = None, include_archived: bool = False,
             limit: int | None = None) -> list[PaperMeta]:
        """Find papers by shelf, free-text query, status or archived state."""
        records = self.records(include_archived=include_archived)
        if topic:
            wanted = slugify(topic)
            records = [r for r in records if r.topic == wanted]
        if status:
            wanted_status = status.strip().lower()
            records = [r for r in records if r.status == wanted_status]
        if query:
            needle = query.casefold()

            def haystack(record: PaperMeta) -> str:
                return " ".join([
                    record.paper_id, record.title, record.target,
                    record.abstract or "", record.topic, record.author,
                    " ".join(record.tags),
                ]).casefold()

            records = [r for r in records if needle in haystack(r)]
        records.sort(key=lambda r: (r.created_at, r.paper_id), reverse=True)
        return records[:limit] if limit else records
# ---- catalogue ---------------------------------------------------
    def rebuild_index(self) -> Path:
        """Regenerate ``INDEX.md`` and ``INDEX.json`` from the records."""
        self.ensure_layout()
        records = sorted(self.records(include_archived=True),
                         key=lambda r: (r.created_at, r.paper_id),
                         reverse=True)
        active = [r for r in records if r.status != "archived"]
        archived = [r for r in records if r.status == "archived"]
        now = datetime.utcnow()

        lines = [
            "# Finalized Research Papers — Index",
            "",
            "> **Auto-generated — do not edit by hand.** Rebuilt by "
            "`publish`, `archive-paper` and "
            "`python -m research_tool papers --rebuild-index`.",
            "> Organisation rules: [ORGANISATION.md](ORGANISATION.md) · Raw "
            "findings remain in `data/reports/`.",
            "",
            f"_Last rebuilt: {now:%Y-%m-%d %H:%M} UTC · "
            f"**{len(active)} active** · **{len(archived)} archived**_",
            "",
            "## Active papers",
            "",
        ]
        lines += _index_table(active)
        lines += ["", "## Archived papers", ""]
        lines += _index_table(archived, empty="_None._")
        lines += [
            "",
            "## Layout",
            "",
            "```",
            "data/papers/",
            "├── INDEX.md / INDEX.json   # this catalogue (auto-generated)",
            "├── ORGANISATION.md         # the organisation rules",
            "├── _templates/             # authoring template",
            "├── _archive/<topic>/       # superseded papers",
            "└── <topic>/                # people | organisations | domains | general",
            "    ├── <slug>_<date>.md|.pdf|.json",
            "    └── <slug>_<date>.meta.json",
            "```",
            "",
        ]
        index_path = self.root / INDEX_FILE
        index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        payload = {
            "generated_at": now.isoformat() + "Z",
            "library": self.root.as_posix(),
            "active": [r.to_dict() for r in active],
            "archived": [r.to_dict() for r in archived],
        }
        (self.root / INDEX_JSON).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8")
        return index_path

    # ---- lifecycle ---------------------------------------------------
    def archive(self, paper_id: str) -> PaperMeta:
        """Move a paper and its files to ``_archive/<topic>/``."""
        record = next((r for r in self.records(include_archived=True)
                       if r.paper_id == paper_id and r.status != "archived"),
                      None)
        if record is None:      # already archived (or unknown)
            record = next((r for r in self.records(include_archived=True)
                           if r.paper_id == paper_id), None)
        if record is None:
            raise FileNotFoundError(
                f"paper '{paper_id}' not found in {self.root}")
        if record.status == "archived":
            return record

        meta_path = self.root / record.topic / f"{paper_id}{META_SUFFIX}"
        dest_dir = self.root / ARCHIVE_DIR / record.topic
        dest_dir.mkdir(parents=True, exist_ok=True)
        moved: list[str] = []
        for rel in record.files:
            src = self.root / rel
            if not src.exists():
                continue
            dest = dest_dir / src.name
            src.replace(dest)
            moved.append(f"{ARCHIVE_DIR}/{record.topic}/{src.name}")

        record.status = "archived"
        record.files = moved
        meta_path.unlink(missing_ok=True)
        (dest_dir / f"{paper_id}{META_SUFFIX}").write_text(
            json.dumps(record.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8")
        self.rebuild_index()
        logger.info("[paper-library] archived {} ({})", paper_id, record.topic)
        return record


def _md_cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def _file_links(record: PaperMeta) -> str:
    parts: list[str] = []
    for rel in record.files:
        suffix = Path(rel).suffix.lower()
        if suffix in (".md", ".pdf", ".json"):
            parts.append(f"[{suffix.lstrip('.')}]({rel})")
        else:
            parts.append(f"`{Path(rel).name}`")
    return " · ".join(parts) or "—"


def _index_table(records: list[PaperMeta],
                 empty: str | None = None) -> list[str]:
    if not records:
        if empty is not None:
            return [empty]
        return ["_None yet. Finalize one with:_", "",
                "```powershell",
                'python -m research_tool publish "<target>" --format markdown',
                "```"]
    lines = [
        "| Paper ID | Title | Topic | Status | Published | Risk | Findings | Files |",
        "|---|---|---|---|---|---:|---:|---|",
    ]
    for record in records:
        lines.append(
            f"| `{record.paper_id}` | {_md_cell(record.title)} | "
            f"`{record.topic}` | {record.status} | "
            f"{record.created_at:%Y-%m-%d} | {record.risk_score}/100 "
            f"({record.risk_label}) | {record.findings} | "
            f"{_file_links(record)} |")
    return lines


__all__ = [
    "PaperLibrary", "load_report_file", "normalise_formats", "slugify",
    "TOPIC_BY_KIND", "DEFAULT_TOPIC", "INDEX_FILE", "INDEX_JSON",
    "ARCHIVE_DIR", "TEMPLATES_DIR",
]