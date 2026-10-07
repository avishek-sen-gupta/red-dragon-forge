# Call-target restricted fixpoint — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** add a `--call-targets-only` option to `cobble-dataflow-fixpoint`. It walks each member over only the bytes its call targets, jump areas and exit areas depend on, and gives the same targets and combine results as a full run.

**Architecture:** before a member's walk, gather the seed extents: every extent the jumps and targets tables read a fact at. Close them over the program's writes into a `Relevant` set. The existing walk then runs with the transfer and edge extraction dropping writes that don't overlap the set. `AnalysisOptions.scope` selects this, and `MemberCounts` records it. The corpus build refuses to mix scopes in one out-dir, and `fixpoint-query` refuses restricted output.

**Tech Stack:** Python 3.13, pytest, Pydantic (`MemberCounts`), the ProLeap bridge for integration tests.

**Spec:** `docs/superpowers/specs/2026-10-07-call-target-restricted-fixpoint-design.md`

## Global Constraints

- The project guidelines apply:
  - no comments beyond one-line class or module headers;
  - frozen dataclasses;
  - no `for` loops with mutation;
  - no `Any` or `object`;
  - no `None` defaults;
  - fully qualified imports;
  - one class per file.
- Gate per commit:
  - `make fmt`;
  - `uv run pyright` (zero new errors in touched files);
  - `uv run lint-imports`;
  - `pre-commit run python-fp-lint-check --hook-stage manual --files <touched>`;
  - the cobble suite, `cd cobble && uv run --no-sync python -m pytest -q`.
- Before the last commit, run `make test-all`.
- Never `--no-verify`. If Talisman flags something, reword it; never touch `.talismanrc` without asking.
- No client identifiers in any tracked file. Programs in tests are invented (PROGA…, SYNPERF…).
- Behaviour with the default scope must not change. The existing cost test (`test_fixpoint_cost_synthetic.py`) has to stay green with its recorded `coalesced` dequeues.

## Ruling recorded against the spec

The spec's seed 3, "every write into LINKAGE", is implemented as the exit areas: `received_areas`, read at `GOBACK`, `EXIT PROGRAM`, `STOP RUN` and CICS `RETURN`. Those are the bytes the combine reads when a callee hands data back, so they are exactly what the spec's seed was for. Seeding every LINKAGE write as well would only add bytes no reader asks for.

## Review Focus

1. **Area through a group.** A call target that reaches its value through a group MOVE into a record holding it must still resolve. The closure has to pull the group's source in. Covered in Task 1's test.
2. **Ref-mod target.** A target written by a ref-mod MOVE (`MOVE X TO WS-PGM(1:4)`) is a write whose target overlaps the seed, so it must be kept. Covered in Task 1.
3. **Sibling not pulled in.** A field sharing a record with the target, but never moved into it, must stay out of the set. Covered in Task 1.
4. **Mixed scopes.** A finished full member reused by a restricted run would publish a mixed corpus. Covered in Task 3.
5. **Unreached dynamic site.** A dynamic site the walk never reaches still gets its `targets.jsonl` row with a reason. Its seed must not crash the closure. Covered by the equality tests in Task 4, where PROGB's site is reached on one branch.

## File structure

- Create `cobble/cobble/dataflow/fixpoint/relevant.py`: the `Relevant` set, `EVERYTHING`, `closed()`.
- Create `cobble/cobble/dataflow/fixpoint/scope.py`: the `Scope` enum.
- Modify `cobble/cobble/dataflow/jumps/discover.py`: add `fact_extents()`.
- Modify `cobble/cobble/dataflow/fields/transfer.py`: `transfer` takes a `Relevant`.
- Modify `cobble/cobble/dataflow/fixpoint/options.py`: `scope` field.
- Modify `cobble/cobble/dataflow/fixpoint/fixpoint.py`:
  - compute the relevant set;
  - thread it through the walk and extraction;
  - add `tracked` and `relevant` to `ProgramFlow`.
- Modify `cobble/cobble/dataflow/fixpoint/member_counts.py`: `scope`, `tracked`, `relevant`.
- Modify `cobble/cobble/dataflow/fixpoint/build_corpus.py`:
  - the CLI option;
  - carrying the counts through;
  - the mixed-scope refusal;
  - logging.
