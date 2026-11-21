# Credential Research Toolkit — Agent Operating Guide

> **Read this first.** A single self-contained manual for *using* the toolkit.
> You can complete any research task from here without reading the source.

## 0. TL;DR
- Run everything from the repo root: `python -m research_tool <command> <target> [options]`
- Pick a command (§2), then add `--format markdown|json|pdf|excel` to save a report under `data/reports/`.
- **Reports (`data/reports/`) are raw findings. Finalized papers go to `data/papers/`** via `publish`; the layout/naming rules are enforced and documented in `data/papers/ORGANISATION.md` (§4.1).
- Findings print as a table on stdout; each has `engine, category, title, detail, url, confidence(0-1), data{...}`.
- A 0-100 risk score and a text summary are produced automatically.
- Unsure which engines apply? Use `full "<target>"` — it auto-selects by target kind (§3).

## 1. Environment
- Python 3.10+ (developed on 3.12). Install deps once: `pip install -r requirements.txt`.
- Windows consoles (cp1252) are handled automatically — the CLI forces UTF-8 stdio; no `PYTHONIOENCODING` needed.
- Config lives in `config.yaml` (repo root); environment variables override it.
- Inspect: `python -m research_tool config` (effective config, secrets masked) and `python -m research_tool engines` (engine list + enabled state).

## 2. Command cheat-sheet
All commands take the form `python -m research_tool <cmd> TARGET [options]`.
Global options must come **before** the command (§5). Every engine command also accepts `--format/-f markdown|json|pdf|excel` and `--verbose/-v`. `publish` is the exception: it writes curated papers to the library (§4.1), not raw reports.

| Command | TARGET | Key options | Example |
|---|---|---|---|
| `search` | query / name | `--limit N` | `search "Jane Doe"` |
| `social` | username (handle) | — | `social octocat` |
| `whois` | domain | — | `whois example.com` |
| `domain` | domain | — | `domain example.com` |
| `credential` | email | — | `credential jane@example.com` |
| `academic` | name | `--issuer`, `--kind academic\|certification\|license` | `academic "Jane Doe" --issuer MIT` |
| `company` | entity name | — | `company "Acme Inc"` |
| `scrape` | url | — | `scrape https://example.com` |
| `full` | any | `--engines a,b`, `--tor` | `full example.com --engines whois,domain_intel` |
| `publish` | target, or `--from <report.json>` | `--format markdown,pdf,json`, `--topic`, `--title`, `--author`, `--tags`, `--abstract`, `--status draft\|final`, `--include-raw`, `--engines a,b` | `publish "Jane Doe" --engines search,academic --tags osint` |
| `papers` | — | `--topic`, `--query/-q`, `--status`, `--archived`, `--rebuild-index`, `--limit` | `papers --query "jane"` |
| `archive-paper` | paper ID | `--yes/-y` | `archive-paper jane-doe_2026-11-21` |
| `dark` | keyword / .onion | `--limit N`, `--tor` | `dark "ransomware" --tor` |
| `regional-search` | query / name | `--region/-r cn\|kr\|ru\|global`, `--sources baidu,naver,yandex,searx`, `--limit`, `--translate/--no-translate` | `regional-search "김정은" --region kr` |
| `regional-social` | username (handle) | — | `regional-social someone` |
| `sanctions` | person / org | `--source/-s ofac,un,eu,uk,opensanctions`, `--threshold 0.8`, `--limit` | `sanctions "Name" -s ofac,un --threshold 0.85` |
| `researcher` | name | `--limit` | `researcher "Yoshua Bengio"` (OpenAlex) |
| `orcid` | name | `--limit` | `orcid "Yoshua Bengio"` |
| `license` | provider name | `--state NY`, `--limit` | `license "John Smith" --state NY` (US NPI) |
| `engines` / `config` | — | — | `engines`, `config` |
| `purge` | — | `--older-than-hours H`, `--yes/-y` | `purge --older-than-hours 0 -y` |
| `keygen` | — | `--bytes 48`, `--quiet/-q` | `keygen` |
| `decrypt` | path.enc | `--out/-o` | `decrypt data/reports/x.md.enc` |
| `github status` | — | — | `github status` |
| `github connect` | — | `--repo owner/name`, `--visibility public\|private`, `--push`, `--remote`, `--branch` | `github connect --push` |
| `github host` | — | `--all`, `--reports/--no-reports`, `--papers/--no-papers`, `--limit`, `-m/--message`, `--pages/--no-pages`, `--branch`, `--dry-run` | `github host --reports --limit 20` |

