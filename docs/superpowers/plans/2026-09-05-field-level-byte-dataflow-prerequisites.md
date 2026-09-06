# Field-Level Byte Dataflow — Prerequisites Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the byte-extent algebra on cobble's importable static surface, and produce an ASG cache whose MOVE operands carry subscripts and reference modification — the two things `cobble/dataflow/fields/` cannot be built without.

**Architecture:** Four modules (190 lines) move from `interpreter/` to a new sibling package `cobol_memory` in red-dragon, mirroring the existing `cobol_asg` sibling pattern and its leaf contract. Forge takes the change as a submodule bump. Then a committed diagnostic establishes what an ASG cache actually carries per operand, and the corpus is re-parsed into a fresh cache the diagnostic accepts.

**Tech Stack:** Python 3.11+, uv workspace, pytest, Black (88), import-linter, hatchling (red-dragon) / uv_build (cobble), ProLeap bridge JAR (Java, JVM).

**Spec:** `docs/superpowers/specs/2026-09-05-field-level-byte-dataflow-design.md`

## Global Constraints

- **Two repositories.** Tasks 1 is in `vendor/red-dragon` (its own git remote, `git@github.com:avishek-sen-gupta/red-dragon.git`). Tasks 2–5 are in `red-dragon-forge`. Never edit `vendor/red-dragon` from a forge working session that intends to commit in forge — commit upstream first, then bump.
- **No external-codebase identifiers in any tracked artifact.** Per `vendor/red-dragon/.claude/core/workflow.md`: never put corpus program names, field names, dataset names or organisation names in commit messages, issues, specs, plans, docs, code comments or test names. Use generic examples (`PROG-A`, `REC-MASTER`, `FLD-COUNT`). This governs both repos for the duration of this plan.
- **Do not run `bd export` or stage `issues/issues.jsonl` in forge.** Forge has no redactor and its HEAD snapshot contains zero corpus identifiers; a plain export reintroduces them. Redaction is an open decision outside this plan. Beads may be updated in the local DB; the snapshot stays unstaged.
- **red-dragon commits run a pre-commit gate** at `.claude/hooks/pre-commit`: Talisman, Black, import-linter, pytest, `bd backup`. Do not run these manually first; commit and fix what it rejects. If Talisman flags a false positive, **append** to `.talismanrc`, never edit existing entries.
- **red-dragon issue changes** require `bd export -o beads/issues.jsonl && git add beads/issues.jsonl` before committing. Note the path differs from forge's (`issues/issues.jsonl`).
- **Formatting:** Black, line length 88, both repos.
- **Comments are a smell** (forge convention). A surviving comment must carry an external constraint, a non-obvious why, or a reference to an issue or standard.
- **No test counts in living documentation** (forge convention). READMEs and package docs describe what a suite covers, never how many tests it has.
- **`uv` needs the sandbox disabled** in this environment — `~/.cache/uv` is not writable inside it. Every `uv run` may need `dangerouslyDisableSandbox: true`.
- **Use `$TMPDIR`, never `/tmp`.**
- **Conservative git profile in forge:** do not push without explicit authority. red-dragon's own convention is to push to `main`; confirm before doing so.

---

### Task 1: Extract `cobol_memory` in red-dragon

Move the byte-extent algebra out from under `interpreter/` so a static-only consumer can import it without loading the VM. This mirrors the reason `cobol_asg` is a sibling, stated in `vendor/red-dragon/.importlinter` lines 6–10.

**Repository:** `vendor/red-dragon` (upstream). All paths below are relative to it.

**Files:**
- Create: `cobol_memory/__init__.py`
- Create: `cobol_memory/abstract_location.py` (moved from `interpreter/abstract_location.py`, 59 lines)
- Create: `cobol_memory/storage_identifier.py` (moved from `interpreter/storage_identifier.py`, 23 lines)
- Create: `cobol_memory/region_id.py` (moved from `interpreter/cobol/region_id.py`, 22 lines)
- Create: `cobol_memory/field_extent.py` (moved from `interpreter/cobol/field_extent.py`, 86 lines)
- Delete: the four source paths above
- Modify: `pyproject.toml:45` — `packages = ["interpreter", "cobol_asg"]`
- Modify: `.importlinter` — add `cobol_memory` to `root_packages` (line 2–4) and add a leaf contract
- Modify: importers of `field_extent` — `interpreter/cobol/{memory_dataflow,emit_context,lower_data_division,lower_call,field_resolution,memory_effects,lower_io}.py`
- Modify: importers of `region_id` — `interpreter/cobol/{emit_context,lower_program_init,sectioned_layout,lower_data_division,lower_call,field_resolution,statement_dispatch,lower_arithmetic}.py`
- Modify: importers of `storage_identifier` — `interpreter/{instructions,dataflow}.py`, `interpreter/cobol/memory_dataflow.py`
- Modify: importers of `abstract_location` — `interpreter/storage_identifier.py` (moves with it), `interpreter/cobol/field_extent.py` (moves with it)
- Test: `tests/unit/cobol/test_field_extent.py`, `tests/unit/test_abstract_location.py`, `tests/unit/cobol/test_region_id.py` (update imports; these move conceptually but may stay in place)
- Test: `tests/unit/test_cobol_memory_is_a_leaf.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: the importable module path `cobol_memory`, exporting `FieldExtent`, `Precision`, `RegionId`, `AbstractLocation`, `StorageIdentifier`. `FieldExtent` is a frozen dataclass with fields `region: RegionId`, `start: int`, `length: int`, `precision: Precision`, `field_name: str`; property `end -> int`; methods `may_alias(other: object) -> bool`, `must_cover(other: object) -> bool`, `alias_key() -> tuple[str, str]`, `is_present() -> bool`. `Precision` is an `Enum` with members `EXACT` and `CLAMPED`. Task 2 relies on `from cobol_memory.field_extent import FieldExtent, Precision` succeeding without `interpreter` being imported.

- [ ] **Step 1: Write the failing leaf test**

Create `tests/unit/test_cobol_memory_is_a_leaf.py`. This is the whole point of the extraction, so it gets a test rather than only a lint contract — an import-linter contract catches a static import, this catches the runtime consequence.

```python
import subprocess
import sys


