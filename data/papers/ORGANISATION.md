# Finalized Research Paper Library — Organisation Rules

**Purpose.** This folder holds *finalized research papers* — the curated,
citable end product. It does **not** hold raw engine output. The two output
locations are deliberately separate:

| Location | Holds | Lifecycle |
|---|---|---|
| `data/reports/` | raw findings / engine output (`--format` on any command) | transient; eligible for `purge` |
| `data/papers/` | finalized, curated papers (this folder) | durable deliverables |

Reports answer *"what did the engines find?"*. Papers answer *"what did we
conclude, on what evidence, and when?"* Publish a paper only after reviewing
the report.

---

## 1. Layout (do not invent new top-level folders)

```
data/papers/
├── INDEX.md / INDEX.json      # auto-generated catalogue — never hand-edit
├── ORGANISATION.md            # this rules file
├── _templates/                # authoring template
│   └── TEMPLATE_research_paper.md
├── _archive/                  # superseded or withdrawn papers
│   └── <topic>/
└── <topic>/                   # one shelf per topic
    ├── <paper-id>.md
    ├── <paper-id>.pdf
    ├── <paper-id>.json
    └── <paper-id>.meta.json   # catalogue record (required)
```

Topic shelves are single folder names. The defaults are:

| Target kind | Shelf |
|---|---|
| `name`, `email`, `username` | `people` |
| `domain`, `url`, `ip`, `onion` | `domains` |
| anything else / mixed research | `general` |

Use a custom shelf with `--topic <name>` for research programmes
(e.g. `--topic nightfall`). Shelves are lower-kebab-case (`slugify`d).
Never nest shelves (`people/politicians`) and never put loose files in the
library root.

## 2. Naming rules

```
<paper-id>.<ext>          <paper-id> = <slug>_<YYYY-MM-DD>[_vN]
<paper-id>.meta.json
```

- `<slug>` is the target, transliterated to lower-kebab ASCII
  (`"Jane Doe"` → `jane-doe`; `"Kim Jong-un"` → `kim-jong-un`; non-Latin
  targets fall back to `paper-<hash8>`).
- `<YYYY-MM-DD>` is the **publication date (UTC)**, not the research date.
- Re-publishing the same target on the same date creates `_v2`, `_v3`, …
  Nothing is overwritten.
- A new publication date is a new paper ID. Archive the older version (§4).
- Extensions: `.md` (primary), `.pdf` (distribution), `.json`
  (machine-readable, includes the raw report). Never `.docx`/`.xlsx` here —
  those belong in `data/reports/`.

## 3. Metadata record (`.meta.json`)

The toolkit writes one record beside every paper. It is the catalogue source
of truth; keep it next to the documents and never rename it by hand.

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
| `files` | document files relative to this folder |
| `source_report` | raw JSON report the paper was finalized from |

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

When a newer paper supersedes an older one, archive the older version and
keep the newer one active. The index shows both states separately.

## 5. Index rules

- `INDEX.md` and `INDEX.json` are **auto-generated** from the `.meta.json`
  records. Never edit them by hand.
- They are rebuilt by every `publish`, every `archive-paper`, and:
  `python -m research_tool papers --rebuild-index`.
- If a record is malformed the rebuild logs a warning and skips it; fix the
  record (or delete it) and rebuild.
- Never bypass the index by copying papers in by hand. If you must import an
  external document, create a record with `publish --from <report.json>` so
  it is findable.

## 6. Publishing checklist (paper = final only when all true)

- [ ] Raw report exists in `data/reports/` (or is embedded in a paper JSON).
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
python -m research_tool papers --topic people           # one shelf
python -m research_tool papers --query "nightfall"      # free-text search
python -m research_tool papers --status draft           # review queue
python -m research_tool papers --archived               # archive
python -m research_tool papers --rebuild-index          # repair the index
```

You can also browse `INDEX.md` directly, or filter `INDEX.json` in scripts.

## 8. Publishing recipes

```powershell
# Research and finalize in one run (writes a .md paper + record + index)
python -m research_tool publish "Jane Doe" --engines search,academic `
    --tags osint,credential --topic people

# Finalize an existing raw report (no engines re-run) as PDF + Markdown
python -m research_tool full example.com --format json
python -m research_tool publish --from data/reports/report_example.com.json `
    --format markdown,pdf --status final

# Distribution copy
python -m research_tool publish "Acme Inc" --format pdf
```

Default formats/author/status come from the `papers:` section of
`config.yaml`.

## 9. Retention & privacy

- `python -m research_tool purge` **never** deletes `data/papers/` by
  default — papers are deliverables, not cache.
- `purge --include-papers` explicitly includes them (with the same
  overwrite-before-unlink treatment). It always preserves this rules file and
  `_templates/`; run `python -m research_tool papers --rebuild-index`
  afterwards so the catalogue matches what remains.
- `--ephemeral` runs cannot publish: publishing is an explicit write to disk.
- Never store API keys, passwords or live credentials in a paper. Findings
  may quote public exposure, but do not reproduce secret values.