# Source CFG with Reaching Conditions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a per-program control-flow graph from the cached COBOL ASGs whose
edges carry conditions, so that every assignment can be labelled with the atomic
predicates that must hold for it to execute, and every field can be traced to the
fields it is derived from.

**Architecture:** A new package `cobble/dataflow/srccfg` reads the ASG JSON cache
written by `cobble-parse-corpus` and lowers each program's procedure division into a
graph of two semantic node kinds — `TEST` (one atomic predicate, two out-edges) and
`ASSIGN` (`writes`/`reads`/`transfer`) — plus plumbing nodes. Short-circuit `AND`/`OR`
are desugared into chains of `TEST` nodes, so the CFG itself is the condition
language: a reaching condition is the list of (test, edge-polarity) pairs along a
path, and `NOT` is an edge swap rather than a term. Nothing is compiled and no solver
is used. Later passes over that graph produce reaching conditions, reaching
definitions/def-use, co-assignment candidates, and a cross-program call graph.

**Tech Stack:** Python ≥3.11, `cobol_asg` (vendored ASG dataclasses, `CobolASG.from_dict`),
existing `cobble.dataflow.depgraph.flows` / `.graph` for the verb table and name
classification, `pytest`, `black`, `pyright`, `import-linter`, `python_fp_lint`, `uv`.

**Spec:** `docs/superpowers/specs/2026-09-04-src-cfg-reaching-conditions-design.md`

## Global Constraints

- **No client identifiers anywhere.** Not in code, comments, docstrings, test data,
  config examples, artifact names, or commit messages. Field and program names in
  tests are invented (`WS-FLAG-A`, `PROGA`, `MAIN`). Corpus member ids reach tests
  only through a fixture reading a gitignored `config/*.toml` — never a literal.
- Python ≥3.11. Every module starts with `from __future__ import annotations`.
- **Enforced-functional style.** `fp.json` bans: mutation (list `append`/`extend`/
  `insert`/`pop`, dict `update`/`setdefault`, set `add`, subscript assignment,
  augmented assignment, mutation inside loops), `is None` / `is not None`,
  `Optional`/`X | None`, `None` defaults, unfrozen dataclasses, `Any`, `staticmethod`,
  deep nesting. Ruff `select` includes `T20` (no `print`), `C901`, `PLR0915`,
  `ANN401`. `max_statements: 10` per function.
- **Zero new fp-lint violations for srccfg files.** The sibling `depgraph` package
  carries 155 pre-existing violations; do not fix them, and do not add to the count.
  Gate: `uv run --no-sync python -m python_fp_lint check cobble/dataflow/srccfg/`
  must report 0.
- Absent values are empty tuples / empty strings / sentinel dataclass instances,
  never `None`.
- **Statement kinds are matched by class name**, not `isinstance` — the existing
  house rule in `depgraph/graph.py` and `depgraph/flows.py`.
- ASGs are loaded as `CobolASG.from_dict(json.loads(path.read_text()))` **inside**
  `with cached_asg_dialect_parsers_registered():` — imported from
  `cobble.dataflow.depgraph.cics_cache`, not from `cobol_asg`. Without it, `EXEC_CICS`
  raises `Unknown COBOL statement type: 'EXEC_CICS'`, which on the onboarding corpus is
  2,129 of 3,779 members. `CobolASG` itself comes from `cobol_asg.asg_types`.
- Config carries no silent defaults: every key goes through a `_require` helper and a
  missing key raises.
- Commit messages: `type(cobble): summary`, ending with
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Test command: `make test` (`uv run --no-sync python -m pytest`). Lint: `make lint`.
  Format: `make fmt`. If `uv` fails with `Operation not permitted` on its cache, the
  sandbox is the cause, not the code.

## File Structure

| File | Responsibility |
| --- | --- |
| `cobble/dataflow/srccfg/__init__.py` | Package marker; no re-exports. |
| `cobble/dataflow/srccfg/cfg.py` | The vocabulary: frozen `Atom`, `Node`, `Edge`, `Cfg`, `Fragment`, node kinds, edge kinds, `seq()`. No ASG knowledge. |
| `cobble/dataflow/srccfg/conditions.py` | ASG condition dicts to a normalised condition tree of `Atom`s and `And`/`Or`/`Not`; 88-level resolution; `negate_atom`. |
| `cobble/dataflow/srccfg/desugar.py` | One ASG statement to a `Fragment`. Short-circuit lowering, IF/EVALUATE/PERFORM/GO TO/I-O arms/SEARCH/HANDLE CONDITION. |
| `cobble/dataflow/srccfg/build.py` | Per-program assembly: paragraph order, `PERFORM` range expansion, whole-program `Cfg`. No I/O. |
| `cobble/dataflow/srccfg/build_corpus.py` | Corpus driver and CLI `cobble-srccfg-build`: one CFG JSON per cached ASG, per-member failure reporting, `cfg_to_dict`/`cfg_from_dict`. |
| `cobble/dataflow/srccfg/dataflow.py` | Graph passes: reaching conditions, reaching definitions, def-use, `%HANDLER[…]` resolution. |
| `cobble/dataflow/srccfg/link.py` | Cross-program: call graph from LINK/XCTL/CALL, commarea aliasing. |
| `cobble/dataflow/srccfg/coassign.py` | The four co-assignment tiers. |
| `cobble/dataflow/srccfg/render.py` | Query CLI `cobble-srccfg`: writers of a field, guards, derivation, co-assign candidates. |
| `cobble/dataflow/srccfg/config.py` | Frozen `SrcCfgConfig` + `load_srccfg_config`, `_require` pattern. |
| `tests/dataflow/srccfg/conftest.py` | `asg_of(dict)` helper and the gitignored-config corpus fixture. |
| `tests/dataflow/srccfg/test_*.py` | One test module per source module. |

---

### Task 0: De-identify the sibling `dataflow` package

The `cobble/dataflow` package and `tests/dataflow` are currently **untracked**, and
they carry roughly 40 lines naming client members, fields, copybooks and config
files. `srccfg` lands inside that package, so the first commit that tracks it also
tracks those lines. This task is mechanical, changes no behaviour, and must land
before anything else.

**Files:**
- Modify: `cobble/dataflow/layout.py:5,200,328`
- Modify: `cobble/dataflow/layout_check.py:18`
- Modify: `cobble/dataflow/depgraph/build.py:58-59`
- Modify: `cobble/dataflow/depgraph/config.py:13,17,18,23,24`
- Modify: `cobble/dataflow/depgraph/render.py:65`
- Modify: `cobble/dataflow/depgraph/graph.py:13,26,97,187`
- Modify: `cobble/dataflow/depgraph/parse_corpus.py:5,18,19`
- Modify: `cobble/dataflow/depgraph/cics_cache.py:9`
- Modify: `cobble/dataflow/depgraph/flows.py:11-15,180,185-188,272,317,381`
- Test: `tests/dataflow/test_layout_check.py:28,33`, `tests/dataflow/test_field_layout.py:3,5,86,208,210,256`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing. No signature changes — comments, docstrings, and test data only.

- [ ] **Step 1: List every identifier occurrence**

```bash
cd cobble
grep -rniE '<client-app-prefix>|<client-file-prefix>|<client-dictionary-prefix>' \
  cobble/dataflow tests/dataflow --include='*.py' --include='*.toml' -n
```

Substitute the three real prefixes from the analysis ledger for the placeholders
above **in the shell only** — do not write them into any file, and do not paste the
grep output into a commit message.

Expected: roughly 40 lines across 11 files.

- [ ] **Step 2: Rewrite each occurrence to a generic equivalent**

Rules, applied in this order:

1. A **member name** used as an example becomes `PROGA`, `PROGB`, … in prose;
   an example paragraph becomes `MAIN` or `2000-UPDATE`.
2. A **field name** becomes the same shape with a neutral stem: a record-prefixed
   field becomes `REC1-CDE-STATUS`, a working-storage field becomes `WS-FLAG-A`,
   a map field becomes `FLAGI` / `FLAGO`.
3. A **copybook or layout file name** becomes `LAYOUT1.txt`, and a layout directory
   becomes `layouts/`.
4. A **config file name** becomes the neutral example name — in
   `depgraph/config.py`, `config/depgraph.<corpus>.example.toml` becomes
   `config/depgraph.example.toml`, and the file on disk is renamed to match if it
   exists under the old name.
5. A **measurement** stays exactly as it is: "2,129 of 3,779 members", "146,525
   nodes", "65% carry a guard" are the point of the comment and are not identifiers.

Keep every sentence's meaning. If a comment only makes sense because it names a real
member, rewrite the comment to state the general rule the member illustrated.

- [ ] **Step 3: Verify nothing remains**

```bash
cd cobble
grep -rniE '<client-app-prefix>|<client-file-prefix>|<client-dictionary-prefix>' \
  cobble tests config Makefile pyproject.toml ; echo "exit=$?"
```

Expected: no output, `exit=1`.

- [ ] **Step 4: Run the test suite**

Run: `make test`
Expected: PASS, same count as before the edits. If a test failed, a rename in step 2
crossed from a comment into an assertion — the data in the test must be renamed on
both sides.

- [ ] **Step 5: Commit**

```bash
git add cobble/dataflow tests/dataflow
git commit -m "$(cat <<'EOF'
chore(cobble): use generic names in dataflow examples and fixtures

Comments, docstrings and test fixtures only; no behaviour change. Measured
counts are kept, the names that made them traceable are not.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

The commit message must not name what was removed.

---

### Task 1: The CFG vocabulary

**Files:**
- Create: `cobble/dataflow/srccfg/__init__.py` (empty)
- Create: `cobble/dataflow/srccfg/cfg.py`
- Test: `tests/dataflow/srccfg/test_cfg.py`

**Interfaces:**
- Consumes: nothing.
- Produces the whole vocabulary every later task builds on:
  - `NodeKind` — `TEST`, `ASSIGN`, `LABEL`, `CALL`, `NOP`
  - `EdgeKind` — `FLOW`, `TRUE`, `FALSE`, `PERFORM`, `RETURN`, `FALLTHRU`, `GOTO`
  - `Atom(text: str, left: str, op: str, right: str, resolved: bool)` frozen
  - `UNRESOLVED: Atom` — the sentinel for a predicate that could not be read
  - `Node(id: str, kind: NodeKind, paragraph: str, atom: Atom, writes: tuple[str, ...], reads: tuple[str, ...], transfer: str, target: str)` frozen
  - `Edge(source: str, target: str, kind: EdgeKind)` frozen
  - `Cfg(program: str, nodes: tuple[Node, ...], edges: tuple[Edge, ...])` frozen, with
    `node_ids: frozenset[str]`, `successors(node_id) -> tuple[Edge, ...]`,
    `predecessors(node_id) -> tuple[Edge, ...]`, `node(node_id) -> Node`
  - `Fragment(nodes: tuple[Node, ...], edges: tuple[Edge, ...], entry: str, exits: tuple[Exit, ...])` frozen
  - `Exit(node_id: str, kind: EdgeKind)` frozen — a dangling out-edge waiting for a target
  - `EMPTY_FRAGMENT: Fragment`
  - `seq(fragments: Sequence[Fragment], nop_id: str) -> Fragment`
  - `merge(fragments: Sequence[Fragment]) -> Fragment` — nodes and edges only, no wiring

- [ ] **Step 1: Write the failing tests**

`tests/dataflow/srccfg/test_cfg.py`:

```python
"""The graph vocabulary. Everything downstream is written against these types, so
the invariants that matter are structural: a TEST has exactly two out-edges, a
fragment's exits are the only place the next statement may attach, and sequencing
two fragments consumes every exit of the first."""

from __future__ import annotations

import pytest

from cobble.dataflow.srccfg.cfg import (
    EMPTY_FRAGMENT,
    UNRESOLVED,
    Atom,
    Cfg,
    Edge,
    EdgeKind,
    Exit,
    Fragment,
    Node,
    NodeKind,
    merge,
    seq,
)


def _assign(node_id: str, writes: tuple[str, ...] = ("WS-A",)) -> Node:
    return Node(
        id=node_id,
        kind=NodeKind.ASSIGN,
        paragraph="MAIN",
        atom=UNRESOLVED,
        writes=writes,
        reads=("WS-B",),
        transfer="MOVE",
        target="",
    )


def _fragment(node_id: str) -> Fragment:
    """One ASSIGN node with one dangling FLOW exit -- the shape every
    straight-line statement lowers to."""
    return Fragment(
        nodes=(_assign(node_id),),
        edges=(),
        entry=node_id,
        exits=(Exit(node_id=node_id, kind=EdgeKind.FLOW),),
    )


def test_an_atom_carries_its_own_source_text() -> None:
    """The text is what a report shows a human; the parts are what a query filters
    on. Both are needed, so both are stored rather than reconstructed."""
    atom = Atom(text="WS-FLAG-A = 'Y'", left="WS-FLAG-A", op="==", right="'Y'")

    assert atom.resolved is True
    assert (atom.left, atom.op, atom.right) == ("WS-FLAG-A", "==", "'Y'")


def test_the_unresolved_atom_is_a_value_not_an_absence() -> None:
    """A predicate the ASG gives as opaque text -- SEARCH WHEN, a computed
    condition -- must still occupy a node, because a path through it is a real
    path. Dropping it would silently strengthen every condition downstream."""
    assert UNRESOLVED.resolved is False
    assert UNRESOLVED.left == ""


def test_a_fragment_with_no_nodes_has_no_entry_and_no_exits() -> None:
    assert EMPTY_FRAGMENT.nodes == ()
    assert EMPTY_FRAGMENT.entry == ""
    assert EMPTY_FRAGMENT.exits == ()


def test_sequencing_wires_every_exit_of_the_first_into_the_second() -> None:
    """An IF fragment leaves two exits, one per arm. Both continue into whatever
    follows the END-IF, so seq must attach all of them -- attaching only the last
    is the classic way an arm's assignments lose their successors."""
    left = Fragment(
        nodes=(_assign("a"), _assign("b")),
        edges=(),
        entry="a",
        exits=(
            Exit(node_id="a", kind=EdgeKind.TRUE),
            Exit(node_id="b", kind=EdgeKind.FALSE),
        ),
    )

    joined = seq((left, _fragment("c")), nop_id="unused")

    assert joined.entry == "a"
    assert set(joined.edges) == {
        Edge(source="a", target="c", kind=EdgeKind.TRUE),
        Edge(source="b", target="c", kind=EdgeKind.FALSE),
    }
    assert joined.exits == (Exit(node_id="c", kind=EdgeKind.FLOW),)


def test_sequencing_an_empty_fragment_changes_nothing() -> None:
    """A statement that lowers to nothing -- a comment-only paragraph, a verb with
    no dataflow and no control effect -- must not break the chain around it."""
    only = _fragment("a")

    assert seq((EMPTY_FRAGMENT, only, EMPTY_FRAGMENT), nop_id="unused") == only


def test_sequencing_nothing_is_empty() -> None:
    assert seq((), nop_id="unused") == EMPTY_FRAGMENT


def test_a_fragment_whose_exits_are_all_consumed_ends_the_chain() -> None:
    """A GO TO fragment has no exits: control leaves for a label. Anything
    sequenced after it is unreachable, and must not be wired to it."""
    goes = Fragment(
        nodes=(_assign("a"),), edges=(), entry="a", exits=()
    )

    joined = seq((goes, _fragment("b")), nop_id="unused")

    assert joined.edges == ()
    assert joined.entry == "a"
    assert joined.exits == (Exit(node_id="b", kind=EdgeKind.FLOW),)


def test_merge_collects_nodes_and_edges_without_wiring_them() -> None:
    """Paragraph fragments are collected before their PERFORM and GO TO edges can
    be resolved, so there is a step that unions without sequencing."""
    merged = merge((_fragment("a"), _fragment("b")))

    assert [node.id for node in merged.nodes] == ["a", "b"]
    assert merged.edges == ()
    assert merged.entry == "a"


def test_a_cfg_indexes_successors_and_predecessors_by_node() -> None:
    cfg = Cfg(
        program="PROGA",
        nodes=(_assign("a"), _assign("b")),
        edges=(Edge(source="a", target="b", kind=EdgeKind.FLOW),),
    )

    assert cfg.successors("a") == (Edge(source="a", target="b", kind=EdgeKind.FLOW),)
    assert cfg.predecessors("b") == (Edge(source="a", target="b", kind=EdgeKind.FLOW),)
    assert cfg.successors("b") == ()
    assert cfg.node("b").writes == ("WS-A",)


def test_asking_for_a_node_that_is_not_there_raises() -> None:
    """A missing node means an edge was built against an id nothing emitted --
    always a bug in lowering, never a query a caller should get an answer to."""
    cfg = Cfg(program="PROGA", nodes=(), edges=())

    with pytest.raises(KeyError):
        cfg.node("a")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg/test_cfg.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobble.dataflow.srccfg'`

- [ ] **Step 3: Write the implementation**

`cobble/dataflow/srccfg/__init__.py` is empty.

`cobble/dataflow/srccfg/cfg.py`:

```python
"""The graph vocabulary, with no knowledge of COBOL or of the ASG.

Two node kinds carry meaning. A TEST holds ONE atomic predicate and has exactly
two out-edges, TRUE and FALSE; an ASSIGN holds what it writes, what it reads and
which verb transferred the data. Everything else -- LABEL, CALL, NOP -- is
plumbing that a query walks through.

That split is what removes the need for a condition language: AND and OR are
lowered into chains of TESTs by the caller, and NOT is lowered by swapping a
fragment's TRUE and FALSE exits. So a reaching condition is a path, and there is
no formula to normalise and no solver to run.

A Fragment is a partly built graph: its exits are out-edges that have no target
yet, and sequencing is the act of giving them one. Absent values are empty
tuples and empty strings throughout -- never None -- so a caller never has to
ask whether a field is there before reading it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from functools import cached_property


class NodeKind(Enum):
    TEST = "TEST"
    ASSIGN = "ASSIGN"
    LABEL = "LABEL"
    CALL = "CALL"
    NOP = "NOP"


class EdgeKind(Enum):
    FLOW = "FLOW"
    TRUE = "TRUE"
    FALSE = "FALSE"
    PERFORM = "PERFORM"
    RETURN = "RETURN"
    FALLTHRU = "FALLTHRU"
    GOTO = "GOTO"


@dataclass(frozen=True)
class Atom:
    """One atomic predicate: no AND, no OR, no NOT.

    ``resolved`` False means the ASG gave text this pass could not decompose, and
    the parts are empty. Such an atom still gets a TEST node, because a path
    through an unreadable predicate is a real path.
    """

    text: str
    left: str = ""
    op: str = ""
    right: str = ""
    resolved: bool = True


UNRESOLVED = Atom(text="UNRESOLVED", resolved=False)


@dataclass(frozen=True)
class Node:
    id: str
    kind: NodeKind
    paragraph: str
    atom: Atom = UNRESOLVED
    writes: tuple[str, ...] = ()
    reads: tuple[str, ...] = ()
    transfer: str = ""
    target: str = ""


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    kind: EdgeKind


@dataclass(frozen=True)
class Exit:
    """An out-edge with no target yet: the node it leaves and the kind it will be."""

    node_id: str
    kind: EdgeKind


@dataclass(frozen=True)
class Fragment:
    nodes: tuple[Node, ...] = ()
    edges: tuple[Edge, ...] = ()
    entry: str = ""
    exits: tuple[Exit, ...] = ()


EMPTY_FRAGMENT = Fragment()


@dataclass(frozen=True)
class Cfg:
    program: str
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]

    @cached_property
    def _by_id(self) -> dict[str, Node]:
        return {node.id: node for node in self.nodes}

    @cached_property
    def node_ids(self) -> frozenset[str]:
        return frozenset(self._by_id)

    @cached_property
    def _out(self) -> dict[str, tuple[Edge, ...]]:
        return _group(self.edges, lambda edge: edge.source)

    @cached_property
    def _in(self) -> dict[str, tuple[Edge, ...]]:
        return _group(self.edges, lambda edge: edge.target)

    def node(self, node_id: str) -> Node:
        return self._by_id[node_id]

    def successors(self, node_id: str) -> tuple[Edge, ...]:
        return self._out.get(node_id, ())

    def predecessors(self, node_id: str) -> tuple[Edge, ...]:
        return self._in.get(node_id, ())


def _group(edges: Sequence[Edge], key) -> dict[str, tuple[Edge, ...]]:
    keys = tuple(dict.fromkeys(key(edge) for edge in edges))
    return {k: tuple(edge for edge in edges if key(edge) == k) for k in keys}


def merge(fragments: Sequence[Fragment]) -> Fragment:
    """Union nodes and edges, wire nothing. Used where targets are not known yet."""
    present = tuple(f for f in fragments if f.nodes or f.edges)
    if not present:
        return EMPTY_FRAGMENT
    return Fragment(
        nodes=tuple(node for f in present for node in f.nodes),
        edges=tuple(edge for f in present for edge in f.edges),
        entry=present[0].entry,
        exits=tuple(exit_ for f in present for exit_ in f.exits),
    )


def seq(fragments: Sequence[Fragment], nop_id: str) -> Fragment:
    """Chain fragments, giving every exit of each one the next one's entry.

    ``nop_id`` is reserved for callers that need a landing node when a chain has
    no statements of its own; it is unused when the chain is non-empty.
    """
    present = tuple(f for f in fragments if f is not EMPTY_FRAGMENT and f.nodes)
    if not present:
        return EMPTY_FRAGMENT
    return _fold(present[0], present[1:])


def _fold(acc: Fragment, rest: Sequence[Fragment]) -> Fragment:
    if not rest:
        return acc
    return _fold(_join(acc, rest[0]), rest[1:])


def _join(left: Fragment, right: Fragment) -> Fragment:
    return Fragment(
        nodes=(*left.nodes, *right.nodes),
        edges=(
            *left.edges,
            *right.edges,
            *(
                Edge(source=exit_.node_id, target=right.entry, kind=exit_.kind)
                for exit_ in left.exits
            ),
        ),
        entry=left.entry,
        exits=right.exits,
    )
```

Note `field` is imported but must be removed if unused — run `make lint` and delete
the unused import rather than leaving it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg/test_cfg.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Check the style gates**

```bash
cd cobble
uv run --no-sync python -m python_fp_lint check cobble/dataflow/srccfg/
make fmt
```
Expected: fp-lint reports 0 violations. `cached_property` on a frozen dataclass needs
no mutation because the decorator writes through `object.__setattr__` — if fp-lint
flags it anyway, replace the four `cached_property` members with plain methods that
rebuild their index, and keep the same names.

- [ ] **Step 6: Commit**

```bash
git add cobble/dataflow/srccfg tests/dataflow/srccfg
git commit -m "$(cat <<'EOF'
feat(cobble): add the source CFG vocabulary

Two semantic node kinds -- TEST with one atomic predicate, ASSIGN with
writes/reads/transfer -- plus fragments whose dangling exits are wired by seq().
Lowering AND/OR into TEST chains is what lets a reaching condition be a path
rather than a formula.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---
### Task 2: The condition tree

The ASG gives conditions as nested dicts. This task turns them into a small tree of
`Atom` leaves under `And` / `Or` / `Not` nodes, and nothing else — the lowering to
TEST chains is Task 4's job. Every shape the cache actually contains is listed below;
anything else becomes `UNRESOLVED` rather than raising, because one unreadable
predicate must not cost a whole member.

**Files:**
- Create: `cobble/dataflow/srccfg/conditions.py`
- Create: `tests/dataflow/srccfg/conftest.py`
- Test: `tests/dataflow/srccfg/test_conditions.py`

**Interfaces:**
- Consumes: `cfg.Atom`, `cfg.UNRESOLVED`.
- Produces:
  - `Cond` — the union alias `Atom | And | Or | Not`
  - `And(left: Cond, right: Cond)`, `Or(left: Cond, right: Cond)`, `Not(inner: Cond)` frozen
  - `read_condition(raw: object) -> Cond`
  - `negate_atom(atom: Atom) -> Atom` — for reporting a FALSE-edge atom in prose
  - `EIGHTY_EIGHT: str` — the `op` used for a bare condition-name atom
  - `class_atom(operand: str, class_name: str) -> Atom`

The ASG condition shapes, verified against the cache:

| Shape | Meaning |
| --- | --- |
| `{"not": bool, "relation": {"left": …, "op": …, "right": …}}` | a relational atom |
| `{"op": "AND"\|"OR", "left": …, "right": …}` | a binary combination |
| `{"not": bool, "condition": {…}}` | a parenthesised sub-condition |
| `{"not": bool, "condition_name": "NAME"}` | an 88-level reference |
| `{"not": bool, "class": "NUMERIC", "operand": {…}}` | a class test |
| `{"kind": "ref", "name": "WS-A"}` | an operand naming a field |
| `{"kind": "lit", "value": "'Y'"}` | an operand holding a literal |
| `{"kind": "dfhresp", "condition": "NORMAL"}` | `DFHRESP(NORMAL)` in a CICS test |
| a bare `str` | a WHEN subject that is an 88 name or a literal |

Operators appear exactly as `==`, `!=`, `>`, `<`, `>=`, `<=`, and the combinators
exactly as `AND`, `OR`.

- [ ] **Step 1: Write the conftest**

`tests/dataflow/srccfg/conftest.py`:

```python
"""Fixtures shared by the srccfg tests.

``asg_of`` is the one that matters: a program's procedure division as a dict, in
the exact shape the parse cache holds, turned into the same CobolASG object the
real pass consumes. Registering the dialect parsers is not optional -- without it
any member containing EXEC CICS raises "Unknown COBOL statement type".

No corpus member is named in any test. ``corpus_asg_paths`` reads a gitignored
config so a developer can run the slow acceptance test against a real cache
without that cache's identifiers entering the repository; with no config, the
tests that use it skip.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from cobol_asg.asg_types import CobolASG

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered

CORPUS_CONFIG = Path(__file__).resolve().parents[3] / "config" / "srccfg-tests.toml"


@pytest.fixture
def asg_of():
    """Build a CobolASG from a procedure-division dict."""

    def build(body: Mapping) -> CobolASG:
        with cached_asg_dialect_parsers_registered():
            return CobolASG.from_dict(json.loads(json.dumps(dict(body))))

    return build


@pytest.fixture
def program_of(asg_of):
    """A one-paragraph program named PROGA whose paragraph is MAIN."""

    def build(statements: Sequence[Mapping], **extra) -> CobolASG:
        return asg_of(
            {
                "program_id": "PROGA",
                "paragraphs": [{"name": "MAIN", "statements": list(statements)}],
                **extra,
            }
        )

    return build


@pytest.fixture
def corpus_asg_paths() -> tuple[Path, ...]:
    """Parsed-ASG files from a real cache, or a skip.

    The config is gitignored (`config/*.toml`), so the member names it points at
    stay out of the repository. Shape:

        cache_dir = "/abs/path/to/out-<corpus>-parsed"
        members = ["SOMEMEMBER", "OTHERMEMBER"]
    """
    if not CORPUS_CONFIG.is_file():
        pytest.skip(f"no {CORPUS_CONFIG.name}; acceptance test needs a parsed cache")
    raw = tomllib.loads(CORPUS_CONFIG.read_text())
    cache = Path(raw["cache_dir"])
    return tuple(cache / f"{member}.json" for member in raw["members"])
```

- [ ] **Step 2: Write the failing tests**

`tests/dataflow/srccfg/test_conditions.py`:

```python
"""Reading the ASG's condition dicts into a tree of atoms.

Nothing here lowers anything: the point is that every shape the cache holds
becomes either an atom with its parts filled in or, when it cannot be read, an
UNRESOLVED atom that still occupies a leaf.
"""

from __future__ import annotations

from cobble.dataflow.srccfg.cfg import UNRESOLVED, Atom
from cobble.dataflow.srccfg.conditions import (
    EIGHTY_EIGHT,
    And,
    Not,
    Or,
    negate_atom,
    read_condition,
)


def _rel(left: str, op: str, right: str, negated: bool = False) -> dict:
    return {
        "not": negated,
        "relation": {
            "left": {"kind": "ref", "name": left},
            "op": op,
            "right": {"kind": "lit", "value": right},
        },
    }


def test_a_relational_condition_becomes_one_atom_with_its_parts() -> None:
    assert read_condition(_rel("WS-FLAG-A", "==", "'Y'")) == Atom(
        text="WS-FLAG-A == 'Y'", left="WS-FLAG-A", op="==", right="'Y'"
    )


def test_a_field_on_both_sides_keeps_both_names() -> None:
    """A guard comparing two fields is a dependency on both of them, so neither
    side may be flattened into text."""
    raw = {
        "not": False,
        "relation": {
            "left": {"kind": "ref", "name": "WS-FLAG-A"},
            "op": "==",
            "right": {"kind": "ref", "name": "WS-FLAG-B"},
        },
    }

    assert read_condition(raw) == Atom(
        text="WS-FLAG-A == WS-FLAG-B", left="WS-FLAG-A", op="==", right="WS-FLAG-B"
    )


def test_a_negated_relation_becomes_a_not_around_the_atom() -> None:
    """NOT stays a node rather than flipping the operator: the lowering pass
    implements it by swapping edges, and an operator flip would be wrong for a
    class test or an 88 name where there is no operator to flip."""
    assert read_condition(_rel("WS-FLAG-A", "==", "'Y'", negated=True)) == Not(
        inner=Atom(text="WS-FLAG-A == 'Y'", left="WS-FLAG-A", op="==", right="'Y'")
    )


def test_and_and_or_nest_left_and_right() -> None:
    raw = {
        "op": "OR",
        "left": _rel("WS-FLAG-A", "==", "'Y'"),
        "right": {
            "op": "AND",
            "left": _rel("WS-FLAG-B", "==", "'N'"),
            "right": _rel("WS-TYPE-C", "==", "'G'"),
        },
    }

    assert read_condition(raw) == Or(
        left=Atom(text="WS-FLAG-A == 'Y'", left="WS-FLAG-A", op="==", right="'Y'"),
        right=And(
            left=Atom(text="WS-FLAG-B == 'N'", left="WS-FLAG-B", op="==", right="'N'"),
            right=Atom(text="WS-TYPE-C == 'G'", left="WS-TYPE-C", op="==", right="'G'"),
        ),
    )


def test_a_parenthesised_subcondition_is_read_through() -> None:
    raw = {"not": False, "condition": _rel("WS-FLAG-A", "==", "'Y'")}

    assert read_condition(raw) == Atom(
        text="WS-FLAG-A == 'Y'", left="WS-FLAG-A", op="==", right="'Y'"
    )


def test_a_negated_parenthesised_subcondition_negates_the_whole_group() -> None:
    """NOT (A AND B) is not NOT A AND NOT B, and the group is the only place the
    ASG records that the negation is outside the combination."""
    raw = {
        "not": True,
        "condition": {
            "op": "AND",
            "left": _rel("WS-FLAG-A", "==", "'Y'"),
            "right": _rel("WS-FLAG-B", "==", "'N'"),
        },
    }

    assert isinstance(read_condition(raw), Not)
    assert isinstance(read_condition(raw).inner, And)


def test_a_condition_name_becomes_an_atom_naming_the_88() -> None:
    """An 88 level is a named predicate on its parent field. Until the data
    division is consulted the name is all there is, and it is a real dependency."""
    raw = {"not": False, "condition_name": "WS-FLAG-A-SET"}

    assert read_condition(raw) == Atom(
        text="WS-FLAG-A-SET", left="WS-FLAG-A-SET", op=EIGHTY_EIGHT, right=""
    )


def test_a_class_test_keeps_the_operand_and_the_class() -> None:
    raw = {
        "not": False,
        "class": "NUMERIC",
        "operand": {"kind": "ref", "name": "WS-AMOUNT"},
    }

    assert read_condition(raw) == Atom(
        text="WS-AMOUNT IS NUMERIC", left="WS-AMOUNT", op="CLASS", right="NUMERIC"
    )


def test_a_dfhresp_operand_reads_as_the_condition_it_names() -> None:
    """EXEC CICS response tests are guards like any other, and the field they read
    is the response code the preceding command set."""
    raw = {
        "not": False,
        "relation": {
            "left": {"kind": "ref", "name": "WS-RESP"},
            "op": "==",
            "right": {"kind": "dfhresp", "condition": "NORMAL"},
        },
    }

    assert read_condition(raw) == Atom(
        text="WS-RESP == DFHRESP(NORMAL)",
        left="WS-RESP",
        op="==",
        right="DFHRESP(NORMAL)",
    )


def test_a_bare_string_condition_is_an_atom_of_that_text() -> None:
    """EVALUATE WHEN gives its subject as plain text when it is an 88 name or a
    literal, and SEARCH WHEN gives the whole predicate that way."""
    assert read_condition("WS-FLAG-A-SET") == Atom(
        text="WS-FLAG-A-SET", left="WS-FLAG-A-SET", op=EIGHTY_EIGHT, right=""
    )


def test_a_shape_this_pass_does_not_know_is_unresolved_not_an_error() -> None:
    """One unreadable predicate must cost that predicate's parts, not the member.
    The leaf still exists, so the path through it still exists."""
    assert read_condition({"something": "new"}) == UNRESOLVED


def test_an_empty_condition_is_unresolved() -> None:
    assert read_condition(None) == UNRESOLVED


def test_negating_an_atom_for_a_report_flips_the_operator() -> None:
    """The graph negates by taking the FALSE edge. A report that prints one path
    still needs prose for that edge, and for a relation the readable form is the
    flipped operator."""
    atom = Atom(text="WS-FLAG-A == 'Y'", left="WS-FLAG-A", op="==", right="'Y'")

    assert negate_atom(atom) == Atom(
        text="WS-FLAG-A != 'Y'", left="WS-FLAG-A", op="!=", right="'Y'"
    )


def test_negating_a_predicate_with_no_opposite_operator_says_not() -> None:
    """An 88 name and a class test have no flipped operator, so the readable form
    is a NOT prefix -- and the parts stay as they were, because the field being
    depended on has not changed."""
    atom = Atom(text="WS-FLAG-A-SET", left="WS-FLAG-A-SET", op=EIGHTY_EIGHT)

    assert negate_atom(atom).text == "NOT WS-FLAG-A-SET"
    assert negate_atom(atom).left == "WS-FLAG-A-SET"


def test_negating_the_unresolved_atom_stays_unresolved() -> None:
    assert negate_atom(UNRESOLVED).resolved is False
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg/test_conditions.py -v`
Expected: FAIL — `ImportError: cannot import name 'read_condition'`

- [ ] **Step 4: Write the implementation**

`cobble/dataflow/srccfg/conditions.py`:

```python
"""ASG condition dicts to a tree of atoms.

Only reading happens here. AND/OR/NOT stay as nodes; turning them into TEST
chains is desugar.py's job, and NOT in particular is implemented there as an edge
swap, which is why it must survive as a node rather than being folded into the
operator now -- an 88 name and a class test have no operator to fold into.

A shape this module does not recognise yields UNRESOLVED rather than raising. The
leaf still exists, so no path is silently removed; what is lost is the parts, and
that loss is visible in every report because ``resolved`` is False.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from cobble.dataflow.srccfg.cfg import UNRESOLVED, Atom

EIGHTY_EIGHT = "88"
CLASS = "CLASS"

_OPPOSITE = {"==": "!=", "!=": "==", ">": "<=", "<=": ">", "<": ">=", ">=": "<"}


@dataclass(frozen=True)
class And:
    left: Cond
    right: Cond


@dataclass(frozen=True)
class Or:
    left: Cond
    right: Cond


@dataclass(frozen=True)
class Not:
    inner: Cond


Cond = Atom | And | Or | Not


def read_condition(raw: object) -> Cond:
    if isinstance(raw, str):
        return _named(raw)
    if not isinstance(raw, Mapping):
        return UNRESOLVED
    return _wrap(raw, _body(raw))


def _wrap(raw: Mapping, inner: Cond) -> Cond:
    return Not(inner=inner) if raw.get("not") else inner


def _body(raw: Mapping) -> Cond:
    if "op" in raw and "left" in raw:
        return _combine(str(raw["op"]), raw["left"], raw["right"])
    if "relation" in raw:
        return _relation(raw["relation"])
    if "condition" in raw:
        return read_condition(raw["condition"])
    if "condition_name" in raw:
        return _named(str(raw["condition_name"]))
    if "class" in raw:
        return _class_test(raw)
    return UNRESOLVED


