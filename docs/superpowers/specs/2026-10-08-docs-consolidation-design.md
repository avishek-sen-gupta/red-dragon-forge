# Docs consolidation — design

## Goal

Make the forge's documentation:

- live in one tree (`docs/`), not five;
- reachable from one index, with sub-indices for the record collections;
- free of ephemeral measurements (test counts, timings, node counts, corpus sizes);
- plain and concise: no history narration, aphorisms or emphasis-for-effect;
- actionable: every how-to is a straight sequence of commands with expected results.

Agent instructions (`CLAUDE.md`, `AGENTS.md`, `guidelines/`) stay at the root. Package-level
agent files are removed once their package-specific content is placed elsewhere.

## Decisions

| Question | Decision |
|---|---|
| Layout | Centralise every doc under root `docs/`. Package directories keep only a short README. |
| Records | `docs/superpowers/{specs,plans}` stays where the superpowers skills write; package records move into a package subfolder there. Other frozen records go to `docs/records/{design,analysis}`. |
| Presentation | `docs/presentation/` stays put. It is a build (Makefile, capture scripts, hardcoded paths), not a record. |
| Status documents | Kept as living roadmaps under `docs/roadmaps/<package>.md`. Cobble's two trackers merge into `cobble.md`. |
| Package agent files | Deleted. Everything they say is either already in `guidelines/`, is how-to/reference content that moves to `docs/`, or is one of the two rules below. |
| jackal grammar-first rule | Kept: "jackal parses JCL and IDCAMS by grammar, never regex" goes into `guidelines/project/workflow.md`. The three current `re` usages (`jackal/tso.py`, `jackal/idcams/preprocess.py`, `jackal/idcams/ast_values.py`) are filed as a bead. |
| Interpreter issues | Filed in red-dragon's own beads DB (`bd -C <red-dragon clone> create …`), not the forge's. Added to `guidelines/project/workflow.md`. |
| `PHILOSOPHY.md` | One copy at `docs/philosophy.md`, linked from the index. The four package copies (identical) are deleted. |

## Target tree

```
README.md                  what the forge is, 3-step quickstart, link to docs/README.md
docs/
  README.md                index of every how-to, reference page, roadmap, explainer; links to sub-indices
  philosophy.md
  how-to/
    setup.md               fresh clone → make setup → bridge-env → beads init
    run-tests.md           the gate, each package's suite, what needs Db2 / the JARs
    db2.md                 up, seed, status, restart, clean, memory troubleshooting
    run-carddemo.md        CICS over tn3270, with and without Db2
    run-jcl-job.md         jackal CLI
    analyse-a-corpus.md    cobble end to end
  reference/
    forge/architecture.md
    cicada/architecture.md, tn3270-config.md, cicada-architecture.html, conversational-suspend-resume.html
    squall/architecture.md
    jackal/architecture.md, cli.md, idcams-ref.pdf
    cobble/config.md, knowledge-graph.md, srccfg.md, field-dataflow.md, trace.md, diagnostics.md, viz.md
  roadmaps/cicada.md, jackal.md, cobble.md
  explainers/              unchanged
  presentation/            unchanged
  superpowers/
    README.md              index of specs and plans, by package
    specs/  (forge)  cicada/  squall/  jackal/  cobble/
    plans/  (forge)  cicada/  squall/  jackal/  cobble/
  records/
    README.md              index of design records and analyses
    design/
    analysis/
cicada/README.md, squall/README.md, jackal/README.md, cobble/README.md
                           ~5 lines each: what the package is, link to its reference page
```

## Source → destination

### Moved unchanged (`git mv`; content frozen)

| Source | Destination |
|---|---|
| `cicada/docs/superpowers/{specs,plans}/*` | `docs/superpowers/{specs,plans}/cicada/` |
| `squall/docs/superpowers/{specs,plans}/*` | `docs/superpowers/{specs,plans}/squall/` |
| `squall/docs/plans/*` | `docs/superpowers/plans/squall/` |
| `jackal/docs/superpowers/{specs,plans}/*` | `docs/superpowers/{specs,plans}/jackal/` |
| `cobble/docs/superpowers/{specs,plans}/*` | `docs/superpowers/{specs,plans}/cobble/` |
| `docs/design/*` | `docs/records/design/` |
| `squall/docs/design/*` | `docs/records/design/` |
| `docs/analysis/2026-*.md` | `docs/records/analysis/` |
| `jackal/docs/analysis/*` | `docs/records/analysis/` |
| `cicada/docs/cicada-architecture.html` | `docs/reference/cicada/` |
| `cicada/docs/design/conversational-suspend-resume.html` | `docs/reference/cicada/` |
| `docs/idcams-ref.pdf` | `docs/reference/jackal/` |
| `cicada/PHILOSOPHY.md` | `docs/philosophy.md` |

Three frozen records contain relative links that the move breaks. They stay unedited; the
indices point at the correct locations.

### Rewritten into new pages

