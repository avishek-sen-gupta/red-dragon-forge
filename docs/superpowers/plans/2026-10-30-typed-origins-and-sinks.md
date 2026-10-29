# Typed Origins and Sinks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace cobble's string-encoded field-dataflow origins and sinks with `Origin(kind, name)` / `Sink(kind, name)` values, end to end, so no reader learns a kind from text.

**Architecture:** Two value types with closed kind enums live in `cobble/dataflow/fields/`. The field transfer and the sink finder build them; the fixpoint carries them; `emit.py` and `side_tables.py` write them as nested `{"kind", "name"}` objects; provenance reads them back into `DepRow`; partition and trace-query read kinds, and use one `text()` form (`KIND:name`) only for ids and display.

**Tech Stack:** Python 3.13, frozen dataclasses, `enum.StrEnum`, Pydantic v2 (stdlib dataclasses as model fields), pytest.

**Spec:** `docs/superpowers/specs/cobble/2026-10-30-typed-origins-and-sinks-design.md`

## Global Constraints

- Origin kinds, exactly: `NONE, LITERAL, FILE, MAP, CALL, DYNAMIC_CALL, CICS_STATE, FUNCTION, UNKNOWN_FIELD, FIGURATIVE, LENGTH_OF, UNRESOLVED_OPERAND, UNMODELLED`. Values are the upper-case names.
- Sink kinds, exactly: `NONE, FILE, MAP, TS_QUEUE, TD_QUEUE, TRANSID`.
- Text form: `KIND:name`, or `KIND` alone when `name` is empty. `unplaced` is never part of it. Used for ids, labels and trace output only; nothing parses it.
- Wire form: `{"kind": "<KIND>", "name": "<name>"}`, plus `"unplaced"` on an origin only when non-empty. `attrs.literal` and every `literal` field are removed.
- No backward compatibility; old runs are rebuilt. Reading an old `graph.jsonl` **or** `sinks.jsonl` raises provenance's stale-artifacts error.
- Out of scope: CFG `FILE:`/`MAP:`/`PROGRAM:` read/write names; `OperandExtents.reason`; `fixpoint/query.py`'s field-id split.
- Repo rules: frozen dataclasses, one class per file, no `None` defaults (null objects), no comments beyond a one-line module/class header, Pyright strict, python-fp-lint. One hooked commit at the end (`git commit` runs every gate; do not run pre-commit by hand, do not use `--no-verify`). Run only targeted `uv run --no-sync python -m pytest <paths>` from `cobble/` while working; do **not** source `bridge-env.sh`.

## Review Focus

1. A CICS `LINK`/`XCTL` with `PROGRAM('X')` vs `PROGRAM(WS-X)`: the first must be `CALL:X` (quotes stripped), the second `DYNAMIC_CALL:WS-X`. Pinned in Task 2.
2. A literal containing a dot or a colon (`'.'`, `'12:00'`) must survive as an origin name and in `PROG.LITERAL:'.'` ids without breaking `fixpoint/query.py`'s field-id split, which splits on the **first** dot only (program names have none). Pinned in Task 4.
3. `INITIALIZE` gives `LITERAL` with an empty name; its text is `LITERAL` and its wire object has `"name": ""`. Pinned in Task 2.
4. A WRITE whose sink and origin would both be FILE: `dataset_resolution` must pick the sink branch first, as today. Pinned in Task 5.
5. An old-format `sinks.jsonl` must raise the stale-artifacts message, not a raw `ValidationError`. Pinned in Task 4.

---

### Task 1: The types

**Files:**
- Create: `cobble/cobble/dataflow/fields/origin_kind.py`, `origin.py`, `sink_kind.py`, `sink.py` (one class each)
- Test: `cobble/tests/dataflow/fields/test_origin_and_sink.py`

**Interfaces:**
- Produces:
  - `class OriginKind(StrEnum)`, `class SinkKind(StrEnum)` with the Global Constraints values.
  - `@dataclass(frozen=True) class Origin: kind: OriginKind; name: str; unplaced: str = ""` with `def text(self) -> str`, `def wire(self) -> Mapping[str, str]`, `@property def is_storage(self) -> bool` (kind is `NONE`). Module constant `NO_ORIGIN = Origin(OriginKind.NONE, "")`.
  - `@dataclass(frozen=True) class Sink: kind: SinkKind; name: str` with `text()`, `wire()`, `is_none`. Module constant `NO_SINK`.
