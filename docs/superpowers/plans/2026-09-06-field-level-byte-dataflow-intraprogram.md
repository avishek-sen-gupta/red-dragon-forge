# Field-level byte dataflow — intra-program slice — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `cobble/cobble/dataflow/fields/` far enough to answer "which bytes did this field's value come from" **within one program** — operand to byte extent, statement transfer, paragraph-keyed fixpoint, naming, and graph emission — with a coverage-measured acceptance run over a real cache.

**Architecture:** A program's records come from `cobble.dataflow.layout` (already built, validated); its control flow comes from `cobble.dataflow.srccfg` (already built); the byte-range alias algebra comes from `cobol_memory` (extracted upstream by the prerequisites plan). This plan adds only the layer between them: `extent.py` maps a *structured* ASG operand to `FieldExtent`s through layout's cells, `transfer.py` turns one statement plus an in-state into an out-state, `fixpoint.py` iterates that over the CFG keyed on paragraph entry state, `naming.py` maps extents back to field names, and `emit.py` writes `FIELD` nodes and `FLOWS_TO` edges. Task 1 first extracts the one depth-agnostic ASG descent every consumer has been reimplementing.

**Tech Stack:** Python 3.13, `uv` workspace, pytest, Black (88), import-linter. Inputs: the parsed ASG cache (`cobble/out-<corpus>-parsed`, JSON per member) loaded as `CobolASG` via `CobolASG.from_dict`, and `cobol_memory` from `vendor/red-dragon`.

**Spec:** `docs/superpowers/specs/2026-09-05-field-level-byte-dataflow-design.md`

**Predecessor plan:** `docs/superpowers/plans/2026-09-05-field-level-byte-dataflow-prerequisites.md` (complete, merged) — it produced `cobol_memory` and the cache whose MOVE operands carry subscripts and reference modification.

## Scope

**In:** `extent.py`, `state.py`, `transfer.py`, `fixpoint.py`, `naming.py`, `emit.py`, a corpus driver, and the shared ASG descent.

