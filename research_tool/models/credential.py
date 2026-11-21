"""Credential & breach-check data models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Breach(BaseModel):
    name: str
    domain: str | None = None
    breach_date: str | None = None
    pwn_count: int | None = None
    data_classes: list[str] = Field(default_factory=list)
    description: str | None = None
    is_verified: bool | None = None


class CredentialCheck(BaseModel):
    """Result of checking an email against breach/verification services."""

    email: str
    breached: bool = False
    breach_count: int = 0
    breaches: list[Breach] = Field(default_factory=list)
    services_registered: list[str] = Field(default_factory=list)
    syntax_valid: bool = True
    disposable: bool | None = None
    mx_valid: bool | None = None
    risk_score: int = 0
    sources: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
    checked_at: datetime = Field(default_factory=datetime.utcnow)


class Credential(BaseModel):
    """A claimed academic or professional credential."""

    kind: str = "unknown"          # degree | license | certification | employment
    title: str | None = None
    issuer: str | None = None
    holder: str | None = None
    identifier: str | None = None
    issued_date: str | None = None
    expiry_date: str | None = None
    status: str = "unverified"     # unverified | verified | not_found | expired
    verified: bool = False
    source_url: str | None = None
    notes: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


__all__ = ["Breach", "CredentialCheck", "Credential"]