def _combine(op: str, left: object, right: object) -> Cond:
    read = (read_condition(left), read_condition(right))
    if op == "AND":
        return And(left=read[0], right=read[1])
    if op == "OR":
        return Or(left=read[0], right=read[1])
    return UNRESOLVED


def _relation(raw: object) -> Cond:
    if not isinstance(raw, Mapping):
        return UNRESOLVED
    left = _operand(raw.get("left"))
    right = _operand(raw.get("right"))
    op = str(raw.get("op", ""))
    if not op or not left:
        return UNRESOLVED
    return Atom(text=f"{left} {op} {right}", left=left, op=op, right=right)


def _operand(raw: object) -> str:
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, Mapping):
        return ""
    kind = raw.get("kind")
    if kind == "ref":
        return str(raw.get("name", ""))
    if kind == "lit":
        return str(raw.get("value", ""))
    if kind == "dfhresp":
        return f"DFHRESP({raw.get('condition', '')})"
    return ""


def _named(name: str) -> Cond:
    return Atom(text=name, left=name, op=EIGHTY_EIGHT) if name else UNRESOLVED


def _class_test(raw: Mapping) -> Cond:
    operand = _operand(raw.get("operand"))
    class_name = str(raw.get("class", ""))
    if not operand:
        return UNRESOLVED
    return class_atom(operand, class_name)


def class_atom(operand: str, class_name: str) -> Atom:
    return Atom(
        text=f"{operand} IS {class_name}", left=operand, op=CLASS, right=class_name
    )


