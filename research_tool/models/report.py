"""Report & finding data models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Finding(BaseModel):
    """A single normalised result produced by an engine."""

    engine: str
    category: str                       # identity | credential | domain | company ...
    title: str
    detail: str | None = None
    url: str | None = None
    confidence: float = 0.5             # 0..1
    data: dict[str, Any] = Field(default_factory=dict)


class ResearchReport(BaseModel):
    target: str
    target_kind: str = "unknown"
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    findings: list[Finding] = Field(default_factory=list)
    summary: str | None = None
    risk_score: int = 0
    engines_run: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


__all__ = ["Finding", "ResearchReport"]