## 3. Target kind → engines auto-selected by `full`
Override the plan with `--engines a,b`. Engine names: `search, whois, domain_intel, social, credential_check, academic, company, web_scraper, openalex, orcid, npi, dark, regional_search, regional_social, sanctions`. Disable any engine globally with `engines.<name>: false` in `config.yaml`.

| Detected kind | Example | Engines run |
|---|---|---|
| email | `a@b.com` | credential_check, search, social, orcid, dark, sanctions |
| domain | `example.com` | whois, domain_intel, web_scraper, search, dark |
| url | `https://x.com` | web_scraper, search |
| ip | `8.8.8.8` | domain_intel, search |
| username | `octocat` | social, regional_social, search, web_scraper, dark |
| name | `John Smith` | search, academic, company, social, regional_social, regional_search, sanctions, openalex, orcid, npi, dark |
| onion | `*.onion` | dark, search |

## 4. Output & artifacts (all relative to the repo root)
| Path | Contents |
|---|---|
| stdout | rich table of findings + summary + risk score |
| `data/reports/report_<target>.<ext>` | the report (written only when `--format` is given); spaces/slashes in the target become `_` |
| `data/reports/*.enc` | encrypted report when `reporting.encrypt: true` + `RESEARCH_ENCRYPTION_KEY` |
| `data/papers/<topic>/<paper-id>.md\|.pdf\|.json` | finalized paper documents (written by `publish`) |
| `data/papers/<topic>/<paper-id>.meta.json` | catalogue record for a paper |
| `data/papers/INDEX.md` / `INDEX.json` | auto-generated paper catalogue |
| `data/papers/ORGANISATION.md` | the paper-library organisation rules |
| `data/research.log` | rolling log (PII-redacted unless `logging.redact_pii: false`) |
| `data/cache/responses.db` | HTTP response cache (TTL `cache.ttl_seconds`, default 3600 s) |
| `data/audit.log` | optional PII-minimised action audit (`ethics.audit_log: true`) |
| `docs/index.html` | GitHub Pages landing page (built by `github host`; nothing uploaded until then) |
| `docs/reports/`, `docs/papers/` | site copies + rendered HTML of the hosted reports/papers |

## 4.1 Reports vs. finalized papers (`data/papers/`)

**Reports are not papers.** A report (`data/reports/`) records what the engines found and is transient/purge-eligible. A **paper** is the reviewed, citable write-up: abstract, methodology, findings by category, risk assessment, source register, limitations and provenance. Only publish after reviewing a report.

| Rule | Value |
|---|---|
| Location | `data/papers/<topic>/` |
| Topic shelves | `people` (name/email/username), `domains` (domain/url/ip/onion), `organisations`, `general`; override with `--topic` |
| Paper ID | `<target-slug>_<YYYY-MM-DD>[_vN]` (publication date, UTC); same-day re-publish gets `_v2`, `_v3`… |
| Documents | `.md` (primary), `.pdf`, `.json`; each has a sibling `<paper-id>.meta.json` |
| Status | `draft` → `final` → `archived` (`papers.default_status` sets the default) |
| Index | `INDEX.md` / `INDEX.json` are rebuilt from records by every `publish`, `archive-paper` and `papers --rebuild-index`; never edit by hand |
| Archive | `archive-paper <paper-id>` moves documents + record to `_archive/<topic>/` |
| Search | `papers --topic` / `--query` / `--status` / `--archived` |
| Retention | `purge` leaves `data/papers/` alone unless `--include-papers` is explicit; `--ephemeral` cannot publish |

Minimum workflow: run the engines (`full`/single commands, optionally `--format json`) → review findings and translate non-English material into English → `publish` with a topic, tags and `--status final` → confirm the entry in `data/papers/INDEX.md`. Full rules: `data/papers/ORGANISATION.md`; template: `data/papers/_templates/TEMPLATE_research_paper.md`.

## 4.2 Hosting reports on GitHub (optional)
`github connect` links this checkout to a repository; `github host` builds a static site from `data/reports/` + `data/papers/` into `docs/`, commits it in a **single** commit and enables **GitHub Pages**. Nothing is uploaded until you run these commands.

| Command | Purpose | Key options |
|---|---|---|
| `github status` | show target, token, repo existence and the Pages URL | — |
| `github connect` | create/link the repo and set the git remote | `--repo owner/name`, `--visibility public\|private`, `--push`, `--remote`, `--branch` |
| `github host` | build `docs/`, commit it and enable Pages | `--all`, `--reports/--no-reports`, `--papers/--no-papers`, `--limit`, `-m/--message`, `--pages/--no-pages`, `--branch`, `--dry-run` |