def negate_atom(atom: Atom) -> Atom:
    """The readable form of an atom's FALSE edge.

    The graph needs no such thing -- the edge is the negation -- but a report that
    prints a path does. The parts are unchanged where there is no opposite
    operator, because the field depended on is the same either way.
    """
    if not atom.resolved:
        return atom
    flipped = _OPPOSITE.get(atom.op, "")
    if not flipped:
        return Atom(
            text=f"NOT {atom.text}", left=atom.left, op=atom.op, right=atom.right
        )
    return Atom(
        text=f"{atom.left} {flipped} {atom.right}",
        left=atom.left,
        op=flipped,
        right=atom.right,
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg/test_conditions.py -v`
Expected: PASS, 15 tests.

- [ ] **Step 6: Commit**

```bash
git add cobble/dataflow/srccfg/conditions.py tests/dataflow/srccfg
git commit -m "$(cat <<'EOF'
feat(cobble): read ASG conditions into a tree of atoms

Every condition shape the parse cache holds -- relations, AND/OR, parenthesised
groups, 88 names, class tests, DFHRESP -- reads into atoms with their parts
filled in. An unrecognised shape becomes UNRESOLVED so that one unreadable
predicate costs its parts, not the member.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---
### Task 3: Resolve 88-level condition names to their parent field

A guard written as an 88 name depends on the parent field, not on the name, and a
query for "what does this field depend on" has to see that parent. The data division
carries the mapping: `CobolField.conditions` is a list of `ConditionName(name, values)`
on the parent field, and `ConditionValue(from_val, to_val)` holds a discrete value or
a `THRU` range.

**Files:**
- Modify: `cobble/dataflow/srccfg/conditions.py`
- Test: `tests/dataflow/srccfg/test_conditions_88.py`

**Interfaces:**
- Consumes: `cfg.Atom`, `conditions.EIGHTY_EIGHT`, `CobolASG.data_fields` /
  `.linkage_fields` / `.local_storage_fields` / `.file_fields`, each a
  `list[CobolField]` with `name`, `level`, `children`, and
  `conditions: list[ConditionName]`.
- Produces:
  - `EightyEight(name: str, parent: str, values: tuple[str, ...], ranges: tuple[tuple[str, str], ...])` frozen
  - `condition_index(asg) -> Mapping[str, EightyEight]` — every 88 name in the program,
    upper-cased, mapped to its parent field
  - `resolve_atom(atom: Atom, index: Mapping[str, EightyEight]) -> Atom`
  - `IN = "IN"`, `RANGE = "RANGE"` — the operators a multi-valued 88 resolves to

- [ ] **Step 1: Write the failing tests**

`tests/dataflow/srccfg/test_conditions_88.py`:

```python
"""An 88 name is a predicate on its parent field, and the parent is the
dependency. Resolving it is what stops a guard from reporting a name nothing else
in the corpus mentions."""

from __future__ import annotations

from cobble.dataflow.srccfg.cfg import UNRESOLVED, Atom
from cobble.dataflow.srccfg.conditions import (
    EIGHTY_EIGHT,
    IN,
    RANGE,
    EightyEight,
    condition_index,
    resolve_atom,
)

_WITH_88 = {
    "program_id": "PROGA",
    "data_fields": [
        {
            "name": "WS-GROUP",
            "level": 1,
            "children": [
                {
                    "name": "WS-STATUS",
                    "level": 5,
                    "pic": "X(1)",
                    "conditions": [
                        {"name": "STATUS-ACTIVE", "values": [{"from": "'A'"}]},
                        {
                            "name": "STATUS-VALID",
                            "values": [{"from": "'A'"}, {"from": "'B'"}],
                        },
                        {
                            "name": "STATUS-ALPHA",
                            "values": [{"from": "'A'", "to": "'Z'"}],
                        },
                    ],
                }
            ],
        }
    ],
    "paragraphs": [{"name": "MAIN", "statements": []}],
}


def test_the_index_finds_an_88_nested_under_a_group(asg_of) -> None:
    """Level 88s hang off elementary items that are usually children of an 01
    group, so a scan of the top level alone finds none of them."""
    index = condition_index(asg_of(_WITH_88))

    assert index["STATUS-ACTIVE"] == EightyEight(
        name="STATUS-ACTIVE", parent="WS-STATUS", values=("'A'",), ranges=()
    )


def test_an_88_with_several_discrete_values_keeps_them_all(asg_of) -> None:
    index = condition_index(asg_of(_WITH_88))

    assert index["STATUS-VALID"].values == ("'A'", "'B'")


def test_a_thru_range_is_kept_as_a_range_not_flattened(asg_of) -> None:
    """VALUE 'A' THRU 'Z' is not the two values 'A' and 'B'; reporting it as a
    value list would make the guard read as a false equality."""
    index = condition_index(asg_of(_WITH_88))

    assert index["STATUS-ALPHA"] == EightyEight(
        name="STATUS-ALPHA", parent="WS-STATUS", values=(), ranges=(("'A'", "'Z'"),)
    )


def test_the_index_covers_linkage_and_file_and_local_storage(asg_of) -> None:
    """A commarea 88 and an FD-record 88 are as common as a working-storage one,
    and the sections are separate lists on the ASG."""
    asg = asg_of(
        {
            "program_id": "PROGA",
            "linkage_fields": [
                {
                    "name": "LK-FLAG",
                    "level": 1,
                    "pic": "X(1)",
                    "conditions": [{"name": "LK-FLAG-ON", "values": [{"from": "'Y'"}]}],
                }
            ],
            "file_fields": [
                {
                    "name": "REC1-CDE",
                    "level": 1,
                    "pic": "X(1)",
                    "conditions": [{"name": "REC1-OK", "values": [{"from": "'0'"}]}],
                }
            ],
            "local_storage_fields": [
                {
                    "name": "LS-MODE",
                    "level": 1,
                    "pic": "X(1)",
                    "conditions": [{"name": "LS-BATCH", "values": [{"from": "'B'"}]}],
                }
            ],
            "paragraphs": [{"name": "MAIN", "statements": []}],
        }
    )

    index = condition_index(asg)

    assert [index[name].parent for name in ("LK-FLAG-ON", "REC1-OK", "LS-BATCH")] == [
        "LK-FLAG",
        "REC1-CDE",
        "LS-MODE",
    ]


def test_resolving_a_single_valued_88_gives_an_equality_on_the_parent(asg_of) -> None:
    """This is the shape a report should show: the name is what the code says, the
    equality is what it means, and the parent is what the query filters on."""
    index = condition_index(asg_of(_WITH_88))
    atom = Atom(text="STATUS-ACTIVE", left="STATUS-ACTIVE", op=EIGHTY_EIGHT)

    assert resolve_atom(atom, index) == Atom(
        text="STATUS-ACTIVE (WS-STATUS == 'A')",
        left="WS-STATUS",
        op="==",
        right="'A'",
    )


def test_resolving_a_multi_valued_88_gives_a_membership_test(asg_of) -> None:
    index = condition_index(asg_of(_WITH_88))
    atom = Atom(text="STATUS-VALID", left="STATUS-VALID", op=EIGHTY_EIGHT)

    assert resolve_atom(atom, index) == Atom(
        text="STATUS-VALID (WS-STATUS IN 'A' 'B')",
        left="WS-STATUS",
        op=IN,
        right="'A' 'B'",
    )


def test_resolving_a_range_88_says_it_is_a_range(asg_of) -> None:
    index = condition_index(asg_of(_WITH_88))
    atom = Atom(text="STATUS-ALPHA", left="STATUS-ALPHA", op=EIGHTY_EIGHT)

    resolved = resolve_atom(atom, index)

    assert (resolved.left, resolved.op, resolved.right) == (
        "WS-STATUS",
        RANGE,
        "'A' THRU 'Z'",
    )


def test_an_88_the_data_division_does_not_declare_stays_as_it_was(asg_of) -> None:
    """The name is in a copybook the parse could not resolve, or is a paragraph
    name the ASG typed as a condition. Either way the atom is still the guard that
    was written, so it is kept rather than dropped or turned into UNRESOLVED."""
    index = condition_index(asg_of(_WITH_88))
    atom = Atom(text="NOT-DECLARED", left="NOT-DECLARED", op=EIGHTY_EIGHT)

    assert resolve_atom(atom, index) == atom


def test_an_atom_that_is_not_an_88_is_returned_untouched(asg_of) -> None:
    index = condition_index(asg_of(_WITH_88))
    atom = Atom(text="WS-FLAG-A == 'Y'", left="WS-FLAG-A", op="==", right="'Y'")

    assert resolve_atom(atom, index) == atom
    assert resolve_atom(UNRESOLVED, index) == UNRESOLVED


def test_a_program_with_no_data_division_has_an_empty_index(asg_of) -> None:
    index = condition_index(asg_of({"program_id": "PROGA"}))

    assert dict(index) == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg/test_conditions_88.py -v`
Expected: FAIL — `ImportError: cannot import name 'condition_index'`

- [ ] **Step 3: Write the implementation**

Append to `cobble/dataflow/srccfg/conditions.py`:

```python
IN = "IN"
RANGE = "RANGE"


@dataclass(frozen=True)
class EightyEight:
    """A level-88 condition name and the parent field it tests."""

    name: str
    parent: str
    values: tuple[str, ...] = ()
    ranges: tuple[tuple[str, str], ...] = ()


def condition_index(asg) -> Mapping[str, EightyEight]:
    """Every 88 name declared anywhere in the program, keyed upper-case.

    All four data sections are walked, and each is a forest -- an 88 hangs off an
    elementary item that is normally a child of an 01, so only a recursive walk
    finds them.
    """
    roots = (
        *asg.data_fields,
        *asg.linkage_fields,
        *asg.local_storage_fields,
        *asg.file_fields,
    )
    return {entry.name.upper(): entry for entry in _walk_fields(roots)}


def _walk_fields(fields) -> tuple[EightyEight, ...]:
    return tuple(
        entry
        for cobol_field in fields
        for entry in (*_entries(cobol_field), *_walk_fields(cobol_field.children))
    )


def _entries(cobol_field) -> tuple[EightyEight, ...]:
    return tuple(
        EightyEight(
            name=condition.name.upper(),
            parent=cobol_field.name.upper(),
            values=tuple(v.from_val for v in condition.values if not v.is_range),
            ranges=tuple(
                (v.from_val, v.to_val) for v in condition.values if v.is_range
            ),
        )
        for condition in cobol_field.conditions
    )


def resolve_atom(atom: Atom, index: Mapping[str, EightyEight]) -> Atom:
    """Rewrite an 88-name atom as a predicate on its parent field.

    The text keeps the name the code was written with, because that is what a
    reader recognises; ``left`` becomes the parent, because that is what a
    dependency query filters on. An undeclared name is left exactly as it is --
    it is still the guard that was written.
    """
    if atom.op != EIGHTY_EIGHT:
        return atom
    entry = index.get(atom.left.upper())
    if not entry:
        return atom
    return _from_entry(atom.text, entry)


def _from_entry(name: str, entry: EightyEight) -> Atom:
    op, right = _op_and_right(entry)
    if not op:
        return Atom(text=name, left=entry.parent, op=EIGHTY_EIGHT)
    return Atom(
        text=f"{name} ({entry.parent} {op} {right})",
        left=entry.parent,
        op=op,
        right=right,
    )


def _op_and_right(entry: EightyEight) -> tuple[str, str]:
    if entry.ranges:
        return (RANGE, " ".join(f"{lo} THRU {hi}" for lo, hi in entry.ranges))
    if len(entry.values) == 1:
        return ("==", entry.values[0])
    if entry.values:
        return (IN, " ".join(entry.values))
    return ("", "")
```

The `RANGE` case takes precedence over `values` because an 88 that mixes a range
with discrete values is rare and the range is the part a reader must not see
flattened; the text keeps both.

- [ ] **Step 4: Run both condition test modules**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg -v`
Expected: PASS, 25 tests.

- [ ] **Step 5: Commit**

```bash
git add cobble/dataflow/srccfg/conditions.py tests/dataflow/srccfg/test_conditions_88.py
git commit -m "$(cat <<'EOF'
feat(cobble): resolve 88-level names to their parent field

A guard written as a condition name depends on the parent field, so the atom
keeps the name as its text and carries the parent as its left operand. THRU
ranges stay ranges; an undeclared name is kept rather than dropped.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---
### Task 4: Straight-line lowering — ASSIGN nodes and node identity

The first slice of `desugar.py`: statements with no control effect. Data movement is
**not** re-derived here — `depgraph.flows` already has the verb table, and a second
copy of it would drift. `flows.blocks_of` returns `(sources, targets)` blocks and
`flows.verb_of` returns the verb label; this task turns each block into an `ASSIGN`
node. The one gap is `INITIALIZE`, which `_RULES` has no entry for: it is a definition
with no source, and a definition with no source still kills the previous one, so
srccfg needs its own writes-only rule.

No ASG statement carries a line number, so **identity is a path**: `MAIN/3` is the
fourth statement of paragraph `MAIN`, `MAIN/3.else.1` the second statement of its ELSE
arm. Paths are stable across reruns of the same source and are what every artifact
and report keys on.

**Files:**
- Create: `cobble/dataflow/srccfg/desugar.py`
- Test: `tests/dataflow/srccfg/test_desugar_assign.py`

**Interfaces:**
- Consumes: `cfg.{Node, NodeKind, Edge, EdgeKind, Exit, Fragment, EMPTY_FRAGMENT, UNRESOLVED, seq}`,
  `conditions.{condition_index, resolve_atom}`,
  `cobble.dataflow.depgraph.flows.{blocks_of, verb_of, program_context, ProgramContext}`,
  `cobble.dataflow.depgraph.graph.is_literal`.
- Produces:
  - `Ctx(program: str, paragraph: str, flows: ProgramContext, index: Mapping[str, EightyEight])` frozen
  - `node_id(ctx: Ctx, path: str, suffix: str) -> str`
  - `lower_statement(statement, ctx: Ctx, path: str) -> Fragment`
  - `lower_statements(statements: Sequence, ctx: Ctx, path: str) -> Fragment`
  - `WRITES_ONLY: Mapping[str, ...]` — the kinds `flows` has no rule for
  - `WRITES_ONLY_KINDS = ("InitializeStatement",)`

- [ ] **Step 1: Write the failing tests**

`tests/dataflow/srccfg/test_desugar_assign.py`:

```python
"""Statements with no control effect, and the node identity every artifact keys on.

The verb table is not reimplemented here: flows.blocks_of already knows what each
statement moves, and this slice only turns its answer into nodes.
"""

from __future__ import annotations

from cobble.dataflow.srccfg.cfg import EdgeKind, NodeKind
from cobble.dataflow.srccfg.desugar import Ctx, lower_statement, lower_statements
from cobble.dataflow.srccfg.conditions import condition_index
from cobble.dataflow.depgraph.flows import program_context


def _ctx(asg, paragraph: str = "MAIN") -> Ctx:
    return Ctx(
        program=asg.program_id,
        paragraph=paragraph,
        flows=program_context(asg),
        index=condition_index(asg),
    )


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


def _only(program_of, statement: dict):
    asg = program_of([statement])
    return lower_statement(asg.paragraphs[0].statements[0], _ctx(asg), "0")


def test_a_move_becomes_one_assign_node_naming_what_it_reads_and_writes(
    program_of,
) -> None:
    fragment = _only(program_of, _move("WS-FLAG-A", "WS-FLAG-B"))

    node = fragment.nodes[0]
    assert (node.kind, node.writes, node.reads, node.transfer) == (
        NodeKind.ASSIGN,
        ("WS-FLAG-B",),
        ("WS-FLAG-A",),
        "MOVE",
    )


def test_the_node_id_is_the_paragraph_and_the_statement_path(program_of) -> None:
    """No ASG statement carries a line number, so identity has to come from
    position. A path is stable across reruns of the same source, which is what a
    stored artifact and a report need to agree on."""
    fragment = _only(program_of, _move("WS-FLAG-A", "WS-FLAG-B"))

    assert fragment.nodes[0].id == "MAIN/0"
    assert fragment.nodes[0].paragraph == "MAIN"


def test_a_fragment_leaves_one_flow_exit_for_the_next_statement(program_of) -> None:
    fragment = _only(program_of, _move("WS-FLAG-A", "WS-FLAG-B"))

    assert fragment.entry == "MAIN/0"
    assert [(e.node_id, e.kind) for e in fragment.exits] == [("MAIN/0", EdgeKind.FLOW)]


def test_a_move_to_two_targets_writes_both_from_one_node(program_of) -> None:
    """One statement, so one node: the co-assignment tier that means "same
    statement" is exactly this, and splitting it into two nodes would lose it."""
    fragment = _only(
        program_of,
        {
            "type": "MOVE",
            "operands": [{"name": "WS-FLAG-A"}, {"name": "WS-B"}, {"name": "WS-C"}],
        },
    )

    assert len(fragment.nodes) == 1
    assert fragment.nodes[0].writes == ("WS-B", "WS-C")


def test_a_literal_source_is_kept_as_a_read(program_of) -> None:
    """MOVE 'F' TO X is the assignment a dictionary rule is usually about, so the
    literal has to survive as the node's source rather than be filtered out."""
    fragment = _only(program_of, _move("'F'", "WS-FLAG-B"))

    assert fragment.nodes[0].reads == ("'F'",)


def test_a_compute_reads_every_name_in_its_expression(program_of) -> None:
    """flows.expression_names already walks the expression tree; this asserts the
    reuse, not a reimplementation."""
    fragment = _only(
        program_of,
        {
            "type": "COMPUTE",
            "targets": [{"name": "WS-TOTAL"}],
            "expression": {
                "kind": "binary",
                "op": "+",
                "left": {"kind": "ref", "name": "WS-A"},
                "right": {"kind": "ref", "name": "WS-B"},
            },
        },
    )

    node = fragment.nodes[0]
    assert node.writes == ("WS-TOTAL",)
    assert set(node.reads) == {"WS-A", "WS-B"}
    assert node.transfer == "COMPUTE"


def test_initialize_writes_with_no_source(program_of) -> None:
    """flows has no rule for INITIALIZE, because a source-to-target edge needs a
    source. Here it matters anyway: a definition with no source still kills the
    previous definition, and a reaching-definitions pass that cannot see the kill
    reports a stale writer."""
    fragment = _only(program_of, {"type": "INITIALIZE", "targets": [{"name": "WS-REC"}]})

    node = fragment.nodes[0]
    assert (node.kind, node.writes, node.reads, node.transfer) == (
        NodeKind.ASSIGN,
        ("WS-REC",),
        (),
        "INITIALIZE",
    )


def test_a_statement_that_moves_nothing_still_gets_a_node(program_of) -> None:
    """A verb with a rule that yielded no block -- a bare REWRITE, a DISPLAY --
    still happened. Dropping it would make the statements either side of it look
    adjacent, and a GO TO or a paragraph exit hides behind exactly that."""
    fragment = _only(program_of, {"type": "DISPLAY", "operands": [{"name": "WS-A"}]})

    assert len(fragment.nodes) == 1
    assert fragment.nodes[0].kind == NodeKind.NOP


def test_consecutive_statements_are_chained_in_order(program_of) -> None:
    asg = program_of([_move("WS-A", "WS-B"), _move("WS-B", "WS-C")])

    fragment = lower_statements(asg.paragraphs[0].statements, _ctx(asg), "")

    assert [node.id for node in fragment.nodes] == ["MAIN/0", "MAIN/1"]
    assert [(e.source, e.target, e.kind) for e in fragment.edges] == [
        ("MAIN/0", "MAIN/1", EdgeKind.FLOW)
    ]


def test_a_nested_path_is_prefixed_by_its_parent(program_of) -> None:
    """Paths compose, so a statement inside an arm inside a loop still has one id
    and it says where it is."""
    asg = program_of([_move("WS-A", "WS-B")])

    fragment = lower_statements(asg.paragraphs[0].statements, _ctx(asg), "3.else")

    assert fragment.nodes[0].id == "MAIN/3.else.0"


def test_a_paragraph_with_no_statements_lowers_to_nothing(program_of) -> None:
    asg = program_of([])

    assert lower_statements(asg.paragraphs[0].statements, _ctx(asg), "").nodes == ()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg/test_desugar_assign.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobble.dataflow.srccfg.desugar'`

- [ ] **Step 3: Write the implementation**

`cobble/dataflow/srccfg/desugar.py`:

```python
"""One ASG statement to one Fragment.

What a statement MOVES is not decided here. ``depgraph.flows`` already holds the
verb table -- 30-odd statement kinds, the CICS verbs, the FD-to-record pairing --
and a second copy of it would drift from the first. This module asks flows what
the blocks are and turns them into nodes.

One gap has to be filled locally: flows has no INITIALIZE rule, because a
source-to-target edge needs a source. A definition with no source still kills the
definition before it, so reaching definitions needs the node even though the
dependency graph does not.

Identity is a path, because no ASG statement carries a line number. ``MAIN/3`` is
the fourth statement of MAIN; ``MAIN/3.else.1`` the second statement of its ELSE
arm. Suffixes distinguish the several nodes one statement can lower to:
``#test.0``, ``#join``, ``#end``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from cobble.dataflow.depgraph.flows import ProgramContext, blocks_of, verb_of
from cobble.dataflow.srccfg.cfg import (
    EMPTY_FRAGMENT,
    Edge,
    EdgeKind,
    Exit,
    Fragment,
    Node,
    NodeKind,
    seq,
)
from cobble.dataflow.srccfg.conditions import EightyEight

WRITES_ONLY_KINDS = ("InitializeStatement",)


@dataclass(frozen=True)
class Ctx:
    """What lowering needs about the program and the paragraph being lowered."""

    program: str
    paragraph: str
    flows: ProgramContext
    index: Mapping[str, EightyEight]


def node_id(ctx: Ctx, path: str, suffix: str = "") -> str:
    return f"{ctx.paragraph}/{path}{suffix}"


def lower_statements(
    statements: Sequence, ctx: Ctx, path: str
) -> Fragment:
    prefix = f"{path}." if path else ""
    return seq(
        tuple(
            lower_statement(statement, ctx, f"{prefix}{position}")
            for position, statement in enumerate(statements)
        ),
        nop_id=node_id(ctx, f"{prefix}empty"),
    )


def lower_statement(statement, ctx: Ctx, path: str) -> Fragment:
    """The straight-line case. Control-flow kinds are added in later slices."""
    return _plain(statement, ctx, path)


def _plain(statement, ctx: Ctx, path: str) -> Fragment:
    kind = type(statement).__name__
    writes, reads = _writes_reads(statement, ctx, kind)
    return _one(
        Node(
            id=node_id(ctx, path),
            kind=NodeKind.ASSIGN if writes or reads else NodeKind.NOP,
            paragraph=ctx.paragraph,
            writes=writes,
            reads=reads,
            transfer=verb_of(statement) or _fallback_verb(kind),
        )
    )


def _writes_reads(statement, ctx: Ctx, kind: str) -> tuple[tuple[str, ...], ...]:
    if kind in WRITES_ONLY_KINDS:
        return (_names(getattr(statement, "targets", ())), ())
    blocks = blocks_of(statement, ctx.flows)
    return (
        _dedupe(target for _, targets in blocks for target in targets),
        _dedupe(source for sources, _ in blocks for source in sources),
    )


def _names(operands) -> tuple[str, ...]:
    return _dedupe(
        str(getattr(operand, "name", operand or "")).upper() for operand in operands
    )


def _dedupe(names) -> tuple[str, ...]:
    return tuple(dict.fromkeys(name for name in names if name))


def _fallback_verb(kind: str) -> str:
    """A kind flows has no label for still shows something a reader recognises:
    ``DisplayStatement`` reads as DISPLAY."""
    return kind.removesuffix("Statement").upper()


def _one(node: Node) -> Fragment:
    return Fragment(
        nodes=(node,),
        edges=(),
        entry=node.id,
        exits=(Exit(node_id=node.id, kind=EdgeKind.FLOW),),
    )
```

`Edge` and `EMPTY_FRAGMENT` are imported for the later slices; if `make lint`
flags them as unused now, leave them out and add them back in Task 5.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg/test_desugar_assign.py -v`
Expected: PASS, 11 tests. If `test_a_statement_that_moves_nothing_still_gets_a_node`
fails because DISPLAY yields reads, check `flows._RULES` for a `DisplayStatement`
entry — if one exists, change the test to a kind that has no rule and note which.

- [ ] **Step 5: Commit**

```bash
git add cobble/dataflow/srccfg/desugar.py tests/dataflow/srccfg/test_desugar_assign.py
git commit -m "$(cat <<'EOF'
feat(cobble): lower straight-line statements to ASSIGN nodes

flows.blocks_of stays the single verb table; this turns its blocks into nodes and
adds the one rule it has no reason to carry -- INITIALIZE writes with no source,
which reaching definitions needs in order to see the kill.

Node identity is the paragraph plus a statement path, because no ASG statement
carries a line number.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---
### Task 5: IF and short-circuit lowering — the core of the design

This is the task the whole spec turns on. `A AND B` becomes two `TEST` nodes chained
on their TRUE edges; `A OR B` chains on their FALSE edges; `NOT` swaps a fragment's
true and false exits. Because the graph is built that way, the ELSE arm of
`IF A AND B` is reached by two distinct paths — `NOT A`, and `A AND NOT B` — which
together are exactly `NOT A OR NOT B`. No normal form, no solver, and no way to make
the mistake a guard-stack walk makes when it negates that arm as `NOT A AND NOT B`.

**Files:**
- Modify: `cobble/dataflow/srccfg/desugar.py`
- Test: `tests/dataflow/srccfg/test_desugar_if.py`

**Interfaces:**
- Consumes: everything from Task 4 plus `conditions.{Cond, And, Or, Not, read_condition, resolve_atom}`.
- Produces:
  - `CondFragment(nodes, edges, entry: str, true_exits: tuple[Exit, ...], false_exits: tuple[Exit, ...])` frozen
  - `lower_condition(cond: Cond, ctx: Ctx, path: str, slot: str) -> CondFragment`
  - `as_fragment(cond_fragment: CondFragment) -> Fragment` — exits are true then false
  - `lower_statement` now dispatches `IfStatement` to `_if`
- The `IfStatement` attributes used: `.condition` (the raw dict), `.children`
  (THEN statements), `.else_children` (ELSE statements) — the traversal attrs
  `depgraph.graph.statement_stream` already relies on.

- [ ] **Step 1: Write the failing tests**

`tests/dataflow/srccfg/test_desugar_if.py`:

```python
"""Short-circuit lowering, which is the whole design.

Two TEST nodes chained on their TRUE edges are AND; chained on their FALSE edges
they are OR; NOT is a swap of a fragment's exits. Everything the spec claims about
reaching conditions -- no normal form, no solver, and a correct ELSE arm -- follows
from these tests passing.
"""

from __future__ import annotations

from cobble.dataflow.depgraph.flows import program_context

from cobble.dataflow.srccfg.cfg import Cfg, EdgeKind, NodeKind
from cobble.dataflow.srccfg.conditions import condition_index, read_condition
from cobble.dataflow.srccfg.desugar import Ctx, lower_condition, lower_statements


def _ctx(asg) -> Ctx:
    return Ctx(
        program=asg.program_id,
        paragraph="MAIN",
        flows=program_context(asg),
        index=condition_index(asg),
    )


def _rel(left: str, right: str) -> dict:
    return {
        "not": False,
        "relation": {
            "left": {"kind": "ref", "name": left},
            "op": "==",
            "right": {"kind": "lit", "value": right},
        },
    }


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


def _cfg(program_of, statements: list[dict]) -> Cfg:
    asg = program_of(statements)
    fragment = lower_statements(asg.paragraphs[0].statements, _ctx(asg), "")
    return Cfg(program="PROGA", nodes=fragment.nodes, edges=fragment.edges)


def _atom_texts(cfg: Cfg) -> list[str]:
    return [n.atom.text for n in cfg.nodes if n.kind == NodeKind.TEST]


def test_one_atom_lowers_to_one_test_with_a_true_and_a_false_exit(program_of) -> None:
    asg = program_of([])
    frag = lower_condition(read_condition(_rel("WS-FLAG-A", "'Y'")), _ctx(asg), "0", "")

    assert frag.nodes[0].kind == NodeKind.TEST
    assert frag.nodes[0].atom.left == "WS-FLAG-A"
    assert [e.kind for e in frag.true_exits] == [EdgeKind.TRUE]
    assert [e.kind for e in frag.false_exits] == [EdgeKind.FALSE]
    assert frag.true_exits[0].node_id == frag.false_exits[0].node_id


def test_an_88_in_a_guard_is_resolved_to_its_parent_field(program_of) -> None:
    """The resolution from Task 3 has to happen during lowering, not in a later
    pass: the TEST node is what every query reads, so the parent field has to be
    on the node."""
    asg = program_of(
        [],
        data_fields=[
            {
                "name": "WS-STATUS",
                "level": 1,
                "pic": "X(1)",
                "conditions": [{"name": "STATUS-ACTIVE", "values": [{"from": "'A'"}]}],
            }
        ],
    )

    frag = lower_condition(read_condition("STATUS-ACTIVE"), _ctx(asg), "0", "")

    assert frag.nodes[0].atom.left == "WS-STATUS"


def test_and_chains_the_two_tests_on_the_true_edge(program_of) -> None:
    """The definition of short-circuit AND: B is only evaluated when A held, so the
    only way into B is A's TRUE edge."""
    asg = program_of([])
    cond = read_condition(
        {"op": "AND", "left": _rel("WS-FLAG-A", "'Y'"), "right": _rel("WS-TYPE-B", "'G'")}
    )

    frag = lower_condition(cond, _ctx(asg), "0", "")

    first, second = frag.nodes
    assert frag.entry == first.id
    assert [(e.source, e.target, e.kind) for e in frag.edges] == [
        (first.id, second.id, EdgeKind.TRUE)
    ]
    assert [e.node_id for e in frag.true_exits] == [second.id]
    assert [e.node_id for e in frag.false_exits] == [first.id, second.id]


def test_or_chains_the_two_tests_on_the_false_edge(program_of) -> None:
    asg = program_of([])
    cond = read_condition(
        {"op": "OR", "left": _rel("WS-FLAG-A", "'Y'"), "right": _rel("WS-TYPE-B", "'G'")}
    )

    frag = lower_condition(cond, _ctx(asg), "0", "")

    first, second = frag.nodes
    assert [(e.source, e.target, e.kind) for e in frag.edges] == [
        (first.id, second.id, EdgeKind.FALSE)
    ]
    assert [e.node_id for e in frag.true_exits] == [first.id, second.id]
    assert [e.node_id for e in frag.false_exits] == [second.id]


def test_not_swaps_the_true_and_false_exits_and_emits_no_extra_node(
    program_of,
) -> None:
    """This is why NOT is not a term. Swapping the edges of the fragment means the
    negation of a chain comes out right for free, and there is nothing to
    normalise."""
    asg = program_of([])
    plain = lower_condition(read_condition(_rel("WS-FLAG-A", "'Y'")), _ctx(asg), "0", "")
    negated = lower_condition(
        read_condition({"not": True, "condition": _rel("WS-FLAG-A", "'Y'")}),
        _ctx(asg),
        "0",
        "",
    )

    assert len(negated.nodes) == len(plain.nodes) == 1
    assert negated.true_exits == plain.false_exits
    assert negated.false_exits == plain.true_exits


def test_not_of_an_and_reaches_its_true_side_by_two_paths(program_of) -> None:
    """NOT (A AND B) is NOT A OR NOT B. Nothing computes that here: swapping the
    exits of the AND chain leaves the FALSE edges of both tests as the true side,
    which IS the disjunction, expressed as two paths."""
    asg = program_of([])
    cond = read_condition(
        {
            "not": True,
            "condition": {
                "op": "AND",
                "left": _rel("WS-FLAG-A", "'Y'"),
                "right": _rel("WS-TYPE-B", "'G'"),
            },
        }
    )

    frag = lower_condition(cond, _ctx(asg), "0", "")

    assert len(frag.true_exits) == 2
    assert [e.kind for e in frag.true_exits] == [EdgeKind.FALSE, EdgeKind.FALSE]


def test_each_test_node_gets_its_own_id_within_the_statement(program_of) -> None:
    """Two atoms of one IF are two nodes of one statement, so the ids are the
    statement path plus a slot, and the slot says where in the condition tree the
    atom was."""
    asg = program_of([])
    cond = read_condition(
        {"op": "AND", "left": _rel("WS-FLAG-A", "'Y'"), "right": _rel("WS-TYPE-B", "'G'")}
    )

    frag = lower_condition(cond, _ctx(asg), "0", "")

    assert [node.id for node in frag.nodes] == ["MAIN/0#test.L", "MAIN/0#test.R"]


def test_an_if_wires_the_then_arm_to_the_true_edge(program_of) -> None:
    cfg = _cfg(
        program_of,
        [
            {
                "type": "IF",
                "condition": _rel("WS-FLAG-A", "'Y'"),
                "children": [_move("'F'", "WS-RESULT")],
            }
        ],
    )

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert [(e.target, e.kind) for e in cfg.successors(test_node.id)] == [
        ("MAIN/0.then.0", EdgeKind.TRUE)
    ]


def test_an_if_with_no_else_leaves_the_false_edge_for_what_follows(program_of) -> None:
    """The statement after END-IF is reached both by falling out of the THEN arm
    and by the guard failing, so both have to be exits of the IF fragment."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "IF",
                "condition": _rel("WS-FLAG-A", "'Y'"),
                "children": [_move("'F'", "WS-RESULT")],
            },
            _move("WS-RESULT", "WS-COPY"),
        ],
    )

    into_last = {e.source for e in cfg.predecessors("MAIN/1")}
    assert into_last == {"MAIN/0.then.0", "MAIN/0#test"}


def test_both_arms_of_an_if_else_continue_into_the_next_statement(program_of) -> None:
    cfg = _cfg(
        program_of,
        [
            {
                "type": "IF",
                "condition": _rel("WS-FLAG-A", "'Y'"),
                "children": [_move("'F'", "WS-RESULT")],
                "else_children": [_move("'G'", "WS-RESULT")],
            },
            _move("WS-RESULT", "WS-COPY"),
        ],
    )

    assert {e.source for e in cfg.predecessors("MAIN/1")} == {
        "MAIN/0.then.0",
        "MAIN/0.else.0",
    }


def test_the_else_arm_of_a_two_clause_and_is_reached_by_two_paths(program_of) -> None:
    """The measured failure of the ancestor-walk probe, now a test.

        IF A AND B ... ELSE ... END-IF

    The ELSE arm is NOT A OR NOT B, so it has two predecessors: the FALSE edge of
    A, and the FALSE edge of B. A guard stack that negates the arm as a
    conjunction reports one path and it is the wrong one.
    """
    cfg = _cfg(
        program_of,
        [
            {
                "type": "IF",
                "condition": {
                    "op": "AND",
                    "left": _rel("WS-FLAG-A", "'Y'"),
                    "right": _rel("WS-TYPE-B", "'G'"),
                },
                "children": [_move("'F'", "WS-RESULT")],
                "else_children": [_move("WS-TYPE-B", "WS-RESULT")],
            }
        ],
    )

    into_else = {
        (e.source, e.kind) for e in cfg.predecessors("MAIN/0.else.0")
    }
    assert into_else == {
        ("MAIN/0#test.L", EdgeKind.FALSE),
        ("MAIN/0#test.R", EdgeKind.FALSE),
    }


def test_a_nested_if_keeps_every_atom_as_its_own_test(program_of) -> None:
    """The shape a dictionary rule is usually written in: an outer emptiness guard
    around an inner two-clause test. Four atoms, four TEST nodes, and the inner
    arm's assignment is under all of them."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "IF",
                "condition": {
                    "op": "OR",
                    "left": _rel("WS-RESULT", "SPACES"),
                    "right": _rel("WS-RESULT", "LOW-VALUES"),
                },
                "children": [
                    {
                        "type": "IF",
                        "condition": {
                            "op": "AND",
                            "left": _rel("WS-FLAG-A", "'Y'"),
                            "right": _rel("WS-TYPE-B", "'G'"),
                        },
                        "children": [_move("'F'", "WS-RESULT")],
                        "else_children": [_move("WS-TYPE-B", "WS-RESULT")],
                    }
                ],
            }
        ],
    )

    assert len([n for n in cfg.nodes if n.kind == NodeKind.TEST]) == 4
    assert _atom_texts(cfg)[:2] == ["WS-RESULT == SPACES", "WS-RESULT == LOW-VALUES"]
    assert cfg.node("MAIN/0.then.0.then.0").writes == ("WS-RESULT",)


def test_a_condition_with_no_readable_shape_still_gets_a_test(program_of) -> None:
    """An UNRESOLVED guard is a fork that exists, so the two arms stay distinct
    paths. Collapsing it would silently claim the arm is unconditional."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "IF",
                "condition": {"something": "new"},
                "children": [_move("'F'", "WS-RESULT")],
            }
        ],
    )

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert test_node.atom.resolved is False
    assert len(cfg.successors(test_node.id)) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg/test_desugar_if.py -v`
Expected: FAIL — `ImportError: cannot import name 'lower_condition'`

- [ ] **Step 3: Write the implementation**

Add to `cobble/dataflow/srccfg/desugar.py`:

```python
@dataclass(frozen=True)
class CondFragment:
    """A lowered condition: the tests, and the two sets of exits it leaves.

    A chain of ANDed atoms leaves one true exit and one false exit per atom; a
    chain of ORed atoms leaves the mirror image. NOT is applied by swapping the
    two sets, which is why no node is emitted for it and why the negation of a
    chain comes out as a set of paths rather than a formula.
    """

    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    entry: str
    true_exits: tuple[Exit, ...]
    false_exits: tuple[Exit, ...]


def lower_condition(cond, ctx: Ctx, path: str, slot: str = "") -> CondFragment:
    if isinstance(cond, Not):
        return _swap(lower_condition(cond.inner, ctx, path, slot))
    if isinstance(cond, And):
        return _chain(cond, ctx, path, slot, EdgeKind.TRUE)
    if isinstance(cond, Or):
        return _chain(cond, ctx, path, slot, EdgeKind.FALSE)
    return _test(cond, ctx, path, slot)


def _test(atom, ctx: Ctx, path: str, slot: str) -> CondFragment:
    suffix = f"#test.{slot}" if slot else "#test"
    node = Node(
        id=node_id(ctx, path, suffix),
        kind=NodeKind.TEST,
        paragraph=ctx.paragraph,
        atom=resolve_atom(atom, ctx.index),
    )
    return CondFragment(
        nodes=(node,),
        edges=(),
        entry=node.id,
        true_exits=(Exit(node_id=node.id, kind=EdgeKind.TRUE),),
        false_exits=(Exit(node_id=node.id, kind=EdgeKind.FALSE),),
    )


def _swap(inner: CondFragment) -> CondFragment:
    return CondFragment(
        nodes=inner.nodes,
        edges=inner.edges,
        entry=inner.entry,
        true_exits=inner.false_exits,
        false_exits=inner.true_exits,
    )


def _chain(cond, ctx: Ctx, path: str, slot: str, through: EdgeKind) -> CondFragment:
    """Short-circuit: the right side is only reached along ``through`` from the
    left, and the other side's exits from BOTH halves escape the chain."""
    left = lower_condition(cond.left, ctx, path, f"{slot}L")
    right = lower_condition(cond.right, ctx, path, f"{slot}R")
    taken = left.true_exits if through is EdgeKind.TRUE else left.false_exits
    kept = left.false_exits if through is EdgeKind.TRUE else left.true_exits
    joined = CondFragment(
        nodes=(*left.nodes, *right.nodes),
        edges=(
            *left.edges,
            *right.edges,
            *(
                Edge(source=exit_.node_id, target=right.entry, kind=exit_.kind)
                for exit_ in taken
            ),
        ),
        entry=left.entry,
        true_exits=right.true_exits,
        false_exits=(*kept, *right.false_exits),
    )
    return joined if through is EdgeKind.TRUE else _or_exits(joined, kept, right)


def _or_exits(
    joined: CondFragment, kept: tuple[Exit, ...], right: CondFragment
) -> CondFragment:
    return CondFragment(
        nodes=joined.nodes,
        edges=joined.edges,
        entry=joined.entry,
        true_exits=(*kept, *right.true_exits),
        false_exits=right.false_exits,
    )


def as_fragment(cond: CondFragment) -> Fragment:
    return Fragment(
        nodes=cond.nodes,
        edges=cond.edges,
        entry=cond.entry,
        exits=(*cond.true_exits, *cond.false_exits),
    )


def _if(statement, ctx: Ctx, path: str) -> Fragment:
    cond = lower_condition(read_condition(_raw_condition(statement)), ctx, path)
    then_arm = lower_statements(getattr(statement, "children", ()), ctx, f"{path}.then")
    else_arm = lower_statements(
        getattr(statement, "else_children", ()), ctx, f"{path}.else"
    )
    return _wire_arms(cond, then_arm, else_arm)


def _wire_arms(cond: CondFragment, then_arm: Fragment, else_arm: Fragment) -> Fragment:
    """An empty arm leaves the guard's own exit dangling, which is right: the
    statement after END-IF is what that edge goes to."""
    into_then = _attach(cond.true_exits, then_arm)
    into_else = _attach(cond.false_exits, else_arm)
    return Fragment(
        nodes=(*cond.nodes, *then_arm.nodes, *else_arm.nodes),
        edges=(*cond.edges, *then_arm.edges, *else_arm.edges, *into_then, *into_else),
        entry=cond.entry,
        exits=(
            *(then_arm.exits if then_arm.nodes else cond.true_exits),
            *(else_arm.exits if else_arm.nodes else cond.false_exits),
        ),
    )


def _attach(exits: tuple[Exit, ...], arm: Fragment) -> tuple[Edge, ...]:
    if not arm.nodes:
        return ()
    return tuple(
        Edge(source=exit_.node_id, target=arm.entry, kind=exit_.kind) for exit_ in exits
    )


def _raw_condition(statement) -> object:
    """The ASG hands conditions back as the same dicts it was built from, and the
    statement dataclasses keep them under ``condition``."""
    raw = getattr(statement, "condition", None)
    return raw if raw else {}
```

Extend `lower_statement` to dispatch by class name:

```python
def lower_statement(statement, ctx: Ctx, path: str) -> Fragment:
    handler = _HANDLERS.get(type(statement).__name__)
    return handler(statement, ctx, path) if handler else _plain(statement, ctx, path)


_HANDLERS = {"IfStatement": _if}
```

`_HANDLERS` must be defined after the handlers it names; put it at the bottom of the
module and keep adding to it in later tasks.

Add the imports: `Not`, `And`, `Or`, `read_condition`, `resolve_atom` from
`.conditions`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg -v`
Expected: PASS. If `test_the_else_arm_of_a_two_clause_and_is_reached_by_two_paths`
fails with one predecessor, `_chain` dropped `kept` — that single line is the whole
correctness claim of the design, so fix it there rather than in the test.

If the ASG exposes the condition under a different attribute than `condition` for
`IfStatement`, `_raw_condition` returns `{}` and every guard reads UNRESOLVED. Check
with:

```bash
cd cobble && uv run --no-sync python -c "
from cobol_asg.cobol_statements import IfStatement
print([f.name for f in IfStatement.__dataclass_fields__.values()])"
```

- [ ] **Step 5: Check the style gates**

```bash
cd cobble
uv run --no-sync python -m python_fp_lint check cobble/dataflow/srccfg/
```
Expected: 0. `isinstance` on the condition classes is a type test, not a statement-kind
test, so it does not break the match-by-class-name rule — that rule is about ASG
statements, whose classes this package does not own.

- [ ] **Step 6: Commit**

```bash
git add cobble/dataflow/srccfg/desugar.py tests/dataflow/srccfg/test_desugar_if.py
git commit -m "$(cat <<'EOF'
feat(cobble): lower IF and short-circuit AND/OR into TEST chains

AND chains two tests on the TRUE edge, OR on the FALSE edge, and NOT swaps a
fragment's exits without emitting a node. That makes the ELSE arm of a two-clause
AND reachable by two paths, which is the disjunction the guard-stack probe got
wrong -- and it means a reaching condition is a path, with no normal form and no
solver.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---
### Task 6: EVALUATE and WHEN

An `EVALUATE` is a chain of guards: each `WHEN` is tried only when every earlier one
failed, which is the same FALSE-edge chaining `OR` uses. `WHEN OTHER` is the last
FALSE arm. `WHEN a ALSO b` is a conjunction, so it chains on TRUE within the branch.

The ASG shapes, from `cobol_statements.py`:
- `EvaluateStatement(subject: str, also_subjects: tuple[str, ...], children: list)`
  — the branches are in `children`.
- `WhenStatement(condition: dict | str, also_conditions: tuple, children: list, condition_thru: str | None)`
  — `condition` is a structured dict for `EVALUATE TRUE`, and a **plain string already
  prefixed with `<subject> = `** for `EVALUATE <subject> WHEN <value>`; `WHEN ANY` is
  the string `"ANY"`.
- `WhenOtherStatement(children: list)`.

`condition_thru` is not `None` for `WHEN a THRU b`, and it is the one place in this
package where an ASG field is genuinely nullable — compare with `is not None` is
banned, so compare against `""` after `str(... or "")`.

**Files:**
- Modify: `cobble/dataflow/srccfg/desugar.py`
- Modify: `cobble/dataflow/srccfg/conditions.py`
- Test: `tests/dataflow/srccfg/test_desugar_evaluate.py`

**Interfaces:**
- Produces:
  - `conditions.read_when_condition(raw: object, thru: str) -> Cond` — the string form
    `"WS-X = 'A'"` becomes a relational atom; with `thru` non-empty it becomes a
    `RANGE` atom; `"ANY"` becomes an always-true atom
  - `conditions.ALWAYS: Atom` — the atom of a branch with no test (`WHEN ANY`)
  - `desugar._evaluate` registered in `_HANDLERS` for `EvaluateStatement`

- [ ] **Step 1: Write the failing tests**

`tests/dataflow/srccfg/test_desugar_evaluate.py`:

```python
"""EVALUATE is a guard chain: a WHEN is reached only when every earlier WHEN
failed. That is the same FALSE-edge chaining OR uses, so the reaching condition of
a branch's body already carries the negation of the branches above it -- which is
the part a per-branch guard stack loses.
"""

from __future__ import annotations

from cobble.dataflow.depgraph.flows import program_context

from cobble.dataflow.srccfg.cfg import Cfg, EdgeKind, NodeKind
from cobble.dataflow.srccfg.conditions import condition_index
from cobble.dataflow.srccfg.desugar import Ctx, lower_statements


def _ctx(asg) -> Ctx:
    return Ctx(
        program=asg.program_id,
        paragraph="MAIN",
        flows=program_context(asg),
        index=condition_index(asg),
    )


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


def _cfg(program_of, statements: list[dict]) -> Cfg:
    asg = program_of(statements)
    fragment = lower_statements(asg.paragraphs[0].statements, _ctx(asg), "")
    return Cfg(program="PROGA", nodes=fragment.nodes, edges=fragment.edges)


def _evaluate(*branches: dict, subject: str = "WS-TYPE-B") -> dict:
    return {"type": "EVALUATE", "subject": subject, "children": list(branches)}


def test_a_when_value_becomes_an_equality_on_the_subject(program_of) -> None:
    """The ASG hands EVALUATE <subject> WHEN <value> over already prefixed as the
    string "<subject> = <value>", so the parts have to be recovered from text --
    without that, the subject is not a dependency of anything in the branch."""
    cfg = _cfg(
        program_of,
        [_evaluate({"type": "WHEN", "condition": "WS-TYPE-B = 'G'", "children": [
            _move("'F'", "WS-RESULT")
        ]})],
    )

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert (test_node.atom.left, test_node.atom.op, test_node.atom.right) == (
        "WS-TYPE-B",
        "==",
        "'G'",
    )


def test_a_second_when_is_reached_only_by_the_first_ones_false_edge(program_of) -> None:
    cfg = _cfg(
        program_of,
        [
            _evaluate(
                {"type": "WHEN", "condition": "WS-TYPE-B = 'G'", "children": [
                    _move("'F'", "WS-RESULT")
                ]},
                {"type": "WHEN", "condition": "WS-TYPE-B = 'H'", "children": [
                    _move("'J'", "WS-RESULT")
                ]},
            )
        ],
    )

    first, second = (n.id for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert [(e.target, e.kind) for e in cfg.successors(first) if e.kind is EdgeKind.FALSE] == [
        (second, EdgeKind.FALSE)
    ]


def test_when_other_is_the_last_false_arm(program_of) -> None:
    """WHEN OTHER carries the negation of every branch above it, and that is the
    only place it is recorded -- the branch itself has no condition of its own."""
    cfg = _cfg(
        program_of,
        [
            _evaluate(
                {"type": "WHEN", "condition": "WS-TYPE-B = 'G'", "children": [
                    _move("'F'", "WS-RESULT")
                ]},
                {"type": "WHEN_OTHER", "children": [_move("'Z'", "WS-RESULT")]},
            )
        ],
    )

    other = cfg.node("MAIN/0.when.1.0")
    assert other.writes == ("WS-RESULT",)
    assert [e.kind for e in cfg.predecessors(other.id)] == [EdgeKind.FALSE]


def test_every_branch_body_continues_into_the_statement_after_the_evaluate(
    program_of,
) -> None:
    """COBOL EVALUATE does not fall through: each branch ends the statement. So
    every body's exit, and the last WHEN's FALSE edge when there is no WHEN OTHER,
    lead to whatever follows END-EVALUATE."""
    cfg = _cfg(
        program_of,
        [
            _evaluate(
                {"type": "WHEN", "condition": "WS-TYPE-B = 'G'", "children": [
                    _move("'F'", "WS-RESULT")
                ]},
                {"type": "WHEN", "condition": "WS-TYPE-B = 'H'", "children": [
                    _move("'J'", "WS-RESULT")
                ]},
            ),
            _move("WS-RESULT", "WS-COPY"),
        ],
    )

    assert {e.source for e in cfg.predecessors("MAIN/1")} == {
        "MAIN/0.when.0.0",
        "MAIN/0.when.1.0",
        "MAIN/0.when.1#test",
    }


def test_a_structured_condition_under_evaluate_true_lowers_like_an_if(
    program_of,
) -> None:
    """EVALUATE TRUE WHEN A AND B is a full conditional expression, and the ASG
    gives it as the same dict an IF carries -- so it must lower to a TEST chain,
    not to one opaque atom."""
    cfg = _cfg(
        program_of,
        [
            _evaluate(
                {
                    "type": "WHEN",
                    "condition": {
                        "op": "AND",
                        "left": {
                            "not": False,
                            "relation": {
                                "left": {"kind": "ref", "name": "WS-FLAG-A"},
                                "op": "==",
                                "right": {"kind": "lit", "value": "'Y'"},
                            },
                        },
                        "right": {
                            "not": False,
                            "relation": {
                                "left": {"kind": "ref", "name": "WS-TYPE-B"},
                                "op": "==",
                                "right": {"kind": "lit", "value": "'G'"},
                            },
                        },
                    },
                    "children": [_move("'F'", "WS-RESULT")],
                },
                subject="TRUE",
            )
        ],
    )

    assert len([n for n in cfg.nodes if n.kind == NodeKind.TEST]) == 2


def test_a_when_thru_becomes_one_range_atom(program_of) -> None:
    cfg = _cfg(
        program_of,
        [
            _evaluate(
                {
                    "type": "WHEN",
                    "condition": "WS-TYPE-B = 'A'",
                    "condition_thru": "'M'",
                    "children": [_move("'F'", "WS-RESULT")],
                }
            )
        ],
    )

    atom = next(n for n in cfg.nodes if n.kind == NodeKind.TEST).atom
    assert (atom.left, atom.op, atom.right) == ("WS-TYPE-B", "RANGE", "'A' THRU 'M'")


def test_also_conditions_are_a_conjunction_within_the_branch(program_of) -> None:
    """WHEN a ALSO b holds only if both hold, so within the branch the two tests
    chain on the TRUE edge -- and both FALSE edges leave for the next branch."""
    cfg = _cfg(
        program_of,
        [
            _evaluate(
                {
                    "type": "WHEN",
                    "condition": "WS-TYPE-B = 'G'",
                    "also_conditions": ["WS-FLAG-A = 'Y'"],
                    "children": [_move("'F'", "WS-RESULT")],
                },
                {"type": "WHEN_OTHER", "children": [_move("'Z'", "WS-RESULT")]},
            )
        ],
    )

    tests = [n.id for n in cfg.nodes if n.kind == NodeKind.TEST]
    assert len(tests) == 2
    other = "MAIN/0.when.1.0"
    assert {e.source for e in cfg.predecessors(other)} == set(tests)


def test_when_any_is_an_always_true_test_that_still_occupies_a_node(
    program_of,
) -> None:
    """WHEN ANY matches unconditionally. Keeping a node means the branch above it
    still records its own negation on the path here, and a report can say which
    branch fired."""
    cfg = _cfg(
        program_of,
        [_evaluate({"type": "WHEN", "condition": "ANY", "children": [
            _move("'F'", "WS-RESULT")
        ]})],
    )

    atom = next(n for n in cfg.nodes if n.kind == NodeKind.TEST).atom
    assert atom.text == "ANY"
    assert atom.op == ""


def test_an_evaluate_with_no_branches_lowers_to_nothing(program_of) -> None:
    cfg = _cfg(program_of, [_evaluate()])

    assert cfg.nodes == ()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg/test_desugar_evaluate.py -v`
Expected: FAIL — every branch body lowers with no guard above it, because
`EvaluateStatement` currently falls through to `_plain`.

- [ ] **Step 3: Add the WHEN condition reader**

Append to `cobble/dataflow/srccfg/conditions.py`:

```python
ALWAYS = Atom(text="ANY", left="", op="", right="")
_WHEN_ANY = ("ANY", "OTHER", "")


def read_when_condition(raw: object, thru: str = "") -> Cond:
    """A WHEN branch's condition.

    EVALUATE TRUE gives a structured dict, and that path is read_condition's. The
    other form arrives as text the ASG has already prefixed with the subject --
    "WS-X = 'A'" -- and the parts have to be recovered from it, because without
    them the subject is not a dependency of anything in the branch.
    """
    if not isinstance(raw, str):
        return read_condition(raw)
    text = raw.strip()
    if text.upper() in _WHEN_ANY:
        return ALWAYS
    return _from_when_text(text, thru)


def _from_when_text(text: str, thru: str) -> Cond:
    subject, _, value = text.partition(" = ")
    if not value:
        return _named(text)
    if thru:
        return Atom(
            text=f"{subject} = {value} THRU {thru}",
            left=subject,
            op=RANGE,
            right=f"{value} THRU {thru}",
        )
    return Atom(text=f"{subject} == {value}", left=subject, op="==", right=value)
```

`RANGE` is already defined by Task 3; `_named` by Task 2.

- [ ] **Step 4: Add the EVALUATE handler**

Add to `cobble/dataflow/srccfg/desugar.py`:

```python
def _evaluate(statement, ctx: Ctx, path: str) -> Fragment:
    """A guard chain. Each branch is tried only when every earlier one failed, so
    branch N is reached along branch N-1's FALSE edges -- the same chaining OR
    uses, which is why the negation of the branches above is already on the path.
    """
    branches = tuple(
        _branch(child, ctx, f"{path}.when.{position}")
        for position, child in enumerate(getattr(statement, "children", ()))
    )
    return _chain_branches(tuple(b for b in branches if b.nodes))


@dataclass(frozen=True)
class _Branch:
    """One WHEN: its guard chain (possibly none, for WHEN OTHER) and its body."""

    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    entry: str
    body_exits: tuple[Exit, ...]
    false_exits: tuple[Exit, ...]


def _branch(child, ctx: Ctx, path: str) -> _Branch:
    body = lower_statements(getattr(child, "children", ()), ctx, path)
    if type(child).__name__ == "WhenOtherStatement":
        return _Branch(
            nodes=body.nodes,
            edges=body.edges,
            entry=body.entry,
            body_exits=body.exits,
            false_exits=(),
        )
    return _guarded_branch(child, ctx, path, body)


def _guarded_branch(child, ctx: Ctx, path: str, body: Fragment) -> _Branch:
    cond = _when_condition(child, ctx, path)
    into_body = _attach(cond.true_exits, body)
    return _Branch(
        nodes=(*cond.nodes, *body.nodes),
        edges=(*cond.edges, *body.edges, *into_body),
        entry=cond.entry,
        body_exits=body.exits if body.nodes else cond.true_exits,
        false_exits=cond.false_exits,
    )


def _when_condition(child, ctx: Ctx, path: str) -> CondFragment:
    """WHEN a ALSO b is a conjunction, so the ALSO conditions chain on TRUE."""
    thru = str(getattr(child, "condition_thru", "") or "")
    parts = (
        read_when_condition(getattr(child, "condition", ""), thru),
        *(read_when_condition(also) for also in getattr(child, "also_conditions", ())),
    )
    return _and_chain(parts, ctx, path, 0)


def _and_chain(parts, ctx: Ctx, path: str, position: int) -> CondFragment:
    head = lower_condition(parts[position], ctx, path, _ALSO_SLOTS[position])
    if position + 1 >= len(parts):
        return head
    tail = _and_chain(parts, ctx, path, position + 1)
    return CondFragment(
        nodes=(*head.nodes, *tail.nodes),
        edges=(
            *head.edges,
            *tail.edges,
            *(
                Edge(source=e.node_id, target=tail.entry, kind=e.kind)
                for e in head.true_exits
            ),
        ),
        entry=head.entry,
        true_exits=tail.true_exits,
        false_exits=(*head.false_exits, *tail.false_exits),
    )


_ALSO_SLOTS = ("", "A1", "A2", "A3", "A4", "A5", "A6", "A7")


def _chain_branches(branches: tuple[_Branch, ...]) -> Fragment:
    if not branches:
        return EMPTY_FRAGMENT
    return Fragment(
        nodes=tuple(node for b in branches for node in b.nodes),
        edges=(
            *(edge for b in branches for edge in b.edges),
            *_between(branches),
        ),
        entry=branches[0].entry,
        exits=(
            *(e for b in branches for e in b.body_exits),
            *branches[-1].false_exits,
        ),
    )


def _between(branches: tuple[_Branch, ...]) -> tuple[Edge, ...]:
    return tuple(
        Edge(source=exit_.node_id, target=nxt.entry, kind=exit_.kind)
        for current, nxt in zip(branches, branches[1:])
        for exit_ in current.false_exits
    )
```

Register it: `_HANDLERS = {"IfStatement": _if, "EvaluateStatement": _evaluate}`.

Add `read_when_condition` to the `.conditions` imports. An EVALUATE with more than
eight ALSO conditions would exhaust `_ALSO_SLOTS`; the corpus has none, and an
`IndexError` there is the right failure — a silent id collision would corrupt the
graph.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg -v`
Expected: PASS. If the branch body ids do not match `MAIN/0.when.1.0`, print
`[n.id for n in cfg.nodes]` and correct the **test's** expected ids only if the
scheme is still `<paragraph>/<statement path>.when.<branch>.<statement>` — otherwise
`_evaluate` built the path wrong.

- [ ] **Step 6: Commit**

```bash
git add cobble/dataflow/srccfg tests/dataflow/srccfg/test_desugar_evaluate.py
git commit -m "$(cat <<'EOF'
feat(cobble): lower EVALUATE into a chain of guarded branches

Branch N is reached along branch N-1's FALSE edges, so the negation of every
earlier WHEN is already on the path into a branch body, and WHEN OTHER carries all
of them. WHEN ... ALSO chains on TRUE; WHEN ... THRU becomes one range atom; the
subject-prefixed string form is decomposed so the subject stays a dependency.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---
### Task 7: Paragraphs, fall-through, and GO TO

Paragraphs are shared nodes: a paragraph is lowered once, and every `PERFORM` of it
and every `GO TO` into it points at the same nodes. This task builds the per-program
skeleton — one `LABEL` node and one `#end` node per paragraph, `FALLTHRU` edges in
declaration order — and resolves `GO TO`.

`GO TO` is the tail the guard-stack probe could not see: 11% of paragraphs are never
`PERFORM`ed and hold 5% of assignments, and they are reached this way.

ASG shapes:
- `CobolASG.sections: list[CobolSection]` each with `.name`, `.paragraphs`,
  `.statements`; `CobolASG.paragraphs: list[CobolParagraph]` for paragraphs in no
  section; `CobolASG.statements` for bare division-level statements.
- `GotoStatement.form` is one of `SimpleGoto(target: ProcedureRef)`,
  `ComputedGoto(targets: tuple[ProcedureRef, ...], index: RefModOperand)`,
  `AlteredGoto()`. `ProcedureRef` has `.paragraph` and `.section`.

**Files:**
- Modify: `cobble/dataflow/srccfg/desugar.py`
- Create: `cobble/dataflow/srccfg/build.py`
- Test: `tests/dataflow/srccfg/test_desugar_goto.py`
- Test: `tests/dataflow/srccfg/test_build_paragraphs.py`

**Interfaces:**
- Produces in `desugar.py`:
  - `_goto` registered for `GotoStatement`; emits `CALL` nodes with `transfer="GO TO"`
    and `target=<paragraph name>`, and **no exits** — control leaves for a label
  - `GOTO_TRANSFER = "GO TO"`, `DISPATCH_TRANSFER = "GO TO DEPENDING"`
- Produces in `build.py`:
  - `ParagraphRef(name: str, section: str, statements: tuple)` frozen
  - `paragraph_order(asg) -> tuple[ParagraphRef, ...]` — declaration order, the order
    fall-through and `PERFORM THRU` ranges both follow
  - `label_id(name: str) -> str` = `f"{name}#label"`, `end_id(name: str) -> str` = `f"{name}#end"`
  - `IMPLICIT_FIRST = "%MAIN"` — the synthetic paragraph holding division-level
    statements when a program has any
  - `build_program(asg) -> Cfg`
  - `resolve_targets(nodes, edges, known: frozenset[str]) -> tuple[Edge, ...]`

- [ ] **Step 1: Write the failing GO TO tests**

`tests/dataflow/srccfg/test_desugar_goto.py`:

```python
"""GO TO. 11% of paragraphs are never PERFORMed and hold 5% of assignments; this
is how they are reached, and a pass that cannot see it reports those assignments as
unreachable or as unguarded."""

from __future__ import annotations

from cobble.dataflow.depgraph.flows import program_context

from cobble.dataflow.srccfg.cfg import NodeKind
from cobble.dataflow.srccfg.conditions import condition_index
from cobble.dataflow.srccfg.desugar import (
    DISPATCH_TRANSFER,
    GOTO_TRANSFER,
    Ctx,
    lower_statements,
)


def _ctx(asg) -> Ctx:
    return Ctx(
        program=asg.program_id,
        paragraph="MAIN",
        flows=program_context(asg),
        index=condition_index(asg),
    )


def _lower(program_of, statements: list[dict]):
    asg = program_of(statements)
    return lower_statements(asg.paragraphs[0].statements, _ctx(asg), "")


def test_a_simple_goto_names_its_target_and_leaves_no_exit(program_of) -> None:
    """No exit is the point: the statement after a GO TO is not reachable from it,
    and wiring one would make every assignment below look guarded by nothing."""
    fragment = _lower(
        program_of,
        [{"type": "GOTO", "form": "simple", "target": {"paragraph": "9999-EXIT"}}],
    )

    node = fragment.nodes[0]
    assert (node.kind, node.transfer, node.target) == (
        NodeKind.CALL,
        GOTO_TRANSFER,
        "9999-EXIT",
    )
    assert fragment.exits == ()


def test_a_statement_after_a_goto_is_left_unreachable(program_of) -> None:
    fragment = _lower(
        program_of,
        [
            {"type": "GOTO", "form": "simple", "target": {"paragraph": "9999-EXIT"}},
            {"type": "MOVE", "operands": [{"name": "'F'"}, {"name": "WS-RESULT"}]},
        ],
    )

    assert fragment.edges == ()
    assert [node.id for node in fragment.nodes] == ["MAIN/0", "MAIN/1"]


def test_a_computed_goto_emits_one_node_per_target(program_of) -> None:
    """GO TO p1 p2 DEPENDING ON i selects by index. Which target is taken depends
    on the index field, so the index is a read and every target is a possibility --
    an over-approximation the spec takes deliberately."""
    fragment = _lower(
        program_of,
        [
            {
                "type": "GOTO",
                "form": "computed",
                "targets": [{"paragraph": "1000-A"}, {"paragraph": "2000-B"}],
                "index": {"name": "WS-IDX"},
            }
        ],
    )

    dispatch = fragment.nodes[0]
    assert (dispatch.transfer, dispatch.reads) == (DISPATCH_TRANSFER, ("WS-IDX",))
    assert [n.target for n in fragment.nodes[1:]] == ["1000-A", "2000-B"]
    assert [n.id for n in fragment.nodes[1:]] == ["MAIN/0#goto.0", "MAIN/0#goto.1"]


def test_a_computed_goto_falls_through_when_the_index_is_out_of_range(
    program_of,
) -> None:
    """An index outside 1..N is not an error in COBOL: control continues with the
    next statement. So the dispatch node keeps a FLOW exit even though each branch
    has none."""
    fragment = _lower(
        program_of,
        [
            {
                "type": "GOTO",
                "form": "computed",
                "targets": [{"paragraph": "1000-A"}],
                "index": {"name": "WS-IDX"},
            }
        ],
    )

    assert [e.node_id for e in fragment.exits] == ["MAIN/0"]


def test_an_altered_goto_is_an_unresolved_transfer_not_a_silence(program_of) -> None:
    """GO TO with no operand is retargeted by ALTER at runtime. The transfer is
    real and its destination is unknown, which is a fact a report has to be able to
    state -- so the node exists with an empty target."""
    fragment = _lower(program_of, [{"type": "GOTO", "form": "altered"}])

    node = fragment.nodes[0]
    assert (node.kind, node.transfer, node.target) == (NodeKind.CALL, GOTO_TRANSFER, "")
    assert fragment.exits == ()


def test_a_goto_inside_an_if_arm_still_ends_that_arm(program_of) -> None:
    """The commonest shape in the corpus: a guarded early exit. The THEN arm must
    contribute no exit, so the statement after END-IF is reached only by the guard
    failing."""
    fragment = _lower(
        program_of,
        [
            {
                "type": "IF",
                "condition": {
                    "not": False,
                    "relation": {
                        "left": {"kind": "ref", "name": "WS-FLAG-A"},
                        "op": "==",
                        "right": {"kind": "lit", "value": "'Y'"},
                    },
                },
                "children": [
                    {"type": "GOTO", "form": "simple", "target": {"paragraph": "9999-EXIT"}}
                ],
            },
            {"type": "MOVE", "operands": [{"name": "'F'"}, {"name": "WS-RESULT"}]},
        ],
    )

    into_last = {(e.source, e.kind.value) for e in fragment.edges if e.target == "MAIN/1"}
    assert into_last == {("MAIN/0#test", "FALSE")}
```

- [ ] **Step 2: Add the GO TO handler**

Add to `cobble/dataflow/srccfg/desugar.py`:

```python
GOTO_TRANSFER = "GO TO"
DISPATCH_TRANSFER = "GO TO DEPENDING"


def _goto(statement, ctx: Ctx, path: str) -> Fragment:
    form = getattr(statement, "form", None)
    targets = getattr(form, "targets", ())
    if targets:
        return _computed_goto(form, targets, ctx, path)
    return _transfer(ctx, path, "", _target_name(getattr(form, "target", None)))


def _transfer(ctx: Ctx, path: str, suffix: str, target: str) -> Fragment:
    """A node control leaves from: no exits, and a target build.py resolves."""
    node = Node(
        id=node_id(ctx, path, suffix),
        kind=NodeKind.CALL,
        paragraph=ctx.paragraph,
        transfer=GOTO_TRANSFER,
        target=target,
    )
    return Fragment(nodes=(node,), edges=(), entry=node.id, exits=())


def _computed_goto(form, targets, ctx: Ctx, path: str) -> Fragment:
    """One dispatch node reading the index, one branch node per target.

    The dispatch keeps a FLOW exit: an index outside 1..N is not an error in COBOL,
    control simply continues with the next statement.
    """
    dispatch = Node(
        id=node_id(ctx, path),
        kind=NodeKind.CALL,
        paragraph=ctx.paragraph,
        reads=_names((getattr(form, "index", ""),)),
        transfer=DISPATCH_TRANSFER,
    )
    branches = tuple(
        _transfer(ctx, path, f"#goto.{position}", _target_name(ref)).nodes[0]
        for position, ref in enumerate(targets)
    )
    return Fragment(
        nodes=(dispatch, *branches),
        edges=tuple(
            Edge(source=dispatch.id, target=branch.id, kind=EdgeKind.FLOW)
            for branch in branches
        ),
        entry=dispatch.id,
        exits=(Exit(node_id=dispatch.id, kind=EdgeKind.FLOW),),
    )


def _target_name(ref) -> str:
    return str(getattr(ref, "paragraph", "") or "").upper()
```

Register `"GotoStatement": _goto` in `_HANDLERS`.

- [ ] **Step 3: Run the GO TO tests**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg/test_desugar_goto.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 4: Write the failing paragraph-assembly tests**

`tests/dataflow/srccfg/test_build_paragraphs.py`:

```python
"""The per-program skeleton: paragraphs in declaration order, fall-through between
them, and GO TO resolved to a label.

A paragraph is lowered once and shared. Every PERFORM of it and every GO TO into it
points at the same nodes, which is what keeps the graph the size of the source
instead of the size of the call tree.
"""

from __future__ import annotations

from cobble.dataflow.srccfg.build import (
    IMPLICIT_FIRST,
    build_program,
    end_id,
    label_id,
    paragraph_order,
)
from cobble.dataflow.srccfg.cfg import EdgeKind, NodeKind


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


def _two_paragraphs() -> dict:
    return {
        "program_id": "PROGA",
        "paragraphs": [
            {"name": "1000-FIRST", "statements": [_move("'F'", "WS-A")]},
            {"name": "2000-SECOND", "statements": [_move("WS-A", "WS-B")]},
        ],
    }


def test_paragraph_order_is_declaration_order(asg_of) -> None:
    """Both fall-through and PERFORM THRU ranges follow it, so it is the one thing
    that must not be sorted or de-duplicated."""
    order = paragraph_order(asg_of(_two_paragraphs()))

    assert [ref.name for ref in order] == ["1000-FIRST", "2000-SECOND"]


def test_paragraphs_inside_sections_keep_their_position_and_section(asg_of) -> None:
    asg = asg_of(
        {
            "program_id": "PROGA",
            "sections": [
                {
                    "name": "MAIN-SECTION",
                    "paragraphs": [{"name": "1000-FIRST", "statements": []}],
                }
            ],
            "paragraphs": [{"name": "2000-SECOND", "statements": []}],
        }
    )

    order = paragraph_order(asg)

    assert [(ref.name, ref.section) for ref in order] == [
        ("1000-FIRST", "MAIN-SECTION"),
        ("2000-SECOND", ""),
    ]


def test_division_level_statements_get_a_synthetic_first_paragraph(asg_of) -> None:
    """A program whose procedure division starts with bare statements has code that
    belongs to no paragraph. It still executes first, so it needs a name -- and the
    name is reserved so it cannot collide with a real paragraph."""
    asg = asg_of(
        {
            "program_id": "PROGA",
            "statements": [_move("'F'", "WS-A")],
            "paragraphs": [{"name": "1000-FIRST", "statements": []}],
        }
    )

    order = paragraph_order(asg)

    assert [ref.name for ref in order] == [IMPLICIT_FIRST, "1000-FIRST"]


def test_a_section_with_bare_statements_gets_one_too(asg_of) -> None:
    asg = asg_of(
        {
            "program_id": "PROGA",
            "sections": [
                {
                    "name": "MAIN-SECTION",
                    "statements": [_move("'F'", "WS-A")],
                    "paragraphs": [{"name": "1000-FIRST", "statements": []}],
                }
            ],
        }
    )

    assert [ref.name for ref in paragraph_order(asg)] == [
        f"MAIN-SECTION{IMPLICIT_FIRST}",
        "1000-FIRST",
    ]


def test_each_paragraph_gets_a_label_node_and_an_end_node(asg_of) -> None:
    cfg = build_program(asg_of(_two_paragraphs()))

    label = cfg.node(label_id("1000-FIRST"))
    assert (label.kind, label.paragraph) == (NodeKind.LABEL, "1000-FIRST")
    assert cfg.node(end_id("1000-FIRST")).kind == NodeKind.NOP


def test_a_paragraph_falls_through_to_the_next_one(asg_of) -> None:
    """Fall-through is why a paragraph's assignments can execute under a guard from
    a paragraph nobody PERFORMs it from."""
    cfg = build_program(asg_of(_two_paragraphs()))

    assert [(e.target, e.kind) for e in cfg.successors(end_id("1000-FIRST"))] == [
        (label_id("2000-SECOND"), EdgeKind.FALLTHRU)
    ]


def test_the_last_paragraph_falls_through_to_nothing(asg_of) -> None:
    cfg = build_program(asg_of(_two_paragraphs()))

    assert cfg.successors(end_id("2000-SECOND")) == ()


def test_a_paragraphs_statements_run_between_its_label_and_its_end(asg_of) -> None:
    cfg = build_program(asg_of(_two_paragraphs()))

    assert [e.target for e in cfg.successors(label_id("1000-FIRST"))] == ["1000-FIRST/0"]
    assert [e.target for e in cfg.successors("1000-FIRST/0")] == [end_id("1000-FIRST")]


def test_an_empty_paragraph_wires_its_label_straight_to_its_end(asg_of) -> None:
    """An empty paragraph is a PERFORM target and a fall-through hop, so it cannot
    be dropped -- doing so would silently join the paragraphs either side of it."""
    cfg = build_program(
        asg_of(
            {
                "program_id": "PROGA",
                "paragraphs": [
                    {"name": "1000-FIRST", "statements": []},
                    {"name": "2000-SECOND", "statements": [_move("'F'", "WS-A")]},
                ],
            }
        )
    )

    assert [e.target for e in cfg.successors(label_id("1000-FIRST"))] == [
        end_id("1000-FIRST")
    ]


def test_a_goto_becomes_an_edge_to_the_targets_label(asg_of) -> None:
    cfg = build_program(
        asg_of(
            {
                "program_id": "PROGA",
                "paragraphs": [
                    {
                        "name": "1000-FIRST",
                        "statements": [
                            {
                                "type": "GOTO",
                                "form": "simple",
                                "target": {"paragraph": "2000-SECOND"},
                            }
                        ],
                    },
                    {"name": "2000-SECOND", "statements": [_move("'F'", "WS-A")]},
                ],
            }
        )
    )

    assert [(e.target, e.kind) for e in cfg.successors("1000-FIRST/0")] == [
        (label_id("2000-SECOND"), EdgeKind.GOTO)
    ]


def test_a_goto_to_a_paragraph_the_program_does_not_declare_gets_no_edge(
    asg_of,
) -> None:
    """The target is in a copybook the parse could not resolve, or is a section
    name. An edge to a node that does not exist would break every walk, and the
    node itself already records the unresolved target."""
    cfg = build_program(
        asg_of(
            {
                "program_id": "PROGA",
                "paragraphs": [
                    {
                        "name": "1000-FIRST",
                        "statements": [
                            {
                                "type": "GOTO",
                                "form": "simple",
                                "target": {"paragraph": "NOWHERE"},
                            }
                        ],
                    }
                ],
            }
        )
    )

    assert cfg.successors("1000-FIRST/0") == ()
    assert cfg.node("1000-FIRST/0").target == "NOWHERE"


def test_every_edge_lands_on_a_node_that_exists(asg_of) -> None:
    """The invariant the whole package depends on, asserted on a program with a
    paragraph, a section, an empty paragraph and a GO TO."""
    cfg = build_program(
        asg_of(
            {
                "program_id": "PROGA",
                "sections": [
                    {
                        "name": "MAIN-SECTION",
                        "paragraphs": [
                            {
                                "name": "1000-FIRST",
                                "statements": [
                                    {
                                        "type": "GOTO",
                                        "form": "simple",
                                        "target": {"paragraph": "3000-THIRD"},
                                    }
                                ],
                            },
                            {"name": "2000-SECOND", "statements": []},
                        ],
                    }
                ],
                "paragraphs": [
                    {"name": "3000-THIRD", "statements": [_move("'F'", "WS-A")]}
                ],
            }
        )
    )

    dangling = {e.target for e in cfg.edges} - cfg.node_ids
    assert dangling == set()
    assert {e.source for e in cfg.edges} <= cfg.node_ids
```

- [ ] **Step 5: Run the assembly tests to verify they fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg/test_build_paragraphs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobble.dataflow.srccfg.build'`

- [ ] **Step 6: Write `build.py`**

```python
"""Per-program assembly: paragraphs in declaration order, and the edges between
them.

A paragraph is lowered ONCE. Every PERFORM of it and every GO TO into it points at
the same nodes, which keeps the graph the size of the source rather than the size
of the call tree -- and means a query answers about the paragraph, not about one
inlined copy of it.

Declaration order is load-bearing twice: fall-through follows it, and so does a
PERFORM THRU range. It is never sorted.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from cobble.dataflow.depgraph.flows import program_context

from cobble.dataflow.srccfg.cfg import (
    Cfg,
    Edge,
    EdgeKind,
    Node,
    NodeKind,
)
from cobble.dataflow.srccfg.conditions import condition_index
from cobble.dataflow.srccfg.desugar import Ctx, lower_statements

IMPLICIT_FIRST = "%MAIN"


@dataclass(frozen=True)
class ParagraphRef:
    name: str
    section: str
    statements: tuple


def label_id(name: str) -> str:
    return f"{name}#label"


def end_id(name: str) -> str:
    return f"{name}#end"


def paragraph_order(asg) -> tuple[ParagraphRef, ...]:
    """Declaration order, with a synthetic paragraph wherever statements belong to
    no paragraph -- division level, or the head of a section. That code executes,
    so it needs a name; the reserved prefix keeps the name from colliding."""
    return (
        *_implicit(IMPLICIT_FIRST, "", asg.statements),
        *(ref for section in asg.sections for ref in _of_section(section)),
        *(_of_paragraph(paragraph, "") for paragraph in asg.paragraphs),
    )


def _of_section(section) -> tuple[ParagraphRef, ...]:
    return (
        *_implicit(f"{section.name}{IMPLICIT_FIRST}", section.name, section.statements),
        *(_of_paragraph(paragraph, section.name) for paragraph in section.paragraphs),
    )


def _implicit(name: str, section: str, statements) -> tuple[ParagraphRef, ...]:
    if not statements:
        return ()
    return (ParagraphRef(name=name, section=section, statements=tuple(statements)),)


def _of_paragraph(paragraph, section: str) -> ParagraphRef:
    return ParagraphRef(
        name=paragraph.name, section=section, statements=tuple(paragraph.statements)
    )


def build_program(asg) -> Cfg:
    order = paragraph_order(asg)
    context = program_context(asg)
    index = condition_index(asg)
    parts = tuple(_paragraph_cfg(ref, asg.program_id, context, index) for ref in order)
    nodes = tuple(node for part in parts for node in part[0])
    edges = (
        *(edge for part in parts for edge in part[1]),
        *_fallthru(order),
    )
    known = frozenset(node.id for node in nodes)
    return Cfg(
        program=asg.program_id,
        nodes=nodes,
        edges=(*edges, *resolve_targets(nodes, known)),
    )


def _paragraph_cfg(
    ref: ParagraphRef, program: str, context, index
) -> tuple[tuple[Node, ...], tuple[Edge, ...]]:
    ctx = Ctx(program=program, paragraph=ref.name, flows=context, index=index)
    body = lower_statements(ref.statements, ctx, "")
    label = Node(id=label_id(ref.name), kind=NodeKind.LABEL, paragraph=ref.name)
    end = Node(id=end_id(ref.name), kind=NodeKind.NOP, paragraph=ref.name)
    return (
        (label, *body.nodes, end),
        (
            *body.edges,
            *_enter(label, body, end),
            *(
                Edge(source=exit_.node_id, target=end.id, kind=exit_.kind)
                for exit_ in body.exits
            ),
        ),
    )


def _enter(label: Node, body, end: Node) -> tuple[Edge, ...]:
    """An empty paragraph is still a PERFORM target and a fall-through hop, so its
    label goes straight to its end rather than the paragraph being dropped."""
    target = body.entry if body.nodes else end.id
    return (Edge(source=label.id, target=target, kind=EdgeKind.FLOW),)


def _fallthru(order: Sequence[ParagraphRef]) -> tuple[Edge, ...]:
    return tuple(
        Edge(source=end_id(current.name), target=label_id(nxt.name), kind=EdgeKind.FALLTHRU)
        for current, nxt in zip(order, order[1:])
    )


def resolve_targets(nodes: Sequence[Node], known: frozenset[str]) -> tuple[Edge, ...]:
    """GO TO nodes carry a paragraph name; here it becomes an edge to that label.

    A target the program does not declare gets NO edge: it is in an unresolved
    copybook or is a section name, and an edge to a node that does not exist would
    break every walk. The unresolved target stays on the node, so nothing is lost.
    """
    return tuple(
        Edge(source=node.id, target=label_id(node.target), kind=EdgeKind.GOTO)
        for node in nodes
        if node.target and label_id(node.target) in known
    )
```

`build_program` calls `resolve_targets(nodes, known)` — the interface block above
lists a three-argument form; use the two-argument one, and if a later task needs the
edges too, pass them then.

- [ ] **Step 7: Run the whole suite**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg -v`
Expected: PASS. `test_every_edge_lands_on_a_node_that_exists` is the one to trust —
if it fails, an id built in `desugar.py` and an id built in `build.py` disagree.

- [ ] **Step 8: Commit**

```bash
git add cobble/dataflow/srccfg tests/dataflow/srccfg
git commit -m "$(cat <<'EOF'
feat(cobble): assemble paragraphs with fall-through and resolve GO TO

Paragraphs are lowered once and shared, in declaration order, with a label and an
end node each and FALLTHRU edges between them. GO TO becomes an edge to a label;
computed GO TO fans out to every target and keeps the out-of-range fall-through.
A target the program does not declare stays on the node with no edge, so a walk
cannot land on a node that is not there.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---
### Task 8: PERFORM — ranges, returns, and the four loop forms

A `PERFORM` is a `CALL` node with a `PERFORM` edge to the target's label and a
`RETURN` edge from the end of the range back to whatever follows the call. Because
paragraphs are shared, the return edge is where the over-approximation lives: a
paragraph performed from two places has two return edges, so a walk can leave by the
wrong one. The spec accepts that, and the reaching-conditions pass in Task 12 prunes
it by matching perform edges to return edges along a path.

ASG shape: `PerformStatement(target: str, thru: str, children: list, spec)` where
`spec` is `PerformTimesSpec(times: str)`, `PerformUntilSpec(condition: dict, test_before: bool)`,
`PerformVaryingSpec(varying_var, varying_from, varying_by, condition, test_before, after_specs)`,
or `None`. `target` is a plain string, already the paragraph name.

**Files:**
- Modify: `cobble/dataflow/srccfg/desugar.py`
- Modify: `cobble/dataflow/srccfg/build.py`
- Test: `tests/dataflow/srccfg/test_desugar_perform.py`

**Interfaces:**
- Produces in `desugar.py`:
  - `_perform` registered for `PerformStatement`
  - `PERFORM_TRANSFER = "PERFORM"`
  - A perform node carries `transfer=PERFORM_TRANSFER`, `target=<first paragraph>`,
    and `writes`/`reads` empty; the range end goes in a second field — `Node.target`
    holds the entry, and the **range** is recomputed in `build.py` from
    `paragraph_order`, so no new field is needed on `Node`
  - `RANGE_SEPARATOR = "|"` — a THRU perform stores `"A|B"` in `target`
- Produces in `build.py`:
  - `paragraph_range(order, first: str, last: str) -> tuple[str, ...]`
  - `perform_edges(cfg_nodes, edges, order) -> tuple[Edge, ...]`

- [ ] **Step 1: Write the failing tests**

`tests/dataflow/srccfg/test_desugar_perform.py`:

```python
"""PERFORM: ranges, the return edge, and the loop forms.

The return edge is where this design over-approximates on purpose. A paragraph
performed from two places has two return edges, so an unconstrained walk can leave
by the wrong one; matching perform edges to return edges along a path is what
prunes that, and it belongs to the reaching-conditions pass, not here.
"""

from __future__ import annotations

from cobble.dataflow.depgraph.flows import program_context

from cobble.dataflow.srccfg.build import (
    build_program,
    end_id,
    label_id,
    paragraph_order,
    paragraph_range,
)
from cobble.dataflow.srccfg.cfg import EdgeKind, NodeKind
from cobble.dataflow.srccfg.conditions import condition_index
from cobble.dataflow.srccfg.desugar import (
    PERFORM_TRANSFER,
    RANGE_SEPARATOR,
    Ctx,
    lower_statements,
)


def _ctx(asg) -> Ctx:
    return Ctx(
        program=asg.program_id,
        paragraph="MAIN",
        flows=program_context(asg),
        index=condition_index(asg),
    )


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


def _cond(left: str, right: str) -> dict:
    return {
        "not": False,
        "relation": {
            "left": {"kind": "ref", "name": left},
            "op": "==",
            "right": {"kind": "lit", "value": right},
        },
    }


def _lower(program_of, statements: list[dict]):
    asg = program_of(statements)
    return lower_statements(asg.paragraphs[0].statements, _ctx(asg), "")


def _program(*paragraphs: dict) -> dict:
    return {"program_id": "PROGA", "paragraphs": list(paragraphs)}


def test_a_perform_of_one_paragraph_names_it_as_the_target(program_of) -> None:
    fragment = _lower(program_of, [{"type": "PERFORM", "operands": ["1000-FIRST"]}])

    node = fragment.nodes[0]
    assert (node.kind, node.transfer, node.target) == (
        NodeKind.CALL,
        PERFORM_TRANSFER,
        "1000-FIRST",
    )


def test_a_perform_keeps_a_flow_exit_because_control_comes_back(program_of) -> None:
    """The difference from GO TO, and the only structural difference: a PERFORM
    returns, so the statement after it is reachable."""
    fragment = _lower(program_of, [{"type": "PERFORM", "operands": ["1000-FIRST"]}])

    assert [e.kind for e in fragment.exits] == [EdgeKind.FLOW]


def test_a_perform_thru_stores_both_ends_of_the_range(program_of) -> None:
    fragment = _lower(
        program_of,
        [{"type": "PERFORM", "operands": ["1000-FIRST"], "thru": "3000-THIRD"}],
    )

    assert fragment.nodes[0].target == f"1000-FIRST{RANGE_SEPARATOR}3000-THIRD"


def test_a_range_is_the_paragraphs_between_the_two_ends_in_declaration_order(
    asg_of,
) -> None:
    """PERFORM A THRU C runs everything declared between them, whatever the names
    look like -- the numbering convention is not the order."""
    order = paragraph_order(
        asg_of(
            _program(
                {"name": "1000-FIRST", "statements": []},
                {"name": "2000-SECOND", "statements": []},
                {"name": "3000-THIRD", "statements": []},
            )
        )
    )

    assert paragraph_range(order, "1000-FIRST", "3000-THIRD") == (
        "1000-FIRST",
        "2000-SECOND",
        "3000-THIRD",
    )


def test_a_range_whose_ends_are_the_wrong_way_round_is_just_the_first(asg_of) -> None:
    """A THRU whose second name is declared before its first is a source defect the
    compiler accepts; over-approximating to the whole program would swamp every
    query, so the range is the entry alone."""
    order = paragraph_order(
        asg_of(
            _program(
                {"name": "1000-FIRST", "statements": []},
                {"name": "2000-SECOND", "statements": []},
            )
        )
    )

    assert paragraph_range(order, "2000-SECOND", "1000-FIRST") == ("2000-SECOND",)


def test_a_perform_edge_goes_to_the_label_and_the_return_comes_from_the_range_end(
    asg_of,
) -> None:
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "0000-MAIN",
                    "statements": [
                        {
                            "type": "PERFORM",
                            "operands": ["1000-FIRST"],
                            "thru": "2000-SECOND",
                        },
                        _move("'F'", "WS-RESULT"),
                    ],
                },
                {"name": "1000-FIRST", "statements": [_move("'A'", "WS-A")]},
                {"name": "2000-SECOND", "statements": [_move("'B'", "WS-B")]},
            )
        )
    )

    assert [(e.target, e.kind) for e in cfg.successors("0000-MAIN/0")] == [
        (label_id("1000-FIRST"), EdgeKind.PERFORM),
        ("0000-MAIN/1", EdgeKind.FLOW),
    ]
    assert (
        Edge_kind := [
            e.kind for e in cfg.successors(end_id("2000-SECOND")) if e.target == "0000-MAIN/1"
        ]
    ) == [EdgeKind.RETURN]


def test_a_perform_of_an_undeclared_paragraph_gets_no_edges(asg_of) -> None:
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "0000-MAIN",
                    "statements": [{"type": "PERFORM", "operands": ["NOWHERE"]}],
                }
            )
        )
    )

    assert [e.kind for e in cfg.successors("0000-MAIN/0")] == [EdgeKind.FLOW]
    assert cfg.node("0000-MAIN/0").target == "NOWHERE"


def test_an_inline_perform_lowers_its_body_in_place(program_of) -> None:
    """PERFORM with a body and no target is a block, not a call: there is no
    paragraph to share, so there is nothing to point at."""
    fragment = _lower(
        program_of,
        [{"type": "PERFORM", "children": [_move("'F'", "WS-RESULT")]}],
    )

    assert [node.id for node in fragment.nodes] == ["MAIN/0.body.0"]
    assert fragment.nodes[0].kind == NodeKind.ASSIGN


def test_perform_until_tests_before_the_body_by_default(program_of) -> None:
    """TEST BEFORE is the default, so a body that never runs is a real path -- and
    an assignment inside the body is guarded by the loop condition being false."""
    fragment = _lower(
        program_of,
        [
            {
                "type": "PERFORM",
                "perform_type": "UNTIL",
                "until": _cond("WS-EOF", "'Y'"),
                "children": [_move("'F'", "WS-RESULT")],
            }
        ],
    )

    test_node = next(n for n in fragment.nodes if n.kind == NodeKind.TEST)
    assert fragment.entry == test_node.id
    assert (
        Edge(source=test_node.id, target="MAIN/0.body.0", kind=EdgeKind.FALSE)
        in fragment.edges
    )
    assert [e.node_id for e in fragment.exits] == [test_node.id]
    assert [e.kind for e in fragment.exits] == [EdgeKind.TRUE]


def test_the_body_of_an_until_loop_goes_back_to_the_test(program_of) -> None:
    fragment = _lower(
        program_of,
        [
            {
                "type": "PERFORM",
                "perform_type": "UNTIL",
                "until": _cond("WS-EOF", "'Y'"),
                "children": [_move("'F'", "WS-RESULT")],
            }
        ],
    )

    test_node = next(n for n in fragment.nodes if n.kind == NodeKind.TEST)
    assert (
        Edge(source="MAIN/0.body.0", target=test_node.id, kind=EdgeKind.FLOW)
        in fragment.edges
    )


def test_perform_until_with_test_after_runs_the_body_first(program_of) -> None:
    """TEST AFTER makes the body unconditional on the first pass, which changes
    what guards an assignment inside it."""
    fragment = _lower(
        program_of,
        [
            {
                "type": "PERFORM",
                "perform_type": "UNTIL",
                "until": _cond("WS-EOF", "'Y'"),
                "test_before": False,
                "children": [_move("'F'", "WS-RESULT")],
            }
        ],
    )

    assert fragment.entry == "MAIN/0.body.0"


def test_perform_times_is_a_loop_whose_test_names_the_count(program_of) -> None:
    """The count is a field as often as a literal, and when it is a field the loop
    depends on it -- so it is a read on the test node."""
    fragment = _lower(
        program_of,
        [
            {
                "type": "PERFORM",
                "perform_type": "TIMES",
                "times": "WS-COUNT",
                "children": [_move("'F'", "WS-RESULT")],
            }
        ],
    )

    test_node = next(n for n in fragment.nodes if n.kind == NodeKind.TEST)
    assert (test_node.atom.left, test_node.atom.op) == ("WS-COUNT", "TIMES")
    assert test_node.reads == ("WS-COUNT",)


def test_perform_varying_initialises_steps_and_tests(program_of) -> None:
    """Three extra nodes, and both assignments to the loop variable are real
    definitions -- a query for what writes the index has to find them."""
    fragment = _lower(
        program_of,
        [
            {
                "type": "PERFORM",
                "perform_type": "VARYING",
                "varying_var": "WS-IDX",
                "varying_from": "1",
                "varying_by": "1",
                "until": _cond("WS-IDX", "10"),
                "children": [_move("'F'", "WS-RESULT")],
            }
        ],
    )

    by_id = {node.id: node for node in fragment.nodes}
    assert by_id["MAIN/0#init"].writes == ("WS-IDX",)
    assert by_id["MAIN/0#init"].reads == ("1",)
    assert by_id["MAIN/0#step"].writes == ("WS-IDX",)
    assert by_id["MAIN/0#step"].reads == ("WS-IDX", "1")
    assert fragment.entry == "MAIN/0#init"


def test_the_step_of_a_varying_loop_goes_back_to_the_test(program_of) -> None:
    fragment = _lower(
        program_of,
        [
            {
                "type": "PERFORM",
                "perform_type": "VARYING",
                "varying_var": "WS-IDX",
                "varying_from": "1",
                "varying_by": "1",
                "until": _cond("WS-IDX", "10"),
                "children": [_move("'F'", "WS-RESULT")],
            }
        ],
    )

    test_node = next(n for n in fragment.nodes if n.kind == NodeKind.TEST)
    assert (
        Edge(source="MAIN/0#step", target=test_node.id, kind=EdgeKind.FLOW)
        in fragment.edges
    )


def test_a_loop_around_a_performed_paragraph_keeps_both(program_of) -> None:
    """PERFORM P UNTIL C is a loop whose body is a call, so the CALL node is inside
    the loop and the paragraph is still shared."""
    fragment = _lower(
        program_of,
        [
            {
                "type": "PERFORM",
                "operands": ["1000-FIRST"],
                "perform_type": "UNTIL",
                "until": _cond("WS-EOF", "'Y'"),
            }
        ],
    )

    kinds = {node.kind for node in fragment.nodes}
    assert kinds == {NodeKind.TEST, NodeKind.CALL}
    call = next(n for n in fragment.nodes if n.kind == NodeKind.CALL)
    assert call.target == "1000-FIRST"
```

The `Edge` used in the assertions is `cobble.dataflow.srccfg.cfg.Edge`; add it to the
imports. Delete the stray walrus in
`test_a_perform_edge_goes_to_the_label_and_the_return_comes_from_the_range_end` and
write it as a plain assertion on the list.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg/test_desugar_perform.py -v`
Expected: FAIL — `ImportError: cannot import name 'PERFORM_TRANSFER'`

- [ ] **Step 3: Add the PERFORM handler**

Add to `cobble/dataflow/srccfg/desugar.py`:

```python
PERFORM_TRANSFER = "PERFORM"
RANGE_SEPARATOR = "|"
TIMES_OP = "TIMES"


def _perform(statement, ctx: Ctx, path: str) -> Fragment:
    """A call, a block, or either of those wrapped in a loop."""
    inner = _perform_body(statement, ctx, path)
    return _loop(getattr(statement, "spec", None), inner, ctx, path)


def _perform_body(statement, ctx: Ctx, path: str) -> Fragment:
    target = str(getattr(statement, "target", "") or "").upper()
    if not target:
        return lower_statements(getattr(statement, "children", ()), ctx, f"{path}.body")
    return _call(ctx, path, _range_target(target, getattr(statement, "thru", "")))


def _range_target(target: str, thru: str) -> str:
    last = str(thru or "").upper()
    return f"{target}{RANGE_SEPARATOR}{last}" if last else target


def _call(ctx: Ctx, path: str, target: str) -> Fragment:
    node = Node(
        id=node_id(ctx, path),
        kind=NodeKind.CALL,
        paragraph=ctx.paragraph,
        transfer=PERFORM_TRANSFER,
        target=target,
    )
    return Fragment(
        nodes=(node,),
        edges=(),
        entry=node.id,
        exits=(Exit(node_id=node.id, kind=EdgeKind.FLOW),),
    )


def _loop(spec, body: Fragment, ctx: Ctx, path: str) -> Fragment:
    kind = type(spec).__name__
    if kind == "PerformTimesSpec":
        return _tested_loop(_times_test(spec, ctx, path), body, before=True)
    if kind == "PerformUntilSpec":
        return _tested_loop(
            _until_test(spec, ctx, path), body, before=_before(spec)
        )
    if kind == "PerformVaryingSpec":
        return _varying_loop(spec, body, ctx, path)
    return body


def _before(spec) -> bool:
    return bool(getattr(spec, "test_before", True))


def _times_test(spec, ctx: Ctx, path: str) -> CondFragment:
    """The count is a field as often as a literal; when it is a field the loop
    depends on it, so it is a read on the test."""
    times = str(getattr(spec, "times", "") or "").upper()
    node = Node(
        id=node_id(ctx, path, "#loop"),
        kind=NodeKind.TEST,
        paragraph=ctx.paragraph,
        atom=Atom(text=f"{times} TIMES", left=times, op=TIMES_OP),
        reads=_dedupe((times,)),
    )
    return _exits_of(node)


def _until_test(spec, ctx: Ctx, path: str) -> CondFragment:
    return lower_condition(
        read_condition(getattr(spec, "condition", {})), ctx, f"{path}#loop"
    )


def _exits_of(node: Node) -> CondFragment:
    return CondFragment(
        nodes=(node,),
        edges=(),
        entry=node.id,
        true_exits=(Exit(node_id=node.id, kind=EdgeKind.TRUE),),
        false_exits=(Exit(node_id=node.id, kind=EdgeKind.FALSE),),
    )


def _tested_loop(test: CondFragment, body: Fragment, before: bool) -> Fragment:
    """UNTIL and TIMES both leave the loop on TRUE and enter the body on FALSE.

    TEST BEFORE makes the body's execution conditional, which is what a query about
    an assignment inside the body must see; TEST AFTER makes the first pass
    unconditional, so the entry is the body.
    """
    back = tuple(
        Edge(source=exit_.node_id, target=test.entry, kind=exit_.kind)
        for exit_ in body.exits
    )
    into_body = _attach(test.false_exits, body)
    return Fragment(
        nodes=(*test.nodes, *body.nodes),
        edges=(*test.edges, *body.edges, *into_body, *back),
        entry=test.entry if before or not body.nodes else body.entry,
        exits=test.true_exits,
    )


def _varying_loop(spec, body: Fragment, ctx: Ctx, path: str) -> Fragment:
    """FROM and BY are assignments to the loop variable, and both are definitions a
    query for its writers has to find."""
    variable = str(getattr(spec, "varying_var", "") or "").upper()
    init = _step_node(ctx, path, "#init", variable, (_text(getattr(spec, "varying_from", "")),))
    step = _step_node(
        ctx, path, "#step", variable, (variable, _text(getattr(spec, "varying_by", "")))
    )
    loop = _tested_loop(_until_test(spec, ctx, path), _with_step(body, step), before=True)
    return Fragment(
        nodes=(init, *loop.nodes),
        edges=(*loop.edges, Edge(source=init.id, target=loop.entry, kind=EdgeKind.FLOW)),
        entry=init.id,
        exits=loop.exits,
    )


def _with_step(body: Fragment, step: Node) -> Fragment:
    stepped = Fragment(
        nodes=(step,),
        edges=(),
        entry=step.id,
        exits=(Exit(node_id=step.id, kind=EdgeKind.FLOW),),
    )
    return seq((body, stepped), nop_id=step.id) if body.nodes else stepped


def _step_node(
    ctx: Ctx, path: str, suffix: str, variable: str, reads: tuple[str, ...]
) -> Node:
    return Node(
        id=node_id(ctx, path, suffix),
        kind=NodeKind.ASSIGN,
        paragraph=ctx.paragraph,
        writes=_dedupe((variable,)),
        reads=_dedupe(reads),
        transfer="SET",
    )


def _text(value) -> str:
    """varying_from is a structured expression dict in newer parses and text in
    older ones; either way what is wanted is the name or the literal."""
    if isinstance(value, Mapping):
        return str(value.get("name", value.get("value", ""))).upper()
    return str(value or "").upper()
```

Register `"PerformStatement": _perform`, and add `Atom` to the `.conditions`/`.cfg`
imports as needed.

- [ ] **Step 4: Add range and return edges to `build.py`**

```python
def paragraph_range(
    order: Sequence[ParagraphRef], first: str, last: str
) -> tuple[str, ...]:
    """The paragraphs a PERFORM A THRU B actually runs: everything declared between
    them. The numbering convention is not the order -- declaration order is.

    Ends the wrong way round is a source defect the compiler accepts. Widening to
    the rest of the program would swamp every query, so the range is the entry
    alone.
    """
    names = tuple(ref.name for ref in order)
    if first not in names:
        return ()
    start = names.index(first)
    if last not in names or names.index(last) < start:
        return (first,)
    return names[start : names.index(last) + 1]


def _perform_edges(
    nodes: Sequence[Node], edges: Sequence[Edge], order: Sequence[ParagraphRef]
) -> tuple[Edge, ...]:
    """A PERFORM edge into the range's first label, and a RETURN edge out of the
    range's last end into whatever the call node flows to.

    Two PERFORMs of one paragraph give it two RETURN edges. That is the deliberate
    over-approximation; pruning it needs the path, which is the reaching-conditions
    pass's business.
    """
    known = frozenset(ref.name for ref in order)
    return tuple(
        edge
        for node in nodes
        if node.transfer == PERFORM_TRANSFER
        for edge in _one_perform(node, edges, order, known)
    )


def _one_perform(
    node: Node, edges: Sequence[Edge], order: Sequence[ParagraphRef], known: frozenset[str]
) -> tuple[Edge, ...]:
    first, _, last = node.target.partition(RANGE_SEPARATOR)
    span = paragraph_range(order, first, last)
    if not span or first not in known:
        return ()
    return (
        Edge(source=node.id, target=label_id(span[0]), kind=EdgeKind.PERFORM),
        *(
            Edge(source=end_id(span[-1]), target=flow.target, kind=EdgeKind.RETURN)
            for flow in edges
            if flow.source == node.id and flow.kind is EdgeKind.FLOW
        ),
    )
```

`build_program` gains one line: the perform edges are appended after the fall-through
edges and before `resolve_targets`, and `resolve_targets` must now skip PERFORM nodes
(it keys off `node.target`, which a perform node also carries). Change its filter to
`if node.transfer == GOTO_TRANSFER and node.target and ...`, importing
`GOTO_TRANSFER` and `PERFORM_TRANSFER` from `desugar`.

```python
def build_program(asg) -> Cfg:
    order = paragraph_order(asg)
    context = program_context(asg)
    index = condition_index(asg)
    parts = tuple(_paragraph_cfg(ref, asg.program_id, context, index) for ref in order)
    nodes = tuple(node for part in parts for node in part[0])
    body = (*(edge for part in parts for edge in part[1]), *_fallthru(order))
    known = frozenset(node.id for node in nodes)
    return Cfg(
        program=asg.program_id,
        nodes=nodes,
        edges=(*body, *_perform_edges(nodes, body, order), *resolve_targets(nodes, known)),
    )
```

- [ ] **Step 5: Run the whole suite**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg -v`
Expected: PASS. Re-check `test_every_edge_lands_on_a_node_that_exists` from Task 7 —
the perform edges are the likeliest source of a dangling target.

- [ ] **Step 6: Commit**

```bash
git add cobble/dataflow/srccfg tests/dataflow/srccfg/test_desugar_perform.py
git commit -m "$(cat <<'EOF'
feat(cobble): lower PERFORM ranges, returns and the loop forms

A PERFORM is a CALL node with a PERFORM edge to the range's first label and a
RETURN edge from its last end back to the continuation, with the range read off
declaration order. UNTIL honours TEST BEFORE and TEST AFTER; TIMES keeps the count
as a read; VARYING emits the FROM and BY assignments, because both are definitions
of the loop variable.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---
### Task 9: I/O conditional arms and SEARCH

`AT END`, `INVALID KEY` and `ON SIZE ERROR` are guards written as clauses of another
statement. An assignment in an `AT END` arm executes only when the read failed, and a
pass that treats the arm as unconditional reports it as a writer under no guard at
all. The predicate is not a field the program declares, so a synthetic one is used:
`%IOSTATUS[<file or target>]`.

`SEARCH WHEN` conditions arrive as **opaque text** (`SearchWhen.condition: str`), so
their atoms are `UNRESOLVED` — and per the spec, that is stated rather than hidden.

ASG shapes:
- `ReadStatement(file_name, into, key, at_end, not_at_end, invalid_key, not_invalid_key)`
- `WriteStatement` / `RewriteStatement`: `invalid_key`, `not_invalid_key`
- `ArithmeticStatement` / `ComputeStatement`: `on_size_error`, `not_on_size_error`
- `SearchStatement(table, varying, whens: list[SearchWhen], at_end)`;
  `SearchWhen(condition: str, children: list)`

**Files:**
- Modify: `cobble/dataflow/srccfg/desugar.py`
- Test: `tests/dataflow/srccfg/test_desugar_arms.py`

**Interfaces:**
- Produces:
  - `ARM_CLAUSES: tuple[tuple[str, str, str], ...]` — `(true_attr, false_attr, label)`
    triples: `("at_end", "not_at_end", "AT END")`,
    `("invalid_key", "not_invalid_key", "INVALID KEY")`,
    `("on_size_error", "not_on_size_error", "ON SIZE ERROR")`
  - `io_status_field(subject: str) -> str` = `f"%IOSTATUS[{subject}]"`
  - `_search` registered for `SearchStatement`
  - `_plain` now wraps its node in the arm structure when any arm attribute is present

- [ ] **Step 1: Write the failing tests**

`tests/dataflow/srccfg/test_desugar_arms.py`:

```python
"""AT END, INVALID KEY, ON SIZE ERROR, and SEARCH.

These are guards written as clauses of another statement. An assignment in an AT END
arm runs only when the read failed; treating the arm as unconditional reports it as
a writer under no guard, which is the wrong answer to the question the whole pass
exists to answer.
"""

from __future__ import annotations

from cobble.dataflow.depgraph.flows import program_context

from cobble.dataflow.srccfg.cfg import Cfg, EdgeKind, NodeKind
from cobble.dataflow.srccfg.conditions import condition_index
from cobble.dataflow.srccfg.desugar import Ctx, io_status_field, lower_statements


def _ctx(asg) -> Ctx:
    return Ctx(
        program=asg.program_id,
        paragraph="MAIN",
        flows=program_context(asg),
        index=condition_index(asg),
    )


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


def _cfg(program_of, statements: list[dict], **extra) -> Cfg:
    asg = program_of(statements, **extra)
    fragment = lower_statements(asg.paragraphs[0].statements, _ctx(asg), "")
    return Cfg(program="PROGA", nodes=fragment.nodes, edges=fragment.edges)


_FILE_CONTROL = {"file_control": [{"file_name": "CUST-FILE", "assign_to": "CUSTDD"}]}


def test_an_at_end_arm_runs_under_a_test_on_the_files_status(program_of) -> None:
    """The predicate is not a field the program declares, so a synthetic one names
    the file it is about -- which is also what makes two files' AT END arms
    distinguishable."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "READ",
                "file_name": "CUST-FILE",
                "at_end": [_move("'Y'", "WS-EOF")],
            }
        ],
        **_FILE_CONTROL,
    )

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert test_node.atom.left == io_status_field("CUST-FILE")
    assert test_node.atom.right == "AT END"


def test_the_at_end_arm_is_on_the_true_edge_and_not_at_end_on_the_false(
    program_of,
) -> None:
    cfg = _cfg(
        program_of,
        [
            {
                "type": "READ",
                "file_name": "CUST-FILE",
                "at_end": [_move("'Y'", "WS-EOF")],
                "not_at_end": [_move("'N'", "WS-EOF")],
            }
        ],
        **_FILE_CONTROL,
    )

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert {(e.target, e.kind) for e in cfg.successors(test_node.id)} == {
        ("MAIN/0.at_end.0", EdgeKind.TRUE),
        ("MAIN/0.not_at_end.0", EdgeKind.FALSE),
    }


def test_the_read_itself_still_happens_before_the_test(program_of) -> None:
    """READ INTO is an assignment, and it happens whichever arm is taken -- so the
    ASSIGN node comes first and the test hangs off it."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "READ",
                "file_name": "CUST-FILE",
                "into": "WS-REC",
                "at_end": [_move("'Y'", "WS-EOF")],
            }
        ],
        **_FILE_CONTROL,
    )

    read = cfg.node("MAIN/0")
    assert read.writes == ("WS-REC",)
    assert [e.target for e in cfg.successors("MAIN/0")] == ["MAIN/0#arm"]