- The existing operand-carrying `Sink` in `fields/sinks.py` is renamed `SinkSite(sink: Sink, operand: RefModOperand)` in Task 3; nothing in this task touches it.

- [ ] **Step 1: Write the failing test** — `test_origin_and_sink_text_and_wire`:

```python
assert Origin(OriginKind.FILE, "ACCTFILE-FILE").text() == "FILE:ACCTFILE-FILE"
assert Origin(OriginKind.CICS_STATE, "").text() == "CICS_STATE"
assert Origin(OriginKind.LITERAL, "'.'").text() == "LITERAL:'.'"
assert Origin(OriginKind.MAP, "M1", unplaced="WS-X").text() == "MAP:M1"
assert Origin(OriginKind.MAP, "M1", unplaced="WS-X").wire() == {"kind": "MAP", "name": "M1", "unplaced": "WS-X"}
assert Origin(OriginKind.LITERAL, "").wire() == {"kind": "LITERAL", "name": ""}
assert NO_ORIGIN.is_storage and not Origin(OriginKind.LITERAL, "").is_storage
assert Sink(SinkKind.TS_QUEUE, "Q1").text() == "TS_QUEUE:Q1"
assert Sink(SinkKind.FILE, "OUT").wire() == {"kind": "FILE", "name": "OUT"}
assert NO_SINK.is_none
assert TypeAdapter(Origin).validate_python({"kind": "MAP", "name": "M1", "unplaced": "WS-X"}) == Origin(OriginKind.MAP, "M1", "WS-X")
assert TypeAdapter(Sink).validate_python({"kind": "FILE", "name": "OUT"}) == Sink(SinkKind.FILE, "OUT")
```

- [ ] **Step 2:** `cd cobble && uv run --no-sync python -m pytest tests/dataflow/fields/test_origin_and_sink.py` — FAIL (import error).
- [ ] **Step 3:** Implement the four files.
- [ ] **Step 4:** Same command — PASS.

### Task 2: Origins from the transfer

**Files:**
- Modify: `cobble/cobble/dataflow/fields/state.py:58-89` (`Source.origin: Origin` with no default, drop `literal`; delete the `LITERAL`, `CICS_STATE` string constants)
- Modify: `cobble/cobble/dataflow/fields/transfer.py` — `_from_extents` (origin `NO_ORIGIN`), `_synthetic(origin: Origin, node)`, `_unresolved`, `_unresolved_origin(operand, reason) -> Origin`, `_union_writes`, `_origin_writes(operands, origin: Origin, ...)`, `_read_writes`, `_call_origin -> Origin`, `_cics_origin -> Origin`, `_cics_received`, `_unmodelled_writes`, the INITIALIZE writer (~537), `_MAP_ORIGIN` and `_NAMED_ORIGINS` removed.
- Modify: every other `Source(` constructor (`combine/link_crossings.py:83`, `fixpoint/provenance.py:109` if it builds one) to pass `NO_ORIGIN`.
- Test: `cobble/tests/dataflow/fields/test_transfer.py` (update existing expectations; add the cases below)

**Interfaces:**
- Consumes: Task 1 `Origin`, `OriginKind`, `NO_ORIGIN`.
- Produces: `Source(origin: Origin, extent: FieldExtent, node: str)`.

Mapping (from spec Decided 2):

| today | becomes |
|---|---|
| `LITERAL` + literal text | `Origin(LITERAL, <operand text as written>)` |
| INITIALIZE `LITERAL` | `Origin(LITERAL, "")` |
| `UNKNOWN:<n>` / `UNKNOWN-NAME` | `Origin(UNKNOWN_FIELD, n)` / `Origin(UNKNOWN_FIELD, "")` |
| `FUNCTION:<n>` / `FUNCTION` | `Origin(FUNCTION, n)` / `Origin(FUNCTION, "")` |
| `FIGURATIVE`, `LENGTH-OF` | `Origin(FIGURATIVE, "")`, `Origin(LENGTH_OF, "")` (reason `"figurative"`, `"length-of"`) |
| `FIELD:A,B` | one source each: `Origin(UNRESOLVED_OPERAND, "A")`, `Origin(UNRESOLVED_OPERAND, "B")` |
| `<x>→<op>` | `replace(x, unplaced=op.name)` |
| `FILE:<f>` (READ, CICS file verbs) | `Origin(FILE, f)` |
| `MAP:<m>` | `Origin(MAP, m)` |
| `%CALL:<lit>` / `%CALL:%DYNAMIC:<id>` (batch) | `Origin(CALL, lit)` / `Origin(DYNAMIC_CALL, id)` |
| CICS LINK/XCTL `%CALL:<PROGRAM text>` | literal operand (`CicsOperand.is_literal`): `Origin(CALL, text without its quotes)`; else `Origin(DYNAMIC_CALL, text upper-cased and stripped)` |
| `%CICS-STATE` | `Origin(CICS_STATE, "")` |
| verb | `Origin(UNMODELLED, verb)` |

