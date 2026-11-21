"""Authorization, scope and rate-limit guardrails for legitimate research.

These are the *opposite* of anti-forensics: they make the tool defensible by
ensuring the caller has attested to authorisation, that domain/URL targets
stay inside an authorised scope, that third-party services are not hammered,
and -- optionally -- that a PII-minimised audit trail of tool actions exists.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RateLimiter:
    """A simple per-minute token bucket (a no-op when ``per_minute <= 0``)."""

    def __init__(self, per_minute: int):
        self.per_minute = max(0, int(per_minute or 0))
        self._times: list[float] = []
        self._lock = threading.Lock()

    def acquire(self, *, block: bool = True, timeout: float = 30.0) -> bool:
        """Take one slot; returns False when it cannot be obtained in time."""
        if self.per_minute <= 0:
            return True
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                self._times = [t for t in self._times if now - t < 60.0]
                if len(self._times) < self.per_minute:
                    self._times.append(now)
                    return True
                wait = 60.0 - (now - self._times[0])
            if not block or time.monotonic() >= deadline:
                return False
            time.sleep(max(0.05, min(wait, 1.0)))


def target_fingerprint(target: str, *, salt: str = "research") -> str:
    """A short, salted, non-reversible identifier for a target string."""
    return hashlib.sha256(f"{salt}:{target}".encode("utf-8")).hexdigest()[:16]


def check_scope(target: str, settings: Any) -> tuple[bool, str]:
    """Return ``(allowed, reason)`` against ``ethics.allowed_domains``.

    An empty ``allowed_domains`` list means "no scope restriction". Only
    domain / URL targets are scope-checked; names, emails and usernames are
    not (they cannot be mapped to an authorisation boundary).
    """
    allow = [d.lower().strip().lstrip(".") for d in
             (getattr(settings.ethics, "allowed_domains", None) or []) if d]
    if not allow:
        return True, ""

    from .validators import detect_kind, normalise_domain

    kind = detect_kind(target)
    if kind in ("domain", "url"):
        host = normalise_domain(target)
        if any(host == d or host.endswith("." + d) for d in allow):
            return True, ""
        return False, (
            f"target '{host}' is outside the authorised scope "
            f"({', '.join(allow)})"
        )
    return True, ""


class AuditLog:
    """Append-only, PII-minimised record of what the tool did."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def record(self, event: str, *, command: str | None = None,
               target: str | None = None, **fields: Any) -> None:
        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "command": command,
            "target_hash": target_fingerprint(target) if target else None,
        }
        entry.update(fields)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")


def audit(settings: Any, event: str, **fields: Any) -> None:
    """Record *event* when ``ethics.audit_log`` is on (otherwise a no-op)."""
    if not getattr(settings.ethics, "audit_log", False):
        return
    AuditLog(settings.audit_log_path).record(event, **fields)


__all__ = [
    "RateLimiter", "target_fingerprint", "check_scope", "AuditLog", "audit",
]
