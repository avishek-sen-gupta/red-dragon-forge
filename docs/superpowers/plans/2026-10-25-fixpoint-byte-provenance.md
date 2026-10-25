# Fixpoint Byte Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The whole-scope fixpoint writes the byte provenance fields-trace wrote; the partition
graph, dataset resolution and `cobble-trace-query` read it; fields-trace, the pathwalk viz, the
narrowed scopes and area-need are deleted.

**Architecture:** Emission gains origin and literal attrs on `FLOWS_TO` edges and a new
`sinks.jsonl`. One streaming reader turns a fixpoint out-dir into the `DepRow`s the consumers already
take, so each consumer switches input rather than logic. Deletions come last, after a byte-level
comparison of trace rows against fixpoint rows on CardDemo.

**Tech Stack:** Python 3.13, Pydantic, pytest; cobble's fixpoint (`cobble/dataflow/fixpoint/`),
fields (`cobble/dataflow/fields/`) and experimental partition packages.

**Spec:** `docs/superpowers/specs/2026-10-25-fixpoint-byte-provenance-design.md`

## Global Constraints

- Gate: the commit hooks (`git commit`, no `--no-verify`); no commit message carries an
  attribution trailer.
- One scope only after Task 6: whole. No backward compatibility for narrowed out-dirs.
- No new sweep-cap flag: `--sweeps N` exists. `PARTITION_SWEEPS` is a Makefile variable with no
  default value written by this plan; the user sets it.
- Streaming: readers of fixpoint output read member by member (`members/<PROGRAM>/`), never a whole
  corpus file into memory at once.