- [ ] **Step 1: Update and add tests** in `test_transfer.py`. Replace each old string expectation with the table's value (the existing tests cover FILE, MAP, CALL, DYNAMIC_CALL, FIELD, FUNCTION, LITERAL, CICS_STATE). Add `test_cics_link_program_literal_and_variable`: `EXEC CICS LINK PROGRAM('SUBPROG') COMMAREA(WS-A)` gives a write to `WS-A` from `Origin(OriginKind.CALL, "SUBPROG")`; `PROGRAM(WS-PGM)` gives `Origin(OriginKind.DYNAMIC_CALL, "WS-PGM")`. Add `test_unresolved_operands_one_source_each`: a COMPUTE reading two undeclared names `EXT-A`, `EXT-B` gives exactly `{Origin(UNRESOLVED_OPERAND, "EXT-A"), Origin(UNRESOLVED_OPERAND, "EXT-B")}` among its synthetic sources. Add to the INITIALIZE test: origin `Origin(OriginKind.LITERAL, "")`.
- [ ] **Step 2:** `uv run --no-sync python -m pytest tests/dataflow/fields/test_transfer.py tests/dataflow/fields/test_state.py` — FAIL.
- [ ] **Step 3:** Implement per the table.
- [ ] **Step 4:** Same command — PASS. Then `uv run --no-sync python -m pytest tests/dataflow/fields` and fix every remaining old-string expectation there (`test_fields_synthetic.py`, `test_extent_text.py`, `tests/dataflow/fields/*undeclared*`, `*varying*`) to the new values.

### Task 3: Sinks from the sink finder

**Files:**
- Modify: `cobble/cobble/dataflow/fields/sinks.py` — rename record to `SinkSite(sink: Sink, operand: RefModOperand)` in its own file `sink_site.py`; drop the five `*_SINK` string constants; each handler builds `Sink(SinkKind.X, name)`.
- Modify: `cobble/cobble/dataflow/fixpoint/fixpoint.py:149` (`FlowSink.sink: Sink`), `:893-920` (`sink=site.sink`), import of `Sink` → `SinkSite`.
- Modify: `cobble/cobble/dataflow/fields/side_tables.py:152-160` (`ProgramSink.sink: Sink`), `:234` (`sink_identity` uses `sink.sink.text()`), `:271-283` (`"sink": sink.sink.wire()`).
- Test: `cobble/tests/dataflow/fields/test_sinks.py`

**Interfaces:**
- Consumes: Task 1 `Sink`, `SinkKind`.
- Produces: `SinkSite`; `FlowSink.sink: Sink`; `ProgramSink.sink: Sink`; `sinks.jsonl` rows with `"sink": {"kind", "name"}`.

- [ ] **Step 1:** Update `test_sinks.py` expectations: WRITE of an FD record → `Sink(SinkKind.FILE, "<file>")`; `SEND MAP('M1')` → `Sink(SinkKind.MAP, "M1")` (no `O`); `WRITEQ TS QUEUE('Q')` → `Sink(SinkKind.TS_QUEUE, "'Q'")` with the operand text as written; `WRITEQ TD` → `TD_QUEUE`; `START TRANSID('T1')` → `TRANSID`. Add to the side-table test: `json.loads(sink_row(row)[1])["sink"] == {"kind": "FILE", "name": "OUT"}`.
- [ ] **Step 2:** `uv run --no-sync python -m pytest tests/dataflow/fields/test_sinks.py` — FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Same — PASS.

### Task 4: Fixpoint, emit and provenance

