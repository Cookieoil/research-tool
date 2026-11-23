"""Finalized research-paper library: layout, naming, index and lookup.

``data/raw/`` holds raw research output (what the engines found). ``papers/``
is the curated library of *finalized* papers. This module enforces the
organisation rules documented in ``papers/ORGANISATION.md`` so every writer
produces the same layout:

    <library>/<topic>/<slug>_<YYYY-MM-DD>[_vN].md|.pdf   # readable documents
    <library>/_meta/<topic>/<paper_id>.json              # machine-readable copy
    <library>/_meta/<topic>/<paper_id>.meta.json         # catalogue record
    <library>/pdfs/<Readable_Title>_<year>.pdf           # reading shelf (mirror)
    <library>/_archive/<topic>/                          # superseded papers
    <library>/_templates/                                # authoring template
    <library>/INDEX.md + INDEX.json                      # auto-generated catalogue

Splitting documents (``<topic>/``) from machine records (``_meta/<topic>/``)
keeps the shelves readable at a glance: a human opening ``papers/vietnam/``
sees papers, not a wall of JSON. ``INDEX.md`` / ``INDEX.json`` are rebuilt from
the ``.meta.json`` records and must never be hand-edited.
"""

from __future__ import annotations

import json
import os
import re
import shutil
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
META_DIR = "_meta"
PDF_MIRROR_DIR = "pdfs"
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
            text.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
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


def _rel_posix(root: Path, path: Path) -> str:
    """Return *path* relative to *root* using POSIX separators."""
    return path.relative_to(root).as_posix()