- Every new or changed stage logs its progress (`counted`/`Tally` pattern in
  `cobble/experimental/partition/progress.py`, `tally.py`, or the fixpoint's own logger).
- Typed rows at file boundaries (Pydantic `model_validate_json`); no structure parsed out of strings.
- Run long suites through a visible streamed command (Monitor), never a hidden background job.

## Review Focus

1. A literal source at one node with two different literals must stay two rows; the edge dedupe key
   is the attrs, so `literal` must be in attrs. Owned by Task 1.
2. A `WRITE` whose FD record has no `file_record_to_select` entry: `sinks_of` raises `KeyError`
   today; the fixpoint must not lose the member for it. Owned by Task 2 (test: member with such a
   WRITE emits its other rows and no sink row for that statement).
3. A member directory written before this change (no `sinks.jsonl`) read by the new reader: reading
   must fail loudly naming the member and `--force`, not yield silently partial provenance. Owned by
   Task 3.
4. A `CALL` write-back must not become a file site in dataset resolution now that `via` is gone; it
   is a `%CALL:` origin. Owned by Task 4.
5. `cobble-trace-query` on a field in a program the out-dir does not hold: exit 2 with a message, as
   a missing trace file did. Owned by Task 5.

---

### Task 1: Origin and literal on FLOWS_TO edges

**Files:**
- Modify: `cobble/cobble/dataflow/fixpoint/fixpoint.py` (`FlowEdge` :110, `_at` :669)
- Modify: `cobble/cobble/dataflow/fields/emit.py` (`_attrs` :85)
- Test: `cobble/tests/dataflow/fields/test_emit.py`, `cobble/tests/dataflow/fixpoint/test_fixpoint.py`

**Interfaces:**
- Produces: `FlowEdge` gains `literal: str = ""`. Edge attrs gain `"origin"` (the synthetic origin,
  `""` for storage) and `"literal"` (`""` unless the source is a literal).

- [ ] **Step 1: Failing tests.** In `test_fixpoint.py`, a program with `MOVE 'A' TO X` and
  `MOVE 'B' TO X` at different nodes asserts two edges whose `literal` values are `'A'` and `'B'`
  (as `Source.literal` holds them). In `test_emit.py`, `graph_records` of a flow with one literal edge
  and one storage edge asserts the attrs exactly:
  `{"node", "source_extent": "", "target_extent", "origin": "LITERAL", "literal": "'A'"}` and
  `{..., "origin": "", "literal": ""}`.
- [ ] **Step 2: Run, see them fail** (`uv run --no-sync python -m pytest -q tests/dataflow/fields/test_emit.py tests/dataflow/fixpoint/test_fixpoint.py`).
- [ ] **Step 3: Implement.** `_at` copies `source.literal` into `FlowEdge.literal`; `_attrs` adds
  `"origin": edge.origin, "literal": edge.literal`.
- [ ] **Step 4: Run the fixpoint, fields and combine suites** (combine reads these attrs and must
  ignore the new keys). Expected: pass.
- [ ] **Step 5: Commit** `feat(cobble): fixpoint edges name their origin and literal`.

### Task 2: sinks.jsonl

**Files:**
- Modify: `cobble/cobble/dataflow/fixpoint/fixpoint.py` (`ProgramFlow`, `_at`, `_extracted`, `analyse`)
- Modify: `cobble/cobble/dataflow/fields/emit.py` or `side_tables.py` (sink row)
- Modify: `cobble/cobble/dataflow/fixpoint/build_corpus.py` (`MemberResult`, `_tables`, `_member_directory`, `_publish`, `MemberCounts` if it counts tables; constant `SINKS_FILE = "sinks.jsonl"` beside `DEFS_FILE`)
- Test: `cobble/tests/dataflow/fixpoint/test_fixpoint.py`, `cobble/tests/dataflow/fields/test_fields_build_corpus.py`

**Interfaces:**
- Produces: `FlowSink(node: str, sink: str, source: FieldExtent, definers: tuple[str, ...])` (frozen
  dataclass, `fixpoint.py`); `ProgramFlow.sinks: tuple[FlowSink, ...] = ()`. A member directory and
  the top-level out-dir gain `sinks.jsonl`, one row per (node, sink, source extent):
  `{"program", "node", "sink", "source_extent", "definers"}`, read back by `SinkRow` (Pydantic,
  frozen, in `cobble/dataflow/fixpoint/sink_row.py`).

- [ ] **Step 1: Failing tests.** `test_fixpoint.py`: a program that moves `WS-A` into an FD record
  and `WRITE`s it asserts one `FlowSink(node=<write node>, sink="FILE:<file>", source=<record
  extent>, definers=(<move node>,))`; a `WRITE` of a record with no `file_record_to_select` entry
  asserts the program's other flows are present and no sink for that node (Review Focus 2).
  `test_fields_build_corpus.py`: a two-member run asserts `members/<P>/sinks.jsonl` and the
  top-level `sinks.jsonl` hold exactly the expected rows.
- [ ] **Step 2: Run, see them fail.**
- [ ] **Step 3: Implement.** `analyse` passes `MappingProxyType(asg.file_record_to_select)` down to
  `_extracted`/`_at`. At each statement, `sinks_of(statement, files)` (catch only the `KeyError` of a
  missing FD-record entry, count it in the member's report); for each `Sink`, each extent of
  `operand_extents(sink.operand, index).extents` gives a `FlowSink` whose definers are
  `_definers(after, extent)`, `after = transfer(statement, node_id, state, index)`. The publish step
  writes sink rows with the same per-member pattern as defs.
- [ ] **Step 4: Run fixpoint, fields and combine suites.** Expected: pass; combine untouched.
- [ ] **Step 5: Commit** `feat(cobble): the fixpoint writes the sinks each statement's bytes leave by`.

### Task 3: A streaming provenance reader

**Files:**
- Create: `cobble/cobble/dataflow/fields/dep_row.py` (move `DepRow` out of `trace_query.py`, unchanged fields)
- Create: `cobble/cobble/dataflow/fields/provenance.py`
- Modify: `cobble/cobble/dataflow/fields/trace_query.py` (import `DepRow` from `dep_row`)
- Test: `cobble/tests/dataflow/fields/test_provenance.py`

**Interfaces:**
- Consumes: Task 1 attrs, Task 2 `SinkRow` and `SINKS_FILE`.
- Produces: `provenance(fixpoint_dir: Path) -> Iterator[DepRow]`, streaming
  `members/<PROGRAM>/` in sorted order, logging `provenance: members read N/M`. Mapping per
  `FLOWS_TO` edge: `program`, `via=""`, `target=byte_range(target_extent, program)`,
  `origin=attrs.origin`, `literal=attrs.literal`, `source=byte_range(source_extent, program)` or
  `NO_RANGE` when origin is set, `site=f"{program}/{node}"`, `definers` from that member's
  `defs.jsonl` row for `(node, source_extent)` qualified as `f"{program}/{definer}"`, `sink=""`.
  Per sink row: `target=NO_RANGE`, `sink`, `source`, `definers` qualified the same way.
  `MissingProvenance(ValueError)` names a member directory with no `sinks.jsonl` and says to rerun
  with `--force`.

- [ ] **Step 1: Failing test.** Build a fixpoint out-dir by running `build_corpus` on a two-member
  synthetic corpus (the fixture pattern in `test_fields_build_corpus.py`), then assert
  `tuple(provenance(out))` equals an exact tuple of `DepRow`s: one literal origin row with its
  literal, one storage copy with its definer, one sink row. A member dir with `sinks.jsonl` removed
  raises `MissingProvenance` naming it (Review Focus 3).
- [ ] **Step 2: Run, see it fail.**
- [ ] **Step 3: Implement** `provenance` and `MissingProvenance`; read edge rows with the existing
  typed `EdgeRow` reader and defs rows by `fixpoint/rows.py:stream`.
- [ ] **Step 4: Run fields suite.** Expected: pass.
- [ ] **Step 5: Commit** `feat(cobble): read a fixpoint out-dir as the dep rows the trace wrote`.

### Task 4: Partition graph and dataset resolution read the fixpoint

**Files:**
- Modify: `cobble/cobble/experimental/partition/graph_cli.py` (`--traces` becomes `--fixpoint DIR`; `_deps`)
- Modify: `cobble/cobble/experimental/partition/dataset_resolution.py` (`file_sites`: drop the `via` crossing filter)
- Modify: `Makefile` (`partition-graph` passes `--fixpoint $(PARTITION_DIR)/fixpoint`)
- Modify: `docs/reference/cobble/partition.md` (inputs table, pipeline table)
- Test: `cobble/tests/experimental/partition/test_partition_cli.py`, `test_dataset_resolution.py`, `test_partition_graph.py`

**Interfaces:**
- Consumes: `provenance(fixpoint_dir)`.
- Produces: `cobble-experimental-partition-graph --fixpoint DIR` (replaces `--traces`).

- [ ] **Step 1: Failing tests.** `test_partition_cli.py`: the end-to-end test builds its graph from a
  fixpoint out-dir it creates with `build_corpus` instead of hand-written trace files, asserting the
  same node and edge lists the current test asserts where the inputs mean the same thing.
  `test_dataset_resolution.py`: a `%CALL:` origin row at a site is not a file site; a `FILE:` origin
  row is (Review Focus 4).
- [ ] **Step 2: Run, see them fail.**
- [ ] **Step 3: Implement.** `_deps` becomes `tuple(provenance(arguments.fixpoint))`, keeping the
  existing progress log; `file_sites` drops `crossings`.
- [ ] **Step 4: Run the partition and fields suites.** Expected: pass.
- [ ] **Step 5: Commit** `feat(cobble): the partition graph reads the fixpoint's provenance`.

### Task 5: cobble-trace-query reads the fixpoint

**Files:**
- Modify: `cobble/cobble/dataflow/fields/trace_query.py` (`--trace FILE` becomes `--fixpoint DIR`; `load` replaced by `provenance`; drop path-derived output)
- Modify: `cobble/cobble/dataflow/fields/access_query.py` (import `ByteRange` from `extent_text`; `_resolve_from_extents` moves to `extent_text.py` or a small `field_resolution.py`)
- Modify: `docs/reference/cobble/trace.md` (`cobble-trace-query` section moves to `field-dataflow.md`)
- Test: `cobble/tests/dataflow/fields/test_trace_query.py`, `test_fields_access.py`

**Interfaces:**
- Produces: `query(fixpoint_dir: Path, direction: str, field: str, max_depth: int = 5, extents_path: Path = Path()) -> tuple[str, ...]`.

- [ ] **Step 1: Failing tests.** `test_trace_query.py` rewritten over a `build_corpus` out-dir:
  forward from a field lists its sinks and copies to depth 2 exactly; backward lists its origins
  with their literals; a program the out-dir lacks exits 2 with
  `trace-query: no member <P> under <dir>` (Review Focus 5).
- [ ] **Step 2: Run, see them fail.**
- [ ] **Step 3: Implement.** BFS unchanged; input from `provenance`.
- [ ] **Step 4: Run the fields suite.** Expected: pass.
- [ ] **Step 5: Commit** `feat(cobble): cobble-trace-query walks the fixpoint's provenance`.

### Task 6: Acceptance — trace rows against fixpoint rows on CardDemo

**Files:**
- Create (scratchpad, not committed): `compare_provenance.py`

- [ ] **Step 1:** Run on CardDemo: `cobble-parse-corpus`, `cobble-extents`,
  `cobble-dataflow-fixpoint --all` (whole scope; record wall time; run once uncapped and once with the
  `--sweeps` value the user names), `cobble-dataflow-combine --max-hops 5`, and the existing
  `cobble-fields-trace` per member with `--dynamic-call-targets`.
- [ ] **Step 2:** The script keys each trace dep row and each `provenance` row on (program, node,
  source extent or origin+literal, target extent or sink) and reports: trace rows the fixpoint lacks
  (listed), fixpoint rows the trace lacks (counted), and trace rows with `via` or `source_program`
  set checked against `links.jsonl` windows instead.
- [ ] **Step 3:** Each trace row the fixpoint lacks is fixed (back to the owning task) or listed with
  its reason. Stop and show the user the report before Task 7; the accepted list goes into the
  Task 8 commit message.

### Task 7: One scope; area-need deleted

**Files:**
- Modify: `cobble/cobble/dataflow/fixpoint/scope.py` (delete; `Scope` callers lose it), `options.py`, `member_counts.py` (drop `scope`), `build_corpus.py` (`_scope`, `_narrowed`, `_narrow_problem`, `_stored_problem`, `_rows_readable`, `_refusal`/`_other_scope`, the two flags), `fixpoint.py` (`_live` keeps the whole branch), `query.py` (`_restriction`/`_restricted`), `diagnose.py` (flags, `_refusal`, `_options`)
- Delete: `area_need_cli.py`, `area_need_file.py`, `area_needs.py`, `area_found.py`, `area_worklist.py`, `area_explain.py`, `explain_request.py`, `prepared_program.py`, then any module left with no importer (check `explain_*`, `demand*`, `live_graph`, the non-whole branch of `liveness`), with their tests (`test_call_targets_only_synthetic.py`, `test_area_worklist.py`, and the narrowed cases in `test_diagnose_synthetic.py`, `test_file_sites_synthetic.py:146`, `test_fixpoint_cost_synthetic.py:309`)
- Modify: `pyproject.toml` (drop `cobble-dataflow-area-need`), `docs/reference/cobble/field-dataflow.md`, `config.md`, `aggregates.md:5`

- [ ] **Step 1:** Delete, then run `uv run --no-sync pyright` and `rg` for every deleted name;
  expected zero hits outside `docs/superpowers/`.
- [ ] **Step 2:** Run fixpoint, combine and fields suites. Expected: pass.
- [ ] **Step 3: Commit** `refactor(cobble): the fixpoint has one scope; area-need is gone`.

### Task 8: fields-trace and the pathwalk viz deleted; pipeline

**Files:**
- Delete: `cobble/cobble/dataflow/fields/trace.py`, `trace_report.py`, `call_targets.py`, `cobble/cobble/viz/pathwalk_viz.py`, `pathwalk_template.html`; tests `test_fields_trace.py`, `test_fields_trace_call.py`, `test_fields_trace_sinks.py`, `test_fields_trace_report.py`, `test_path_recorder.py`, `tests/viz/test_pathwalk_viz.py`
- Modify: `aliases.py` (drop the `targets` parameter and `_candidate_sites`), `build_corpus.py:325`, `test_fields_aliases.py` (drop the candidate case), `pyproject.toml` (drop `cobble-fields-trace`, `cobble-viz-pathwalk`), `.talismanrc` (drop entries of deleted files only), `cobble/demo/carddemo/run.sh:40-43`
- Modify: `Makefile` (`partition-traces`: parse, extents, `cobble-dataflow-fixpoint --all --sweeps $(PARTITION_SWEEPS)`, combine; drop area-need, the trace loop and `PARTITION_PATHS`), `docs/reference/cobble/trace.md` (delete), `viz.md` (pathwalk section), `partition.md`, `config.md`, `docs/README.md` index

- [ ] **Step 1:** Delete and edit, then `rg` for every deleted command and module name; expected
  zero hits outside `docs/superpowers/`, `docs/records/` and `docs/presentation/` (presentation
  material is a point-in-time artefact and stays).
- [ ] **Step 2:** Run the cobble suite through the commit hook.
- [ ] **Step 3: Commit** `refactor(cobble): fields-trace and the pathwalk viz are gone; the partition pipeline is fixpoint and combine`, with Task 6's accepted differences in the body.

### Task 9: Scale

**Files:**
- Modify: `cobble/cobble/dataflow/fixpoint/build_corpus.py` (`_Sinks.add_member`: dedupe within the member, not against a corpus-wide `FirstSighting`)
- Test: `cobble/tests/dataflow/fields/test_fields_build_corpus.py`

- [ ] **Step 1: Failing test.** Two members whose rows would collide only under a corpus-wide key do
  not exist, since every row is program-qualified; assert the published files equal the
  concatenation of each member's deduplicated rows in table order.
- [ ] **Step 2:** Implement per-member dedupe; run the fields suite.
- [ ] **Step 3:** On CardDemo, record peak memory (`/usr/bin/time -l`) and wall time for the
  whole-scope fixpoint and for combine; file one issue per stage with the numbers and the
  extrapolation to 3,000 programs, combine's in-memory tables named.
- [ ] **Step 4: Commit** `perf(cobble): the fixpoint's publish step dedupes per member`.

### Task 10: Combine links one call-connected group at a time

Added at the user's request: combine must not hold every program's tables at once. Decided by the
user: group programs over everything that could link them, and load, link and write one group at a
time. No cache; the largest group bounds memory.

**Files:**
- Create: `cobble/cobble/dataflow/combine/call_groups.py`
- Modify: `cobble/cobble/dataflow/combine/cli.py` (`_load_all` and `_link_and_write` run per group; outputs append per group)
- Test: `cobble/tests/dataflow/combine/test_call_groups.py`, and the existing combine suite unchanged

**Interfaces:**
- Produces: `call_groups(fixpoint_dir: Path, programs: frozenset[str], transactions: Mapping[str, str]) -> tuple[frozenset[str], ...]`:
  the connected components of programs joined by any edge that could link them — each literal call
  target in a member's `jumps.jsonl`, each candidate in the fixpoint's `targets.jsonl`, and each
  `RETURN TRANSID`/`START` transaction mapped to its program by the CSD (`transactions`). Read from
  the small per-member files only, streamed. Largest group first.
- Combine's outputs (`targets.jsonl`, `links.jsonl`, the rest) are the concatenation of each group's
  outputs, in group order, written as each group finishes.

- [ ] **Step 1: Failing tests.** `test_call_groups.py`: over a `build_corpus` out-dir with programs A
  (CALLs B by literal), B, C (XCTL to a field whose candidates are D), D, and E (alone), `call_groups`
  returns `({A, B}, {C, D}, {E})` in size order. A combine run over that out-dir, per group, writes
  the same set of output rows as today's all-at-once run (compare as sets; row order may change
  with grouping).
- [ ] **Step 2:** Run, see them fail.
- [ ] **Step 3: Implement** `call_groups` and the per-group loop. A link that resolves to a program
  outside its group is logged as a warning naming both programs (it means the grouping missed an
  edge), and counted in the run report.
- [ ] **Step 4:** Run the combine suite and the partition suite. Expected: pass.
- [ ] **Step 5:** On CardDemo, record the group sizes, combine's peak memory and wall time next to
  the all-at-once run, in the commit message; file an issue if any cross-group link was logged.
- [ ] **Step 6: Commit** `perf(cobble): combine links one call-connected group of programs at a time`.
