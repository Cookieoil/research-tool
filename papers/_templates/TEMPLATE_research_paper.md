# {Paper title: specific, informative, no marketing language}

## Abstract

{One paragraph, 120–200 words: the question, the method, the key findings with
their magnitudes, and the main limitation. English only. Do not cite sources
here.}

**Keywords:** {3–8 lowercase terms, comma-separated.}

## 1. Introduction

{The puzzle, why it matters, what this paper adds, and the roadmap. End with
the paper's central claim in one sentence.}

## 2. Data and method

| Evidence type | Examples | Principal limitation |
|---|---|---|
| {Institutional} | {World Bank, official decrees} | {Publication lag} |
| {Market data} | {Sensor Tower, Gamma Data} | {Estimates, not audited revenue} |
| {Peer-reviewed research} | {Journals, DOIs} | {Sample scope} |
| {Trade press} | {Named outlets} | {Selection and translation risk} |

Table 1. Evidence types and limitations.

{State the confidence convention: how magnitudes are treated, what is
interpreted rather than measured, and what was out of scope. Every number in
the paper must be attributable to a numbered reference.}

## 3. {First substantive section}

{Write prose, not bullet dumps. Use one table per comparison. Cite claims
inline as [1], [2] and keep interpretation clearly separated from reported
fact ("Reading: ...", "Interpretation: ...").}

| Indicator | Value | Interpretation |
|---|---|---|
| {metric} | {value} | {what it means} |

Table 2. {Caption.}

## 4. {Second substantive section}

{Same pattern: prose, one comparison table, inline citations. Where a claim is
a probability or a judgement rather than a measurement, say so explicitly.}

## 5. Discussion

**{Claim in bold.}** {Two to four sentences of argument, with the evidence it
rests on.}

**{Second claim in bold.}** {…}

## 6. Limitations

- {What could not be corroborated.}
- {Which sources disagree and why.}
- {What would change the conclusion.}
- Absence of evidence is not evidence of absence.
- Non-English material is translated into English; originals are secondary.

## 7. Conclusion

{What follows for practitioners and researchers, and what should be graded
next (a falsifiable test where possible).}

## References

[1] {Author or Institution} ({Year}). *{Title}.* {Venue or publisher}. {URL or DOI}

[2] {…}

---

_Authoring notes — delete before publishing._

- **Manuscript first.** The `.pdf` is typeset from this Markdown by
  `research_tool/reporters/academic_pdf.py`, so fix the `.md`, never the PDF.
  Supported: `#` title, `##`/`###` headings, prose paragraphs, `|` tables with
  a delimiter row, `-` bullets, `1.` numbered lists, `>` callouts, fenced code,
  inline `**bold**`, `*italic*`, `` `code` ``, `[text](url)` and `<url>`.
- **Show, do not only tell.** Use the five visual fences where a figure beats
  prose (see `papers/ORGANISATION.md` §10):
  ```` ```chart-stats ```` (KPI cards, `| value | label |` rows),
  ```` ```chart-bars ```` (ranked horizontal bars, `| label | number |` rows),
  ```` ```chart-line ```` (annotated trend, one or two numeric columns),
  ```` ```chart-heatmap ```` (shaded intensity matrix) and
  ```` ```chart-timeline ```` (dated milestones). Keys go inside the fence:
  `title:`, `caption:` (cite it), `note:`, plus `benchmark: 25` for a labelled
  reference line, `invert: true` for a lower-is-better series (a declining
  grossing rank) and `suffix: %` for units. A Mermaid `flowchart` fence becomes
  a numbered step flow. Never print the same dataset as both a table and a
  figure: give the figure a derived view (trend, ranking, benchmark) instead.
- **An `## Abstract` section renders as a shaded abstract box**, and a
  `## References` section is typeset with a hanging indent — never use a table
  for references.
- **Register the paper** so it is findable: either `python -m research_tool
  publish --from <report.json>`, or author the manuscript and write
  `papers/_meta/<topic>/<paper-id>.meta.json` with `files` listing
  `<topic>/<paper-id>.md` and `<topic>/<paper-id>.pdf`.
- **Then run** `python -m research_tool papers --rebuild-index` to typeset the
  PDF, rebuild `INDEX.md`/`INDEX.json` and refresh the `papers/pdfs/` shelf.
- **Never** include `engine=... | category=...` debug strings, raw Markdown
  syntax, bare URLs in body text, or repeated boilerplate sections; add the
  claim to the reference list instead.
- Never store API keys, passwords or live credentials in a paper.