Site URL: `https://<owner>.github.io/<repo>/`. Token: `RESEARCH_GITHUB_TOKEN` (else `GITHUB_TOKEN`, else `gh auth token`) — never logged and masked by `config`. Config: the `github:` section of `config.yaml` (`owner`, `repo`, `branch`, `site_dir`, `host_reports`, `host_papers`, `pages`, `visibility`). Commits go through `git push` when an `origin` remote exists, otherwise through the GitHub API in one commit. `--ephemeral` cannot host.

## 5. Global flags (place BEFORE the command)
| Flag | Effect |
|---|---|
| `--ephemeral` / `--no-persist` | keep nothing on disk: in-memory cache, no report/log files |
| `--i-have-authorization` | required only when `ethics.require_attestation: true` |

Example: `python -m research_tool --ephemeral full "Jane Doe"`

## 6. Interpreting findings (important)
Every `Finding` carries `confidence` (0-1) and a `data.status`:
- `matched` — the engine confirmed the datum (e.g. a sanctions hit).
- `not_found` / `unverified` — no corroboration (counts toward the risk score).
- `skipped` — the engine could not run (no Tor, no API key, wrong input kind).
- `blocked` — a source served a captcha / bot wall.

Rules of engagement:
- Never call a credential "verified" unless a registry confirmed it — write "corroborated by public sources".
- A sanctions hit is a **lead, not identity proof**. Report the score and the list; a name match at ≥0.8 can be an unrelated same-surname person.
- `social` / `regional_social` need a single-token **handle**. A display name (e.g. `"Fei-Fei Li"`) returns one `skipped` finding instead of guessing.
- `dark` needs a local Tor (`--tor` or an `http.proxy`); otherwise it returns `skipped`.
- Regional indices may return `blocked` on an IP-based captcha (e.g. Baidu) — see §11.
- **Always report in English.** Translate/transliterate every non-English title, quote, forum/social post or registry entry into English *before* presenting it; keep the native wording only as a clearly-marked secondary reference beside the translation. Never present untranslated non-English text as the primary content (see `agent.md` Operating Principle 7).

## 7. Recipes
```powershell
# Identity / digital footprint
python -m research_tool full "Fei-Fei Li" --format markdown
python -m research_tool social octocat --format json
python -m research_tool credential jane@example.com

# Domain / infrastructure
python -m research_tool domain example.com
python -m research_tool whois example.com --format json

# Cross-border / restricted regions
python -m research_tool regional-search "김정은" --region kr --format json
python -m research_tool regional-search "习近平" --region cn
python -m research_tool regional-social someone
python -m research_tool sanctions "Some Entity" --source ofac,un,eu,uk --threshold 0.85

# Credentials / researchers
python -m research_tool academic "Jane Doe" --issuer MIT --kind academic
python -m research_tool researcher "Yoshua Bengio"      # works, citations, h-index, ORCID
python -m research_tool orcid "Yoshua Bengio"
python -m research_tool license "John Smith" --state NY # US NPI

# Dark web (needs Tor)
python -m research_tool dark "ransomware" --tor
python -m research_tool dark <onion>.onion

# Machine-readable output for downstream parsing
python -m research_tool full example.com --format json  # -> data/reports/report_example.com.json
```

## 8. Driving it from Python (no CLI)
```python
from research_tool.config import get_settings
from research_tool.orchestrator import Orchestrator
from research_tool.reporters import write_report

orch = Orchestrator(get_settings())
report = orch.run_engine("sanctions", "Kim Jong Un")   # one engine
# report = orch.run_full("example.com")                # all applicable engines
for f in report.findings:
    print(f.engine, f.confidence, f.title, f.url, f.data.get("status"))
print("risk", report.risk_score, "kind", report.target_kind)
write_report(report, "json", orch.settings.reports_path)   # raw report (optional)

# Finalize a paper (curated library; record + INDEX updated automatically)
from research_tool.utils.library import PaperLibrary
PaperLibrary(orch.settings.papers_path).publish(
    report, formats=["markdown"], topic="people", tags=["osint"])
orch.close()
```
`report` is a `ResearchReport`; call `report.to_dict()` for JSON-safe output.

