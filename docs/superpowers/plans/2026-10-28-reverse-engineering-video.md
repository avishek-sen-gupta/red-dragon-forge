# Reverse-Engineering Video Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Everything the user needs to record the reverse-engineering video: a frozen CardDemo artifact run, a generic artifact-answering Claude Code skill (with the one helper it needs), and the narrative plus per-segment scripts.

**Architecture:** The skill is tracked at `cobble/skills/cobble-artifacts/` and copied into `.claude/skills/` by `make skills`: prose that maps each artifact to the questions it answers and the query tools that read it, plus judgement rules. Byte-exact copy walking is the one thing an agent cannot do by hand over a 15k-node graph, so it becomes a tested cobble CLI. The video material is Markdown under `docs/presentation/video/`, one file per segment, each naming exact commands and the artifact page to open.

**Tech Stack:** Python 3.13, uv, pytest, Pydantic (cobble); Markdown; existing capture scripts under `docs/presentation/capture/`.

**Spec:** `docs/superpowers/specs/2026-10-28-reverse-engineering-video-design.md`

## Global Constraints

- CardDemo identifiers only; no client or proprietary identifiers in any tracked file.
- No new pipeline features for the video; the copy-walk CLI is the skill's helper and reads existing artifacts only.
- Every explainer carries a concrete CardDemo example (COBOL, a tree, a graph, a row).
- The skill answers from artifacts; source is quoted only to confirm a conclusion, minimally.
- The skill is generic: Q1 and Q2 are examples, not hard-coded procedures.
- One frozen artifact run backs the scripts and the skill; it is not committed.
- Repo gates apply: Black, Pyright strict, import-linter, python-fp-lint, no comments beyond one-line headers, frozen dataclasses, no `Any`/`object`.

## Review Focus

1. A walk start that names no node in the graph — the CLI should exit non-zero naming the missing id, not print an empty answer. (Task 2 test.)
2. A start node holding fewer bytes than `--width` — refuse it, since the window cannot fit. (Task 2 test.)
3. A REDEFINES pair across record variants (same bytes, sibling layouts) — must not be aliased; only a direct `REDEFINES` is. (Task 2 test.)
4. The frozen run directory renamed or regenerated after the scripts were written — every script names one variable for it, so one edit fixes all. (Task 3 check.)
5. The skill asked something no artifact answers (e.g. runtime values) — it says which artifact would be needed rather than reading source. (Task 1 check.)

---

### Task 1: The artifact-answering skill

**Files:**
- Create: `cobble/skills/cobble-artifacts/SKILL.md`; `make skills` copies it to `.claude/skills/`

**Interfaces:**
- Consumes: the CLI from Task 2 (`cobble-experimental-partition-copies`), the existing query tools.
- Produces: a skill named `cobble-artifacts`, invocable in this repo.

- [ ] **Step 1: Write `SKILL.md`** with frontmatter `name: cobble-artifacts` and a description that triggers on questions about a corpus's programs, fields, files, screens, flows or impact when a cobble output directory exists. Sections:
  - **Artifact catalog** — one row per artifact `tools/rebuild-all.sh` writes (`extents.jsonl`, `fixpoint/`, `combine/links.jsonl` and `targets.jsonl`, `knowledge-graph.jsonl`, `srccfg/cfg-*.jsonl`, `accesses/`, `depgraph/`, `bms/metadata.json`, `graph.jsonl`, `render/`, `aggregates/`): what it holds and which question it answers.
  - **Query tools** — `cobble-trace-query`, `cobble-dataflow-fixpoint-query` (each subcommand), `cobble-srccfg-query`, `cobble-access-query`, `cobble-experimental-partition-copies`; one usage line each, run with `uv run --no-sync` from `cobble/`.
  - **Judgement rules**, each with its CardDemo example: commarea bytes in vs out (links extents; the menu takes 218, passes 160); a field and its direct `REDEFINES` are one location, sibling record variants are not; `rebuilt` edges are not copies; `~` marks a clamped (computed-subscript) write; keys (`RIDFLD`, `KEY IS`, `RECORD KEY`) select records and are not data flow — their facts are in the ASGs; "overlapping-layouts" dataset edges need the writer and reader layout compared by field path and offset.
  - **Method examples** — Q1 and Q2 as worked examples, copied from the spec's method section.
  - **Answer format** — the answer, the chain of evidence (artifact and row for each step), and which steps needed judgement.
- [ ] **Step 2: Check** — in a fresh session at the repo root, ask Q1 against the frozen run (Task 3). Expected: the answer names `ACCT-CURR-BAL`, the account file and the four writer programs, cites artifacts for each step, and quotes no source. Then ask "what is the runtime value of the balance for account 1?" Expected: it says no artifact holds runtime values.
- [ ] **Step 3: Commit** with Task 2 (one feature, one commit).

### Task 2: The copy-walk helper

