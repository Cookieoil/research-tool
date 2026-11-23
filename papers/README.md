# Research Papers — Read Me First

Everything you need to read is in this folder. Nothing here is raw machine
output; raw engine results live in `../data/raw/`.

## Where to go

| I want to… | Open |
|---|---|
| Read a finished paper as a PDF | **`pdfs/`** — every active PDF, named by title |
| Open a specific research programme | **`vietnam/`** or **`gacha/`** — manuscripts (`.md`) and PDFs |
| See what exists, by shelf, date and status | **`INDEX.md`** (auto-generated) |
| Know the filing rules | **`ORGANISATION.md`** |
| Start a new paper | **`_templates/TEMPLATE_research_paper.md`** |
| Find a superseded version | **`_archive/<topic>/`** |

## The two shelves

- **`vietnam/`** — the Vietnam research programme: the consolidated monograph
  *Export Factories and Controlled Liberalisation*, plus the eleven underlying
  studies (industrial policy, game-industry forecast, impact, policy rationale,
  actors, motive map, reform, regulator, series synthesis, scorecard).
- **`gacha/`** — the female-oriented gacha market programme: the synthesis
  *Latent Demand and Execution Failure*, the evidence review *Why Women Play
  "Male-Oriented" Gacha Games*, and the *Reign of Nightfall* post-mortem.

## Conventions in one breath

- `<slug>_<YYYY-MM-DD>[_vN].md` is the manuscript; the sibling `.pdf` is its
  typeset edition.
- `.meta.json` records live in `_meta/<topic>/` with the machine-readable
  `.json` copy, so the shelves stay readable.
- `INDEX.md`, `INDEX.json` and `pdfs/` are generated — do not hand-edit.
- Papers are written in English, every claim carries a source, and
  probabilities are labelled as judgements.

## Commands

```powershell
python -m research_tool papers                       # list active papers
python -m research_tool papers --topic vietnam       # one shelf
python -m research_tool papers --query "decree 147"  # search
python -m research_tool papers --rebuild-index       # rebuild index + pdfs/
python -m research_tool archive-paper <paper-id>     # supersede a paper
```

Originating drafts and raw inputs (the original PDFs the gacha papers were
rewritten from, plus the raw report JSON) are preserved under
`../data/sources/`.