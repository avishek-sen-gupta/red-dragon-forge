# src-cfg files as JSONL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every src-cfg file becomes JSONL -- one typed row per program, node, edge and call -- read and written only by `cobble/dataflow/srccfg/bundle.py`, with no reader indexing parsed JSON.

**Architecture:** Three commits. (1) The three readers that walk parsed dicts move onto the typed `Bundle` that `load_bundle` already returns, with the file format unchanged. (2) Pydantic row models for the four row types, each converting to and from its typed value, round-tripped in isolation. (3) The flip: `bundle.py` writes and reads rows instead of one document, both writers and every test that writes a CFG file move with it, and the README changes in the same commit.

**Tech Stack:** Python 3.13, Pydantic v2 (`BaseModel`, `TypeAdapter`, `PlainValidator`, `PlainSerializer`), pytest, uv workspace (`cobble` member).

**Spec:** `docs/superpowers/specs/2026-10-02-srccfg-jsonl-design.md`

## Global Constraints

- Every Python command runs from `~/code/red-dragon-forge/cobble` as `uv run --no-sync python -m pytest ...`. cobble's tests need no `bridge-env.sh`.
- The commit hooks are the gate: python-fp-lint, Black, Pyright (strict, on staged files), import-linter, the test suites, the terminology guard on the diff and the message, Talisman. `--no-verify` is never used. A hook failure is fixed in the code, the test or the message.
- Before each commit also run: `make fmt` (repo root), `uv run --no-sync pyright <the files you touched>` (repo root), `uv run --no-sync lint-imports` (repo root), and the whole cobble suite: `uv run --no-sync python -m pytest -q -n auto` (in `cobble/`).
- python-fp-lint: no `for` loops with mutation, no `.append`/`.update`/subscript assignment, no `is None`/`is not None`, no `Any`, no `object`, frozen dataclasses only, complexity at most 3 per function, at most 10 statements per function. Comprehensions, `reduce`, `groupby` are the tools.
- Pydantic models: `model_config = ConfigDict(frozen=True, extra="forbid")`. One class per file.
- Talisman and the terminology guard have flagged the words "key", "pass", "passed", "bypass" in this repo before. Do not use them in identifiers, test names, docstrings or commit messages.
- Do not modify anything under `vendor/`.
- Docstrings match the surrounding code's density; no `#` comments.
- Commit messages end with:
  ```
  ```

## Review Focus