def test_an_invalid_key_arm_is_guarded_the_same_way(program_of) -> None:
    cfg = _cfg(
        program_of,
        [
            {
                "type": "WRITE",
                "record_name": "CUST-REC",
                "invalid_key": [_move("'E'", "WS-STATUS")],
            }
        ],
    )

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert test_node.atom.right == "INVALID KEY"


def test_an_on_size_error_arm_is_guarded_by_the_targets_own_status(program_of) -> None:
    """A size error is about the arithmetic, not about a file, so the synthetic
    field names the target being computed into."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "COMPUTE",
                "targets": [{"name": "WS-TOTAL"}],
                "expression": {"kind": "ref", "name": "WS-A"},
                "on_size_error": [_move("'E'", "WS-STATUS")],
            }
        ],
    )

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert test_node.atom.left == io_status_field("WS-TOTAL")


def test_a_statement_with_no_arms_gets_no_extra_node(program_of) -> None:
    """The overwhelming majority of statements. An unconditional MOVE must not grow
    a test node it does not need."""
    cfg = _cfg(program_of, [_move("'F'", "WS-RESULT")])

    assert len(cfg.nodes) == 1


def test_both_arms_and_the_fall_through_continue_into_the_next_statement(
    program_of,
) -> None:
    cfg = _cfg(
        program_of,
        [
            {
                "type": "READ",
                "file_name": "CUST-FILE",
                "at_end": [_move("'Y'", "WS-EOF")],
            },
            _move("WS-EOF", "WS-COPY"),
        ],
        **_FILE_CONTROL,
    )

    assert {e.source for e in cfg.predecessors("MAIN/1")} == {
        "MAIN/0.at_end.0",
        "MAIN/0#arm",
    }


def test_a_search_when_is_a_test_whose_predicate_is_unresolved(program_of) -> None:
    """The ASG gives a SEARCH WHEN condition as opaque text. The fork is real, so
    the node exists; the parts are unknown, and saying so is the requirement --
    inventing an atom from the text would be a guess a report could not qualify."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "SEARCH",
                "table": "WS-TABLE",
                "varying": "WS-IDX",
                "whens": [
                    {"condition": "WS-TABLE-KEY (WS-IDX) = WS-WANTED", "children": [
                        _move("'F'", "WS-RESULT")
                    ]}
                ],
            }
        ],
    )

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert test_node.atom.resolved is False
    assert test_node.atom.text == "WS-TABLE-KEY (WS-IDX) = WS-WANTED"