**Files:**
- Create: `cobble/cobble/experimental/partition/copies.py`, `cobble/cobble/experimental/partition/copies_cli.py`
- Modify: `cobble/pyproject.toml` (script `cobble-experimental-partition-copies = "cobble.experimental.partition.copies_cli:main"`)
- Test: `cobble/tests/experimental/partition/test_copies.py`

**Interfaces:**
- Consumes: `read_graph(path) -> FieldGraph` (`graph_file.py`), `GraphNode`, `GraphEdge`; `extents.jsonl` rows with `program`, `names`, `redefines`.
- Produces: `copies(graph: FieldGraph, redefines: Mapping[tuple[str, str], str], starts: Sequence[str], width: int) -> tuple[Copy, ...]`, where `Copy` is a frozen dataclass `(node: str, base: int)` (`node` holds all `width` bytes starting at `base`). CLI: `--graph`, `--extents`, `--width`, one or more `--start NODE_ID`; prints one `node+base` per line, grouped by program.

- [ ] **Step 1: Write the failing test** `test_a_value_is_followed_byte_by_byte_through_copies_and_their_feeders` on a hand-built `FieldGraph`: a 4-byte dataset slot `D[0:4]` → `P:A` (alignment 0,0,4); `P:A` → `P:BUF` (8 bytes, alignment 0→2, length 4); `P:BUF` → `Q:C` (alignment 2→0, length 4); `P:IN` → `P:A` (feeder); `P:OTHER` → `P:BUF` at bytes 4..8 (must not appear); a `rebuilt` edge `P:A` → `P:SUM` (must not appear); `P:A-N` directly REDEFINES `P:A` (must appear); `P:V2` shares `P:A`'s bytes as a sibling variant without REDEFINES (must not appear). Assert `copies(...)` equals exactly `{D[0:4]+0, P:A+0, P:A-N+0, P:BUF+2, Q:C+0, P:IN+0}`.
- [ ] **Step 2: Write** `test_a_start_the_graph_lacks_or_too_small_for_the_width_is_refused`: assert `SystemExit` with the id in the message for a missing start, and for a 2-byte start with `width=4`.
- [ ] **Step 3: Run** `cd cobble && uv run --no-sync python -m pytest tests/experimental/partition/test_copies.py -q`. Expected: FAIL (module missing).
- [ ] **Step 4: Implement** `copies` in `copies.py`: per-byte state `(node, offset, start_byte)`; a forward pass over edges with alignments (any node size), then a backward pass from forward-reached nodes no larger than `width` (never entering larger nodes); skip `rebuilt`; a direct `REDEFINES` pair is a zero-offset link both ways; any dataset node reached becomes a new start, repeated until nothing new. A node is reported when all `width` bytes arrive at one `base`; single-byte table elements are omitted. Then the CLI in `copies_cli.py`, parsing `extents.jsonl` rows with a Pydantic model.
- [ ] **Step 5: Run** the test, then on the frozen run with the spec's five card-number slots and `--width 16`. Expected: PASS, and about 90 places, none of them a transaction or user id.
- [ ] **Step 6: Commit** Tasks 1 and 2 together: `feat(cobble): an artifact-answering skill and the byte copy walk it uses`.

### Task 3: Frozen run, narrative and segment scripts

**Files:**
- Create: `docs/presentation/video/README.md` (narrative and segment order), `docs/presentation/video/01-opening.md`, `02-pipeline.md`, `03-runtime.md`, `04-interpretation.md`, `05-close.md`

- [ ] **Step 1: Freeze the run** — after Tasks 1–2 land, `make carddemo-all`; put its directory in `README.md` as `RUN=cobble/out-carddemo-…` and refer to `$RUN` everywhere else.
- [ ] **Step 2: Write `README.md`** — the one idea; the five segments in order with a target length each, totalling about an hour; prerequisites (bridge JARs, Db2 for the headless Db2 test, c3270 and vhs for the CardDemo clip).
- [ ] **Step 3: Write each segment file** with: on-screen actions, talking points, exact commands, the artifact page to open, and where an explainer goes.
  - `02-pipeline.md` follows `tools/rebuild-all.sh` stage by stage; explainers: AST after parse, CFG after the CFG build (one program), data-flow analysis before the fixpoint (fixpoint as the means), NMF with the aggregates. Minor stages get one line each. BMS maps are shown.
  - `03-runtime.md` reuses `docs/presentation/capture/headless.sh` and `carddemo_3270_video.sh`.
  - `04-interpretation.md` asks Q1 and Q2 through the skill; notes that takes differ; names the limits to say aloud (multi-layout files, computed subscripts, keys).
- [ ] **Step 4: Check** — run every command in every segment against `$RUN`; each must succeed and each named page must exist. Grep the files for client identifiers (none) and test counts (none).
- [ ] **Step 5: Commit** `docs(presentation): video narrative and segment scripts`.
