"""Organization data models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Organization(BaseModel):
    name: str
    domain: str | None = None
    registry_id: str | None = None      # company / tax registration number
    jurisdiction: str | None = None
    status: str | None = None           # active | dissolved | unknown
    incorporation_date: str | None = None
    address: str | None = None
    officers: list[str] = Field(default_factory=list)
    source_url: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


__all__ = ["Organization"]
