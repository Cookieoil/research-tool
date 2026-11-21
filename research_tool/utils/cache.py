"""Response cache with TTL support.

Two backends share one interface:

* :class:`ResponseCache` -- SQLite-backed and persistent. Values may be
  encrypted at rest (:mod:`research_tool.utils.crypto`).
* :class:`MemoryResponseCache` -- a process-local dict; nothing touches disk,
  used in ephemeral / memory-only mode.

:func:`build_cache` picks a backend from the settings.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from . import crypto

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


class BaseCache(ABC):
    """Common interface for the cache backends."""

    enabled: bool
    ttl: int

    @abstractmethod
    def get(self, key: str) -> Any | None: ...

    @abstractmethod
    def set(self, key: str, value: Any) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def clear(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @staticmethod
    def _hash(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()


class ResponseCache(BaseCache):
    """A tiny persistent key/value cache for expensive lookups."""

    def __init__(self, db_path: str | Path, ttl_seconds: int = 3600,
                 enabled: bool = True, encrypt: bool = False):
        self.enabled = enabled
        self.ttl = ttl_seconds
        self.encrypt = encrypt
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------
    def _encode(self, value: Any) -> str | None:
        try:
            payload = json.dumps(value, default=str)
        except (TypeError, ValueError):
            return None
        if self.encrypt:
            try:
                return crypto.encrypt_text(payload)
            except crypto.CryptoError:
                return None
        return payload

    def _decode(self, value: str) -> Any | None:
        if crypto.looks_encrypted(value):
            try:
                value = crypto.decrypt_text(value)
            except crypto.CryptoError:
                return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None

    def get(self, key: str) -> Any | None:
        if not self.enabled:
            return None
        row = self._conn.execute(
            "SELECT value, created_at FROM cache WHERE key = ?",
            (self._hash(key),),
        ).fetchone()
        if not row:
            return None
        value, created_at = row
        if self.ttl and (time.time() - created_at) > self.ttl:
            self.delete(key)
            return None
        return self._decode(value)

    def set(self, key: str, value: Any) -> None:
        if not self.enabled:
            return
        payload = self._encode(value)
        if payload is None:
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, created_at) VALUES (?, ?, ?)",
            (self._hash(key), payload, time.time()),
        )
        self._conn.commit()

    def delete(self, key: str) -> None:
        self._conn.execute("DELETE FROM cache WHERE key = ?", (self._hash(key),))
        self._conn.commit()

    def clear(self) -> None:
        self._conn.execute("DELETE FROM cache")
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # pragma: no cover - defensive
            pass


class MemoryResponseCache(BaseCache):
    """An in-memory cache: nothing is written to disk.

    Values live for the lifetime of the process only. Used in ephemeral
    ("leave nothing behind") mode and by tests.
    """

    def __init__(self, ttl_seconds: int = 3600, enabled: bool = True):
        self.enabled = enabled
        self.ttl = ttl_seconds
        self._store: dict[str, tuple[str, float]] = {}

    def get(self, key: str) -> Any | None:
        if not self.enabled:
            return None
        hashed = self._hash(key)
        item = self._store.get(hashed)
        if item is None:
            return None
        payload, created_at = item
        if self.ttl and (time.time() - created_at) > self.ttl:
            self._store.pop(hashed, None)
            return None
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None

    def set(self, key: str, value: Any) -> None:
        if not self.enabled:
            return
        try:
            payload = json.dumps(value, default=str)
        except (TypeError, ValueError):
            return
        self._store[self._hash(key)] = (payload, time.time())

    def delete(self, key: str) -> None:
        self._store.pop(self._hash(key), None)

    def clear(self) -> None:
        self._store.clear()

    def close(self) -> None:
        self._store.clear()


def build_cache(settings: Any) -> BaseCache:
    """Build the cache backend selected by the settings.

    ``privacy.ephemeral`` or ``cache.backend: memory`` force an in-memory
    cache so no response data is written to disk.
    """
    cfg = settings.cache
    ephemeral = bool(getattr(settings.privacy, "ephemeral", False))
    backend = (cfg.backend or "sqlite").lower()
    if backend == "memory" or ephemeral:
        return MemoryResponseCache(ttl_seconds=cfg.ttl_seconds,
                                   enabled=cfg.enabled)
    db_path = settings.cache_path / "responses.db"
    return ResponseCache(db_path, ttl_seconds=cfg.ttl_seconds,
                         enabled=cfg.enabled, encrypt=bool(cfg.encrypt))


__all__ = [
    "BaseCache", "ResponseCache", "MemoryResponseCache", "build_cache",
]
