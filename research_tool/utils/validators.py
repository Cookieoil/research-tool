"""Input validation and normalisation helpers."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
    r"(?:\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$"
)
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
# Tor hidden-service address: base32 v2 (16 char) or v3 (56 char) + .onion
_ONION_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?"
    r"(?P<host>(?:[a-z2-7]{16}|[a-z2-7]{56})\.onion)"
    r"(?::\d+)?(?:[/?#].*)?$",
    re.IGNORECASE,
)


def is_email(value: str) -> bool:
    return bool(value) and bool(_EMAIL_RE.match(value.strip()))


def is_domain(value: str) -> bool:
    return bool(value) and bool(_DOMAIN_RE.match(value.strip().lower()))


def is_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value.strip())
        return True
    except ValueError:
        return False


def is_username(value: str) -> bool:
    return bool(value) and bool(_USERNAME_RE.match(value.strip()))


def is_onion(value: str) -> bool:
    """True for a Tor hidden-service address (bare or as an http(s) URL)."""
    return bool(value) and bool(_ONION_RE.match(value.strip()))


def normalise_onion(value: str) -> str:
    """Return the bare ``*.onion`` host, stripping scheme/path/port."""
    match = _ONION_RE.match(value.strip())
    return match.group("host").lower() if match else value.strip().lower()


def normalise_domain(value: str) -> str:
    """Strip scheme/path/www and lower-case a domain or URL."""
    value = value.strip().lower()
    if "://" in value:
        value = urlparse(value).netloc
    value = value.split("/")[0].split(":")[0]
    if value.startswith("www."):
        value = value[4:]
    return value


def detect_kind(value: str) -> str:
    """Best-effort classification of a free-form research target."""
    value = value.strip()
    if is_onion(value):
        return "onion"
    if is_email(value):
        return "email"
    if is_url(value):
        return "url"
    if is_ip(value):
        return "ip"
    if is_domain(value):
        return "domain"
    if is_username(value):
        return "username"
    return "name"


__all__ = [
    "is_email", "is_domain", "is_url", "is_ip", "is_username",
    "is_onion", "normalise_domain", "normalise_onion", "detect_kind",
]
