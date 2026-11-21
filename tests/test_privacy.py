"""Tests for the privacy-hardening features.

Covers log redaction, encryption at rest (cache + reports), the in-memory
cache backend, secure deletion / retention purging and the ethics
guardrails. No network access is required.

Run with ``python tests/test_privacy.py`` (or pytest).
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research_tool.config import Settings, load_settings
from research_tool.logger import redact
from research_tool.models.report import Finding, ResearchReport
from research_tool.orchestrator import Orchestrator
from research_tool.reporters import write_report
from research_tool.utils import crypto
from research_tool.utils.cache import (MemoryResponseCache, ResponseCache,
                                       build_cache)
from research_tool.utils.ethics import RateLimiter, audit, check_scope
from research_tool.utils.retention import purge_directory, secure_delete

_KEY = "unit-test-master-key-please-change"


def _use_key() -> None:
    os.environ["RESEARCH_ENCRYPTION_KEY"] = _KEY


# ----------------------------------------------------------------------
# Log redaction
# ----------------------------------------------------------------------
def test_redact_masks_pii() -> None:
    msg = ("lookup jane.doe@example.com via https://x.test/s?q=Jane+Doe "
           "phone +1 (555) 123-4567 token=abcdef123456")
    out = redact(msg)
    assert "jane.doe@example.com" not in out
    assert "***@example.com" in out
    assert "token=[redacted]" in out
    assert "?[redacted]" in out
    assert "+1 (555) 123-4567" not in out  # >= 10 digits -> masked


def test_redact_keeps_dates_and_counts() -> None:
    assert redact("generated 2024-01-01 with 42 findings") == \
        "generated 2024-01-01 with 42 findings"


# ----------------------------------------------------------------------
# Encryption at rest
# ----------------------------------------------------------------------
def test_crypto_requires_key() -> None:
    saved = os.environ.pop("RESEARCH_ENCRYPTION_KEY", None)
    try:
        assert crypto.is_configured() is False
        try:
            crypto.encrypt_text("secret")
            raised = False
        except crypto.CryptoError:
            raised = True
        assert raised
    finally:
        if saved is not None:
            os.environ["RESEARCH_ENCRYPTION_KEY"] = saved


def test_crypto_roundtrip_and_tamper() -> None:
    _use_key()
    token = crypto.encrypt_text("hello \u00e9 world")
    assert crypto.looks_encrypted(token)
    assert crypto.decrypt_text(token) == "hello \u00e9 world"

    # Tampering / wrong key must fail, never return garbage.
    bad = bytearray(crypto.encrypt_bytes(b"payload"))
    bad[-1] ^= 0x01
    try:
        crypto.decrypt_bytes(bytes(bad))
        raised = False
    except crypto.CryptoError:
        raised = True
    assert raised


# ----------------------------------------------------------------------
# Cache backends
# ----------------------------------------------------------------------
def test_memory_cache() -> None:
    cache = MemoryResponseCache(ttl_seconds=60)
    cache.set("k", {"a": 1})
    assert cache.get("k") == {"a": 1}
    cache.delete("k")
    assert cache.get("k") is None
    cache.set("exp", 1)
    cache.ttl = 0  # never expires
    assert cache.get("exp") == 1
    cache.close()
    assert cache.get("exp") is None


def test_cache_encrypted_at_rest() -> None:
    _use_key()
    with tempfile.TemporaryDirectory() as tmp:
        cache = ResponseCache(Path(tmp) / "c.db", ttl_seconds=60,
                              encrypt=True)
        cache.set("k", {"email": "jane.doe@example.com"})
        raw = cache._conn.execute("SELECT value FROM cache").fetchone()[0]
        assert "jane.doe@example.com" not in raw
        assert crypto.looks_encrypted(raw)
        assert cache.get("k") == {"email": "jane.doe@example.com"}
        cache.close()


def test_build_cache_selects_backend() -> None:
    settings = Settings()
    settings.cache.backend = "memory"
    assert isinstance(build_cache(settings), MemoryResponseCache)
    settings.cache.backend = "sqlite"
    settings.privacy.ephemeral = True
    assert isinstance(build_cache(settings), MemoryResponseCache)


# ----------------------------------------------------------------------
# Secure deletion / retention
# ----------------------------------------------------------------------
def test_secure_delete_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "secret.txt"
        f.write_text("sensitive", encoding="utf-8")
        assert secure_delete(f) is True
        assert not f.exists()


def test_purge_directory_by_age() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        old = Path(tmp) / "old.txt"
        new = Path(tmp) / "new.txt"
        old.write_text("old", encoding="utf-8")
        new.write_text("new", encoding="utf-8")
        past = time.time() - 10 * 3600
        os.utime(old, (past, past))
        removed = purge_directory(tmp, max_age_hours=1)
        assert removed == 1
        assert not old.exists()
        assert new.exists()


# ----------------------------------------------------------------------
# Ethics guardrails
# ----------------------------------------------------------------------
def test_rate_limiter() -> None:
    limiter = RateLimiter(2)
    assert limiter.acquire() is True
    assert limiter.acquire() is True
    assert limiter.acquire(block=False) is False
    assert RateLimiter(0).acquire() is True


def test_check_scope() -> None:
    settings = Settings()
    assert check_scope("anything", settings) == (True, "")
    settings.ethics.allowed_domains = ["example.com"]
    assert check_scope("example.com", settings)[0] is True
    assert check_scope("https://sub.example.com/x", settings)[0] is True
    assert check_scope("evil.org", settings)[0] is False
    assert check_scope("Jane Doe", settings)[0] is True  # names exempt


def test_orchestrator_scope_block() -> None:
    settings = Settings()
    settings.cache.backend = "memory"
    settings.ethics.allowed_domains = ["example.com"]
    orch = Orchestrator(settings)
    report = orch.run_engine("whois", "evil.org")
    assert report.engines_run == []
    assert report.errors and "authorised scope" in report.errors[0]
    orch.close()


def test_audit_log_is_pii_minimised() -> None:
    from research_tool.utils.ethics import AuditLog

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.log"
        AuditLog(path).record("run", command="whois",
                              target="jane@example.com")
        line = path.read_text(encoding="utf-8")
        assert "jane@example.com" not in line
        assert '"command": "whois"' in line
    # Disabled audit log writes nothing (no error either).
    audit(Settings(), "run", command="whois", target="jane@example.com")


# ----------------------------------------------------------------------
# Encrypted reports
# ----------------------------------------------------------------------
def test_write_report_encrypted() -> None:
    _use_key()
    report = ResearchReport(target="example.com", target_kind="domain",
                            engines_run=["whois"])
    report.findings = [Finding(engine="whois", category="domain",
                               title="Registrar", confidence=0.9)]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        path = write_report(report, "markdown", out, stem="t", encrypt=True)
        assert path.suffix == ".enc" and path.exists()
        assert not (out / "t.md").exists()
        plain = crypto.decrypt_bytes(path.read_bytes()).decode("utf-8")
        assert "# Research Report: example.com" in plain


# ----------------------------------------------------------------------
# Config plumbing
# ----------------------------------------------------------------------
def test_ephemeral_env_override() -> None:
    saved = os.environ.get("RESEARCH_EPHEMERAL")
    os.environ["RESEARCH_EPHEMERAL"] = "1"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            settings = load_settings(Path(tmp) / "missing.yaml")
            assert settings.privacy.ephemeral is True
            assert settings.cache.backend == "sqlite"
    finally:
        if saved is None:
            os.environ.pop("RESEARCH_EPHEMERAL", None)
        else:
            os.environ["RESEARCH_EPHEMERAL"] = saved


def test_cli_decrypt_roundtrip() -> None:
    _use_key()
    from typer.testing import CliRunner

    from research_tool.cli import app

    report = ResearchReport(target="example.com", engines_run=["whois"])
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        enc = write_report(report, "markdown", out, stem="t", encrypt=True)
        dest = out / "out.md"
        result = CliRunner().invoke(
            app, ["decrypt", str(enc), "--out", str(dest)])
        assert result.exit_code == 0, result.output
        assert "# Research Report: example.com" in \
            dest.read_text(encoding="utf-8")


def test_cli_keygen() -> None:
    import base64 as _b64

    from typer.testing import CliRunner

    from research_tool.cli import app

    result = CliRunner().invoke(app, ["keygen", "--quiet", "--bytes", "48"])
    assert result.exit_code == 0, result.output
    assert len(_b64.urlsafe_b64decode(result.output.strip())) == 48


def test_cli_purge_command() -> None:
    from typer.testing import CliRunner

    from research_tool.cli import app

    result = CliRunner().invoke(
        app, ["purge", "-y", "--older-than-hours", "999999"])
    assert result.exit_code == 0, result.output
    assert "Purge summary" in result.output


def test_cli_attestation_gate() -> None:
    import research_tool.cli as cli_mod
    from typer.testing import CliRunner

    settings = Settings()
    settings.ethics.require_attestation = True
    original = cli_mod.get_settings
    cli_mod.get_settings = lambda: settings          # type: ignore[assignment]
    saved = os.environ.pop("RESEARCH_AUTHORIZED", None)
    try:
        result = CliRunner().invoke(cli_mod.app, ["whois", "example.com"])
        assert result.exit_code == 2, result.output
        assert "attestation" in result.output.lower()
    finally:
        cli_mod.get_settings = original              # type: ignore[assignment]
        if saved is not None:
            os.environ["RESEARCH_AUTHORIZED"] = saved


def _run_all() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
