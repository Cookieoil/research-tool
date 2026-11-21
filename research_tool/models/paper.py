"""Data model for a finalized research paper's library record."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PaperMeta(BaseModel):
    """Catalogue record stored beside every finalized paper.

    The record is the single source of truth for ``INDEX.md`` /
    ``INDEX.json`` and for the ``papers`` lookup command. Publishing always
    writes one, so a paper can be found by topic, target, tag, status or
    free-text query without opening the documents themselves.
    """

    paper_id: str
    title: str
    target: str
    target_kind: str = "unknown"
    topic: str = "general"
    status: str = "final"          # draft | final | archived
    author: str = "None-Bias Research Agent"
    abstract: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    risk_score: int = 0
    risk_label: str = "NONE"
    findings: int = 0
    engines: list[str] = Field(default_factory=list)
    sources: int = 0
    # Document files, relative to the paper-library root (POSIX separators).
    files: list[str] = Field(default_factory=list)
    # Path of the raw report this paper was finalized from, when applicable.
    source_report: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


__all__ = ["PaperMeta"]