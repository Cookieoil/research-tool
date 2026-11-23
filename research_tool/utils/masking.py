"""Secret masking helpers shared by the CLI and the admin server.

Keeping this module dependency-free (standard library only) means
``python -m research_tool config`` never needs the web-server extras, while the
server can reuse exactly the same redaction rules.
"""

from __future__ import annotations

import re
from typing import Any

# Field names whose values are secrets, wherever they appear in the config.
SECRET_FIELDS = {
    "token", "password", "passwd", "secret", "api_key", "apikey",
    "hibp", "shodan", "serpapi", "hunter", "censys_id", "censys_secret",
    "deepl_key", "opensanctions_key", "tor_control_password",
    "admin_password", "admin_password_hash", "session_secret",
    "proxy", "proxy_pool", "encryption_key",
}

MASK = "***set***"

# Credentials embedded in a URL: scheme://user:pass@host
_URL_CRED_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s:@]+:[^@\s/]+@")


def is_secret_field(name: str) -> bool:
    """True when *name* looks like a secret-bearing configuration key."""
    lowered = (name or "").lower()
    return (
        lowered in SECRET_FIELDS
        or lowered.endswith("_key")
        or lowered.endswith("_secret")
        or lowered.endswith("_password")
        or lowered.endswith("_token")
        or lowered.endswith("_passphrase")
    )


def mask_url_credentials(value: str) -> str:
    """Replace ``user:pass@`` in a URL with ``[redacted]@``."""
    return _URL_CRED_RE.sub(lambda m: f"{m.group(1)}[redacted]@", str(value))


def mask_config(value: Any, key: str = "") -> Any:
    """Return a deep copy of *value* with secrets replaced by ``***set***``.

    Values that are falsy (``None``, ``""``, empty lists) are left untouched so
    the output still shows "not configured" honestly. URLs with embedded
    credentials are scrubbed even when the field name is not secret.
    """
    if isinstance(value, dict):
        masked: dict[str, Any] = {}
        for k, v in value.items():
            if is_secret_field(k) and v:
                masked[k] = MASK
            else:
                masked[k] = mask_config(v, k)
        return masked
    if isinstance(value, list):
        return [mask_config(item, key) for item in value]
    if isinstance(value, str):
        return mask_url_credentials(value)
    return value


__all__ = [
    "SECRET_FIELDS", "MASK", "is_secret_field", "mask_url_credentials",
    "mask_config",
]