def test_a_search_body_is_reached_on_the_true_edge_of_its_when(program_of) -> None:
    cfg = _cfg(
        program_of,
        [
            {
                "type": "SEARCH",
                "table": "WS-TABLE",
                "whens": [{"condition": "A = B", "children": [_move("'F'", "WS-RESULT")]}],
            }
        ],
    )

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert [(e.target, e.kind) for e in cfg.successors(test_node.id)] == [
        ("MAIN/0.when.0.0", EdgeKind.TRUE)
    ]


def test_a_second_search_when_is_reached_on_the_firsts_false_edge(program_of) -> None:
    """Same chain as EVALUATE: a WHEN is tried only when the ones above it failed."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "SEARCH",
                "table": "WS-TABLE",
                "whens": [
                    {"condition": "A = B", "children": [_move("'F'", "WS-RESULT")]},
                    {"condition": "A = C", "children": [_move("'G'", "WS-RESULT")]},
                ],
            }
        ],
    )

    first, second = (n.id for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert [e.target for e in cfg.successors(first) if e.kind is EdgeKind.FALSE] == [second]


def test_a_search_at_end_arm_is_the_last_false_arm(program_of) -> None:
    cfg = _cfg(
        program_of,
        [
            {
                "type": "SEARCH",
                "table": "WS-TABLE",
                "whens": [{"condition": "A = B", "children": [_move("'F'", "WS-RESULT")]}],
                "at_end": [_move("'Z'", "WS-RESULT")],
            }
        ],
    )

    assert [e.kind for e in cfg.predecessors("MAIN/0.at_end.0")] == [EdgeKind.FALSE]


def test_a_search_reads_the_table_and_its_index(program_of) -> None:
    """flows already has a SearchStatement rule; this asserts the reuse rather than
    a second reading of the same statement."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "SEARCH",
                "table": "WS-TABLE",
                "varying": "WS-IDX",
                "whens": [{"condition": "A = B", "children": []}],
            }
        ],
    )

    assert "WS-TABLE" in cfg.node("MAIN/0").reads
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg/test_desugar_arms.py -v`
Expected: FAIL — `ImportError: cannot import name 'io_status_field'`

- [ ] **Step 3: Write the implementation**

Add to `cobble/dataflow/srccfg/desugar.py`:

```python
ARM_CLAUSES = (
    ("at_end", "not_at_end", "AT END"),
    ("invalid_key", "not_invalid_key", "INVALID KEY"),
    ("on_size_error", "not_on_size_error", "ON SIZE ERROR"),
)


def io_status_field(subject: str) -> str:
    """The synthetic field an I-O arm tests.

    No field the program declares carries this, and naming the subject is what
    keeps two files' AT END arms -- or two computes' size errors -- distinct.
    """
    return f"%IOSTATUS[{subject}]"


def _with_arms(statement, ctx: Ctx, path: str, body: Fragment) -> Fragment:
    clause = _first_arm(statement)
    if not clause:
        return body
    true_attr, false_attr, label = clause
    cond = _arm_test(statement, ctx, path, label)
    arms = _wire_arms(
        cond,
        lower_statements(getattr(statement, true_attr, ()), ctx, f"{path}.{true_attr}"),
        lower_statements(getattr(statement, false_attr, ()), ctx, f"{path}.{false_attr}"),
    )
    return seq((body, arms), nop_id=node_id(ctx, path, "#arm"))


def _first_arm(statement) -> tuple[str, str, str]:
    present = tuple(
        clause
        for clause in ARM_CLAUSES
        if getattr(statement, clause[0], ()) or getattr(statement, clause[1], ())
    )
    return present[0] if present else ()


def _arm_test(statement, ctx: Ctx, path: str, label: str) -> CondFragment:
    subject = _arm_subject(statement)
    node = Node(
        id=node_id(ctx, path, "#arm"),
        kind=NodeKind.TEST,
        paragraph=ctx.paragraph,
        atom=Atom(
            text=f"{label} {subject}",
            left=io_status_field(subject),
            op="==",
            right=label,
        ),
    )
    return _exits_of(node)


def _arm_subject(statement) -> str:
    """A file when there is one, otherwise the first target -- a size error is about
    the arithmetic, not about a file."""
    named = str(getattr(statement, "file_name", "") or "").upper()
    if named:
        return named
    targets = _names(getattr(statement, "targets", ()))
    return targets[0] if targets else str(
        getattr(statement, "record_name", "") or ""
    ).upper()
```

`_plain` becomes:

```python
def _plain(statement, ctx: Ctx, path: str) -> Fragment:
    kind = type(statement).__name__
    writes, reads = _writes_reads(statement, ctx, kind)
    node = Node(
        id=node_id(ctx, path),
        kind=NodeKind.ASSIGN if writes or reads else NodeKind.NOP,
        paragraph=ctx.paragraph,
        writes=writes,
        reads=reads,
        transfer=verb_of(statement) or _fallback_verb(kind),
    )
    return _with_arms(statement, ctx, path, _one(node))
```

And SEARCH, which is the EVALUATE chain over `whens` with `at_end` as the last FALSE
arm:

```python
def _search(statement, ctx: Ctx, path: str) -> Fragment:
    """The whens chain like EVALUATE's branches, and AT END is the last FALSE arm.

    A WHEN's condition is opaque text in the ASG, so its atom is UNRESOLVED. The
    fork is real and the node exists; inventing parts from the text would be a
    guess no report could qualify.
    """
    head = _plain_without_arms(statement, ctx, path)
    branches = tuple(
        _search_branch(when, ctx, f"{path}.when.{position}")
        for position, when in enumerate(getattr(statement, "whens", ()))
    )
    at_end = lower_statements(getattr(statement, "at_end", ()), ctx, f"{path}.at_end")
    tail = _chain_branches(
        (*(b for b in branches if b.nodes), *_as_branch(at_end))
    )
    return seq((head, tail), nop_id=node_id(ctx, path, "#search"))


def _search_branch(when, ctx: Ctx, path: str) -> _Branch:
    body = lower_statements(getattr(when, "children", ()), ctx, path)
    node = Node(
        id=node_id(ctx, path, "#test"),
        kind=NodeKind.TEST,
        paragraph=ctx.paragraph,
        atom=Atom(text=str(getattr(when, "condition", "")), resolved=False),
    )
    cond = _exits_of(node)
    return _Branch(
        nodes=(node, *body.nodes),
        edges=_attach(cond.true_exits, body),
        entry=node.id,
        body_exits=body.exits if body.nodes else cond.true_exits,
        false_exits=cond.false_exits,
    )


def _as_branch(arm: Fragment) -> tuple[_Branch, ...]:
    if not arm.nodes:
        return ()
    return (
        _Branch(
            nodes=arm.nodes,
            edges=arm.edges,
            entry=arm.entry,
            body_exits=arm.exits,
            false_exits=(),
        ),
    )


def _plain_without_arms(statement, ctx: Ctx, path: str) -> Fragment:
    kind = type(statement).__name__
    writes, reads = _writes_reads(statement, ctx, kind)
    return _one(
        Node(
            id=node_id(ctx, path),
            kind=NodeKind.ASSIGN if writes or reads else NodeKind.NOP,
            paragraph=ctx.paragraph,
            writes=writes,
            reads=reads,
            transfer=verb_of(statement) or _fallback_verb(kind),
        )
    )
```

Register `"SearchStatement": _search`. `_plain` now delegates to
`_plain_without_arms` plus `_with_arms`, which keeps both under the ten-statement
limit.

- [ ] **Step 4: Run the whole suite**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg -v`
Expected: PASS. If `test_a_search_reads_the_table_and_its_index` fails, print
`flows.blocks_of` for that statement — the rule may name the table only as a target,
in which case assert on `writes` instead and say so in the test's docstring.

- [ ] **Step 5: Commit**

```bash
git add cobble/dataflow/srccfg/desugar.py tests/dataflow/srccfg/test_desugar_arms.py
git commit -m "$(cat <<'EOF'
feat(cobble): guard I-O arms and lower SEARCH

AT END, INVALID KEY and ON SIZE ERROR become tests on a synthetic status field
named for the file or the target, so an assignment inside an arm is reported under
the condition that reached it. SEARCH chains its WHENs like EVALUATE with AT END as
the last arm; a WHEN's predicate is opaque text in the ASG and its atom says so.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---
### Task 10: HANDLE CONDITION folds into the same two node kinds

`EXEC CICS HANDLE CONDITION MAPFAIL(9999-MAPFAIL)` is not control flow where it is
written — it *arms* a handler that fires at some later command. Rather than a third
node kind, it becomes an `ASSIGN` to a synthetic field `%HANDLER[MAPFAIL]`, and a
command that can raise becomes a `TEST` on that field plus a dispatch node. Which
paragraph the dispatch reaches is then a **reaching-definitions** question over
`%HANDLER[…]`, answered by the pass in Task 13 — so `PUSH HANDLE` / `POP HANDLE` and
re-arming in a loop all come out of machinery that already exists.

ASG shape, verified against `cicada/cics/statements.py`:
`ExecCicsStatement(verb: str, options: dict[str, CicsOperand | None])`, where
`CicsOperand` has `.text: str` and `.is_literal: bool`. An option that carries no
value — `NOHANDLE`, `RESP` as a bare flag, `IGNORE CONDITION MAPFAIL` — is a key
present with the value `None`, so reading an option means checking for an operand
rather than checking for the key. The serialized JSON in the ASG cache is
`{"type": "EXEC_CICS", "verb": "HANDLE CONDITION", "options": {"MAPFAIL": {"text":
"9999-MAPFAIL", "is_literal": false}}}`, and `cics_cache.SerializedCicsDialectParser`
turns each value back into a `CicsOperand`. `EXEC_CICS` is **not** in the base
dispatch table, so tests must build ASGs inside
`cached_asg_dialect_parsers_registered()` — the `asg_of` fixture already does.

**Files:**
- Modify: `cobble/dataflow/srccfg/desugar.py`
- Test: `tests/dataflow/srccfg/test_desugar_cics.py`

**Interfaces:**
- Produces:
  - `handler_field(condition: str) -> str` = `f"%HANDLER[{condition}]"`
  - `IGNORED = "%IGNORE"`, `SYSTEM_DEFAULT = "%SYSTEM"`, `RAISED = "RAISED"`
  - `ARMING_VERBS = ("HANDLE CONDITION", "IGNORE CONDITION", "HANDLE AID")`
  - `SUPPRESSING_OPTIONS = ("NOHANDLE", "RESP", "RESP2")`
  - `HANDLER_ANY = "%HANDLER[ANY]"` — the field a raise test reads
  - `DISPATCH_TRANSFER_CICS = "HANDLE DISPATCH"` — the node Task 13 resolves
  - `_exec_cics` registered for `ExecCicsStatement`

- [ ] **Step 1: Write the failing tests**

`tests/dataflow/srccfg/test_desugar_cics.py`:

```python
"""EXEC CICS: arming a handler, and a command that can raise.

Arming is an assignment to a synthetic field, and dispatch is a test on it. That is
the whole trick: PUSH HANDLE, re-arming inside a loop, and "which handler is live
here" all become reaching definitions over %HANDLER[...], with no third node kind
and no separate handler model.
"""

from __future__ import annotations

from cobble.dataflow.depgraph.flows import program_context

from cobble.dataflow.srccfg.cfg import Cfg, EdgeKind, NodeKind
from cobble.dataflow.srccfg.conditions import condition_index
from cobble.dataflow.srccfg.desugar import (
    DISPATCH_TRANSFER_CICS,
    HANDLER_ANY,
    IGNORED,
    RAISED,
    SYSTEM_DEFAULT,
    Ctx,
    handler_field,
    lower_statements,
)


def _ctx(asg) -> Ctx:
    return Ctx(
        program=asg.program_id,
        paragraph="MAIN",
        flows=program_context(asg),
        index=condition_index(asg),
    )


def _cfg(program_of, statements: list[dict]) -> Cfg:
    asg = program_of(statements)
    fragment = lower_statements(asg.paragraphs[0].statements, _ctx(asg), "")
    return Cfg(program="PROGA", nodes=fragment.nodes, edges=fragment.edges)


def _cics(verb: str, options: dict) -> dict:
    return {"type": "EXEC_CICS", "verb": verb, "options": options}


def test_handle_condition_writes_the_handler_field_and_reads_the_paragraph(
    program_of,
) -> None:
    cfg = _cfg(
        program_of,
        [
            _cics(
                "HANDLE CONDITION",
                {"MAPFAIL": {"text": "9999-MAPFAIL", "is_literal": False}},
            )
        ],
    )

    node = cfg.node("MAIN/0")
    assert (node.kind, node.writes, node.reads) == (
        NodeKind.ASSIGN,
        (handler_field("MAPFAIL"),),
        ("9999-MAPFAIL",),
    )


def test_arming_two_conditions_in_one_command_writes_both_fields(program_of) -> None:
    """One statement, two definitions -- and they are independent, so a later
    re-arming of one must not look like a re-arming of the other."""
    cfg = _cfg(
        program_of,
        [
            _cics(
                "HANDLE CONDITION",
                {
                    "MAPFAIL": {"text": "9999-MAPFAIL", "is_literal": False},
                    "ERROR": {"text": "9999-ERROR", "is_literal": False},
                },
            )
        ],
    )

    assert cfg.node("MAIN/0").writes == (
        handler_field("MAPFAIL"),
        handler_field("ERROR"),
    )


def test_a_condition_armed_with_no_paragraph_resets_to_the_system_default(
    program_of,
) -> None:
    """HANDLE CONDITION ERROR with no label disarms the program's own handler. That
    is a definition, and the value it writes has to be distinguishable from a
    paragraph name."""
    cfg = _cfg(program_of, [_cics("HANDLE CONDITION", {"ERROR": None})])

    assert cfg.node("MAIN/0").reads == (SYSTEM_DEFAULT,)


def test_ignore_condition_writes_the_ignore_marker(program_of) -> None:
    """IGNORE CONDITION means "do not transfer control", which is a different live
    value from "no handler armed" -- the command returns and execution continues."""
    cfg = _cfg(program_of, [_cics("IGNORE CONDITION", {"MAPFAIL": None})])

    node = cfg.node("MAIN/0")
    assert (node.writes, node.reads) == ((handler_field("MAPFAIL"),), (IGNORED,))


def test_a_command_that_can_raise_gets_a_test_and_a_dispatch_node(program_of) -> None:
    """The dispatch has no target yet: which handler is live here is a
    reaching-definitions question over %HANDLER[...], answered by a later pass."""
    cfg = _cfg(program_of, [_cics("RECEIVE MAP", {"MAP": {"text": "'MAPA'", "is_literal": True}})])

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert (test_node.atom.left, test_node.atom.right) == (HANDLER_ANY, RAISED)
    dispatch = cfg.node("MAIN/0#dispatch")
    assert (dispatch.transfer, dispatch.target) == (DISPATCH_TRANSFER_CICS, "")
    assert dispatch.reads == (HANDLER_ANY,)


def test_the_dispatch_node_has_no_outgoing_edge_of_its_own(program_of) -> None:
    """Control leaves for a handler paragraph, so the node ends its path -- exactly
    like a GO TO, and for the same reason."""
    cfg = _cfg(
        program_of,
        [
            _cics("RECEIVE MAP", {"MAP": {"text": "'MAPA'", "is_literal": True}}),
            {"type": "MOVE", "operands": [{"name": "'F'"}, {"name": "WS-RESULT"}]},
        ],
    )

    assert cfg.successors("MAIN/0#dispatch") == ()
    assert [e.kind for e in cfg.predecessors("MAIN/1")] == [EdgeKind.FALSE]


def test_nohandle_suppresses_the_raise_test(program_of) -> None:
    """NOHANDLE means the command cannot transfer control, so there is no fork here
    at all -- and a test node would make every following assignment read as
    conditional on nothing."""
    cfg = _cfg(
        program_of,
        [_cics("READ", {"FILE": {"text": "'CUSTFILE'", "is_literal": True}, "NOHANDLE": None})],
    )

    assert [n.kind for n in cfg.nodes if n.kind == NodeKind.TEST] == []


def test_a_resp_option_suppresses_the_raise_test_too(program_of) -> None:
    """RESP is the modern form of the same thing: the command sets a field instead
    of transferring, and the program tests that field itself -- which shows up as a
    real IF, so a synthetic fork here would double-count it."""
    cfg = _cfg(
        program_of,
        [
            _cics(
                "READ",
                {
                    "FILE": {"text": "'CUSTFILE'", "is_literal": True},
                    "RESP": {"text": "WS-RESP", "is_literal": False},
                },
            )
        ],
    )

    assert [n.kind for n in cfg.nodes if n.kind == NodeKind.TEST] == []


def test_arming_a_handler_is_not_itself_a_command_that_can_raise(program_of) -> None:
    cfg = _cfg(
        program_of,
        [_cics("HANDLE CONDITION", {"MAPFAIL": {"text": "9999-MAPFAIL", "is_literal": False}})],
    )

    assert len(cfg.nodes) == 1


def test_a_cics_commands_own_dataflow_is_still_read(program_of) -> None:
    """flows already knows what SEND MAP moves; the raise test is added around that
    answer, not instead of it."""
    cfg = _cfg(
        program_of,
        [
            _cics(
                "SEND MAP",
                {
                    "MAP": {"text": "'MAPA'", "is_literal": True},
                    "FROM": {"text": "WS-MAP-AREA", "is_literal": False},
                },
            )
        ],
    )

    assert cfg.node("MAIN/0").reads or cfg.node("MAIN/0").writes
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg/test_desugar_cics.py -v`
Expected: FAIL — `ImportError: cannot import name 'handler_field'`

- [ ] **Step 3: Write the implementation**

Add to `cobble/dataflow/srccfg/desugar.py`:

```python
IGNORED = "%IGNORE"
SYSTEM_DEFAULT = "%SYSTEM"
RAISED = "RAISED"
HANDLER_ANY = "%HANDLER[ANY]"
ARMING_VERBS = ("HANDLE CONDITION", "IGNORE CONDITION", "HANDLE AID")
SUPPRESSING_OPTIONS = ("NOHANDLE", "RESP", "RESP2")
DISPATCH_TRANSFER_CICS = "HANDLE DISPATCH"


def handler_field(condition: str) -> str:
    """The synthetic field a HANDLE CONDITION assigns to.

    Arming a handler is a definition, not a jump: the transfer happens later, at
    whichever command raises. Modelling it this way means PUSH HANDLE, re-arming in
    a loop, and "which handler is live here" are all reaching definitions over this
    field, with no separate handler model to keep consistent.
    """
    return f"%HANDLER[{condition}]"


def _exec_cics(statement, ctx: Ctx, path: str) -> Fragment:
    verb = str(getattr(statement, "verb", "") or "").upper()
    if verb in ARMING_VERBS:
        return _arm(statement, ctx, path, verb)
    body = _with_arms(statement, ctx, path, _plain_without_arms(statement, ctx, path))
    return body if _suppressed(statement) else _raisable(body, ctx, path)


def _arm(statement, ctx: Ctx, path: str, verb: str) -> Fragment:
    options = _handler_options(statement)
    return _one(
        Node(
            id=node_id(ctx, path),
            kind=NodeKind.ASSIGN,
            paragraph=ctx.paragraph,
            writes=tuple(handler_field(name) for name, _ in options),
            reads=_dedupe(_armed_value(value, verb) for _, value in options),
            transfer=verb,
        )
    )


def _handler_options(statement) -> tuple[tuple[str, object], ...]:
    return tuple(
        (name.upper(), value)
        for name, value in getattr(statement, "options", {}).items()
        if name.upper() not in SUPPRESSING_OPTIONS
    )


def _armed_value(value: object, verb: str) -> str:
    """A paragraph name when one is given; otherwise the marker for what the
    command means -- IGNORE CONDITION keeps control, a bare HANDLE CONDITION hands
    the condition back to CICS.

    ``value`` is a CicsOperand or None, so the text comes from the attribute. getattr
    with a default stands in for the banned ``is None`` check.
    """
    text = str(getattr(value, "text", "") or "")
    if text:
        return text.upper()
    return IGNORED if verb == "IGNORE CONDITION" else SYSTEM_DEFAULT


def _suppressed(statement) -> bool:
    names = tuple(name.upper() for name in getattr(statement, "options", {}))
    return any(name in SUPPRESSING_OPTIONS for name in names)


def _raisable(body: Fragment, ctx: Ctx, path: str) -> Fragment:
    """A command with no NOHANDLE and no RESP can transfer control to whichever
    handler is armed. The dispatch node's target is empty: filling it is a
    reaching-definitions question, and answering it here would need a second,
    order-dependent scan.
    """
    cond = _exits_of(
        Node(
            id=node_id(ctx, path, "#raise"),
            kind=NodeKind.TEST,
            paragraph=ctx.paragraph,
            atom=Atom(text=f"{HANDLER_ANY} {RAISED}", left=HANDLER_ANY, op="==", right=RAISED),
        )
    )
    dispatch = Node(
        id=node_id(ctx, path, "#dispatch"),
        kind=NodeKind.CALL,
        paragraph=ctx.paragraph,
        reads=(HANDLER_ANY,),
        transfer=DISPATCH_TRANSFER_CICS,
    )
    arms = _wire_arms(
        cond,
        Fragment(nodes=(dispatch,), edges=(), entry=dispatch.id, exits=()),
        EMPTY_FRAGMENT,
    )
    return seq((body, arms), nop_id=node_id(ctx, path, "#raise"))
```

Register `"ExecCicsStatement": _exec_cics`. Note `_armed_value`'s `isinstance`
guard: an option value is `None` as often as a mapping, and `is None` is banned, so
the mapping test is what stands in for it.

- [ ] **Step 4: Run the whole suite**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg -v`
Expected: PASS. If a fixture ever hands `_armed_value` a raw dict rather than a
`CicsOperand` — which happens only if a caller builds the statement by hand instead of
through `CobolASG.from_dict` — accept both:

```python
def _armed_value(value: object, verb: str) -> str:
    operand = value if hasattr(value, "text") else CicsOperand(text=str(_text_of(value)))
    ...
```

Prefer fixing the fixture. A production path that needs the dict branch means the
dialect parser did not run, which is the defect Task 11's `_cfg_of` guards against.

- [ ] **Step 5: Commit**

```bash
git add cobble/dataflow/srccfg/desugar.py tests/dataflow/srccfg/test_desugar_cics.py
git commit -m "$(cat <<'EOF'
feat(cobble): model CICS handler arming as an assignment

HANDLE CONDITION and IGNORE CONDITION write a synthetic %HANDLER[...] field, and a
command that can raise becomes a test on it plus a dispatch node whose target a
reaching-definitions pass fills in. NOHANDLE and RESP suppress the fork, because
those commands cannot transfer control and the program tests the response itself.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---
### Task 11: config, the corpus driver, and a build CLI

Everything so far builds one program from one ASG. This task turns that into a run
over a whole cached corpus: read a TOML config, walk the ASG cache directory, build a
CFG per member, write one JSON per member, and report per-member failures without
aborting. The failure discipline is the one the corpus build already uses — a member
that raises is a reported failure, not the end of the run.

The config carries no corpus-specific values in the repo: `config/srccfg.example.toml`
holds placeholder paths, and the real one is gitignored.

**Files:**
- Create: `cobble/dataflow/srccfg/config.py`
- Create: `cobble/dataflow/srccfg/build_corpus.py`
- Create: `config/srccfg.example.toml`
- Modify: `cobble/pyproject.toml` (`[project.scripts]`)
- Modify: `.gitignore`
- Test: `tests/dataflow/srccfg/test_config.py`
- Test: `tests/dataflow/srccfg/test_build_corpus.py`

**Interfaces:**
- Consumes: `build_program(asg) -> Cfg` (Task 7/8), `Cfg` (Task 1)
- Produces:
  - `SrcCfgConfig(asg_dir: Path, out_dir: Path)` — frozen
  - `load_srccfg_config(path: Path) -> SrcCfgConfig`
  - `_require(table: Mapping[str, object], key: str, source: Path) -> str`
  - `asg_paths(asg_dir: Path) -> tuple[Path, ...]`
  - `MemberResult(member: str, cfg_path: Path = ..., message: str = "")`
  - `build_one(path: Path, out_dir: Path) -> MemberResult`
  - `build_corpus(config: SrcCfgConfig) -> tuple[MemberResult, ...]`
  - `cfg_to_dict(cfg: Cfg) -> dict`
  - `main(argv: Sequence[str] | None = ...) -> int` — entry point `cobble-srccfg-build`

- [ ] **Step 1: Write the failing config tests**

`tests/dataflow/srccfg/test_config.py`:

```python
"""Config loading: every value required, nothing defaulted quietly.

A wrong path here does not fail -- it produces an empty run that reads exactly like
a corpus with no members, which is the expensive way to find out.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobble.dataflow.srccfg.config import SrcCfgConfig, load_srccfg_config


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_a_complete_config_loads_both_paths(tmp_path: Path) -> None:
    config = load_srccfg_config(
        _write(
            tmp_path / "srccfg.toml",
            f"""
[srccfg]
asg_dir = "{tmp_path}/parsed"
out_dir = "{tmp_path}/srccfg"
""",
        )
    )

    assert config == SrcCfgConfig(
        asg_dir=tmp_path / "parsed", out_dir=tmp_path / "srccfg"
    )


def test_a_missing_key_raises_and_names_the_key_and_the_file(tmp_path: Path) -> None:
    """No default: an asg_dir guessed from the cwd points at nothing and the run
    reports zero members, which is indistinguishable from success on an empty
    corpus."""
    path = _write(tmp_path / "srccfg.toml", '[srccfg]\nasg_dir = "/x"\n')

    with pytest.raises(KeyError) as caught:
        load_srccfg_config(path)

    assert "out_dir" in str(caught.value)
    assert str(path) in str(caught.value)


def test_an_empty_value_is_missing_rather_than_a_relative_path(tmp_path: Path) -> None:
    """out_dir = "" resolves to the cwd, and a run that writes 3,779 files into a
    repo root is worse than a run that refuses."""
    path = _write(tmp_path / "srccfg.toml", '[srccfg]\nasg_dir = "/x"\nout_dir = ""\n')

    with pytest.raises(KeyError):
        load_srccfg_config(path)


def test_a_config_with_no_srccfg_table_raises(tmp_path: Path) -> None:
    path = _write(tmp_path / "srccfg.toml", '[other]\nasg_dir = "/x"\n')

    with pytest.raises(KeyError) as caught:
        load_srccfg_config(path)

    assert "srccfg" in str(caught.value)


def test_a_path_is_expanded_so_a_tilde_config_is_not_a_literal_directory(
    tmp_path: Path,
) -> None:
    """~ in a hand-written TOML is the commonest way to create a directory called
    "~" in the repo."""
    config = load_srccfg_config(
        _write(
            tmp_path / "srccfg.toml",
            '[srccfg]\nasg_dir = "~/parsed"\nout_dir = "~/srccfg"\n',
        )
    )

    assert config.asg_dir == Path.home() / "parsed"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: cobble.dataflow.srccfg.config`

- [ ] **Step 3: Write `config.py`**

```python
"""Where the ASG cache is and where the CFGs go.

Both values are required. A silent default here buys nothing: the failure it hides
is a run that finds no members and reports success.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

TABLE = "srccfg"


@dataclass(frozen=True)
class SrcCfgConfig:
    asg_dir: Path
    out_dir: Path


def _require(table: Mapping[str, object], key: str, source: Path) -> str:
    value = str(table.get(key, ""))
    if value:
        return value
    raise KeyError(f"{source}: [{TABLE}] is missing a non-empty {key}")


def load_srccfg_config(path: Path) -> SrcCfgConfig:
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    table = document.get(TABLE, {})
    if not isinstance(table, Mapping):
        raise KeyError(f"{path}: [{TABLE}] must be a table")
    if not table:
        raise KeyError(f"{path}: no [{TABLE}] table")
    return SrcCfgConfig(
        asg_dir=_path_of(_require(table, "asg_dir", path)),
        out_dir=_path_of(_require(table, "out_dir", path)),
    )


def _path_of(text: str) -> Path:
    return Path(text).expanduser()
```

`config/srccfg.example.toml`:

```toml
# Copy to config/srccfg.toml and point at a parsed corpus. Both keys are required.
[srccfg]
# The directory cobble-parse-corpus wrote: one JSON ASG per member.
asg_dir = "/path/to/out-<corpus>-parsed"
# Where one CFG JSON per member goes.
out_dir = "/path/to/out-<corpus>-srccfg"
```

Add to `.gitignore` (skip any line already present):

```gitignore
config/srccfg.toml
config/srccfg-tests.toml
```

- [ ] **Step 4: Write the failing driver tests**

`tests/dataflow/srccfg/test_build_corpus.py`:

```python
"""One member's failure is a reported failure, not the end of a 3,779-member run.

The parse stage learned this the expensive way: an unguarded member aborted a run
that costs hours. A CFG pass over the cache is cheaper, but a run that dies on
member 40 still tells you nothing about the other 3,739.
"""

from __future__ import annotations

import json
from pathlib import Path

from cobble.dataflow.srccfg.build_corpus import (
    asg_paths,
    build_corpus,
    build_one,
    cfg_to_dict,
    main,
)
from cobble.dataflow.srccfg.config import SrcCfgConfig


def _asg(program: str) -> dict:
    return {
        "program_id": program,
        "paragraphs": [
            {
                "name": "MAIN",
                "statements": [
                    {"type": "MOVE", "operands": [{"name": "'A'"}, {"name": "WS-FLAG-A"}]}
                ],
            }
        ],
    }


def _cache(tmp_path: Path, *programs: str) -> Path:
    asg_dir = tmp_path / "parsed"
    asg_dir.mkdir(parents=True, exist_ok=True)
    for program in programs:
        (asg_dir / f"{program}.json").write_text(json.dumps(_asg(program)))
    return asg_dir


def test_the_cache_is_walked_in_a_stable_order(tmp_path: Path) -> None:
    """Sorted, so two runs produce diffable reports -- the report is read as a diff
    against the previous run to see whether a change moved the failure count."""
    asg_dir = _cache(tmp_path, "PROGB", "PROGA")

    assert [p.stem for p in asg_paths(asg_dir)] == ["PROGA", "PROGB"]


def test_a_non_json_file_in_the_cache_is_not_a_member(tmp_path: Path) -> None:
    asg_dir = _cache(tmp_path, "PROGA")
    (asg_dir / "notes.txt").write_text("hello")

    assert [p.stem for p in asg_paths(asg_dir)] == ["PROGA"]


def test_one_member_builds_to_one_json_named_for_the_program(tmp_path: Path) -> None:
    asg_dir = _cache(tmp_path, "PROGA")
    out_dir = tmp_path / "srccfg"

    result = build_one(asg_dir / "PROGA.json", out_dir)

    assert result.message == ""
    assert result.cfg_path == out_dir / "PROGA.json"
    assert json.loads(result.cfg_path.read_text())["program"] == "PROGA"


def test_the_written_json_carries_every_node_and_edge(tmp_path: Path) -> None:
    """The consumers of this file are later passes, so the round trip has to keep
    the node ids and the edge kinds -- those ARE the reaching condition."""
    asg_dir = _cache(tmp_path, "PROGA")

    written = json.loads(build_one(asg_dir / "PROGA.json", tmp_path / "out").cfg_path.read_text())

    assert [node["id"] for node in written["nodes"]] == ["MAIN#label", "MAIN/0", "MAIN#end"]
    assert {edge["kind"] for edge in written["edges"]} == {"FLOW"}


def test_a_member_that_does_not_parse_is_a_reported_failure(tmp_path: Path) -> None:
    asg_dir = _cache(tmp_path, "PROGA")
    (asg_dir / "BROKEN.json").write_text("{ not json")

    results = build_corpus(SrcCfgConfig(asg_dir=asg_dir, out_dir=tmp_path / "out"))

    failed = [r for r in results if r.message]
    assert [r.member for r in failed] == ["BROKEN"]
    assert (tmp_path / "out" / "PROGA.json").exists()


