# Vietnam Game Industry: Prediction & Impact Scorecard (2026 Baseline)

> **FINALIZED RESEARCH PAPER** · Paper ID `vietnam-game-prediction-scorecard_2026-11-22` · Status **FINAL** · Topic shelf `general`

| Document control | Value |
|---|---|
| Target | `Vietnam Game Prediction Scorecard` |
| Target kind | scorecard |
| Topic shelf | `general` |
| Status | FINAL |
| Author / analyst | None-Bias Research Agent |
| Published (UTC) | 2026-11-22 21:30 |
| Engines run | forecast, impact_tracking |
| Findings | 20 |
| Sources cited | 0 |
| Risk score | 0/100 (NONE) |
| Tags | vietnam, video-games, scorecard, forecast, predictions, impact, tracking, json, grading |
| Library file(s) | `general/vietnam-game-prediction-scorecard_2026-11-22.md`, `general/vietnam-game-prediction-scorecard_2026-11-22.json` |

## Abstract

This is a machine-readable scorecard for the Vietnam game-industry series. It restates the companion forecast paper's fifteen predictions - each with a horizon, a confidence value, a resolve-by date, a watch metric and a falsifier - and the impact paper's five tracking channels. Every prediction is encoded as structured data so it can be graded programmatically in 2027-2031: the companion JSON contains each prediction's horizon, resolve_by date, metric, falsifier and a status of 'unresolved'. The purpose is accountability: rather than letting forecasts fade, this scorecard lets an analyst mark each claim right, wrong or moot at its resolve-by date. The predictions cover the export crown, the download-vs-revenue gap, the $1bn-by-2030 target, Decree 147 consolidation, hyper-casual exemptions, licensing friction, VNG and Sky Mavis, consolidation, co-development, AI margins, senior talent, esports, mobile dominance and cultural-export framing. The scorecard inherits the forecast and impact papers' limitations and adds no new evidence.

## 1. Scope and methodology

Scorecard construction. The fifteen predictions and five impact channels are transcribed from the companion papers and encoded as research findings with structured data fields (type, horizon, resolve_by, metric, falsifier, status). Publishing emits a Markdown scorecard and a JSON file whose 'report.findings' array is directly parseable. To grade, compare each prediction's metric against the observed value at its resolve_by date and set status to resolved_true / resolved_false / moot. No new data were collected.

## 2. Findings

The 20 finding(s) are grouped by category below. `F#` is the finding identifier and `S#` refers to the source register in §4.

### 2.1 Predictions (15)

| ID | Finding | Engine | Confidence | Source |
|---|---|---|---:|---|
| F1 | By 2031 Vietnam keeps the #1 mobile-game export crown | `forecast` | 0.75 (moderate) | — |
| F2 | Export downloads grow, but per-user revenue stays low | `forecast` | 0.70 (moderate) | — |
| F3 | Total market nears $1bn, but domestic mobile misses it | `forecast` | 0.60 (moderate) | — |
| F4 | Decree 147 consolidates publishing around licensed locals | `forecast` | 0.75 (moderate) | — |
| F5 | Hyper-casual exporters stay outside the licence regime | `forecast` | 0.70 (moderate) | — |
| F6 | Licensing friction and revocations persist | `forecast` | 0.65 (moderate) | — |
| F7 | VNG stays the anchor; a big overseas IPO is unlikely before 2028 | `forecast` | 0.55 (moderate) | — |
| F8 | Sky Mavis pivots to infrastructure; no second Web3 mega-hit | `forecast` | 0.60 (moderate) | — |
| F9 | M&A and consolidation among mid-size studios rise | `forecast` | 0.60 (moderate) | — |
| F10 | Vietnam grows as a co-development / AAA-outsourcing hub | `forecast` | 0.65 (moderate) | — |
| F11 | AI tooling squeezes hyper-casual margins | `forecast` | 0.60 (moderate) | — |
| F12 | Senior talent remains the binding constraint | `forecast` | 0.65 (moderate) | — |
| F13 | Esports stays publisher-dependent; the state stays cautious | `forecast` | 0.60 (moderate) | — |
| F14 | Mobile stays above 85% of players; young demand grows | `forecast` | 0.70 (moderate) | — |
| F15 | Policy increasingly frames games as a cultural export | `forecast` | 0.65 (moderate) | — |

**F1 — By 2031 Vietnam keeps the #1 mobile-game export crown**

