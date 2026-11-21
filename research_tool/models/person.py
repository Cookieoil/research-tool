"""Person / identity data models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SocialProfile(BaseModel):
    platform: str
    url: str
    username: str | None = None
    verified: bool = False


class Person(BaseModel):
    """A research subject (individual)."""

    name: str | None = None
    emails: list[str] = Field(default_factory=list)
    usernames: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    social_profiles: list[SocialProfile] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


__all__ = ["Person", "SocialProfile"]