**Out — deferred to a second plan:** `summary.py` and `interprocedural.py` (the spec's **Cross-program** section: caller-independent commarea summaries, the topological DAG pass, `LINK`/`CALL` binding at `min` length, the 31%-synthetic-seam fallback, `XCTL` contributing no exit summary, and the nine duplicate `program_id`s a `program_id`-keyed map must detect rather than overwrite). Nothing in this plan may assume a cross-program stage exists; a `CALL`/`LINK`/`XCTL` in this slice contributes a synthetic `%CALL:<target>` source to its `USING` operands and nothing more.

**Out — the spec says so:** guard conditions on edges, MQ/shared-file flow, extracting `memory_effects.py` or the upstream fixpoint, lifting the precision ceiling on computed subscripts.

## Global Constraints

Every task's requirements implicitly include this section.

- **No external corpus identifiers in any tracked artifact** — commit messages, issues, specs, plans, docs, code comments, test names, fixtures. Use the spec's placeholders (`PROG-A`, `REC-MASTER`, `MST-COUNT`, `DATASET-M`) or generic names (`PROGA`, `WS-A`). Anything corpus-specific goes in a gitignored `cobble/config/*.toml`, following `cobble/tests/dataflow/srccfg/conftest.py`'s `corpus_asg_paths` fixture exactly.
- **`may_alias` over-approximates; `must_cover` under-approximates.** A write KILLs a prior definition only when `must_cover` holds. `Precision.CLAMPED` never covers, so a computed subscript is always a weak update. Never add a code path that kills on a CLAMPED write.
- **cobble must not import any runtime and must not import `interpreter`.** Allowed vendor surface: `cobol_asg`, `cobol_memory`. Nothing may import cobble. Verify with `uv run lint-imports` from the repo root.
- **Comments are a smell.** A surviving comment carries an external constraint, a non-obvious "why", or a reference to an issue or standard.
- **No test counts in living documentation** (READMEs, package docs, design overviews). Step-level "Expected: PASS" in this plan is an execution record and exempt.
- **Black, line length 88.** Measure a line with its indent and trailing comma before claiming it fits.
- **Do not run `bd export` and do not stage `issues/issues.jsonl`.** Forge has no beads redactor; a plain export reintroduces corpus identifiers into the tracked snapshot.
- **Sandbox:** `uv` and `git commit` need `dangerouslyDisableSandbox: true` (blocked `~/.cache/uv`, `~/.cache/pre-commit`). Use `$TMPDIR`, never `/tmp`. macOS has no `timeout` binary.
- **Test command:** `cd cobble && uv run pytest <path> -v`. Full package suite: `cd cobble && make test`.

## Rulings carried into this plan

Recorded here because each settles a question the spec left open, and an executor who re-opens it will burn the timeline.

**R1 — `extent.py` takes ASG statements, not CFG nodes.** `srccfg.cfg.Node` carries `writes`/`reads` as bare name strings (`cfg.py:writes: tuple[str, ...]`) — the flattening the spec faults as bead `j7w`. Subscripts and reference modification are gone by then. So `fields/` reads structured operands off the typed ASG (`MoveStatement.source: RefModOperand`, `.targets: list[RefModOperand]`, each with `subscripts: tuple[ExprNode, ...]` and `ref_mod_start`/`ref_mod_length`) and uses `Cfg` **only** for control flow. The two are joined by CFG node id.

**R2 — the join key is the CFG node id, and the index that inverts it lives in `srccfg`.** `desugar.node_id(ctx, path, suffix)` returns `f"{ctx.paragraph}/{path}{suffix}"`, where `path` is the dotted nesting address built by `lower_statements` (`f"{prefix}{position}"`, extended by `f"{path}.then"`, `f"{path}.else"`, `f"{path}.at_end"`, `f"{path}.body"`, `f"{path}.{true_attr}"`). Every id **without** a `#` suffix addresses exactly one ASG statement; the `#`-suffixed ones (`#test`, `#loop`, `#raise`, `#dispatch`, `#search`, `#empty`, `#raise.join`) are synthetic control nodes. Task 1 builds `statement_index(asg) -> Mapping[str, object]` in `srccfg`, which owns the convention, and a consistency test guards it against drift.

*Rejected alternative:* carry the statement on `Node`. `Node` is `frozen=True` and used in sets; `MoveStatement.targets` is a `list`, so the statement is unhashable and would break `Node`'s value semantics. *Also rejected:* returning `(Cfg, index)` from `build_program` — changes a signature every srccfg consumer calls, for no gain.

**R3 — Task 1 retrofits `diagnosis/asg_operands.py` and `fields/`, not `depgraph.statement_stream` or `srccfg.desugar`.** `depgraph/graph.py:130 statement_stream` enumerates `children`, `else_children`, `whens`, `when_other` and therefore misses `at_end`, `not_at_end`, `invalid_key`, `not_invalid_key` — a real instance of bead `aj3`. Fixing it *changes an existing corpus pass's output* (more statements, more dependency edges), which needs its own re-run and its own review, and coupling that to this vertical slice buys nothing. `srccfg.desugar` keeps its key enumeration because there the nesting keys are semantically distinct — each arm lowers to a different CFG shape, so the enumeration is the logic, not an incidental omission. Bead `aj3` therefore stays open after Task 1, narrowed to the depgraph retrofit.

**R4 — no universal "is this a statement" predicate.** `cobol_asg` has no statement base class; `_DISPATCH_TABLE` is private and excludes dialect-parsed types (`ExecCicsStatement`, `ExecSqlStatement`) that this plan needs. So the shared module provides pure traversal and each consumer filters by what it handles: `descend` for the walk, `isinstance(node, kinds)` at the call site. A statement form `transfer.py` does not handle is then visibly unhandled rather than silently mis-typed.

**R5 — the acceptance oracle's identifiers live in a gitignored config.** The spec's end-to-end oracle (`MST-COUNT` derives from `SCR-COUNT` at `PARA-UPDATE/57`, reaching `DATASET-M`) uses redacted placeholders. The real triple goes in `cobble/config/fields-tests.toml` (gitignored via `config/*.toml`), and the tracked test reads it or skips — the pattern `tests/dataflow/srccfg/conftest.py` already uses.

---

## File Structure

**Create:**

| file | responsibility |
| --- | --- |
| `cobble/cobble/asg_walk.py` | one depth-agnostic descent over an ASG (typed objects or raw dicts) |
| `cobble/cobble/dataflow/srccfg/statements.py` | CFG node id to ASG statement |
| `cobble/cobble/dataflow/fields/__init__.py` | docstring only |
| `cobble/cobble/dataflow/fields/extent.py` | structured operand to `FieldExtent`, via layout cells |
| `cobble/cobble/dataflow/fields/state.py` | `Source`, `State`, `join`, `write`, `reaching` |
| `cobble/cobble/dataflow/fields/transfer.py` | one statement plus in-state to out-state |
| `cobble/cobble/dataflow/fields/fixpoint.py` | paragraph-keyed intra-program worklist |
| `cobble/cobble/dataflow/fields/naming.py` | extent to smallest covering field name |
| `cobble/cobble/dataflow/fields/emit.py` | `FIELD` nodes, `FLOWS_TO` edges |
| `cobble/cobble/dataflow/fields/config.py` | `[fields]` TOML table |
| `cobble/cobble/dataflow/fields/build_corpus.py` | corpus driver and CLI |

**Modify:** `cobble/cobble/diagnosis/asg_operands.py` (Task 1), `cobble/cobble/knowledge_graph/graph_types.py` (Task 6), `cobble/pyproject.toml` (Task 6, entry point), `cobble/README.md` (Task 6).

**Dependency direction:** `fields` reads `layout`, `srccfg`, `asg_walk`, `cobol_asg`, `cobol_memory`. Nothing in `layout` or `srccfg` imports `fields`.

---

## Task 1: Shared ASG descent, and the CFG-node-to-statement index

Closes bead `aj3`'s extraction half (see R3) and supplies the two inputs every later task needs: a walk that cannot miss a nesting key, and the map from a CFG node id back to the statement it lowered.

**Files:**
- Create: `cobble/cobble/asg_walk.py`
- Test: `cobble/tests/test_asg_walk.py`
- Create: `cobble/cobble/dataflow/srccfg/statements.py`
- Test: `cobble/tests/dataflow/srccfg/test_statements.py`
- Modify: `cobble/cobble/diagnosis/asg_operands.py:58-79` (replace `_walk_mapping`/`_walk_sequence`/`_move_operands` with a filter over `descend`)

**Interfaces:**
- Consumes: `cobol_asg.asg_types.CobolASG`, `cobble.dataflow.srccfg.desugar` (path convention only — do not import private names; reimplement the convention and let the consistency test hold the two together).
- Produces:
  - `asg_walk.descend(node: object) -> Iterator[object]` — pre-order, root first, over mapping values, non-string sequence elements, and dataclass field values. Explicit stack, no recursion.
  - `asg_walk.procedure_statements(asg, kinds: tuple[type, ...]) -> Iterator[object]` — every instance of `kinds` reachable from the four places a program hangs statements: `asg.statements`, each `asg.sections[*].statements`, each `asg.sections[*].paragraphs[*].statements`, each `asg.paragraphs[*].statements`.
  - `srccfg.statements.statement_index(asg) -> Mapping[str, object]` — CFG node id (no `#` suffix) to the ASG statement at that address.

- [ ] **Step 1: Write the failing descent tests**

`cobble/tests/test_asg_walk.py`:

```python
"""The one ASG descent, which must not enumerate nesting keys."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.asg_walk import descend


def test_descend_yields_the_root_first():
    root = {"type": "MOVE"}
    assert list(descend(root))[0] is root


def test_descend_reaches_a_statement_under_an_unenumerated_nesting_key():
    """at_end is not children; a walk that enumerates keys misses it."""
    asg = {
        "type": "READ",
        "at_end": [{"type": "IF", "else_children": [{"type": "MOVE", "operands": []}]}],
    }
    types = [n.get("type") for n in descend(asg) if isinstance(n, dict)]
    assert types == ["READ", "IF", "MOVE"]


def test_descend_does_not_split_strings_into_characters():
    assert "ABC" in list(descend({"name": "ABC"}))
    assert "A" not in list(descend({"name": "ABC"}))


def test_descend_enters_dataclass_fields():
    @dataclass(frozen=True)
    class Leaf:
        name: str

    @dataclass(frozen=True)
    class Branch:
        arms: tuple[Leaf, ...]

    leaf = Leaf(name="WS-A")
    assert leaf in list(descend(Branch(arms=(leaf,))))


def test_descend_survives_nesting_deeper_than_the_recursion_limit():
    """29+ levels are observed in the corpus; the walk must not be recursive."""
    node: dict = {"type": "MOVE"}
    for _ in range(5000):
        node = {"type": "IF", "children": [node]}
    assert sum(1 for _ in descend(node)) > 5000
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd cobble && uv run pytest tests/test_asg_walk.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobble.asg_walk'`

- [ ] **Step 3: Write `asg_walk.py`**

```python
"""One depth-agnostic descent over an ASG, whatever shape it arrives in.

Statements nest through many dict keys -- children, else_children, whens,
at_end, not_at_end, invalid_key, not_invalid_key -- and compose to arbitrary
depth (29+ levels observed). Enumerating those keys is the defect bead
red-dragon-forge-aj3 records: a one-level walk saw 36% of the corpus's MOVE
statements, and the next statement form the bridge learns silently reopens the
hole for whichever consumer was not updated. So this walks the whole document
and classifies nothing -- a consumer filters for what it handles, which keeps
an unhandled statement form visible instead of mis-typed.

The stack is explicit because the nesting outruns CPython's recursion limit.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import fields, is_dataclass


def _children(node: object) -> tuple[object, ...]:
    if isinstance(node, Mapping):
        return tuple(node.values())
    if isinstance(node, (str, bytes)):
        return ()
    if isinstance(node, Sequence):
        return tuple(node)
    if is_dataclass(node) and not isinstance(node, type):
        return tuple(getattr(node, f.name) for f in fields(node))
    return ()


def descend(node: object) -> Iterator[object]:
    """Every node reachable from ``node``, pre-order, root first."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(_children(current)))


def _procedure_roots(asg) -> tuple[object, ...]:
    return (
        tuple(asg.statements),
        tuple(section.statements for section in asg.sections),
        tuple(
            paragraph.statements
            for section in asg.sections
            for paragraph in section.paragraphs
        ),
        tuple(paragraph.statements for paragraph in asg.paragraphs),
    )


def procedure_statements(asg, kinds: tuple[type, ...]) -> Iterator[object]:
    """Every statement of one of ``kinds`` in the program's procedure division.

    Rooted at the statement lists rather than at the ASG, so the descent never
    enters the data division's field trees -- which are large, and hold no
    statements.
    """
    for root in _procedure_roots(asg):
        for node in descend(root):
            if isinstance(node, kinds):
                yield node
```

- [ ] **Step 4: Run the descent tests**

Run: `cd cobble && uv run pytest tests/test_asg_walk.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Retrofit `asg_operands.py` onto `descend`**

Replace `cobble/cobble/diagnosis/asg_operands.py:58-79` (the three walk functions) with:

```python
def _move_operands(asg: Mapping) -> Iterator[Mapping]:
    """Every MOVE operand anywhere in the ASG document."""
    return chain.from_iterable(
        node.get("operands") or ()
        for node in descend(asg)
        if isinstance(node, Mapping) and _is_move_statement(node)
    )
```

Add `from cobble.asg_walk import descend`; drop the now-unused `Sequence` import only if nothing else in the file uses it (`cli`'s signature does — keep it). Remove `RecursionError` from `_operand_shapes_guarded`'s except tuple: the walk is no longer recursive, and keeping it there would silently swallow a real failure as "unreadable".

- [ ] **Step 6: Run the existing diagnosis suite unchanged**

Run: `cd cobble && uv run pytest tests/diagnosis/test_asg_operands.py -v`
Expected: PASS, including `test_nested_move_in_if_else_children_is_counted` — the retrofit must not change a single count.

- [ ] **Step 7: Write the failing statement-index tests**

`cobble/tests/dataflow/srccfg/test_statements.py`:

```python
"""CFG node id back to the ASG statement it lowered.

srccfg's Node carries operand *names*; subscripts and reference modification
never reach it. fields/ needs the statement, and the node id is already its
address: desugar builds it from the paragraph plus a dotted nesting path.
"""

from __future__ import annotations

from cobol_asg.cobol_statements import MoveStatement

from cobble.dataflow.srccfg.build import build_program
from cobble.dataflow.srccfg.statements import statement_index


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


def test_a_top_level_statement_is_indexed_at_its_position(program_of):
    asg = program_of([_move("WS-A", "WS-B"), _move("WS-C", "WS-D")])
    index = statement_index(asg)
    second = index["MAIN/1"]
    assert isinstance(second, MoveStatement)
    assert second.targets[0].name == "WS-D"


def test_a_statement_under_an_if_arm_is_indexed_at_the_arm_path(program_of):
    asg = program_of(
        [
            {
                "type": "IF",
                "condition": {"kind": "lit", "value": "1"},
                "children": [_move("WS-A", "WS-B")],
                "else_children": [_move("WS-C", "WS-D")],
            }
        ]
    )
    index = statement_index(asg)
    assert index["MAIN/0.then.0"].targets[0].name == "WS-B"
    assert index["MAIN/0.else.0"].targets[0].name == "WS-D"


def test_every_statement_bearing_cfg_node_has_an_entry(program_of):
    """The convention lives in desugar; this is the guard against drift.

    A node id with no '#' addresses a statement. If desugar changes how it
    builds a path and this module does not, that id stops resolving -- and
    every extent for that statement silently disappears rather than failing.
    """
    asg = program_of(
        [
            {
                "type": "IF",
                "condition": {"kind": "lit", "value": "1"},
                "children": [
                    {
                        "type": "EVALUATE",
                        "subjects": [{"kind": "lit", "value": "1"}],
                        "whens": [
                            {
                                "conditions": [{"kind": "lit", "value": "1"}],
                                "children": [_move("WS-A", "WS-B")],
                            }
                        ],
                    }
                ],
                "else_children": [_move("WS-C", "WS-D")],
            }
        ]
    )
    cfg = build_program(asg)
    index = statement_index(asg)
    unsuffixed = {
        node.id
        for node in cfg.nodes
        if "#" not in node.id and (node.writes or node.reads)
    }
    assert unsuffixed
    assert unsuffixed <= set(index)
```

- [ ] **Step 8: Run them to verify they fail**

Run: `cd cobble && uv run pytest tests/dataflow/srccfg/test_statements.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobble.dataflow.srccfg.statements'`

- [ ] **Step 9: Write `statements.py`**

`cobble/cobble/dataflow/srccfg/statements.py`:

```python
"""CFG node id to the ASG statement it lowered.

desugar.node_id is f"{paragraph}/{path}{suffix}", where path is the dotted
nesting address lower_statements builds. An id with no '#' addresses exactly one
statement; the '#'-suffixed ones (#test, #loop, #raise, #dispatch, #search,
#empty) are synthetic control nodes with no statement behind them.

Inverting the convention here rather than carrying the statement on Node: Node
is frozen and used in sets, and MoveStatement.targets is a list, so a statement
field would make it unhashable. test_statements.py holds the two conventions
together.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping

_ARMS = (
    ("children", "then"),
    ("else_children", "else"),
    ("at_end", "at_end"),
    ("not_at_end", "not_at_end"),
    ("invalid_key", "invalid_key"),
    ("not_invalid_key", "not_invalid_key"),
)


def _arms(statement) -> Iterator[tuple[str, tuple]]:
    for attribute, segment in _ARMS:
        body = getattr(statement, attribute, ()) or ()
        if body:
            yield segment, tuple(body)
    for when in tuple(getattr(statement, "whens", ()) or ()) + tuple(
        getattr(statement, "when_other", ()) or ()
    ):
        body = tuple(getattr(when, "children", ()) or ())
        if body:
            yield "", body


def _walk(statements, paragraph: str, path: str) -> Iterator[tuple[str, object]]:
    prefix = f"{path}." if path else ""
    for position, statement in enumerate(statements):
        here = f"{prefix}{position}"
        yield f"{paragraph}/{here}", statement
        for segment, body in _arms(statement):
            child_path = f"{here}.{segment}" if segment else here
            yield from _walk(body, paragraph, child_path)


def statement_index(asg) -> Mapping[str, object]:
    """Every statement-bearing CFG node id, mapped to its statement."""
    return dict(
        pair
        for paragraph, statements in _paragraphs(asg)
        for pair in _walk(statements, paragraph, "")
    )


def _paragraphs(asg) -> Iterator[tuple[str, tuple]]:
    for paragraph in asg.paragraphs:
        yield paragraph.name, tuple(paragraph.statements)
    for section in asg.sections:
        yield section.name, tuple(section.statements)
        for paragraph in section.paragraphs:
            yield paragraph.name, tuple(paragraph.statements)
```

**Note for the implementer:** `_arms`'s segment names and the `whens` empty-segment case must match `desugar.py`'s actual `lower_statements` call sites (`desugar.py:224-225, 370-371, 432, 525, 541, 672`). Read those lines and correct `_ARMS` and `_arms` against them before running the test — a `whens` body that desugar lowers at `path` with no extra segment is why the `whens` case yields `""`. If a call site uses a segment this table lacks, add it; Step 10's third test is what catches an omission.

- [ ] **Step 10: Run the statement-index tests**

Run: `cd cobble && uv run pytest tests/dataflow/srccfg/test_statements.py -v`
Expected: PASS (3 tests)

- [ ] **Step 11: Run the whole srccfg and diagnosis suites**

Run: `cd cobble && uv run pytest tests/dataflow/srccfg tests/diagnosis -q`
Expected: PASS, no change in outcomes.

- [ ] **Step 12: Format, lint imports, commit**

```bash
cd cobble && uv run black cobble tests
cd /Users/avisheksengupta/code/red-dragon-forge && uv run lint-imports
cd /Users/avisheksengupta/code/red-dragon-forge && git add cobble/cobble/asg_walk.py cobble/tests/test_asg_walk.py cobble/cobble/dataflow/srccfg/statements.py cobble/tests/dataflow/srccfg/test_statements.py cobble/cobble/diagnosis/asg_operands.py
git commit -m "feat(cobble): one ASG descent, and a CFG-node-to-statement index"
```

---

## Task 2: `extent.py` — a structured operand to byte extents

**Files:**
- Create: `cobble/cobble/dataflow/fields/__init__.py`
- Create: `cobble/cobble/dataflow/fields/extent.py`
- Test: `cobble/tests/dataflow/fields/__init__.py` (empty), `cobble/tests/dataflow/fields/conftest.py`, `cobble/tests/dataflow/fields/test_extent.py`

**Interfaces:**
- Consumes: `cobble.dataflow.layout.{Cell, Record, program_records}`; `cobol_memory.field_extent.{FieldExtent, Precision}`; `cobol_memory.region_id.RegionId`; `cobol_asg.ref_mod.{RefModOperand, RefModLiteral, RefModReference, RefModBinOp, FunctionCallOperand}`; `cobol_asg.cobol_expression.{LiteralNode, BinOpNode}`.
- Produces:
  - `CellIndex` with `CellIndex.of(records: tuple[Record, ...]) -> CellIndex`, `.cells_named(name, qualifiers, arity) -> tuple[Cell, ...]`, `.elementary_within(extent) -> tuple[Cell, ...]`, `.containing(extent) -> tuple[Cell, ...]`, `.extent_of(cell) -> FieldExtent`.
  - `OperandExtents(extents: tuple[FieldExtent, ...], reason: str)`.
  - `operand_extents(operand, index: CellIndex) -> OperandExtents`.
  - `NO_EXTENT_REASONS: frozenset[str]` = `{"unknown-name", "length-of", "function", "figurative"}`.

**The operand shapes this must handle**, observed in the current cache and confirmed against `cobol_asg`:

`RefModOperand(name: str, ref_mod_start: RefModExpr | None, ref_mod_length: RefModExpr | None, length_of: str, qualifiers: tuple[str, ...], subscripts: tuple[ExprNode, ...], rounded: bool)`. Reference-modification expressions are `RefModLiteral(value: str)`, `RefModReference(name: str)`, `RefModLengthOf(name: str)`, `RefModBinOp(op: str, left, right)`. Subscript expressions are `LiteralNode(value: str)`, `FieldRefNode(name, subscripts)`, `BinOpNode(op, left, right)`, `FigurativeNode`, `LengthOfNode`, `FunctionNode`, `RefModNode`, `DfhRespNode`. Corpus proportions: of 102,922 subscripted MOVE operands, 24,929 are literal-only (EXACT) and 77,993 have a computed subscript (CLAMPED); of 11,252 reference-modified operands, 10,889 are constant.

**Rules, in order:**

1. `operand.length_of` non-empty → `reason="length-of"`, no extents. `LENGTH OF X` is a compile-time constant, not a read of X.
2. `FunctionCallOperand` → `reason="function"`.
3. Candidate cells = every cell named `operand.name` whose `path` contains all of `operand.qualifiers` and whose `len(cell.index) == len(operand.subscripts)`. Arity matching is what separates a whole-table reference from a subscripted one: `Cell.index` "is also the arity of a reference" (`layout.py:209`).
4. No candidates → `reason="unknown-name"`. A figurative constant (`SPACES`, `ZEROS`) as a source arrives as a name that resolves to nothing; classify it `reason="figurative"` when `operand.name` is in `_FIGURATIVE`.
5. Every subscript folds to a constant → the single cell whose `index` equals that tuple; `Precision.EXACT`.
6. Any subscript does not fold → one `Precision.CLAMPED` extent per distinct `decl` among the candidates, spanning `min(start)` to `max(end)` over the cells sharing that `decl`. `layout.py:33-35` states the contract: "a reference with a variable subscript picks every cell sharing a `decl`. No model can do better."
7. Reference modification then applies to each extent: constant start (and length, defaulting to the remainder) narrows it and keeps its precision; a non-constant start or length widens to the whole base extent at `Precision.CLAMPED`. COBOL reference modification is **1-based** — `WS-F(2:3)` starts at `cell.start + 1`.
8. Region comes from the owning record's `origin`: `WORKING-STORAGE`, `LINKAGE`, `LOCAL-STORAGE`, `FILE` map to the matching `RegionId` (`layout.py:58-63`).

- [ ] **Step 1: Write the fields conftest**

`cobble/tests/dataflow/fields/conftest.py`:

```python
"""Fixtures for the field-level dataflow tests.

Programs are built as ASG dicts in the exact shape the parse cache holds, so a
test's input is the same thing the corpus pass reads. No corpus member is named
anywhere in this directory; the acceptance test reads a gitignored config.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from cobol_asg.asg_types import CobolASG

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.extent import CellIndex
from cobble.dataflow.layout import program_records

CORPUS_CONFIG = Path(__file__).resolve().parents[3] / "config" / "fields-tests.toml"


@pytest.fixture
def program_of():
    """A one-paragraph program PROGA whose paragraph is MAIN."""

    def build(statements: Sequence[Mapping], **extra) -> CobolASG:
        body = {
            "program_id": "PROGA",
            "paragraphs": [{"name": "MAIN", "statements": list(statements)}],
            **extra,
        }
        with cached_asg_dialect_parsers_registered():
            return CobolASG.from_dict(json.loads(json.dumps(body)))

    return build


@pytest.fixture
def index_of():
    """A CellIndex over a program's records."""

    def build(asg: CobolASG) -> CellIndex:
        return CellIndex.of(program_records(asg))

    return build


def field(level: int, name: str, pic: str = "", **extra) -> dict:
    """One DATA DIVISION entry, in cache shape."""
    entry: dict = {"level": level, "name": name}
    if pic:
        entry["pic"] = pic
    return {**entry, **extra}
```

**Note for the implementer:** the exact key names a `CobolField` dict uses (`level`, `name`, `pic`, `occurs`, `children`, `redefines`, `usage`) must be read off `cobol_asg/asg_types.py:57 CobolField.from_dict` and `cobble/tests/dataflow/test_field_layout.py`, which already builds field dicts. Copy that file's helper rather than inventing keys.

- [ ] **Step 2: Write the failing extent tests**

`cobble/tests/dataflow/fields/test_extent.py`:

```python
"""One table-driven case per operand form, asserting precision on each.

The asymmetry under test: only an EXACT extent may later kill a definition, so
a computed subscript must never produce one.
"""

from __future__ import annotations

from cobol_asg.ref_mod import RefModOperand

from cobol_memory.field_extent import Precision
from cobol_memory.region_id import RegionId

from cobble.dataflow.fields.extent import operand_extents

from .conftest import field


def _program(program_of, fields: list[dict]):
    return program_of([], data_fields=fields)


def test_a_bare_elementary_name_is_one_exact_extent(program_of, index_of):
    asg = _program(program_of, [field(1, "REC-A", children=[field(5, "WS-A", "X(10)")])])
    result = operand_extents(RefModOperand(name="WS-A"), index_of(asg))
    (extent,) = result.extents
    assert (extent.start, extent.length) == (0, 10)
    assert extent.precision is Precision.EXACT
    assert extent.region is RegionId.WORKING_STORAGE


def test_a_group_name_spans_its_children(program_of, index_of):
    asg = _program(
        program_of,
        [
            field(
                1,
                "REC-A",
                children=[field(5, "WS-A", "X(10)"), field(5, "WS-B", "X(6)")],
            )
        ],
    )
    (extent,) = operand_extents(RefModOperand(name="REC-A"), index_of(asg)).extents
    assert (extent.start, extent.length) == (0, 16)


def test_a_literal_subscript_selects_one_occurrence_exactly(program_of, index_of):
    asg = _program(
        program_of,
        [field(1, "REC-A", children=[field(5, "WS-A", "X(4)", occurs=5)])],
    )
    operand = RefModOperand(name="WS-A", subscripts=_literals("3"))
    (extent,) = operand_extents(operand, index_of(asg)).extents
    assert (extent.start, extent.length) == (8, 4)
    assert extent.precision is Precision.EXACT


def test_a_computed_subscript_clamps_to_the_whole_table(program_of, index_of):
    asg = _program(
        program_of,
        [
            field(
                1,
                "REC-A",
                children=[field(5, "WS-A", "X(4)", occurs=5), field(5, "WS-I", "9(4)")],
            )
        ],
    )
    operand = RefModOperand(name="WS-A", subscripts=_references("WS-I"))
    (extent,) = operand_extents(operand, index_of(asg)).extents
    assert (extent.start, extent.length) == (0, 20)
    assert extent.precision is Precision.CLAMPED


def test_a_constant_reference_modification_narrows_and_stays_exact(
    program_of, index_of
):
    asg = _program(program_of, [field(1, "REC-A", children=[field(5, "WS-A", "X(10)")])])
    operand = _ref_mod("WS-A", start="3", length="4")
    (extent,) = operand_extents(operand, index_of(asg)).extents
    assert (extent.start, extent.length) == (2, 4)
    assert extent.precision is Precision.EXACT


def test_reference_modification_with_no_length_runs_to_the_end(program_of, index_of):
    asg = _program(program_of, [field(1, "REC-A", children=[field(5, "WS-A", "X(10)")])])
    (extent,) = operand_extents(_ref_mod("WS-A", start="4"), index_of(asg)).extents
    assert (extent.start, extent.length) == (3, 7)


def test_a_computed_reference_modification_clamps_to_the_whole_field(
    program_of, index_of
):
    asg = _program(
        program_of,
        [field(1, "REC-A", children=[field(5, "WS-A", "X(10)"), field(5, "WS-I", "9(4)")])],
    )
    operand = _ref_mod_ref("WS-A", start_name="WS-I")
    (extent,) = operand_extents(operand, index_of(asg)).extents
    assert (extent.start, extent.length) == (0, 10)
    assert extent.precision is Precision.CLAMPED


def test_a_multidimensional_literal_subscript_selects_one_cell(program_of, index_of):
    asg = _program(
        program_of,
        [
            field(
                1,
                "REC-A",
                children=[
                    field(
                        5,
                        "WS-ROW",
                        occurs=3,
                        children=[field(10, "WS-COL", "X(2)", occurs=4)],
                    )
                ],
            )
        ],
    )
    operand = RefModOperand(name="WS-COL", subscripts=_literals("2", "3"))
    (extent,) = operand_extents(operand, index_of(asg)).extents
    assert (extent.start, extent.length) == (12, 2)
    assert extent.precision is Precision.EXACT


def test_length_of_yields_no_extent_and_says_why(program_of, index_of):
    asg = _program(program_of, [field(1, "REC-A", children=[field(5, "WS-A", "X(10)")])])
    result = operand_extents(RefModOperand(name="", length_of="WS-A"), index_of(asg))
    assert result.extents == ()
    assert result.reason == "length-of"


def test_an_unknown_name_yields_no_extent_and_says_why(program_of, index_of):
    asg = _program(program_of, [field(1, "REC-A", children=[field(5, "WS-A", "X(10)")])])
    result = operand_extents(RefModOperand(name="WS-NOPE"), index_of(asg))
    assert result.extents == ()
    assert result.reason == "unknown-name"


def test_a_figurative_constant_is_not_reported_as_an_unknown_name(program_of, index_of):
    asg = _program(program_of, [field(1, "REC-A", children=[field(5, "WS-A", "X(10)")])])
    result = operand_extents(RefModOperand(name="SPACES"), index_of(asg))
    assert result.reason == "figurative"


def test_a_qualifier_disambiguates_a_name_declared_twice(program_of, index_of):
    asg = _program(
        program_of,
        [
            field(1, "REC-A", children=[field(5, "WS-N", "X(4)")]),
            field(1, "REC-B", children=[field(5, "WS-N", "X(4)")]),
        ],
    )
    unqualified = operand_extents(RefModOperand(name="WS-N"), index_of(asg))
    assert len(unqualified.extents) == 2
    qualified = operand_extents(
        RefModOperand(name="WS-N", qualifiers=("REC-B",)), index_of(asg)
    )
    assert len(qualified.extents) == 1
```

Helpers at the bottom of the same file:

```python
def _literals(*values: str):
    from cobol_asg.cobol_expression import LiteralNode

    return tuple(LiteralNode(value=v) for v in values)


def _references(*names: str):
    from cobol_asg.cobol_expression import FieldRefNode

    return tuple(FieldRefNode(name=n) for n in names)


def _ref_mod(name: str, start: str, length: str = "") -> RefModOperand:
    from cobol_asg.ref_mod import RefModLiteral

    return RefModOperand(
        name=name,
        ref_mod_start=RefModLiteral(value=start),
        ref_mod_length=RefModLiteral(value=length) if length else None,
    )


def _ref_mod_ref(name: str, start_name: str) -> RefModOperand:
    from cobol_asg.ref_mod import RefModReference

    return RefModOperand(name=name, ref_mod_start=RefModReference(name=start_name))
```

**Note for the implementer:** `RefModLiteral` and `RefModReference` field names must be read off `cobol_asg/ref_mod.py:21-49`; the docstring at `ref_mod.py:140-142` shows `RefModLiteral("2")` positionally. Correct the helpers if the keyword names differ.

- [ ] **Step 3: Run them to verify they fail**

Run: `cd cobble && uv run pytest tests/dataflow/fields/test_extent.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobble.dataflow.fields'`

- [ ] **Step 4: Write `fields/__init__.py`**

```python
"""Field-level byte dataflow: which bytes a field's value came from.

Cobble's source CFG chains statements by matching operand name strings, so a
write to a group member and a read of the group are unrelated events and
INITIALIZE kills nothing. A MOVE copies a byte range, and stating the analysis
over byte extents makes group containment, REDEFINES aliasing, OCCURS striding
and reference modification fall out of range overlap rather than needing a rule
each.

The alias algebra is cobol_memory's, extracted from the interpreter's own
field-level dataflow: may_alias over-approximates, so an edge survives when
overlap is uncertain; must_cover under-approximates, so only an EXACT extent
may kill a definition and a computed subscript never does. The extents come
from cobble.dataflow.layout, the control flow from cobble.dataflow.srccfg.

See docs/superpowers/specs/2026-09-05-field-level-byte-dataflow-design.md.
"""
```

- [ ] **Step 5: Write `extent.py`**

```python
"""A structured ASG operand to the byte extents it denotes.

srccfg's Node carries operand names only, so this reads the typed ASG operand
instead: RefModOperand keeps subscripts and reference modification, and both are
what separate an EXACT extent from a CLAMPED one. Three quarters of the corpus's
subscripted MOVE operands compute their subscript, so CLAMPED is the common case
for a subscripted write, not a corner.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

from cobol_asg.cobol_expression import BinOpNode, LiteralNode
from cobol_asg.ref_mod import (
    FunctionCallOperand,
    RefModBinOp,
    RefModLiteral,
    RefModOperand,
)

from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId

from cobble.dataflow.layout import Cell, Record

_REGIONS = MappingProxyType(
    {
        "WORKING-STORAGE": RegionId.WORKING_STORAGE,
        "LINKAGE": RegionId.LINKAGE,
        "LOCAL-STORAGE": RegionId.LOCAL_STORAGE,
        "FILE": RegionId.FILE,
    }
)

_FIGURATIVE = frozenset(
    {"SPACE", "SPACES", "ZERO", "ZEROS", "ZEROES", "LOW-VALUES", "HIGH-VALUES", "QUOTES", "NULL", "NULLS"}
)

NO_EXTENT_REASONS = frozenset({"unknown-name", "length-of", "function", "figurative"})

_ARITHMETIC = MappingProxyType(
    {
        "+": lambda a, b: a + b,
        "-": lambda a, b: a - b,
        "*": lambda a, b: a * b,
        "/": lambda a, b: a // b,
    }
)


@dataclass(frozen=True)
class OperandExtents:
    """The extents an operand denotes, or why it denotes none."""

    extents: tuple[FieldExtent, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class CellIndex:
    """Every cell a name can denote in one program, with its region."""

    by_name: Mapping[str, tuple[Cell, ...]]
    by_decl: Mapping[int, tuple[Cell, ...]]
    regions: Mapping[str, RegionId]
    ordered: tuple[Cell, ...]

    @classmethod
    def of(cls, records: tuple[Record, ...]) -> CellIndex:
        cells = tuple(cell for record in records for cell in record.cells)
        by_name: dict[str, list[Cell]] = {}
        by_decl: dict[int, list[Cell]] = {}
        for cell in cells:
            by_name.setdefault(cell.name, []).append(cell)
            by_decl.setdefault(cell.decl, []).append(cell)
        return cls(
            by_name=MappingProxyType({k: tuple(v) for k, v in by_name.items()}),
            by_decl=MappingProxyType({k: tuple(v) for k, v in by_decl.items()}),
            regions=MappingProxyType(
                {record.name: _REGIONS[record.origin] for record in records}
            ),
            ordered=cells,
        )

    def region_of(self, cell: Cell) -> RegionId:
        return self.regions[cell.record]

    def extent_of(self, cell: Cell) -> FieldExtent:
        return FieldExtent(
            region=self.region_of(cell),
            start=cell.start,
            length=cell.length,
            precision=Precision.EXACT,
            field_name=cell.name,
        )

    def cells_named(
        self, name: str, qualifiers: tuple[str, ...], arity: int
    ) -> tuple[Cell, ...]:
        return tuple(
            cell
            for cell in self.by_name.get(name, ())
            if len(cell.index) == arity
            and all(qualifier in cell.path for qualifier in qualifiers)
        )

    def elementary_within(self, extent: FieldExtent) -> tuple[Cell, ...]:
        """The elementary cells this extent fully contains, in record order."""
        return tuple(
            cell
            for cell in self.ordered
            if self.region_of(cell) is extent.region
            and not _is_group(cell)
            and cell.start >= extent.start
            and cell.end <= extent.end
        )

    def containing(self, extent: FieldExtent) -> tuple[Cell, ...]:
        return tuple(
            cell
            for cell in self.ordered
            if self.region_of(cell) is extent.region
            and cell.start <= extent.start
            and cell.end >= extent.end
        )


def _is_group(cell: Cell) -> bool:
    return cell.is_group


def _const(node) -> int | None:
    """The integer an expression folds to, or None if it depends on runtime state."""
    match node:
        case LiteralNode(value=value) | RefModLiteral(value=value):
            return int(value) if str(value).lstrip("+-").isdigit() else None
        case BinOpNode(op=op, left=left, right=right) | RefModBinOp(
            op=op, left=left, right=right
        ):
            operands = (_const(left), _const(right))
            operation = _ARITHMETIC.get(op)
            if operation is None or None in operands:
                return None
            return operation(*operands)
        case _:
            return None


def _clamped_over(cells: tuple[Cell, ...], index: CellIndex, name: str) -> FieldExtent:
    start = min(cell.start for cell in cells)
    end = max(cell.end for cell in cells)
    return FieldExtent(
        region=index.region_of(cells[0]),
        start=start,
        length=end - start,
        precision=Precision.CLAMPED,
        field_name=name,
    )


def _subscripted(
    operand: RefModOperand, candidates: tuple[Cell, ...], index: CellIndex
) -> tuple[FieldExtent, ...]:
    wanted = tuple(_const(subscript) for subscript in operand.subscripts)
    if None in wanted:
        return tuple(
            _clamped_over(index.by_decl[decl], index, operand.name)
            for decl in dict.fromkeys(cell.decl for cell in candidates)
        )
    return tuple(
        index.extent_of(cell) for cell in candidates if cell.index == tuple(wanted)
    )


def _ref_modified(extent: FieldExtent, operand: RefModOperand) -> FieldExtent:
    """COBOL reference modification is 1-based: WS-F(2:3) starts one byte in."""
    start = _const(operand.ref_mod_start)
    length = (
        _const(operand.ref_mod_length) if operand.ref_mod_length is not None else None
    )
    if start is None or (operand.ref_mod_length is not None and length is None):
        return replace(extent, precision=Precision.CLAMPED)
    absolute = extent.start + start - 1
    return replace(
        extent,
        start=absolute,
        length=extent.end - absolute if length is None else length,
    )


def operand_extents(operand, index: CellIndex) -> OperandExtents:
    if isinstance(operand, FunctionCallOperand):
        return OperandExtents(reason="function")
    if operand.length_of:
        return OperandExtents(reason="length-of")
    candidates = index.cells_named(
        operand.name, operand.qualifiers, len(operand.subscripts)
    )
    if not candidates:
        reason = "figurative" if operand.name in _FIGURATIVE else "unknown-name"
        return OperandExtents(reason=reason)
    extents = (
        _subscripted(operand, candidates, index)
        if operand.subscripts
        else tuple(index.extent_of(cell) for cell in candidates)
    )
    if operand.ref_mod_start is not None:
        extents = tuple(_ref_modified(extent, operand) for extent in extents)
    if not extents:
        return OperandExtents(reason="unknown-name")
    return OperandExtents(extents=extents)
```

- [ ] **Step 6: Run the extent tests**

Run: `cd cobble && uv run pytest tests/dataflow/fields/test_extent.py -v`
Expected: PASS (12 tests). If `Cell.is_group` does not exist under that name, read `layout.py`'s `Cell` properties and use the real one — `_is_group` is the only place it is referenced.

- [ ] **Step 7: Format and commit**

```bash
cd cobble && uv run black cobble tests
cd /Users/avisheksengupta/code/red-dragon-forge && git add cobble/cobble/dataflow/fields cobble/tests/dataflow/fields
git commit -m "feat(cobble): a structured MOVE operand to its byte extents"
```

---

## Task 3: `state.py` and `transfer.py` — GEN/KILL per statement class

Closes bead `pr2` as rescoped ("operand-to-extent construction only" plus the transfer rules).

**Files:**
- Create: `cobble/cobble/dataflow/fields/state.py`
- Create: `cobble/cobble/dataflow/fields/transfer.py`
- Test: `cobble/tests/dataflow/fields/test_state.py`, `cobble/tests/dataflow/fields/test_transfer.py`

**Interfaces:**
- Consumes: Task 2's `CellIndex`, `operand_extents`, `OperandExtents`; `cobol_memory.field_extent.{FieldExtent, Precision}`; `cobol_asg.cobol_statements.{MoveStatement, InitializeStatement, ArithmeticStatement, ComputeStatement, StringStatement, ReadStatement, CallStatement}` and the dialect `ExecCicsStatement`.
- Produces:
  - `state.Source(origin: str, extent: FieldExtent | None, node: str)`; `state.State` (a `Mapping[FieldExtent, frozenset[Source]]`); `state.EMPTY`; `state.join(left, right) -> State`; `state.write(state, target, sources) -> State`; `state.reaching(state, read) -> frozenset[Source]`.
  - `transfer.HANDLED: tuple[type, ...]` — every statement class `transfer` dispatches on, so `fixpoint` and the corpus driver can measure what they skipped.
  - `transfer.transfer(statement, node: str, state: State, index: CellIndex) -> State`.

**Transfer rules, from the spec, in the order `transfer` must dispatch them:**

| statement | rule |
| --- | --- |
| `MoveStatement`, both operands DISPLAY, target a group | per elementary cell the target covers, the source's byte range at the matching relative offset; a target longer than the source takes `LITERAL SPACES` on the tail |
| `MoveStatement`, otherwise | whole target from whole source. A COMP operand has no byte-wise digit correspondence and a scale difference realigns on the decimal point, so this is exact rather than a widening |
| target extent `CLAMPED` | weak update — GEN without KILL, on every rule |
| `InitializeStatement` | every elementary extent in each named group takes `LITERAL` |
| `ArithmeticStatement`, `ComputeStatement`, `StringStatement` | whole target takes the union of every operand extent |
| `ReadStatement` with `INTO` | target takes `FILE:<name>` |
| `ExecCicsStatement` `READ`/`READNEXT`/`RECEIVE MAP` with `INTO`/`SET` | target takes `FILE:<file>` or `%CICS-STATE` |
| `CallStatement`, and `ExecCicsStatement` `LINK`/`XCTL` | every `USING` operand extent takes `%CALL:<target>`. A real summary is the deferred second plan's job; this records the seam so a coverage measurement is not silently crediting it as analysed |

- [ ] **Step 1: Write the failing state tests**

`cobble/tests/dataflow/fields/test_state.py`:

```python
"""The lattice, and the one asymmetry the whole analysis rests on."""

from __future__ import annotations

from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId

from cobble.dataflow.fields.state import EMPTY, Source, join, reaching, write


def _extent(start: int, length: int, precision=Precision.EXACT, name="WS-A"):
    return FieldExtent(
        region=RegionId.WORKING_STORAGE,
        start=start,
        length=length,
        precision=precision,
        field_name=name,
    )


def _source(name: str) -> Source:
    return Source(origin="", extent=_extent(100, 4, name=name), node="MAIN/0")


def test_an_exact_write_kills_the_definition_it_covers():
    first = write(EMPTY, _extent(0, 4), frozenset({_source("WS-OLD")}))
    second = write(first, _extent(0, 4), frozenset({_source("WS-NEW")}))
    assert {s.extent.field_name for s in reaching(second, _extent(0, 4))} == {"WS-NEW"}


def test_a_clamped_write_never_kills():
    """Precision.CLAMPED cannot cover, so a computed subscript is a weak update."""
    first = write(EMPTY, _extent(0, 4), frozenset({_source("WS-OLD")}))
    second = write(
        first, _extent(0, 4, precision=Precision.CLAMPED), frozenset({_source("WS-NEW")})
    )
    names = {s.extent.field_name for s in reaching(second, _extent(0, 4))}
    assert names == {"WS-OLD", "WS-NEW"}


def test_a_write_does_not_kill_a_definition_it_only_partly_covers():
    first = write(EMPTY, _extent(0, 8), frozenset({_source("WS-OLD")}))
    second = write(first, _extent(0, 4), frozenset({_source("WS-NEW")}))
    names = {s.extent.field_name for s in reaching(second, _extent(4, 4))}
    assert "WS-OLD" in names


def test_a_read_matches_by_overlap_not_by_equality():
    state = write(EMPTY, _extent(0, 8), frozenset({_source("WS-OLD")}))
    assert reaching(state, _extent(6, 4))


def test_a_read_of_a_disjoint_range_sees_nothing():
    state = write(EMPTY, _extent(0, 4), frozenset({_source("WS-OLD")}))
    assert reaching(state, _extent(8, 4)) == frozenset()


def test_join_is_union():
    left = write(EMPTY, _extent(0, 4), frozenset({_source("WS-L")}))
    right = write(EMPTY, _extent(0, 4), frozenset({_source("WS-R")}))
    names = {s.extent.field_name for s in reaching(join(left, right), _extent(0, 4))}
    assert names == {"WS-L", "WS-R"}


def test_join_of_a_state_with_itself_is_that_state():
    left = write(EMPTY, _extent(0, 4), frozenset({_source("WS-L")}))
    assert join(left, left) == left
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd cobble && uv run pytest tests/dataflow/fields/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobble.dataflow.fields.state'`

- [ ] **Step 3: Write `state.py`**

```python
"""What reaches an extent, and how a write changes it.

The governing asymmetry is cobol_memory's: a read matches by may_alias, which
over-approximates, so provenance survives when overlap is uncertain; a write
kills only where must_cover holds, which under-approximates, so a CLAMPED
extent -- a computed subscript -- adds provenance without ever removing any.
Getting that backwards would drop real edges rather than keep spurious ones.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TypeAlias

from cobol_memory.field_extent import FieldExtent

LITERAL = "LITERAL"
CICS_STATE = "%CICS-STATE"


@dataclass(frozen=True)
class Source:
    """Where a value came from: another extent, or a synthetic origin.

    ``origin`` is empty exactly when ``extent`` is set. ``node`` is the CFG node
    id that wrote it, which is how a reader recovers the guard conditions this
    lattice deliberately does not carry.
    """

    origin: str
    extent: FieldExtent | None
    node: str


State: TypeAlias = Mapping[FieldExtent, frozenset[Source]]

EMPTY: State = MappingProxyType({})


def join(left: State, right: State) -> State:
    merged = dict(left)
    for extent, sources in right.items():
        merged[extent] = merged.get(extent, frozenset()) | sources
    return MappingProxyType(merged)


def write(state: State, target: FieldExtent, sources: frozenset[Source]) -> State:
    survivors = {
        extent: held
        for extent, held in state.items()
        if not target.must_cover(extent)
    }
    survivors[target] = survivors.get(target, frozenset()) | sources
    return MappingProxyType(survivors)


def reaching(state: State, read: FieldExtent) -> frozenset[Source]:
    return frozenset(
        source
        for extent, sources in state.items()
        if read.may_alias(extent)
        for source in sources
    )
```

- [ ] **Step 4: Run the state tests**

Run: `cd cobble && uv run pytest tests/dataflow/fields/test_state.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Write the failing transfer tests**

`cobble/tests/dataflow/fields/test_transfer.py`:

```python
"""One case per transfer rule in the design, plus the weak-update asymmetry."""

from __future__ import annotations

from cobble.dataflow.fields.state import EMPTY, reaching
from cobble.dataflow.fields.transfer import transfer

from .conftest import field


def _names_reaching(state, index, name: str) -> set[str]:
    from cobol_asg.ref_mod import RefModOperand

    from cobble.dataflow.fields.extent import operand_extents

    (extent,) = operand_extents(RefModOperand(name=name), index).extents
    return {
        source.origin or source.extent.field_name
        for source in reaching(state, extent)
    }


def _move(source: str, *targets: str) -> dict:
    return {
        "type": "MOVE",
        "operands": [{"name": source}, *({"name": t} for t in targets)],
    }


def test_an_alphanumeric_move_gives_the_target_the_source(program_of, index_of):
    asg = program_of(
        [_move("WS-A", "WS-B")],
        data_fields=[
            field(1, "REC", children=[field(5, "WS-A", "X(4)"), field(5, "WS-B", "X(4)")])
        ],
    )
    index = index_of(asg)
    state = transfer(asg.paragraphs[0].statements[0], "MAIN/0", EMPTY, index)
    assert _names_reaching(state, index, "WS-B") == {"WS-A"}


def test_a_move_distributes_to_every_receiving_field(program_of, index_of):
    asg = program_of(
        [_move("WS-A", "WS-B", "WS-C")],
        data_fields=[
            field(
                1,
                "REC",
                children=[
                    field(5, "WS-A", "X(4)"),
                    field(5, "WS-B", "X(4)"),
                    field(5, "WS-C", "X(4)"),
                ],
            )
        ],
    )
    index = index_of(asg)
    state = transfer(asg.paragraphs[0].statements[0], "MAIN/0", EMPTY, index)
    assert _names_reaching(state, index, "WS-C") == {"WS-A"}


def test_a_group_move_lands_on_each_covered_member_at_its_own_offset(
    program_of, index_of
):
    """The case names cannot express: two copybook names over one piece of storage."""
    asg = program_of(
        [_move("REC-SRC", "REC-DST")],
        data_fields=[
            field(
                1,
                "REC-SRC",
                children=[field(5, "SRC-ONE", "X(4)"), field(5, "SRC-TWO", "X(6)")],
            ),
            field(
                1,
                "REC-DST",
                children=[field(5, "DST-ONE", "X(4)"), field(5, "DST-TWO", "X(6)")],
            ),
        ],
    )
    index = index_of(asg)
    state = transfer(asg.paragraphs[0].statements[0], "MAIN/0", EMPTY, index)
    assert _names_reaching(state, index, "DST-ONE") == {"SRC-ONE"}
    assert _names_reaching(state, index, "DST-TWO") == {"SRC-TWO"}


def test_a_group_move_into_a_longer_target_pads_the_tail_with_a_literal(
    program_of, index_of
):
    asg = program_of(
        [_move("REC-SRC", "REC-DST")],
        data_fields=[
            field(1, "REC-SRC", children=[field(5, "SRC-ONE", "X(4)")]),
            field(
                1,
                "REC-DST",
                children=[field(5, "DST-ONE", "X(4)"), field(5, "DST-TAIL", "X(6)")],
            ),
        ],
    )
    index = index_of(asg)
    state = transfer(asg.paragraphs[0].statements[0], "MAIN/0", EMPTY, index)
    assert _names_reaching(state, index, "DST-TAIL") == {"LITERAL SPACES"}


def test_a_comp_operand_gets_whole_to_whole_with_no_byte_split(program_of, index_of):
    asg = program_of(
        [_move("WS-BIN", "REC-DST")],
        data_fields=[
            field(1, "REC-SRC", children=[field(5, "WS-BIN", "9(8)", usage="COMP")]),
            field(
                1,
                "REC-DST",
                children=[field(5, "DST-ONE", "X(2)"), field(5, "DST-TWO", "X(2)")],
            ),
        ],
    )
    index = index_of(asg)
    state = transfer(asg.paragraphs[0].statements[0], "MAIN/0", EMPTY, index)
    assert _names_reaching(state, index, "REC-DST") == {"WS-BIN"}
    assert _names_reaching(state, index, "DST-ONE") == {"WS-BIN"}


def test_a_computed_subscript_target_is_a_weak_update(program_of, index_of):
    asg = program_of(
        [
            _move("WS-A", "WS-T"),
            {
                "type": "MOVE",
                "operands": [
                    {"name": "WS-B"},
                    {"name": "WS-T", "subscripts": [{"kind": "ref", "name": "WS-I"}]},
                ],
            },
        ],
        data_fields=[
            field(
                1,
                "REC",
                children=[
                    field(5, "WS-A", "X(4)"),
                    field(5, "WS-B", "X(4)"),
                    field(5, "WS-T", "X(4)", occurs=3),
                    field(5, "WS-I", "9(4)"),
                ],
            )
        ],
    )
    index = index_of(asg)
    statements = asg.paragraphs[0].statements
    state = transfer(statements[0], "MAIN/0", EMPTY, index)
    state = transfer(statements[1], "MAIN/1", state, index)
    assert _names_reaching(state, index, "WS-T") == {"WS-A", "WS-B"}


def test_initialize_gives_every_member_a_literal(program_of, index_of):
    asg = program_of(
        [{"type": "INITIALIZE", "operands": [{"name": "REC"}]}],
        data_fields=[
            field(1, "REC", children=[field(5, "WS-A", "X(4)"), field(5, "WS-B", "X(4)")])
        ],
    )
    index = index_of(asg)
    state = transfer(asg.paragraphs[0].statements[0], "MAIN/0", EMPTY, index)
    assert _names_reaching(state, index, "WS-B") == {"LITERAL"}


def test_add_gives_the_target_the_union_of_its_operands(program_of, index_of):
    asg = program_of(
        [{"type": "ADD", "operands": [{"name": "WS-A"}, {"name": "WS-B"}]}],
        data_fields=[
            field(1, "REC", children=[field(5, "WS-A", "9(4)"), field(5, "WS-B", "9(4)")])
        ],
    )
    index = index_of(asg)
    state = transfer(asg.paragraphs[0].statements[0], "MAIN/0", EMPTY, index)
    assert _names_reaching(state, index, "WS-B") >= {"WS-A", "WS-B"}


def test_an_unhandled_statement_leaves_the_state_untouched(program_of, index_of):
    asg = program_of(
        [{"type": "DISPLAY", "operands": [{"name": "WS-A"}]}],
        data_fields=[field(1, "REC", children=[field(5, "WS-A", "X(4)")])],
    )
    index = index_of(asg)
    state = transfer(asg.paragraphs[0].statements[0], "MAIN/0", EMPTY, index)
    assert state == EMPTY
```

**Note for the implementer:** the ASG dict shapes for `INITIALIZE` and `ADD` (`operands` vs named fields, and where an `ADD`'s target lives) must be read off `cobol_asg/cobol_statements.py:646 InitializeStatement.from_dict` and `:242 ArithmeticStatement.from_dict`. Correct the test dicts and the transfer code to the real shapes — the assertions are the requirement, the dict spellings are not.

- [ ] **Step 6: Run to verify they fail**

Run: `cd cobble && uv run pytest tests/dataflow/fields/test_transfer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobble.dataflow.fields.transfer'`

- [ ] **Step 7: Write `transfer.py`**

```python
"""One statement plus an in-state to an out-state.

Dispatch is by statement class, and a class this module does not name leaves the
state untouched -- visibly unhandled rather than silently mis-analysed. There is
no universal "is a statement" predicate to lean on: cobol_asg has no statement
base class and its dispatch table excludes the dialect-parsed EXEC CICS and
EXEC SQL forms this module needs.
"""

from __future__ import annotations

from dataclasses import replace

from cobol_asg.cobol_statements import (
    ArithmeticStatement,
    CallStatement,
    ComputeStatement,
    InitializeStatement,
    MoveStatement,
    ReadStatement,
    StringStatement,
)

from cobol_memory.field_extent import FieldExtent, Precision

from cobble.dataflow.fields.extent import CellIndex, operand_extents
from cobble.dataflow.fields.state import LITERAL, Source, State, write

LITERAL_SPACES = "LITERAL SPACES"

_DISPLAY_USAGES = frozenset({"", "DISPLAY"})


def _sources(extents: tuple[FieldExtent, ...], node: str) -> frozenset[Source]:
    return frozenset(Source(origin="", extent=e, node=node) for e in extents)


def _synthetic(origin: str, node: str) -> frozenset[Source]:
    return frozenset({Source(origin=origin, extent=None, node=node)})


def _slice(extent: FieldExtent, offset: int, length: int) -> FieldExtent:
    return replace(extent, start=extent.start + offset, length=length)


def _is_display(extent: FieldExtent, index: CellIndex) -> bool:
    containing = index.containing(extent)
    return all(cell.usage.upper() in _DISPLAY_USAGES for cell in containing)


def _move_bytewise(
    source: FieldExtent, target: FieldExtent, node: str, state: State, index: CellIndex
) -> State:
    """Left-aligned at matching relative offset, min length, spaces on the tail."""
    covered = index.elementary_within(target)
    if not covered:
        return write(state, target, _sources((source,), node))
    for cell in covered:
        offset = cell.start - target.start
        piece = index.extent_of(cell)
        if offset >= source.length:
            state = write(state, piece, _synthetic(LITERAL_SPACES, node))
            continue
        taken = min(cell.length, source.length - offset)
        state = write(
            state, piece, _sources((_slice(source, offset, taken),), node)
        )
    return state


def _move(statement: MoveStatement, node: str, state: State, index: CellIndex) -> State:
    sources = operand_extents(statement.source, index)
    for operand in statement.targets:
        targets = operand_extents(operand, index)
        for target in targets.extents:
            state = _one_move(sources, target, node, state, index)
    return state


def _one_move(
    sources, target: FieldExtent, node: str, state: State, index: CellIndex
) -> State:
    if not sources.extents:
        return write(state, target, _synthetic(sources.reason.upper(), node))
    bytewise = (
        target.precision is Precision.EXACT
        and _is_display(target, index)
        and all(_is_display(s, index) for s in sources.extents)
        and len(sources.extents) == 1
    )
    if bytewise:
        return _move_bytewise(sources.extents[0], target, node, state, index)
    return write(state, target, _sources(sources.extents, node))


def _initialize(statement, node: str, state: State, index: CellIndex) -> State:
    for operand in statement.operands:
        for group in operand_extents(operand, index).extents:
            for cell in index.elementary_within(group) or ():
                state = write(state, index.extent_of(cell), _synthetic(LITERAL, node))
    return state


def _union_into_targets(operands, targets, node: str, state: State, index) -> State:
    every = tuple(
        extent
        for operand in operands
        for extent in operand_extents(operand, index).extents
    )
    for operand in targets:
        for target in operand_extents(operand, index).extents:
            state = write(state, target, _sources(every, node))
    return state


def _read_into(statement, node: str, state: State, index: CellIndex) -> State:
    origin = f"FILE:{statement.file_name}"
    for operand in _into_operands(statement):
        for target in operand_extents(operand, index).extents:
            state = write(state, target, _synthetic(origin, node))
    return state


HANDLED: tuple[type, ...] = (
    MoveStatement,
    InitializeStatement,
    ArithmeticStatement,
    ComputeStatement,
    StringStatement,
    ReadStatement,
    CallStatement,
)


def transfer(statement, node: str, state: State, index: CellIndex) -> State:
    match statement:
        case MoveStatement():
            return _move(statement, node, state, index)
        case InitializeStatement():
            return _initialize(statement, node, state, index)
        case ArithmeticStatement() | ComputeStatement() | StringStatement():
            return _union_into_targets(
                _read_operands(statement),
                _target_operands(statement),
                node,
                state,
                index,
            )
        case ReadStatement():
            return _read_into(statement, node, state, index)
        case CallStatement():
            return _call(statement, node, state, index)
        case _:
            return _exec_cics(statement, node, state, index)
```

**Note for the implementer:** `_read_operands`, `_target_operands`, `_into_operands`, `_call` and `_exec_cics` are yours to write against the real statement classes — read `cobol_asg/cobol_statements.py` for `ArithmeticStatement` (`:242`), `ComputeStatement` (`:352`, note `ComputeTarget` at `:325`), `StringStatement` (`:738`, note `StringSending` at `:699`), `ReadStatement`, and `CallStatement` (`:1027`, note `CallUsingParam` at `:1000`); and `cobble/cobble/dataflow/depgraph/cics_cache.py` for how the dialect `ExecCicsStatement` arrives and what its verb and options look like. `_exec_cics` must return `state` unchanged for any object it does not recognise — that is the `case _` fallback the last test pins. Add `ExecCicsStatement` to `HANDLED` once you have its import path.

- [ ] **Step 8: Run the transfer tests**

Run: `cd cobble && uv run pytest tests/dataflow/fields/test_transfer.py -v`
Expected: PASS (9 tests)

- [ ] **Step 9: Format and commit**

```bash
cd cobble && uv run black cobble tests
cd /Users/avisheksengupta/code/red-dragon-forge && git add cobble/cobble/dataflow/fields cobble/tests/dataflow/fields
git commit -m "feat(cobble): byte-extent transfer functions per statement class"
```

---

## Task 4: `fixpoint.py` — the paragraph-keyed intra-program worklist

Closes bead `ujr`.

**Files:**
- Create: `cobble/cobble/dataflow/fields/fixpoint.py`
- Test: `cobble/tests/dataflow/fields/test_fixpoint.py`

**Interfaces:**
- Consumes: `cobble.dataflow.srccfg.build.build_program`, `cobble.dataflow.srccfg.cfg.{Cfg, Node}`, `cobble.dataflow.srccfg.statements.statement_index`, Task 3's `transfer`/`HANDLED`, Task 2's `CellIndex`.
- Produces:
  - `FlowEdge(source: Source, target: FieldExtent, node: str)`.
  - `ProgramFlow(program: str, edges: tuple[FlowEdge, ...] = (), writes: int = 0, covered: int = 0, unhandled: int = 0, dequeues: int = 0, skipped: str = "")`.
  - `analyse(asg, index: CellIndex) -> ProgramFlow` — builds the CFG and the statement index itself, so a caller needs one call per program.
  - `analysed(asg) -> tuple[ProgramFlow, CellIndex | None]` — builds the index too, turning `UnsizeableFieldError` into a `ProgramFlow` with `skipped` set. This is the entry point `emit` and the acceptance suite call; `analyse` is the one that assumes an index exists.
  - `ITERATION_FACTOR: int = 50` — the defensive dequeue cap, `ITERATION_FACTOR * paragraph count`.

**Why paragraph-keyed:** the `ujr` spike measured loop fixpoints as cheap (11,826 loops settled in one iteration, 1,599 in two, the 30-iteration cap never reached). The cost was recursive PERFORM inlining re-analysing a paragraph once per call path — `PROG-WORST` took 710.58s. Storing each paragraph's **entry state** and re-analysing only when that entry state changes bounds work at O(paragraphs × state changes) and removes the need for a depth cap.

**`covered` is the number this task exists to report.** The `3ao` post-mortem found the srccfg acceptance suite passing while the walk reached 18% of nodes, because nothing measured reach. `writes` counts write operands whose extents resolved; `covered` counts those that produced at least one edge; `unhandled` counts statements of a class `transfer` does not dispatch. Task 7 asserts a floor on `covered / writes`.

- [ ] **Step 1: Write the failing fixpoint tests**

`cobble/tests/dataflow/fields/test_fixpoint.py`:

```python
"""Convergence, PERFORM re-entry, and the coverage counters.

Termination is not the property under test -- coverage is. The 3ao post-mortem
found an acceptance suite passing while its walk reached 18% of nodes, because
nothing measured reach.
"""

from __future__ import annotations

from cobble.dataflow.fields.fixpoint import analyse, analysed

from .conftest import field


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


_FIELDS = [
    field(
        1,
        "REC",
        children=[
            field(5, "WS-A", "X(4)"),
            field(5, "WS-B", "X(4)"),
            field(5, "WS-C", "X(4)"),
        ],
    )
]


def _flow(program_of, index_of, paragraphs: list[dict]):
    asg = program_of([], paragraphs=paragraphs, data_fields=_FIELDS)
    return analyse(asg, index_of(asg))


def _pairs(flow) -> set[tuple[str, str]]:
    return {
        (edge.source.origin or edge.source.extent.field_name, edge.target.field_name)
        for edge in flow.edges
    }


def test_a_chain_within_one_paragraph_yields_both_edges(program_of, index_of):
    flow = _flow(
        program_of,
        index_of,
        [{"name": "MAIN", "statements": [_move("WS-A", "WS-B"), _move("WS-B", "WS-C")]}],
    )
    assert {("WS-A", "WS-B"), ("WS-B", "WS-C")} <= _pairs(flow)


def test_provenance_crosses_a_paragraph_boundary_by_fallthrough(program_of, index_of):
    flow = _flow(
        program_of,
        index_of,
        [
            {"name": "MAIN", "statements": [_move("WS-A", "WS-B")]},
            {"name": "NEXT-PARA", "statements": [_move("WS-B", "WS-C")]},
        ],
    )
    assert ("WS-B", "WS-C") in _pairs(flow)


def test_a_loop_converges_and_does_not_hang(program_of, index_of):
    flow = _flow(
        program_of,
        index_of,
        [
            {
                "name": "MAIN",
                "statements": [
                    {
                        "type": "PERFORM",
                        "target": "LOOP-PARA",
                        "until": {"kind": "lit", "value": "1"},
                    }
                ],
            },
            {"name": "LOOP-PARA", "statements": [_move("WS-A", "WS-B")]},
        ],
    )
    assert ("WS-A", "WS-B") in _pairs(flow)


def test_a_paragraph_performed_from_two_sites_is_not_analysed_per_call_path(
    program_of, index_of
):
    """Keying on paragraph entry state is what stops the ujr blowup."""
    flow = _flow(
        program_of,
        index_of,
        [
            {
                "name": "MAIN",
                "statements": [
                    {"type": "PERFORM", "target": "SHARED"},
                    {"type": "PERFORM", "target": "SHARED"},
                ],
            },
            {"name": "SHARED", "statements": [_move("WS-A", "WS-B")]},
        ],
    )
    assert flow.dequeues <= 4 * len(("MAIN", "SHARED"))


def test_every_resolvable_write_is_covered_in_a_program_with_no_unknown_names(
    program_of, index_of
):
    flow = _flow(
        program_of,
        index_of,
        [{"name": "MAIN", "statements": [_move("WS-A", "WS-B"), _move("WS-B", "WS-C")]}],
    )
    assert flow.writes > 0
    assert flow.covered == flow.writes


def test_an_unsizeable_program_is_recorded_not_dropped(program_of):
    """layout.UnsizeableFieldError must surface as a skip with a reason.

    Building the index is where it raises, so the guard lives in analysed(),
    not in analyse() -- which is why the two entry points exist.
    """
    asg = program_of(
        [_move("WS-A", "WS-B")],
        data_fields=[field(1, "REC", children=[field(5, "WS-A", "9(40)", usage="COMP")])],
    )
    flow, index = analysed(asg)
    assert flow.skipped
    assert flow.edges == ()
    assert index is None
```

**Note for the implementer:** this test needs a field declaration `layout` genuinely refuses to size. `9(40) COMP` is the candidate; if `layout` sizes it without complaint, read `layout.py`'s `UnsizeableFieldError` raise sites and pick a declaration that reaches one. The `PERFORM` dict shape must be read off `cobol_asg/cobol_statements.py` `PerformStatement.from_dict` and `cobble/tests/dataflow/srccfg/test_desugar_perform.py`.

- [ ] **Step 2: Run to verify they fail**

Run: `cd cobble && uv run pytest tests/dataflow/fields/test_fixpoint.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobble.dataflow.fields.fixpoint'`

- [ ] **Step 3: Write `fixpoint.py`**

```python
"""Intra-program worklist over paragraph entry states.

The ujr spike measured loop fixpoints as cheap -- 11,826 loops settled in one
iteration, 1,599 in two, the 30-iteration cap never reached. The cost was
recursive PERFORM inlining re-analysing a paragraph once per call path, which
took 710.58s on the corpus's worst member. Storing each paragraph's entry state
and re-analysing only when that entry state changes bounds the work at
O(paragraphs x state changes), and needs no depth cap.

Termination does not rest on the cap: every extent a transfer can construct is
fixed by the statement set before iteration begins -- a group MOVE yields one
per covered target field and the offset arithmetic is per-statement -- so the
lattice has finite height. The cap is a defence against a defect, not part of
the argument, and it logs rather than silently truncating.

Edges come from diffing the state a transfer returned against the one it was
given, rather than from instrumenting state.write. The transfer functions stay
pure that way, and the diff is exact: a (source, target) pair present after and
absent before is precisely a flow this statement created.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass

from cobol_memory.field_extent import FieldExtent

from cobble.dataflow.fields.extent import CellIndex
from cobble.dataflow.fields.state import EMPTY, Source, State, join
from cobble.dataflow.fields.transfer import HANDLED, transfer
from cobble.dataflow.layout import UnsizeableFieldError, program_records
from cobble.dataflow.srccfg.build import build_program
from cobble.dataflow.srccfg.statements import statement_index

logger = logging.getLogger(__name__)

ITERATION_FACTOR = 50


@dataclass(frozen=True)
class FlowEdge:
    source: Source
    target: FieldExtent
    node: str


@dataclass(frozen=True)
class ProgramFlow:
    program: str
    edges: tuple[FlowEdge, ...] = ()
    writes: int = 0
    covered: int = 0
    unhandled: int = 0
    dequeues: int = 0
    skipped: str = ""


def _new_edges(before: State, after: State, node: str) -> tuple[FlowEdge, ...]:
    return tuple(
        FlowEdge(source=source, target=target, node=node)
        for target, sources in after.items()
        for source in sources - before.get(target, frozenset())
    )


def _run_paragraph(nodes, statements, entry: State, index: CellIndex):
    state = entry
    edges: list[FlowEdge] = []
    writes = covered = unhandled = 0
    for node_id in nodes:
        statement = statements.get(node_id)
        if statement is None:
            continue
        if not isinstance(statement, HANDLED):
            unhandled += 1
            continue
        after = transfer(statement, node_id, state, index)
        created = _new_edges(state, after, node_id)
        touched = {edge.target for edge in created}
        writes += len(set(after) - set(state)) + len(touched)
        covered += len(touched)
        edges.extend(created)
        state = after
    return state, tuple(edges), writes, covered, unhandled


def analyse(asg, index: CellIndex) -> ProgramFlow:
    cfg = build_program(asg)
    statements = statement_index(asg)
    order = _paragraph_node_ids(cfg)
    paragraphs = tuple(order)
    if not paragraphs:
        return ProgramFlow(program=cfg.program)
    entry: dict[str, State] = {paragraphs[0]: EMPTY}
    worklist = deque([paragraphs[0]])
    cap = ITERATION_FACTOR * len(paragraphs)
    edges: list[FlowEdge] = []
    writes = covered = unhandled = dequeues = 0
    while worklist:
        if dequeues >= cap:
            logger.warning(
                "fields: dequeue cap %d reached for %s (%d paragraphs)",
                cap,
                cfg.program,
                len(paragraphs),
            )
            return ProgramFlow(
                program=cfg.program,
                edges=tuple(edges),
                writes=writes,
                covered=covered,
                unhandled=unhandled,
                dequeues=dequeues,
                skipped=f"dequeue cap {cap} reached",
            )
        dequeues += 1
        paragraph = worklist.popleft()
        exit_state, created, wrote, hit, missed = _run_paragraph(
            order[paragraph], statements, entry[paragraph], index
        )
        edges.extend(created)
        writes += wrote
        covered += hit
        unhandled += missed
        for successor in _successor_paragraphs(cfg, order[paragraph]):
            joined = join(entry.get(successor, EMPTY), exit_state)
            if joined != entry.get(successor):
                entry[successor] = joined
                worklist.append(successor)
    return ProgramFlow(
        program=cfg.program,
        edges=tuple(edges),
        writes=writes,
        covered=covered,
        unhandled=unhandled,
        dequeues=dequeues,
    )


def analysed(asg) -> tuple[ProgramFlow, CellIndex | None]:
    """analyse, with the index built here so an unsizeable field is a skip.

    layout raises while computing extents, which is before any statement has
    been seen, so a program that cannot be laid out has no partial answer worth
    returning -- only a recorded reason. Never silently dropped.
    """
    try:
        index = CellIndex.of(program_records(asg))
    except UnsizeableFieldError as error:
        return ProgramFlow(program=_program_id(asg), skipped=str(error)), None
    return analyse(asg, index), index
```

**Note for the implementer:** `_paragraph_node_ids(cfg)`, `_successor_paragraphs(cfg, node_ids)` and `_program_id(asg)` are yours to write against the real `Cfg` surface. Read `cobble/cobble/dataflow/srccfg/cfg.py` and `build.py`: `Cfg` exposes `program`, `nodes`, `edges`, `node(id)`, `successors(id)`, `predecessors(id)`, `node_ids`, and `Node` exposes `id` plus whatever paragraph attribute it carries. `_paragraph_node_ids` must return an insertion-ordered `dict[str, tuple[str, ...]]` — paragraph name to its node ids in execution order — because `paragraphs[0]` is taken as the program entry. Derive the paragraph from the node id's `f"{paragraph}/"` prefix if `Node` has no paragraph field. `_successor_paragraphs` returns the paragraphs of every CFG successor of the paragraph's nodes that lies outside it.

One judgment call is yours: `_run_paragraph`'s `writes` counter must count **write operands whose extents resolved**, and the expression above approximates that from the state delta. If Step 4's `test_every_resolvable_write_is_covered_in_a_program_with_no_unknown_names` cannot be made to hold exactly, change `transfer` to also return a count of resolved write operands rather than weakening the assertion — the coverage ratio is Task 7's whole deliverable and an approximated denominator makes it unfalsifiable.

- [ ] **Step 4: Run the fixpoint tests**

Run: `cd cobble && uv run pytest tests/dataflow/fields/test_fixpoint.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the whole fields suite**

Run: `cd cobble && uv run pytest tests/dataflow/fields -q`
Expected: PASS

- [ ] **Step 6: Format and commit**

```bash
cd cobble && uv run black cobble tests
cd /Users/avisheksengupta/code/red-dragon-forge && git add cobble/cobble/dataflow/fields cobble/tests/dataflow/fields
git commit -m "feat(cobble): paragraph-keyed fixpoint over byte-extent state"
```

---

## Task 5: `naming.py` — an extent back to a field name

**Files:**
- Create: `cobble/cobble/dataflow/fields/naming.py`
- Test: `cobble/tests/dataflow/fields/test_naming.py`

**Interfaces:**
- Consumes: Task 2's `CellIndex`; `cobol_memory.field_extent.FieldExtent`.
- Produces: `smallest_covering(extent, index) -> str`; `covering_fields(extent, index) -> tuple[str, ...]`.

**Rules:** reports name the **smallest covering field**, so an edge reads `MST-COUNT` rather than `REC-MASTER`. Among the cells whose range contains the extent, take the shortest; break a tie by the deepest `level`, then by the longest `path`, then lexicographically by `name` — the tie-break must be total, or the same extent gets two names across runs. When no cell contains the extent, fall back to `extent.field_name`. `covering_fields` returns every field the extent touches, including REDEFINES views, ordered by ascending length — the opt-in expansion for when alias information is the answer.

**Cells are used only here and in `extent.py`.** The corpus expands to roughly 5.6M cells (mean 1,491 per program, worst 121,001). Keeping that expansion out of the lattice — which is keyed on extents — is why the analysis does not pay for OCCURS. Do not cache cells on `State` or on a `FlowEdge`.

- [ ] **Step 1: Write the failing naming tests**

`cobble/tests/dataflow/fields/test_naming.py`:

```python
"""An extent names the smallest field that covers it, deterministically."""

from __future__ import annotations

from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId

from cobble.dataflow.fields.naming import covering_fields, smallest_covering

from .conftest import field


def _extent(start: int, length: int, name="?"):
    return FieldExtent(
        region=RegionId.WORKING_STORAGE,
        start=start,
        length=length,
        precision=Precision.EXACT,
        field_name=name,
    )


_NESTED = [
    field(
        1,
        "REC-MASTER",
        children=[
            field(5, "MST-KEY", "X(8)"),
            field(5, "MST-BODY", children=[field(10, "MST-COUNT", "9(4)")]),
        ],
    )
]


def test_a_member_extent_names_the_member_not_the_record(program_of, index_of):
    asg = program_of([], data_fields=_NESTED)
    assert smallest_covering(_extent(8, 4), index_of(asg)) == "MST-COUNT"


def test_an_extent_spanning_two_members_names_their_smallest_common_group(
    program_of, index_of
):
    asg = program_of([], data_fields=_NESTED)
    assert smallest_covering(_extent(0, 12), index_of(asg)) == "REC-MASTER"


def test_an_extent_no_field_covers_falls_back_to_its_own_name(program_of, index_of):
    asg = program_of([], data_fields=_NESTED)
    assert smallest_covering(_extent(6, 4, name="WS-ODD"), index_of(asg)) == "WS-ODD"


def test_covering_fields_expands_to_every_field_touched_smallest_first(
    program_of, index_of
):
    asg = program_of([], data_fields=_NESTED)
    assert covering_fields(_extent(8, 4), index_of(asg)) == (
        "MST-COUNT",
        "MST-BODY",
        "REC-MASTER",
    )


def test_a_redefines_view_appears_in_the_expansion(program_of, index_of):
    asg = program_of(
        [],
        data_fields=[
            field(1, "REC-A", children=[field(5, "WS-A", "X(4)")]),
            field(1, "REC-B", redefines="REC-A", children=[field(5, "WS-ALT", "X(4)")]),
        ],
    )
    assert "WS-ALT" in covering_fields(_extent(0, 4), index_of(asg))
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd cobble && uv run pytest tests/dataflow/fields/test_naming.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobble.dataflow.fields.naming'`

- [ ] **Step 3: Write `naming.py`**

```python
"""An extent back to the field a reader recognises.

The smallest covering field, so an edge reads MST-COUNT rather than
REC-MASTER. The tie-break is total on purpose: two cells of equal length over
one range would otherwise name the same extent differently between runs.

This and extent.py are the only places cells are touched. The corpus expands to
roughly 5.6M of them (worst member 121,001), and keeping that expansion out of
the lattice -- which is keyed on extents -- is why the analysis does not pay for
OCCURS.
"""

from __future__ import annotations

from cobol_memory.field_extent import FieldExtent

from cobble.dataflow.fields.extent import CellIndex


def _rank(cell) -> tuple:
    return (cell.length, -cell.level, -len(cell.path), cell.name)


def smallest_covering(extent: FieldExtent, index: CellIndex) -> str:
    covering = index.containing(extent)
    if not covering:
        return extent.field_name
    return min(covering, key=_rank).name


def covering_fields(extent: FieldExtent, index: CellIndex) -> tuple[str, ...]:
    """Every field the extent touches, smallest first, REDEFINES views included."""
    touched = tuple(
        cell
        for cell in index.ordered
        if index.region_of(cell) is extent.region
        and cell.start < extent.end
        and cell.end > extent.start
    )
    return tuple(dict.fromkeys(cell.name for cell in sorted(touched, key=_rank)))
```

- [ ] **Step 4: Run the naming tests**

Run: `cd cobble && uv run pytest tests/dataflow/fields/test_naming.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Format and commit**

```bash
cd cobble && uv run black cobble tests
cd /Users/avisheksengupta/code/red-dragon-forge && git add cobble/cobble/dataflow/fields/naming.py cobble/tests/dataflow/fields/test_naming.py
git commit -m "feat(cobble): name a byte extent by its smallest covering field"
```

---

## Task 6: `emit.py`, the graph vocabulary, and the corpus driver

Closes bead `pd9`.

**Files:**
- Modify: `cobble/cobble/knowledge_graph/graph_types.py` (add `NodeKind.FIELD`, `EdgeKind.FLOWS_TO`)
- Create: `cobble/cobble/dataflow/fields/emit.py`
- Create: `cobble/cobble/dataflow/fields/config.py`
- Create: `cobble/cobble/dataflow/fields/build_corpus.py`
- Modify: `cobble/pyproject.toml` (entry point `cobble-fields`)
- Modify: `cobble/README.md` (the stage, its config, its exit codes)
- Test: `cobble/tests/dataflow/fields/test_emit.py`, `cobble/tests/dataflow/fields/test_build_corpus.py`

**Interfaces:**
- Consumes: Task 4's `ProgramFlow`/`FlowEdge`, Task 5's `smallest_covering`/`covering_fields`, `cobble.knowledge_graph.graph_types.{GraphNode, GraphEdge, NodeKind, EdgeKind}`, `cobble.knowledge_graph.graph_writer.GraphWriter`, `cobble.dataflow.depgraph.cics_cache.cached_asg_dialect_parsers_registered`.
- Produces:
  - `emit.field_id(program: str, name: str) -> str` — `f"{program}.{name}"`, uppercased, matching every other extractor's convention that a node id is a logical name.
  - `emit.graph_records(flow: ProgramFlow, index: CellIndex, expand: bool) -> tuple[tuple[GraphNode, ...], tuple[GraphEdge, ...]]`.
  - `config.FieldsConfig(asg_dir: Path, out_dir: Path)`, `config.load_fields_config(path) -> FieldsConfig`, `config.TABLE = "fields"`.
  - `build_corpus.main() -> int`.

**A `FLOWS_TO` edge carries source extent, target extent, and the CFG node id that wrote it. It does NOT carry the guard condition** — a reader wanting the condition asks `srccfg` for that node's guards on demand. Carrying it would multiply state by the number of distinct guard paths and would depend on the path-enumeration walk bead `3ao` found broken. Edge `attrs`: `{"node": <cfg node id>, "source_extent": str(source_extent), "target_extent": str(target_extent)}` — `FieldExtent.__str__` is already `f"{field_name}@{region}[{start}:{end}]"`. A synthetic source (`LITERAL`, `FILE:<name>`, `%CICS-STATE`, `%CALL:<target>`) becomes its own `FIELD` node with that id and no location.

**Config**, modelled exactly on `srccfg/config.py` — both values required, no silent default, because the failure a default hides is a run that finds no members and reports success:

```toml
[fields]
asg_dir = "/abs/path/to/out-<corpus>-parsed"
out_dir = "/abs/path/to/out-<corpus>-fields"
```

**Exit status contract for `cobble-fields`,** matching `diagnosis/asg_operands.py`'s shape:

| code | meaning |
| --- | --- |
| 0 | every member analysed, coverage at or above the floor |
| 1 | coverage below the floor (`--min-coverage`, default 0.60) |
| 2 | ASG directory not found, or config missing its table |
| 3 | one or more members were skipped or unreadable |

- [ ] **Step 1: Add the vocabulary**

In `cobble/cobble/knowledge_graph/graph_types.py`, add to `NodeKind`:

```python
    # A COBOL data field, or a synthetic origin a field's bytes came from
    # (LITERAL, FILE:<name>, %CICS-STATE, %CALL:<target>). id is
    # "<program>.<field>" because a field name is only unique within a program
    # -- two copybooks routinely give one piece of storage two names.
    FIELD = "FIELD"
```

and to `EdgeKind`:

```python
    # FIELD -> FIELD, from field-level byte dataflow: the source's bytes reach
    # the target's. attrs carry both extents and the CFG node id that wrote
    # them, but deliberately NOT the guard condition -- a reader asks srccfg
    # for that node's guards on demand, which keeps conditions out of the
    # lattice they would otherwise multiply.
    FLOWS_TO = "FLOWS_TO"
```

- [ ] **Step 2: Write the failing emit tests**

`cobble/tests/dataflow/fields/test_emit.py`:

```python
"""What a FLOWS_TO edge carries, and what it deliberately does not."""

from __future__ import annotations

from cobble.dataflow.fields.emit import field_id, graph_records
from cobble.dataflow.fields.fixpoint import analyse
from cobble.knowledge_graph.graph_types import EdgeKind, NodeKind

from .conftest import field


def _flow(program_of, index_of):
    asg = program_of(
        [{"type": "MOVE", "operands": [{"name": "WS-A"}, {"name": "WS-B"}]}],
        data_fields=[
            field(1, "REC", children=[field(5, "WS-A", "X(4)"), field(5, "WS-B", "X(4)")])
        ],
    )
    index = index_of(asg)
    return analyse(asg, index), index


def test_a_field_id_is_scoped_by_program():
    assert field_id("PROGA", "WS-A") == "PROGA.WS-A"


def test_an_edge_runs_between_two_field_nodes(program_of, index_of):
    flow, index = _flow(program_of, index_of)
    _, edges = graph_records(flow, index, expand=False)
    (edge,) = [e for e in edges if e.kind is EdgeKind.FLOWS_TO]
    assert (edge.source, edge.target) == ("PROGA.WS-A", "PROGA.WS-B")
    assert edge.source_kind is NodeKind.FIELD
    assert edge.target_kind is NodeKind.FIELD


def test_an_edge_carries_both_extents_and_the_cfg_node(program_of, index_of):
    flow, index = _flow(program_of, index_of)
    _, edges = graph_records(flow, index, expand=False)
    (edge,) = [e for e in edges if e.kind is EdgeKind.FLOWS_TO]
    assert edge.attrs["node"] == "MAIN/0"
    assert "[0:4]" in edge.attrs["source_extent"]


def test_an_edge_does_not_carry_a_guard_condition(program_of, index_of):
    """Conditions stay out of the lattice; a reader asks srccfg for the node's."""
    flow, index = _flow(program_of, index_of)
    _, edges = graph_records(flow, index, expand=False)
    (edge,) = [e for e in edges if e.kind is EdgeKind.FLOWS_TO]
    assert "condition" not in edge.attrs
    assert "guard" not in edge.attrs


def test_a_synthetic_origin_becomes_its_own_field_node(program_of, index_of):
    asg = program_of(
        [{"type": "INITIALIZE", "operands": [{"name": "REC"}]}],
        data_fields=[field(1, "REC", children=[field(5, "WS-A", "X(4)")])],
    )
    index = index_of(asg)
    _, edges = graph_records(analyse(asg, index), index, expand=False)
    assert any(e.source == "PROGA.LITERAL" for e in edges)


def test_expansion_names_every_field_the_extent_touches(program_of, index_of):
    flow, index = _flow(program_of, index_of)
    _, edges = graph_records(flow, index, expand=True)
    assert any("REC" in e.attrs.get("target_fields", "") for e in edges)
```

- [ ] **Step 3: Run to verify they fail**

Run: `cd cobble && uv run pytest tests/dataflow/fields/test_emit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobble.dataflow.fields.emit'`

- [ ] **Step 4: Write `emit.py`**

```python
"""FIELD nodes and FLOWS_TO edges from one program's flow.

An edge carries its two extents and the CFG node id that wrote them, and not
the guard condition -- a reader wanting the condition asks srccfg for that
node's guards. Carrying it would multiply the lattice by the number of distinct
guard paths and would depend on the path-enumeration walk bead
red-dragon-forge-3ao found broken.
"""

from __future__ import annotations

from cobble.dataflow.fields.extent import CellIndex
from cobble.dataflow.fields.fixpoint import FlowEdge, ProgramFlow
from cobble.dataflow.fields.naming import covering_fields, smallest_covering
from cobble.knowledge_graph.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind


def field_id(program: str, name: str) -> str:
    return f"{program}.{name}".upper()


def _source_name(edge: FlowEdge, index: CellIndex) -> str:
    if edge.source.extent is None:
        return edge.source.origin
    return smallest_covering(edge.source.extent, index)


def _attrs(edge: FlowEdge, index: CellIndex, expand: bool) -> dict:
    attrs: dict = {
        "node": edge.node,
        "target_extent": str(edge.target),
        "source_extent": "" if edge.source.extent is None else str(edge.source.extent),
    }
    if expand:
        attrs["target_fields"] = ",".join(covering_fields(edge.target, index))
        if edge.source.extent is not None:
            attrs["source_fields"] = ",".join(
                covering_fields(edge.source.extent, index)
            )
    return attrs


def graph_records(
    flow: ProgramFlow, index: CellIndex, expand: bool
) -> tuple[tuple[GraphNode, ...], tuple[GraphEdge, ...]]:
    edges = tuple(
        GraphEdge(
            source=field_id(flow.program, _source_name(edge, index)),
            source_kind=NodeKind.FIELD,
            target=field_id(flow.program, smallest_covering(edge.target, index)),
            target_kind=NodeKind.FIELD,
            kind=EdgeKind.FLOWS_TO,
            attrs=_attrs(edge, index, expand),
        )
        for edge in flow.edges
    )
    ids = tuple(dict.fromkeys(i for e in edges for i in (e.source, e.target)))
    nodes = tuple(GraphNode(id=i, kind=NodeKind.FIELD) for i in ids)
    return nodes, edges
```

- [ ] **Step 5: Run the emit tests**

Run: `cd cobble && uv run pytest tests/dataflow/fields/test_emit.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Write `config.py`**

```python
"""The [fields] TOML table.

Both values are required and neither defaults. A default asg_dir would let a
run point at an empty directory, find no members, and report success -- which
is the one failure mode a corpus pass must not have.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

TABLE = "fields"


@dataclass(frozen=True)
class FieldsConfig:
    asg_dir: Path
    out_dir: Path


def _require(table: dict, key: str, path: Path) -> str:
    value = table.get(key, "")
    if not value:
        raise KeyError(f"[{TABLE}] {key} is missing or empty in {path}")
    return value


def load_fields_config(path: Path) -> FieldsConfig:
    table = tomllib.loads(path.read_text(encoding="utf-8")).get(TABLE, {})
    return FieldsConfig(
        asg_dir=Path(_require(table, "asg_dir", path)),
        out_dir=Path(_require(table, "out_dir", path)),
    )
```

Check this against `cobble/cobble/dataflow/srccfg/config.py` before committing: if that file's `_require` or loader differs in how it reports a missing table, follow it rather than this sketch — two configs in one package that fail differently is the drift worth avoiding.

- [ ] **Step 7: Write the failing corpus-driver test**

`cobble/tests/dataflow/fields/test_build_corpus.py`:

```python
"""The corpus pass: one member per ASG file, a member that raises reported."""

from __future__ import annotations

import json

from cobble.dataflow.fields.build_corpus import cli


def _write_member(directory, name: str, body: dict) -> None:
    (directory / f"{name}.json").write_text(json.dumps(body), encoding="utf-8")


def _config(tmp_path, asg_dir, out_dir) -> str:
    path = tmp_path / "fields.toml"
    path.write_text(
        f'[fields]\nasg_dir = "{asg_dir}"\nout_dir = "{out_dir}"\n', encoding="utf-8"
    )
    return str(path)


def _program(program_id: str) -> dict:
    return {
        "program_id": program_id,
        "data_fields": [
            {
                "level": 1,
                "name": "REC",
                "children": [
                    {"level": 5, "name": "WS-A", "pic": "X(4)"},
                    {"level": 5, "name": "WS-B", "pic": "X(4)"},
                ],
            }
        ],
        "paragraphs": [
            {
                "name": "MAIN",
                "statements": [
                    {
                        "type": "MOVE",
                        "operands": [{"name": "WS-A"}, {"name": "WS-B"}],
                    }
                ],
            }
        ],
    }


def test_a_run_writes_nodes_and_edges_and_exits_zero(tmp_path):
    asg_dir = tmp_path / "asg"
    asg_dir.mkdir()
    out_dir = tmp_path / "out"
    _write_member(asg_dir, "MEMBERA", _program("PROGA"))
    assert cli(["--config", _config(tmp_path, asg_dir, out_dir)]) == 0
    edges = (out_dir / "edges.jsonl").read_text(encoding="utf-8")
    assert "FLOWS_TO" in edges


def test_a_malformed_member_is_reported_and_the_run_continues(tmp_path):
    asg_dir = tmp_path / "asg"
    asg_dir.mkdir()
    out_dir = tmp_path / "out"
    _write_member(asg_dir, "MEMBERA", _program("PROGA"))
    (asg_dir / "MEMBERB.json").write_text("{not json", encoding="utf-8")
    assert cli(["--config", _config(tmp_path, asg_dir, out_dir)]) == 3
    assert "FLOWS_TO" in (out_dir / "edges.jsonl").read_text(encoding="utf-8")


def test_a_missing_asg_directory_exits_two(tmp_path):
    config = _config(tmp_path, tmp_path / "nope", tmp_path / "out")
    assert cli(["--config", config]) == 2


def test_two_members_declaring_one_program_id_are_both_reported(tmp_path):
    """The corpus holds nine such collisions; a keyed map must detect, not overwrite."""
    asg_dir = tmp_path / "asg"
    asg_dir.mkdir()
    out_dir = tmp_path / "out"
    _write_member(asg_dir, "MEMBERA", _program("PROGA"))
    _write_member(asg_dir, "MEMBERB", _program("PROGA"))
    assert cli(["--config", _config(tmp_path, asg_dir, out_dir)]) == 3
```

- [ ] **Step 8: Run to verify they fail**

Run: `cd cobble && uv run pytest tests/dataflow/fields/test_build_corpus.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobble.dataflow.fields.build_corpus'`

- [ ] **Step 9: Write `build_corpus.py`**

No JVM: the cache is the whole input. A member that raises is reported and the run continues, because the answer wanted from a corpus pass is "which members are missing from this output", and a run that aborts answers that for one member only.

```python
"""The field dataflow corpus pass.

Intra-program only: a CALL or LINK contributes a synthetic %CALL:<target>
source and no callee summary. Cross-program flow is a separate stage.

Exit status contract:
  0 - every member analysed, coverage at or above the floor
  1 - coverage below the floor
  2 - ASG directory not found, or config missing its table
  3 - one or more members skipped, unreadable, or colliding on program_id
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from cobol_asg.asg_types import CobolASG

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.config import load_fields_config
from cobble.dataflow.fields.emit import graph_records
from cobble.dataflow.fields.fixpoint import analysed

logger = logging.getLogger(__name__)


@dataclass
class RunTotals:
    analysed: int = 0
    writes: int = 0
    covered: int = 0
    unhandled: int = 0
    skipped: dict[str, str] = field(default_factory=dict)
    collisions: dict[str, list[str]] = field(default_factory=dict)

    @property
    def coverage(self) -> float:
        return self.covered / self.writes if self.writes else 0.0

    def as_dict(self) -> dict:
        return {
            "analysed": self.analysed,
            "writes": self.writes,
            "covered": self.covered,
            "coverage": round(self.coverage, 4),
            "unhandled": self.unhandled,
            "skipped": len(self.skipped),
            "collisions": len(self.collisions),
        }


def _member_asg(path: Path) -> CobolASG:
    return CobolASG.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _record_member(totals: RunTotals, member: str, program_id: str) -> None:
    """A program_id seen twice is recorded, never overwritten.

    The corpus holds nine such collisions across 3,779 members; a keyed map
    that silently keeps the last one loses the other eight silently too.
    """
    totals.collisions.setdefault(program_id, []).append(member)


def _analyse_member(path: Path, writer, totals: RunTotals, expand: bool) -> None:
    try:
        asg = _member_asg(path)
    except (OSError, json.JSONDecodeError, TypeError, KeyError, ValueError) as error:
        totals.skipped[path.stem] = f"unreadable: {error}"
        return
    flow, index = analysed(asg)
    _record_member(totals, path.stem, flow.program)
    if index is None or flow.skipped:
        totals.skipped[path.stem] = flow.skipped or "no layout"
        return
    nodes, edges = graph_records(flow, index, expand=expand)
    for node in nodes:
        writer.add_node(node)
    for edge in edges:
        writer.add_edge(edge)
    totals.analysed += 1
    totals.writes += flow.writes
    totals.covered += flow.covered
    totals.unhandled += flow.unhandled


def _exit_code(totals: RunTotals, floor: float) -> int:
    duplicated = {k: v for k, v in totals.collisions.items() if len(v) > 1}
    if totals.skipped or duplicated:
        return 3
    return 0 if totals.coverage >= floor else 1


def _emit_results(totals: RunTotals) -> None:
    logger.info(
        "fields: %d members, coverage %.1f%% (%d/%d writes), "
        "%d unhandled, %d skipped",
        totals.analysed,
        totals.coverage * 100,
        totals.covered,
        totals.writes,
        totals.unhandled,
        len(totals.skipped),
    )
    for member, reason in sorted(totals.skipped.items()):
        logger.warning("fields: skipped %s: %s", member, reason)
    for program_id, members in sorted(totals.collisions.items()):
        if len(members) > 1:
            logger.warning(
                "fields: program_id %s declared by %d members", program_id, len(members)
            )
    json.dump(totals.as_dict(), sys.stdout)
    sys.stdout.write("\n")


def cli(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    parser = argparse.ArgumentParser(
        description="Field-level byte dataflow over a cached ASG corpus."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--min-coverage", type=float, default=0.60)
    parser.add_argument("--expand", action="store_true")
    arguments = parser.parse_args(tuple(argv) if argv else None)
    try:
        config = load_fields_config(arguments.config)
    except (OSError, KeyError, ValueError) as error:
        sys.stderr.write(f"{error}\n")
        return 2
    if not config.asg_dir.is_dir():
        sys.stderr.write(f"No ASG cache at {config.asg_dir}\n")
        return 2
    config.out_dir.mkdir(parents=True, exist_ok=True)
    totals = RunTotals()
    writer = _graph_writer(config)
    try:
        with cached_asg_dialect_parsers_registered():
            for path in sorted(config.asg_dir.glob("*.json")):
                _analyse_member(path, writer, totals, arguments.expand)
    finally:
        writer.close()
    _emit_results(totals)
    return _exit_code(totals, arguments.min_coverage)


def main() -> int:
    sys.exit(cli())
```

**Note for the implementer:** `_graph_writer(config)` is yours. `GraphWriter(nodes_path, edges_path, corpus_index)` needs a `CorpusIndex`, and how one is built in this package is settled — read `cobble/cobble/dataflow/srccfg/build_corpus.py` and `cobble/cobble/build_graph.py` and follow whichever they use. `GraphWriter.close()` renames its tmp files into place, so the `finally` is what stops a crash from leaving truncated output. The `cached_asg_dialect_parsers_registered()` wrapper is not optional: without it a member containing EXEC CICS raises "Unknown COBOL statement type" and the whole corpus reports as unreadable.

- [ ] **Step 10: Run the corpus-driver tests**

Run: `cd cobble && uv run pytest tests/dataflow/fields/test_build_corpus.py -v`
Expected: PASS (4 tests)

- [ ] **Step 11: Register the entry point**

In `cobble/pyproject.toml`, after the `cobble-srccfg-*` block:

```toml
# Field-level byte dataflow over the one ASG cache: FIELD nodes and FLOWS_TO
# edges, intra-program. No JVM.
cobble-fields = "cobble.dataflow.fields.build_corpus:main"
```

- [ ] **Step 12: Document the stage in `cobble/README.md`**

Add a section next to the existing srccfg stage: what `cobble-fields` reads, the `[fields]` config keys, the exit-status table above, and the one-line statement that it is intra-program only with cross-program summaries deferred. Describe what the suite covers; state no test counts.

- [ ] **Step 13: Run the full cobble suite and the import contracts**

```bash
cd cobble && uv run pytest -q
cd /Users/avisheksengupta/code/red-dragon-forge && uv run lint-imports
```
Expected: PASS; 0 broken contracts. `tests/test_static_surface.py` must still pass — it is what holds cobble off the interpreter.

- [ ] **Step 14: Format and commit**

```bash
cd cobble && uv run black cobble tests
cd /Users/avisheksengupta/code/red-dragon-forge && git add cobble/cobble cobble/tests cobble/pyproject.toml cobble/README.md
git commit -m "feat(cobble): emit FIELD nodes and FLOWS_TO edges from a corpus pass"
```

---

## Task 7: Acceptance — coverage, the end-to-end oracle, and the performance guard

**Files:**
- Test: `cobble/tests/dataflow/fields/test_acceptance.py`
- Modify: `cobble/tests/dataflow/fields/conftest.py` (add the `corpus_members` fixture)
- Create: `cobble/config/fields-tests.toml.example` (tracked; the real file is gitignored)

**Interfaces:**
- Consumes: everything above, plus `cobble/config/fields-tests.toml` — gitignored via `config/*.toml`, so the members and oracle it names never enter the repository.

**This task is the reason the plan exists in this shape.** The `3ao` post-mortem found the srccfg acceptance suite passing while its walk reached 18% of nodes, because nothing measured reach. A termination assertion is not an acceptance test. Assert the fraction of writes producing at least one edge, and pin the end-to-end oracle.

- [ ] **Step 1: Write the example config**

`cobble/config/fields-tests.toml.example`:

```toml
# Copy to fields-tests.toml (gitignored) to run the acceptance tests against a
# real parsed cache. Without it, they skip -- which is why no member name,
# field name or dataset name from a corpus under analysis appears in any
# tracked file in this repository.
cache_dir = "/abs/path/to/out-<corpus>-parsed"

# Members to analyse for the coverage floor.
members = ["MEMBERONE", "MEMBERTWO"]

# The end-to-end oracle: one known derivation, asserted end to end.
[oracle]
member = "MEMBERONE"
source_field = "SCR-COUNT"
target_field = "MST-COUNT"
cfg_node = "PARA-UPDATE/57"

# The slowest member measured, and the bound its analysis must stay under.
# 710.58s was the cost under recursive PERFORM inlining; the paragraph-keyed
# worklist is what this asserts away.
[performance]
member = "MEMBERWORST"
seconds = 60.0
```

- [ ] **Step 2: Add the fixture**

Append to `cobble/tests/dataflow/fields/conftest.py`:

```python
@pytest.fixture
def corpus_config() -> Mapping:
    """A gitignored config naming real members, or a skip.

    Shape: see config/fields-tests.toml.example. The names stay out of the
    repository; the assertions do not depend on what they are.
    """
    import tomllib

    if not CORPUS_CONFIG.is_file():
        pytest.skip(f"no {CORPUS_CONFIG.name}; acceptance needs a parsed cache")
    return tomllib.loads(CORPUS_CONFIG.read_text(encoding="utf-8"))
```

- [ ] **Step 3: Write the acceptance tests**

`cobble/tests/dataflow/fields/test_acceptance.py`:

```python
"""Coverage, one pinned derivation, and a bound on the worst member.

A termination assertion is not an acceptance test: the 3ao post-mortem found a
suite passing while its walk reached 18% of nodes, because nothing measured
reach. Every assertion here is about how much of the program the analysis
actually explained.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from cobol_asg.asg_types import CobolASG

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.emit import graph_records
from cobble.dataflow.fields.fixpoint import analysed

COVERAGE_FLOOR = 0.60


def _asg(cache: Path, member: str) -> CobolASG:
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict(
            json.loads((cache / f"{member}.json").read_text(encoding="utf-8"))
        )


def _analysed(cache: Path, member: str):
    return analysed(_asg(cache, member))


def test_most_resolvable_writes_produce_at_least_one_edge(corpus_config):
    """The measurement 3ao's post-mortem demands: reach, not termination."""
    cache = Path(corpus_config["cache_dir"])
    writes = covered = 0
    for member in corpus_config["members"]:
        flow, _ = _analysed(cache, member)
        writes += flow.writes
        covered += flow.covered
    assert writes > 0
    assert covered / writes >= COVERAGE_FLOOR


def test_no_analysed_member_is_silently_skipped(corpus_config):
    cache = Path(corpus_config["cache_dir"])
    skipped = {
        member: _analysed(cache, member)[0].skipped
        for member in corpus_config["members"]
    }
    assert not [m for m, reason in skipped.items() if reason], skipped


def test_the_pinned_derivation_holds_end_to_end(corpus_config):
    oracle = corpus_config["oracle"]
    flow, index = _analysed(Path(corpus_config["cache_dir"]), oracle["member"])
    _, edges = graph_records(flow, index, expand=True)
    matching = [
        edge
        for edge in edges
        if edge.source.endswith(f".{oracle['source_field']}")
        and edge.target.endswith(f".{oracle['target_field']}")
    ]
    assert matching, f"no edge {oracle['source_field']} -> {oracle['target_field']}"
    assert any(edge.attrs["node"] == oracle["cfg_node"] for edge in matching)


def test_the_worst_member_completes_within_its_bound(corpus_config):
    """710.58s under recursive PERFORM inlining; the paragraph-keyed worklist
    is what this asserts away."""
    performance = corpus_config.get("performance")
    if not performance:
        pytest.skip("no [performance] in fields-tests.toml")
    cache = Path(corpus_config["cache_dir"])
    started = time.monotonic()
    flow, _ = _analysed(cache, performance["member"])
    elapsed = time.monotonic() - started
    assert not flow.skipped
    assert elapsed < performance["seconds"]
```

- [ ] **Step 4: Run them without a config, to confirm they skip rather than fail**

Run: `cd cobble && uv run pytest tests/dataflow/fields/test_acceptance.py -v`
Expected: 4 skipped, 0 failed. A tracked test that cannot run without corpus identifiers must skip cleanly.

- [ ] **Step 5: Run them with a real config**

Create `cobble/config/fields-tests.toml` from the example, pointing at `cobble/out-<corpus>-parsed`. Choose members with structured LINKAGE and OCCURS, not just flat ones. Then:

Run: `cd cobble && uv run pytest tests/dataflow/fields/test_acceptance.py -v`
Expected: PASS. If coverage falls below the floor, **do not lower the floor** — read the `unhandled` and `skipped` counters and the `reason` values `operand_extents` returned, and report which statement class or operand form is missing. That report is the deliverable; a lowered floor is the failure `3ao` already paid for once.

- [ ] **Step 6: Run the corpus pass over the whole cache**

```bash
cd cobble && uv run cobble-fields --config config/fields.local.toml --min-coverage 0.60
```
Record: members analysed, members skipped, coverage ratio, unhandled statement count, duplicate `program_id` count (expect nine collisions across 3,779 members), and wall-clock. Put these in the commit message, not in `README.md` — they are a point-in-time measurement, and living documentation does not carry counts.

- [ ] **Step 7: Full suite, contracts, commit**

```bash
cd cobble && uv run pytest -q
cd /Users/avisheksengupta/code/red-dragon-forge && uv run lint-imports && make test
cd cobble && uv run black cobble tests
cd /Users/avisheksengupta/code/red-dragon-forge && git add cobble/tests/dataflow/fields cobble/config/fields-tests.toml.example
git commit -m "test(cobble): acceptance for field dataflow — coverage, oracle, perf bound"
```

Confirm before committing: `git diff --cached` contains no corpus member name, field name, dataset name, or source-root path; and `cobble/config/fields-tests.toml` is untracked.

---

## Deferred

Filed as beads rather than carried here.

- **Cross-program flow** — `summary.py` and `interprocedural.py`, the whole **Cross-program** section of the spec. A second plan.
- **`depgraph.statement_stream`'s missing nesting keys** — ruling R3. Bead `aj3` stays open, narrowed to this retrofit; it changes an existing corpus pass's output and needs its own re-run.
- **`red-dragon-forge-3ao`** — the srccfg reaching-walk bug. Does not block this work: it lives in path enumeration, the gen-kill fixpoints are unaffected, and no edge here carries a guard condition. Its diagnosis already settled the fix: expand a walk refused by the cap only when its `(node, perform stack)` context is new.
- **`red-dragon-forge-tmx`** — forge has no beads redactor, so `issues/issues.jsonl` cannot be regenerated. Until it exists, no task in this plan may run `bd export`.
