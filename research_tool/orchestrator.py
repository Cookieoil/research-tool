"""Orchestrator: run one or many engines against a target and build a report."""

from __future__ import annotations

from typing import Any, Iterable

from .analyzers.link_analyzer import LinkAnalyzer
from .analyzers.llm_analyzer import LLMAnalyzer
from .analyzers.risk_scorer import RiskScorer
from .config import Settings, get_settings
from .engines import ENGINE_REGISTRY, BaseEngine
from .logger import logger
from .models.report import ResearchReport
from .utils.cache import build_cache
from .utils.ethics import RateLimiter, audit, check_scope
from .utils.proxy import build_session
from .utils.validators import detect_kind

# Engines that make sense for each detected target kind.
_KIND_ENGINES: dict[str, list[str]] = {
    "email": ["credential_check", "search", "social", "orcid", "dark",
              "sanctions"],
    "domain": ["whois", "domain_intel", "web_scraper", "search", "dark"],
    "url": ["web_scraper", "search"],
    "ip": ["domain_intel", "search"],
    "username": ["social", "regional_social", "search", "web_scraper", "dark"],
    "name": ["search", "academic", "company", "social", "regional_social",
             "regional_search", "sanctions", "openalex", "orcid", "npi", "dark"],
    "onion": ["dark", "search"],
}


class Orchestrator:
    """Coordinates engines and assembles a :class:`ResearchReport`."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.session = build_session(self.settings)
        self.cache = build_cache(self.settings)
        self._rate = RateLimiter(self.settings.ethics.rate_limit_per_minute)

    # ------------------------------------------------------------------
    def _enabled(self, name: str) -> bool:
        return bool(getattr(self.settings.engines, name, True))

    def _make_engine(self, name: str) -> BaseEngine | None:
        cls = ENGINE_REGISTRY.get(name)
        if cls is None:
            logger.warning("Unknown engine '{}'", name)
            return None
        return cls(self.settings, self.session, self.cache)

    def plan(self, target: str, requested: Iterable[str] | None = None) -> list[str]:
        """Decide which engines to run for a target."""
        if requested:
            names = [n for n in requested if n in ENGINE_REGISTRY]
        else:
            kind = detect_kind(target)
            names = _KIND_ENGINES.get(kind, ["search"])
        return [n for n in names if self._enabled(n)]

    # ------------------------------------------------------------------
    def _guard(self, name: str, target: str, report: ResearchReport) -> bool:
        """Enforce scope + rate limits and audit the run.

        Returns True when the run was blocked (a reason is appended to
        ``report.errors``); the caller then returns the report early.
        """
        allowed, reason = check_scope(target, self.settings)
        if not allowed:
            logger.warning("scope check blocked {} run", name)
            report.errors.append(reason)
            audit(self.settings, "scope_blocked", command=name, target=target,
                  reason=reason)
            return True
        if not self._rate.acquire():
            logger.warning("rate limit reached for {} run", name)
            report.errors.append("rate limit reached; try again shortly")
            audit(self.settings, "rate_limited", command=name, target=target)
            return True
        audit(self.settings, "run", command=name, target=target)
        return False

    def run_engine(self, name: str, target: str, **kwargs: Any) -> ResearchReport:
        report = ResearchReport(target=target, target_kind=detect_kind(target))
        if self._guard(name, target, report):
            return report
        engine = self._make_engine(name)
        if engine is None:
            report.errors.append(f"engine '{name}' unavailable")
            return report
        report.engines_run.append(name)
        try:
            report.findings.extend(engine.run(target, **kwargs))
        except Exception as exc:  # noqa: BLE001 - isolate engine failures
            logger.exception("[{}] engine error", name)
            report.errors.append(f"{name}: {exc}")
        report.risk_score = RiskScorer.score(report)
        report.summary = LLMAnalyzer().summarise(report)
        report.metadata["link_analysis"] = LinkAnalyzer.summarise(report)
        return report

    # ------------------------------------------------------------------
    def run_full(self, target: str, engines: Iterable[str] | None = None,
                 **kwargs: Any) -> ResearchReport:
        report = ResearchReport(target=target, target_kind=detect_kind(target))
        if self._guard("full", target, report):
            return report
        names = self.plan(target, engines)
        for name in names:
            engine = self._make_engine(name)
            if engine is None:
                continue
            report.engines_run.append(name)
            try:
                report.findings.extend(engine.run(target, **kwargs))
            except Exception as exc:  # noqa: BLE001
                logger.exception("[{}] engine error", name)
                report.errors.append(f"{name}: {exc}")
        report.risk_score = RiskScorer.score(report)
        report.summary = LLMAnalyzer().summarise(report)
        report.metadata["link_analysis"] = LinkAnalyzer.summarise(report)
        logger.info(
            "[orchestrator] full run complete: {} findings, risk {}/100",
            len(report.findings), report.risk_score,
        )
        return report

    def close(self) -> None:
        self.cache.close()


__all__ = ["Orchestrator"]
