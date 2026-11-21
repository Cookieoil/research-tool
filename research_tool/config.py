"""Configuration loading for the research toolkit.

Loads ``config.yaml`` from the project root and layers environment
variables on top so that secrets never need to live in the file.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

# Project root = parent of the ``research_tool`` package directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"

# Environment variable -> (config section, key) mapping.
_ENV_OVERRIDES: dict[str, tuple[str, str]] = {
    "RESEARCH_HIBP_KEY": ("api_keys", "hibp"),
    "RESEARCH_SHODAN_KEY": ("api_keys", "shodan"),
    "RESEARCH_SERPAPI_KEY": ("api_keys", "serpapi"),
    "RESEARCH_HUNTER_KEY": ("api_keys", "hunter"),
    "RESEARCH_CENSYS_ID": ("api_keys", "censys_id"),
    "RESEARCH_CENSYS_SECRET": ("api_keys", "censys_secret"),
    "RESEARCH_HTTP_PROXY": ("http", "proxy"),
    "RESEARCH_LOG_LEVEL": ("logging", "level"),
    "RESEARCH_DEEPL_KEY": ("i18n", "deepl_key"),
    "RESEARCH_LIBRETRANSLATE_URL": ("i18n", "libretranslate_url"),
    "RESEARCH_OPENSANCTIONS_KEY": ("sanctions", "opensanctions_key"),
    "RESEARCH_EPHEMERAL": ("privacy", "ephemeral"),
    "RESEARCH_GITHUB_TOKEN": ("github", "token"),
    "RESEARCH_GITHUB_OWNER": ("github", "owner"),
    "RESEARCH_GITHUB_REPO": ("github", "repo"),
    "RESEARCH_GITHUB_BRANCH": ("github", "branch"),
}


class AppConfig(BaseModel):
    name: str = "Credential Research Toolkit"
    version: str = "1.4.0"
    data_dir: str = "data"
    reports_dir: str = "data/reports"
    # Finalized research papers (curated output), separate from raw reports.
    papers_dir: str = "data/papers"
    cache_dir: str = "data/cache"


class HttpConfig(BaseModel):
    timeout: int = 20
    retries: int = 3
    user_agent: str = "Mozilla/5.0 ResearchTool/1.0"
    verify_ssl: bool = True
    proxy: str | None = None
    # Rotate a pool of realistic browser User-Agents (reduces bot-blocking).
    user_agent_rotation: bool = True
    # Opt-in headless-browser rendering for JS-heavy pages (needs Playwright).
    render_js: bool = False
    # A pool of proxy URLs to rotate through per-request. A proxy that gets
    # blocked is retired, so the next attempt uses a fresh exit IP - the
    # practical bypass for IP-based captchas (e.g. Baidu's wappass).
    proxy_pool: list[str] = Field(default_factory=list)
    # Harvest a fresh pool of public proxies from well-known GitHub lists.
    proxy_pool_auto: bool = False
    # Local Tor control port for circuit renewal (SIGNAL NEWNYM), e.g. 9051.
    tor_control_port: int | None = None
    tor_control_password: str | None = None


class CacheConfig(BaseModel):
    enabled: bool = True
    ttl_seconds: int = 3600
    # Backend: "sqlite" (persistent) or "memory" (nothing touches disk).
    backend: str = "sqlite"
    # Encrypt cached values at rest (needs RESEARCH_ENCRYPTION_KEY).
    encrypt: bool = False


class LoggingConfig(BaseModel):
    level: str = "INFO"
    log_file: str | None = "data/research.log"
    rotation: str = "10 MB"
    retention: str = "7 days"
    # Mask emails / phones / secrets / URL queries before a record is emitted.
    redact_pii: bool = True


class ApiKeys(BaseModel):
    hibp: str | None = None
    shodan: str | None = None
    serpapi: str | None = None
    hunter: str | None = None
    censys_id: str | None = None
    censys_secret: str | None = None

    def has(self, name: str) -> bool:
        """Return True when the named key is present and non-empty."""
        return bool(getattr(self, name, None))


class EnginesConfig(BaseModel):
    search: bool = True
    whois: bool = True
    domain_intel: bool = True
    social: bool = True
    credential_check: bool = True
    academic: bool = True
    company: bool = True
    web_scraper: bool = True
    openalex: bool = True
    orcid: bool = True
    npi: bool = True
    dark: bool = True
    # --- cross-border / restricted-region capabilities ---
    regional_search: bool = True
    regional_social: bool = True
    sanctions: bool = True


class I18nConfig(BaseModel):
    """Language / cross-border settings.

    ``target_languages`` are the languages a Latin target is expanded into
    when searching regional indices. ``translation_backend`` is ``auto``,
    ``libretranslate``, ``mymemory``, ``deepl`` or ``none``.
    """

    enabled: bool = True
    target_languages: list[str] = Field(
        default_factory=lambda: ["ko", "zh-CN", "ru", "ar", "fa"]
    )
    translation_backend: str = "auto"
    libretranslate_url: str | None = None
    deepl_key: str | None = None


class SanctionsConfig(BaseModel):
    """Sanctions-screening settings.

    ``opensanctions`` adds the OpenSanctions aggregated API (covers OFAC, UN,
    EU, UK plus 100+ other lists and PEPs - the richest source for DPRK/Russia/
    Iran coverage). ``phonetic`` enables Soundex/Metaphone name matching
    (requires the optional ``jellyfish`` package).
    """

    cache_ttl_hours: int = 24
    sources: dict[str, bool] = Field(default_factory=lambda: {
        "ofac": True, "un": True, "eu": True, "uk": True,
    })
    opensanctions: bool = True
    opensanctions_key: str | None = None   # env: RESEARCH_OPENSANCTIONS_KEY
    # Key-free fallback: download OpenSanctions bulk datasets directly
    # (heavier - tens of MB - but needs no API key). Opt-in.
    opensanctions_bulk: bool = False
    phonetic: bool = True


class RegionalSearchConfig(BaseModel):
    """Regional search-engine settings.

    ``searx_instances`` overrides the built-in SearXNG instance list when
    non-empty; an empty list lets the engine use its own defaults.
    """

    searx_instances: list[str] = Field(default_factory=list)


class ReportingConfig(BaseModel):
    default_format: str = "markdown"
    include_raw_data: bool = True
    # Encrypt report files at rest (writes ``<name>.<ext>.enc``; needs
    # RESEARCH_ENCRYPTION_KEY).
    encrypt: bool = False


class PapersConfig(BaseModel):
    """Finalized-paper library settings.

    ``author`` is credited on every paper; ``default_status`` is applied when
    ``publish`` runs without ``--status`` (``draft`` or ``final``);
    ``formats`` is the default output set; ``include_raw`` appends the
    raw-findings appendix unless overridden per run.
    """

    author: str = "None-Bias Research Agent"
    default_status: str = "final"
    formats: list[str] = Field(default_factory=lambda: ["markdown"])
    include_raw: bool = False


class GitHubConfig(BaseModel):
    """GitHub hosting settings (``github connect`` / ``github host``).

    ``enabled`` is advisory and documents intent. ``owner``/``repo``/``branch``
    select the target; ``token`` is normally supplied through
    ``RESEARCH_GITHUB_TOKEN`` so it never lives in the file. ``site_dir`` is the
    folder GitHub Pages serves; ``host_reports``/``host_papers`` choose what a
    bare ``github host`` publishes; ``pages`` enables or refreshes the Pages
    site; ``visibility`` is used only when the repository is created.
    """

    enabled: bool = False
    owner: str | None = None
    repo: str = "research-tool"
    branch: str = "main"
    token: str | None = None
    remote: str = "origin"
    site_dir: str = "docs"
    host_reports: bool = True
    host_papers: bool = True
    pages: bool = True
    visibility: str = "public"
    description: str = (
        "OSINT & credential-verification research reports "
        "(Credential Research Toolkit)")
    commit_message: str = "Publish research reports to GitHub Pages"


class PrivacyConfig(BaseModel):
    """Privacy / data-protection controls.

    ``ephemeral`` keeps nothing on disk: the cache is in-memory, no report
    files are written and no log file is created. ``retention_hours`` is the
    age after which tool-owned data becomes eligible for purging (see the
    ``purge`` command). ``secure_delete_passes`` is the number of overwrite
    passes applied before a file is unlinked.
    """

    ephemeral: bool = False
    retention_hours: int = 72
    secure_delete_passes: int = 1


class EthicsConfig(BaseModel):
    """Authorization / scope guardrails for legitimate research.

    ``require_attestation`` forces the caller to pass ``--i-have-authorization``
    (or set ``RESEARCH_AUTHORIZED=1``). ``allowed_domains`` restricts
    domain/URL targets to an authorised scope (empty = unrestricted).
    ``audit_log`` writes a PII-minimised record of tool actions to
    ``data/audit.log``. ``rate_limit_per_minute`` throttles engine runs
    (0 = unlimited).
    """

    require_attestation: bool = False
    allowed_domains: list[str] = Field(default_factory=list)
    audit_log: bool = False
    rate_limit_per_minute: int = 0


class DarkWebConfig(BaseModel):
    """Dark-web / Tor settings.

    ``index_url`` is a clearnet-reachable index of known ``.onion`` services;
    ``search_endpoints`` are onion search-engine URL templates (``{query}``
    substituted) queried over Tor. ``tor_proxy`` / ``tor_alt_proxies`` are the
    local SOCKS proxies probed when none is configured (9050 = Tor daemon,
    9150 = Tor Browser).
    """

    index_url: str = "https://ahmia.fi/onions/"
    search_endpoints: list[str] = Field(default_factory=lambda: [
        # OnionLand
        "http://3bbad7fauom4d6sgppalyqddsqbf5u5p56b5k5uk2zxsy3d6ey2jobad.onion/search?q={query}&page=1",
        # Tor66
        "http://tor66sewebgixwhcqfnp5inzp5x5uohhdy3kvtnyfxc2e5mxiuh34iid.onion/search?q={query}&sorttype=rel&page=1",
        # Phobos
        "http://phobosxilamwcg75xt22id7aywkzol6q6rfl2flipcqoc4e4ahima5id.onion/search?query={query}&p=1",
        # Haystack
        "http://haystak5njsmn2hqkewecpaxetahtwhsbsa64jom2k22z5afxhnpxfid.onion/?q={query}&offset=0",
        # Tordex
        "http://tordex7iie7z2wcg.onion/search?query={query}&page=1",
        # Torgle (Submarine)
        "http://no6m4wzdexe3auiupv2zwif7rm6qwxcyhslkcnzisxgeiw6pvjsgafad.onion/search.php?term={query}",
        # Multivac
        "http://multivacigqzqqon.onion/?q={query}&page=1",
        # DeepLink
        "http://deeplinkdeatbml7.onion/?search={query}&type=verified",
    ])
    tor_proxy: str = "socks5h://127.0.0.1:9050"
    tor_alt_proxies: list[str] = Field(
        default_factory=lambda: ["socks5h://127.0.0.1:9150"]
    )


class Settings(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    ethics: EthicsConfig = Field(default_factory=EthicsConfig)
    api_keys: ApiKeys = Field(default_factory=ApiKeys)
    engines: EnginesConfig = Field(default_factory=EnginesConfig)
    reporting: ReportingConfig = Field(default_factory=ReportingConfig)
    papers: PapersConfig = Field(default_factory=PapersConfig)
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    darkweb: DarkWebConfig = Field(default_factory=DarkWebConfig)
    i18n: I18nConfig = Field(default_factory=I18nConfig)
    sanctions: SanctionsConfig = Field(default_factory=SanctionsConfig)
    regional_search: RegionalSearchConfig = Field(
        default_factory=RegionalSearchConfig)

    # ---- convenience path helpers -------------------------------------
    @property
    def root(self) -> Path:
        return PROJECT_ROOT

    def resolve(self, relative: str) -> Path:
        """Resolve a possibly-relative path against the project root."""
        p = Path(relative)
        return p if p.is_absolute() else (PROJECT_ROOT / p)

    @property
    def reports_path(self) -> Path:
        p = self.resolve(self.app.reports_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def papers_path(self) -> Path:
        """Root of the finalized-paper library (``data/papers``)."""
        p = self.resolve(self.app.papers_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def cache_path(self) -> Path:
        p = self.resolve(self.app.cache_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def audit_log_path(self) -> Path:
        """Path of the optional PII-minimised audit log."""
        return self.resolve("data/audit.log")

    @property
    def site_path(self) -> Path:
        """Root of the static site published to GitHub Pages.

        Created on demand by ``github host``; reading it has no side effects.
        """
        return self.resolve(self.github.site_dir)


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    for env_name, (section, key) in _ENV_OVERRIDES.items():
        value = os.environ.get(env_name)
        if value:
            data.setdefault(section, {})
            data[section][key] = value
    return data


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Load settings from YAML + environment overrides."""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    data: dict[str, Any] = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    data = _apply_env_overrides(data)
    return Settings(**data)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance for the default config path."""
    return load_settings()


__all__ = ["Settings", "get_settings", "load_settings", "PROJECT_ROOT"]