- Modify `cobble/cobble/dataflow/fixpoint/query.py`: refuse restricted out-dirs.
- Tests:
  - `cobble/tests/dataflow/fixpoint/test_relevant.py` (new);
  - `cobble/tests/dataflow/fields/test_transfer.py`;
  - `cobble/tests/dataflow/fixpoint/conftest.py`;
  - `cobble/tests/dataflow/fixpoint/test_call_targets_only_synthetic.py` (new);
  - `cobble/tests/dataflow/fixpoint/test_fixpoint_cost_synthetic.py`, plus fixture `data/perf/SYNPERFD.cbl`.
- Docs: `cobble/README.md`.

---

### Task 1: the relevant set and its seeds

**Files:**
- Create: `cobble/cobble/dataflow/fixpoint/relevant.py`
- Modify: `cobble/cobble/dataflow/jumps/discover.py` (add `fact_extents` and its helpers at the end)
- Test: `cobble/tests/dataflow/fixpoint/test_relevant.py`

**Interfaces:**
- Produces:
  - `Relevant(extents: frozenset[FieldExtent] = frozenset(), everything: bool = False)` with `.touches(target: FieldExtent) -> bool`;
  - `EVERYTHING: Relevant`;
  - `closed(seeds: Iterable[FieldExtent], writes: Sequence[Write]) -> Relevant`;
  - `fact_extents(asg: CobolASG, cfg: Cfg, statements: Mapping[str, Statement], index: CellIndex) -> frozenset[FieldExtent]`.

- [ ] **Step 1: Write the failing test**

```python
"""Which bytes a call-target walk tracks: the seeds closed over the program's writes."""

from cobble.dataflow.fields.state import NOWHERE, Source
from cobble.dataflow.fields.transfer import Write
from cobble.dataflow.fields.values import EMPTY as NO_VALUE
from cobble.dataflow.fixpoint.relevant import EVERYTHING, Relevant, closed
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId


def _ws(start: int, length: int, name: str) -> FieldExtent:
    return FieldExtent(RegionId.WORKING_STORAGE, start, length, Precision.EXACT, name)


def _write(target: FieldExtent, *sources: FieldExtent) -> Write:
    return Write(
        target=target,
        sources=frozenset(Source(origin="", extent=one, node="N") for one in sources),
        values=NO_VALUE,
    )


def test_the_set_follows_writes_into_the_target_and_nothing_beside_it() -> None:
    pgm = _ws(0, 8, "WS-PGM")
    head = _ws(0, 4, "WS-PGM")
    staged = _ws(8, 8, "WS-STAGED")
    record = _ws(16, 20, "WS-REC")
    origin = _ws(36, 20, "WS-ORIGIN")
    sibling = _ws(56, 8, "WS-SIBLING")
    other = _ws(64, 8, "WS-OTHER")
    literal = Write(
        target=head,
        sources=frozenset({Source(origin="LITERAL", extent=NOWHERE, node="L")}),
        values=NO_VALUE,
    )
    writes = (
        _write(pgm, staged),
        _write(staged, _ws(20, 8, "WS-REC-PART")),
        _write(record, origin),
        _write(sibling, other),
        literal,
    )

    found = closed((pgm,), writes)

    assert found == Relevant(
        extents=frozenset({pgm, staged, _ws(20, 8, "WS-REC-PART"), origin})
    )
    assert found.touches(head)
    assert found.touches(record)
    assert not found.touches(sibling)
    assert not found.touches(
        FieldExtent(RegionId.LINKAGE, 0, 8, Precision.EXACT, "WS-PGM")
    )
    assert EVERYTHING.touches(sibling)
```

The test covers four cases:
- `record` is pulled in through `WS-REC-PART`, the part `staged` reads.
- The ref-mod `head` overlaps the seed, so it is touched.
- The sibling stays out.
- A literal write adds nothing.

- [ ] **Step 2: Run it and see it fail**

Run: `cd cobble && uv run --no-sync python -m pytest -q tests/dataflow/fixpoint/test_relevant.py`
Expected: FAIL, `ModuleNotFoundError: cobble.dataflow.fixpoint.relevant`.

- [ ] **Step 3: Implement `relevant.py`**

