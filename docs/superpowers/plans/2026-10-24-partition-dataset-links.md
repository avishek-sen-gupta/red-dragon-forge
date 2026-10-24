# Partition Dataset Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Link file write sites to file read sites in the partition graph through dataset slot nodes, each link `exact` or `possible` with reasons, and let unify join fields across programs through exact links.

**Architecture:** A pure resolution step turns each trace file site into a `DatasetSite` (dataset identity, certainty, reasons) from the knowledge graph and the combine's `targets.jsonl`. A second pure step cuts each dataset's record into slots and emits slot nodes and field↔slot edges, merged into the existing `FieldGraph` after `field_graph` runs. Unify treats slots as byte relays; the page draws them.

**Tech Stack:** Python 3.13, Pydantic v2 frozen models, networkx, pytest; sigma.js page template.

**Spec:** `docs/superpowers/specs/cobble/2026-10-24-partition-dataset-links-design.md`

## Global Constraints

- Code lives in `cobble/cobble/experimental/partition/` (and `cobble/cobble/experimental/aggregates/exact_merge.py`); tests in `cobble/tests/experimental/partition/` and `cobble/tests/experimental/aggregates/`.
- One class per file; frozen dataclasses or `ConfigDict(frozen=True, extra="forbid")` models; no comments beyond a one-line module/class header; no loops with mutation; Pyright strict; python-fp-lint.
- No function over 3–4 parameters: `field_graph`'s signature does not change; dataset edges are merged by a separate function.
- No heuristics: no copybook or field-name joins, no `VALUE`-clause fallback; batch step attribution only through `JCL_STEP_RUNS`, `TSO_RUNS_PROGRAM` and `CALL`/`CALL_CANDIDATE` chains.
- The trace's `FILE:` terminal text is parsed once, in the site reader, into a typed value; nothing downstream inspects the string.
- Fail-safe: without `--knowledge-graph` the graph file is byte-identical to today's; without `--targets` batch links are still made and CICS sites get none. Each absent input is logged by name.
- Docs `docs/reference/cobble/partition.md` and `docs/reference/cobble/aggregates.md` change in the commit that changes the behaviour they describe. No test counts in docs.
- CardDemo, bank-of-z and NIST may be named; no other corpus.
- Commit through the hooks only; never `--no-verify`.

## Rulings Against the Spec

- CICS sites read the combine's `targets.jsonl` (`$(PARTITION_DIR)/combine/targets.jsonl`), not the fixpoint's: same schema, and the combine also resolves names that arrive from another program.
- The page's component colouring comes from per-program clusters and stays so; "follow the chain across programs" (spec Goal 5) is delivered as the click-to-select dataset chain in Task 5.

## Review Focus

1. A site that appears in many dep rows (one per path or field) is one site: it produces one set of slot edges, not duplicates — Task 1 test `test_repeated_dep_rows_are_one_site`.
2. Writer and reader records of different lengths: slots past the shorter record have edges on one side only, and no error — Task 2 test asserts it.
3. A file site matching neither a `kind: file` target nor a select name (e.g. a CICS literal operand) gets a `possible: unresolved-file` slot of its own, never a crash — Task 1 test asserts it.
4. A clamped record extent (`exact` False) never yields an `exact` edge — Task 2 test asserts `possible: clamped`.
5. Running the graph CLI without the new flags gives the same `graph.jsonl` as before — Task 3 test compares bytes.

---

### Task 1: Resolve file sites to dataset identities

**Files:**
- Create: `cobble/cobble/experimental/partition/certainty.py` — `class Certainty(StrEnum)`: `EXACT = "exact"`, `POSSIBLE = "possible"`
- Create: `cobble/cobble/experimental/partition/file_site.py` — `@dataclass(frozen=True) class FileSite`: `program: str`, `site: str`, `file: str`, `record: ByteRange`, `writes: bool`
- Create: `cobble/cobble/experimental/partition/dataset_site.py` — `@dataclass(frozen=True) class DatasetSite`: `use: FileSite`, `identity: str`, `certainty: Certainty`, `reasons: tuple[str, ...]`, `resolved: bool`
- Create: `cobble/cobble/experimental/partition/dataset_resolution.py`
- Test: `cobble/tests/experimental/partition/test_dataset_resolution.py`