def _contained(root: Path, candidate: Path) -> Path:
    """Resolve *candidate* and refuse anything outside *root*.

    ``record.files`` entries come from JSON catalogue records; a tampered or
    hand-edited record could otherwise point at ``../../etc/passwd`` and make
    the archive/mirror code move or copy arbitrary files.
    """
    # os.path.realpath() resolves Windows 8.3 short names (e.g. RUNNER~1)
    # as well as symlinks, so both sides compare in the same form.
    base = Path(os.path.realpath(str(root)))
    resolved = Path(os.path.realpath(str(candidate)))
    if not resolved.is_relative_to(base):
        raise ValueError(f"Refusing path outside {base}: {candidate}")
    return resolved


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
        """Create the library root, archive, template and metadata folders."""
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / ARCHIVE_DIR).mkdir(exist_ok=True)
        (self.root / TEMPLATES_DIR).mkdir(exist_ok=True)
        (self.root / META_DIR).mkdir(exist_ok=True)
        return self.root

    def topic_path(self, topic: str | None = None) -> Path:
        """Return (and create) the document directory for a topic shelf."""
        name = slugify(topic) if topic else DEFAULT_TOPIC
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def meta_dir(self, topic: str | None = None) -> Path:
        """Return (and create) the machine-record directory for a shelf."""
        name = slugify(topic) if topic else DEFAULT_TOPIC
        path = self.root / META_DIR / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def meta_path(self, paper_id: str, topic: str | None = None) -> Path:
        """Return the catalogue-record path for *paper_id*."""
        return self.meta_dir(topic) / f"{paper_id}{META_SUFFIX}"

    def _unique_id(self, folder: Path, base: str,
                   archive_folder: Path | None = None,
                   records_folder: Path | None = None) -> str:
        """Return *base*, or ``base_v2``/``base_v3``… if already taken.

        IDs already used by an archived paper stay reserved, so archiving and
        re-publishing on the same date cannot create two records with the
        same paper ID.
        """
        exts = (".md", ".pdf", ".json", META_SUFFIX)
        folders = [folder] + ([archive_folder] if archive_folder else [])
        if records_folder is not None:
            folders.append(records_folder)

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
        records_folder = self.meta_dir(shelf)
        stamp = published_at or datetime.utcnow()
        paper_id = self._unique_id(
            folder, f"{slugify(report.target)}_{stamp:%Y-%m-%d}",
            self.root / ARCHIVE_DIR / shelf, records_folder)
        title = (title or f"Research Paper: {report.target}").strip()
        status = (status or self.default_status).lower()
        if status not in {"draft", "final"}:
            raise ValueError("status must be 'draft' or 'final'")
        formats = normalise_formats(formats)
        urls = source_urls(report)

        # Readable documents live on the shelf; the machine-readable JSON copy
        # lives with the catalogue record in _meta/<topic>/ so shelves stay
        # legible for humans.
        targets: list[tuple[str, Path]] = []
        for fmt in formats:
            dest = _contained(self.root, (records_folder if fmt == "json"
                                          else folder)
                              / f"{paper_id}{PAPER_EXT[fmt]}")
            targets.append((fmt, dest))
        files = [_rel_posix(self.root, dest) for _fmt, dest in targets]

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
        for fmt, dest in targets:
            reporter.write(report, meta, dest, include_raw=include_raw)
        # The catalogue record sits beside the JSON copy in _meta/<topic>/.
        meta_path = _contained(self.root, records_folder / f"{paper_id}{META_SUFFIX}")
        meta_path.write_text(
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
        """Regenerate ``INDEX.md`` and ``INDEX.json`` from the records.

        Also refreshes the ``pdfs/`` reading shelf so every publication-ready
        PDF is one click away with a human-readable filename.
        """
        self.ensure_layout()
        records = sorted(self.records(include_archived=True),
                         key=lambda r: (r.created_at, r.paper_id),
                         reverse=True)
        active = [r for r in records if r.status != "archived"]
        archived = [r for r in records if r.status == "archived"]
        now = datetime.utcnow()

        shelves: dict[str, list[PaperMeta]] = {}
        for record in active:
            shelves.setdefault(record.topic, []).append(record)

        lines = [
            "# Finalized Research Papers — Index",
            "",
            "> **Auto-generated — do not edit by hand.** Rebuilt by "
            "`publish`, `archive-paper` and "
            "`python -m research_tool papers --rebuild-index`.",
            "> Organisation rules: [ORGANISATION.md](ORGANISATION.md) · Raw "
            "engine output stays in `data/raw/` · Ready-to-read PDFs are "
            "mirrored in [pdfs/](pdfs/).",
            "",
            f"_Last rebuilt: {now:%Y-%m-%d %H:%M} UTC · "
            f"**{len(active)} active** · **{len(archived)} archived**_",
            "",
        ]
        if shelves:
            lines += ["## Shelves at a glance", "",
                      "| Shelf | Active papers | Read |",
                      "|---|---:|---|"]
            for shelf in sorted(shelves):
                lines.append(
                    f"| `{shelf}` | {len(shelves[shelf])} | "
                    f"[browse]({shelf}/) |")
            lines += [""]

        lines += [
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
            "papers/",
            "├── INDEX.md / INDEX.json   # this catalogue (auto-generated)",
            "├── ORGANISATION.md         # the organisation rules",
            "├── pdfs/                   # reading shelf: every PDF, readable names",
            "├── _meta/<topic>/          # .meta.json records + .json copies",
            "├── _templates/             # authoring template",
            "├── _archive/<topic>/       # superseded papers",
            "└── <topic>/                # vietnam | gacha | people | domains | ...",
            "    ├── <slug>_<date>.md    # manuscript (primary)",
            "    └── <slug>_<date>.pdf   # typeset edition",
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
        self.rebuild_pdf_mirror()
        return index_path

    # ---- reading shelf (pdfs/) ---------------------------------------
    def rebuild_pdf_mirror(self) -> list[Path]:
        """Mirror every active PDF into ``pdfs/`` with a readable name.

        The canonical files keep their ``<slug>_<date>.pdf`` names inside the
        topic shelves; this shelf exists so a human can find every finished
        PDF in one place without knowing a paper ID.
        """
        mirror = self.root / PDF_MIRROR_DIR
        mirror.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for record in self.records(include_archived=False):
            for rel in record.files:
                if not rel.lower().endswith(".pdf"):
                    continue
                src = _contained(self.root, self.root / rel)
                if not src.is_file():
                    continue
                dest = _contained(mirror, mirror / _pdf_mirror_name(
                    record, taken=written))
                if (not dest.exists()
                        or dest.stat().st_size != src.stat().st_size
                        or dest.read_bytes() != src.read_bytes()):
                    shutil.copyfile(src, dest)
                written.append(dest)
        for stale in mirror.glob("*.pdf"):
            if stale not in written:
                stale.unlink(missing_ok=True)
        return written

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

        meta_path = _contained(self.root, self.meta_path(paper_id, record.topic))
        dest_dir = _contained(self.root,
                              self.root / ARCHIVE_DIR / record.topic)
        dest_dir.mkdir(parents=True, exist_ok=True)
        moved: list[str] = []
        for rel in record.files:
            src = _contained(self.root, self.root / rel)
            if not src.exists():
                continue
            dest = _contained(dest_dir, dest_dir / src.name)
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


# Words that make a truncated filename end mid-thought; trimmed after capping.
_TRAILING_STOPWORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on", "or",
    "the", "to", "with", "its", "his", "her",
}


def _pdf_mirror_name(record: PaperMeta, *, taken: Iterable[Path] = ()) -> str:
    """Return a human-readable mirror filename for *record*'s PDF.

    ``"Export Factories and Controlled Liberalisation: Value Capture..."``
    published in 2026 becomes
    ``Export_Factories_and_Controlled_Liberalisation_Value_Capture_2026.pdf`` so
    the reading shelf is browsable without paper IDs. The stem is capped at a
    word boundary (never mid-word), possessives are closed up
    (``Vietnam's`` -> ``Vietnams``) and a dangling connective is trimmed.
    """
    text = record.title.replace("'", "").replace("\u2019", "")
    words = re.sub(r"[^0-9A-Za-z]+", " ", text).split()
    kept: list[str] = []
    length = 0
    for word in words:
        if kept and length + len(word) + 1 > 62:   # never cut mid-word
            break
        kept.append(word)
        length += len(word) + 1
    while len(kept) > 3 and kept[-1].lower() in _TRAILING_STOPWORDS:
        kept.pop()
    stem = "_".join(kept) or record.paper_id
    year = f"{record.created_at:%Y}"
    # Avoid "…_2026_2026.pdf" when the title already ends with the year.
    name = f"{stem}.pdf" if stem.endswith(year) else f"{stem}_{year}.pdf"
    existing = {path.name for path in taken}
    if name in existing:      # same title, same year: fall back to the ID
        name = f"{stem}_{record.paper_id}.pdf"
    return name


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
    "ARCHIVE_DIR", "TEMPLATES_DIR", "META_DIR", "PDF_MIRROR_DIR",
]