```python
"""The bytes a restricted walk tracks: its seeds, closed over the program's writes."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import accumulate, pairwise, repeat

from cobble.dataflow.fields.transfer import Write
from cobol_memory.field_extent import FieldExtent


@dataclass(frozen=True)
class Relevant:
    """The extents a write must overlap to be kept; ``everything`` keeps every write."""

    extents: frozenset[FieldExtent] = frozenset()
    everything: bool = False

    def touches(self, target: FieldExtent) -> bool:
        return self.everything or any(_overlap(target, one) for one in self.extents)


EVERYTHING = Relevant(everything=True)


def _overlap(left: FieldExtent, right: FieldExtent) -> bool:
    return (
        left.region is right.region
        and left.start < right.end
        and right.start < left.end
    )


def _grown(relevant: Relevant, writes: Sequence[Write]) -> Relevant:
    return Relevant(
        extents=relevant.extents
        | frozenset(
            source.extent
            for write in writes
            if relevant.touches(write.target)
            for source in write.sources
            if not source.origin
        )
    )


def closed(seeds: Iterable[FieldExtent], writes: Sequence[Write]) -> Relevant:
    steps = accumulate(
        repeat(None),
        lambda held, _: _grown(held, writes),
        initial=Relevant(extents=frozenset(seeds)),
    )
    return next(before for before, after in pairwise(steps) if before == after)
```

- [ ] **Step 4: Add `fact_extents` to `discover.py`**

Add it at the end of the file. Every name it uses is already imported there, except `area_extents`, which is already imported from `aliases`.

```python
def fact_extents(
    asg: CobolASG,
    cfg: Cfg,
    statements: Mapping[str, Statement],
    index: CellIndex,
) -> frozenset[FieldExtent]:
    """Every extent the jumps and targets tables read a fact at, in any state."""
    return frozenset(
        (
            *(extent for _, extent in received_areas(asg, index)),
            *(
                extent
                for node in cfg.nodes
                if node.transfer in CALL_TRANSFERS
                for extent in _call_extents(node, index)
            ),
            *(
                extent
                for node in cfg.nodes
                if node.transfer not in CALL_TRANSFERS
                and isinstance(statements.get(node.id), ExecCicsStatement)
                for extent in _cics_extents(statements[node.id], index)
            ),
        )
    )


def _call_extents(node: Node, index: CellIndex) -> tuple[FieldExtent, ...]:
    target = (
        ()
        if node.target_resolved
        else operand_occurrence_extents(node.target_operand, index)
    )
    if CALL_TRANSFERS[node.transfer] == "CALL":
        return (
            *target,
            *(
                extent
                for argument in node.using
                for extent in area_extents(argument.name, index)
            ),
        )
    return (*target, *_named(commarea_field(node), index))


def _named(operand: str, index: CellIndex) -> tuple[FieldExtent, ...]:
    if not operand:
        return ()
    return area_extents(operand, index)


def _cics_extents(
    statement: ExecCicsStatement, index: CellIndex
) -> tuple[FieldExtent, ...]:
    return tuple(
        extent
        for kind in _cics_kind(statement)
        if kind is not JumpKind.EXIT
        for extent in (
            *_transid_extents(statement, kind, index),
            *_named(_option(statement, _CICS_OPTION[kind]).text, index),
        )
    )


def _transid_extents(
    statement: ExecCicsStatement, kind: JumpKind, index: CellIndex
) -> tuple[FieldExtent, ...]:
    operand = _option(statement, "TRANSID")
    if kind is JumpKind.RETRIEVE or operand.is_literal:
        return ()
    return _named(operand.text, index)
```

`isinstance` here is a type test on the statement union, not a defensive check. It is the same dispatch `_statement_jumps` does with `match`.

- [ ] **Step 5: Run the tests**

Run: `cd cobble && uv run --no-sync python -m pytest -q tests/dataflow/fixpoint/test_relevant.py tests/dataflow/jumps`
Expected: all green. `fact_extents` is exercised end to end in Task 4.

- [ ] **Step 6: Gate and commit**

```bash
git add cobble/cobble/dataflow/fixpoint/relevant.py cobble/cobble/dataflow/jumps/discover.py cobble/tests/dataflow/fixpoint/test_relevant.py
git commit -m "feat(cobble): the bytes call targets can depend on, closed over a program's writes"
```

---

### Task 2: scope, and the walk restricted to the relevant set

**Files:**
- Create: `cobble/cobble/dataflow/fixpoint/scope.py`
- Modify:
  - `cobble/cobble/dataflow/fixpoint/options.py`;
  - `cobble/cobble/dataflow/fields/transfer.py` (`transfer`);
  - `cobble/cobble/dataflow/fixpoint/fixpoint.py`.
- Test: `cobble/tests/dataflow/fields/test_transfer.py`