**Interfaces:**
- Produces: `file_sites(deps: Sequence[DepRow]) -> tuple[FileSite, ...]`; `dataset_sites(sites: Sequence[FileSite], graph: KnowledgeGraph, targets: Sequence[TargetSite]) -> tuple[DatasetSite, ...]`; `@dataclass(frozen=True) class KnowledgeGraph` (in `knowledge_graph_view.py`, one class per file) with `edges: tuple[GraphEdge, ...]` from `cobble.knowledge_graph.graph_types`, built by `knowledge_graph(path: Path) -> KnowledgeGraph` via `cobble.knowledge_graph.graph_file.read_graph`.
- Consumes: `DepRow` (`cobble.dataflow.fields.trace_query`), `TargetSite` (`cobble.dataflow.fixpoint.target_site`, `kind is TargetKind.FILE`).

Rules (spec Goal 1–2):
- `file_sites`: a dep with `sink` naming `FILE:<name>` is a write whose record is `dep.source`; a dep with `origin` naming `FILE:<name>` is a read whose record is `dep.target`. Deduplicate by `(program, site, file, writes, record)`.
- CICS: a site matches the `TargetSite` with `kind is TargetKind.FILE` and `f"{caller}/{node}" == site.site`. Each candidate (strip trailing blanks) maps through `CICS_FILE -DEFINES_DATASET-> DATASET` to a DSN, or keeps the CICS file name as identity when undefined. One candidate and no reasons → `exact`; several → one `possible` per candidate with reason `candidates`; `reasons` non-empty → `possible` with them; none → one unresolved site, identity `?<file>`, reasons from the row.
- Batch: `PROGRAM -READS|WRITES|UPDATES|ENDS_BROWSE{select_name == file}-> COBOL_FILE` gives the DD name. Steps: every `STEP -JCL_STEP_RUNS|TSO_RUNS_PROGRAM-> P` where `P` reaches the program through zero or more `CALL` (exact) or `CALL_CANDIDATE` (possible, reason `call-candidate`) edges. Each step's `STEP -READS|WRITES|UPDATES{ddname == DD}-> DATASET` gives the DSN. No step → unresolved `no-step`; a step with no such DD → unresolved `dd-unbound`.
- Neither a target row nor a select name → unresolved, reason `unresolved-file`.
- Unresolved sites have `resolved=False`; their slot is per `(program, site)` (Task 2).

- [ ] **Step 1: Write the failing tests** in `test_dataset_resolution.py`, one per behaviour, on a hand-built `KnowledgeGraph` and `TargetSite` rows:
  - `test_batch_sites_resolve_through_the_steps_that_run_or_call_their_program`: program `W` (run by step `J1.S1`, DD `OUT` → `DS.A`) writes select `OUT-FILE`; program `R` called by `C` (run by `J2.S1`, DD `IN` → `DS.A`) reads select `IN-FILE`; a program `N` run by no step; a step `J3.S1` running `M` with no DD for its select. Assert the exact tuple of `DatasetSite`s: `W` and `R` → identity `DS.A`, `exact`, `()`; `N` → `?IN-FILE`, `possible`, `("no-step",)`, `resolved=False`; `M` → `possible`, `("dd-unbound",)`.
  - `test_cics_sites_resolve_through_resolved_targets_and_the_csd`: targets with one candidate `ACCTDAT ` (CSD → `DS.ACCT`), two candidates, a reason `incomplete-walk`, and no candidate with reason `uninitialised`. Assert identities and labels per the rules, including `?LIT-X` for the last.
  - `test_repeated_dep_rows_are_one_site`: five identical read deps give one `FileSite`.
  - `test_a_site_with_no_binding_is_unresolved_not_dropped`: a `FILE:` site matching neither → `possible`, `("unresolved-file",)`.
- [ ] **Step 2: Run** `cd cobble && uv run --no-sync pytest tests/experimental/partition/test_dataset_resolution.py -q` — Expected: FAIL (module not found).
- [ ] **Step 3: Implement** the three dataclasses, `KnowledgeGraph`/`knowledge_graph`, `file_sites`, `dataset_sites` per the rules above. Parse `FILE:<name>` once in `file_sites`.
- [ ] **Step 4: Run** the same command — Expected: green.
- [ ] **Step 5: Commit** — `feat(cobble): partition file sites resolve to dataset identities, exact or possible`

### Task 2: Dataset slots and field↔slot edges in the graph

