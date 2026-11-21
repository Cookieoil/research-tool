"""Research engines. Each engine analyses a target and yields Findings."""

from .academic import AcademicEngine
from .base import BaseEngine
from .company import CompanyEngine
from .dark import DarkEngine
from .credential_check import CredentialCheckEngine
from .domain_intel import DomainIntelEngine
from .npi import NpiEngine
from .openalex import OpenAlexEngine
from .orcid import OrcidEngine
from .regional_search import RegionalSearchEngine
from .regional_social import RegionalSocialEngine
from .sanctions import SanctionsEngine
from .search import SearchEngine
from .social import SocialEngine
from .web_scraper import WebScraperEngine
from .whois import WhoisEngine

# Registry used by the CLI / orchestrator.
ENGINE_REGISTRY: dict[str, type[BaseEngine]] = {
    "search": SearchEngine,
    "whois": WhoisEngine,
    "domain_intel": DomainIntelEngine,
    "social": SocialEngine,
    "credential_check": CredentialCheckEngine,
    "academic": AcademicEngine,
    "company": CompanyEngine,
    "web_scraper": WebScraperEngine,
    "openalex": OpenAlexEngine,
    "orcid": OrcidEngine,
    "npi": NpiEngine,
    "dark": DarkEngine,
    "regional_search": RegionalSearchEngine,
    "regional_social": RegionalSocialEngine,
    "sanctions": SanctionsEngine,
}

__all__ = [
    "BaseEngine",
    "SearchEngine",
    "WhoisEngine",
    "DomainIntelEngine",
    "SocialEngine",
    "CredentialCheckEngine",
    "AcademicEngine",
    "CompanyEngine",
    "WebScraperEngine",
    "OpenAlexEngine",
    "OrcidEngine",
    "NpiEngine",
    "DarkEngine",
    "RegionalSearchEngine",
    "RegionalSocialEngine",
    "SanctionsEngine",
    "ENGINE_REGISTRY",
]