**Interfaces:**
- Consumes: `Relevant`, `EVERYTHING`, `closed` and `fact_extents` from Task 1.
- Produces:
  - `Scope.WHOLE` and `Scope.CALL_TARGETS`;
  - `AnalysisOptions.scope: Scope = Scope.WHOLE`;
  - `transfer(statement, node, state, index, relevant: Relevant) -> State`;
  - `ProgramFlow.tracked: int` and `ProgramFlow.relevant: int`.

- [ ] **Step 1: Write the failing test** (append to `test_transfer.py`)

```python
def test_a_restricted_transfer_drops_writes_outside_the_set(
    program_of, field, index_of, names_reaching
):
    asg = program_of(
        [_move("WS-A", "WS-B"), _move("WS-A", "WS-C")],
        data_fields=[
            field(
                1,
                "REC",
                children=[
                    field(5, "WS-A", "X(4)", offset=0),
                    field(5, "WS-B", "X(4)", offset=4),
                    field(5, "WS-C", "X(4)", offset=8),
                ],
            )
        ],
    )
    index = index_of(asg)
    (b,) = operand_extents(RefModOperand(name="WS-B"), index).extents
    kept = Relevant(extents=frozenset({b}))
    state = reduce(
        lambda held, pair: transfer(pair[1], f"MAIN/{pair[0]}", held, index, kept),
        enumerate(asg.paragraphs[0].statements),
        EMPTY,
    )

    assert names_reaching(state, index, "WS-B") == {"WS-A"}
    assert names_reaching(state, index, "WS-C") == set()
```

Add these imports to the test file:
- `from functools import reduce`
- `from cobble.dataflow.fixpoint.relevant import EVERYTHING, Relevant`

Change the two existing `transfer(...)` calls to add `EVERYTHING` as the last argument.

- [ ] **Step 2: Run it and see it fail**

Run: `cd cobble && uv run --no-sync python -m pytest -q tests/dataflow/fields/test_transfer.py`
Expected: FAIL. `transfer()` takes 4 positional arguments, but 5 were given.

- [ ] **Step 3: Implement**

`scope.py`:

```python
"""Which bytes a fixpoint run tracks."""

from enum import Enum


class Scope(Enum):
    """Every written byte, or only what call targets and jump areas depend on."""

    WHOLE = "whole"
    CALL_TARGETS = "call-targets"
```

`options.py`: import `Scope` and add the field `scope: Scope = Scope.WHOLE` to `AnalysisOptions`.

`transfer.py`:

```python
def transfer(
    statement: Statement,
    node: str,
    state: State,
    index: CellIndex,
    relevant: Relevant,
) -> State:
    """The state after ``statement``, keeping only writes ``relevant`` touches."""
    return _applied(
        state,
        (
            write
            for write in writes_of(statement, node, index, state)
            if relevant.touches(write.target)
        ),
    )
```

Import `Relevant` from `cobble.dataflow.fixpoint.relevant`. Run `uv run lint-imports` now. If `.importlinter` forbids `fields` importing from `fixpoint`, move `relevant.py` to `cobble/cobble/dataflow/fields/relevant.py`, and update Task 1's imports and test path to match.

`fixpoint.py`:
1. Add a `relevant: Relevant` parameter after `index` to `_after`, `_step`, `_settled`, `_propagated`, `_swept`, `_worked` and `_walked`. Supply it at every call site, beside `index`.
2. `_after` calls `transfer(statement, node_id, before, index, relevant)`.
3. `_at` and `_extracted` take `relevant: Relevant` too. In `_at`, the `moved` comprehension iterates `for write in writes_of(statement, node_id, index) if relevant.touches(write.target)`.
4. Add `tracked: int = 0` and `relevant: int = 0` to `ProgramFlow`.
5. In `analyse`:

```python
    relevant = _relevant(asg, cfg, statements, found, index, options.scope)
    walk = _walked(
        cfg, statements, index, relevant, _entry_node(asg), options, entry_state
    )
    extracted = _extracted(found, walk.states, index, relevant)
```

Then add `tracked=_tracked(found, index)` and `relevant=len(relevant.extents) if not relevant.everything else _tracked(found, index)` to the `ProgramFlow(...)` call, with:

```python
def _written(
    found: tuple[tuple[str, Statement], ...], index: CellIndex
) -> tuple[Write, ...]:
    return tuple(
        write
        for node_id, statement in found
        for write in writes_of(statement, node_id, index)
    )


def _tracked(found: tuple[tuple[str, Statement], ...], index: CellIndex) -> int:
    return len({write.target for write in _written(found, index)})


def _relevant(
    asg,
    cfg: Cfg,
    statements: Mapping[str, Statement],
    found: tuple[tuple[str, Statement], ...],
    index: CellIndex,
    scope: Scope,
) -> Relevant:
    if scope is Scope.WHOLE:
        return EVERYTHING
    return closed(fact_extents(asg, cfg, statements, index), _written(found, index))
```

Import `Write` from `transfer`, `Scope`, `EVERYTHING`, `Relevant`, `closed`, and `fact_extents` from `cobble.dataflow.jumps.discover`.

- [ ] **Step 4: Run the tests**

Run: `cd cobble && uv run --no-sync python -m pytest -q tests/dataflow/fields tests/dataflow/fixpoint/test_fixpoint_cost_synthetic.py`
Expected: all green. The cost test's `coalesced` dequeues are unchanged, which proves the default scope behaves as before.

- [ ] **Step 5: Gate and commit**

```bash
git commit -am "feat(cobble): a fixpoint scope that walks only the bytes call targets depend on"
```

---

### Task 3: the CLI option, counts, and the mixed-scope refusal

**Files:**
- Modify:
  - `cobble/cobble/dataflow/fixpoint/member_counts.py`;
  - `cobble/cobble/dataflow/fixpoint/build_corpus.py`;
  - `cobble/tests/dataflow/fixpoint/conftest.py`.
- Test: `cobble/tests/dataflow/fixpoint/test_call_targets_only_synthetic.py` (new; its first test)

**Interfaces:**
- Consumes: `Scope` and `ProgramFlow.tracked`/`relevant` from Task 2.
- Produces:
  - `MemberCounts.scope: str = "whole"`, `.tracked: int = 0` and `.relevant: int = 0`;
  - `fixpoint_corpus_with` fixture: `(sources: Mapping[str, str], extra: tuple[str, ...]) -> Path`.

`MemberCounts` holds the scope as its enum value string. The model reads from JSON, and Pydantic parses `Scope` too, so use the enum type: `scope: Scope = Scope.WHOLE`.

- [ ] **Step 1: Add the conftest fixture**

In `conftest.py`, give `_fixpoint` a trailing `extra: tuple[str, ...]` parameter, appended to the `cli([...])` argument list after `"1"`. Give `()` from the two existing fixtures. Then add:

```python
@pytest.fixture(scope="session")
def fixpoint_corpus_with(
    tmp_path_factory: pytest.TempPathFactory,
) -> Callable[[Mapping[str, str], tuple[str, ...]], Path]:
    """``fixpoint_corpus`` with extra fixpoint arguments."""

    def run(sources: Mapping[str, str], extra: tuple[str, ...]) -> Path:
        return _fixpoint(tmp_path_factory, ("--all",), sources, extra)

    return run
```

- [ ] **Step 2: Write the failing test**

```python
"""A run restricted to call targets, compiled by the real bridge, against a full run."""

import json
from collections.abc import Callable, Mapping
from pathlib import Path

from cobble.dataflow.fixpoint.build_corpus import cli
from cobble.dataflow.fixpoint.member_counts import MemberCounts
from cobble.dataflow.fixpoint.scope import Scope

LOCAL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CTL.
           05  WS-MODE          PIC X(1).
           05  WS-PGM           PIC X(8).
           05  WS-NOISE         PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'ABC' TO WS-NOISE.
           IF WS-MODE = 'A'
               MOVE 'PROGX' TO WS-PGM
           ELSE
               MOVE 'PROGY' TO WS-PGM
           END-IF.
           CALL WS-PGM.
           GOBACK.
"""


def _counts(out: Path, member: str) -> MemberCounts:
    return MemberCounts.model_validate_json(
        (out / "members" / member / "counts.json").read_text(encoding="utf-8")
    )


def test_a_restricted_run_records_its_scope_and_refuses_a_full_one_beside_it(
    fixpoint_corpus_with: Callable[[Mapping[str, str], tuple[str, ...]], Path],
) -> None:
    out = fixpoint_corpus_with({"PROGL": LOCAL}, ("--call-targets-only",))
    counts = _counts(out, "PROGL")

    assert (counts.scope, counts.tracked, counts.relevant) == (Scope.CALL_TARGETS, 2, 1)
    assert cli(
        [
            "--asg-dir",
            str(out.parent / "parsed"),
            "--out-dir",
            str(out),
            "--extents",
            str(out.parent / "extents.jsonl"),
            "--all",
            "--max-workers",
            "1",
        ]
    ) == 2
```

