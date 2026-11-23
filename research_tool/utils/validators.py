"""Input validation and normalisation helpers."""

from __future__ import annotations

import ipaddress
import re
import socket
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


# ---------------------------------------------------------------------------
# URL safety / SSRF protection
# ---------------------------------------------------------------------------
# Schemes that may appear in a rendered hyperlink. ``javascript:``, ``data:``,
# ``vbscript:`` and ``file:`` are deliberately excluded: they execute script or
# read local files when a report is opened in a browser.
_SAFE_LINK_SCHEMES = {"http", "https", "mailto"}

# Literal hostnames that always resolve to the local machine.
_LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}


def _literal_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse *host* as an IP address, or return ``None``."""
    candidate = host.strip().strip("[]")
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


def _is_private_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for addresses that must not be fetched by an SSRF-prone client."""
    return bool(
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


def is_private_host(host: str, *, resolve: bool = False) -> bool:
    """Return True when *host* points at a private/loopback/link-local address.

    With ``resolve=True`` a DNS lookup is attempted and every resolved address
    is checked. A resolution failure is treated as "not private" so callers
    keep normal network error handling; the request itself will fail anyway.
    """
    host = (host or "").strip().lower().rstrip(".")
    if not host:
        return True
    if host in _LOCAL_HOSTNAMES or host.endswith(".localhost"):
        return True
    literal = _literal_ip(host)
    if literal is not None:
        return _is_private_ip(literal)
    if not resolve:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        address = info[4][0]
        parsed = _literal_ip(address)
        if parsed is not None and _is_private_ip(parsed):
            return True
    return False


def is_safe_url(url: str, *, allow_private: bool = False,
                resolve: bool = False) -> bool:
    """True when *url* is an http(s) URL that is safe to fetch.

    Rejects non-http(s) schemes and, unless ``allow_private`` is set, hosts
    that resolve to loopback / private / link-local / reserved addresses
    (cloud metadata endpoints such as ``169.254.169.254`` included).
    """
    try:
        parsed = urlparse(str(url).strip())
    except ValueError:
        return False
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return False
    host = parsed.hostname or ""
    if not host:
        return False
    if allow_private:
        return True
    return not is_private_host(host, resolve=resolve)


_DANGEROUS_SCHEMES = (
    "javascript:", "vbscript:", "data:", "file:", "about:", "blob:",
)


def safe_href(href: str, *, allow_relative: bool = True) -> str:
    """Return a hyperlink target that cannot execute script.

    Absolute links are limited to http(s) and mailto; scheme-less relative
    links (``reports/x.html``, ``./x``, ``../x``, ``/x``, ``#anchor``) are
    allowed when ``allow_relative`` is true. Anything else (``javascript:``,
    ``data:``, ``vbscript:``, ``file:``, protocol-relative ``//host``) becomes
    ``#`` so a crafted report cannot run code in the reader's browser.

    Browsers ignore tabs/newlines/control characters while parsing a scheme,
    so ``java\\tscript:alert(1)`` is treated as ``javascript:`` here as well.
    """
    value = str(href or "").strip()
    if not value:
        return "#"
    # Reject control characters anywhere in the string, and check both the
    # raw and the control-stripped forms for dangerous schemes.
    compact = re.sub(r"[\x00-\x20\x7f]", "", value)
    for candidate in (value.lower(), compact.lower()):
        for scheme in _DANGEROUS_SCHEMES:
            if candidate.startswith(scheme):
                return "#"
    # Protocol-relative URLs inherit the page scheme and bypass allowlists.
    if compact.startswith("//"):
        return "#"
    parsed = urlparse(compact)
    scheme = parsed.scheme.lower()
    if scheme:
        return compact if scheme in _SAFE_LINK_SCHEMES else "#"
    # No scheme: a relative path or anchor. Windows drive paths ("C:/x")
    # parse with scheme "c" and are already rejected above.
    return compact if allow_relative else "#"


__all__ = [
    "is_email", "is_domain", "is_url", "is_ip", "is_username",
    "is_onion", "normalise_domain", "normalise_onion", "detect_kind",
    "is_private_host", "is_safe_url", "safe_href",
]