- *Engine:* `forecast` · *category:* `predictions` · *confidence:* 0.75 (moderate)
- *Detail:* Prediction to 2031; resolve by 2031-12-31. Watch: Google / Sensor Tower export ranking. Falsified if: Another country overtakes Vietnam on export rankings before 2031.
- *Recorded data:*

```json
{
  "type": "prediction",
  "horizon": "2031",
  "resolve_by": "2031-12-31",
  "metric": "Google / Sensor Tower export ranking",
  "falsifier": "Another country overtakes Vietnam on export rankings before 2031",
  "status": "unresolved"
}
```

**F2 — Export downloads grow, but per-user revenue stays low**

- *Engine:* `forecast` · *category:* `predictions` · *confidence:* 0.70 (moderate)
- *Detail:* Prediction to 2028; resolve by 2028-12-31. Watch: ARPDAU ex-ads vs ~$0.70 benchmark. Falsified if: Vietnam ARPDAU approaches the ~$0.70 benchmark by 2028.
- *Recorded data:*

```json
{
  "type": "prediction",
  "horizon": "2028",
  "resolve_by": "2028-12-31",
  "metric": "ARPDAU ex-ads vs ~$0.70 benchmark",
  "falsifier": "Vietnam ARPDAU approaches the ~$0.70 benchmark by 2028",
  "status": "unresolved"
}
```

**F3 — Total market nears $1bn, but domestic mobile misses it**

- *Engine:* `forecast` · *category:* `predictions` · *confidence:* 0.60 (moderate)
- *Detail:* Prediction to 2030; resolve by 2030-12-31. Watch: Domestic mobile revenue vs $1bn target. Falsified if: Domestic mobile revenue alone exceeds $1bn before 2030.
- *Recorded data:*

```json
{
  "type": "prediction",
  "horizon": "2030",
  "resolve_by": "2030-12-31",
  "metric": "Domestic mobile revenue vs $1bn target",
  "falsifier": "Domestic mobile revenue alone exceeds $1bn before 2030",
  "status": "unresolved"
}
```

**F4 — Decree 147 consolidates publishing around licensed locals**

- *Engine:* `forecast` · *category:* `predictions` · *confidence:* 0.75 (moderate)
- *Detail:* Prediction to 2028; resolve by 2028-12-31. Watch: Share of top-grossing titles via licensed locals. Falsified if: Unlicensed foreign titles regain broad domestic distribution.
- *Recorded data:*

```json
{
  "type": "prediction",
  "horizon": "2028",
  "resolve_by": "2028-12-31",
  "metric": "Share of top-grossing titles via licensed locals",
  "falsifier": "Unlicensed foreign titles regain broad domestic distribution",
  "status": "unresolved"
}
```

**F5 — Hyper-casual exporters stay outside the licence regime**

- *Engine:* `forecast` · *category:* `predictions` · *confidence:* 0.70 (moderate)
- *Detail:* Prediction to 2028; resolve by 2028-12-31. Watch: Licensing applied to export-oriented studios. Falsified if: Enforcement extends to export studios at scale.
- *Recorded data:*

```json
{
  "type": "prediction",
  "horizon": "2028",
  "resolve_by": "2028-12-31",
  "metric": "Licensing applied to export-oriented studios",
  "falsifier": "Enforcement extends to export studios at scale",
  "status": "unresolved"
}
```

**F6 — Licensing friction and revocations persist**

- *Engine:* `forecast` · *category:* `predictions` · *confidence:* 0.65 (moderate)
- *Detail:* Prediction to 2027; resolve by 2027-12-31. Watch: G1 licence revocation rate. Falsified if: Revocation rates fall sharply and timelines are met.
- *Recorded data:*

```json
{
  "type": "prediction",
  "horizon": "2027",
  "resolve_by": "2027-12-31",
  "metric": "G1 licence revocation rate",
  "falsifier": "Revocation rates fall sharply and timelines are met",
  "status": "unresolved"
}
```

**F7 — VNG stays the anchor; a big overseas IPO is unlikely before 2028**

- *Engine:* `forecast` · *category:* `predictions` · *confidence:* 0.55 (moderate)
- *Detail:* Prediction to 2028; resolve by 2028-12-31. Watch: Any completed major international listing. Falsified if: A completed major overseas IPO before 2028.
- *Recorded data:*

```json
{
  "type": "prediction",
  "horizon": "2028",
  "resolve_by": "2028-12-31",
  "metric": "Any completed major international listing",
  "falsifier": "A completed major overseas IPO before 2028",
  "status": "unresolved"
}
```

**F8 — Sky Mavis pivots to infrastructure; no second Web3 mega-hit**