`tracked` is 2: the program writes `WS-NOISE` once and `WS-PGM` twice, at one extent. `CALL WS-PGM` has no `USING`, so it writes nothing. `relevant` is 1: the seed `WS-PGM`, whose writers read only literals.

- [ ] **Step 3: Run it and see it fail**

Run: `cd cobble && . ../bridge-env.sh && uv run --no-sync python -m pytest -q tests/dataflow/fixpoint/test_call_targets_only_synthetic.py`
Expected: FAIL, with argparse rejecting `--call-targets-only`.

- [ ] **Step 4: Implement**

1. `member_counts.py`: add `scope: Scope = Scope.WHOLE`, `tracked: int = 0` and `relevant: int = 0`.
2. `build_corpus.py`:
   - `MemberResult` gains `scope: Scope = Scope.WHOLE`, `tracked: int = 0` and `relevant: int = 0`.
   - The `MemberResult(...)` at line 273 copies `tracked=flow.tracked` and `relevant=flow.relevant`, and adds `scope=options.scope`. Thread `options` into that function if it isn't already in scope there; it is what `analysed` receives.
   - `counts_of` copies all three.
3. `_add_walk_budget` gains:

```python
    parser.add_argument(
        "--call-targets-only",
        action="store_true",
        help="track only the bytes call targets and jump areas depend on",
    )
```

4. `_options` sets `scope=Scope.CALL_TARGETS if arguments.call_targets_only else Scope.WHOLE`.
5. In `_analysed_run`, after the `--force` handling and `ensure_dir(members)`:

```python
    mixed = _other_scope(members, _options(arguments).scope)
    if mixed:
        sys.stderr.write(
            f"fields: !! members analysed in another scope: {', '.join(mixed)};"
            " rerun with --force\n"
        )
        return 2
```

with:

```python
def _other_scope(members: Path, scope: Scope) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.parent.name
            for path in members.glob(f"*/{COUNTS_FILE}")
            if MemberCounts.model_validate_json(path.read_text(encoding="utf-8")).scope
            is not scope
        )
    )
```

6. The per-member log line in `_as_finished`'s logger call adds the sizes for an analysed member: `logger.info("fields: [%d/%d] %s (%d of %d extents tracked)", finished, total, member.counts.member, member.counts.relevant, member.counts.tracked)`.

- [ ] **Step 5: Run the tests, then gate and commit**

Run: `cd cobble && . ../bridge-env.sh && uv run --no-sync python -m pytest -q tests/dataflow/fixpoint`
Expected: all green.

```bash
git commit -am "feat(cobble): cobble-dataflow-fixpoint --call-targets-only, its counts, and no mixed scopes"
```

---

### Task 4: restricted and full runs agree through the combine

**Files:**
- Test: `cobble/tests/dataflow/fixpoint/test_call_targets_only_synthetic.py` (append)

**Interfaces:**
- Consumes:
  - `fixpoint_corpus_with` (Task 3);
  - `cobble.dataflow.combine.cli.cli`;
  - `tests.dataflow.combine.corpus_toml.CONFIG`;
  - `tests.dataflow.combine.linked_rows.target_rows` and `link_rows`;
  - `PROGA` and `PROGB` from `tests.dataflow.fixpoint.test_combine_synthetic`.

- [ ] **Step 1: Write the tests**