## 9. Config knobs that change behaviour (`config.yaml`)
| Section | Key(s) | Effect |
|---|---|---|
| `engines` | `<name>: true/false` | enable/disable an engine |
| `api_keys` | `hibp, shodan, serpapi, hunter, censys_*` | unlock HIBP breach, Shodan, SerpAPI, etc. (`null` = that engine degrades) |
| `i18n` | `target_languages`, `translation_backend` | languages a Latin target expands into; backend `auto\|mymemory\|libretranslate\|deepl\|none` |
| `sanctions` | `sources`, `opensanctions`, `opensanctions_bulk`, `phonetic` | which lists; OpenSanctions API (needs key) or key-free bulk; Metaphone matching |
| `http` | `proxy`, `proxy_pool`, `proxy_pool_auto`, `tor_control_port`, `render_js` | egress/IP rotation + headless render for bot walls |
| `cache` | `ttl_seconds` | cache lifetime (repeat runs are served from cache) |
| `ethics` | `require_attestation`, `allowed_domains`, `audit_log`, `rate_limit_per_minute` | authorisation + scope + throttling |
| `privacy` | `ephemeral`, `retention_hours`, `secure_delete_passes` | disk hygiene + the `purge` window |
| `reporting` | `default_format`, `encrypt` | report defaults / encryption at rest |
| `papers` | `author`, `default_status`, `formats`, `include_raw` | finalized-paper library defaults (`data/papers/`) |
| `github` | `owner`, `repo`, `branch`, `site_dir`, `host_reports`, `host_papers`, `pages`, `visibility` | GitHub hosting target and what `github host` publishes |

## 10. Environment variables (override `config.yaml`)
`RESEARCH_HIBP_KEY`, `RESEARCH_SHODAN_KEY`, `RESEARCH_SERPAPI_KEY`, `RESEARCH_HUNTER_KEY`,
`RESEARCH_CENSYS_ID`, `RESEARCH_CENSYS_SECRET`, `RESEARCH_HTTP_PROXY`, `RESEARCH_LOG_LEVEL`,
`RESEARCH_DEEPL_KEY`, `RESEARCH_LIBRETRANSLATE_URL`, `RESEARCH_OPENSANCTIONS_KEY`,
`RESEARCH_EPHEMERAL=1`, `RESEARCH_AUTHORIZED=1`, and `RESEARCH_ENCRYPTION_KEY` (cache/report encryption).
`RESEARCH_GITHUB_TOKEN`, `RESEARCH_GITHUB_OWNER`, `RESEARCH_GITHUB_REPO`, `RESEARCH_GITHUB_BRANCH` (GitHub hosting; see §4.2).

## 11. Gotchas / known limitations
- Missing API keys degrade gracefully: the affected engine returns `skipped`/`not_found`, never an error.
- IP-based captchas (Baidu; sometimes Naver/Yandex) return `status: blocked`. Fix: `--tor`, `http.proxy`, or `http.proxy_pool`. A normal Naver page is parsed correctly — only real challenges are flagged.
- Sanctions fuzzy matching (default threshold 0.8) can surface unrelated same-name people; always review before asserting.
- Repeated runs are served from cache (TTL); use `--ephemeral` to leave nothing on disk.
- Reports are written to disk only when `--format` is passed; otherwise results are printed only.
- `publish` is the only writer of `data/papers/`. Do not copy papers into the library by hand: without a `.meta.json` record they are invisible to `INDEX.md` and `papers`.
- `--ephemeral` cannot `publish` (papers are explicit disk writes). `purge` keeps `data/papers/` unless `--include-papers` is passed.
- `github host` is the only command that uploads: it commits the selected reports/papers to the GitHub repo and enables Pages (public by default). `--ephemeral` cannot host, and no engine or `publish` uploads implicitly.

## 12. Extend with a new engine
1. Subclass `engines.base.BaseEngine`; set `name`/`category`; implement `run(self, target, **kwargs) -> list[Finding]` (use `self.cached_get(url)` for HTTP and `self.finding(...)` to build results).
2. Register the class in `engines/__init__.py::ENGINE_REGISTRY`.
3. Add an enable flag under `engines:` in `config.yaml` and in `config.py::EnginesConfig`.
4. (Optional) add the engine name to `orchestrator.py::_KIND_ENGINES` so `full` schedules it.

## 13. Verify the install / troubleshooting
- Offline test suites (no network, no pytest required):
  `python tests/test_smoke.py`  ·  `python tests/test_cross_border.py`  ·  `python tests/test_privacy.py`  ·  `python tests/test_papers.py`
- `python -m research_tool engines` → engine list + enabled state.
- `python -m research_tool config` → effective configuration (secrets masked).
- Exit code `2` = authorisation attestation required (re-run with `--i-have-authorization`).


