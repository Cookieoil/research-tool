# Finalized Research Paper Library — Organisation Rules

**Purpose.** `papers/` holds *finalized research papers* — the curated, citable
end product. It does **not** hold raw engine output, caches or logs. The three
locations are deliberately separate:

| Location | Holds | Lifecycle |
|---|---|---|
| `data/raw/` | raw findings / engine output (`--format` on any command) | transient; eligible for `purge` |
| `data/sources/` | imported inputs: prior drafts, vendor decks, raw report JSON | reference material; keep with provenance |
| `papers/` | finalized, curated papers (this folder) | durable deliverables |

A report answers *"what did the engines find?"*. A paper answers *"what did we
conclude, on what evidence, and when?"* Publish a paper only after reviewing
the report.

---

## 1. Layout (do not invent new top-level folders)

```
papers/
├── INDEX.md / INDEX.json      # auto-generated catalogue — never hand-edit
├── ORGANISATION.md            # this rules file
├── pdfs/                      # reading shelf: every active PDF, readable name
├── README.md                  # one-page guide for humans
├── _meta/<topic>/             # .meta.json records + .json (machine copies)
├── _templates/                # authoring template
├── _archive/<topic>/          # superseded or withdrawn papers
└── <topic>/                   # one shelf per topic (vietnam, gacha, people, ...)
    ├── <paper-id>.md          # manuscript (primary, human-readable)
    └── <paper-id>.pdf         # typeset edition
```

**Readable documents live on the shelf; machine records live in `_meta/`.**
That is the rule that keeps the library usable: opening `papers/vietnam/`
shows manuscripts and PDFs, never a wall of JSON.

Topic shelves are single folder names. The defaults are:

| Target kind | Shelf |
|---|---|
| `name`, `email`, `username` | `people` |
| `domain`, `url`, `ip`, `onion` | `domains` |
| anything else / mixed research | `general` |

Use a custom shelf with `--topic <name>` for research programmes (for example
`--topic vietnam` or `--topic gacha`). Shelves are lower-kebab-case
(`slugify`d). Never nest shelves (`people/politicians`) and never put loose
files in the library root.

`pdfs/` is generated: `rebuild_index` copies every active PDF there under a
human-readable name (`The_Vietnam_Research_Program_2026.pdf`). Never hand-edit
it; the next rebuild prunes stale copies.

## 2. Naming rules

```
<paper-id>.<ext>            <paper-id> = <slug>_<YYYY-MM-DD>[_vN]
<paper-id>.meta.json        (in _meta/<topic>/)
```

- `<slug>` is the target, transliterated to lower-kebab ASCII
  (`"Jane Doe"` → `jane-doe`; non-Latin targets fall back to `paper-<hash8>`).
- `<YYYY-MM-DD>` is the **publication date (UTC)**, not the research date.
- Re-publishing the same target on the same date creates `_v2`, `_v3`, …
  Nothing is overwritten.
- A new publication date is a new paper ID. Archive the older version (§4).
- Extensions: `.md` (primary), `.pdf` (typeset edition), `.json`
  (machine-readable, stored in `_meta/`). Never `.docx`/`.xlsx` here.

## 3. Metadata record (`.meta.json`)

The toolkit writes one record beside every paper's JSON copy in
`_meta/<topic>/`. It is the catalogue source of truth; keep it there and never
rename it by hand.

| Field | Meaning |
|---|---|
| `paper_id` | `<slug>_<date>[_vN]` |
| `title`, `target`, `target_kind` | what the paper is about |
| `topic` | shelf folder name |
| `status` | `draft` → `final` → `archived` |
| `author` | analyst credited (`papers.author`) |
| `abstract` | curated abstract override |
| `tags` | free-text labels for lookup |
| `created_at` | publication timestamp (UTC) |
| `risk_score`, `risk_label` | 0–100 score and NONE/LOW/MEDIUM/HIGH |
| `findings`, `engines`, `sources` | counts / provenance |
| `files` | document files relative to the library root |
| `source_report` | raw report the paper was finalized from |

**Convention for authored papers.** A paper written directly (a synthesis,
literature review or case study rather than an engine run) sets `findings` to
the number of numbered references in its source register, and `sources` to the
same value: for these papers the cited evidence base *is* the finding set. The
`engines` field then records `retrospective_synthesis`.
## 4. Lifecycle rules

1. **Draft** — work in progress. Use `--status draft` while reviewing.
2. **Final** — reviewed, English, every claim backed by a source. This is the
   default (`papers.default_status: final`).
3. **Archived** — superseded or withdrawn. Move it with:

   ```powershell
   python -m research_tool archive-paper <paper-id>
   ```

   This moves the documents *and* the record to `_archive/<topic>/` and
   rebuilds the index. Never delete a paper that was ever cited — archive it.

## 5. Index rules

- `INDEX.md` and `INDEX.json` are **auto-generated** from the `.meta.json`
  records. Never edit them by hand.
- They are rebuilt by every `publish`, every `archive-paper`, and
  `python -m research_tool papers --rebuild-index` (which also refreshes
  `pdfs/`).
- If a record is malformed the rebuild logs a warning and skips it; fix the
  record (or delete it) and rebuild.
- Never bypass the index by copying papers in by hand. Import an external
  document with `publish --from <report.json>` so it is findable.