- *Engine:* `forecast` · *category:* `predictions` · *confidence:* 0.60 (moderate)
- *Detail:* Prediction to 2028; resolve by 2028-12-31. Watch: New Vietnamese Web3 title at mass scale. Falsified if: A new Vietnamese Web3 game reaching mass scale by 2028.
- *Recorded data:*

```json
{
  "type": "prediction",
  "horizon": "2028",
  "resolve_by": "2028-12-31",
  "metric": "New Vietnamese Web3 title at mass scale",
  "falsifier": "A new Vietnamese Web3 game reaching mass scale by 2028",
  "status": "unresolved"
}
```

**F9 — M&A and consolidation among mid-size studios rise**

- *Engine:* `forecast` · *category:* `predictions` · *confidence:* 0.60 (moderate)
- *Detail:* Prediction to 2028; resolve by 2028-12-31. Watch: Studio count and M&A volume. Falsified if: Studio count and independent mid-tier grow through 2028.
- *Recorded data:*

```json
{
  "type": "prediction",
  "horizon": "2028",
  "resolve_by": "2028-12-31",
  "metric": "Studio count and M&A volume",
  "falsifier": "Studio count and independent mid-tier grow through 2028",
  "status": "unresolved"
}
```

**F10 — Vietnam grows as a co-development / AAA-outsourcing hub**

- *Engine:* `forecast` · *category:* `predictions` · *confidence:* 0.65 (moderate)
- *Detail:* Prediction to 2029; resolve by 2029-12-31. Watch: Outsourcing revenue and headcount. Falsified if: Outsourcing revenue and headcount stagnate.
- *Recorded data:*

```json
{
  "type": "prediction",
  "horizon": "2029",
  "resolve_by": "2029-12-31",
  "metric": "Outsourcing revenue and headcount",
  "falsifier": "Outsourcing revenue and headcount stagnate",
  "status": "unresolved"
}
```

**F11 — AI tooling squeezes hyper-casual margins**

- *Engine:* `forecast` · *category:* `predictions` · *confidence:* 0.60 (moderate)
- *Detail:* Prediction to 2028; resolve by 2028-12-31. Watch: Studio margins after AI adoption. Falsified if: Margins and studio counts are stable despite AI adoption.
- *Recorded data:*

```json
{
  "type": "prediction",
  "horizon": "2028",
  "resolve_by": "2028-12-31",
  "metric": "Studio margins after AI adoption",
  "falsifier": "Margins and studio counts are stable despite AI adoption",
  "status": "unresolved"
}
```

**F12 — Senior talent remains the binding constraint**

- *Engine:* `forecast` · *category:* `predictions` · *confidence:* 0.65 (moderate)
- *Detail:* Prediction to 2028; resolve by 2028-12-31. Watch: Senior wage / shortage indicators. Falsified if: A clear surplus of senior talent or falling senior wages.
- *Recorded data:*

```json
{
  "type": "prediction",
  "horizon": "2028",
  "resolve_by": "2028-12-31",
  "metric": "Senior wage / shortage indicators",
  "falsifier": "A clear surplus of senior talent or falling senior wages",
  "status": "unresolved"
}
```

**F13 — Esports stays publisher-dependent; the state stays cautious**

- *Engine:* `forecast` · *category:* `predictions` · *confidence:* 0.60 (moderate)
- *Detail:* Prediction to 2028; resolve by 2028-12-31. Watch: Publisher-run vs independent leagues. Falsified if: State-led, publisher-independent leagues at scale.
- *Recorded data:*

```json
{
  "type": "prediction",
  "horizon": "2028",
  "resolve_by": "2028-12-31",
  "metric": "Publisher-run vs independent leagues",
  "falsifier": "State-led, publisher-independent leagues at scale",
  "status": "unresolved"
}
```

**F14 — Mobile stays above 85% of players; young demand grows**

- *Engine:* `forecast` · *category:* `predictions` · *confidence:* 0.70 (moderate)
- *Detail:* Prediction to 2031; resolve by 2031-12-31. Watch: Platform mix of players. Falsified if: A sharp shift to PC/console share or demographic decline.
- *Recorded data:*

```json
{
  "type": "prediction",
  "horizon": "2031",
  "resolve_by": "2031-12-31",
  "metric": "Platform mix of players",
  "falsifier": "A sharp shift to PC/console share or demographic decline",
  "status": "unresolved"
}
```

**F15 — Policy increasingly frames games as a cultural export**

- *Engine:* `forecast` · *category:* `predictions` · *confidence:* 0.65 (moderate)
- *Detail:* Prediction to 2030; resolve by 2030-12-31. Watch: Policy and incentive language. Falsified if: A return to restriction-first framing.
- *Recorded data:*

