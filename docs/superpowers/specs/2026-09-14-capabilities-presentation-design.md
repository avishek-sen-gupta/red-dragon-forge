# Capabilities Presentation — Design

## Purpose

A 45-minute RevealJS deck (~35 slides) for mainframe-modernization stakeholders showing what
RedDragon, RedDragonForge (CICS, JCL, SQL) and Cobble can do. Every capability claim is
backed by an artifact captured from a real run in this repo, or a figure cited from an
analysis doc.

## Narrative: one application, end to end

CardDemo is the throughline. Production-corpus evidence appears anonymised ("a production
estate") — no client, system, or program-family names.

| # | Section | Slides | Evidence |
|---|---|---|---|
| 1 | The problem — logic locked in mainframe estates; costly to understand, test, migrate | 3 | — |
| 2 | Meet CardDemo | 2 | Corpus stats from the Cobble graph (programs, jobs, transactions, maps, datasets) |
| 3 | Understand it without running it (Cobble) | 6 | Whole-system graph; call graph + sequence diagram; field-level dataflow across programs; BMS screens rendered from source |
| 4 | The engine (RedDragon) | 4 | Source → IR → CFG → VM pipeline; COBOL feature coverage (COMP-3, edit pictures, REDEFINES/OCCURS, file I/O, CALL); extension seams — CICS/SQL never touch the core VM |
| 5 | Run it online (CICS) | 6 | Sign-on → menu → account view as captured screens; pseudo-conversational dispatch; VSAM KSDS reads; supported verb surface |
| 6 | Run it in batch (JCL) | 4 | ACCTFILE → READACCT job log with step RCs; PROC expansion, COND, referbacks; IDCAMS |
| 7 | Talk to Db2 (SQL) | 4 | Unmodified IBM Bank-of-Z INQCUST: CICS LINK + EXEC SQL against live Db2; SQL surface (cursors, WHENEVER, DCLGEN) |
| 8 | Scale evidence (anonymised) | 3 | 2,137-program estate: compile/run outcome; JCL utility frequency across 860 members / 12,267 steps |
| 9 | Honest gaps and roadmap | 2 | SORT/MERGE, IEBGENER/IEBCOPY/ICETOOL, GDG execution, non-executing IDCAMS verbs, SQL parsed-vs-executed; JCL roadmap table |
| 10 | Close — what this unlocks | 1 | Test harnesses, migration equivalence checking, estate documentation |

Every slide carries speaker notes naming its evidence source (artifact path or doc path).

## Layout

```
docs/presentation/
  index.html            # the deck
  theme.css             # dark theme, palette shared with RedDragon's existing decks
  vendor/reveal.js/     # pinned reveal.js dist (css, js, notes plugin) — offline
  artifacts/            # captured outputs, committed
    cobble/  cics/  jcl/  sql/
  capture/              # one script per section
  Makefile              # `make artifacts` regenerates artifacts/
```

Artifacts are committed so the deck opens anywhere without the bridge JARs, Db2 or CardDemo.
`make artifacts` is the reproducibility path, not a prerequisite for presenting.

## Capture

| Section | Source | Output |
|---|---|---|
| Cobble | `make parse`/`make build` on `config/carddemo.toml`; `cobble-render`, `cobble-viz-*`, `cobble-bms-render` | Graph/callgraph/sequence/dataflow HTML + PNG screenshots; empty-map screens; stats JSON |
| CICS | Script drives `CicsRegion` (sign-on → menu → account view) with scripted `InputEvent`s against seeded VSAM; drains the screen channel to `{map, fields}` JSON per turn | Payload JSON + `cobble-bms-render --format html` screens |
| JCL | `python -m jackal run` on ACCTFILE.jcl then READACCT.jcl | Job log text (step, RC, ran) + produced dataset excerpt |
| SQL | `tests/integration/test_inqcust_e2e.py` path against Docker Db2 | Program output + fetched row excerpt |
| Scale, gaps | `docs/analysis/2026-09-01-index-items-search-and-cics-verb-gaps.md`, `docs/analysis/2026-09-02-jcl-utility-and-argument-frequency.md`, `jackal/docs/jcl-execution-roadmap.md` | Inline SVG charts / tables in the deck |

Capture scripts import only the one package they drive, preserving package independence;
Cobble renders runtime screens from JSON, not by importing cicada.

## Rules

- **No unrun claims.** If a capture fails, its slide states what is missing; it is never mocked.
  The sample-value account-view render from the renderer spike is not used.
- **Traceable numbers.** Every figure maps to a committed artifact or a cited doc (in speaker notes).
  Stale analysis (e.g. the 2026-07-09 CardDemo job executability survey) is re-checked before use.
- **Gaps are slides, not footnotes.**
- **Anonymisation** — production-estate names never appear; the terminology guard backs this at commit.
- **Verify SEARCH ALL** before presenting it as binary search (design doc says linear scan).

## Verification

- Each capture script exits non-zero on failure; `make artifacts` stops on the first failure.
- Open the deck in a browser (local HTTP server) and screenshot every slide; check layout at
  1920×1080 and that no artifact is missing or overflowing.
- Speaker notes checked for a source on every evidence slide.

## Out of scope

Live demos during the talk, a published web copy, a mixed-audience technical deep dive.