```python
from cobble.dataflow.combine.cli import cli as combine_cli
from tests.dataflow.combine.corpus_toml import CONFIG
from tests.dataflow.combine.linked_rows import link_rows, target_rows
from tests.dataflow.fixpoint.test_combine_synthetic import PROGA, PROGB

CALLER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA.
           05  WS-NEXT          PIC X(8).
           05  WS-PAD           PIC X(12).
       01  WS-NOISE             PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'ABC' TO WS-NOISE.
           EXEC CICS LINK PROGRAM('PROGW') COMMAREA(WS-AREA) END-EXEC.
           CALL WS-NEXT.
           GOBACK.
"""

CALLEE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGW.
       DATA DIVISION.
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  LK-NEXT          PIC X(8).
           05  LK-PAD           PIC X(12).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'PROGZ' TO LK-NEXT.
           EXEC CICS RETURN END-EXEC.
"""


def _combined(out: Path, tmp_path: Path, name: str) -> Path:
    config = tmp_path / f"{name}.toml"
    config.write_text(CONFIG.format(asg=out.parent / "parsed"), encoding="utf-8")
    combined = tmp_path / name
    assert combine_cli(
        [
            "--config",
            str(config),
            "--fixpoint-dir",
            str(out),
            "--out-dir",
            str(combined),
            "--all",
        ]
    ) == 0
    return combined


def _both(
    run: Callable[[Mapping[str, str], tuple[str, ...]], Path],
    sources: Mapping[str, str],
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path]:
    full = run(sources, ())
    restricted = run(sources, ("--call-targets-only",))
    return (
        full,
        restricted,
        _combined(full, tmp_path, "full"),
        _combined(restricted, tmp_path, "restricted"),
    )


def test_a_local_target_resolves_the_same_in_fewer_steps(
    fixpoint_corpus_with: Callable[[Mapping[str, str], tuple[str, ...]], Path],
    tmp_path: Path,
) -> None:
    full, restricted, full_combined, restricted_combined = _both(
        fixpoint_corpus_with, {"PROGL": LOCAL}, tmp_path
    )
    (row,) = target_rows(restricted / "targets.jsonl")

    assert target_rows(restricted / "targets.jsonl") == target_rows(
        full / "targets.jsonl"
    )
    assert row.candidates == ("PROGX", "PROGY")
    assert target_rows(restricted_combined / "targets.jsonl") == target_rows(
        full_combined / "targets.jsonl"
    )


def test_a_target_through_a_commarea_resolves_the_same(
    fixpoint_corpus_with: Callable[[Mapping[str, str], tuple[str, ...]], Path],
    tmp_path: Path,
) -> None:
    _, _, full_combined, restricted_combined = _both(
        fixpoint_corpus_with, {"PROGA": PROGA, "PROGB": PROGB}, tmp_path
    )
    (row,) = target_rows(restricted_combined / "targets.jsonl")

    assert row.candidates == ("PROGA", "PROGM")
    assert target_rows(restricted_combined / "targets.jsonl") == target_rows(
        full_combined / "targets.jsonl"
    )
    assert link_rows(restricted_combined / "links.jsonl") == link_rows(
        full_combined / "links.jsonl"
    )


def test_a_target_handed_back_by_a_callee_resolves_the_same(
    fixpoint_corpus_with: Callable[[Mapping[str, str], tuple[str, ...]], Path],
    tmp_path: Path,
) -> None:
    _, _, full_combined, restricted_combined = _both(
        fixpoint_corpus_with, {"PROGC": CALLER, "PROGW": CALLEE}, tmp_path
    )

    assert target_rows(restricted_combined / "targets.jsonl") == target_rows(
        full_combined / "targets.jsonl"
    )
    assert link_rows(restricted_combined / "links.jsonl") == link_rows(
        full_combined / "links.jsonl"
    )
```

The step-count claim in the first test's name is asserted through counts: add `assert _counts(restricted, "PROGL").relevant < _counts(full, "PROGL").tracked`.

For the third test, first run the full corpus alone and read `target_rows(full_combined / "targets.jsonl")`. If the combine resolves the write-back to `("PROGZ",)`, add `assert row.candidates == ("PROGZ",)`. If it does not, the equality assertions stand alone. Write down which case it was in the commit message, because it is a fact about the combine and not about this change.

- [ ] **Step 2: Run the tests**

Run: `cd cobble && . ../bridge-env.sh && uv run --no-sync python -m pytest -q tests/dataflow/fixpoint/test_call_targets_only_synthetic.py`
Expected: all green. If an equality fails, the seed set is missing bytes the combine reads. Find which reader they belong to (a jumps fact or a target), and add those extents to `fact_extents`. Never weaken the assertion.

- [ ] **Step 3: Mutation-check**

Make two temporary changes, one at a time:
1. In `fact_extents`, drop the `received_areas` part.
2. In `_call_extents`, drop the commarea or `USING` part.

The write-back test must fail for the first, and the commarea test for the second. Revert both.

- [ ] **Step 4: Gate and commit**

```bash
git commit -am "test(cobble): restricted and full fixpoint runs agree through the combine"
```

---

### Task 5: fixpoint-query refuses restricted output

**Files:**
- Modify: `cobble/cobble/dataflow/fixpoint/query.py` (`cli`, line ~1228)
- Test: `cobble/tests/dataflow/fixpoint/test_call_targets_only_synthetic.py` (append)