| Source | Destination |
|---|---|
| `README.md` | `README.md` (short), `docs/how-to/setup.md`, `run-tests.md`, `run-carddemo.md`, `docs/reference/forge/architecture.md` |
| `docs/db2-container-memory.md`, Db2 sections of `squall/CLAUDE.md` and `cicada/README.md` | `docs/how-to/db2.md` |
| `cicada/README.md`, `cicada/CLAUDE.md` (layout, invariant) | `docs/reference/cicada/architecture.md`, `tn3270-config.md`, `docs/how-to/run-carddemo.md` |
| `squall/README.md`, `squall/CLAUDE.md` (layout, invariants, seam) | `docs/reference/squall/architecture.md` |
| `jackal/README.md` | `docs/reference/jackal/architecture.md`, `cli.md`, `docs/how-to/run-jcl-job.md` |
| `cobble/README.md` | `docs/how-to/analyse-a-corpus.md`, `docs/reference/cobble/*` |
| `cicada/docs/cics-production-roadmap.md` | `docs/roadmaps/cicada.md` |
| `jackal/docs/jcl-execution-roadmap.md` | `docs/roadmaps/jackal.md` |
| `cobble/docs/outstanding-issues.md`, `cobble/docs/corpus-onboarding-blockers.md` | `docs/roadmaps/cobble.md`. Resolved items are dropped; open items become beads and are listed by ID. |
| `AGENTS.md` | `AGENTS.md`, deduplicated. Its fresh-clone steps defer to `guidelines/project/workflow.md`. |

### Deleted

- `cicada/CLAUDE.md`, `squall/CLAUDE.md`, `jackal/CLAUDE.md`
- `cicada/AGENTS.md`, `jackal/AGENTS.md`
- the other three `PHILOSOPHY.md` copies
- `jackal/.claude/`, `cicada/.agents/`, `jackal/.agents/`, `cicada/.codex/`, `jackal/.codex/`
- `squall/tests/oracle/README.md` (describes an oracle not in the tree)
- `docs/analysis/cobble-srccfg-build-set-statement-bug.md`, filed as an issue in red-dragon's beads DB

### Links to fix in living files

- `guidelines/project-context.md` → `docs/records/design/2026-09-09-package-boundaries.md`
- Any README, how-to or reference page that links to a moved file.

## Content rules

**How-to pages.**
- Prerequisites first, then numbered steps, one command block per step.
- Commands run from the repo root unless a step says `cd`.
- Each step states its expected result.
- No explanation inside the steps. A "Why" or "Troubleshooting" section follows only when needed.

**Reference pages.**
- What the code does now: modules, entry points, flags, config keys, invariants. Tables where tabular.
- No history: no "now", "no longer", "used to", "previously", "replaced", "since <commit>".
- No measurements that change with the code or corpus.

**Roadmaps.**
- One table per package: item, issue ID, status (supported / partial / not started).
- No dates, no "last updated".

**Indices.**
- `docs/README.md` links every page under `how-to/`, `reference/`, `roadmaps/`, `explainers/`, plus `philosophy.md` and the two sub-indices.
- `docs/superpowers/README.md` and `docs/records/README.md` list each record with one line, grouped by package.

**Prose.**
- Short plain sentences.
- No aphorisms, no intensifiers ("load-bearing", "crucially", "sharp"), no bold for emphasis in running text.
- No external-codebase identifiers (`data-security.md`). Check every merged tracker for them before committing.

## Accuracy fixes carried into the rewrite

These come from the audit. They must not survive into the new pages.

- jackal: `python -m jackal` does not run; the command is `uv run --no-sync jackal`. jackal requires Python 3.13. `jcl_graph.py`/`cobol_file_graph.py` are in `cobble/cobble/jcl/`.
- cicada: the flow-graph code is in `cobble/cobble/cics/`. The verb table includes START, RETRIEVE, SYNCPOINT [ROLLBACK], HANDLE/IGNORE CONDITION and BIF DEEDIT. The tn3270 config has four tables.
- cobble:
  - cobble imports jackal, cicada, squall and `cobol_asg`.
  - `cobble-parse-corpus` requires `PROLEAP_BRIDGE_JAR`.
  - `cobble-srccfg-build` takes a `[srccfg]` config, copied from `config/srccfg.example.toml`.
  - There is no `[fields]` table.
  - `cobble-bms-render` requires `--out-dir`.
  - The depgraph config shape is documented.
  - Undocumented flags are documented.
- root: the Db2 recipe starts with `make db2-up`; `make test` runs only the root suite (Makefile help text too).
- squall: Db2 is the primary backend; `make db2-status` and `make db2-seed` are documented.
- Code bug, own commit: `red_dragon_forge/db2_status.py` and the Makefile comment name a non-existent `--reset-schema` flag; they should say `make db2-seed`.

## Verification

- **How-tos:** every command is run in a scratch shell. Steps needing Db2 or a tn3270 terminal are run if Db2 is up; otherwise they are listed as unverified in the commit message.
- **Links and paths:** a scratch script resolves every relative link and backticked path in living docs. It is not committed.
- **Banned words and numbers:** a grep over living docs for history words ("no longer", "used to", "previously", "historically", "now ") and for numerals, each hit reviewed.
- **Coverage:** every file under `docs/` is reachable from `docs/README.md`.
- **Gate:** the normal pre-commit gate runs on every commit.

## Commit

One commit: the moves, the rewrites, the deletions, the guidelines additions and the
`db2_status.py` message fix together. No implementation plan document.
