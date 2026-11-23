# Credential Research Toolkit

A full-spectrum, CLI-driven **OSINT & credential-verification research
toolkit** in Python. It gathers and corroborates public information about
people, credentials, organizations, domains and web content, then writes
structured reports (Markdown / PDF / Excel / JSON) with a risk score.

Reports under `data/raw/` capture **what the engines found**. Reviewed,
curated **research papers** live in the `papers/vietnam/` and
`papers/gacha/` shelves, with enforced naming/topic rules, per-paper
metadata and an auto-generated index (see
[`papers/ORGANISATION.md`](papers/ORGANISATION.md)).

> Using an AI agent? See [`AGENT_USAGE.md`](AGENT_USAGE.md) — a one-file
> operating guide (commands, flags, target→engine map, output paths, gotchas).

## Features

| Engine | What it does |
|---|---|
| `search` | Web/news search (DuckDuckGo via `ddgs`; optional SerpAPI/Google) |
| `social` | Username enumeration across 20 public platforms |
| `whois` | Domain registration / registrar data |
| `domain_intel` | DNS records, certificate-transparency subdomains, Shodan |
| `credential_check` | Email syntax, MX deliverability, breach exposure (HIBP) |
| `academic` | Credential corroboration + authoritative verification portals |
| `company` | Business-registry lookup (OpenCorporates) |
| `web_scraper` | Page emails, phones, social & outbound links |
| `openalex` | Academic author profiles: works, citations, h-index, ORCID |
| `orcid` | ORCID researcher-identity registry lookup |
| `npi` | US healthcare provider licensing (NPI Registry) |
| `dark` | Dark-web / `.onion` search & analysis (via Tor) |
| `regional_search` | Regional web search: Baidu, Naver, Yandex, SearXNG |
| `regional_social` | Regional social platforms: VK, Weibo, Zhihu, LINE, … |
| `sanctions` | Sanctions screening: OFAC SDN, UN, EU, UK OFSI |

Plus **analyzers** (risk scoring, link/relationship analysis, optional LLM
summary), an **i18n layer** (script/language detection, romanisation,
translation, query expansion) and **reporters** (Markdown, PDF, Excel, JSON).

A **finalized-paper library** (`publish`, `papers`, `archive-paper`) turns a
reviewed report into a citable paper under `papers/` that is easy to
find by topic, date, target or tag.

