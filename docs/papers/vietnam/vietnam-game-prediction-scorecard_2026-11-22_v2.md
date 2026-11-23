# Vietnam Game Industry: Forecast, Impact & Reform Scorecard (2026 Baseline)

## Abstract

This is the extended, machine-readable scorecard for the Vietnam game-industry series. It now holds thirty items: the companion forecast paper's fifteen predictions, the impact paper's five tracking channels, and ten reform predictions from the reform-feasibility paper. Every prediction is encoded as structured data - horizon, resolve-by date, watch metric, falsifier and status (and, for reform items, a probability) - so it can be graded programmatically in 2027-2031. Fifteen forecasts cover the export crown, the download-vs-revenue gap, the $1bn target, Decree 147 consolidation, licensing friction, VNG, Sky Mavis, consolidation, co-development, AI margins, talent and esports. Ten reform predictions cover promotion incentives, cultural-industry status, consolidation, licensing simplification, talent retention, content/data liberalisation, the local-entity requirement, independent esports, value capture and implementation capacity. The scorecard adds no new evidence.

## 1. Introduction

Forecasts that are never graded are forgotten. This paper publishes the series' predictions as a scorecard of thirty items - fifteen industry forecasts, five impact channels and ten reform predictions - each with a horizon, a watch metric, a falsifier and a resolution date, so that the analysis can be scored rather than argued about.

## 2. Evidence and method

Scorecard construction. The fifteen forecasts and five impact channels are transcribed from the companion papers; the ten reform predictions come from the reform-feasibility paper. Each is encoded as a research finding with structured data fields (type, horizon, resolve_by, metric, falsifier, status; plus probability for reform items). Publishing emits a Markdown scorecard and a JSON file whose 'report.findings' array is directly parseable. To grade, compare each item's metric against the observed value at its resolve_by date and set status to resolved_true / resolved_false / moot. No new data were collected.

Every claim below is a finding reproduced from the underlying research record: the claim text and its supporting detail are carried over from that record, the confidence label is the one the analysis assigned, and a bracketed number points at the reference register at the end of the paper. Analytical judgements are labelled as such, and no new data were collected for this paper.

## 3. Predictions

The fifteen forecasts are transcribed from the companion industry forecast and impact papers [1, 2].

**By 2031 Vietnam keeps the #1 mobile-game export crown.** Prediction to 2031; resolve by 2031-12-31. Watch: Google / Sensor Tower export ranking. Falsified if: Another country overtakes Vietnam before 2031.

**Export downloads grow, but per-user revenue stays low.** Prediction to 2028; resolve by 2028-12-31. Watch: ARPDAU ex-ads vs ~$0.70 benchmark. Falsified if: ARPDAU approaches the ~$0.70 benchmark by 2028.

**Total market nears $1bn, but domestic mobile misses it.** Prediction to 2030; resolve by 2030-12-31. Watch: Domestic mobile revenue vs $1bn. Falsified if: Domestic mobile revenue alone exceeds $1bn before 2030.

**Decree 147 consolidates publishing around licensed locals.** Prediction to 2028; resolve by 2028-12-31. Watch: Share of top-grossing via licensed locals. Falsified if: Unlicensed foreign titles regain broad distribution.

**Hyper-casual exporters stay outside the licence regime.** Prediction to 2028; resolve by 2028-12-31. Watch: Licensing of export-oriented studios. Falsified if: Enforcement extends to export studios at scale.

**Licensing friction and revocations persist.** Prediction to 2027; resolve by 2027-12-31. Watch: G1 revocation rate. Falsified if: Revocations fall sharply and timelines are met.

**VNG anchors; big overseas IPO unlikely before 2028.** Prediction to 2028; resolve by 2028-12-31. Watch: Any completed major international listing. Falsified if: A completed major overseas IPO before 2028.

**Sky Mavis pivots; no second Web3 mega-hit.** Prediction to 2028; resolve by 2028-12-31. Watch: New Vietnamese Web3 title at mass scale. Falsified if: A new Vietnamese Web3 game at mass scale by 2028.

**M&A and consolidation among mid-size studios rise.** Prediction to 2028; resolve by 2028-12-31. Watch: Studio count and M&A volume. Falsified if: Studio count and independent mid-tier grow through 2028.

**Vietnam grows as a co-development hub.** Prediction to 2029; resolve by 2029-12-31. Watch: Outsourcing revenue and headcount. Falsified if: Outsourcing revenue and headcount stagnate.

**AI tooling squeezes hyper-casual margins.** Prediction to 2028; resolve by 2028-12-31. Watch: Studio margins after AI adoption. Falsified if: Margins and studio counts stable despite AI adoption.

**Senior talent remains the binding constraint.** Prediction to 2028; resolve by 2028-12-31. Watch: Senior wage / shortage indicators. Falsified if: A clear surplus of senior talent or falling senior wages.

**Esports stays publisher-dependent.** Prediction to 2028; resolve by 2028-12-31. Watch: Publisher-run vs independent leagues. Falsified if: State-led, publisher-independent leagues at scale.

**Mobile stays above 85% of players.** Prediction to 2031; resolve by 2031-12-31. Watch: Platform mix of players. Falsified if: A sharp shift to PC/console share or demographic decline.

