"""Authenticated encryption-at-rest helpers.

Small, dependency-light envelope used to protect the sensitive data this
toolkit keeps on disk (cached API responses, exported reports) so a stolen
laptop or a leaked backup is not also a data breach.

Two backends are auto-selected:

* :mod:`cryptography` (Fernet: AES-128-CBC + HMAC-SHA256, encrypt-then-MAC)
  when the optional package is installed -- the recommended path;
* a pure standard-library fallback (HMAC-SHA256 keystream in counter mode
  with an encrypt-then-MAC tag) so encryption still works on a bare install.

The master secret is read from the ``RESEARCH_ENCRYPTION_KEY`` environment
variable. When it is absent, :func:`is_configured` returns ``False`` and
callers surface a clear error instead of silently storing plaintext.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

_ENV_KEY = "RESEARCH_ENCRYPTION_KEY"

_MAGIC_STD = b"RTP1"       # stdlib HMAC-CTR keystream + HMAC tag
_MAGIC_FERNET = b"RTP2"    # cryptography.Fernet token
_MAGIC_LEN = 4
_SALT_LEN = 16
_NONCE_LEN = 16
_KEY_LEN = 32
_MAC_LEN = 32
_PBKDF2_ROUNDS = 600_000


class CryptoError(RuntimeError):
    """Raised when encryption is requested but cannot be performed."""


# ----------------------------------------------------------------------
# Configuration / capability detection
# ----------------------------------------------------------------------
def is_configured() -> bool:
    """True when a master key is present in the environment."""
    return bool(os.environ.get(_ENV_KEY))


def backend() -> str:
    """Name of the backend that will be used (``fernet`` or ``stdlib``)."""
    return "fernet" if _fernet_available() else "stdlib"


def _fernet_available() -> bool:
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return False
    return True


def _master_secret() -> bytes:
    secret = os.environ.get(_ENV_KEY)
    if not secret:
        raise CryptoError(
            "Encryption is enabled but no master key is set. Export "
            "RESEARCH_ENCRYPTION_KEY (a long random passphrase) first."
        )
    return secret.encode("utf-8")


def _derive(secret: bytes, salt: bytes, length: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", secret, salt, _PBKDF2_ROUNDS,
                               dklen=length)


# ----------------------------------------------------------------------
# Pure-standard-library backend
# ----------------------------------------------------------------------
def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    """HMAC-SHA256 in counter mode, used as a PRF stream."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(key, nonce + counter.to_bytes(8, "big"),
                         hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def _encrypt_std(data: bytes, secret: bytes) -> bytes:
    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    dk = _derive(secret, salt, _KEY_LEN * 2)
    enc_key, mac_key = dk[:_KEY_LEN], dk[_KEY_LEN:]
    stream = _keystream(enc_key, nonce, len(data))
    ciphertext = bytes(a ^ b for a, b in zip(data, stream))
    tag = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
    return _MAGIC_STD + salt + nonce + tag + ciphertext


def _decrypt_std(blob: bytes, secret: bytes) -> bytes:
    body = blob[_MAGIC_LEN:]
    if len(body) < _SALT_LEN + _NONCE_LEN + _MAC_LEN:
        raise CryptoError("Encrypted payload is truncated.")
    salt = body[:_SALT_LEN]
    nonce = body[_SALT_LEN:_SALT_LEN + _NONCE_LEN]
    tag = body[_SALT_LEN + _NONCE_LEN:_SALT_LEN + _NONCE_LEN + _MAC_LEN]
    ciphertext = body[_SALT_LEN + _NONCE_LEN + _MAC_LEN:]
    dk = _derive(secret, salt, _KEY_LEN * 2)
    enc_key, mac_key = dk[:_KEY_LEN], dk[_KEY_LEN:]
    expected = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, tag):
        raise CryptoError("Authentication failed (wrong key or tampered data).")
    stream = _keystream(enc_key, nonce, len(ciphertext))
    return bytes(a ^ b for a, b in zip(ciphertext, stream))


# ----------------------------------------------------------------------
# Fernet backend
# ----------------------------------------------------------------------
def _fernet(secret: bytes, salt: bytes):
    from cryptography.fernet import Fernet  # type: ignore[import-not-found]

    key = base64.urlsafe_b64encode(_derive(secret, salt, _KEY_LEN))
    return Fernet(key)


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------
def encrypt_bytes(data: bytes, *, secret: bytes | None = None) -> bytes:
    """Encrypt *data*, returning a self-describing envelope."""
    secret = secret or _master_secret()
    if _fernet_available():
        salt = os.urandom(_SALT_LEN)
        token = _fernet(secret, salt).encrypt(data)
        return _MAGIC_FERNET + salt + token
    return _encrypt_std(data, secret)


def decrypt_bytes(blob: bytes, *, secret: bytes | None = None) -> bytes:
    """Reverse :func:`encrypt_bytes`; raises :class:`CryptoError` on failure."""
    secret = secret or _master_secret()
    if blob.startswith(_MAGIC_STD):
        return _decrypt_std(blob, secret)
    if blob.startswith(_MAGIC_FERNET):
        if not _fernet_available():
            raise CryptoError(
                "This payload was encrypted with 'cryptography'; install it "
                "(pip install cryptography) to decrypt."
            )
        salt = blob[_MAGIC_LEN:_MAGIC_LEN + _SALT_LEN]
        token = blob[_MAGIC_LEN + _SALT_LEN:]
        try:
            return _fernet(secret, salt).decrypt(token)
        except Exception as exc:  # noqa: BLE001 - cryptography raises its own
            raise CryptoError(
                "Authentication failed (wrong key or tampered data)."
            ) from exc
    raise CryptoError("Unrecognised encrypted payload.")


def encrypt_text(text: str, *, secret: bytes | None = None) -> str:
    """Encrypt *text* to an ASCII (base64) token safe for text columns."""
    return base64.b64encode(encrypt_bytes(text.encode("utf-8"),
                                          secret=secret)).decode("ascii")


def decrypt_text(token: str, *, secret: bytes | None = None) -> str:
    """Reverse :func:`encrypt_text`."""
    try:
        raw = base64.b64decode(token, validate=True)
    except (ValueError, TypeError) as exc:
        raise CryptoError("Payload is not valid base64.") from exc
    return decrypt_bytes(raw, secret=secret).decode("utf-8")


def looks_encrypted(token: str) -> bool:
    """Heuristic: is *token* one of our base64-encoded envelopes?"""
    try:
        raw = base64.b64decode(token, validate=True)
    except (ValueError, TypeError):
        return False
    return raw.startswith(_MAGIC_STD) or raw.startswith(_MAGIC_FERNET)


__all__ = [
    "CryptoError",
    "backend",
    "is_configured",
    "encrypt_bytes",
    "decrypt_bytes",
    "encrypt_text",
    "decrypt_text",
    "looks_encrypted",
]