## 6. Publishing checklist (paper = final only when all true)

- [ ] Raw report exists in `data/raw/` (or is embedded in a paper JSON).
- [ ] Findings reviewed; confidence and source URLs present.
- [ ] Every non-English title/quote translated to English; native wording
      kept only as a clearly marked secondary reference.
- [ ] Credentials described as *corroborated by public sources* unless an
      authoritative registry was cited.
- [ ] Sanctions/name matches described as leads, not identity proof.
- [ ] Abstract states scope, method, key findings and limitations.
- [ ] `--status final`, a topic shelf, and searchable `--tags`.
- [ ] `publish` reports the new paper in `INDEX.md`.

## 7. Finding things fast

```powershell
python -m research_tool papers                          # all active papers
python -m research_tool papers --topic vietnam          # one shelf
python -m research_tool papers --query "decree 147"     # free-text search
python -m research_tool papers --status draft           # review queue
python -m research_tool papers --archived               # archive
python -m research_tool papers --rebuild-index          # repair index + pdfs/
```

Browse `papers/pdfs/` when you just want to read: every active PDF is there
under its title, whatever the shelf.

## 8. Publishing recipes

```powershell
# Research and finalize in one run (writes .md + record + index)
python -m research_tool publish "Jane Doe" --engines search,academic `
    --tags osint,credential --topic people

# Finalize an existing raw report as a typeset PDF + Markdown
python -m research_tool full example.com --format json
python -m research_tool publish --from data/raw/report_example.com.json `
    --format markdown,pdf --status final

# Distribution copy
python -m research_tool publish "Acme Inc" --format pdf
```

Default formats/author/status come from the `papers:` section of
`config.yaml`.

## 9. PDF quality standard

A library PDF must read as a research paper, not as a database dump:

- title block (title, subtitle, author, date, keywords) and an abstract box;
- numbered prose sections with justified body text;
- booktabs-style tables (header rule, wrapped cells, numeric alignment);
- **visuals where they help**: KPI panels, bar/line charts, shaded heatmaps,
  timelines and flow diagrams (see §11);
- running header on continuation pages, footer with "Page X of Y";
- a formal reference list; inline citations such as `[1]`, `[2]`;
- no `engine=... | category=...` debug strings, no raw Markdown syntax, no
  bare URLs interleaved with prose, no repeated boilerplate sections.

The typesetting engine (`research_tool/reporters/academic_pdf.py` and
`research_tool/reporters/charts.py`) enforces this for every
`publish --format pdf` and for `PaperReporter.render_pdf`.

## 10. Visual devices (fenced chart blocks)

A manuscript may use five fenced blocks; each renders as a print-quality
figure rather than as text. Put the caption inside the fence so it is typeset
as a figure caption.

| Fence | Renders as | Shape |
|---|---|---|
| `chart-stats` | KPI panel: large figures on cards | `\| value \| label \|` rows (no header) |
| `chart-bars` | ranked **horizontal** bars, value at each bar end | header row, then `\| label \| number \|` rows |
| `chart-line` | annotated trend line: markers + value labels | header row, then `\| category \| number \| [number] \|` rows |
| `chart-heatmap` | shaded intensity matrix + colour-scale legend | header row, then `\| label \| 0-3 \| ... \|` rows |
| `chart-timeline` | dated milestones on a node rail | `\| date \| event \|` rows (no header) |

Keys (inside the fence, before or after the table): `title:`, `caption:`
(always cite the source in it), `note:` (a caveat line), `columns:` (KPI panel
width), plus the three that make a figure readable:

| Key | Effect |
|---|---|
| `benchmark: 25` | draws a labelled dashed reference line (e.g. the 25 percent female-player baseline, or the 50 percent reform threshold) |
| `invert: true` | plots larger values lower - use it for a "lower is better" series such as a grossing rank, so a decline slopes downwards |
| `suffix: %` | appends a unit to every value and axis label |

A Mermaid `flowchart` fence renders as a numbered step flow with an explicit
relations line.

Example (a ranked comparison with a reference line):

````
```chart-bars
title: Female share of players by franchise (percent)
benchmark: 25
| Franchise | Female |
| Genshin Impact | 45 |
| Blue Archive | 10 |
```
caption: Figure 1. Against a 25 percent baseline, mixed-cast anime RPGs
over-index women while male-coded titles do not [2].
````

Editorial rules: a figure must add information a reader cannot get faster from
prose; every caption states the takeaway and carries its citation; do not print
the same dataset twice in a row as a table and then a figure - give the figure
a derived view (a trend, a ranking, a benchmark comparison) instead; and numbers
in a figure must match the sources cited in the text.

Figures are typeset by `research_tool/reporters/charts.py` (PDF) and rendered as
inline SVG or shaded tables by `research_tool/utils/github.py` (the hosted
site), so the two always agree.

## 11. Retention & privacy

- `python -m research_tool purge` targets `data/raw/` and never deletes the
  paper shelves by default — papers are deliverables, not cache.
- `purge --include-papers` explicitly includes them. It always preserves this
  rules file and `_templates/`; run
  `python -m research_tool papers --rebuild-index` afterwards.
- `--ephemeral` runs cannot publish: publishing is an explicit write to disk.
- Never store API keys, passwords or live credentials in a paper.