**Games increasingly framed as cultural export.** Prediction to 2030; resolve by 2030-12-31. Watch: Policy and incentive language. Falsified if: A return to restriction-first framing.

## 4. Impact Channels

**Games' share of digital-economy GMV.** Impact channel to track: Games' contribution within the ~$39bn digital economy.

**Cross-border / platform tax receipts.** Impact channel to track: Tax collected from foreign platforms (Google, Meta, etc.).

**Senior-talent retention.** Impact channel to track: Net retention vs emigration of senior developers.

**Studio incorporation location.** Impact channel to track: Whether studios incorporate/staff in Vietnam or abroad.

**Domestic-vs-export revenue split.** Impact channel to track: Share of revenue earned domestically vs abroad.

## 5. Reform Predictions

```chart-bars
title: Reform probabilities to 2031 (percent)
benchmark: 50
| Reform | Probability |
| Promotion incentives expand | 75 |
| Cultural-industry tax breaks | 70 |
| Publishing consolidation | 75 |
| Licensing simplification | 55 |
| Talent retention | 45 |
| Content/data liberalisation | 30 |
| End local-entity rule | 15 |
| Independent esports | 25 |
| Value-capture upgrade | 35 |
| Implementation capacity | 45 |
caption: Figure 1. The asymmetry of reform: every measure that lowers friction for capital sits above 50 percent, and every measure that relaxes control sits below it [12, 13].
```

**Promotion-side incentives keep expanding.** Reform probability ~75% by 2028; resolve by 2028-12-31. Watch: Digital Technology Law / Decree 96 incentive uptake. Falsified if: New incentives go unimplemented.

**Games stay a priority cultural industry with tax breaks.** Reform probability ~70% by 2028; resolve by 2028-12-31. Watch: Priority-list status / incentive continuity. Falsified if: Games dropped from the priority list.

**Continued consolidation around licensed locals.** Reform probability ~75% by 2028; resolve by 2028-12-31. Watch: Share of top-grossing via licensed locals. Falsified if: Unlicensed foreign titles regain broad distribution.

**Moderate licensing simplification.** Reform probability ~55% by 2028; resolve by 2028-12-31. Watch: G1 processing time / revocation rate. Falsified if: Revocations stay high and delays persist.

**Talent retention improves via incentives.** Reform probability ~45% by 2029; resolve by 2029-12-31. Watch: Senior emigration indicators. Falsified if: Senior emigration accelerates.

**Deeper content/data liberalisation.** Reform probability ~30% by 2030; resolve by 2030-12-31. Watch: Data-localisation / real-name rules. Falsified if: Material relaxation of data/real-name rules.

**End of the local-entity publishing requirement.** Reform probability ~15% by 2031; resolve by 2031-12-31. Watch: Local-entity requirement. Falsified if: Requirement removed or a major carve-out.

**Independent (publisher-independent) esports at scale.** Reform probability ~25% by 2030; resolve by 2030-12-31. Watch: Publisher-run vs independent leagues. Falsified if: A major independent league reaches scale.

**A genuine value-capture upgrade.** Reform probability ~35% by 2031; resolve by 2031-12-31. Watch: Share of revenue from original IP. Falsified if: A durable IP-led revenue shift.

**Implementation capacity improves enough to matter.** Reform probability ~45% by 2029; resolve by 2029-12-31. Watch: Procedures updated / predictability. Falsified if: Sharp, sustained improvement in procedures.

## 6. Interpretation and confidence

The scorecard restates predictions from its companion papers and adds no new evidence; it assesses an industry, not an individual or organisation, so the toolkit's 0-100 adverse-signal score has no subject. Probabilities are calibrated judgements with self-imposed resolution dates.

## 7. Limitations

- The scorecard restates predictions from companion papers; it adds no new evidence and inherits their limits.
- Probabilities are subjective judgements, not statistical estimates.
- Resolve-by dates are calendar-year proxies; some claims depend on private decisions and macro conditions.
- Metrics require manual verification against primary sources at grading time.
- Absence of a finding is not proof of absence; sources that were skipped or blocked are noted in the findings.
- Public data changes. Re-verify sources before relying on a paper that is no longer current.
- Non-English source material is translated into English; original wording is kept only as a clearly marked secondary reference.
- Absence of evidence is not evidence of absence.
- Public data changes; re-verify sources before relying on a paper that is no longer current.
- Non-English source material is translated into English; original wording is kept only as a marked secondary reference.

## 8. Conclusion

The scorecard is the series' accountability mechanism. Grade each item against its watch metric at its resolve-by date: the pattern of results will show whether the binding constraint on Vietnam's game industry is value capture, regulation or execution capacity - the question the series as a whole poses.

## References

[1] Vietnam's Video Game Industry: Forecasts to 2031 (`papers/vietnam/vietnam-game-industry-forecast_2026-11-22.md`)
[2] How Vietnam's Game-Industry Situation Affects the Country (`papers/vietnam/vietnam-game-industry-impact_2026-11-22.md`)
[3] What It Would Take for Vietnam's Game Policy to Change (`papers/vietnam/vietnam-game-policy-reform_2026-11-22.md`)