**Files:**
- Modify: `cobble/cobble/dataflow/fixpoint/fixpoint.py:121-146` (`FlowEdge.origin: Origin`, drop `literal`), `:736`, `:760-781` (`source.origin.is_storage` replaces truthiness).
- Modify: `cobble/cobble/dataflow/fields/emit.py:72-95` — `_source_name` returns `edge.origin.text()` unless storage; `_source_extent` tests `is_storage`; `_attrs` writes `"origin": edge.origin.wire()`, no `"literal"`.
- Modify: `cobble/cobble/dataflow/fixpoint/flow_attrs.py` (`origin: Origin`, drop `literal`), `sink_row.py` (`sink: Sink`).
- Modify: `cobble/cobble/dataflow/fixpoint/provenance.py:84-113` (`origin=attrs.origin`, `sink=NO_SINK` in `_flow`; `origin=NO_ORIGIN`, `sink=row.sink` in `_sunk`; `source` is `NO_RANGE` when `not attrs.origin.is_storage`), `:131-134` wrap `SinkRow.model_validate` with the same `ValidationError` → `_stale(directory, "a sink row lacks its typed sink")` handler as `_attrs`.
- Modify: `cobble/cobble/dataflow/fields/dep_row.py` (`origin: Origin`, `sink: Sink`, drop `literal`). Fix every `DepRow(` constructor (`rg -n 'DepRow\(' cobble`) to pass `NO_ORIGIN`/`NO_SINK` where it passed `""`.
- Modify: tests and fixtures: `tests/dataflow/fields/test_emit.py`, `test_fields_build_corpus.py` (`:226`, `:1200-1201`), `tests/dataflow/fixpoint/test_provenance.py`, `tests/dataflow/fixpoint/fixpoint_dir.py` (writes `attrs.origin` objects), `tests/dataflow/combine/test_load.py:81`, `tests/dataflow/jumps/test_facts.py:18`, and regenerate `tests/dataflow/fixpoint/data/jumps_baseline/graph.jsonl` by rerunning the test that produces it (or rewrite its 22 lines to the new form: ids `PROGA.LITERAL:<text>`, `PROGA.CALL:SUBP`, `attrs.origin` objects, no `attrs.literal`).

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: `DepRow.origin: Origin`, `DepRow.sink: Sink`; `graph.jsonl` edge `attrs.origin` object; source ids `PROG.<text()>` upper-cased.

- [ ] **Step 1:** Update tests. In `test_emit.py`: a literal move's edge has `source == "PROGA.LITERAL:'Y'"` and `attrs["origin"] == {"kind": "LITERAL", "name": "'Y'"}` and no `"literal"` key; a map receive's source id is `"PROGA.MAP:MAP1"`. Add `test_literal_with_a_dot_keeps_its_program`: a `MOVE '.' TO X` in `PROGA`, emitted and then read by `fixpoint/query.py`'s program lookup, gives program `PROGA` and id `PROGA.LITERAL:'.'`. In `test_provenance.py`: rows carry `Origin(OriginKind.LITERAL, "'Y'")` and `Origin(OriginKind.MAP, "MAP1")`; add `test_old_sink_rows_are_stale`: a member directory whose `sinks.jsonl` row has `"sink": "FILE:OUT"` raises the stale-artifacts error (same exception type and message prefix the existing old-`attrs` test asserts).
- [ ] **Step 2:** `uv run --no-sync python -m pytest tests/dataflow/fields/test_emit.py tests/dataflow/fixpoint tests/dataflow/combine tests/dataflow/jumps` — FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Same — PASS, then `uv run --no-sync python -m pytest tests/dataflow` — PASS.

### Task 5: Readers — partition and trace query