```json
{
  "type": "prediction",
  "horizon": "2030",
  "resolve_by": "2030-12-31",
  "metric": "Policy and incentive language",
  "falsifier": "A return to restriction-first framing",
  "status": "unresolved"
}
```

### 2.2 Impact Channels (5)

| ID | Finding | Engine | Confidence | Source |
|---|---|---|---:|---|
| F16 | Games' share of digital-economy GMV | `impact_tracking` | 0.60 (moderate) | — |
| F17 | Cross-border / platform tax receipts | `impact_tracking` | 0.60 (moderate) | — |
| F18 | Senior-talent retention | `impact_tracking` | 0.60 (moderate) | — |
| F19 | Studio incorporation location | `impact_tracking` | 0.55 (moderate) | — |
| F20 | Domestic-vs-export revenue split | `impact_tracking` | 0.60 (moderate) | — |

**F16 — Games' share of digital-economy GMV**

- *Engine:* `impact_tracking` · *category:* `impact channels` · *confidence:* 0.60 (moderate)
- *Detail:* Impact channel to track: Games' contribution within the ~$39bn digital economy.
- *Recorded data:*

```json
{
  "type": "impact_channel",
  "metric": "Games' contribution within the ~$39bn digital economy",
  "status": "tracking"
}
```

**F17 — Cross-border / platform tax receipts**

- *Engine:* `impact_tracking` · *category:* `impact channels` · *confidence:* 0.60 (moderate)
- *Detail:* Impact channel to track: Tax collected from foreign platforms (Google, Meta, etc.).
- *Recorded data:*

```json
{
  "type": "impact_channel",
  "metric": "Tax collected from foreign platforms (Google, Meta, etc.)",
  "status": "tracking"
}
```

**F18 — Senior-talent retention**

- *Engine:* `impact_tracking` · *category:* `impact channels` · *confidence:* 0.60 (moderate)
- *Detail:* Impact channel to track: Net retention vs emigration of senior developers.
- *Recorded data:*

```json
{
  "type": "impact_channel",
  "metric": "Net retention vs emigration of senior developers",
  "status": "tracking"
}
```

**F19 — Studio incorporation location**

- *Engine:* `impact_tracking` · *category:* `impact channels` · *confidence:* 0.55 (moderate)
- *Detail:* Impact channel to track: Whether studios incorporate/staff in Vietnam or abroad.
- *Recorded data:*

```json
{
  "type": "impact_channel",
  "metric": "Whether studios incorporate/staff in Vietnam or abroad",
  "status": "tracking"
}
```

**F20 — Domestic-vs-export revenue split**

- *Engine:* `impact_tracking` · *category:* `impact channels` · *confidence:* 0.60 (moderate)
- *Detail:* Impact channel to track: Share of revenue earned domestically vs abroad.
- *Recorded data:*

```json
{
  "type": "impact_channel",
  "metric": "Share of revenue earned domestically vs abroad",
  "status": "tracking"
}
```

## 3. Risk assessment

**Risk score: 0/100 (NONE).** Not applicable. This scorecard tracks predictions about an industry, not an adverse-signal assessment of a person or organisation, so the toolkit's 0-100 score has no subject. A score of 0/100 (NONE) records that no such assessment was in scope.

Findings by engine: `forecast` (15), `impact_tracking` (5).

## 4. Source register

_No source URLs were recorded with the findings._

## 5. Limitations and confidence

- The scorecard restates predictions from the companion papers; it adds no new evidence and inherits their limits.
- Confidence values are subjective probabilities, not frequentist estimates.
- Resolve-by dates are calendar-year proxies; several claims depend on private decisions and macro conditions that cannot be observed in advance.
- Metrics require manual verification against primary sources at grading time.
- The scorecard tracks an industry, not an individual or organisation; the risk score is not applicable.
- Absence of a finding is not proof of absence; sources that were skipped or blocked are noted in the findings.
- Public data changes. Re-verify sources before relying on a paper that is no longer current.
- Non-English source material is translated into English; original wording is kept only as a clearly marked secondary reference.

## 6. Provenance

- **Paper ID:** `vietnam-game-prediction-scorecard_2026-11-22`
- **Status:** FINAL
- **Report generated (UTC):** 2026-11-22 21:30
- **Raw report:** not linked (engines were run for this paper)
- **Library rules:** `data/reports/ORGANISATION.md`
- **Library index:** `data/reports/INDEX.md`