**Files:**
- Modify: `cobble/cobble/experimental/partition/node_kind.py` — add `DATASET = "dataset"`
- Modify: `cobble/cobble/experimental/partition/graph_edge.py` — add `certainty: Certainty = Certainty.EXACT`, `reasons: tuple[str, ...] = ()`
- Create: `cobble/cobble/experimental/partition/dataset_links.py`
- Test: `cobble/tests/experimental/partition/test_dataset_links.py`

**Interfaces:**
- Consumes: `DatasetSite` (Task 1), `LeafIndex.fields_in`, `FieldGraph`, `GraphNode`, `GraphEdge`, `ByteAlignment`.
- Produces: `with_datasets(graph: FieldGraph, index: LeafIndex, sites: Sequence[DatasetSite]) -> FieldGraph` — the input graph plus slot nodes and dataset edges, nodes and edges kept sorted as `field_graph` sorts them.

Rules (spec Goals 3–6):
- Slots per resolved identity: boundaries are `0`, each site's record length, and every leaf's start/end relative to its site's record start, clipped to the record. Consecutive boundaries are slots. Node id `{identity}[{start}:{end}]`, label the same, `kind=DATASET`, `program=""`, `size=end-start`.
- Unresolved site: one slot over its whole record, id `{program}/{site}|{identity}`, label `{identity}`.
- Write site: edge leaf → slot; read site: slot → leaf; alignment is the overlap, offsets relative to leaf and slot. `clustered=False`, `cross_program=True`, `sites` = distinct sites, `barrier=graph.barrier`.
- An edge is `possible` (no alignments, `aligned=False`) when the site is `possible` (its reasons), the record is clamped (`clamped`), or two of the site's leaves overlap inside the slot (`overlapping-layouts`); otherwise `exact` with alignments.

- [ ] **Step 1: Write the failing tests**:
  - `test_writer_and_reader_layouts_are_cut_into_shared_slots`: writer leaf `ID[0:11]`, reader leaves `GRP[0:5]`, `SEQ[5:11]`, reader record 14 bytes with `X[11:14]`. Assert slot ids `DS.A[0:5]`, `DS.A[5:11]`, `DS.A[11:14]`; edges `W:R.ID→DS.A[0:5]` alignment `(0,0,5)`, `W:R.ID→DS.A[5:11]` `(5,0,6)`, `DS.A[0:5]→R:R.GRP` `(0,0,5)`, `DS.A[5:11]→R:R.SEQ` `(0,0,6)`, `DS.A[11:14]→R:R.X` and no writer edge into `DS.A[11:14]`; all `exact`, `clustered=False`.
  - `test_redefined_bytes_make_only_their_slots_possible`: reader record with header `TYPE[0:1]` and two `REDEFINES` variants over `[1:5]`. Assert the `[0:1]` edges `exact`, the `[1:5]` edges `possible`, `("overlapping-layouts",)`, no alignments.
  - `test_possible_and_unresolved_sites_get_unaligned_edges`: a `possible` (`candidates`) site, a clamped record (`clamped`), an unresolved site → its own slot `R/R/P/0|?LIT-X`.
  - `test_dataset_edges_never_change_clusters`: `cluster_set` on a graph before and after `with_datasets` yields equal cluster memberships.
- [ ] **Step 2: Run** `cd cobble && uv run --no-sync pytest tests/experimental/partition/test_dataset_links.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** `with_datasets` and the two model fields.
- [ ] **Step 4: Run** the new tests plus `tests/experimental/partition -q` — Expected: green.
- [ ] **Step 5: Commit** — `feat(cobble): dataset slots link writer and reader fields in the partition graph`

### Task 3: Graph CLI inputs, make target, docs

**Files:**
- Modify: `cobble/cobble/experimental/partition/graph_cli.py` — `--knowledge-graph` and `--targets`, both `type=Path, default=Path()`
- Modify: `Makefile` — `partition-graph` runs `cobble-build --config $(PARTITION_CONFIG) --output $(PARTITION_DIR)/knowledge-graph.jsonl --dynamic-call-targets $(PARTITION_DIR)/combine/targets.jsonl`, then passes `--knowledge-graph $(PARTITION_DIR)/knowledge-graph.jsonl --targets $(PARTITION_DIR)/combine/targets.jsonl`
- Modify: `docs/reference/cobble/partition.md` — flags, the `dataset` node kind, slots, labels, fail-safe
- Test: `cobble/tests/experimental/partition/test_partition_cli.py`

**Interfaces:**
- Consumes: `file_sites`, `dataset_sites`, `knowledge_graph` (Task 1), `with_datasets` (Task 2).

- [ ] **Step 1: Write the failing tests** in `test_partition_cli.py`:
  - `test_without_resolution_inputs_the_graph_is_unchanged`: run `main` on a fixture traces dir with and without `--targets` but no `--knowledge-graph`; assert the two output files are byte-identical and equal today's output, and the log names `knowledge graph` as absent (`caplog`).
  - `test_with_a_knowledge_graph_file_sites_become_dataset_links`: a fixture knowledge graph JSONL plus traces; assert the `dataset` nodes and dataset edges written, and that without `--targets` a CICS site yields no dataset node while a batch site does.
- [ ] **Step 2: Run** `cd cobble && uv run --no-sync pytest tests/experimental/partition/test_partition_cli.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the flags; log `partition graph: no knowledge graph given, dataset links off` / `no targets given, CICS file sites unresolved`; Makefile and docs.
- [ ] **Step 4: Run** the partition tests — Expected: green.
- [ ] **Step 5: Commit** — `feat(cobble): the partition graph stage takes dataset links from the knowledge graph and targets`