- [ ] **Step 1: Write the failing test**

```python
from cobble.dataflow.fixpoint.query import cli as query_cli


def test_the_query_refuses_a_restricted_run(
    fixpoint_corpus_with: Callable[[Mapping[str, str], tuple[str, ...]], Path],
    capsys,
) -> None:
    out = fixpoint_corpus_with({"PROGL": LOCAL}, ("--call-targets-only",))

    assert query_cli(
        [
            "writers",
            "PROGL.WS-NOISE",
            "--fixpoint-dir",
            str(out),
            "--extents",
            str(out.parent / "extents.jsonl"),
        ]
    ) == 2
    assert capsys.readouterr().err == (
        f"fields: !! {out} holds a run restricted to call targets (PROGL);"
        " rerun cobble-dataflow-fixpoint without --call-targets-only to query it\n"
    )
```

- [ ] **Step 2: Run it and see it fail**

Expected: FAIL. The query answers instead of returning 2.

- [ ] **Step 3: Implement**

In `query.cli`, after the existing `is_dir` check:

```python
    restricted = _restricted(arguments.fixpoint_dir)
    if restricted:
        sys.stderr.write(
            f"fields: !! {arguments.fixpoint_dir} holds a run restricted to call"
            f" targets ({', '.join(restricted)}); rerun cobble-dataflow-fixpoint"
            " without --call-targets-only to query it\n"
        )
        return 2
```

```python
def _restricted(fixpoint_dir: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.parent.name
            for path in (fixpoint_dir / "members").glob("*/counts.json")
            if MemberCounts.model_validate_json(path.read_text(encoding="utf-8")).scope
            is Scope.CALL_TARGETS
        )
    )
```

Use the out-dir's existing constants for `"members"` and `"counts.json"` if `query.py` can import them without a cycle (`MEMBERS_DIR` and `COUNTS_FILE` from `build_corpus`). Check with `uv run lint-imports`.

- [ ] **Step 4: Run the tests, gate and commit**

```bash
git commit -am "feat(cobble): fixpoint-query refuses a run restricted to call targets"
```

---

### Task 6: cost rows for a program with dynamic call sites, and the README

**Files:**
- Create: `cobble/tests/dataflow/fixpoint/data/perf/SYNPERFD.cbl`
- Modify:
  - `cobble/tests/dataflow/fixpoint/test_fixpoint_cost_synthetic.py`;
  - `cobble/tests/dataflow/fixpoint/fixpoint_baseline.py`;
  - `cobble/README.md`.

- [ ] **Step 1: Make the fixture**

Copy `SYNPERFA.cbl` and rename `PROGRAM-ID` to `SYNPERFD`. After every fourth `MOVE … TO WS-PGM` in the procedure division, add `CALL WS-PGM.` on its own line, at the same indentation. Use a short script in the scratchpad, not by hand. Confirm `grep -c "CALL WS-PGM" SYNPERFD.cbl` is at least 5, and that the program parses through the bridge.

- [ ] **Step 2: Record the rows**

Measure SYNPERFD in both scopes with the scratchpad harness (`repro/measure.py`, which spies on `_extracted` for extent counts). Give it `AnalysisOptions(scope=Scope.CALL_TARGETS)` for the restricted run.

`FixpointBaseline` cannot hold this program's history: the four historical rows don't exist for it. Add a second record type:
- `cobble/tests/dataflow/fixpoint/fixpoint_scope_baseline.py`: `FixpointScopeBaseline(program: str, whole: FixpointCost, call_targets: FixpointCost)`.
- `test_fixpoint_cost_synthetic.py`: a tuple `SCOPE_BASELINES` with SYNPERFD's two rows, and a second parametrized test. It runs `analysed` in each scope and asserts `(nodes, dequeues, settled)` equals the recorded row.

- [ ] **Step 3: README**

In the fixpoint stage's section of `cobble/README.md`, add a paragraph covering:
- `--call-targets-only`: what it tracks (call targets, jump and exit areas, closed over writes);
- that `targets.jsonl` and the combine's results equal a full run's;
- that `fixpoint-query` refuses its output;
- that one out-dir holds one scope.

In the pipeline sequence, show it as the flag to use when only call targets are wanted.

- [ ] **Step 4: Full gate, then commit**

Run `make test-all`.

```bash
git commit -am "test(cobble): fixpoint cost in both scopes; document --call-targets-only"
```
