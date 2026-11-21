# {Paper title}

> **FINALIZED RESEARCH PAPER** · Paper ID `{slug_YYYY-MM-DD}` ·
> Status **FINAL** · Topic shelf `{topic}`

| Document control | Value |
|---|---|
| Target | `{target}` |
| Target kind | `{name \| email \| username \| domain \| url \| ip \| onion}` |
| Topic shelf | `{people \| organisations \| domains \| general \| custom}` |
| Status | FINAL |
| Author / analyst | {author} |
| Published (UTC) | {YYYY-MM-DD HH:MM} |
| Engines run | `{engine, engine, ...}` |
| Findings | {N} |
| Sources cited | {N} |
| Risk score | {0-100}/100 ({NONE \| LOW \| MEDIUM \| HIGH}) |
| Tags | {tag, tag} |
| Library file(s) | `{topic/paper-id.md}` |

## Abstract

{What was researched, how, the key corroborated findings and the main
limitation — 3–6 sentences. English only.}

## 1. Scope and methodology

{Which engines ran, what public sources were used, what was out of scope, and
the confidence convention (0–1 per finding; *corroborated by public sources*
vs *verified by an authoritative registry*).}

## 2. Findings

{Group by category. Each finding keeps its `F#` identifier, engine,
confidence and source `S#`. Add narrative only where it clarifies.}

## 3. Risk assessment

{Score, label and explanation. Risk reflects adverse signals (breach
exposure, credential gaps, explicit engine risk), not finding volume.}

## 4. Source register

{Numbered `S#` list of URLs; each finding in §2 points at one.}

## 5. Limitations and confidence

{What could not be corroborated, engines that were skipped or blocked, and
why absence of a finding is not proof of absence.}

## Appendix A — raw findings (optional)

{Raw JSON dump of the report, when the paper is published with
`--include-raw`. Remove this section when not needed.}

## 6. Provenance

| Field | Value |
|---|---|
| Paper ID | `{paper-id}` |
| Raw report | `{data/reports/... | not linked}` |
| Report generated (UTC) | {YYYY-MM-DD HH:MM} |
| Library rules | `data/papers/ORGANISATION.md` |
| Library index | `data/papers/INDEX.md` |

---

_Publish this paper with `python -m research_tool publish` so the metadata
record and `INDEX.md` entry are created. Do not copy the file in by hand._