### Task 4: Unify relays bytes through exact dataset slots

**Files:**
- Modify: `cobble/cobble/experimental/aggregates/exact_merge.py` — `_bytes`
- Modify: `docs/reference/cobble/aggregates.md` — Unify section
- Test: `cobble/tests/experimental/aggregates/test_unify.py`

**Interfaces:**
- Consumes: `NodeKind.DATASET`, `GraphEdge.aligned` (Task 2).
- Produces: `exact_classes(graph: FieldGraph)` unchanged signature.

Rule: placed edges may have a `DATASET` node at either end; dataset nodes join `relays` (like subscripted occurrences) and are never sources or landings; an unaligned edge touching a dataset node never marks its field end unplaced.

- [ ] **Step 1: Extend the test** with `test_fields_holding_the_same_dataset_bytes_in_two_programs_are_one_class`: writer `W:R.ID` (11) → slots `DS[0:5]`, `DS[5:11]` → reader `R:R.ID` (11) joins; a reader `R:R.GRP` (5) does not; a `possible` unaligned edge from `DS[0:5]` to `Q:R.ID` (11) leaves `Q:R.ID`'s own exact join with `W:R.ID` through another commarea edge intact. Assert the exact class tuple.
- [ ] **Step 2: Run** `cd cobble && uv run --no-sync pytest tests/experimental/aggregates/test_unify.py -q` — Expected: FAIL (no class through slots).
- [ ] **Step 3: Implement** the `_bytes` change; update `aggregates.md`.
- [ ] **Step 4: Run** `tests/experimental -q` — Expected: green.
- [ ] **Step 5: Commit** — `feat(cobble): aggregate unify joins fields through exact dataset slots`

### Task 5: The page draws slots and dataset chains

**Files:**
- Modify: `cobble/cobble/experimental/partition/partition_page.html` — dataset nodes as squares in a distinct colour; dataset edges blue when `certainty == "exact"`, pale blue when `possible`, hover shows the slot id and reasons; clicking a dataset node or a field selects every node reachable through dataset edges (both directions) and lists them by program in the side panel; legend line extended.
- Modify: `docs/reference/cobble/partition.md` — render section
- Test: `cobble/tests/experimental/partition/test_partition_render.py`

**Interfaces:**
- Consumes: `NodeKind.DATASET`, `GraphEdge.certainty`, `GraphEdge.reasons`.

Ruling for the executor: sigma.js draws no dashed edges without an extra program, so "dashed" from the spec is rendered as the pale colour; slots stay in the outer rings `layout` already gives non-field nodes.

- [ ] **Step 1: Write the failing test** `test_the_page_embeds_dataset_slots_and_their_edge_labels`: render a graph from `with_datasets`; assert the embedded `PageData` JSON holds the slot node with `kind == "dataset"` and the edges' `certainty` and `reasons` exactly.
- [ ] **Step 2: Run** `cd cobble && uv run --no-sync pytest tests/experimental/partition/test_partition_render.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the template changes; docs.
- [ ] **Step 4: Run** `tests/experimental -q` — Expected: green. Then `make partition-render` on CardDemo and open `cobble/out-partition/partition.html`; check that clicking `AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS[0:11]` lists writer and reader fields in more than one program.
- [ ] **Step 5: Commit** — `feat(cobble): the partition page draws dataset slots and follows their chains`