def test_importing_cobol_memory_does_not_load_the_interpreter():
    """The reason cobol_memory is a sibling of interpreter, not a subpackage.

    Importing interpreter.anything runs interpreter/__init__.py, which loads the
    VM. A static-only consumer must be able to reach the byte-extent algebra
    without paying for that.
    """
    code = (
        "import sys;"
        "import cobol_memory.field_extent;"
        "print(any(m == 'interpreter' or m.startswith('interpreter.')"
        " for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"


def test_field_extent_surface_is_importable_from_the_new_home():
    from cobol_memory.field_extent import FieldExtent, Precision
    from cobol_memory.region_id import RegionId

    extent = FieldExtent(
        region=next(iter(RegionId)),
        start=10,
        length=5,
        precision=Precision.EXACT,
        field_name="FLD-A",
    )
    assert extent.end == 15
    assert extent.is_present() is True
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run python -m pytest tests/unit/test_cobol_memory_is_a_leaf.py -v`
Expected: FAIL, both tests, with `ModuleNotFoundError: No module named 'cobol_memory'`.

- [ ] **Step 3: Move the four modules**

```bash
cd vendor/red-dragon
mkdir -p cobol_memory
git mv interpreter/abstract_location.py   cobol_memory/abstract_location.py
git mv interpreter/storage_identifier.py  cobol_memory/storage_identifier.py
git mv interpreter/cobol/region_id.py     cobol_memory/region_id.py
git mv interpreter/cobol/field_extent.py  cobol_memory/field_extent.py
```

Create `cobol_memory/__init__.py`. Keep it empty of imports — the sibling pattern's value is that importing a submodule costs nothing, and a re-exporting `__init__` would load all four on any import.

```python
"""Byte-extent algebra for COBOL storage, importable without the interpreter.

A COBOL field is a slice of a section's region buffer, so two fields alias
exactly when their byte ranges intersect within one region. Stating that here,
as a sibling of ``cobol_asg`` rather than under ``interpreter``, is what lets a
static-only consumer use it: an import of ``interpreter.anything`` runs
``interpreter/__init__.py``, which loads the VM. See ``.importlinter``.
"""
```

- [ ] **Step 4: Fix the two intra-set imports**

In `cobol_memory/field_extent.py`, change:

```python
from interpreter.cobol.region_id import RegionId
```

to:

```python
from cobol_memory.region_id import RegionId
```

In `cobol_memory/storage_identifier.py`, change:

```python
from interpreter.abstract_location import AbstractLocation
```

to:

```python
from cobol_memory.abstract_location import AbstractLocation
```

Also update the docstring cross-reference in `cobol_memory/field_extent.py:77`, which currently reads ``interpreter.abstract_location.AbstractLocation.alias_key`` — it must become ``cobol_memory.abstract_location.AbstractLocation.alias_key`` or it points at a module that no longer exists.

- [ ] **Step 5: Register the package**

In `pyproject.toml:45`, change:

```toml
packages = ["interpreter", "cobol_asg"]
```

to:

```toml
packages = ["interpreter", "cobol_asg", "cobol_memory"]
```

- [ ] **Step 6: Declare the contract**

In `.importlinter`, add `cobol_memory` to `root_packages`:

```ini
root_packages =
    interpreter
    cobol_asg
    cobol_memory
```

Then add a leaf contract alongside `cobol-asg-is-a-leaf`:

```ini
[importlinter:contract:cobol-memory-is-a-leaf]
name = The byte-extent algebra must not import the interpreter
type = forbidden
source_modules =
    cobol_memory
forbidden_modules =
    interpreter
```

Extend the comment block above `root_packages` so the new sibling's reason is recorded next to `cobol_asg`'s: `cobol_memory` holds storage algebra rather than ASG nodes, and it is a sibling for the same reason — a consumer that only computes byte ranges must not load the VM.

- [ ] **Step 7: Run the new test to verify it is green**

Run: `uv run python -m pytest tests/unit/test_cobol_memory_is_a_leaf.py -v`
Expected: green, both tests.

- [ ] **Step 8: Update every importer**

Rewrite the import paths across the modules listed in **Files**. Four substitutions, applied to every `.py` file outside `cobol_memory/`:

```bash
cd vendor/red-dragon
find . -name '*.py' -not -path './cobol_memory/*' -not -path './.venv/*' -print0 |
  xargs -0 sed -i '' \
    -e 's/interpreter\.cobol\.field_extent/cobol_memory.field_extent/g' \
    -e 's/interpreter\.cobol\.region_id/cobol_memory.region_id/g' \
    -e 's/interpreter\.storage_identifier/cobol_memory.storage_identifier/g' \
    -e 's/interpreter\.abstract_location/cobol_memory.abstract_location/g'
```

The dotted-path form is what both `from X.Y import Z` and `import X.Y` share, so one pattern covers both spellings. `sed -i ''` is the BSD form — this is macOS.

Then confirm nothing is left behind:

```bash
grep -rn "interpreter\.cobol\.field_extent\|interpreter\.cobol\.region_id\|interpreter\.storage_identifier\|interpreter\.abstract_location" --include='*.py' .
```

Expected: no output. Test modules under `tests/` are included — `tests/unit/cobol/test_field_extent.py`, `tests/unit/test_abstract_location.py`, `tests/unit/cobol/test_region_id.py`, `tests/unit/cobol/test_memory_effects.py`, `tests/unit/cobol/test_resolved_extent.py`, `tests/unit/cobol/test_recorded_memory_effects.py` and `tests/unit/cobol/test_memory_dataflow.py` all reference at least one of these.

- [ ] **Step 9: Run the full suite**

Run: `uv run python -m pytest tests/ -q`
Expected: green, no new failures relative to the pre-change baseline. Record the baseline first if you have not: `git stash && uv run python -m pytest tests/ -q; git stash pop`.

- [ ] **Step 10: Commit**

The pre-commit hook runs Talisman, Black, import-linter, pytest and `bd backup`. Commit and fix what it rejects.

```bash
git add cobol_memory/ interpreter/ tests/ pyproject.toml .importlinter
git commit -m "refactor(cobol): byte-extent algebra becomes cobol_memory, a static-surface sibling

The alias algebra is what a static consumer needs and the only thing under
interpreter/ that has no IR dependency. Moving it to a sibling package makes it
importable without loading the VM, for the same reason cobol_asg is a sibling.
Adds cobol-memory-is-a-leaf to hold that true."
```

- [ ] **Step 11: Push, then confirm the bump target**

red-dragon's convention is to push to `main`. Confirm before pushing, then record the resulting commit SHA — Task 2 needs it.

```bash
git push origin main
git rev-parse HEAD
```

---

### Task 1b: Stop the MOVE operand serialiser losing subscripts

Added during execution, after discovering the re-parse could not have worked without it.

The ASG cache is not the bridge's JSON. `cobble/cobble/parsing/parse_corpus.py:99` writes `json.dumps(asg.to_dict())`, so anything the `to_dict` side omits is gone before any later stage reads the cache. `MoveStatement._operand_dict` omits most of the operand: it emits `name`, `ref_mod_start` and `ref_mod_length`, while `RefModOperand` also carries `subscripts`, `qualifiers`, `length_of` and `rounded`, and `RefModOperand.from_dict` reads all of them. `ComputeTarget.to_dict` in the same file does serialise `subscripts`, so MOVE departs from its neighbour rather than following a convention.

MOVE is the corpus's highest-volume verb, and a subscripted MOVE is precisely what the extent model needs to see. A `LENGTH OF` source is worse than lossy — it round-trips to an operand with an empty name.

**Repository:** `vendor/red-dragon`.

**Files:**
- Modify: `cobol_asg/cobol_statements.py` — `MoveStatement._operand_dict`
- Test: `tests/unit/cobol_asg/test_move_operand_round_trip.py` (create; place it beside the existing `cobol_asg` statement tests if they live elsewhere)

**Interfaces:**
- Consumes: nothing from Task 1 — disjoint files in the same repo.
- Produces: `MoveStatement.to_dict()` output that `MoveStatement.from_dict` can read back without loss. Task 3's diagnostic counts `subscripts` on MOVE operands, and Task 4's cache is what makes those counts non-zero.

- [ ] **Step 1: Read the reader before writing the writer**

Read `RefModOperand.from_dict` in `cobol_asg/ref_mod.py` in full and list every key it reads. The fix is to make `_operand_dict` emit exactly that set — the round trip is only closed when the writer and reader agree on the same keys. Do not guess a key name: take each one from `from_dict`.

- [ ] **Step 2: Write the failing round-trip tests**

Create the test file. `expr_to_dict`'s shape for a plain field reference is `{"kind": "ref", "name": ...}` (`cobol_asg/cobol_expression.py:264`) — confirm that against the code before relying on it, and correct the fixture rather than the implementation if it differs.

```python
from cobol_asg.cobol_statements import MoveStatement


def _round_tripped(operands: list[dict]) -> list[dict]:
    statement = MoveStatement.from_dict({"type": "MOVE", "operands": operands})
    return statement.to_dict()["operands"]


def test_a_plain_operand_serialises_exactly_as_before():
    """The compact form is load-bearing: existing caches and fixtures use it."""
    operands = [{"name": "FLD-A"}, {"name": "FLD-B"}]
    assert _round_tripped(operands) == operands


def test_reference_modification_survives_the_round_trip():
    operands = [
        {
            "name": "FLD-A",
            "ref_mod_start": {"kind": "literal", "value": "2"},
            "ref_mod_length": {"kind": "literal", "value": "3"},
        },
        {"name": "FLD-B"},
    ]
    assert _round_tripped(operands) == operands


def test_a_subscript_survives_the_round_trip():
    operands = [
        {"name": "TBL-ROW", "subscripts": [{"kind": "ref", "name": "IDX-A"}]},
        {"name": "FLD-B"},
    ]
    assert _round_tripped(operands) == operands


def test_a_length_of_source_keeps_its_data_name():
    """from_dict puts the data name in length_of and leaves name empty.

    Without a matching writer this operand serialises to {"name": ""} -- an
    operand that resolves as no field at all.
    """
    operands = [{"kind": "length_of", "name": "REC-MASTER"}, {"name": "FLD-N"}]
    assert _round_tripped(operands) == operands
```

If `from_dict` reads `qualifiers` or `rounded` on a MOVE operand, add one round-trip test per key in the same shape. Every key from Step 1's list gets a test.

- [ ] **Step 3: Run them to see which fail, and why**

Run: `uv run python -m pytest tests/unit/cobol_asg/test_move_operand_round_trip.py -v`
Expected: `test_a_plain_operand_serialises_exactly_as_before` is green (the compact path already works); the subscript, `LENGTH OF` and any qualifier/rounded tests FAIL, each showing the key silently absent from the round-tripped dict. Reference modification should survive. Record which failed — that list is the defect's real extent.

- [ ] **Step 4: Make the writer mirror the reader**

Extend `_operand_dict` so every key `from_dict` reads is emitted when set, following `ComputeTarget.to_dict`'s existing convention of omitting a key that carries no information. Omission on empty is what keeps the plain-operand form byte-identical, so the first test stays green.

`length_of` needs its own branch rather than an added key: `from_dict` recognises it by `kind` and leaves `name` empty, so a `length_of` operand must serialise back to the `{"kind": "length_of", "name": ...}` form it came from.

- [ ] **Step 5: Run the tests to verify they are green**

Run: `uv run python -m pytest tests/unit/cobol_asg/test_move_operand_round_trip.py -v`
Expected: green, all tests.

- [ ] **Step 6: Run the full suite**

Run: `uv run python -m pytest tests/ -q`
Expected: green, no new failures. Watch for tests asserting on a MOVE `to_dict()` result — a test that hard-codes the lossy output will now fail, and it is the assertion that is wrong, not the fix. Update any such test and say so in the report.

- [ ] **Step 7: Commit**

```bash
git add cobol_asg/cobol_statements.py tests/
git commit -m "fix(cobol-asg): MOVE operands keep their subscripts through to_dict

The consumer writes its cache as json.dumps(asg.to_dict()), so a key the
writer omits is gone before anything reads it. _operand_dict emitted three of
the seven fields from_dict reads, which cost every subscript on the corpus's
highest-volume verb and turned a LENGTH OF source into a nameless operand.
Mirrors ComputeTarget.to_dict, which had it right."
```

---

### Task 2: Take the extraction into forge and prove the boundary

Bump the submodule and establish, as a test cobble owns, that the byte-extent algebra is reachable from cobble without violating `cobble-no-interpreter`.

**Repository:** `red-dragon-forge`.

**Files:**
- Modify: `vendor/red-dragon` (submodule pointer)
- Modify: `.importlinter` — the Cobble comment block above `[importlinter:contract:cobble-no-interpreter]`, which lists the allowed static surface
- Test: `cobble/tests/test_static_surface.py` (create)

**Interfaces:**
- Consumes: `cobol_memory.field_extent.FieldExtent`, `cobol_memory.field_extent.Precision`, `cobol_memory.region_id.RegionId` from Task 1.
- Produces: nothing importable. Establishes that `cobble` may import `cobol_memory`, which Task 3 and the follow-on plan rely on.

- [ ] **Step 1: Write the failing test**

Create `cobble/tests/test_static_surface.py`.

```python
import subprocess
import sys


def test_cobble_can_reach_the_byte_extent_algebra():
    from cobol_memory.field_extent import FieldExtent, Precision

    assert Precision.CLAMPED is not Precision.EXACT
    assert FieldExtent.must_cover is not None


def test_reaching_it_does_not_drag_in_the_interpreter():
    """cobble-no-interpreter is a static contract; this is its runtime twin.

    import-linter sees import statements. It cannot see that importing
    cobol_memory would execute interpreter/__init__.py and load the VM.
    """
    code = (
        "import sys;"
        "import cobol_memory.field_extent;"
        "print(any(m == 'interpreter' or m.startswith('interpreter.')"
        " for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run python -m pytest cobble/tests/test_static_surface.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cobol_memory'` — the submodule still points at the pre-extraction commit.

- [ ] **Step 3: Bump the submodule**

Use the SHA recorded in Task 1 Step 11.

```bash
cd vendor/red-dragon
git fetch origin
git checkout <SHA-from-task-1>
cd ../..
uv sync --all-packages
```

`red-dragon` is an editable path dependency (`pyproject.toml:19`), so no version pin changes; `uv sync` is what makes the new package visible in the workspace venv.

- [ ] **Step 4: Run the test to verify it is green**

Run: `uv run python -m pytest cobble/tests/test_static_surface.py -v`
Expected: green, both tests.

- [ ] **Step 5: Record the widened surface**

In `.importlinter`, the comment block above the Cobble contracts states the allowed static surface and says keeping it in step is a review obligation rather than a machine-checked one. Add `cobol_memory` to that list, alongside `cobol_asg.*`, the `cics.*` parsing modules, `jackal.{model,dsn,value_parts,tso,jcl.*}` and `squall.statements`.

- [ ] **Step 6: Verify the contracts still hold**

Run: `uv run lint-imports`
Expected: all contracts kept. `cobble-no-interpreter` is unaffected — `cobol_memory` is not `interpreter`.

- [ ] **Step 7: Commit**

```bash
git add vendor/red-dragon .importlinter cobble/tests/test_static_surface.py
git commit -m "feat(cobble): reach the byte-extent algebra via cobol_memory

Bumps red-dragon to the commit that moves the alias algebra to a static-surface
sibling. The runtime test is the load-bearing one: import-linter sees imports,
not the VM that interpreter/__init__.py would load."
```

---

### Task 3: A diagnostic for what an ASG cache carries per operand

Before re-parsing, build the instrument that says whether a cache is usable. The spec's precondition is that MOVE operands carry subscripts and reference modification; `red-dragon-forge-8y0` was closed as retracted precisely because a stale cache was mistaken for a bridge defect. A committed diagnostic is what stops that recurring.

**Repository:** `red-dragon-forge`.

**Files:**
- Create: `cobble/cobble/diagnosis/asg_operands.py`
- Modify: `cobble/pyproject.toml` — add `diagnose-asg-operands` under `[project.scripts]`
- Test: `cobble/tests/diagnosis/test_asg_operands.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `cobble.diagnosis.asg_operands.operand_shapes(asg: dict) -> OperandShapes` and `cobble.diagnosis.asg_operands.cli(argv: Sequence[str] = ()) -> int`. `OperandShapes` is a frozen dataclass with integer fields `bare`, `subscripted`, `ref_modified`, `total`. Task 4 calls the CLI.

- [ ] **Step 1: Write the failing test**

Create `cobble/tests/diagnosis/test_asg_operands.py`. The fixtures are hand-built dicts in the bridge's shape, so this test does not need a corpus.

```python
from cobble.diagnosis.asg_operands import OperandShapes, operand_shapes


def _asg(*statements: dict) -> dict:
    return {
        "program_id": "PROG-A",
        "data_fields": [],
        "linkage_fields": [],
        "paragraphs": [{"name": "PARA-A", "statements": list(statements)}],
    }


def test_a_bare_operand_counts_as_bare():
    asg = _asg({"type": "MOVE", "operands": [{"name": "FLD-A"}, {"name": "FLD-B"}]})
    assert operand_shapes(asg) == OperandShapes(
        bare=2, subscripted=0, ref_modified=0, total=2
    )


def test_a_structured_subscript_counts_as_subscripted():
    asg = _asg(
        {
            "type": "MOVE",
            "operands": [
                {"name": "TBL-ROW", "subscripts": [{"type": "IDENTIFIER"}]},
                {"name": "FLD-B"},
            ],
        }
    )
    assert operand_shapes(asg) == OperandShapes(
        bare=1, subscripted=1, ref_modified=0, total=2
    )


def test_reference_modification_counts_separately():
    asg = _asg(
        {
            "type": "MOVE",
            "operands": [
                {"name": "FLD-A", "ref_mod": {"start": 2, "length": 3}},
                {"name": "FLD-B"},
            ],
        }
    )
    assert operand_shapes(asg) == OperandShapes(
        bare=1, subscripted=0, ref_modified=1, total=2
    )


def test_an_operand_with_both_counts_in_both():
    asg = _asg(
        {
            "type": "MOVE",
            "operands": [
                {
                    "name": "TBL-ROW",
                    "subscripts": [{"type": "IDENTIFIER"}],
                    "ref_mod": {"start": 1, "length": 2},
                }
            ],
        }
    )
    assert operand_shapes(asg) == OperandShapes(
        bare=0, subscripted=1, ref_modified=1, total=1
    )


def test_a_program_with_no_paragraphs_is_not_an_error():
    assert operand_shapes({"program_id": "PROG-A"}) == OperandShapes(
        bare=0, subscripted=0, ref_modified=0, total=0
    )


def test_only_move_operands_are_counted():
    asg = _asg(
        {"type": "MOVE", "operands": [{"name": "FLD-A"}]},
        {"type": "EXEC_CICS", "verb": "READ", "options": {"FILE": {"text": "DS-M"}}},
    )
    assert operand_shapes(asg).total == 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run python -m pytest cobble/tests/diagnosis/test_asg_operands.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cobble.diagnosis.asg_operands'`.

- [ ] **Step 3: Write the minimal implementation**

Create `cobble/cobble/diagnosis/asg_operands.py`.

```python
"""What a cached ASG carries per MOVE operand, counted.

Bead 8y0 was filed as a P0 bridge defect and closed as retracted: the evidence
was a cache generated before the bridge emitted structured subscripts. Nothing
downstream can tell a stale cache from a corpus property by reading it, so this
counts the distinction directly and the field analysis refuses a cache that
fails it.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OperandShapes:
    bare: int = 0
    subscripted: int = 0
    ref_modified: int = 0
    total: int = 0

    def plus(self, other: OperandShapes) -> OperandShapes:
        return OperandShapes(
            bare=self.bare + other.bare,
            subscripted=self.subscripted + other.subscripted,
            ref_modified=self.ref_modified + other.ref_modified,
            total=self.total + other.total,
        )


def operand_shapes(asg: dict) -> OperandShapes:
    return _summed(_shape(operand) for operand in _move_operands(asg))


def _move_operands(asg: dict) -> Iterator[dict]:
    for paragraph in asg.get("paragraphs") or ():
        for statement in paragraph.get("statements") or ():
            if statement.get("type") != "MOVE":
                continue
            yield from statement.get("operands") or ()


def _shape(operand: dict) -> OperandShapes:
    subscripted = bool(operand.get("subscripts"))
    ref_modified = bool(operand.get("ref_mod"))
    return OperandShapes(
        bare=int(not subscripted and not ref_modified),
        subscripted=int(subscripted),
        ref_modified=int(ref_modified),
        total=1,
    )


def _summed(shapes: Iterator[OperandShapes]) -> OperandShapes:
    total = OperandShapes()
    for shape in shapes:
        total = total.plus(shape)
    return total


def cache_shapes(asg_dir: Path) -> OperandShapes:
    return _summed(
        operand_shapes(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(asg_dir.glob("*.json"))
    )


def cli(argv: Sequence[str] = ()) -> int:
    parser = argparse.ArgumentParser(
        description="Count MOVE operand shapes across a cached ASG directory."
    )
    parser.add_argument("asg_dir", type=Path)
    arguments = parser.parse_args(tuple(argv) or None)
    if not arguments.asg_dir.is_dir():
        sys.stderr.write(f"No ASG cache at {arguments.asg_dir}\n")
        return 2
    shapes = cache_shapes(arguments.asg_dir)
    sys.stdout.write(
        f"MOVE operands: {shapes.total}\n"
        f"  bare:          {shapes.bare}\n"
        f"  subscripted:   {shapes.subscripted}\n"
        f"  ref-modified:  {shapes.ref_modified}\n"
    )
    return 0 if shapes.subscripted else 1
```

The exit status is the usable part: a cache with zero subscripted MOVE operands fails, which is what a pipeline step can gate on.

- [ ] **Step 4: Run the tests to verify they are green**

Run: `uv run python -m pytest cobble/tests/diagnosis/test_asg_operands.py -v`
Expected: green, all six tests.

If `test_a_structured_subscript_counts_as_subscripted` or `test_reference_modification_counts_separately` fails on the key name, read the real shape from the current bridge before adjusting: `RefModOperand.from_dict` in `vendor/red-dragon/cobol_asg/cobol_statements.py` is authoritative for what keys the bridge emits. Fix the test's fixture to match the real key, not the implementation to match a guessed one.

- [ ] **Step 5: Register the entry point**

In `cobble/pyproject.toml` under `[project.scripts]`, alongside the existing `diagnose-*` entries:

```toml
diagnose-asg-operands = "cobble.diagnosis.asg_operands:cli"
```

- [ ] **Step 6: Verify the entry point resolves**

Run: `uv sync --all-packages && uv run diagnose-asg-operands --help`
Expected: the argparse usage line, exit 0.

- [ ] **Step 7: Commit**

```bash
git add cobble/cobble/diagnosis/asg_operands.py \
        cobble/tests/diagnosis/test_asg_operands.py \
        cobble/pyproject.toml
git commit -m "feat(cobble): count MOVE operand shapes in a cached ASG

8y0 was filed as a P0 bridge defect and retracted once the cache turned out to
predate the fix. Nothing downstream can tell those apart by reading the cache,
so count it and let a non-zero exit gate the stages that need subscripts."
```

---

### Task 4: Re-parse the corpus into a fresh cache

The existing cache predates both the current bridge JAR and the upstream extent work. The parse is skip-if-cached, so a re-parse must target a new directory — and its own config comment records the cost, 557 MB and roughly four hours of JVM, so the existing cache must survive until the new one is validated.

**Repository:** `red-dragon-forge`, run from `cobble/`.

**Files:**
- Create: `cobble/config/parse.local.reparse.toml` (gitignored — `config/*.toml` holds absolute corpus paths)
- Modify: nothing tracked

**Interfaces:**
- Consumes: `diagnose-asg-operands` from Task 3, and Task 1b's serialiser fix by way of the submodule pointer Task 2 set. Without 1b this task burns four hours to produce a cache that fails its own Step 5 gate — confirm the pointer includes it before starting.
- Produces: a validated ASG cache directory. Records its path for the follow-on plan.

- [ ] **Step 1: Confirm the bridge JAR is current**

```bash
cd /Users/avisheksengupta/code/red-dragon-forge
ls -l vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
git -C vendor/red-dragon log -1 --format='%h %ci %s'
```

Expected: the JAR's mtime is at or after the submodule commit from Task 1. If it is older, rebuild: `make jar-force` from `vendor/red-dragon`, or `make jar` from the forge root.

- [ ] **Step 2: Copy the parse config to a fresh output directory**

Copy `cobble/config/parse.local.toml` to `cobble/config/parse.local.reparse.toml` and change exactly one key:

```toml
asg_dir = "out-corpus-parsed-2"
```

Leave `cobol_dir`, `cobol_globs`, `copybook_dirs`, `copybook_extensions` and `bridge_jar` untouched. Both directories are covered by the existing `out-*/` gitignore rule.

- [ ] **Step 3: Start the parse**

This is a multi-hour job. Run it in the background so the session is not blocked, and do not poll it — the harness re-invokes on completion.

```bash
cd /Users/avisheksengupta/code/red-dragon-forge/cobble
uv run --no-sync cobble-parse-corpus --config config/parse.local.reparse.toml --jobs 10
```

- [ ] **Step 4: Check for recorded failures**

The parse writes `<program>.fail` beside the `.json` it could not produce, and that is also what makes the skip work on a resumed run.

```bash
ls cobble/out-corpus-parsed-2/*.fail 2>/dev/null | wc -l
ls cobble/out-corpus-parsed-2/*.json | wc -l
```

Expected: the `.json` count is at or above the old cache's 3,779. Compare the `.fail` count against the old cache's; a rise means the JAR bump regressed something and must be investigated before proceeding.

- [ ] **Step 5: Run the diagnostic against both caches**

```bash
cd /Users/avisheksengupta/code/red-dragon-forge
uv run diagnose-asg-operands cobble/out-corpus-parsed-2; echo "exit=$?"
uv run diagnose-asg-operands cobble/out-corpus-parsed;   echo "exit=$?"
```

Expected: the new cache exits 0 with a non-zero `subscripted` count. The old cache exits 1 with `subscripted: 0` and `bare: 512432`, which is the retraction in 8y0 reproduced as a measurement.

- [ ] **Step 6: Record the outcome, do not switch yet**

Note the new cache's path and its three counts. Leave `parse.local.toml` and the old cache in place: the existing srccfg work reads the old one, and switching is the follow-on plan's business, not this task's.

There is nothing tracked to commit in this task.

---

### Task 5: Re-measure the spec's cache-derived figures

The spec carries a caveat, added deliberately, that every figure drawn from the stale cache must be re-measured before being quoted. Discharge it.

**Repository:** `red-dragon-forge`.

**Files:**
- Modify: `docs/superpowers/specs/2026-09-05-field-level-byte-dataflow-design.md` — the "Corpus measurements" section and the "Prerequisite: re-parse" section

**Interfaces:**
- Consumes: the validated cache from Task 4.
- Produces: a spec whose figures are current. No code.

- [ ] **Step 1: Re-measure the structural claims**

Write this to `$TMPDIR/remeasure.py` and run it with `uv run python $TMPDIR/remeasure.py cobble/out-corpus-parsed-2`. Delete it afterwards — it prints corpus-derived counts, which are fine in a tracked spec, but it must not become a tracked script that names corpus paths.

```python
import json
import sys
from collections import Counter
from pathlib import Path

asg_dir = Path(sys.argv[1])
verbs = Counter()
cics = Counter()
usage = Counter()
linkage = Counter()
edges = set()
dynamic = 0
programs = set()

for path in sorted(asg_dir.glob("*.json")):
    asg = json.loads(path.read_text(encoding="utf-8"))
    program = asg.get("program_id") or path.stem
    programs.add(program)

    top = [f for f in (asg.get("linkage_fields") or ()) if f.get("level") == 1]
    commarea = [f for f in top if f.get("name") == "DFHCOMMAREA"]
    if not top:
        linkage["none"] += 1
    elif commarea and not (commarea[0].get("children") or ()):
        linkage["flat DFHCOMMAREA"] += 1
    else:
        linkage["structured"] += 1

    for field in asg.get("data_fields") or ():
        usage[(field.get("usage") or "DISPLAY").upper()] += 1

    for paragraph in asg.get("paragraphs") or ():
        for statement in paragraph.get("statements") or ():
            kind = statement.get("type")
            verbs[kind] += 1
            if kind == "EXEC_CICS":
                cics[statement.get("verb")] += 1
                target = (statement.get("options") or {}).get("PROGRAM")
                if statement.get("verb") in ("LINK", "XCTL"):
                    name = (target or {}).get("text")
                    if name and name.startswith("'"):
                        edges.add((program, name.strip("'")))
                    else:
                        dynamic += 1

print(f"programs: {len(programs)}")
print(f"linkage: {dict(linkage)}")
print(f"literal call edges: {len(edges)}")
print(f"resolved: {sum(1 for _, t in edges if t in programs)}")
print(f"dynamic call sites: {dynamic}")
print(f"self-recursive: {sum(1 for s, t in edges if s == t)}")
print(f"verbs: {verbs.most_common(12)}")
print(f"cics: {cics.most_common(6)}")
print(f"usage: {usage.most_common()}")
```

The acyclicity claim needs one more step, since the above only catches self-loops. Check for larger cycles with a topological peel over `edges` restricted to resolved targets: repeatedly drop nodes with no outgoing resolved edge; whatever remains is in a cycle. Expected: nothing remains.

Cross-check `linkage` against the spec's flat/none/structured split. If the flat count moves materially, the child-list heuristic above disagrees with however the original measurement defined "flat" — reconcile before editing the spec, because that figure carries the "needs no special machinery" argument in the Cross-program section.

- [ ] **Step 2: Re-measure the subscript figures, now from the cache**

The spec currently sources the subscript and reference-modification counts from source text because the cache could not supply them. With a good cache, take them from `diagnose-asg-operands` and from a per-shape count over MOVE operands, and say so — a cache-derived figure is the one the analysis will actually see.

- [ ] **Step 3: Update the spec**

Replace the figures in "Corpus measurements". Remove the `**Caveat, per 8y0**` paragraph, since it exists only to mark figures as provisional. In "Prerequisite: re-parse", replace the forward-looking wording with the outcome: which cache is current, what the diagnostic reported, and what the follow-on plan should read.

Keep the generic identifiers. The no-external-identifiers constraint applies to this file.

- [ ] **Step 4: Verify no corpus identifiers were reintroduced**

Grep `docs/superpowers/specs/2026-09-05-field-level-byte-dataflow-design.md` for the corpus's own identifiers — the member-name prefixes visible in the cache directory's filenames and the source root's name in `parse.local.toml`. This plan cannot spell them out: it is tracked, and the constraint it is checking forbids them here too.

Expected: no output.

- [ ] **Step 5: Update the beads**

In the local DB only — per the Global Constraints, do not export or stage `issues/issues.jsonl` in forge.

```bash
bd close red-dragon-forge-j7w --reason="Subsumed by the byte-extent model: containment, REDEFINES, OCCURS and reference modification all fall out of extent overlap. See the field-level byte dataflow spec."
bd update red-dragon-forge-pr2 --notes="Rescoped by the 2026-09-05 design: the alias algebra is extracted from upstream rather than built here, so this becomes operand-to-extent construction only."
```

- [ ] **Step 6: Commit the spec**

```bash
git add docs/superpowers/specs/2026-09-05-field-level-byte-dataflow-design.md
git commit -m "docs(cobble): current figures in the field dataflow design

Discharges the caveat the spec carried: every count drawn from the previous ASG
cache is replaced with one measured against the rebuilt cache."
```

---

## What this plan does not do

Building `cobble/dataflow/fields/` — `extent.py`, `transfer.py`, `fixpoint.py`, `summary.py`, `interprocedural.py`, `naming.py`, `emit.py`. That is a separate plan, written after Task 4 lands, because `extent.py`'s tests must be written against the operand shape the rebuilt cache actually carries. Writing them now would mean inventing fixtures for a shape not yet observed.

Also out of scope: forge's beads redaction, which blocks committing `issues/issues.jsonl` and is an open decision; and switching `parse.local.toml` to the new cache, which belongs with the consumer that needs it.