1. **A row naming a program no `program` row declared** (a hand-edited or spliced file): the reader should refuse it with a `CfgDocumentError` naming the program, not crash with a `KeyError`. Test in Task 3.
2. **Blank lines, including a trailing newline**: skipped, never an error. Test in Task 3.
3. **A program with no nodes**: still a `Cfg` in the bundle, in its place in the order. Test in Task 3 (bundle round trip).
4. **Non-ASCII text in a node** (an atom's text, a `target` with a national character): survives the write and read byte for byte. Test in Task 2 (node round trip).
5. **A file truncated mid-line** (a writer killed partway): refused with the line number, so the reader knows where it broke. Covered by Task 3's invalid-line test, whose bad line is a truncated row.

---

## File Structure

| File | Task | Responsibility |
|---|---|---|
| `cobble/cobble/viz/sequence_cmd.py` | 1 | modify: index typed `Cfg`/`Node`/`Edge` instead of dicts |
| `cobble/cobble/viz/callgraph_cmd.py` | 1 | modify: program names from `load_bundle` |
| `cobble/cobble/dataflow/fields/access.py` | 1 | modify: read typed `Node`s |
| `cobble/cobble/dataflow/srccfg/bundle.py` | 1, 3 | 1: drop the raw-dict readers; 3: rows in place of the document |
| `cobble/cobble/dataflow/srccfg/rows/__init__.py` | 2 | create: package header |
| `cobble/cobble/dataflow/srccfg/rows/cfg_row_type.py` | 2 | create: `CfgRowType` |
| `cobble/cobble/dataflow/srccfg/rows/program_row.py` | 2 | create: `CfgProgramRow` |
| `cobble/cobble/dataflow/srccfg/rows/node_row.py` | 2 | create: `CfgNodeRow` |
| `cobble/cobble/dataflow/srccfg/rows/edge_row.py` | 2 | create: `CfgEdgeRow` |
| `cobble/cobble/dataflow/srccfg/rows/call_row.py` | 2 | create: `CfgCallRow` |
| `cobble/cobble/dataflow/srccfg/rows/cfg_row.py` | 2 | create: the `CfgRow` union and the four row builders |
| `cobble/cobble/dataflow/srccfg/build_corpus.py` | 3 | modify: write `<program>.jsonl` |
| `cobble/cobble/dataflow/srccfg/closure.py` | 3 | modify: write rows |
| `cobble/README.md` | 3 | modify: the two format descriptions and the file names |
| tests (listed per task) | 1-3 | modify / create |

---

### Task 1: The raw readers onto `Bundle`

**Files:**
- Modify: `cobble/cobble/viz/sequence_cmd.py` (the dict aliases at lines ~40-56, `_entry_paragraph`, `_perform_paras`, `_add_perform`, `_collect_performs`, `_add_node_link_decision`, `_index_cfg`, `extract_per_program`, `_emit_callee`, `_walk_cross`, `extract_cross_program`, `_run`)
- Modify: `cobble/cobble/viz/callgraph_cmd.py:105-106`
- Modify: `cobble/cobble/dataflow/fields/access.py` (lines ~25-51 helpers, `_names_from_node`, `_rows_for_node`, `_rows_for_program`, `accesses`)
- Modify: `cobble/cobble/dataflow/srccfg/bundle.py` (delete `cfg_dicts_of`, `load_cfg_dicts`)
- Test: `cobble/tests/viz/test_sequence.py`, `cobble/tests/dataflow/fields/test_fields_access.py`, `cobble/tests/dataflow/srccfg/test_bundle.py`

**Interfaces:**
- Consumes: `load_bundle(path: Path) -> Bundle`, `Bundle.cfgs: tuple[Cfg, ...]`, `bundle_to_json(bundle: Bundle) -> str` (all existing in `bundle.py`); `Cfg(program, nodes, edges)`, `Node`, `Edge`, `NodeKind`, `EdgeKind`, `Atom` from `cobble.dataflow.srccfg.cfg`.
- Produces: `extract_per_program(cfg: Cfg) -> ProgramSequence`; `extract_cross_program(entry_program: str, cfg_by_prog: Mapping[str, Cfg], target_programs: frozenset[str], cfg_indices: Mapping[str, _Index]) -> CrossProgramSequence`; `_names_from_node(node: Node) -> tuple[str, ...]`; `accesses(cfg_path: Path, asg_dir: Path) -> tuple[AccessRow, ...]` (unchanged signature). `cfg_dicts_of` and `load_cfg_dicts` no longer exist.

- [ ] **Step 1: Make the tests feed typed CFGs.**

In `cobble/tests/viz/test_sequence.py`, replace the three dict builders and `CFG` (lines 16-62) with typed ones, and add the imports:

```python
from cobble.dataflow.srccfg.cfg import Atom, Cfg, Edge, EdgeKind, Node, NodeKind
from cobble.viz.models import Arm
from cobble.viz.render_cmd import _render_program
from cobble.viz.sequence_cmd import extract_per_program


def _label(paragraph: str) -> Node:
    return Node(id=f"{paragraph}#label", kind=NodeKind.LABEL, paragraph=paragraph)


def _perform(site: str) -> Node:
    return Node(
        id=site,
        kind=NodeKind.CALL,
        paragraph=site.split("/")[0],
        transfer="PERFORM",
    )


def _test(node_id: str, text: str) -> Node:
    return Node(
        id=node_id,
        kind=NodeKind.TEST,
        paragraph=node_id.split("/")[0],
        atom=Atom(text=text),
    )
```

`SITES` stays as it is. `CFG` becomes:

```python
CFG = Cfg(
    program="PROG",
    nodes=(
        *(_label(p) for p in ("0000-MAIN", "A-PARA", "S-PARA", "P-PARA", "R-PARA")),
        _test("0000-MAIN/1.when.0#test", "ENTER"),
        _test("0000-MAIN/1.when.1#test", "REENTER"),
        _test("0000-MAIN/1.when.1.1#test", "INPUT-ERROR"),
        _test("S-PARA/0#test", "FLAG"),
        *(_perform(site) for site, _ in SITES),
    ),
    edges=tuple(
        Edge(source=site, target=f"{target}#label", kind=EdgeKind.PERFORM)
        for site, target in SITES
    ),
)
```

In `cobble/tests/dataflow/fields/test_fields_access.py`:

- Replace the five `_names_from_node` tests' dict nodes with typed nodes, keeping each assertion exactly as it is:

```python
from cobble.dataflow.srccfg.bundle import Bundle, CfgDocumentError, bundle_to_json
from cobble.dataflow.srccfg.cfg import Atom, Cfg, Node, NodeKind


def _assign(*reads: str) -> Node:
    return Node(id="MAIN/0", kind=NodeKind.ASSIGN, paragraph="MAIN", reads=reads)


def _condition(left: str, right: str) -> Node:
    return Node(
        id="MAIN/0",
        kind=NodeKind.TEST,
        paragraph="MAIN",
        atom=Atom(text=f"{left} = {right}", left=left, op="==", right=right),
    )


def test_assign_node_uses_reads():
    assert _names_from_node(_assign("WS-A", "WS-B")) == ("WS-A", "WS-B")


def test_test_node_uses_atom_left_right():
    assert _names_from_node(_condition("WS-STATUS", "'Y'")) == ("WS-STATUS",)


def test_test_node_both_sides_real():
    assert set(_names_from_node(_condition("WS-A", "WS-B"))) == {"WS-A", "WS-B"}


def test_names_are_deduped():
    assert _names_from_node(_assign("WS-A", "WS-A")) == ("WS-A",)


def test_synthetics_filtered_from_reads():
    assert _names_from_node(_assign("%HANDLER", "WS-REAL", "FILE:X")) == ("WS-REAL",)
```

- Replace `_minimal_cfg` with a writer of typed CFGs, used by every `accesses` test (this helper is the one line Task 3 changes):

```python
def _write_cfgs(path: Path, *cfgs: Cfg) -> Path:
    path.write_text(
        bundle_to_json(Bundle(seed=cfgs[0].program, cfgs=cfgs)), encoding="utf-8"
    )
    return path


def _program(name: str, *nodes: Node) -> Cfg:
    return Cfg(program=name, nodes=nodes, edges=())
```

  and in each `accesses` test replace the dict CFG and its `write_text` with, for example:

```python
    cfg_path = _write_cfgs(tmp_path / "cfg.json", _program("PROG", _assign("WS-A")))
```

  (`test_accesses_emits_row_for_test_condition` uses `_condition(...)` with the operands its dict had; `test_accesses_dedupes_same_site_field` uses `_assign("WS-A", "WS-A")`; `test_accesses_spans_every_program_a_bundle_carries` writes `_program("PROG", _assign("WS-A"))` and `_program("PROG2", _assign("WS-A"))`; `_one_assign_program` returns `asg_dir` and `_program("PROG", _assign("WS-A"))`.) `test_accesses_refuses_a_pre_bundle_file` keeps writing its two old-shape documents with `json.dumps`, unchanged.

In `cobble/tests/dataflow/srccfg/test_bundle.py`:

- Delete `test_a_reader_that_wants_the_json_sees_the_one_shape` (the function it covers is removed).
- In `test_a_pre_bundle_file_is_refused_and_says_how_to_rebuild`, delete the second `with pytest.raises(..., match="cobble-srccfg-build"): load_cfg_dicts(path)` block; the `load_bundle` assertion stays.
- Remove `cfg_dicts_of` and `load_cfg_dicts` from the import list.

- [ ] **Step 2: Run the tests to see them fail.**

Run: `uv run --no-sync python -m pytest tests/viz/test_sequence.py tests/dataflow/fields/test_fields_access.py tests/dataflow/srccfg/test_bundle.py -q`
Expected: FAIL. `test_sequence` errors with `AttributeError: 'Cfg' object has no attribute 'get'`; the `_names_from_node` tests with `AttributeError: 'Node' object has no attribute 'get'`. `test_bundle` passes (it only lost code).

- [ ] **Step 3: Move `sequence_cmd.py` onto typed CFGs.**

Imports: replace `from cobble.dataflow.srccfg.bundle import JsonValue, load_cfg_dicts` with

```python
from cobble.dataflow.srccfg.bundle import load_bundle
from cobble.dataflow.srccfg.cfg import Cfg, Edge, EdgeKind, Node, NodeKind
```

Delete the `CfgNode`/`CfgEdge`/`CfgDict` aliases, `_atom` and `_rows`. Replace the dict-reading functions with:

```python
def _entry_paragraph(cfg: Cfg) -> str:
    return next(
        (
            node.paragraph
            for node in cfg.nodes
            if node.kind is NodeKind.LABEL
            and any(node.paragraph.startswith(px) for px in _MAIN_PREFIXES)
        ),
        "",
    )


def _perform_paras(edge: Edge, nodes_by_id: Mapping[str, Node]) -> tuple[str, str]:
    """Return (src_para, tgt_para) for a PERFORM edge; either may be ''."""
    if edge.kind is not EdgeKind.PERFORM:
        return "", ""
    src_para = nodes_by_id[edge.source].paragraph if edge.source in nodes_by_id else ""
    tgt_para = edge.target.replace("#label", "").replace("#end", "")
    return src_para, tgt_para


def _add_perform(
    acc: PerformsAcc, edge: Edge, nodes_by_id: Mapping[str, Node]
) -> PerformsAcc:
    src_para, tgt_para = _perform_paras(edge, nodes_by_id)
    if not src_para or not tgt_para or src_para == tgt_para:
        return acc
    site = _Site(node=edge.source, target=tgt_para)
    return {**acc, src_para: (*acc.get(src_para, ()), site)}


def _collect_performs(
    edges: Sequence[Edge],
    nodes_by_id: Mapping[str, Node],
) -> PerformsAcc:
    return reduce(lambda acc, e: _add_perform(acc, e, nodes_by_id), edges, {})


def _add_node_link_decision(acc: _LinksDecisions, node: Node) -> _LinksDecisions:
    if not node.paragraph:
        return acc
    has_decision = (
        {**acc.para_has_decision, node.paragraph: True}
        if node.kind is NodeKind.TEST
        else acc.para_has_decision
    )
    is_cics_call = node.kind is NodeKind.CALL and "CICS" in node.transfer
    para_link = (
        {**acc.para_link, node.paragraph: node.target}
        if is_cics_call and node.paragraph not in acc.para_link and node.target
        else acc.para_link
    )
    return _LinksDecisions(para_link=para_link, para_has_decision=has_decision)


def _index_cfg(cfg: Cfg) -> _Index:
    nodes_by_id = {node.id: node for node in cfg.nodes}
    ld = reduce(_add_node_link_decision, cfg.nodes, _LinksDecisions({}, {}))
    return _Index(
        performs=_collect_performs(cfg.edges, nodes_by_id),
        links=ld.para_link,
        has_decision=ld.para_has_decision,
        node_ids=frozenset(nodes_by_id),
        tests={
            node.id: node.atom.text
            for node in cfg.nodes
            if node.kind is NodeKind.TEST
        },
    )


def extract_per_program(cfg: Cfg) -> ProgramSequence:
    entry = _entry_paragraph(cfg)
    if not entry:
        return ProgramSequence(program=cfg.program, entry_paragraph="", steps=())
    steps = _steps_of(entry, _index_cfg(cfg), frozenset({entry}), depth=1)
    return ProgramSequence(program=cfg.program, entry_paragraph=entry, steps=steps)
```

In `_emit_callee`, `_walk_cross` and `extract_cross_program`, change every `cfg_by_prog: Mapping[str, CfgDict]` to `cfg_by_prog: Mapping[str, Cfg]`; their bodies need no other change. `_run` becomes:

```python
def _run(args: argparse.Namespace) -> None:
    cfg_by_prog = {cfg.program: cfg for cfg in load_bundle(args.cfg).cfgs}
    targets = frozenset(cfg_by_prog)
    entry = args.entry or next(iter(sorted(targets)))
    cfg_indices = {prog: _index_cfg(cfg) for prog, cfg in cfg_by_prog.items()}
    per_program = {prog: extract_per_program(cfg_by_prog[prog]) for prog in sorted(targets)}
    _write_output(
        args,
        extract_cross_program(entry, cfg_by_prog, targets, cfg_indices),
        per_program,
    )
```

- [ ] **Step 4: Move `callgraph_cmd.py` and `access.py` onto typed CFGs.**

`callgraph_cmd.py`: replace `from cobble.dataflow.srccfg.bundle import load_cfg_dicts` with `from cobble.dataflow.srccfg.bundle import load_bundle`, and in `_run` replace the two lines `cfgs_raw = load_cfg_dicts(args.cfg)` / `targets = frozenset(c["program"] for c in cfgs_raw)` with:

```python
    targets = frozenset(cfg.program for cfg in load_bundle(args.cfg).cfgs)
```

`access.py`: replace `from cobble.dataflow.srccfg.bundle import JsonValue, load_cfg_dicts` with

```python
from cobble.dataflow.srccfg.bundle import load_bundle
from cobble.dataflow.srccfg.cfg import Cfg, Node, NodeKind
```

delete `_JsonRow`, `_submapping`, `_subrows` and `_strings`, and replace the four node-reading functions:

```python
def _names_from_node(node: Node) -> tuple[str, ...]:
    """Field names read at this node, deduped, synthetics removed."""
    reads = _real_names(node.reads)
    if node.kind is NodeKind.TEST:
        extra = _real_names((node.atom.left, node.atom.right))
        return tuple(dict.fromkeys((*reads, *extra)))
    return reads


def _rows_for_node(program: str, node: Node, idx: CellIndex) -> tuple[AccessRow, ...]:
    return tuple(
        AccessRow(
            program=program,
            site=f"{program}/{node.id}",
            paragraph=node.paragraph,
            extent=extent,
        )
        for name in _names_from_node(node)
        for extent in operand_extents(RefModOperand(name=name), idx).extents
    )


def _rows_for_program(cfg: Cfg, asg_dir: Path) -> tuple[AccessRow, ...]:
    logger.info("access: %s", cfg.program)
    indices = _try_index(cfg.program, asg_dir)
    if not indices:
        return ()
    rows = tuple(
        row for node in cfg.nodes for row in _rows_for_node(cfg.program, node, indices[0])
    )
    logger.info("access: %s — %d rows", cfg.program, len(rows))
    return rows


def accesses(cfg_path: Path, asg_dir: Path) -> tuple[AccessRow, ...]:
    """All access rows across every program in ``cfg_path``."""
    all_rows = tuple(
        row
        for cfg in load_bundle(cfg_path).cfgs
        for row in _rows_for_program(cfg, asg_dir)
    )
    keyed = {
        (row.site, row.extent.field_name, row.extent.start): row for row in all_rows
    }
    return tuple(keyed.values())
```

Keep `import json` (it still reads the ASG). Remove `Mapping` from the `collections.abc` import if nothing else uses it.

- [ ] **Step 5: Remove the raw-dict readers from `bundle.py`.**

Delete `load_cfg_dicts`. Rename `cfg_dicts_of` to `_cfg_entries` (it is still what `bundle_of` reads through) and update its one caller in `bundle_of`. Then confirm nothing else names the old functions:

Run: `rg -n "load_cfg_dicts|cfg_dicts_of|JsonValue" cobble tests ../red_dragon_forge ../tests`
Expected: matches only inside `cobble/dataflow/srccfg/bundle.py` (`JsonValue` stays there until Task 3).

- [ ] **Step 6: Run the tests.**

Run: `uv run --no-sync python -m pytest tests/viz tests/dataflow/fields/test_fields_access.py tests/dataflow/srccfg/test_bundle.py -q`
Expected: PASS, with every assertion unchanged from before Step 1.

- [ ] **Step 7: Mutation-check.** In `access.py` change `if node.kind is NodeKind.TEST:` to `if node.kind is NodeKind.ASSIGN:`; run `tests/dataflow/fields/test_fields_access.py` -- `test_test_node_uses_atom_left_right` must FAIL. Restore. In `sequence_cmd.py` change `if edge.kind is not EdgeKind.PERFORM:` to `if edge.kind is EdgeKind.PERFORM:`; run `tests/viz/test_sequence.py` -- FAIL. Restore.

- [ ] **Step 8: Gate and commit.**

Run the Global Constraints gate (fmt, pyright on the four modules and three test files, lint-imports, the whole cobble suite). Then:

```bash
git add cobble/cobble/viz/sequence_cmd.py cobble/cobble/viz/callgraph_cmd.py \
  cobble/cobble/dataflow/fields/access.py cobble/cobble/dataflow/srccfg/bundle.py \
  cobble/tests/viz/test_sequence.py cobble/tests/dataflow/fields/test_fields_access.py \
  cobble/tests/dataflow/srccfg/test_bundle.py
git commit -m "refactor(cobble): the CFG readers that walked parsed JSON read typed CFGs

sequence_cmd, callgraph_cmd and fields.access indexed the parsed document
(node.get(\"kind\"), entry[\"program\"]). They now read the Cfgs load_bundle
builds, and load_cfg_dicts is gone. The file format is unchanged.

```

---

### Task 2: The row types

**Files:**
- Create: `cobble/cobble/dataflow/srccfg/rows/__init__.py`, `cfg_row_type.py`, `program_row.py`, `node_row.py`, `edge_row.py`, `call_row.py`, `cfg_row.py`
- Test: `cobble/tests/dataflow/srccfg/test_cfg_rows.py` (create)

**Interfaces:**
- Consumes: `Node`, `Edge`, `NodeKind`, `EdgeKind`, `Atom`, `SourceSpan` from `cobble.dataflow.srccfg.cfg`; `BundleCall` from `cobble.dataflow.srccfg.link`; `RefModOperand` from `cobol_asg.ref_mod` (with `RefModOperand.from_dict(data: dict)` and `.to_dict() -> dict`).
- Produces (Task 3 relies on these exact names):
  - `CfgRowType(StrEnum)`: `PROGRAM = "program"`, `NODE = "node"`, `EDGE = "edge"`, `CALL = "call"`.
  - `CfgProgramRow(program: str)`; `CfgNodeRow(program: str, <every Node field>)` with `.to_node() -> Node`; `CfgEdgeRow(program, source, target, kind: EdgeKind)` with `.to_edge() -> Edge`; `CfgCallRow(<every BundleCall field>)` with `.to_call() -> BundleCall`. Every row has `type: Literal[CfgRowType.<X>]`.
  - In `rows/cfg_row.py`: `CfgRow = CfgProgramRow | CfgNodeRow | CfgEdgeRow | CfgCallRow`; `CFG_ROWS: TypeAdapter[CfgRow]`; `program_row(program: str) -> CfgProgramRow`; `node_row(program: str, node: Node) -> CfgNodeRow`; `edge_row(program: str, edge: Edge) -> CfgEdgeRow`; `call_row(call: BundleCall) -> CfgCallRow`.

- [ ] **Step 1: Write the failing round-trip tests.**

Create `cobble/tests/dataflow/srccfg/test_cfg_rows.py`:

```python
"""Each src-cfg row type, written as one JSON line and read back as the value it holds."""

from __future__ import annotations

import pytest
from cobble.dataflow.srccfg.cfg import Atom, Edge, EdgeKind, Node, NodeKind, SourceSpan
from cobble.dataflow.srccfg.link import BundleCall
from cobble.dataflow.srccfg.rows.call_row import CfgCallRow
from cobble.dataflow.srccfg.rows.cfg_row import (
    CFG_ROWS,
    call_row,
    edge_row,
    node_row,
    program_row,
)
from cobble.dataflow.srccfg.rows.edge_row import CfgEdgeRow
from cobble.dataflow.srccfg.rows.node_row import CfgNodeRow
from cobble.dataflow.srccfg.rows.program_row import CfgProgramRow
from cobol_asg.ref_mod import RefModLiteral, RefModOperand

NODE = Node(
    id="MAIN/3",
    kind=NodeKind.CALL,
    paragraph="MAIN",
    atom=Atom(text="WS-NAME = 'ÄÖÜ £'", left="WS-NAME", op="==", right="'ÄÖÜ £'"),
    writes=("WS-RET",),
    reads=("WS-PGM", "WS-ARG"),
    transfer="CALL",
    target="WS-PGM",
    target_resolved=False,
    target_operand=RefModOperand(
        name="WS-PGM",
        ref_mod_start=RefModLiteral("1"),
        ref_mod_length=RefModLiteral("8"),
    ),
    transfer_operand="WS-PGM",
    using=("WS-ARG",),
    span=SourceSpan(line_start=12, col_start=8, line_end=12, col_end=30, source_file="PROGA.cbl"),
    resume="MAIN/4",
)


def test_a_node_row_holds_every_field_of_its_node_and_reads_back_equal() -> None:
    """Every Node field crosses the line: a field the row dropped would be a fact a
    reader of the file silently lacks."""
    line = node_row("PROGA", NODE).model_dump_json()

    read = CFG_ROWS.validate_json(line)

    assert isinstance(read, CfgNodeRow)
    assert (read.program, read.to_node()) == ("PROGA", NODE)


@pytest.mark.parametrize("kind", tuple(EdgeKind))
def test_an_edge_row_reads_back_as_its_edge_for_every_kind(kind: EdgeKind) -> None:
    edge = Edge(source="MAIN/0", target="MAIN/1", kind=kind)

    read = CFG_ROWS.validate_json(edge_row("PROGA", edge).model_dump_json())

    assert isinstance(read, CfgEdgeRow)
    assert (read.program, read.to_edge()) == ("PROGA", edge)


def test_a_program_row_and_a_call_row_read_back_as_what_they_hold() -> None:
    call = BundleCall(
        caller="PROGA",
        node="MAIN/3",
        transfer="CICS_XCTL",
        program="PROGB",
        entry="MAIN#label",
        resolved=False,
        commarea="WS-COMM",
        expression="WS-PGM",
        reasons=("from-callee", "inbound-linkage"),
        certain=False,
    )

    program = CFG_ROWS.validate_json(program_row("PROGA").model_dump_json())
    called = CFG_ROWS.validate_json(call_row(call).model_dump_json())

    assert isinstance(program, CfgProgramRow)
    assert program.program == "PROGA"
    assert isinstance(called, CfgCallRow)
    assert called.to_call() == call


def test_a_row_with_an_unknown_type_or_a_stray_field_is_refused() -> None:
    """The union is closed: a misspelt type or a field no row declares is an error,
    never a row quietly read as something else."""
    with pytest.raises(ValueError, match="program"):
        CFG_ROWS.validate_json('{"type": "programme", "program": "PROGA"}')
    with pytest.raises(ValueError, match="extra"):
        CFG_ROWS.validate_json('{"type": "program", "program": "PROGA", "seed": true}')
```

- [ ] **Step 2: Run them to see them fail.**

Run: `uv run --no-sync python -m pytest tests/dataflow/srccfg/test_cfg_rows.py -q`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'cobble.dataflow.srccfg.rows'`.

- [ ] **Step 3: Write the row types.**

`cobble/cobble/dataflow/srccfg/rows/__init__.py`:

```python
"""One line of a src-cfg file: a program, a node, an edge or a call."""
```

`cobble/cobble/dataflow/srccfg/rows/cfg_row_type.py`:

```python
"""What one line of a src-cfg file holds."""

from enum import StrEnum


class CfgRowType(StrEnum):
    PROGRAM = "program"
    NODE = "node"
    EDGE = "edge"
    CALL = "call"
```

`cobble/cobble/dataflow/srccfg/rows/program_row.py`:

```python
"""A src-cfg row opening one program's CFG."""

from typing import Literal

from cobble.dataflow.srccfg.rows.cfg_row_type import CfgRowType
from pydantic import BaseModel, ConfigDict


class CfgProgramRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[CfgRowType.PROGRAM]
    program: str
```

`cobble/cobble/dataflow/srccfg/rows/node_row.py`:

```python
"""A src-cfg row holding one CFG node."""

from typing import Annotated, Literal

from cobble.dataflow.srccfg.cfg import Atom, Node, NodeKind, SourceSpan
from cobble.dataflow.srccfg.rows.cfg_row_type import CfgRowType
from cobol_asg.ref_mod import RefModOperand
from pydantic import BaseModel, ConfigDict, PlainSerializer, PlainValidator


def _operand_of(raw: RefModOperand | dict) -> RefModOperand:
    """A row built from a Node holds the operand itself; a row read from a line holds
    the object RefModOperand.to_dict wrote, which its own from_dict reads."""
    if isinstance(raw, RefModOperand):
        return raw
    return RefModOperand.from_dict(raw)


def _operand_dict(operand: RefModOperand) -> dict:
    return operand.to_dict()


Operand = Annotated[
    RefModOperand, PlainValidator(_operand_of), PlainSerializer(_operand_dict)
]


class CfgNodeRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[CfgRowType.NODE]
    program: str
    id: str
    kind: NodeKind
    paragraph: str
    atom: Atom
    writes: tuple[str, ...]
    reads: tuple[str, ...]
    transfer: str
    target: str
    target_resolved: bool
    target_operand: Operand
    transfer_operand: str
    using: tuple[str, ...]
    span: SourceSpan
    resume: str

    def to_node(self) -> Node:
        return Node(
            id=self.id,
            kind=self.kind,
            paragraph=self.paragraph,
            atom=self.atom,
            writes=self.writes,
            reads=self.reads,
            transfer=self.transfer,
            target=self.target,
            target_resolved=self.target_resolved,
            target_operand=self.target_operand,
            transfer_operand=self.transfer_operand,
            using=self.using,
            span=self.span,
            resume=self.resume,
        )
```

`cobble/cobble/dataflow/srccfg/rows/edge_row.py`:

```python
"""A src-cfg row holding one CFG edge."""

from typing import Literal

from cobble.dataflow.srccfg.cfg import Edge, EdgeKind
from cobble.dataflow.srccfg.rows.cfg_row_type import CfgRowType
from pydantic import BaseModel, ConfigDict


class CfgEdgeRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[CfgRowType.EDGE]
    program: str
    source: str
    target: str
    kind: EdgeKind

    def to_edge(self) -> Edge:
        return Edge(source=self.source, target=self.target, kind=self.kind)
```

`cobble/cobble/dataflow/srccfg/rows/call_row.py`:

```python
"""A src-cfg row holding one call joining two programs' CFGs."""

from typing import Literal

from cobble.dataflow.srccfg.link import BundleCall
from cobble.dataflow.srccfg.rows.cfg_row_type import CfgRowType
from pydantic import BaseModel, ConfigDict


class CfgCallRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[CfgRowType.CALL]
    caller: str
    node: str
    transfer: str
    program: str
    entry: str
    resolved: bool
    commarea: str
    expression: str
    reasons: tuple[str, ...]
    certain: bool

    def to_call(self) -> BundleCall:
        return BundleCall(
            caller=self.caller,
            node=self.node,
            transfer=self.transfer,
            program=self.program,
            entry=self.entry,
            resolved=self.resolved,
            commarea=self.commarea,
            expression=self.expression,
            reasons=self.reasons,
            certain=self.certain,
        )
```

`cobble/cobble/dataflow/srccfg/rows/cfg_row.py`:

```python
"""Every src-cfg row type, and the rows a program's values are written as."""

from cobble.dataflow.srccfg.cfg import Edge, Node
from cobble.dataflow.srccfg.link import BundleCall
from cobble.dataflow.srccfg.rows.call_row import CfgCallRow
from cobble.dataflow.srccfg.rows.cfg_row_type import CfgRowType
from cobble.dataflow.srccfg.rows.edge_row import CfgEdgeRow
from cobble.dataflow.srccfg.rows.node_row import CfgNodeRow
from cobble.dataflow.srccfg.rows.program_row import CfgProgramRow
from pydantic import TypeAdapter

CfgRow = CfgProgramRow | CfgNodeRow | CfgEdgeRow | CfgCallRow

CFG_ROWS: TypeAdapter[CfgRow] = TypeAdapter(CfgRow)


def program_row(program: str) -> CfgProgramRow:
    return CfgProgramRow(type=CfgRowType.PROGRAM, program=program)


def node_row(program: str, node: Node) -> CfgNodeRow:
    return CfgNodeRow(
        type=CfgRowType.NODE,
        program=program,
        id=node.id,
        kind=node.kind,
        paragraph=node.paragraph,
        atom=node.atom,
        writes=node.writes,
        reads=node.reads,
        transfer=node.transfer,
        target=node.target,
        target_resolved=node.target_resolved,
        target_operand=node.target_operand,
        transfer_operand=node.transfer_operand,
        using=node.using,
        span=node.span,
        resume=node.resume,
    )


def edge_row(program: str, edge: Edge) -> CfgEdgeRow:
    return CfgEdgeRow(
        type=CfgRowType.EDGE,
        program=program,
        source=edge.source,
        target=edge.target,
        kind=edge.kind,
    )


def call_row(call: BundleCall) -> CfgCallRow:
    return CfgCallRow(
        type=CfgRowType.CALL,
        caller=call.caller,
        node=call.node,
        transfer=call.transfer,
        program=call.program,
        entry=call.entry,
        resolved=call.resolved,
        commarea=call.commarea,
        expression=call.expression,
        reasons=call.reasons,
        certain=call.certain,
    )
```

`node_row` and `CfgNodeRow` each list sixteen fields; if `Node` gains a field later, the round-trip test fails at the `to_node()` comparison, which is the check that keeps them in step.

- [ ] **Step 4: Run the tests.**

Run: `uv run --no-sync python -m pytest tests/dataflow/srccfg/test_cfg_rows.py -q`
Expected: PASS (all four tests; the edge test once per `EdgeKind`).

If `node_row` fails with a Pydantic schema error on `RefModOperand`, the `PlainValidator` did not replace the type's own schema: check that `Operand` is `Annotated[RefModOperand, PlainValidator(...), PlainSerializer(...)]` in that order. Do not add `arbitrary_types_allowed`.

- [ ] **Step 5: Mutation-check.** Delete `resume=self.resume,` from `CfgNodeRow.to_node`: the node test must FAIL. Restore. Change `_operand_of` to `return RefModOperand(name=raw.get("name", ""))` on the dict branch: the node test must FAIL (the reference modification is lost). Restore.

- [ ] **Step 6: Gate and commit.**

Run the gate. Then:

```bash
git add cobble/cobble/dataflow/srccfg/rows cobble/tests/dataflow/srccfg/test_cfg_rows.py
git commit -m "feat(cobble): row types for src-cfg files as JSONL

One Pydantic row per program, node, edge and call, each converting to and from
the value it holds; a node's ref-modified operand crosses through
RefModOperand's own to_dict/from_dict. Nothing reads or writes them yet.

```

---

### Task 3: The flip

**Files:**
- Modify: `cobble/cobble/dataflow/srccfg/bundle.py` (rewrite)
- Modify: `cobble/cobble/dataflow/srccfg/build_corpus.py:77,85-90`
- Modify: `cobble/cobble/dataflow/srccfg/closure.py:172-193`
- Modify: `cobble/README.md` (lines ~76-90 and ~130-137, and every `.json` CFG file name in examples)
- Test: `cobble/tests/dataflow/srccfg/test_bundle.py`, and every test that writes or reads a CFG file (listed in Step 5)

**Interfaces:**
- Consumes: from Task 2, `CfgRow`, `CFG_ROWS`, `program_row`, `node_row`, `edge_row`, `call_row`, `CfgProgramRow`, `CfgNodeRow`, `CfgEdgeRow`, `CfgCallRow`.
- Produces: in `bundle.py`, `Bundle` (unchanged), `CfgDocumentError` (unchanged), `REBUILD_HINT` (unchanged), `rows_of(bundle: Bundle) -> tuple[CfgRow, ...]`, `bundle_jsonl(bundle: Bundle) -> str`, `bundle_of_rows(rows: Sequence[CfgRow]) -> Bundle`, `load_bundle(path: Path) -> Bundle`. Deleted: `cfg_to_dict`, `cfg_from_dict`, `bundle_to_json`, `one_cfg_document`, `bundle_of`, `calls_of`, `load_document`, `JsonValue`, `BUNDLE_CFGS`, `BUNDLE_CALLS`.

- [ ] **Step 1: Rewrite the format tests in `test_bundle.py`.**

Replace `test_a_bundle_round_trips_through_json_with_its_calls`, `test_a_bundle_document_loads_as_its_cfgs_and_its_calls`, `test_a_one_program_file_is_the_same_shape_as_a_closure` and `test_a_pre_bundle_file_is_refused_and_says_how_to_rebuild` (and the `_written` helper) with:

```python
def _written(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "cfg.jsonl"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_bundle_round_trips_through_its_rows(tmp_path: Path) -> None:
    """The file is the whole handover: programs in order, an empty one included, and
    the calls joining them."""
    bundle = Bundle(
        seed="PROGA",
        cfgs=(_caller("PROGB"), _callee(), Cfg(program="PROGC", nodes=(), edges=())),
        calls=_bundle(_caller("PROGB"), _callee()).calls,
    )

    read = load_bundle(_written(tmp_path, bundle_jsonl(bundle)))

    assert read == bundle


def test_rows_come_program_first_and_every_edge_after_both_its_nodes() -> None:
    """The order a streaming reader relies on, held by the writer."""
    rows = rows_of(_bundle(_caller("PROGB"), _callee()))
    seen = tuple(
        (row.program, row.id) for row in rows if isinstance(row, CfgNodeRow)
    )
    opened = tuple(row.program for row in rows if isinstance(row, CfgProgramRow))

    assert opened == ("PROGA", "PROGB")
    assert all(
        rows.index(row) > max(
            at
            for at, other in enumerate(rows)
            if isinstance(other, CfgNodeRow)
            and other.program == row.program
            and other.id in (row.source, row.target)
        )
        for row in rows
        if isinstance(row, CfgEdgeRow)
    )
    assert all(
        rows.index(row)
        > next(
            at
            for at, other in enumerate(rows)
            if isinstance(other, CfgProgramRow) and other.program == row.program
        )
        for row in rows
        if isinstance(row, CfgNodeRow)
    )
    assert len(seen) == len(set(seen))


@pytest.mark.parametrize(
    ("text", "line"),
    (
        ('{"cfgs": [], "calls": []}\n', 1),
        ('{"type": "program", "program": "PROGA"}\n{"type": "node", "program": "PRO', 2),
    ),
    ids=("pre-jsonl document", "truncated row"),
)
def test_a_line_that_is_not_a_row_is_refused_by_number(
    tmp_path: Path, text: str, line: int
) -> None:
    """A file in the old one-document shape, or one cut off mid-write, says where it
    stops being a CFG file and what to run."""
    path = _written(tmp_path, text)

    with pytest.raises(CfgDocumentError, match=f"cfg.jsonl:{line}: .*cobble-srccfg-build"):
        load_bundle(path)


def test_blank_lines_are_not_rows_and_are_skipped(tmp_path: Path) -> None:
    text = bundle_jsonl(_bundle(_callee()))

    read = load_bundle(_written(tmp_path, f"\n{text}\n\n"))

    assert read == _bundle(_callee())


def test_a_row_naming_a_program_no_program_row_opened_is_refused(tmp_path: Path) -> None:
    stray = '{"type": "edge", "program": "GHOST", "source": "A", "target": "B", "kind": "FLOW"}'
    text = f'{{"type": "program", "program": "PROGA"}}\n{stray}\n'

    with pytest.raises(CfgDocumentError, match="GHOST"):
        load_bundle(_written(tmp_path, text))
```

Update the imports: drop `cfg_to_dict`, `one_cfg_document`, `bundle_of`, `bundle_to_json`; add `bundle_jsonl`, `rows_of` from `cobble.dataflow.srccfg.bundle`, and `CfgEdgeRow`, `CfgNodeRow`, `CfgProgramRow` from their `rows` modules. `_bundle(...)` in this file builds `Bundle(seed=cfgs[0].program, cfgs=cfgs, calls=bundle_calls(cfgs))`; if it does not set `seed` that way, make `test_blank_lines_are_not_rows_and_are_skipped` compare `cfgs` and `calls` rather than the whole bundle.

- [ ] **Step 2: Run them to see them fail.**

Run: `uv run --no-sync python -m pytest tests/dataflow/srccfg/test_bundle.py -q`
Expected: FAIL at import: `cannot import name 'bundle_jsonl' from 'cobble.dataflow.srccfg.bundle'`.

- [ ] **Step 3: Rewrite `bundle.py`.**

Replace the whole module with:

```python
"""The one shape a CFG file has, and the only code that reads or writes it.

One JSON row per line: a ``program`` row opening each CFG, then its ``node`` rows,
then its ``edge`` rows, and the ``call`` rows joining the programs after all of
them. The first program is the bundle's seed. A corpus member is a file with one
program and no calls; a closure is the same file with more.

Rows rather than one document so a file can be written and read as it streams. A
line that is not a row -- the one-document shape this replaced, or a row cut off
mid-write -- is refused with its line number, and ``cobble-srccfg-build``
regenerates the file.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import groupby
from operator import attrgetter
from pathlib import Path
from typing import TypeVar

from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.link import BundleCall
from cobble.dataflow.srccfg.rows.call_row import CfgCallRow
from cobble.dataflow.srccfg.rows.cfg_row import (
    CFG_ROWS,
    CfgRow,
    call_row,
    edge_row,
    node_row,
    program_row,
)
from cobble.dataflow.srccfg.rows.edge_row import CfgEdgeRow
from cobble.dataflow.srccfg.rows.node_row import CfgNodeRow
from cobble.dataflow.srccfg.rows.program_row import CfgProgramRow
from pydantic import ValidationError

REBUILD_HINT = "rebuild it with cobble-srccfg-build"

RowT = TypeVar("RowT", CfgNodeRow, CfgEdgeRow)


class CfgDocumentError(ValueError):
    """A CFG file that is not in the one shape, named so a caller can say which."""


@dataclass(frozen=True)
class Bundle:
    seed: str
    cfgs: tuple[Cfg, ...] = ()
    calls: tuple[BundleCall, ...] = ()


def rows_of(bundle: Bundle) -> tuple[CfgRow, ...]:
    return (
        *(row for cfg in bundle.cfgs for row in _cfg_rows(cfg)),
        *(call_row(call) for call in bundle.calls),
    )


def _cfg_rows(cfg: Cfg) -> tuple[CfgRow, ...]:
    return (
        program_row(cfg.program),
        *(node_row(cfg.program, node) for node in cfg.nodes),
        *(edge_row(cfg.program, edge) for edge in cfg.edges),
    )


def bundle_jsonl(bundle: Bundle) -> str:
    return "".join(f"{row.model_dump_json()}\n" for row in rows_of(bundle))


def load_bundle(path: Path) -> Bundle:
    return bundle_of_rows(
        tuple(
            _row(line, f"{path.name}:{at}")
            for at, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if line.strip()
        ),
        path.name,
    )


def _row(line: str, where: str) -> CfgRow:
    try:
        return CFG_ROWS.validate_json(line)
    except ValidationError as error:
        raise CfgDocumentError(f"{where}: not a CFG row -- {REBUILD_HINT}") from error


def bundle_of_rows(rows: Sequence[CfgRow], source: str = "<rows>") -> Bundle:
    programs = tuple(row.program for row in rows if isinstance(row, CfgProgramRow))
    order = {program: at for at, program in enumerate(programs)}
    nodes = _by_program(
        tuple(row for row in rows if isinstance(row, CfgNodeRow)), order, source
    )
    edges = _by_program(
        tuple(row for row in rows if isinstance(row, CfgEdgeRow)), order, source
    )
    return Bundle(
        seed=programs[0] if programs else "",
        cfgs=tuple(
            Cfg(
                program=program,
                nodes=tuple(row.to_node() for row in nodes.get(program, ())),
                edges=tuple(row.to_edge() for row in edges.get(program, ())),
            )
            for program in programs
        ),
        calls=tuple(row.to_call() for row in rows if isinstance(row, CfgCallRow)),
    )


def _by_program(
    rows: tuple[RowT, ...], order: Mapping[str, int], source: str
) -> Mapping[str, tuple[RowT, ...]]:
    """Each program's rows in file order. A stable sort by the program's position
    keeps a program's own rows in the order they were written."""
    strays = sorted({row.program for row in rows} - order.keys())
    if strays:
        raise CfgDocumentError(
            f"{source}: rows for {', '.join(strays)} with no program row -- {REBUILD_HINT}"
        )
    ordered = sorted(rows, key=lambda row: order[row.program])
    return {
        program: tuple(group)
        for program, group in groupby(ordered, key=attrgetter("program"))
    }
```

`order.keys()` is a set view, so `{...} - order.keys()` is a set difference. The `strays` check is the one place this reader validates beyond the row schema, and it exists for Review Focus item 1.

- [ ] **Step 4: Move both writers.**

`build_corpus.py`: replace `from cobble.dataflow.srccfg.bundle import one_cfg_document` with `from cobble.dataflow.srccfg.bundle import Bundle, bundle_jsonl`; on line 77 change `f"{cfg.program or member}.json"` to `f"{cfg.program or member}.jsonl"`; on line 86 change the collision name's `.json` to `.jsonl`; and replace `written.write_text(one_cfg_document(cfg), encoding="utf-8")` with:

```python
    written.write_text(
        bundle_jsonl(Bundle(seed=cfg.program, cfgs=(cfg,))), encoding="utf-8"
    )
```

Leave line 44's `asg_dir.glob("*.json")` alone: that globs the ASG cache, not CFG files.

`closure.py`: replace `from cobble.dataflow.srccfg.bundle import Bundle, bundle_to_json` with `from cobble.dataflow.srccfg.bundle import Bundle, bundle_jsonl`; in `main` replace `bundle_to_json(` with `bundle_jsonl(`; and since the rows already end in newlines, `_emitted` becomes:

```python
def _emitted(document: str, output: Path) -> int:
    if output == Path():
        sys.stdout.write(document)
        return 0
    ensure_parent(output).write_text(document, encoding="utf-8")
    return 0
```

Keep `Bundle` in the import only if `closure.py` still names it; otherwise drop it.

- [ ] **Step 5: Move every test that writes or reads a CFG file.**

List them:

Run: `rg -ln "bundle_to_json|one_cfg_document|cfg_to_dict|cfg_from_dict|bundle_of\b|calls_of|load_document|\"cfgs\"|cfg\.json\"|\.json\" *\)" tests`

For each match apply exactly these substitutions, and change nothing else in the test:

| Old | New |
|---|---|
| `bundle_to_json(b)` | `bundle_jsonl(b)` |
| `one_cfg_document(cfg)` | `bundle_jsonl(Bundle(seed=cfg.program, cfgs=(cfg,)))` |
| `cfg_from_dict(cfg_to_dict(cfg))` (a round trip) | `bundle_of_rows(rows_of(Bundle(seed=cfg.program, cfgs=(cfg,)))).cfgs[0]` |
| `bundle_of(json.loads(text))` | `load_bundle(path)` on the file the test wrote, or `bundle_of_rows(rows_of(bundle))` where no file exists |
| a hand-built `{"cfgs": [...], "calls": [...]}` written with `json.dumps` | build the `Cfg`s and write them with `bundle_jsonl` |
| a CFG file named `*.json` that `build_corpus` wrote (e.g. `out / "MEMA.json"`) | `out / "MEMA.jsonl"` |
| `tmp_path / "cfg.json"` used as a `--cfg` input | `tmp_path / "cfg.jsonl"` |

In `tests/dataflow/fields/test_fields_access.py`, the `_write_cfgs` helper from Task 1 changes its one line to `bundle_jsonl(...)`, and `test_accesses_refuses_a_pre_bundle_file` gains the old document shape as a third parameter, `{"cfgs": [], "calls": []}`, all three still refused with `match="cobble-srccfg-build"`.

Then confirm nothing outside `bundle.py` names a deleted function:

Run: `rg -n "bundle_to_json|one_cfg_document|cfg_to_dict|cfg_from_dict|bundle_of\(|calls_of|load_document|JsonValue|BUNDLE_CFGS|BUNDLE_CALLS" cobble tests ../red_dragon_forge ../tests ../cicada ../squall ../jackal`
Expected: no matches.

- [ ] **Step 6: Run the whole cobble suite.**

Run: `uv run --no-sync python -m pytest -q -n auto`
Expected: PASS. The skipped acceptance tests stay skipped.

- [ ] **Step 7: Mutation-check.** In `_cfg_rows`, move the edge rows before the node rows: `test_rows_come_program_first_and_every_edge_after_both_its_nodes` must FAIL. Restore. In `_by_program`, delete the `strays` check: `test_a_row_naming_a_program_no_program_row_opened_is_refused` must FAIL. Restore. In `load_bundle`, drop the `if line.strip()`: `test_blank_lines_are_not_rows_and_are_skipped` must FAIL. Restore.

- [ ] **Step 8: Update the README.**

In `cobble/README.md`:

- Replace the paragraph beginning "The bundle is a JSON object, `{"cfgs": [...], "calls": [...]}`" with:

  > The bundle is JSONL: one row per line, each tagged with a `type`. A `program` row opens each CFG, its `node` and `edge` rows follow, and the `call` rows joining the programs come after all of them; the first program is the seed. A CFG is what the corpus build writes one of per member, unchanged. A call row names the calling program and node, the callee and **the entry node in it the call lands on** — the one thing the call site itself does not know, and exactly what a reader crossing into the callee needs, so no consumer has to rebuild the join to walk the closure:

  and turn the JSON example under it into one line with `"type": "call", ` added at its front.

- Replace the paragraph beginning "Every CFG file has one shape — `{"cfgs": [...], "calls": [...]}`" with:

  > Every CFG file has one shape — JSONL rows, as above — whether it holds a whole closure or the single program the corpus build writes, which is one `program` row and no `call` rows. A line that is not a row, including a file in the one-document shape this replaced, is refused with its line number rather than half-read; `cobble-srccfg-build` regenerates it.

- Change every example CFG file name from `.json` to `.jsonl` (`closure.json`, `one.json` and the like). Find them with `rg -n "closure\.json|--cfg [^ ]*\.json\b|cfg-[A-Z<]*.*\.json" README.md`; leave ASG cache paths (`out-parsed/*.json`) and `.html`/`.dot` outputs alone.

- [ ] **Step 9: Gate and commit.**

Run the gate (fmt; pyright on `bundle.py`, `build_corpus.py`, `closure.py` and every test file changed; lint-imports; the whole cobble suite). Then stage the source files, the tests listed in Step 5 and the README, and:

```bash
git commit -m "feat(cobble): src-cfg files are JSONL

One row per program, node, edge and call, written in an order a streaming reader
can rely on: a program's row before its nodes, an edge after both its nodes, the
calls last. bundle.py is still the only code that reads or writes the format.
A line that is not a row -- the one-document shape this replaces, or a row cut
off mid-write -- is refused with its line number. Per-member files are named
<program>.jsonl. Existing CFG files must be rebuilt with cobble-srccfg-build.

```

---

## Deviations from the spec

- **The whole-`Bundle` round trip is in Task 3, not Task 2.** Assembling a `Bundle` from rows is `bundle.py`'s job, and the row modules importing `Bundle` would make a cycle once `bundle.py` imports the rows. Task 2 round-trips each row type, covering every `Node` field; Task 3's `test_a_bundle_round_trips_through_its_rows` covers the bundle.
- **The old shape is refused by the general invalid-line rule** rather than a separate first-line check: its first line is not a row, so it is refused with its line number and the rebuild hint, which is what the spec asks of both cases.
- **The reachability tool's row types are not added here.** The spec's rule that `load_bundle` skips declared non-graph rows lands with that tool's plan, which adds those row types to `CfgRow` and the skip to `bundle_of_rows` (whose `isinstance` filters already ignore any row type they do not ask for).