**Files:**
- Modify: `cobble/cobble/experimental/partition/graph_node.py` — add `origin: Origin = NO_ORIGIN` and `sink: Sink = NO_SINK`. (Ruling against spec Decided 6's single `terminal` field: `FILE` and `MAP` are kinds of both types, so one untyped `{kind, name}` object would be ambiguous to parse.)
- Modify: `cobble/cobble/experimental/partition/graph_build.py:48-54, 141-150` — `_terminal` takes the typed value: origin nodes `id=f"{program}|origin|{origin.text()}"`, `label=f"{program} {origin.text()}"`, `origin=origin`; sink nodes likewise with `sink`. Delete `_origin_name`. `dep.sink` truthiness → `not dep.sink.is_none`.
- Modify: `cobble/cobble/experimental/partition/fill_trace.py:30`, `graph_build.py:214` — same truthiness change.
- Modify: `cobble/cobble/experimental/partition/dataset_resolution.py:7, 25-48` — drop `FILE_PREFIX` import and `_named`; `_uses` returns `_written(dep, dep.sink.name)` when `dep.sink.kind is SinkKind.FILE`, else `_read(dep, dep.origin.name)` when `dep.origin.kind is OriginKind.FILE`, else `()`.
- Modify: `cobble/cobble/dataflow/fields/trace_query.py:266, 299` — `dep.sink.text()` / `dep.origin.text()` when not none/storage.
- Modify: `cobble/cobble/knowledge_graph/graph_types.py:50-52` — the FIELD comment lists the new text forms (`LITERAL:<text>`, `FILE:<name>`, `CICS_STATE`, `CALL:<member>`).
- Tests: `tests/experimental/partition/test_partition_graph.py:101-148`, `test_partition_cli.py:138-267`, `test_dataset_resolution.py:28, 199-223`, `tests/experimental/aggregates/test_unify.py:78`, `tests/dataflow/fields/test_trace_query.py`.

**Interfaces:**
- Consumes: Task 4 `DepRow`.
- Produces: partition `graph.jsonl` nodes with `origin`/`sink` objects; ids `P|origin|LITERAL:'Y'`, `P|sink|FILE:F`.

- [ ] **Step 1:** Update tests: partition ids become `P|origin|LITERAL:'Y'`, `P|origin|LITERAL:SPACES`, `P|sink|FILE:F`; a terminal node's `origin == Origin(OriginKind.LITERAL, "'Y'")` (or `sink == Sink(SinkKind.FILE, "F")`) and a field node's are `NO_ORIGIN`/`NO_SINK`. `test_dataset_resolution.py`: the `%CALL:K` case becomes `Origin(OriginKind.CALL, "K")` and resolves to no file site. Add `test_written_record_is_resolved_by_its_sink`: a dep with `sink=Sink(FILE, "OUT")` and `origin=Origin(FILE, "IN")` yields one written `FileSite` named `OUT` and no read one. Trace query: lines read `<- LITERAL:'Y'  at P/n`, `-> FILE:OUT  at P/n`, `<- CALL:CALLEE  at P/n`.
- [ ] **Step 2:** `uv run --no-sync python -m pytest tests/experimental tests/dataflow/fields/test_trace_query.py` — FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Same — PASS; then `uv run --no-sync python -m pytest` (whole cobble suite) — PASS.
- [ ] **Step 5:** `rg -n 'FILE_PREFIX|removeprefix|startswith' cobble/cobble/experimental/partition cobble/cobble/dataflow/fields/trace_query.py cobble/cobble/dataflow/fixpoint/provenance.py` shows nothing that touches an origin or sink.

### Task 6: Docs, skill, capture script; rebuild; commit

**Files:**
- Modify: `docs/reference/cobble/field-dataflow.md` (24-30, 108, 421-422), `docs/reference/cobble/partition.md` (65-68, 259): the origin/sink kinds table, the wire object, the text form, ids as opaque keys.
- Modify: `cobble/skills/cobble-artifacts/SKILL.md` (20, 84): how to read `attrs.origin` / `sink` / partition `origin`/`sink`; then `make skills` to refresh `.claude/skills/`.
- Modify: `docs/presentation/capture/cobble.sh:169` — `ORIGINS = {"LITERAL", "CICS_STATE"}` and compare `name.partition(":")[0]` (the token is now `LITERAL:'Y'`).

- [ ] **Step 1:** Edit the docs, skill and script.
- [ ] **Step 2:** Rebuild CardDemo from the repo root: `make carddemo-all`. Expected: completes; prints the new run directory.
- [ ] **Step 3:** Compare against `cobble/out-carddemo-20261028-1640-rebuild-all`: node and edge counts of fixpoint `graph.jsonl`, `sinks.jsonl` and partition `graph.jsonl` differ only by (a) extra fixpoint LITERAL source nodes (one per literal value), (b) `UNRESOLVED_OPERAND` splits, (c) `COACTVWC`'s `CDEMO-TO-PROGRAM` call now `DYNAMIC_CALL`. Record the counts in the commit message body.
- [ ] **Step 4:** Update the `RUN=` line in `docs/presentation/video/README.md` to the new run directory.
- [ ] **Step 5:** `git diff --cached --name-only` after staging lists only files this plan touched; anything else staged is someone else's work — stop and ask.
- [ ] **Step 6: Commit once** (hooks are the gate):

```bash
git add docs/superpowers/specs/cobble/2026-10-30-typed-origins-and-sinks-design.md docs/superpowers/plans/2026-10-30-typed-origins-and-sinks.md cobble docs/reference/cobble docs/presentation/capture/cobble.sh docs/presentation/video/README.md
git commit -m "refactor(cobble): typed origins and sinks, written as {kind, name}"
```

Expected: every hook passes. If one fails, fix the cause and commit again; never `--no-verify`.