def test_the_failure_message_names_the_member_and_says_what_happened(
    tmp_path: Path,
) -> None:
    asg_dir = _cache(tmp_path)
    (asg_dir / "BROKEN.json").write_text("{ not json")

    results = build_corpus(SrcCfgConfig(asg_dir=asg_dir, out_dir=tmp_path / "out"))

    assert results[0].message.startswith("BROKEN: ")


def test_a_failing_member_writes_no_partial_cfg(tmp_path: Path) -> None:
    """A half-written CFG is worse than none: the next pass cannot tell it from a
    member that genuinely has three nodes."""
    asg_dir = _cache(tmp_path)
    (asg_dir / "BROKEN.json").write_text("{ not json")

    build_corpus(SrcCfgConfig(asg_dir=asg_dir, out_dir=tmp_path / "out"))

    assert list((tmp_path / "out").glob("*.json")) == []


def test_the_cli_reports_counts_and_exits_zero_when_every_member_built(
    tmp_path: Path, caplog
) -> None:
    import logging

    caplog.set_level(logging.INFO)
    asg_dir = _cache(tmp_path, "PROGA", "PROGB")
    config = tmp_path / "srccfg.toml"
    config.write_text(f'[srccfg]\nasg_dir = "{asg_dir}"\nout_dir = "{tmp_path}/out"\n')

    assert main(["--config", str(config)]) == 0
    assert "2" in caplog.text


def test_the_cli_exits_non_zero_when_any_member_failed(tmp_path: Path) -> None:
    """A pass whose output is consumed by later passes must not report success while
    silently missing members -- the next pass would read the gap as "this field is
    never written"."""
    asg_dir = _cache(tmp_path, "PROGA")
    (asg_dir / "BROKEN.json").write_text("{ not json")
    config = tmp_path / "srccfg.toml"
    config.write_text(f'[srccfg]\nasg_dir = "{asg_dir}"\nout_dir = "{tmp_path}/out"\n')

    assert main(["--config", str(config)]) == 1


def test_the_cli_does_not_print_member_names_to_stdout(tmp_path: Path, capsys) -> None:
    """Member names are corpus identifiers. The failure report is a log record, so a
    run in a shared terminal does not leak them, and stdout stays free for a machine
    channel."""
    asg_dir = _cache(tmp_path, "PROGA")
    config = tmp_path / "srccfg.toml"
    config.write_text(f'[srccfg]\nasg_dir = "{asg_dir}"\nout_dir = "{tmp_path}/out"\n')

    main(["--config", str(config)])

    assert capsys.readouterr().out == ""


def test_cfg_to_dict_is_json_serialisable_without_a_custom_encoder(tmp_path: Path) -> None:
    """Enums and frozen dataclasses are not JSON by themselves, and a default=str
    encoder would write "EdgeKind.TRUE" -- which no reader can round-trip."""
    from cobble.dataflow.srccfg.cfg import Cfg, EdgeKind, Edge, Node, NodeKind

    cfg = Cfg(
        program="PROGA",
        nodes=(Node(id="MAIN/0", kind=NodeKind.NOP, paragraph="MAIN"),),
        edges=(Edge(source="MAIN/0", target="MAIN/0", kind=EdgeKind.TRUE),),
    )

    assert json.loads(json.dumps(cfg_to_dict(cfg)))["edges"][0]["kind"] == "TRUE"
```

- [ ] **Step 5: Write `build_corpus.py`**

```python
"""Build one CFG per cached ASG.

No JVM: the ASG cache is the whole input. A member that raises is reported and the
run continues, because the answer wanted from a corpus pass is "which members are
missing from this output", and a run that aborts answers that for one member only.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from cobol_asg.asg_types import CobolASG
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered

from cobble.dataflow.srccfg.build import build_program
from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.config import SrcCfgConfig, load_srccfg_config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemberResult:
    member: str
    cfg_path: Path = Path()
    message: str = ""


def asg_paths(asg_dir: Path) -> tuple[Path, ...]:
    return tuple(sorted(asg_dir.glob("*.json")))


def cfg_to_dict(cfg: Cfg) -> dict:
    """Plain JSON: enum members become their names, so a reader needs no import of
    this package to interpret an edge."""
    return {
        "program": cfg.program,
        "nodes": [_node_dict(node) for node in cfg.nodes],
        "edges": [
            {"source": e.source, "target": e.target, "kind": e.kind.name}
            for e in cfg.edges
        ],
    }


def _node_dict(node) -> dict:
    body = asdict(node)
    return {**body, "kind": node.kind.name}


def build_one(path: Path, out_dir: Path) -> MemberResult:
    member = path.stem
    try:
        cfg = _cfg_of(path)
    except Exception as error:  # noqa: BLE001 - one member must not end the run
        return MemberResult(member=member, message=f"{member}: {error!r}")
    out_dir.mkdir(parents=True, exist_ok=True)
    written = out_dir / f"{cfg.program or member}.json"
    written.write_text(json.dumps(cfg_to_dict(cfg)), encoding="utf-8")
    return MemberResult(member=member, cfg_path=written)


def _cfg_of(path: Path) -> Cfg:
    with cached_asg_dialect_parsers_registered():
        asg = CobolASG.from_dict(json.loads(path.read_text(encoding="utf-8")))
    return build_program(asg)


def build_corpus(config: SrcCfgConfig) -> tuple[MemberResult, ...]:
    return tuple(
        build_one(path, config.out_dir) for path in asg_paths(config.asg_dir)
    )


def main(argv: Sequence[str] = ()) -> int:
    parser = argparse.ArgumentParser(description="Build a source CFG per cached ASG.")
    parser.add_argument("--config", required=True, type=Path)
    arguments = parser.parse_args(tuple(argv) or None)
    results = build_corpus(load_srccfg_config(arguments.config))
    failures = tuple(r.message for r in results if r.message)
    logger.info("Built %d CFG(s), %d failure(s)", len(results) - len(failures), len(failures))
    for message in failures:
        logger.error("  - %s", message)
    return 1 if failures else 0
```

`_cfg_of` opens the dialect registry because a member with `EXEC CICS` is otherwise
`Unknown COBOL statement type: 'EXEC_CICS'` — 2,129 of 3,779 members on the
onboarding corpus, and the same defect the FILE-CONTROL stage had.

`main(argv=())` rather than a `None` default keeps the fp ban on `None` defaults, and
`tuple(argv) or None` is what makes a bare `cobble-srccfg-build` read `sys.argv`.

Add to `cobble/pyproject.toml`, in the existing `[project.scripts]` table beside
`cobble-parse-corpus` and `cobble-depgraph`:

```toml
cobble-srccfg-build = "cobble.dataflow.srccfg.build_corpus:main"
```

- [ ] **Step 6: Run the suite and the gates**

```bash
cd cobble
uv run --no-sync python -m pytest tests/dataflow/srccfg -v
uv run --no-sync python -m python_fp_lint check cobble/dataflow/srccfg/
make lint
```

Expected: tests PASS, zero new fp-lint violations. The broad `except Exception` needs
the `noqa: BLE001` shown; if `make lint` still objects, narrow it to
`(ValueError, KeyError, AttributeError, TypeError, json.JSONDecodeError)` — but keep
`Exception` if the corpus run then dies on a member, because the point of the guard is
the failures nobody predicted.

- [ ] **Step 7: Commit**

```bash
git add cobble/dataflow/srccfg/config.py cobble/dataflow/srccfg/build_corpus.py \
  config/srccfg.example.toml cobble/pyproject.toml .gitignore \
  tests/dataflow/srccfg/test_config.py tests/dataflow/srccfg/test_build_corpus.py
git commit -m "$(cat <<'EOF'
feat(cobble): build a source CFG for every cached ASG

Reads the parsed-ASG cache, writes one CFG JSON per member, and reports a member
that raises instead of ending the run. Both config keys are required: a defaulted
asg_dir produces an empty run that reads exactly like success.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---
### Task 12: reaching conditions, with perform and return edges matched

The CFG is now complete enough to walk. A **reaching condition** for a node is the
sequence of `(test node id, edge polarity)` pairs along one path from the entry to
that node; a node's answer is the tuple of such sequences, one per path. That is the
whole condition language — no normal form, no solver, and negation is already an edge
polarity rather than a term.

Two things make the walk finite and honest:

- **No node repeats on a path.** A loop body is visited once, so `PERFORM UNTIL`
  yields the guard for entering the body and the guard for skipping it, not an
  unbounded family. A path that would revisit a node stops.
- **PERFORM returns are matched.** `perform` edges push the call node; a `return`
  edge is followed only when it matches the top of that stack. Without this, a
  paragraph PERFORMed from four places has every one of its return edges taken from
  every call, and the guard sets multiply into nonsense.

The walk is capped. `MAX_PATHS` bounds the tuple per node, and a node that hit the cap
is named in `truncated` — an unreported truncation would read as "this assignment is
reached under exactly these three conditions", which is a claim the walk did not
establish.

**Files:**
- Create: `cobble/dataflow/srccfg/dataflow.py`
- Test: `tests/dataflow/srccfg/test_reaching.py`

**Interfaces:**
- Consumes: `Cfg`, `Node`, `Edge`, `EdgeKind`, `NodeKind` (Task 1);
  `PERFORM_TRANSFER`, `GOTO_TRANSFER` (Task 8/7); `IMPLICIT_FIRST`, `label_id` (Task 7)
- Produces:
  - `Guard = tuple[tuple[str, EdgeKind], ...]`
  - `MAX_PATHS = 64`
  - `Walk(node: str, guard: Guard, stack: tuple[str, ...], seen: frozenset[str])`
  - `Reaching(guards: Mapping[str, tuple[Guard, ...]], truncated: frozenset[str])`
  - `reaching_conditions(cfg: Cfg, max_paths: int = MAX_PATHS) -> Reaching`
  - `guards_of(reaching: Reaching, node_id: str) -> tuple[Guard, ...]`
  - `guard_set(guard: Guard) -> frozenset[tuple[str, EdgeKind]]`
  - `guard_text(cfg: Cfg, guard: Guard) -> tuple[str, ...]`
  - `entry_of(cfg: Cfg) -> str`

- [ ] **Step 1: Write the failing tests**

`tests/dataflow/srccfg/test_reaching.py`:

```python
"""A node's reaching conditions are the guards along the paths that reach it.

The measured failure this replaces was a guard stack: it negated a two-clause AND as
NOT A AND NOT B, so the ELSE arm of the commonest COBOL shape got a condition no
input satisfies. Here negation is an edge polarity, so the same shape comes out as
two paths -- which is what NOT (A AND B) means.
"""

from __future__ import annotations

import json

from cobol_asg.asg_types import CobolASG
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered

from cobble.dataflow.srccfg.build import build_program
from cobble.dataflow.srccfg.cfg import EdgeKind, NodeKind
from cobble.dataflow.srccfg.dataflow import (
    MAX_PATHS,
    guard_set,
    guard_text,
    guards_of,
    reaching_conditions,
)


def _asg(paragraphs: list[dict]) -> CobolASG:
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict(
            json.loads(json.dumps({"program_id": "PROGA", "paragraphs": paragraphs}))
        )


def _move(value: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": value}, {"name": target}]}


def _if(condition: dict, then: list[dict], otherwise: list[dict]) -> dict:
    return {
        "type": "IF",
        "condition": condition,
        "then_statements": then,
        "else_statements": otherwise,
    }


def _rel(left: str, op: str, right: str) -> dict:
    return {"kind": "relation", "left": left, "operator": op, "right": right}


def _and(left: dict, right: dict) -> dict:
    return {"kind": "and", "left": left, "right": right}


def _writer_of(cfg, field: str) -> str:
    return next(node.id for node in cfg.nodes if field in node.writes)


def test_an_unguarded_assignment_has_one_empty_guard() -> None:
    """65% of a corpus's assignments carry a guard, which means 35% do not -- and an
    empty tuple of paths would say "unreachable", the opposite claim."""
    cfg = build_program(_asg([{"name": "MAIN", "statements": [_move("'A'", "WS-FLAG-A")]}]))

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-FLAG-A")) == ((),)


def test_an_assignment_in_a_then_arm_carries_the_true_polarity() -> None:
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _if(_rel("WS-FLAG-A", "=", "'Y'"), [_move("'A'", "WS-RESULT")], [])
                    ],
                }
            ]
        )
    )

    reaching = reaching_conditions(cfg)
    (guard,) = guards_of(reaching, _writer_of(cfg, "WS-RESULT"))

    assert [kind for _, kind in guard] == [EdgeKind.TRUE]


def test_the_else_arm_of_a_two_clause_and_is_reached_by_two_paths() -> None:
    """The whole point. NOT (A AND B) is NOT A OR NOT B, and an OR is two paths --
    so this node has two guards, each with a single FALSE, not one guard with two.
    """
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _if(
                            _and(_rel("WS-FLAG-A", "=", "'Y'"), _rel("WS-FLAG-B", "=", "'Y'")),
                            [_move("'A'", "WS-TAKEN")],
                            [_move("'B'", "WS-SKIPPED")],
                        )
                    ],
                }
            ]
        )
    )

    reaching = reaching_conditions(cfg)
    guards = guards_of(reaching, _writer_of(cfg, "WS-SKIPPED"))

    assert sorted(len(guard) for guard in guards) == [1, 2]
    assert all(guard[-1][1] == EdgeKind.FALSE for guard in guards)


def test_the_then_arm_of_a_two_clause_and_is_reached_by_one_path_of_two_tests() -> None:
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _if(
                            _and(_rel("WS-FLAG-A", "=", "'Y'"), _rel("WS-FLAG-B", "=", "'Y'")),
                            [_move("'A'", "WS-TAKEN")],
                            [],
                        )
                    ],
                }
            ]
        )
    )

    reaching = reaching_conditions(cfg)
    (guard,) = guards_of(reaching, _writer_of(cfg, "WS-TAKEN"))

    assert [kind for _, kind in guard] == [EdgeKind.TRUE, EdgeKind.TRUE]


def test_a_statement_after_the_if_is_reached_under_every_arm() -> None:
    """A node whose guards include the empty-difference pair is unconditional in
    effect. Reporting it as guarded is the noise that makes a derivation unreadable.
    """
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _if(_rel("WS-FLAG-A", "=", "'Y'"), [_move("'A'", "WS-X")], []),
                        _move("'B'", "WS-AFTER"),
                    ],
                }
            ]
        )
    )

    reaching = reaching_conditions(cfg)

    assert len(guards_of(reaching, _writer_of(cfg, "WS-AFTER"))) == 2


def test_a_performed_paragraph_carries_the_guard_of_the_call_site() -> None:
    """This is why a per-paragraph analysis is not enough: the assignment is
    unconditional where it is written and conditional in every run."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _if(
                            _rel("WS-FLAG-A", "=", "'Y'"),
                            [{"type": "PERFORM", "target": "SET-IT"}],
                            [],
                        )
                    ],
                },
                {"name": "SET-IT", "statements": [_move("'A'", "WS-RESULT")]},
            ]
        )
    )

    reaching = reaching_conditions(cfg)
    guards = guards_of(reaching, _writer_of(cfg, "WS-RESULT"))

    assert any(EdgeKind.TRUE in {kind for _, kind in guard} for guard in guards)


def test_a_return_edge_is_only_taken_back_to_its_own_call_site() -> None:
    """A paragraph PERFORMed twice has two return edges. Following the wrong one
    joins the guard of call site A to everything after call site B, and on a corpus
    where a paragraph is performed from a dozen places that is where the guard sets
    stop meaning anything.
    """
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _if(
                            _rel("WS-FLAG-A", "=", "'Y'"),
                            [{"type": "PERFORM", "target": "SET-IT"}, _move("'1'", "WS-AFTER-A")],
                            [{"type": "PERFORM", "target": "SET-IT"}, _move("'2'", "WS-AFTER-B")],
                        )
                    ],
                },
                {"name": "SET-IT", "statements": [_move("'A'", "WS-RESULT")]},
            ]
        )
    )

    reaching = reaching_conditions(cfg)

    assert [kind for _, kind in guards_of(reaching, _writer_of(cfg, "WS-AFTER-A"))[0]] == [
        EdgeKind.TRUE
    ]
    assert [kind for _, kind in guards_of(reaching, _writer_of(cfg, "WS-AFTER-B"))[0]] == [
        EdgeKind.FALSE
    ]


def test_a_paragraph_reached_only_by_a_goto_still_gets_guards() -> None:
    """11% of paragraphs on a real corpus are never PERFORMed and hold 5% of the
    assignments. A walk that only followed perform edges would report them
    unreachable and lose those definitions."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _if(
                            _rel("WS-FLAG-A", "=", "'Y'"),
                            [{"type": "GOTO", "form": {"kind": "simple", "target": "LAND"}}],
                            [],
                        )
                    ],
                },
                {"name": "LAND", "statements": [_move("'A'", "WS-RESULT")]},
            ]
        )
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-RESULT"))


def test_a_loop_body_is_walked_once_rather_than_forever() -> None:
    """No node repeats on a path, so a PERFORM UNTIL terminates. The answer wanted
    is "under what condition does this run at all", not one guard per iteration."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        {
                            "type": "PERFORM",
                            "target": "STEP",
                            "spec": {
                                "kind": "until",
                                "condition": _rel("WS-FLAG-A", "=", "'Y'"),
                                "test_before": True,
                            },
                        }
                    ],
                },
                {"name": "STEP", "statements": [_move("'A'", "WS-RESULT")]},
            ]
        )
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-RESULT"))


def test_a_node_that_hit_the_path_cap_is_named_as_truncated() -> None:
    """A silently capped answer is a wrong answer with no warning: it reads as a
    complete list of the conditions under which a field is written."""
    ifs = [
        _if(_rel(f"WS-FLAG-{n}", "=", "'Y'"), [_move("'A'", f"WS-X{n}")], [])
        for n in range(12)
    ]
    cfg = build_program(
        _asg([{"name": "MAIN", "statements": [*ifs, _move("'Z'", "WS-LAST")]}])
    )

    reaching = reaching_conditions(cfg, max_paths=8)

    assert len(guards_of(reaching, _writer_of(cfg, "WS-LAST"))) <= 8
    assert _writer_of(cfg, "WS-LAST") in reaching.truncated


def test_the_default_cap_is_the_documented_constant() -> None:
    assert MAX_PATHS == 64


def test_guard_set_drops_order_so_two_orders_of_the_same_tests_compare_equal() -> None:
    """Co-assignment asks whether two writes are guarded the same way, and the order
    two independent tests were written in is not part of that question."""
    guard_a = (("MAIN/0#test", EdgeKind.TRUE), ("MAIN/1#test", EdgeKind.FALSE))
    guard_b = (("MAIN/1#test", EdgeKind.FALSE), ("MAIN/0#test", EdgeKind.TRUE))

    assert guard_set(guard_a) == guard_set(guard_b)


def test_guard_text_renders_a_polarity_as_a_readable_predicate() -> None:
    """The rendering is what a human reads in a derivation, so a FALSE edge has to
    say NOT rather than showing the atom that was tested with no polarity at all."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _if(_rel("WS-FLAG-A", "=", "'Y'"), [], [_move("'B'", "WS-RESULT")])
                    ],
                }
            ]
        )
    )
    reaching = reaching_conditions(cfg)
    (guard,) = guards_of(reaching, _writer_of(cfg, "WS-RESULT"))

    rendered = guard_text(cfg, guard)

    assert len(rendered) == 1
    assert rendered[0].startswith("NOT ")
    assert "WS-FLAG-A" in rendered[0]


def test_a_test_node_records_the_guards_that_reach_it_not_its_own_polarity() -> None:
    """A test's own answer is not known until it runs, so its guard is what reached
    it -- otherwise every nested test would double-count itself."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _if(
                            _rel("WS-FLAG-A", "=", "'Y'"),
                            [_if(_rel("WS-FLAG-B", "=", "'Y'"), [_move("'A'", "WS-X")], [])],
                            [],
                        )
                    ],
                }
            ]
        )
    )

    reaching = reaching_conditions(cfg)
    inner = next(
        node
        for node in cfg.nodes
        if node.kind == NodeKind.TEST and "WS-FLAG-B" in node.atom.text
    )

    assert [kind for _, kind in guards_of(reaching, inner.id)[0]] == [EdgeKind.TRUE]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg/test_reaching.py -v`
Expected: FAIL — `ModuleNotFoundError: cobble.dataflow.srccfg.dataflow`

- [ ] **Step 3: Write `dataflow.py`**

```python
"""Reaching conditions: the guards along the paths that reach each node.

The condition language is the CFG. A guard is a sequence of (test, polarity) pairs,
and negation is the polarity -- which is why the ELSE arm of `A AND B` comes out as
two paths rather than as one impossible conjunction.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from itertools import chain

from cobble.dataflow.srccfg.cfg import Cfg, Edge, EdgeKind, NodeKind
from cobble.dataflow.srccfg.build import IMPLICIT_FIRST, label_id

Guard = tuple[tuple[str, EdgeKind], ...]

MAX_PATHS = 64


@dataclass(frozen=True)
class Walk:
    node: str
    guard: Guard = ()
    stack: tuple[str, ...] = ()
    seen: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Reaching:
    guards: Mapping[str, tuple[Guard, ...]] = field(default_factory=dict)
    truncated: frozenset[str] = frozenset()


def entry_of(cfg: Cfg) -> str:
    """The first node the program runs: the implicit paragraph when the source has
    statements before its first paragraph, else the first label."""
    implicit = label_id(IMPLICIT_FIRST)
    return implicit if implicit in cfg.node_ids else _first_id(cfg)


def _first_id(cfg: Cfg) -> str:
    return cfg.nodes[0].id if cfg.nodes else ""


def reaching_conditions(cfg: Cfg, max_paths: int = MAX_PATHS) -> Reaching:
    found: dict[str, tuple[Guard, ...]] = {}
    capped: set[str] = set()
    pending = (Walk(node=entry_of(cfg)),) if cfg.nodes else ()
    while pending:
        walk, pending = pending[0], pending[1:]
        known = found.get(walk.node, ())
        if len(known) >= max_paths:
            capped.add(walk.node)
            continue
        found[walk.node] = (*known, walk.guard)
        pending = (*pending, *_next_walks(cfg, walk))
    return Reaching(guards=found, truncated=frozenset(capped))


def _next_walks(cfg: Cfg, walk: Walk) -> tuple[Walk, ...]:
    seen = walk.seen | {walk.node}
    return tuple(
        _advance(walk, edge, seen)
        for edge in cfg.successors(walk.node)
        if edge.target not in seen and _passable(walk, edge)
    )


def _passable(walk: Walk, edge: Edge) -> bool:
    """A return edge belongs to one call site. Following another's joins that call
    site's guard onto this path, and a paragraph performed from a dozen places turns
    every guard set into a union of all of them."""
    if edge.kind != EdgeKind.RETURN:
        return True
    return bool(walk.stack) and walk.stack[-1] == edge.target


def _advance(walk: Walk, edge: Edge, seen: frozenset[str]) -> Walk:
    return Walk(
        node=edge.target,
        guard=_extended(walk, edge),
        stack=_stack(walk, edge),
        seen=seen,
    )


def _extended(walk: Walk, edge: Edge) -> Guard:
    if edge.kind in (EdgeKind.TRUE, EdgeKind.FALSE):
        return (*walk.guard, (edge.source, edge.kind))
    return walk.guard


def _stack(walk: Walk, edge: Edge) -> tuple[str, ...]:
    if edge.kind == EdgeKind.PERFORM:
        return (*walk.stack, edge.source)
    if edge.kind == EdgeKind.RETURN:
        return walk.stack[:-1]
    return walk.stack


def guards_of(reaching: Reaching, node_id: str) -> tuple[Guard, ...]:
    return reaching.guards.get(node_id, ())


def guard_set(guard: Guard) -> frozenset[tuple[str, EdgeKind]]:
    return frozenset(guard)


def guard_text(cfg: Cfg, guard: Guard) -> tuple[str, ...]:
    return tuple(_term(cfg, node_id, kind) for node_id, kind in guard)


def _term(cfg: Cfg, node_id: str, kind: EdgeKind) -> str:
    text = cfg.node(node_id).atom.text
    return text if kind == EdgeKind.TRUE else f"NOT ({text})"
```

Two notes for whoever runs this:

- The `RETURN` edge check compares `edge.target` to the stack top, which works
  because Task 8 attaches a paragraph's return edges to the FLOW successor of the
  call node, and pushes `edge.source` — the paragraph's `#end`. If the tests show
  the stack never matching, the mismatch is between what `_stack` pushes and what
  `_passable` compares; push the call node id in `_stack` and store the mapping from
  return-edge target to call node in `build.py` rather than guessing here.
- The while loop is a queue, so the guards come out breadth-first and the shortest
  path to a node is first in its tuple. That is what makes a truncated answer still
  useful: the guards that survive the cap are the short ones.

- [ ] **Step 4: Run the suite and the gates**

```bash
cd cobble
uv run --no-sync python -m pytest tests/dataflow/srccfg -v
uv run --no-sync python -m python_fp_lint check cobble/dataflow/srccfg/
make lint
```

Expected: PASS with zero new violations. If the queue is slow enough to matter on a
real member, the fix is a `deque` — but measure first: the cap bounds the work per
node, so the total is `nodes * max_paths`, and a 2,000-node member at 64 is small.
`chain` is unused until Task 13 and `Iterable` may stay unused; if `make lint` flags
them now, add them back with Task 13 rather than fighting the import.

- [ ] **Step 5: Commit**

```bash
git add cobble/dataflow/srccfg/dataflow.py tests/dataflow/srccfg/test_reaching.py
git commit -m "$(cat <<'EOF'
feat(cobble): compute reaching conditions over the source CFG

A guard is a sequence of (test, edge polarity) pairs along one path, so negation is
the polarity and the ELSE arm of a conjunction comes out as two paths rather than as
one unsatisfiable conjunction. Return edges are matched to their own call site, and a
node that hits the path cap is reported as truncated rather than answered short.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---
### Task 13: reaching definitions, def-use pairs, and live handlers

Guards say *when* a node runs. Reaching definitions say *which write* a read sees. The
two together are what "how is this field derived" needs: the chain of writes back to a
source, each with the condition it happened under.

This is a classic gen/kill fixpoint over the CFG, deliberately **not** the path walk
from Task 12 — a fixpoint is order-insensitive and linear-ish, where a per-path answer
would multiply the same definition by every guard that reaches it. Guards stay a
separate lookup, joined at query time.

The fixpoint also answers the `%HANDLER[…]` question Task 10 deferred: a dispatch node
reads `%HANDLER[ANY]`, the definitions of any `%HANDLER[…]` that reach it are the live
handlers, and their read values are the paragraphs control can go to. So `PUSH HANDLE`,
re-arming in a loop, and a handler armed on one arm only all come out of machinery
that already exists.

**Files:**
- Modify: `cobble/dataflow/srccfg/dataflow.py`
- Test: `tests/dataflow/srccfg/test_reaching_definitions.py`
- Test: `tests/dataflow/srccfg/test_handlers.py`

**Interfaces:**
- Consumes: `Cfg`, `Edge`, `EdgeKind`, `NodeKind` (Task 1); `entry_of` (Task 12);
  `handler_field`, `IGNORED`, `SYSTEM_DEFAULT`, `HANDLER_ANY`,
  `DISPATCH_TRANSFER_CICS` (Task 10)
- Produces:
  - `Definition(node: str, field: str)` — frozen, hashable
  - `Defs = frozenset[Definition]`
  - `reaching_definitions(cfg: Cfg) -> Mapping[str, Defs]` — defs reaching each node's
    *entry*, so a node's own write is not in its own in-set
  - `definitions_of(cfg: Cfg) -> Mapping[str, Defs]` — the gen set per node
  - `Use(node: str, field: str, definitions: Defs)`
  - `def_use(cfg: Cfg) -> tuple[Use, ...]`
  - `writers_of(cfg: Cfg, field: str) -> tuple[str, ...]`
  - `HANDLER_PREFIX = "%HANDLER["`
  - `live_handlers(cfg: Cfg) -> Mapping[str, tuple[str, ...]]` — dispatch node id to
    paragraph names
  - `with_handler_edges(cfg: Cfg) -> Cfg`

- [ ] **Step 1: Write the failing reaching-definitions tests**

`tests/dataflow/srccfg/test_reaching_definitions.py`:

```python
"""Which write does a read see.

A gen/kill fixpoint rather than a per-path walk: the same definition reached by four
paths is one definition, and answering per path would report it four times with four
guards -- guards are a separate lookup, joined when a query asks for them.
"""

from __future__ import annotations

import json

from cobol_asg.asg_types import CobolASG
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered

from cobble.dataflow.srccfg.build import build_program
from cobble.dataflow.srccfg.dataflow import (
    Definition,
    def_use,
    definitions_of,
    reaching_definitions,
    writers_of,
)


def _asg(paragraphs: list[dict]) -> CobolASG:
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict({"program_id": "PROGA", "paragraphs": paragraphs})


def _move(value: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": value}, {"name": target}]}


def _if(condition: dict, then: list[dict], otherwise: list[dict]) -> dict:
    return {
        "type": "IF",
        "condition": condition,
        "then_statements": then,
        "else_statements": otherwise,
    }


def _rel(left: str, op: str, right: str) -> dict:
    return {"kind": "relation", "left": left, "operator": op, "right": right}


def _fields_of(uses, field: str):
    return next(use for use in uses if use.field == field)


def test_a_write_is_a_definition_at_its_own_node() -> None:
    cfg = build_program(_asg([{"name": "MAIN", "statements": [_move("'A'", "WS-FLAG-A")]}]))

    generated = definitions_of(cfg)

    assert Definition(node="MAIN/0", field="WS-FLAG-A") in generated["MAIN/0"]


def test_a_nodes_own_write_does_not_reach_its_own_entry() -> None:
    """The in-set is what a read on this node sees, and MOVE WS-X TO WS-X must read
    the previous write, not itself."""
    cfg = build_program(_asg([{"name": "MAIN", "statements": [_move("'A'", "WS-FLAG-A")]}]))

    assert reaching_definitions(cfg)["MAIN/0"] == frozenset()


def test_a_later_read_sees_the_earlier_write() -> None:
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_move("'A'", "WS-FLAG-A"), _move("WS-FLAG-A", "WS-RESULT")],
                }
            ]
        )
    )

    assert Definition(node="MAIN/0", field="WS-FLAG-A") in reaching_definitions(cfg)["MAIN/1"]


def test_a_second_write_on_the_same_path_kills_the_first() -> None:
    """Without the kill, a derivation lists every write to a field ever, and the
    commonest COBOL shape -- initialise then overwrite -- reads as two sources."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _move("'A'", "WS-FLAG-A"),
                        _move("'B'", "WS-FLAG-A"),
                        _move("WS-FLAG-A", "WS-RESULT"),
                    ],
                }
            ]
        )
    )

    reaching = reaching_definitions(cfg)["MAIN/2"]

    assert Definition(node="MAIN/1", field="WS-FLAG-A") in reaching
    assert Definition(node="MAIN/0", field="WS-FLAG-A") not in reaching


def test_a_write_on_one_arm_only_does_not_kill_the_write_before_the_if() -> None:
    """The join is a union, so a read after a conditional overwrite sees both -- and
    the question "which one" is what the guards answer."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _move("'A'", "WS-FLAG-A"),
                        _if(_rel("WS-OTHER", "=", "'Y'"), [_move("'B'", "WS-FLAG-A")], []),
                        _move("WS-FLAG-A", "WS-RESULT"),
                    ],
                }
            ]
        )
    )
    reader = next(node.id for node in cfg.nodes if "WS-RESULT" in node.writes)

    fields = {d.field for d in reaching_definitions(cfg)[reader]}
    writers = {d.node for d in reaching_definitions(cfg)[reader] if d.field == "WS-FLAG-A"}

    assert "WS-FLAG-A" in fields
    assert len(writers) == 2


def test_a_write_on_both_arms_kills_the_write_before_the_if() -> None:
    """A kill on every path is a kill, and reporting the pre-IF write here would put
    a dead source in every derivation of this field."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _move("'A'", "WS-FLAG-A"),
                        _if(
                            _rel("WS-OTHER", "=", "'Y'"),
                            [_move("'B'", "WS-FLAG-A")],
                            [_move("'C'", "WS-FLAG-A")],
                        ),
                        _move("WS-FLAG-A", "WS-RESULT"),
                    ],
                }
            ]
        )
    )
    reader = next(node.id for node in cfg.nodes if "WS-RESULT" in node.writes)

    writers = {d.node for d in reaching_definitions(cfg)[reader] if d.field == "WS-FLAG-A"}

    assert "MAIN/0" not in writers
    assert len(writers) == 2


def test_a_definition_reaches_a_performed_paragraph() -> None:
    """The whole reason this is a program-level pass: the write and the read are in
    different paragraphs, and 65% of the interesting ones are."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _move("'A'", "WS-FLAG-A"),
                        {"type": "PERFORM", "target": "USE-IT"},
                    ],
                },
                {"name": "USE-IT", "statements": [_move("WS-FLAG-A", "WS-RESULT")]},
            ]
        )
    )
    reader = next(node.id for node in cfg.nodes if "WS-RESULT" in node.writes)

    assert Definition(node="MAIN/0", field="WS-FLAG-A") in reaching_definitions(cfg)[reader]


def test_a_write_inside_a_performed_paragraph_reaches_after_the_call() -> None:
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        {"type": "PERFORM", "target": "SET-IT"},
                        _move("WS-FLAG-A", "WS-RESULT"),
                    ],
                },
                {"name": "SET-IT", "statements": [_move("'A'", "WS-FLAG-A")]},
            ]
        )
    )
    reader = next(node.id for node in cfg.nodes if "WS-RESULT" in node.writes)

    assert {d.node for d in reaching_definitions(cfg)[reader] if d.field == "WS-FLAG-A"} == {
        "SET-IT/0"
    }


def test_a_loop_reaches_a_fixpoint_rather_than_iterating_forever() -> None:
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        {
                            "type": "PERFORM",
                            "target": "STEP",
                            "spec": {
                                "kind": "until",
                                "condition": _rel("WS-FLAG-A", "=", "'Y'"),
                                "test_before": True,
                            },
                        }
                    ],
                },
                {
                    "name": "STEP",
                    "statements": [_move("WS-FLAG-A", "WS-PREV"), _move("'Y'", "WS-FLAG-A")],
                },
            ]
        )
    )

    assert reaching_definitions(cfg)


def test_def_use_pairs_name_the_field_and_every_definition_that_reaches_it() -> None:
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_move("'A'", "WS-FLAG-A"), _move("WS-FLAG-A", "WS-RESULT")],
                }
            ]
        )
    )

    use = _fields_of(def_use(cfg), "WS-FLAG-A")

    assert use.node == "MAIN/1"
    assert use.definitions == frozenset({Definition(node="MAIN/0", field="WS-FLAG-A")})


def test_a_read_with_no_definition_is_still_a_use_with_an_empty_set() -> None:
    """An empty set is the answer for a field written by the caller, by a file read,
    or in a copybook VALUE clause -- and dropping the use would hide it entirely."""
    cfg = build_program(
        _asg([{"name": "MAIN", "statements": [_move("WS-FROM-CALLER", "WS-RESULT")]}])
    )

    assert _fields_of(def_use(cfg), "WS-FROM-CALLER").definitions == frozenset()


def test_writers_of_lists_every_node_that_writes_a_field_in_source_order() -> None:
    """The first query anyone asks. Source order, because a reader compares it
    against the listing."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_move("'A'", "WS-FLAG-A"), _move("'B'", "WS-FLAG-A")],
                }
            ]
        )
    )

    assert writers_of(cfg, "WS-FLAG-A") == ("MAIN/0", "MAIN/1")
```

- [ ] **Step 2: Write the failing handler tests**

`tests/dataflow/srccfg/test_handlers.py`:

```python
"""Which handler is live at a command that can raise.

Task 10 made arming an assignment precisely so this question needs no new machinery:
the live handlers are the definitions of %HANDLER[...] that reach the dispatch node.
"""

from __future__ import annotations

from cobol_asg.asg_types import CobolASG
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered

from cobble.dataflow.srccfg.build import build_program
from cobble.dataflow.srccfg.cfg import EdgeKind
from cobble.dataflow.srccfg.dataflow import live_handlers, with_handler_edges


def _asg(paragraphs: list[dict]) -> CobolASG:
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict({"program_id": "PROGA", "paragraphs": paragraphs})


def _cics(verb: str, options: dict) -> dict:
    return {"type": "EXEC_CICS", "verb": verb, "options": options}


def _arm(condition: str, paragraph: str) -> dict:
    return _cics("HANDLE CONDITION", {condition: {"text": paragraph, "is_literal": False}})


def _receive() -> dict:
    return _cics("RECEIVE MAP", {"MAP": {"text": "'MAPA'", "is_literal": True}})


def _dispatch_of(cfg) -> str:
    return next(node.id for node in cfg.nodes if node.id.endswith("#dispatch"))


def test_a_handler_armed_before_a_command_is_live_at_it() -> None:
    cfg = build_program(
        _asg([{"name": "MAIN", "statements": [_arm("MAPFAIL", "H-MAPFAIL"), _receive()]},
              {"name": "H-MAPFAIL", "statements": []}])
    )

    assert live_handlers(cfg)[_dispatch_of(cfg)] == ("H-MAPFAIL",)


def test_a_handler_armed_after_the_command_is_not_live_at_it() -> None:
    """Arming order is the whole semantics, and a per-paragraph "this paragraph arms
    MAPFAIL" answer gets this backwards."""
    cfg = build_program(
        _asg([{"name": "MAIN", "statements": [_receive(), _arm("MAPFAIL", "H-MAPFAIL")]},
              {"name": "H-MAPFAIL", "statements": []}])
    )

    assert live_handlers(cfg)[_dispatch_of(cfg)] == ()


def test_re_arming_kills_the_earlier_handler_for_the_same_condition() -> None:
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _arm("MAPFAIL", "H-FIRST"),
                        _arm("MAPFAIL", "H-SECOND"),
                        _receive(),
                    ],
                },
                {"name": "H-FIRST", "statements": []},
                {"name": "H-SECOND", "statements": []},
            ]
        )
    )

    assert live_handlers(cfg)[_dispatch_of(cfg)] == ("H-SECOND",)


def test_handlers_for_two_conditions_are_both_live() -> None:
    """%HANDLER[MAPFAIL] and %HANDLER[ERROR] are separate fields, so neither kills
    the other -- and the dispatch can go to either."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _arm("MAPFAIL", "H-MAPFAIL"),
                        _arm("ERROR", "H-ERROR"),
                        _receive(),
                    ],
                },
                {"name": "H-ERROR", "statements": []},
                {"name": "H-MAPFAIL", "statements": []},
            ]
        )
    )

    assert live_handlers(cfg)[_dispatch_of(cfg)] == ("H-ERROR", "H-MAPFAIL")


def test_a_handler_armed_on_one_arm_only_is_live_alongside_no_handler() -> None:
    """Sorted and deduplicated, so a dispatch reached under two arms lists each
    target once -- which arm is which is a guard question."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        {
                            "type": "IF",
                            "condition": {
                                "kind": "relation",
                                "left": "WS-FLAG-A",
                                "operator": "=",
                                "right": "'Y'",
                            },
                            "then_statements": [_arm("MAPFAIL", "H-MAPFAIL")],
                            "else_statements": [],
                        },
                        _receive(),
                    ],
                },
                {"name": "H-MAPFAIL", "statements": []},
            ]
        )
    )

    assert live_handlers(cfg)[_dispatch_of(cfg)] == ("H-MAPFAIL",)


def test_an_ignored_condition_is_not_a_dispatch_target() -> None:
    """IGNORE CONDITION means the command returns and execution continues, so there
    is nowhere to go -- and %IGNORE is not a paragraph name."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _cics("IGNORE CONDITION", {"MAPFAIL": None}),
                        _receive(),
                    ],
                }
            ]
        )
    )

    assert live_handlers(cfg)[_dispatch_of(cfg)] == ()


def test_a_condition_reset_to_the_system_default_is_not_a_dispatch_target() -> None:
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _arm("MAPFAIL", "H-MAPFAIL"),
                        _cics("HANDLE CONDITION", {"MAPFAIL": None}),
                        _receive(),
                    ],
                },
                {"name": "H-MAPFAIL", "statements": []},
            ]
        )
    )

    assert live_handlers(cfg)[_dispatch_of(cfg)] == ()


def test_the_resolved_cfg_grows_a_goto_edge_to_each_live_handler() -> None:
    """The point of resolving: a walk over the returned CFG reaches the handler
    paragraph, so an assignment there gets the guard of the command that raised."""
    cfg = with_handler_edges(
        build_program(
            _asg(
                [
                    {"name": "MAIN", "statements": [_arm("MAPFAIL", "H-MAPFAIL"), _receive()]},
                    {"name": "H-MAPFAIL", "statements": []},
                ]
            )
        )
    )

    edges = cfg.successors(_dispatch_of(cfg))

    assert [(e.target, e.kind) for e in edges] == [("H-MAPFAIL#label", EdgeKind.GOTO)]


def test_a_handler_paragraph_the_program_does_not_declare_gets_no_edge() -> None:
    """A name that is not a paragraph is a dynamic or dead handler. Keeping the
    target on the node with no edge is what stops a later walk landing on a node
    that does not exist."""
    cfg = with_handler_edges(
        build_program(
            _asg([{"name": "MAIN", "statements": [_arm("MAPFAIL", "H-GONE"), _receive()]}])
        )
    )

    assert cfg.successors(_dispatch_of(cfg)) == ()


def test_resolving_a_cfg_with_no_cics_returns_it_unchanged() -> None:
    cfg = build_program(
        _asg([{"name": "MAIN", "statements": [{"type": "MOVE", "operands": [{"name": "'A'"}, {"name": "WS-FLAG-A"}]}]}])
    )

    assert with_handler_edges(cfg) == cfg
```

- [ ] **Step 3: Run both to verify they fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg/test_reaching_definitions.py tests/dataflow/srccfg/test_handlers.py -v`
Expected: FAIL — `ImportError: cannot import name 'reaching_definitions'`

- [ ] **Step 4: Add to `dataflow.py`**

```python
@dataclass(frozen=True)
class Definition:
    node: str
    field: str


Defs = frozenset[Definition]

HANDLER_PREFIX = "%HANDLER["


def definitions_of(cfg: Cfg) -> Mapping[str, Defs]:
    """The gen set: what each node writes."""
    return {
        node.id: frozenset(Definition(node=node.id, field=name) for name in node.writes)
        for node in cfg.nodes
    }


def reaching_definitions(cfg: Cfg) -> Mapping[str, Defs]:
    """A gen/kill fixpoint. Not the path walk: one definition reached by four paths
    is one definition, and a per-path answer would report it four times.
    """
    generated = definitions_of(cfg)
    incoming: dict[str, Defs] = {node.id: frozenset() for node in cfg.nodes}
    while True:
        stepped = {
            node_id: _joined(cfg, node_id, incoming, generated) for node_id in incoming
        }
        if stepped == incoming:
            return incoming
        incoming = stepped


def _joined(
    cfg: Cfg,
    node_id: str,
    incoming: Mapping[str, Defs],
    generated: Mapping[str, Defs],
) -> Defs:
    return frozenset(
        chain.from_iterable(
            _out_of(edge.source, incoming, generated) for edge in cfg.predecessors(node_id)
        )
    )


def _out_of(
    node_id: str, incoming: Mapping[str, Defs], generated: Mapping[str, Defs]
) -> Defs:
    written = {definition.field for definition in generated.get(node_id, frozenset())}
    survived = frozenset(
        definition
        for definition in incoming.get(node_id, frozenset())
        if definition.field not in written
    )
    return survived | generated.get(node_id, frozenset())


@dataclass(frozen=True)
class Use:
    node: str
    field: str
    definitions: Defs = frozenset()


def def_use(cfg: Cfg) -> tuple[Use, ...]:
    incoming = reaching_definitions(cfg)
    return tuple(
        Use(
            node=node.id,
            field=name,
            definitions=frozenset(
                d for d in incoming.get(node.id, frozenset()) if d.field == name
            ),
        )
        for node in cfg.nodes
        for name in node.reads
    )


def writers_of(cfg: Cfg, field: str) -> tuple[str, ...]:
    return tuple(node.id for node in cfg.nodes if field in node.writes)


def live_handlers(cfg: Cfg) -> Mapping[str, tuple[str, ...]]:
    """The paragraphs a raise at each dispatch node can reach.

    Any %HANDLER[...] definition reaching the dispatch is a candidate, whatever the
    condition: the dispatch reads %HANDLER[ANY] because the CFG does not model which
    condition a command raises.
    """
    incoming = reaching_definitions(cfg)
    return {
        node.id: _targets(cfg, incoming.get(node.id, frozenset()))
        for node in cfg.nodes
        if node.transfer == DISPATCH_TRANSFER_CICS
    }


def _targets(cfg: Cfg, definitions: Defs) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                value
                for definition in definitions
                if definition.field.startswith(HANDLER_PREFIX)
                for value in cfg.node(definition.node).reads
                if value not in (IGNORED, SYSTEM_DEFAULT)
            }
        )
    )


def with_handler_edges(cfg: Cfg) -> Cfg:
    """Resolve every dispatch node, so a walk reaches the handler paragraph and an
    assignment there carries the guard of the command that raised."""
    added = tuple(
        Edge(source=node_id, target=label_id(target), kind=EdgeKind.GOTO)
        for node_id, targets in live_handlers(cfg).items()
        for target in targets
        if label_id(target) in cfg.node_ids
    )
    return cfg if not added else Cfg(program=cfg.program, nodes=cfg.nodes, edges=(*cfg.edges, *added))
```

`_out_of` recomputes each predecessor's out-set on every sweep, which is redundant
work bounded by the edge count times the sweep count. Leave it: it keeps the pass a
pure function of the CFG with no worklist state, and the corpus members are small
enough that measuring comes first. `from cobble.dataflow.srccfg.desugar import
DISPATCH_TRANSFER_CICS, IGNORED, SYSTEM_DEFAULT` goes at the top — if that import is
circular because `desugar` imports `dataflow`, it does not (desugar imports only
`cfg` and `conditions`), so a cycle here means an import was added in the wrong
direction and belongs in `cfg.py` instead.

- [ ] **Step 5: Run the suite and the gates**

```bash
cd cobble
uv run --no-sync python -m pytest tests/dataflow/srccfg -v
uv run --no-sync python -m python_fp_lint check cobble/dataflow/srccfg/
make lint
```

Expected: PASS with zero new violations. `reaching_definitions` uses `while True` with
a reassigned local, which is the same shape Task 12 already passes with; if fp-lint
rejects the reassignment, make it recursive:

```python
def _fixpoint(cfg: Cfg, incoming: Mapping[str, Defs], generated: Mapping[str, Defs]) -> Mapping[str, Defs]:
    stepped = {node_id: _joined(cfg, node_id, incoming, generated) for node_id in incoming}
    return incoming if stepped == incoming else _fixpoint(cfg, stepped, generated)
```

and raise the recursion limit nowhere — the depth is the number of sweeps, not the
node count.

- [ ] **Step 6: Commit**

```bash
git add cobble/dataflow/srccfg/dataflow.py \
  tests/dataflow/srccfg/test_reaching_definitions.py tests/dataflow/srccfg/test_handlers.py
git commit -m "$(cat <<'EOF'
feat(cobble): add reaching definitions, def-use, and live handler resolution

A gen/kill fixpoint over the CFG, kept separate from the per-path guards so one
definition reached by four paths stays one definition. Resolving a CICS dispatch node
falls out of it: the live handlers are the %HANDLER[...] definitions that reach the
command, which makes re-arming and arming on one arm only ordinary dataflow.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---
### Task 14: co-assignment in four tiers

"Which fields are written together with this one" is a weaker question than reaching
conditions, and it is the one a reader asks first: two fields set in the same breath
are usually two halves of one decision. It is a **query-time** relation over the CFG
and the guards, not a stored one, and it comes in four tiers of decreasing strength so
a caller can choose how much noise to accept:

| Tier | Relation | Why it is weaker than the one above |
|------|----------|-------------------------------------|
| 1 `SAME_STATEMENT` | one node writes both fields | Certain. One statement, one decision. |
| 2 `SAME_SOURCE` | same paragraph, and the two writes read a field in common | The precise tier. A shared source is real evidence of one derivation. |
| 3 `SAME_GUARD` | identical guard sets | Two unrelated fields under the same flag look co-assigned. |
| 4 `SAME_PARAGRAPH` | same paragraph, nothing else | Weakest: a 300-line paragraph makes everything a candidate. |

Each pair is reported once, at its strongest tier. `min_tier` lets a caller stop at 2.

**Files:**
- Create: `cobble/dataflow/srccfg/coassign.py`
- Test: `tests/dataflow/srccfg/test_coassign.py`

**Interfaces:**
- Consumes: `Cfg`, `Node` (Task 1); `Reaching`, `guards_of`, `guard_set`,
  `reaching_conditions`, `writers_of` (Task 12/13)
- Produces:
  - `class Tier(IntEnum)`: `SAME_STATEMENT = 1`, `SAME_SOURCE = 2`, `SAME_GUARD = 3`,
    `SAME_PARAGRAPH = 4`
  - `Candidate(field: str, tier: Tier, nodes: tuple[str, str], shared: tuple[str, ...])`
  - `co_assigned(cfg: Cfg, field: str, reaching: Reaching, min_tier: Tier = Tier.SAME_PARAGRAPH) -> tuple[Candidate, ...]`
  - `guard_signature(reaching: Reaching, node_id: str) -> frozenset[frozenset[tuple[str, EdgeKind]]]`

- [ ] **Step 1: Write the failing tests**

`tests/dataflow/srccfg/test_coassign.py`:

```python
"""Which fields are written together with this one, in four tiers.

Tiers rather than one answer because the strong relation is rare and the weak one is
everywhere: on a real corpus, "same paragraph" makes a 300-line paragraph's every
field a candidate, which is true and useless. A caller that wants signal stops at
tier 2.
"""

from __future__ import annotations

from cobol_asg.asg_types import CobolASG
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered

from cobble.dataflow.srccfg.build import build_program
from cobble.dataflow.srccfg.coassign import Tier, co_assigned, guard_signature
from cobble.dataflow.srccfg.dataflow import reaching_conditions


def _asg(paragraphs: list[dict]) -> CobolASG:
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict({"program_id": "PROGA", "paragraphs": paragraphs})


def _move(value: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": value}, {"name": target}]}


def _if(condition: dict, then: list[dict], otherwise: list[dict]) -> dict:
    return {
        "type": "IF",
        "condition": condition,
        "then_statements": then,
        "else_statements": otherwise,
    }


def _rel(left: str, op: str, right: str) -> dict:
    return {"kind": "relation", "left": left, "operator": op, "right": right}


def _for(cfg, field: str, **kwargs):
    return co_assigned(cfg, field, reaching_conditions(cfg), **kwargs)


def _fields(candidates) -> dict:
    return {candidate.field: candidate.tier for candidate in candidates}


def test_two_fields_written_by_one_statement_are_tier_one() -> None:
    """INITIALIZE and MOVE CORRESPONDING write several fields from one decision, and
    that is the only tier where co-assignment is certain."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [{"type": "INITIALIZE", "operands": [{"name": "WS-A"}, {"name": "WS-B"}]}],
                }
            ]
        )
    )

    assert _fields(_for(cfg, "WS-A")) == {"WS-B": Tier.SAME_STATEMENT}


def test_two_writes_in_one_paragraph_from_a_shared_source_are_tier_two() -> None:
    """The precise tier: a shared source is evidence of one derivation, not just of
    two statements happening to be near each other."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_move("WS-IN", "WS-A"), _move("WS-IN", "WS-B")],
                }
            ]
        )
    )

    assert _fields(_for(cfg, "WS-A")) == {"WS-B": Tier.SAME_SOURCE, "WS-IN": Tier.SAME_PARAGRAPH}


def test_the_shared_source_is_named_on_the_candidate() -> None:
    """Without it the tier is a claim the reader cannot check against the listing."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_move("WS-IN", "WS-A"), _move("WS-IN", "WS-B")],
                }
            ]
        )
    )

    candidate = next(c for c in _for(cfg, "WS-A") if c.field == "WS-B")

    assert candidate.shared == ("WS-IN",)


def test_two_fields_under_the_same_guard_in_different_paragraphs_are_tier_three() -> None:
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _if(
                            _rel("WS-FLAG-A", "=", "'Y'"),
                            [
                                {"type": "PERFORM", "target": "P-ONE"},
                                {"type": "PERFORM", "target": "P-TWO"},
                            ],
                            [],
                        )
                    ],
                },
                {"name": "P-ONE", "statements": [_move("'1'", "WS-A")]},
                {"name": "P-TWO", "statements": [_move("'2'", "WS-B")]},
            ]
        )
    )

    assert _fields(_for(cfg, "WS-A")).get("WS-B") == Tier.SAME_GUARD


def test_two_unrelated_fields_in_one_paragraph_are_tier_four() -> None:
    """The weakest tier is still reported, because on the corpus it is often the only
    evidence there is -- and its weakness has to be visible in the answer rather than
    argued about afterwards."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_move("'1'", "WS-A"), _move("'2'", "WS-B")],
                }
            ]
        )
    )

    assert _fields(_for(cfg, "WS-A")) == {"WS-B": Tier.SAME_PARAGRAPH}


def test_a_pair_is_reported_once_at_its_strongest_tier() -> None:
    """Two fields in one paragraph, sharing a source, under one guard, satisfy tiers
    2, 3 and 4 at once. Three rows for one pair would make every count meaningless.
    """
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _if(
                            _rel("WS-FLAG-A", "=", "'Y'"),
                            [_move("WS-IN", "WS-A"), _move("WS-IN", "WS-B")],
                            [],
                        )
                    ],
                }
            ]
        )
    )

    matches = [c for c in _for(cfg, "WS-A") if c.field == "WS-B"]

    assert [c.tier for c in matches] == [Tier.SAME_SOURCE]


def test_min_tier_two_drops_the_noisy_tiers() -> None:
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_move("'1'", "WS-A"), _move("'2'", "WS-B")],
                }
            ]
        )
    )

    assert _for(cfg, "WS-A", min_tier=Tier.SAME_SOURCE) == ()


def test_a_field_is_never_a_candidate_for_itself() -> None:
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_move("'1'", "WS-A"), _move("'2'", "WS-A")],
                }
            ]
        )
    )

    assert _for(cfg, "WS-A") == ()


def test_a_field_written_nowhere_has_no_candidates() -> None:
    cfg = build_program(_asg([{"name": "MAIN", "statements": [_move("'1'", "WS-A")]}]))

    assert _for(cfg, "WS-NEVER") == ()


def test_candidates_are_ordered_by_tier_then_by_name() -> None:
    """Stable output, strongest first: the caller reads the head of the list and
    stops, and two runs diff."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _move("WS-IN", "WS-A"),
                        _move("WS-IN", "WS-Z"),
                        _move("'2'", "WS-B"),
                    ],
                }
            ]
        )
    )

    assert [(c.tier, c.field) for c in _for(cfg, "WS-A")] == [
        (Tier.SAME_SOURCE, "WS-Z"),
        (Tier.SAME_PARAGRAPH, "WS-B"),
        (Tier.SAME_PARAGRAPH, "WS-IN"),
    ]


def test_the_pair_of_nodes_is_named_so_the_claim_can_be_checked() -> None:
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_move("WS-IN", "WS-A"), _move("WS-IN", "WS-B")],
                }
            ]
        )
    )

    candidate = next(c for c in _for(cfg, "WS-A") if c.field == "WS-B")

    assert candidate.nodes == ("MAIN/0", "MAIN/1")


def test_two_writes_of_one_field_in_two_paragraphs_find_candidates_in_both() -> None:
    """A field written in four places has four contexts, and a query that only looked
    at the first would answer for one of them."""
    cfg = build_program(
        _asg(
            [
                {"name": "MAIN", "statements": [_move("'1'", "WS-A"), _move("'2'", "WS-B")]},
                {"name": "OTHER", "statements": [_move("'3'", "WS-A"), _move("'4'", "WS-C")]},
            ]
        )
    )

    assert set(_fields(_for(cfg, "WS-A"))) == {"WS-B", "WS-C"}


def test_guard_signature_is_order_insensitive_and_covers_every_path() -> None:
    """A node reached under two guards has a signature of two sets, so it matches
    another node only when both are reached the same ways."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _if(_rel("WS-FLAG-A", "=", "'Y'"), [_move("'1'", "WS-A")], []),
                        _move("'2'", "WS-AFTER"),
                    ],
                }
            ]
        )
    )
    reaching = reaching_conditions(cfg)
    writer = next(node.id for node in cfg.nodes if "WS-AFTER" in node.writes)

    assert len(guard_signature(reaching, writer)) == 2
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg/test_coassign.py -v`
Expected: FAIL — `ModuleNotFoundError: cobble.dataflow.srccfg.coassign`

- [ ] **Step 3: Write `coassign.py`**

```python
"""Co-assignment: which fields are written together with this one.

A query-time relation, in tiers, because the strong evidence is rare and the weak
evidence is everywhere. Storing one blended answer would hide which kind a given
candidate rests on -- and the weak tier is exactly the one a reader must be able to
discount.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from cobble.dataflow.srccfg.cfg import Cfg, EdgeKind, Node
from cobble.dataflow.srccfg.dataflow import Reaching, guard_set, guards_of


class Tier(IntEnum):
    SAME_STATEMENT = 1
    SAME_SOURCE = 2
    SAME_GUARD = 3
    SAME_PARAGRAPH = 4


@dataclass(frozen=True)
class Candidate:
    field: str
    tier: Tier
    nodes: tuple[str, str]
    shared: tuple[str, ...] = ()


def guard_signature(
    reaching: Reaching, node_id: str
) -> frozenset[frozenset[tuple[str, EdgeKind]]]:
    return frozenset(guard_set(guard) for guard in guards_of(reaching, node_id))


def co_assigned(
    cfg: Cfg,
    field: str,
    reaching: Reaching,
    min_tier: Tier = Tier.SAME_PARAGRAPH,
) -> tuple[Candidate, ...]:
    best: dict[str, Candidate] = {}
    for source in (n for n in cfg.nodes if field in n.writes):
        best = _folded(best, _pairs(cfg, source, field, reaching, min_tier))
    return tuple(sorted(best.values(), key=lambda c: (c.tier, c.field)))


def _folded(
    best: dict[str, Candidate], found: tuple[Candidate, ...]
) -> dict[str, Candidate]:
    return {
        **best,
        **{
            candidate.field: candidate
            for candidate in found
            if candidate.tier < best.get(candidate.field, candidate).tier
            or candidate.field not in best
        },
    }


def _pairs(
    cfg: Cfg, source: Node, field: str, reaching: Reaching, min_tier: Tier
) -> tuple[Candidate, ...]:
    return tuple(
        candidate
        for other in cfg.nodes
        for candidate in _candidate(source, other, field, reaching)
        if candidate.tier <= min_tier
    )


def _candidate(
    source: Node, other: Node, field: str, reaching: Reaching
) -> tuple[Candidate, ...]:
    written = tuple(name for name in other.writes if name != field)
    tier = _tier(source, other, reaching)
    return tuple(
        Candidate(
            field=name,
            tier=tier,
            nodes=(source.id, other.id),
            shared=_shared(source, other),
        )
        for name in written
        if tier
    )


def _tier(source: Node, other: Node, reaching: Reaching) -> Tier | None:
    if source.id == other.id:
        return Tier.SAME_STATEMENT
    if other.paragraph == source.paragraph and _shared(source, other):
        return Tier.SAME_SOURCE
    if guard_signature(reaching, source.id) == guard_signature(reaching, other.id):
        return Tier.SAME_GUARD
    return Tier.SAME_PARAGRAPH if other.paragraph == source.paragraph else None


def _shared(source: Node, other: Node) -> tuple[str, ...]:
    return tuple(sorted(set(source.reads) & set(other.reads)))
```

Two things the implementer will hit:

- `_tier` returns `Tier | None`, and `None` is banned. Rewrite it to return `Tier`
  plus a sentinel: add `UNRELATED = 9` to the enum, return that instead of `None`, and
  filter on `tier != Tier.UNRELATED` in `_candidate`. Do this rather than keeping the
  `None`.
- `_folded`'s condition reads awkwardly and evaluates `best.get` twice. If it is
  clearer, replace it with an explicit helper `_better(existing: Candidate, found:
  Candidate) -> Candidate` returning whichever has the lower tier, and build the dict
  from that.

The tier-3 comparison uses whole guard signatures, so a node reached two ways matches
only a node reached the same two ways. That is deliberately strict: a looser
"intersecting guards" rule made everything under the program's top-level flag a
candidate.

- [ ] **Step 4: Run the suite and the gates**

```bash
cd cobble
uv run --no-sync python -m pytest tests/dataflow/srccfg -v
uv run --no-sync python -m python_fp_lint check cobble/dataflow/srccfg/
make lint
```

Expected: PASS with zero new violations. `co_assigned`'s `for` loop rebinds `best`; if
fp-lint objects, fold with `functools.reduce` over the writer nodes.

- [ ] **Step 5: Commit**

```bash
git add cobble/dataflow/srccfg/coassign.py tests/dataflow/srccfg/test_coassign.py
git commit -m "$(cat <<'EOF'
feat(cobble): report co-assignment candidates in four tiers

Same statement, same source, same guard set, same paragraph -- strongest first, each
pair reported once. Tiered rather than blended because the weak tier is everywhere on
a real corpus and a reader has to be able to see which evidence a candidate rests on.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---
### Task 15: the call graph, and commarea aliasing

A field's derivation stops at the edge of a member unless the calls out of it are
known. On the onboarding corpus that is 4,084 `LINK`/`XCTL` sites and 1,231 static
`CALL` sites over 3,779 members, so a per-member answer is missing most of the story
for anything that crosses a commarea.

Two pieces:

- **Call sites become CFG nodes with a transfer and a target**, the same shape
  `GO TO` and `PERFORM` already use. A dynamic `PROGRAM(WS-FIELD)` keeps the field name
  as its target and is marked unresolved — resolving those is deferred, and marking is
  what stops them being silently dropped or silently believed.
- **A commarea is an alias, at whole-record granularity.** `LINK PROGRAM('PROGB')
  COMMAREA(WS-AREA)` means the callee's `DFHCOMMAREA` and the caller's `WS-AREA` are
  the same storage. Byte-offset-accurate field-level aliasing needs the layout work
  that is out of scope here, so the alias is recorded record-to-record and the
  granularity is stated in the answer rather than implied.

**Files:**
- Modify: `cobble/dataflow/srccfg/desugar.py`
- Create: `cobble/dataflow/srccfg/link.py`
- Modify: `cobble/dataflow/srccfg/build_corpus.py` (add `cfg_from_dict`)
- Test: `tests/dataflow/srccfg/test_link.py`

**Interfaces:**
- Consumes: `Cfg`, `Node` (Task 1); `_exec_cics`, `_plain_without_arms`,
  `SUPPRESSING_OPTIONS` (Task 10); `cfg_to_dict`, `asg_paths` (Task 11)
- Produces:
  - in `desugar.py`: `LINK_TRANSFER = "LINK"`, `XCTL_TRANSFER = "XCTL"`,
    `CALL_TRANSFER = "CALL"`, `CALL_TRANSFERS = (LINK_TRANSFER, XCTL_TRANSFER, CALL_TRANSFER)`,
    `COMMAREA_OPTION = "COMMAREA"`, `PROGRAM_OPTION = "PROGRAM"`,
    `commarea_field(node: Node) -> str`, `_call`-side handler for `CallStatement`
  - in `link.py`:
    - `CallSite(caller: str, node: str, transfer: str, program: str, resolved: bool, commarea: str)`
    - `call_sites(cfg: Cfg) -> tuple[CallSite, ...]`
    - `Alias(caller: str, caller_field: str, callee: str, callee_field: str)`
    - `COMMAREA_RECORD = "DFHCOMMAREA"`
    - `aliases(cfg: Cfg) -> tuple[Alias, ...]`
    - `CallGraph(sites: tuple[CallSite, ...], aliases: tuple[Alias, ...])`
    - `call_graph(cfgs: Iterable[Cfg]) -> CallGraph`
    - `callers_of(graph: CallGraph, program: str) -> tuple[str, ...]`
    - `callees_of(graph: CallGraph, program: str) -> tuple[str, ...]`
    - `unresolved_sites(graph: CallGraph) -> tuple[CallSite, ...]`
  - in `build_corpus.py`: `cfg_from_dict(document: Mapping) -> Cfg`,
    `load_cfg(path: Path) -> Cfg`

- [ ] **Step 1: Write the failing tests**

`tests/dataflow/srccfg/test_link.py`:

```python
"""Calls out of a member, and the storage a commarea shares.

A derivation that stops at the member boundary answers nothing for a field filled by
a caller -- and on this corpus most of the interesting ones are. Dynamic program
names are marked rather than dropped: 38 of them, and either silently believing or
silently losing them is worse than an answer that says "unresolved".
"""

from __future__ import annotations

from cobol_asg.asg_types import CobolASG

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered

from cobble.dataflow.srccfg.build import build_program
from cobble.dataflow.srccfg.link import (
    COMMAREA_RECORD,
    Alias,
    aliases,
    call_graph,
    call_sites,
    callees_of,
    callers_of,
    unresolved_sites,
)


def _asg(program: str, statements: list[dict]) -> CobolASG:
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict(
            {"program_id": program, "paragraphs": [{"name": "MAIN", "statements": statements}]}
        )


def _cfg(program: str, statements: list[dict]):
    return build_program(_asg(program, statements))


def _cics(verb: str, options: dict) -> dict:
    return {"type": "EXEC_CICS", "verb": verb, "options": options}


def _link(program: str, literal: bool = True, commarea: str = "") -> dict:
    options = {"PROGRAM": {"text": program, "is_literal": literal}}
    extra = {"COMMAREA": {"text": commarea, "is_literal": False}} if commarea else {}
    return _cics("LINK", {**options, **extra})


def test_a_link_to_a_literal_program_is_a_resolved_call_site() -> None:
    (site,) = call_sites(_cfg("PROGA", [_link("'PROGB'")]))

    assert (site.caller, site.transfer, site.program, site.resolved) == (
        "PROGA",
        "LINK",
        "PROGB",
        True,
    )


def test_the_program_name_loses_its_quotes() -> None:
    """The call graph joins on program id, and 'PROGB' never equals PROGB."""
    (site,) = call_sites(_cfg("PROGA", [_link("'PROGB'")]))

    assert site.program == "PROGB"


def test_an_xctl_is_a_call_site_of_its_own_kind() -> None:
    """XCTL does not return, so a walk must not continue past it the way a LINK does
    -- and a caller asking "what runs after this" needs the two distinguished."""
    (site,) = call_sites(_cfg("PROGA", [_cics("XCTL", {"PROGRAM": {"text": "'PROGB'", "is_literal": True}})]))

    assert site.transfer == "XCTL"


def test_a_static_cobol_call_is_a_call_site() -> None:
    """1,231 of them on the corpus, and they carry USING parameters rather than a
    commarea -- a batch program's whole interface."""
    (site,) = call_sites(_cfg("PROGA", [{"type": "CALL", "program": "'PROGB'", "using": [{"name": "WS-AREA"}]}]))

    assert (site.transfer, site.program, site.resolved) == ("CALL", "PROGB", True)


def test_a_dynamic_program_name_is_unresolved_and_keeps_the_field_name() -> None:
    """Keeping the field is what makes the follow-up possible: the answer to "which
    programs can this reach" is a reaching-definitions query over that field."""
    (site,) = call_sites(_cfg("PROGA", [_link("WS-TARGET", literal=False)]))

    assert (site.program, site.resolved) == ("WS-TARGET", False)


def test_a_call_with_no_program_option_is_not_a_call_site() -> None:
    """A malformed or unparsed command must not become an edge to the empty program,
    which would collapse every one of them onto a single graph node."""
    assert call_sites(_cfg("PROGA", [_cics("LINK", {})])) == ()


def test_a_commarea_is_an_alias_between_the_caller_field_and_dfhcommarea() -> None:
    assert aliases(_cfg("PROGA", [_link("'PROGB'", commarea="WS-AREA")])) == (
        Alias(caller="PROGA", caller_field="WS-AREA", callee="PROGB", callee_field=COMMAREA_RECORD),
    )


def test_a_link_with_no_commarea_produces_no_alias() -> None:
    assert aliases(_cfg("PROGA", [_link("'PROGB'")])) == ()


def test_a_dynamic_target_produces_no_alias_because_the_callee_is_unknown() -> None:
    """An alias to an unresolved program would name the FIELD as the callee, and a
    query joining on program id would then match nothing while looking like data."""
    assert aliases(_cfg("PROGA", [_link("WS-TARGET", literal=False, commarea="WS-AREA")])) == ()


def test_a_call_using_aliases_every_parameter_positionally() -> None:
    """USING has no commarea to name, so the alias is positional -- and the position
    is what a later linkage-section match needs."""
    found = aliases(
        _cfg(
            "PROGA",
            [{"type": "CALL", "program": "'PROGB'", "using": [{"name": "WS-ONE"}, {"name": "WS-TWO"}]}],
        )
    )

    assert [(a.caller_field, a.callee_field) for a in found] == [
        ("WS-ONE", "%USING[0]"),
        ("WS-TWO", "%USING[1]"),
    ]


def test_a_literal_using_parameter_is_not_an_alias() -> None:
    """BY CONTENT of a literal shares no storage back."""
    found = aliases(
        _cfg("PROGA", [{"type": "CALL", "program": "'PROGB'", "using": [{"name": "'X'", "is_literal": True}]}])
    )

    assert found == ()


def test_an_omitted_parameter_takes_its_position_without_an_alias() -> None:
    """OMITTED shifts nothing: the parameter after it is still the third, and
    renumbering would alias the wrong field."""
    found = aliases(
        _cfg(
            "PROGA",
            [
                {
                    "type": "CALL",
                    "program": "'PROGB'",
                    "using": [{"name": "WS-ONE"}, {"name": "", "omitted": True}, {"name": "WS-THREE"}],
                }
            ],
        )
    )

    assert [(a.caller_field, a.callee_field) for a in found] == [
        ("WS-ONE", "%USING[0]"),
        ("WS-THREE", "%USING[2]"),
    ]


def test_the_call_graph_joins_two_members() -> None:
    graph = call_graph([_cfg("PROGA", [_link("'PROGB'")]), _cfg("PROGB", [_link("'PROGC'")])])

    assert callees_of(graph, "PROGA") == ("PROGB",)
    assert callers_of(graph, "PROGB") == ("PROGA",)


def test_callers_and_callees_are_sorted_and_deduplicated() -> None:
    """A member that LINKs the same program from eleven places is one edge."""
    graph = call_graph([_cfg("PROGA", [_link("'PROGC'"), _link("'PROGB'"), _link("'PROGB'")])])

    assert callees_of(graph, "PROGA") == ("PROGB", "PROGC")


def test_an_unresolved_site_is_not_a_callee_edge_but_is_reported() -> None:
    """A field name in the callee position would be a node in the call graph that no
    member ever matches -- so it stays out of the edges and into a list a reader can
    work through."""
    graph = call_graph([_cfg("PROGA", [_link("WS-TARGET", literal=False)])])

    assert callees_of(graph, "PROGA") == ()
    assert [s.program for s in unresolved_sites(graph)] == ("WS-TARGET",)


def test_a_program_nobody_calls_has_no_callers() -> None:
    graph = call_graph([_cfg("PROGA", [_link("'PROGB'")])])

    assert callers_of(graph, "PROGA") == ()


def test_a_call_site_names_the_node_so_its_guard_can_be_looked_up() -> None:
    """The call graph on its own says a call is possible; the guard says when. Both
    answers are needed together, and the node id is the join."""
    (site,) = call_sites(_cfg("PROGA", [_link("'PROGB'")]))

    assert site.node.startswith("MAIN/")
```

