"""Data-retention and secure-deletion helpers.

The toolkit keeps derived data on disk (response cache, generated reports,
optional audit log). Data minimisation means that data should not linger
indefinitely and must be removable on request. These helpers purge
tool-owned files older than a retention window and overwrite file contents
before unlinking.

Caveat: overwriting in place gives no guarantee on SSDs, copy-on-write
filesystems or journalled volumes that retain old blocks, so secure deletion
is best-effort. Full-disk encryption is the stronger control.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

_BLOCK = 64 * 1024


def _overwrite(path: Path, *, passes: int = 1) -> bool:
    """Overwrite *path* with random bytes, then unlink it."""
    try:
        size = path.stat().st_size
        with open(path, "r+b") as fh:
            for _ in range(max(1, passes)):
                fh.seek(0)
                remaining = size
                while remaining > 0:
                    n = min(_BLOCK, remaining)
                    fh.write(os.urandom(n))
                    remaining -= n
                fh.flush()
                os.fsync(fh.fileno())
        path.unlink()
        return True
    except OSError:
        try:
            path.unlink()
            return True
        except OSError:
            return False


def secure_delete(path: str | Path, *, passes: int = 1) -> bool:
    """Securely delete a file, or every file in a directory tree."""
    p = Path(path)
    if not p.exists():
        return False
    if p.is_dir():
        for child in sorted(p.rglob("*"), key=lambda c: len(c.parts),
                            reverse=True):
            if child.is_file():
                _overwrite(child, passes=passes)
            elif child.is_dir():
                try:
                    child.rmdir()
                except OSError:
                    pass
        try:
            p.rmdir()
        except OSError:
            pass
        return True
    return _overwrite(p, passes=passes)


def purge_directory(directory: str | Path, *, max_age_hours: float | None = None,
                    all_files: bool = False, passes: int = 1) -> int:
    """Securely delete files in *directory* older than a cutoff.

    ``all_files=True`` (or ``max_age_hours is None``) purges everything.
    Returns the number of files removed.
    """
    d = Path(directory)
    if not d.exists():
        return 0
    cutoff: float | None = None
    if not all_files and max_age_hours is not None:
        cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for f in [c for c in d.rglob("*") if c.is_file()]:
        try:
            if cutoff is None or f.stat().st_mtime < cutoff:
                if _overwrite(f, passes=passes):
                    removed += 1
        except OSError:
            continue
    return removed


def purge_papers(directory: str | Path, *, max_age_hours: float | None = None,
                 passes: int = 1) -> int:
    """Securely delete finalized papers but keep the rules and template.

    Unlike :func:`purge_directory` this walks the library while preserving
    ``ORGANISATION.md`` and everything under ``_templates/``. Run
    ``python -m research_tool papers --rebuild-index`` afterwards so the
    catalogue reflects what remains.
    """
    d = Path(directory)
    if not d.exists():
        return 0
    cutoff: float | None = None
    if max_age_hours is not None:
        cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for f in [c for c in d.rglob("*") if c.is_file()]:
        rel = f.relative_to(d)
        if rel.name == "ORGANISATION.md":
            continue
        if len(rel.parts) > 1 and rel.parts[0] == "_templates":
            continue
        try:
            if cutoff is None or f.stat().st_mtime < cutoff:
                if _overwrite(f, passes=passes):
                    removed += 1
        except OSError:
            continue
    return removed


def purge_tool_data(settings: Any, *,
                    older_than_hours: float | None = None,
                    include_papers: bool = False) -> dict[str, int]:
    """Purge this toolkit's derived data: reports, cache, logs, audit log.

    Finalized papers (``data/papers``) are deliberate deliverables, so they
    are **excluded by default** and only purged when *include_papers* is
    explicitly true. Even then the rules file and template are preserved.
    """
    hours = (older_than_hours if older_than_hours is not None
             else getattr(settings.privacy, "retention_hours", None))
    passes = int(getattr(settings.privacy, "secure_delete_passes", 1) or 1)
    summary: dict[str, int] = {}

    summary["reports"] = purge_directory(settings.reports_path,
                                         max_age_hours=hours, passes=passes)
    summary["cache"] = purge_directory(settings.cache_path,
                                       max_age_hours=hours, passes=passes)
    papers_path = getattr(settings, "papers_path", None)
    if include_papers and papers_path:
        summary["papers"] = purge_papers(papers_path, max_age_hours=hours,
                                         passes=passes)

    singles = {
        "log": getattr(settings.logging, "log_file", None),
        "audit_log": settings.audit_log_path,
    }
    for label, raw in singles.items():
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = settings.resolve(raw)
        if not path.exists():
            continue
        if hours is None or path.stat().st_mtime < time.time() - hours * 3600:
            summary[label] = 1 if _overwrite(path, passes=passes) else 0
        else:
            summary[label] = 0
    return summary


__all__ = ["secure_delete", "purge_directory", "purge_papers",
           "purge_tool_data"]