An optional **GitHub publishing** layer (`github connect|host`) commits the
reports/papers to a repository and serves them as a browsable site through
GitHub Pages — see [Host reports on GitHub](#host-reports-on-github).

## Install

```powershell
pip install -r requirements.txt
```

Python 3.10+ is required (developed on 3.12).

## Quick start

```powershell
# Single-purpose lookups
python -m research_tool search "Jane Doe"
python -m research_tool social octocat
python -m research_tool whois example.com
python -m research_tool domain example.com
python -m research_tool credential jane@example.com
python -m research_tool academic "Jane Doe" --issuer MIT
python -m research_tool company "Acme Inc"
python -m research_tool scrape https://example.com
python -m research_tool researcher "Jane Doe"        # OpenAlex author profile
python -m research_tool orcid "Jane Doe"             # ORCID registry
python -m research_tool license "John Smith" --state NY   # NPI Registry
python -m research_tool dark "ransomware"                # dark-web search
python -m research_tool dark <onion>.onion               # .onion lookup
python -m research_tool dark "ransomware" --tor          # route via local Tor

# Cross-border / restricted-region research
python -m research_tool regional-search "Kim Jong Un" --region kr
python -m research_tool regional-search "习近平" --region cn
python -m research_tool regional-search "example" --sources yandex,searx
python -m research_tool regional-social someusername     # VK / Weibo / Zhihu / LINE
python -m research_tool sanctions "Some Entity Name"     # OFAC / UN / EU / UK
python -m research_tool sanctions "Name" --source ofac,un --threshold 0.85

# Full multi-engine investigation + report
python -m research_tool full example.com --format markdown
python -m research_tool full "Jane Doe" --engines search,academic --format pdf
python -m research_tool full jane@example.com --format excel

# Finalize a reviewed result into the paper library (papers/)
python -m research_tool publish "Jane Doe" --engines search,academic --format markdown,pdf
python -m research_tool publish --from data/raw/report_example.com.json
python -m research_tool papers                      # browse the catalogue
python -m research_tool papers --query "Jane Doe"   # find a paper
python -m research_tool archive-paper jane-doe_2026-11-21

# Host the reports/papers on GitHub (repository + GitHub Pages)
python -m research_tool github status        # target, token, repo & Pages state
python -m research_tool github connect --push  # create/link the repo + 'origin'
python -m research_tool github host          # build docs/, commit it, enable Pages

# Introspection
python -m research_tool engines
python -m research_tool config
```

`--format` accepts `markdown` (default), `json`, `excel`, or `pdf`.
Reports are written to `data/raw/`; finalized papers are written to
`papers/<topic>/` (see below).

## Reports vs. finalized papers

| Output | Written by | Location | Purpose |
|---|---|---|---|
| **Report** | `<command> --format ...` | `data/raw/` | raw record of what the engines found (transient, purge-eligible) |
| **Paper** | `publish` | `papers/<topic>/` | reviewed, citable write-up with sources and confidence (durable deliverable) |

The paper library's organisation is enforced in code and documented in
[`papers/ORGANISATION.md`](papers/ORGANISATION.md):

- **Topic shelves** — `people/`, `domains/`, `organisations/`, `general/`, or
  a custom `--topic` for a research programme.
- **Naming** — `<target-slug>_<YYYY-MM-DD>[_vN].md|.pdf|.json` plus a
  `<paper-id>.meta.json` catalogue record. Re-publishing the same day adds a
  version instead of overwriting.
- **Index** — `papers/INDEX.md` and `INDEX.json` are rebuilt
  automatically from the records; never hand-edited.
- **Archive** — `archive-paper` moves superseded papers to
  `_archive/<topic>/` and marks them archived.
- **Retention** — `purge` never deletes papers unless `--include-papers` is
  passed explicitly.

```powershell
python -m research_tool publish "Jane Doe" --engines search,academic
python -m research_tool publish "Acme Inc" --format markdown,pdf --tags company
python -m research_tool publish --from data/raw/report_example.com.json
python -m research_tool papers --topic people --query "jane"
python -m research_tool papers --status draft          # review queue
python -m research_tool archive-paper jane-doe_2026-11-21
```

## Host reports on GitHub

Reports and papers can be published to a GitHub repository and served as a
browsable static site through **GitHub Pages**. Nothing is uploaded until you
run an explicit `github` command.

```powershell
python -m research_tool github status          # target, token, repo & Pages state
python -m research_tool github connect --push  # create/link the repo + 'origin'
python -m research_tool github host            # build docs/, commit it, enable Pages
python -m research_tool github host --reports --no-papers --limit 20
python -m research_tool github host --dry-run  # build locally, upload nothing
```

`github host` renders every report/paper into `docs/` (Markdown and JSON get an
HTML page), writes an `index.html` landing page, commits the whole folder in a
**single** commit and enables Pages. The site is served at
`https://<owner>.github.io/<repo>/` (`github status` prints the exact URL).

- **Token** — resolved from `RESEARCH_GITHUB_TOKEN` (or `GITHUB_TOKEN`), else the
  `gh` CLI's stored login (`gh auth token`). It is never written to a report or
  log, and `config` masks it.
- **Config** — the `github:` section of `config.yaml` (`owner`, `repo`,
  `branch`, `site_dir`, `host_reports`, `host_papers`, `pages`, `visibility`).
- **Commit path** — when an `origin` remote exists in this checkout the site is
  pushed with `git`; otherwise it is committed directly through the GitHub API.
- **Safety** — `--ephemeral` cannot host (hosting writes files and uploads
  them), and no engine or `publish` run uploads anything implicitly.

## Configuration

Edit `config.yaml` for defaults. Secrets are best supplied via environment
variables (they override the file):

| Env var | Unlocks |
|---|---|
| `RESEARCH_HIBP_KEY` | HaveIBeenPwned breach lookups |
| `RESEARCH_SHODAN_KEY` | Shodan domain intelligence |
| `RESEARCH_SERPAPI_KEY` | Google search via SerpAPI |
| `RESEARCH_HUNTER_KEY` | Hunter.io email discovery |
| `RESEARCH_CENSYS_ID` / `RESEARCH_CENSYS_SECRET` | Censys host data |
| `RESEARCH_HTTP_PROXY` | Outbound proxy, e.g. `socks5h://127.0.0.1:9050` (Tor) |
| `RESEARCH_LIBRETRANSLATE_URL` | Self-hosted LibreTranslate endpoint for translation |
| `RESEARCH_DEEPL_KEY` | DeepL API key for higher-quality translation |
| `RESEARCH_OPENSANCTIONS_KEY` | OpenSanctions API key (free tier) — 100+ sanctions/PEP lists |
| `OPENAI_API_KEY` | LLM narrative summaries |
| `RESEARCH_GITHUB_TOKEN` | GitHub token for `github host` (else `GITHUB_TOKEN` / `gh auth token`) |
| `RESEARCH_GITHUB_OWNER` / `RESEARCH_GITHUB_REPO` / `RESEARCH_GITHUB_BRANCH` | Override the GitHub hosting target |

Everything degrades gracefully without keys: breach checks fall back to
syntax/MX analysis, search uses DuckDuckGo (via the `ddgs` library, with an
HTML-scraping fallback), and summaries are rule-based.

## Dark web / Tor

The `dark` engine reaches Tor hidden services (`.onion`). It uses a Tor
SOCKS proxy, enabled per-run with `--tor` or globally via
`RESEARCH_HTTP_PROXY`. Tor is **auto-detected** on the common local ports
(`9050` = Tor daemon, `9150` = Tor Browser); SOCKS support needs
`pip install PySocks`. Keyword search queries several onion search engines
(OnionLand, Tor66, Phobos, Haystack, Tordex, Torgle, Multivac, DeepLink),
all configurable under `darkweb.search_endpoints`. Without Tor it still
works in index-only mode and clearly reports what was skipped.

```powershell
python -m research_tool dark "ransomware"
python -m research_tool dark duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion
python -m research_tool dark "ransomware" --tor
python -m research_tool full <onion>.onion --tor --format markdown
```

## Cross-border & restricted-region research

Researching targets in non-anglophone or restricted jurisdictions (the DPRK,
China, Russia, Iran, …) needs three things the toolkit now provides.

**1. Language awareness (`utils/i18n.py`).** Every target is classified by
writing system (Hangul, Han, Cyrillic, Arabic, …) and language. Non-Latin
names are **romanised** (built-in Revised-Romanization/Cyrillic/Greek/Arabic
tables - no dependency), and can be **translated** so the same subject is
searched in its own language. Detection works offline; translation uses a
LibreTranslate endpoint, MyMemory (key-free), or DeepL when configured, and
silently degrades when no backend is reachable.

**2. Regional indices (`regional_search`).** Queries **Baidu** (China),
**Naver** (South Korea), **Yandex** (Russia/CIS) and public **SearXNG**
instances, each in its own language, translating non-Latin result titles back
to English for the report.

```powershell
python -m research_tool regional-search "Kim Jong Un" --region kr
python -m research_tool regional-search "example" --sources yandex
python -m research_tool regional-search "topic" --no-translate   # skip back-translation
```

**3. Restricted-entity screening (`sanctions`).** Downloads, parses and caches
the **OFAC SDN**, **UN**, **EU** and **UK OFSI** lists, then fuzzy-matches a
name (exact / substring / token-set / edit-distance) after transliterating
non-Latin targets. A match is a *lead*, not proof of identity.

```powershell
python -m research_tool sanctions "Kim Jong Un"
python -m research_tool sanctions "Name" --source ofac,un --threshold 0.85
```

The `regional_social` engine additionally probes platforms dominant outside
the anglophone web - **VK**, **Odnoklassniki**, **Dzen**, **Rutube** (RU),
**Weibo**, **Zhihu**, **Bilibili**, **Douyin**, **QZone** (CN), **Naver Blog**,
**Tistory**, **Kakao Story**, **LINE** (KR/JP). These engines are auto-selected
by `full` for name/username/email targets.

### Bypassing blocks, captchas and rate limits

The toolkit escalates automatically before giving up:

| Barrier | Bypass |
|---|---|
| Bot fingerprinting | **User-Agent rotation** across realistic browser UAs (`http.user_agent_rotation`, on by default) |
| JS bot-challenge | **Mobile endpoints** (`m.baidu.com`, `m.search.naver.com`) with a mobile UA, then a **headless-browser render** (`http.render_js: true`; needs Playwright) |
| IP-based captcha (e.g. Baidu `wappass`) | **Exit-IP rotation**: a **proxy pool** (`http.proxy_pool`, or `proxy_pool_auto` to harvest public proxies) is rotated per attempt and blocked proxies are retired; **Tor circuit renewal** (`http.tor_control_port`, needs `stem`) also rotates the exit. A block is detected, never cached, and reported as `status: blocked` |
| Layout / selector changes | **Generic `<a>` fallback** harvests plausible result links when every selector misses |
| Blocked or unparseable source | **SerpAPI fallback** queries the same engine cleanly (`RESEARCH_SERPAPI_KEY`) |
| SearXNG JSON API disabled | **HTML fallback** scrape of the same instance |
| MyMemory rate limits | **Google Translate** (key-free JSON endpoint) is tried before MyMemory |
| Name transliteration variants | **Permutation + phonetic** name matching (optional `jellyfish` for Soundex/Metaphone) |
| OpenSanctions API key | **Bulk-dataset download** (`sanctions.opensanctions_bulk: true`) needs **no key** — verified live: the UN list alone yields 3,538 entities |

For JS rendering, install once:

```powershell
pip install playwright; playwright install chromium
# then set http.render_js: true in config.yaml
```

For exit-IP rotation, either list your own proxies under `http.proxy_pool`, let
it harvest public ones with `http.proxy_pool_auto: true`, or enable Tor circuit
renewal (`pip install stem` + `ControlPort 9051` in `torrc`, then set
`http.tor_control_port: 9051`).

All cross-border features can be tuned in `config.yaml` under `i18n:`,
`sanctions:` and `regional_search:`, and enabled/disabled per-engine under
`engines:`. Routing any of them through Tor (`--tor` / `RESEARCH_HTTP_PROXY`)
also works where a jurisdiction's index is blocked.

## Privacy & data protection

This toolkit handles personal data, so it ships with controls that reduce
exposure. These are data-protection measures (minimise, encrypt, retain,
delete) — they protect data subjects and the researcher, and they keep the
tool auditable.

| Control | Config | What it does |
|---|---|---|
| **PII-minimised logging** | `logging.redact_pii: true` (default) | Emails, phone numbers, secrets and URL query strings are masked before any log record is written |
| **Encryption at rest** | `cache.encrypt`, `reporting.encrypt` | Cached responses and exported reports are encrypted (AES/Fernet via `cryptography`, else a stdlib encrypt-then-MAC fallback) |
| **Ephemeral / memory-only mode** | `privacy.ephemeral` or `--ephemeral` | In-memory cache, no report files, no log file — nothing is written to disk |
| **Retention window** | `privacy.retention_hours` | Age after which tool-owned data becomes eligible for purging |
| **Secure deletion** | `purge` command | Overwrites tool-owned files before unlinking them |
| **Scope guardrail** | `ethics.allowed_domains` | Restricts domain/URL targets to an authorised scope |
| **Attestation** | `ethics.require_attestation` | Requires `--i-have-authorization` before any engine runs |
| **Rate limiting** | `ethics.rate_limit_per_minute` | Throttles engine runs so third-party services are not hammered |
| **Audit trail** | `ethics.audit_log` | Appends a PII-minimised (hashed-target) record of tool actions to `data/audit.log` |

`purge` targets `data/raw/` and **keeps** the paper shelves
(`papers/<topic>/`) intact by default; pass `--include-papers` to include
the paper library in a purge explicitly.

Encryption needs a master key. Generate one and export it (never commit it):

```powershell
# Generate a strong random key, then export the value it prints
python -m research_tool keygen
$env:RESEARCH_ENCRYPTION_KEY = "<the printed key>"
# enable encryption at rest
#   config.yaml -> cache.encrypt: true   and   reporting.encrypt: true

# Run a full investigation that leaves nothing behind on disk
python -m research_tool --ephemeral full "Jane Doe"

# Purge cached data / reports / logs older than the retention window (secure delete)
python -m research_tool purge
python -m research_tool purge --older-than-hours 0 -y   # purge everything now
```

Encrypted reports are written as `data/raw/<name>.<ext>.enc`; decrypt
with the same key:

```powershell
python -m research_tool decrypt "data/raw/report_x.md.enc" --out report.md
```

(The Python equivalent is `research_tool.utils.crypto.decrypt_bytes`.)

Set an authorised scope and require attestation for defensible research:

```yaml
ethics:
  require_attestation: true
  allowed_domains: ["example.com", "acme.org"]
  audit_log: true
  rate_limit_per_minute: 30
```

```powershell
python -m research_tool --i-have-authorization full example.com
```

> **Note on scope.** These controls reduce *retention and exposure of the
> data you collect*. They are not — and this toolkit does not provide —
> anti-forensic capabilities: it does not scrub system/event logs, spoof
> hardware identities, or hide itself from the operating system, because
> that would defeat the accountability that lawful research depends on.

## Project layout

```
research_tool/
├── cli.py              # Typer CLI (entry point)
├── orchestrator.py     # Runs engines, builds a ResearchReport
├── config.py           # Settings (YAML + env overrides)
├── engines/            # One module per research capability
├── analyzers/          # Risk scoring, link analysis, LLM summary
├── reporters/          # Markdown / PDF / Excel / JSON output
├── models/             # Pydantic data models
└── utils/              # Cache, validators, HTTP/proxy helpers
config.yaml             # Defaults
agent.md                # Agent behaviour / instructions
papers/                 # Finalized papers: <topic>/ (md+pdf) + _meta/ + pdfs/
data/raw/               # Raw engine output (transient, purge target)
data/sources/           # Imported source documents / prior drafts
data/cache/             # HTTP response cache (sqlite)
docs/                   # Static site published to GitHub Pages (github host)
```

## Extending

1. Subclass `engines.base.BaseEngine`.
2. Implement `run(self, target, **kwargs) -> list[Finding]`.
3. Register it in `engines/__init__.py::ENGINE_REGISTRY`.
4. Add an enable flag to `config.yaml` and `config.py::EnginesConfig`.