Fix the one type error in the test above before running: `unresolved_sites` returns a
tuple, so `[s.program for s in unresolved_sites(graph)] == ("WS-TARGET",)` compares a
list to a tuple. Write it as `== ["WS-TARGET"]`.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg/test_link.py -v`
Expected: FAIL — `ModuleNotFoundError: cobble.dataflow.srccfg.link`

- [ ] **Step 3: Record the transfer and target in `desugar.py`**

Add, and call `_call_node` from `_exec_cics` before the arms/raise wrapping so a LINK
is both a call site and a command that can raise:

```python
LINK_TRANSFER = "LINK"
XCTL_TRANSFER = "XCTL"
CALL_TRANSFER = "CALL"
CALL_TRANSFERS = (LINK_TRANSFER, XCTL_TRANSFER, CALL_TRANSFER)
PROGRAM_OPTION = "PROGRAM"
COMMAREA_OPTION = "COMMAREA"
_CICS_CALL_VERBS = {"LINK": LINK_TRANSFER, "XCTL": XCTL_TRANSFER}


def commarea_field(node: Node) -> str:
    """The caller field a call site shares with its callee, or "" for none.

    Stored in `transfer_operand` rather than inferred from `reads`, because a LINK
    reads its map name and its length too and picking the commarea back out of that
    list is guesswork.
    """
    return node.transfer_operand


def _with_call(statement, node: Node, verb: str) -> Node:
    transfer = _CICS_CALL_VERBS.get(verb, "")
    program = _option_text(statement, PROGRAM_OPTION)
    if not (transfer and program):
        return node
    return replace(
        node,
        kind=NodeKind.CALL,
        transfer=transfer,
        target=program,
        target_resolved=_option_is_literal(statement, PROGRAM_OPTION),
        transfer_operand=_option_text(statement, COMMAREA_OPTION),
    )


def _option_text(statement, name: str) -> str:
    return str(getattr(getattr(statement, "options", {}).get(name), "text", "") or "")


def _option_is_literal(statement, name: str) -> bool:
    return bool(getattr(getattr(statement, "options", {}).get(name), "is_literal", False))


def _cobol_call(statement, ctx: Ctx, path: str) -> Fragment:
    """CALL 'PROGB' USING A B. The parameters are the alias list, so they are kept in
    order -- OMITTED included, since a parameter's position is its identity."""
    return _one(
        replace(
            _plain(statement, ctx, path),
            kind=NodeKind.CALL,
            transfer=CALL_TRANSFER,
            target=_literal_text(getattr(statement, "program", "")),
            target_resolved=_is_quoted(getattr(statement, "program", "")),
            using=tuple(
                "" if param.omitted or param.is_literal else param.name
                for param in getattr(statement, "using", ())
            ),
        )
    )
```

Register `"CallStatement": _cobol_call`. `Node` gains three fields in `cfg.py`, all
with empty defaults so every existing construction and every written CFG JSON stays
valid:

```python
    target_resolved: bool = True
    transfer_operand: str = ""
    using: tuple[str, ...] = ()
```

`target_resolved` defaults to `True` because `GO TO` and `PERFORM` targets are always
paragraph names; only a call can be dynamic.

`_literal_text` and `_is_quoted` belong beside the existing literal handling — reuse
`cobble.dataflow.depgraph.graph.is_literal` for the test rather than adding a second
quoting rule, and strip with `.strip("'\"")`.

- [ ] **Step 4: Write `link.py`**

```python
"""Calls out of a member, and the storage a commarea shares.

Whole-record aliasing only: a commarea maps the caller's field onto the callee's
DFHCOMMAREA, and matching individual fields inside it needs byte-offset-accurate
layouts, which are out of scope here. Saying record-to-record is the honest answer;
a field-level claim from a name match would be wrong wherever the two sides declare
the area differently, which on a real corpus is most places.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import chain

from cobble.dataflow.srccfg.cfg import Cfg, Node
from cobble.dataflow.srccfg.desugar import CALL_TRANSFERS, CALL_TRANSFER, commarea_field

COMMAREA_RECORD = "DFHCOMMAREA"


@dataclass(frozen=True)
class CallSite:
    caller: str
    node: str
    transfer: str
    program: str
    resolved: bool = True
    commarea: str = ""


@dataclass(frozen=True)
class Alias:
    caller: str
    caller_field: str
    callee: str
    callee_field: str


@dataclass(frozen=True)
class CallGraph:
    sites: tuple[CallSite, ...] = ()
    aliases: tuple[Alias, ...] = ()


def call_sites(cfg: Cfg) -> tuple[CallSite, ...]:
    return tuple(
        CallSite(
            caller=cfg.program,
            node=node.id,
            transfer=node.transfer,
            program=node.target,
            resolved=node.target_resolved,
            commarea=commarea_field(node),
        )
        for node in cfg.nodes
        if node.transfer in CALL_TRANSFERS and node.target
    )


def aliases(cfg: Cfg) -> tuple[Alias, ...]:
    return tuple(
        chain.from_iterable(_aliases_of(cfg, site, node) for site, node in _resolved(cfg))
    )


def _resolved(cfg: Cfg) -> tuple[tuple[CallSite, Node], ...]:
    return tuple(
        (site, cfg.node(site.node)) for site in call_sites(cfg) if site.resolved
    )


def _aliases_of(cfg: Cfg, site: CallSite, node: Node) -> tuple[Alias, ...]:
    if site.transfer == CALL_TRANSFER:
        return tuple(
            Alias(
                caller=cfg.program,
                caller_field=name,
                callee=site.program,
                callee_field=f"%USING[{position}]",
            )
            for position, name in enumerate(node.using)
            if name
        )
    if not site.commarea:
        return ()
    return (
        Alias(
            caller=cfg.program,
            caller_field=site.commarea,
            callee=site.program,
            callee_field=COMMAREA_RECORD,
        ),
    )


def call_graph(cfgs: Iterable[Cfg]) -> CallGraph:
    built = tuple(cfgs)
    return CallGraph(
        sites=tuple(chain.from_iterable(call_sites(cfg) for cfg in built)),
        aliases=tuple(chain.from_iterable(aliases(cfg) for cfg in built)),
    )


def callees_of(graph: CallGraph, program: str) -> tuple[str, ...]:
    return tuple(
        sorted({s.program for s in graph.sites if s.caller == program and s.resolved})
    )


def callers_of(graph: CallGraph, program: str) -> tuple[str, ...]:
    return tuple(
        sorted({s.caller for s in graph.sites if s.program == program and s.resolved})
    )


def unresolved_sites(graph: CallGraph) -> tuple[CallSite, ...]:
    return tuple(site for site in graph.sites if not site.resolved)
```

- [ ] **Step 5: Add the CFG reader to `build_corpus.py`**

A corpus-wide call graph is built from the written CFGs, not by re-lowering 3,779
ASGs, so the JSON has to read back:

```python
def cfg_from_dict(document: Mapping) -> Cfg:
    return Cfg(
        program=str(document.get("program", "")),
        nodes=tuple(_node_of(entry) for entry in document.get("nodes", ())),
        edges=tuple(
            Edge(source=e["source"], target=e["target"], kind=EdgeKind[e["kind"]])
            for e in document.get("edges", ())
        ),
    )


def _node_of(entry: Mapping) -> Node:
    atom = entry.get("atom", {})
    return Node(
        **{
            **{k: v for k, v in entry.items() if k not in ("kind", "atom", "writes", "reads", "using")},
            "kind": NodeKind[entry["kind"]],
            "atom": Atom(**atom),
            "writes": tuple(entry.get("writes", ())),
            "reads": tuple(entry.get("reads", ())),
            "using": tuple(entry.get("using", ())),
        }
    )


def load_cfg(path: Path) -> Cfg:
    return cfg_from_dict(json.loads(path.read_text(encoding="utf-8")))
```

Add a round-trip test to `tests/dataflow/srccfg/test_build_corpus.py`:

```python
def test_a_written_cfg_reads_back_identical(tmp_path: Path) -> None:
    """The corpus call graph is built from the written files, so a lossy round trip
    would silently drop call sites -- and a missing call site reads as a member with
    no callees rather than as an error."""
    from cobble.dataflow.srccfg.build import build_program
    from cobble.dataflow.srccfg.build_corpus import cfg_from_dict

    asg_dir = _cache(tmp_path, "PROGA")
    built = build_one(asg_dir / "PROGA.json", tmp_path / "out")

    assert cfg_from_dict(json.loads(built.cfg_path.read_text())) == _rebuilt(asg_dir)
```

with `_rebuilt` building the same member through `_cfg_of`. If comparing whole `Cfg`
objects fails on the `cached_property` caches, compare `cfg_to_dict` of each instead —
that is the contract that matters.

- [ ] **Step 6: Run the suite and the gates**

```bash
cd cobble
uv run --no-sync python -m pytest tests/dataflow/srccfg -v
uv run --no-sync python -m python_fp_lint check cobble/dataflow/srccfg/
make lint
```

Expected: PASS with zero new violations. `_node_of`'s dict-splat is compact but will
raise `TypeError` on an unexpected key; if a future field breaks it, name the fields
explicitly rather than filtering harder.

- [ ] **Step 7: Commit**

```bash
git add cobble/dataflow/srccfg/link.py cobble/dataflow/srccfg/desugar.py \
  cobble/dataflow/srccfg/cfg.py cobble/dataflow/srccfg/build_corpus.py \
  tests/dataflow/srccfg/test_link.py tests/dataflow/srccfg/test_build_corpus.py
git commit -m "$(cat <<'EOF'
feat(cobble): build a call graph and record commarea aliases

LINK, XCTL and static CALL become CFG nodes carrying a transfer and a target, so a
call site has a node id and therefore a guard. A dynamic program name is kept and
marked unresolved rather than dropped or believed. Commarea aliasing is
record-to-record: field-level matching needs byte-accurate layouts, and a name-based
guess would be wrong wherever the two sides declare the area differently.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---
### Task 16: the query CLI

Everything so far is a library. This task is the thing a person runs: four queries over
one member's CFG, printed as text a reader can check against the listing.

| Query | Answers |
|-------|---------|
| `writers FIELD` | every node that writes it, with the guard each write happens under |
| `guards NODE` | the reaching conditions of one node, one path per line |
| `derivation FIELD` | the definition chain back from every write, guards included |
| `coassign FIELD` | co-assignment candidates, strongest tier first |

Output is plain lines on stdout, and **field and member names go to stdout only** — the
logging channel stays free of them, the same rule the copybook diagnostic follows,
because these names are corpus identifiers and a log gets tailed in shared terminals.

Derivation depth is capped and a truncated chain says so. A chain that stops without
saying it stopped reads as "this field's source is here", which is the one thing the
query must not get wrong.

**Files:**
- Create: `cobble/dataflow/srccfg/render.py`
- Modify: `cobble/pyproject.toml` (`[project.scripts]`)
- Test: `tests/dataflow/srccfg/test_render.py`

**Interfaces:**
- Consumes: `load_cfg` (Task 15); `reaching_conditions`, `guards_of`, `guard_text`,
  `reaching_definitions`, `writers_of`, `Definition` (Task 12/13); `co_assigned`,
  `Tier` (Task 14)
- Produces:
  - `MAX_DEPTH = 6`
  - `writers_report(cfg: Cfg, field: str) -> tuple[str, ...]`
  - `guards_report(cfg: Cfg, node_id: str) -> tuple[str, ...]`
  - `derivation_report(cfg: Cfg, field: str, max_depth: int = MAX_DEPTH) -> tuple[str, ...]`
  - `coassign_report(cfg: Cfg, field: str, min_tier: Tier = Tier.SAME_PARAGRAPH) -> tuple[str, ...]`
  - `main(argv: Sequence[str] = ()) -> int` — entry point `cobble-srccfg`

- [ ] **Step 1: Write the failing tests**

`tests/dataflow/srccfg/test_render.py`:

```python
"""What a person sees. Four queries, plain lines, no name in a log record.

The reports are the only part of this whose correctness a reader can check by hand
against a listing, so each line names the node it is claiming something about.
"""

from __future__ import annotations

import json
from pathlib import Path

from cobol_asg.asg_types import CobolASG

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered

from cobble.dataflow.srccfg.build import build_program
from cobble.dataflow.srccfg.build_corpus import cfg_to_dict
from cobble.dataflow.srccfg.coassign import Tier
from cobble.dataflow.srccfg.render import (
    coassign_report,
    derivation_report,
    guards_report,
    main,
    writers_report,
)


def _asg(statements: list[dict]) -> CobolASG:
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict(
            {"program_id": "PROGA", "paragraphs": [{"name": "MAIN", "statements": statements}]}
        )


def _move(value: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": value}, {"name": target}]}


def _if(condition: dict, then: list[dict], otherwise: list[dict]) -> dict:
    return {
        "type": "IF",
        "condition": condition,
        "then_statements": then,
        "else_statements": otherwise,
    }


def _rel(left: str, op: str, right: str) -> dict:
    return {"kind": "relation", "left": left, "operator": op, "right": right}


def _guarded_cfg():
    return build_program(
        _asg(
            [
                _move("WS-IN", "WS-MID"),
                _if(_rel("WS-FLAG-A", "=", "'Y'"), [_move("WS-MID", "WS-OUT")], []),
            ]
        )
    )


def _written(tmp_path: Path):
    cfg = _guarded_cfg()
    path = tmp_path / "PROGA.json"
    path.write_text(json.dumps(cfg_to_dict(cfg)))
    return path


def test_the_writers_report_names_every_writing_node() -> None:
    lines = writers_report(_guarded_cfg(), "WS-OUT")

    assert any("WS-OUT" in line for line in lines)
    assert any("MAIN/1" in line for line in lines)


def test_the_writers_report_shows_the_guard_of_each_write() -> None:
    """A write with no guard shown reads as unconditional, and 65% of them are not."""
    lines = writers_report(_guarded_cfg(), "WS-OUT")

    assert any("WS-FLAG-A" in line for line in lines)


def test_an_unguarded_write_says_so_rather_than_showing_nothing() -> None:
    """A blank where the guard goes is indistinguishable from a bug in the pass."""
    lines = writers_report(_guarded_cfg(), "WS-MID")

    assert any("unconditional" in line for line in lines)


def test_a_field_nothing_writes_says_so() -> None:
    """The commonest real answer for a field filled by a caller or a file read, and an
    empty report would read as a failed query."""
    lines = writers_report(_guarded_cfg(), "WS-NEVER")

    assert lines
    assert "WS-NEVER" in lines[0]


def test_the_guards_report_prints_one_line_per_path() -> None:
    cfg = build_program(
        _asg(
            [
                _if(_rel("WS-FLAG-A", "=", "'Y'"), [_move("'1'", "WS-X")], []),
                _move("'2'", "WS-AFTER"),
            ]
        )
    )
    writer = next(node.id for node in cfg.nodes if "WS-AFTER" in node.writes)

    lines = guards_report(cfg, writer)

    assert len([line for line in lines if line.startswith("  path")]) == 2


def test_a_negated_guard_reads_as_not() -> None:
    cfg = build_program(
        _asg([_if(_rel("WS-FLAG-A", "=", "'Y'"), [], [_move("'B'", "WS-OUT")])])
    )
    writer = next(node.id for node in cfg.nodes if "WS-OUT" in node.writes)

    assert any("NOT" in line for line in guards_report(cfg, writer))


def test_the_derivation_report_follows_the_chain_back_to_a_source() -> None:
    """WS-OUT comes from WS-MID which comes from WS-IN, and the chain is the answer
    -- one level would stop at the intermediate and say nothing useful."""
    lines = derivation_report(_guarded_cfg(), "WS-OUT")

    assert any("WS-MID" in line for line in lines)
    assert any("WS-IN" in line for line in lines)


def test_the_derivation_report_indents_by_depth() -> None:
    lines = derivation_report(_guarded_cfg(), "WS-OUT")
    depths = [len(line) - len(line.lstrip()) for line in lines if line.strip()]

    assert len(set(depths)) > 1


def test_a_derivation_deeper_than_the_cap_says_it_was_truncated() -> None:
    """Silently stopping is the one failure that turns a useful report into a wrong
    one: the last field shown reads as the source."""
    chain = [_move("WS-F0", "WS-F1"), _move("WS-F1", "WS-F2"), _move("WS-F2", "WS-F3")]
    cfg = build_program(_asg(chain))

    lines = derivation_report(cfg, "WS-F3", max_depth=1)

    assert any("truncated" in line for line in lines)


def test_a_cyclic_derivation_terminates() -> None:
    """COMPUTE WS-A = WS-A + 1 is everywhere, and a naive chase never returns."""
    cfg = build_program(_asg([_move("'0'", "WS-A"), _move("WS-A", "WS-A")]))

    assert derivation_report(cfg, "WS-A")


def test_the_coassign_report_shows_the_tier_of_each_candidate() -> None:
    """The tier is the whole reason a reader can act on the answer, so it cannot be
    dropped to make the line shorter."""
    cfg = build_program(_asg([_move("WS-IN", "WS-A"), _move("WS-IN", "WS-B")]))

    lines = coassign_report(cfg, "WS-A")

    assert any("SAME_SOURCE" in line and "WS-B" in line for line in lines)


def test_the_coassign_report_honours_min_tier() -> None:
    cfg = build_program(_asg([_move("'1'", "WS-A"), _move("'2'", "WS-B")]))

    assert coassign_report(cfg, "WS-A", min_tier=Tier.SAME_SOURCE) == (
        "WS-A: no co-assignment candidates at tier SAME_SOURCE or stronger",
    )


def test_the_cli_prints_the_writers_report_to_stdout(tmp_path: Path, capsys) -> None:
    exit_code = main(["writers", "WS-OUT", "--cfg", str(_written(tmp_path))])

    assert exit_code == 0
    assert "MAIN/1" in capsys.readouterr().out


def test_the_cli_keeps_field_names_out_of_the_log(tmp_path: Path, caplog) -> None:
    """Field names are corpus identifiers. stdout is where the answer goes; a log
    record gets tailed in a shared terminal."""
    import logging

    caplog.set_level(logging.DEBUG)

    main(["writers", "WS-OUT", "--cfg", str(_written(tmp_path))])

    assert "WS-OUT" not in caplog.text


def test_an_unknown_query_exits_non_zero_without_a_traceback(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(SystemExit) as caught:
        main(["nonsense", "WS-OUT", "--cfg", str(_written(tmp_path))])

    assert caught.value.code == 2


def test_a_missing_cfg_file_exits_non_zero_with_a_message(tmp_path: Path, capsys) -> None:
    """A CFG path is typed by hand, so a wrong one is the commonest failure -- and it
    must not look like "this field has no writers"."""
    exit_code = main(["writers", "WS-OUT", "--cfg", str(tmp_path / "gone.json")])

    assert exit_code == 2
    assert "gone.json" in capsys.readouterr().err
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg/test_render.py -v`
Expected: FAIL — `ModuleNotFoundError: cobble.dataflow.srccfg.render`

- [ ] **Step 3: Write `render.py`**

```python
"""Four queries over one member's CFG, printed for a person.

Names go to stdout and nowhere else: they are corpus identifiers, and the pattern the
copybook diagnostic settled on is that the machine channel carries the answer while
the log stays safe to tail.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from cobble.dataflow.srccfg.build_corpus import load_cfg
from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.coassign import Tier, co_assigned
from cobble.dataflow.srccfg.dataflow import (
    Definition,
    Reaching,
    guard_text,
    guards_of,
    reaching_conditions,
    reaching_definitions,
    writers_of,
)

MAX_DEPTH = 6
UNCONDITIONAL = "unconditional"


def writers_report(cfg: Cfg, field: str) -> tuple[str, ...]:
    nodes = writers_of(cfg, field)
    if not nodes:
        return (f"{field}: written nowhere in {cfg.program}",)
    reaching = reaching_conditions(cfg)
    return (
        f"{field}: {len(nodes)} writer(s) in {cfg.program}",
        *tuple(line for node_id in nodes for line in _writer_lines(cfg, reaching, node_id)),
    )


def _writer_lines(cfg: Cfg, reaching: Reaching, node_id: str) -> tuple[str, ...]:
    node = cfg.node(node_id)
    head = f"  {node_id}  {node.transfer or 'ASSIGN'}  reads {', '.join(node.reads) or '(none)'}"
    return (head, *tuple(f"    when {text}" for text in _guard_lines(cfg, reaching, node_id)))


def _guard_lines(cfg: Cfg, reaching: Reaching, node_id: str) -> tuple[str, ...]:
    guards = guards_of(reaching, node_id)
    return tuple(
        " AND ".join(guard_text(cfg, guard)) or UNCONDITIONAL for guard in guards
    ) or (f"unreachable from {cfg.program} entry",)


def guards_report(cfg: Cfg, node_id: str) -> tuple[str, ...]:
    reaching = reaching_conditions(cfg)
    truncated = ("  (truncated: more paths reach this node)",) if node_id in reaching.truncated else ()
    return (
        f"{node_id}: {len(guards_of(reaching, node_id))} path(s)",
        *tuple(f"  path {n}: {text}" for n, text in enumerate(_guard_lines(cfg, reaching, node_id))),
        *truncated,
    )


def derivation_report(cfg: Cfg, field: str, max_depth: int = MAX_DEPTH) -> tuple[str, ...]:
    incoming = reaching_definitions(cfg)
    reaching = reaching_conditions(cfg)
    return (
        f"{field} in {cfg.program}:",
        *_chain(cfg, incoming, reaching, field, 1, max_depth, frozenset()),
    )


def _chain(
    cfg: Cfg,
    incoming,
    reaching: Reaching,
    field: str,
    depth: int,
    max_depth: int,
    seen: frozenset[str],
) -> tuple[str, ...]:
    pad = "  " * depth
    if field in seen:
        return (f"{pad}{field} (already shown)",)
    if depth > max_depth:
        return (f"{pad}{field} (truncated at depth {max_depth})",)
    nodes = writers_of(cfg, field)
    if not nodes:
        return (f"{pad}{field} <- source (written nowhere in this member)",)
    return tuple(
        line
        for node_id in nodes
        for line in _from_node(cfg, incoming, reaching, node_id, depth, max_depth, seen | {field})
    )


def _from_node(
    cfg: Cfg,
    incoming,
    reaching: Reaching,
    node_id: str,
    depth: int,
    max_depth: int,
    seen: frozenset[str],
) -> tuple[str, ...]:
    node = cfg.node(node_id)
    pad = "  " * depth
    when = "; ".join(_guard_lines(cfg, reaching, node_id))
    head = f"{pad}{node_id} {node.transfer or 'ASSIGN'} when {when}"
    return (
        head,
        *tuple(
            line
            for name in node.reads
            for line in _chain(cfg, incoming, reaching, name, depth + 1, max_depth, seen)
        ),
    )


def coassign_report(
    cfg: Cfg, field: str, min_tier: Tier = Tier.SAME_PARAGRAPH
) -> tuple[str, ...]:
    found = co_assigned(cfg, field, reaching_conditions(cfg), min_tier=min_tier)
    if not found:
        return (
            f"{field}: no co-assignment candidates at tier {min_tier.name} or stronger",
        )
    return (
        f"{field}: {len(found)} candidate(s)",
        *tuple(
            f"  {c.tier.name:<15} {c.field}"
            + (f"  shared {', '.join(c.shared)}" if c.shared else "")
            + f"  ({c.nodes[0]} / {c.nodes[1]})"
            for c in found
        ),
    )


_QUERIES = ("writers", "guards", "derivation", "coassign")


def main(argv: Sequence[str] = ()) -> int:
    parser = argparse.ArgumentParser(description="Query one member's source CFG.")
    parser.add_argument("query", choices=_QUERIES)
    parser.add_argument("subject", help="a field name, or a node id for `guards`")
    parser.add_argument("--cfg", required=True, type=Path)
    parser.add_argument("--min-tier", type=int, default=int(Tier.SAME_PARAGRAPH))
    parser.add_argument("--max-depth", type=int, default=MAX_DEPTH)
    arguments = parser.parse_args(tuple(argv) or None)
    if not arguments.cfg.is_file():
        print(f"No CFG at {arguments.cfg}", file=sys.stderr)
        return 2
    for line in _lines(load_cfg(arguments.cfg), arguments):
        print(line)
    return 0


def _lines(cfg: Cfg, arguments) -> tuple[str, ...]:
    if arguments.query == "guards":
        return guards_report(cfg, arguments.subject)
    if arguments.query == "derivation":
        return derivation_report(cfg, arguments.subject, max_depth=arguments.max_depth)
    if arguments.query == "coassign":
        return coassign_report(cfg, arguments.subject, min_tier=Tier(arguments.min_tier))
    return writers_report(cfg, arguments.subject)
```

`print` is what this module is for, so it needs `# noqa: T201` on both `print` calls —
ruff's `select` includes T20 and the ban is right everywhere except a CLI's own output.
Add the pragma rather than removing T20 from the config.

Add to `cobble/pyproject.toml` under `[project.scripts]`:

```toml
cobble-srccfg = "cobble.dataflow.srccfg.render:main"
```

- [ ] **Step 4: Run the suite and the gates**

```bash
cd cobble
uv run --no-sync python -m pytest tests/dataflow/srccfg -v
uv run --no-sync python -m python_fp_lint check cobble/dataflow/srccfg/
make lint
make test
```

Expected: PASS with zero new violations. `_from_node` and `_chain` are mutually
recursive with `seen` carrying the fields already shown, which is what stops
`MOVE WS-A TO WS-A`; if a member still recurses without bound, the missing piece is
`seen` not being threaded through `_from_node`.

`Definition` and `incoming` are passed but only used by later work; if `make lint`
flags the unused import or parameter, drop them from the signatures rather than
keeping a dead parameter.

- [ ] **Step 5: Commit**

```bash
git add cobble/dataflow/srccfg/render.py cobble/pyproject.toml \
  tests/dataflow/srccfg/test_render.py
git commit -m "$(cat <<'EOF'
feat(cobble): add a query CLI for writers, guards, derivation and co-assignment

Four reports over one member's CFG, printed as checkable lines. Names go to stdout
only, and a derivation that hits the depth cap or a cycle says so -- a chain that
stops quietly reads as if the last field shown were the source.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---
### Task 17: acceptance over a real parsed corpus

Every test so far builds its ASG from a dict. That proves the lowering is right about
what it was told and nothing about what real members contain — and the failures that
matter on a corpus are the shapes nobody invented: a paragraph performed from twelve
places, a 400-line `EVALUATE`, a `GO TO` into the middle of a range.

So one test module runs the whole pipeline over whatever members the gitignored
`config/srccfg-tests.toml` points at, and **skips** when there is no config. Skipping
rather than failing is what keeps the suite green on a clean checkout: there is no
corpus in the repo and there must never be one.

The assertions are structural invariants, not values. A corpus-specific expected
number would be both a client identifier and a test that breaks whenever the corpus is
re-parsed.

**Files:**
- Create: `tests/dataflow/srccfg/test_acceptance.py`
- Create: `config/srccfg-tests.example.toml`
- Test: itself

**Interfaces:**
- Consumes: `corpus_asg_paths` fixture (Task 2 conftest); `build_program` (Task 7/8);
  `reaching_conditions`, `reaching_definitions`, `with_handler_edges` (Task 12/13);
  `call_sites` (Task 15); `writers_report` (Task 16); `cfg_to_dict`, `cfg_from_dict`
  (Task 11/15)

- [ ] **Step 1: Write the config example**

`config/srccfg-tests.example.toml`:

```toml
# Copy to config/srccfg-tests.toml to run the acceptance tests against a parsed
# corpus. Without it those tests skip -- there is no corpus in this repo.
[srccfg-tests]
# A directory of CobolASG JSON as written by cobble-parse-corpus.
asg_dir = "/path/to/out-<corpus>-parsed"
# How many members to run. Keep it small; the whole pipeline runs per member.
limit = 40
```

- [ ] **Step 2: Write the test module**

`tests/dataflow/srccfg/test_acceptance.py`:

```python
"""The whole pipeline over real members.

Skips with no config, because the corpus is not in this repo and must not be. The
assertions are invariants rather than values: a member count or a node count would be
both a corpus identifier and a test that breaks on every re-parse.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cobol_asg.asg_types import CobolASG

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered

from cobble.dataflow.srccfg.build import build_program
from cobble.dataflow.srccfg.build_corpus import cfg_from_dict, cfg_to_dict
from cobble.dataflow.srccfg.cfg import EdgeKind, NodeKind
from cobble.dataflow.srccfg.dataflow import (
    reaching_conditions,
    reaching_definitions,
    with_handler_edges,
)
from cobble.dataflow.srccfg.link import call_sites
from cobble.dataflow.srccfg.render import writers_report


def _cfgs(paths):
    with cached_asg_dialect_parsers_registered():
        for path in paths:
            yield path, build_program(
                CobolASG.from_dict(json.loads(path.read_text(encoding="utf-8")))
            )


def test_every_member_builds_a_cfg(corpus_asg_paths) -> None:
    """The first thing that goes wrong at scale is an ASG shape the lowering does not
    handle, and it shows up as an exception on member 40 of 3,779."""
    failures = []
    for path, cfg in _cfgs(corpus_asg_paths):
        if not cfg.nodes:
            failures.append(path.stem)

    assert failures == []


def test_every_edge_lands_on_a_node_that_exists(corpus_asg_paths) -> None:
    """The invariant every later walk depends on. A dangling edge is a KeyError in a
    pass that runs much later, on a member nobody was looking at."""
    for _, cfg in _cfgs(corpus_asg_paths):
        dangling = {
            (edge.source, edge.target)
            for edge in cfg.edges
            if edge.source not in cfg.node_ids or edge.target not in cfg.node_ids
        }
        assert dangling == set(), f"{cfg.program}: {sorted(dangling)[:3]}"


def test_every_node_id_is_unique_within_a_member(corpus_asg_paths) -> None:
    """Node identity is a path, not a line number. A collision silently merges two
    statements, and every guard and definition on both becomes wrong."""
    for _, cfg in _cfgs(corpus_asg_paths):
        ids = [node.id for node in cfg.nodes]
        assert len(ids) == len(set(ids)), cfg.program


def test_every_test_node_has_exactly_two_outgoing_polarities(corpus_asg_paths) -> None:
    """A TEST with one arm makes one polarity unreachable, which silently drops the
    guard for everything on that side."""
    for _, cfg in _cfgs(corpus_asg_paths):
        for node in cfg.nodes:
            if node.kind != NodeKind.TEST:
                continue
            kinds = {edge.kind for edge in cfg.successors(node.id)}
            assert kinds == {EdgeKind.TRUE, EdgeKind.FALSE}, f"{cfg.program} {node.id}"


def test_every_assign_node_writes_or_reads_something(corpus_asg_paths) -> None:
    """An ASSIGN with neither is a verb the flows table has a rule for and no operands
    extracted -- which reads downstream as "this statement moves nothing"."""
    for _, cfg in _cfgs(corpus_asg_paths):
        empty = [
            node.id
            for node in cfg.nodes
            if node.kind == NodeKind.ASSIGN and not (node.writes or node.reads)
        ]
        assert empty == [], f"{cfg.program}: {empty[:3]}"


def test_reaching_conditions_terminate_on_every_member(corpus_asg_paths) -> None:
    """The path walk is capped, so this is really a test that the cap is reached
    rather than the walk diverging -- a member with deep nesting is where an
    unbounded walk stops being a theory."""
    for _, cfg in _cfgs(corpus_asg_paths):
        assert reaching_conditions(cfg).guards


def test_reaching_definitions_terminate_on_every_member(corpus_asg_paths) -> None:
    """The fixpoint has no iteration cap, so a member with a loop through a PERFORM
    range is what would hang it."""
    for _, cfg in _cfgs(corpus_asg_paths):
        assert reaching_definitions(cfg)


def test_most_members_have_at_least_one_guarded_assignment(corpus_asg_paths) -> None:
    """The aggregate the design rests on: guards are the common case, not the exotic
    one. A pass that produced almost none would still satisfy every unit test above.
    """
    guarded = 0
    total = 0
    for _, cfg in _cfgs(corpus_asg_paths):
        total = total + 1
        reaching = reaching_conditions(cfg)
        if any(
            any(guard for guard in reaching.guards.get(node.id, ()))
            for node in cfg.nodes
            if node.kind == NodeKind.ASSIGN
        ):
            guarded = guarded + 1

    assert guarded > total // 2, f"{guarded} of {total} members had a guarded write"


def test_handler_resolution_adds_no_dangling_edge(corpus_asg_paths) -> None:
    for _, cfg in _cfgs(corpus_asg_paths):
        resolved = with_handler_edges(cfg)
        assert all(edge.target in resolved.node_ids for edge in resolved.edges), cfg.program


def test_every_call_site_names_a_program_or_a_field(corpus_asg_paths) -> None:
    """An empty program on a call site collapses every unparsed call onto one graph
    node, which reads as a hub in the call graph that does not exist."""
    for _, cfg in _cfgs(corpus_asg_paths):
        assert all(site.program for site in call_sites(cfg)), cfg.program


def test_a_cfg_round_trips_through_json(corpus_asg_paths) -> None:
    """The corpus call graph reads the written files, so a lossy round trip drops call
    sites -- and a dropped call site reads as a member with no callees."""
    for _, cfg in _cfgs(corpus_asg_paths):
        assert cfg_to_dict(cfg_from_dict(cfg_to_dict(cfg))) == cfg_to_dict(cfg)


def test_a_report_can_be_rendered_for_a_field_the_member_writes(corpus_asg_paths) -> None:
    """End to end: build, analyse, render. A report that raises on a real member is
    the failure a person meets first."""
    for _, cfg in _cfgs(corpus_asg_paths):
        written = next(
            (name for node in cfg.nodes for name in node.writes),
            "",
        )
        if not written:
            continue
        assert writers_report(cfg, written)
```

- [ ] **Step 3: Run with no config and confirm the module skips**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/srccfg/test_acceptance.py -v`
Expected: every test SKIPPED, with the skip reason naming `config/srccfg-tests.toml`.
If any test ERRORs instead, `corpus_asg_paths` is raising rather than calling
`pytest.skip` — fix the conftest fixture from Task 2, not this module.

- [ ] **Step 4: Run with a config against a parsed corpus**

```bash
cd cobble
cp config/srccfg-tests.example.toml config/srccfg-tests.toml
# edit asg_dir to a real out-<corpus>-parsed directory, keep limit small
uv run --no-sync python -m pytest tests/dataflow/srccfg/test_acceptance.py -v
```

Expected: PASS. Real failures here are findings, not test bugs — for each one, add a
unit test in the task that owns the shape (a dangling edge belongs to Task 7's
`resolve_targets`, an empty ASSIGN to Task 4's `_writes_reads`), fix it there, and
leave this module alone. Raise `limit` and re-run once each is fixed.

- [ ] **Step 5: Confirm the corpus config never lands in git**

```bash
cd cobble
git status --porcelain config/
git check-ignore -v config/srccfg-tests.toml
```

Expected: `git status` shows only `config/srccfg-tests.example.toml`, and
`check-ignore` confirms the real one is ignored. If it is not ignored, stop and fix
`.gitignore` from Task 11 before committing anything.

- [ ] **Step 6: Full gates**

```bash
cd cobble
make fmt
make lint
make test
uv run --no-sync python -m python_fp_lint check cobble/dataflow/srccfg/
```

Expected: all clean, zero new fp-lint violations. A `uv` failure reading
`Operation not permitted` is the sandbox, not the code.

- [ ] **Step 7: Commit**

```bash
git add tests/dataflow/srccfg/test_acceptance.py config/srccfg-tests.example.toml
git commit -m "$(cat <<'EOF'
test(cobble): assert source CFG invariants over a real parsed corpus

Structural invariants only -- unique node ids, no dangling edges, two polarities per
test, terminating analyses -- so nothing here encodes a corpus value. Skips without a
config, because the corpus is not in this repo.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Out of scope

Named here so nobody adds them mid-plan. Each was considered and deferred by an
explicit decision:

- **Condition representation iteration** — no normal form, no solver, no simplifier.
  The CFG is the condition language.
- **Dynamic program targets** — kept and marked unresolved (Task 15); resolving them
  by reaching definitions over the target field is a follow-up.
- **`EXEC SQL` host variables** — SQL text stays opaque, so a host variable is neither
  a read nor a write yet.
- **Line-number provenance** — no ASG statement carries a line, so node identity is a
  path. Adding lines needs bridge work.
- **Byte-offset-accurate commarea layouts** — aliasing stays record-to-record
  (Task 15).
- **Method-level call trees and the EL-side CFG** — separate subsystems, separate
  specs.
