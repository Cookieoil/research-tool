"""Centralised logging setup built on loguru."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from loguru import logger

_CONFIGURED = False


# ---------------------------------------------------------------------------
# PII redaction
# ---------------------------------------------------------------------------
# Logs are a common, avoidable source of leaked personal data. When
# ``logging.redact_pii`` is on (the default) emails, phone numbers, secrets
# and URL query strings are masked before a record is emitted.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})")
_PHONE_RE = re.compile(r"(?<![\w.])\+?\d[\d\s().\-]{5,}\d(?![\w.])")
# key=value / key: value pairs (covers api_key, hibp-api-key, deepl-auth-key...)
_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|apikey|access[_-]?key|token|authorization|"
    r"password|passwd|secret|hibp-api-key|deepl-auth-key|"
    r"opensanctions[_-]?key|session[_-]?secret)\b\s*[:=]\s*"
    r"(?:(bearer|basic|apikey|token)\s+)?\S+"
)
# Space-delimited auth headers: "Bearer <token>", "ApiKey <key>", ...
_AUTH_HEADER_RE = re.compile(
    r"(?i)\b(bearer|apikey|api-key|deepL-auth-key|token)\s+"
    r"[A-Za-z0-9._~+/=\-]{8,}"
)
# Standalone token prefixes used by GitHub, OpenAI, Slack, etc.
_TOKEN_PREFIX_RE = re.compile(
    r"\b(?:ghp_|gho_|ghu_|ghs_|ghr_|github_pat_|sk-|xox[baprs]-)"
    r"[A-Za-z0-9_\-]{8,}"
)
# Credentials embedded in proxy URLs: scheme://user:pass@host
_PROXY_CRED_RE = re.compile(
    r"(?i)\b(https?|socks5h?)://[^/\s:@]+:[^@\s/]+@"
)
_URL_QUERY_RE = re.compile(r"(https?://[^\s?'\"]+)\?[^\s'\"]*")


def _phone_sub(match: "re.Match[str]") -> str:
    # Require >= 10 digits so dates (e.g. 2024-01-01) and counts survive.
    digits = sum(c.isdigit() for c in match.group(0))
    return "[phone]" if digits >= 10 else match.group(0)


def _secret_sub(match: "re.Match[str]") -> str:
    """Keep the key/scheme readable while masking the secret value."""
    key, scheme = match.group(1), match.group(2)
    if scheme:
        return f"{key}: {scheme} [redacted]"
    return f"{key}=[redacted]"


def redact(message: str) -> str:
    """Mask common PII / secrets in a log *message*."""
    text = _EMAIL_RE.sub(lambda m: "***@" + m.group(1), message)
    text = _PHONE_RE.sub(_phone_sub, text)
    # Auth headers first so "Authorization: Bearer <token>" is masked whole.
    text = _AUTH_HEADER_RE.sub(lambda m: f"{m.group(1)} [redacted]", text)
    text = _SECRET_RE.sub(_secret_sub, text)
    text = _TOKEN_PREFIX_RE.sub("[redacted-token]", text)
    text = _PROXY_CRED_RE.sub(lambda m: f"{m.group(1)}://[redacted]@", text)
    text = _URL_QUERY_RE.sub(lambda m: m.group(1) + "?[redacted]", text)
    return text


class _PiiFilter:
    """A loguru filter that redacts ``record["message"]`` in place."""

    def __init__(self, active: bool = True):
        self.active = active

    def __call__(self, record: dict) -> bool:
        if self.active:
            record["message"] = redact(record["message"])
        return True


def setup_logger(level: str = "INFO", log_file: str | None = None,
                 rotation: str = "10 MB", retention: str = "7 days",
                 redact_pii: bool = True) -> "logger.__class__":
    """Configure the global loguru logger once.

    Parameters
    ----------
    level:      minimum log level (DEBUG/INFO/WARNING/ERROR)
    log_file:   optional path to a rotating log file
    rotation:   loguru rotation policy
    retention:  loguru retention policy
    redact_pii: mask emails/phones/secrets/URL queries before emitting
    """
    global _CONFIGURED
    if _CONFIGURED:
        return logger

    logger.remove()

    # Colourful console sink.
    logger.add(
        sys.stderr,
        level=level.upper(),
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
            "<level>{message}</level>"
        ),
        colorize=True,
        backtrace=True,
        diagnose=False,
        filter=_PiiFilter(redact_pii),
    )

    # Optional rotating file sink.
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            str(path),
            level=level.upper(),
            rotation=rotation,
            retention=retention,
            encoding="utf-8",
            enqueue=True,
            backtrace=True,
            diagnose=False,
            filter=_PiiFilter(redact_pii),
        )

    _CONFIGURED = True
    return logger


__all__ = ["logger", "setup_logger", "redact"]
