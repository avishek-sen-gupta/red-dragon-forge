# PARM= → COBOL LINKAGE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pass JCL `EXEC PGM=...,PARM='...'` values into the COBOL program's LINKAGE SECTION at runtime so programs like CBACT04C can read their startup arguments.

**Architecture:** Three layers in order: (1) pure Python — model field, deserializer, and a pure `build_parm_region` function; (2) Java bridge — extract PARM text from the parse tree and emit it in the step JSON; (3) injection — lift `cobol_step.py` to `compile_cobol` + `run_linked` with a pre-seeded `VMState` when PARM is non-empty. Empty PARM leaves the existing `run()` path untouched.

**Tech Stack:** Python 3.13, Java (ANTLR4 JCL bridge), red-dragon vendored at `vendor/red-dragon/`, `struct.pack(">H", ...)` for big-endian halfword, `uv run --no-sync pytest`.

## Global Constraints

- Always invoke Python tools with `uv run --no-sync` (e.g. `uv run --no-sync pytest`, `uv run --no-sync python -m black`)
- No `None` defaults; no defensive guards — fail loud
- Frozen dataclasses for all new data types
- No comments explaining WHAT; only add a comment when WHY is non-obvious
- Export env vars before running tests:
  ```bash
  export PROLEAP_BRIDGE_JAR="$(pwd)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar"
  export JCL_BRIDGE_JAR="$(pwd)/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar"
  export CARDDEMO_HOME="$HOME/code/aws-mainframe-carddemo/app"
  ```
- After any Java change to `jcl-bridge/`: rebuild with `cd jcl-bridge && mvn -DskipTests package -q`
- `bd export -o beads/issues.jsonl && git add beads/issues.jsonl` before committing if beads issues changed

---

## File Map

| File | Change |
|---|---|
| `jackal/model.py` | Add `parm: str = ""` to `Step` dataclass |
| `jackal/jcl/bridge_parser.py` | Add `parm=s.get("parm", "")` in `_step_from_json` |
| `jackal/parm.py` | **New** — `build_parm_region(parm: str) -> bytes` |
| `jackal/cobol_step.py` | Add PARM path: compile + seed `VMState` + `run_linked` |
| `jcl-bridge/src/main/java/org/jackal/jcl/JclSerializer.java` | Extract PARM from parse tree; emit `"parm"` field in step JSON |
| `tests/unit/test_parm.py` | **New** — unit tests for `build_parm_region` + deserializer parm field |
| `tests/integration/test_jcl_bridge_jar.py` | Add 2 tests: PARM present and absent via real JAR |
| `tests/integration/test_parm_cobol_step.py` | **New** — end-to-end: minimal COBOL with LINKAGE, assert receipt |

---

### Task 1: Model field + parm builder

**Files:**
- Modify: `jackal/model.py`
- Modify: `jackal/jcl/bridge_parser.py`
- Create: `jackal/parm.py`
- Create: `tests/unit/test_parm.py`

**Interfaces:**
- Produces:
  - `Step.parm: str` (default `""`) in `jackal.model`
  - `build_parm_region(parm: str) -> bytes` in `jackal.parm`

---

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_parm.py`:

```python
"""Unit tests for PARM region builder and model/deserializer parm field."""

from __future__ import annotations

import struct

import pytest

from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_build_parm_region_empty():
    from jackal.parm import build_parm_region

    result = build_parm_region("")
    assert result == b"\x00\x00"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_build_parm_region_text():
    from jackal.parm import build_parm_region

    result = build_parm_region("2022071800")
    assert result == b"\x00\x0a" + b"2022071800"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_build_parm_region_single_char():
    from jackal.parm import build_parm_region

    result = build_parm_region("X")
    assert result == b"\x00\x01X"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_build_parm_region_too_long_raises():
    from jackal.parm import build_parm_region

    with pytest.raises(ValueError, match="too long"):
        build_parm_region("A" * (0x7FFF + 1))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_step_parm_field_default():
    from jackal.model import Step

    step = Step(name="S", pgm="P", dds=())
    assert step.parm == ""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_step_parm_field_set():
    from jackal.model import Step

    step = Step(name="S", pgm="P", dds=(), parm="2022071800")
    assert step.parm == "2022071800"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_deserializer_parm_present():
    from jackal.jcl.bridge_parser import _job_from_json

    data = {
        "name": "J",
        "steps": [{"name": "S", "pgm": "P", "parm": "HELLO", "dds": []}],
    }
    job = _job_from_json(data)
    assert job.steps[0].parm == "HELLO"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_deserializer_parm_absent_defaults_empty():
    from jackal.jcl.bridge_parser import _job_from_json

    data = {"name": "J", "steps": [{"name": "S", "pgm": "P", "dds": []}]}
    job = _job_from_json(data)
    assert job.steps[0].parm == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run --no-sync pytest tests/unit/test_parm.py -v
```

Expected: ImportError or AttributeError on all tests.

- [ ] **Step 3: Add `parm` field to `Step` in `jackal/model.py`**

Current `Step` (lines 61-65):
```python
@dataclass(frozen=True)
class Step:
    name: str
    pgm: str
    dds: tuple[DD, ...]
    conds: tuple[Cond, ...] = ()
```

Replace with:
```python
@dataclass(frozen=True)
class Step:
    name: str
    pgm: str
    dds: tuple[DD, ...]
    conds: tuple[Cond, ...] = ()
    parm: str = ""
```

- [ ] **Step 4: Add `parm` to `_step_from_json` in `jackal/jcl/bridge_parser.py`**

Current `_step_from_json` (lines 36-42):
```python
def _step_from_json(s: dict) -> Step:
    return Step(
        name=s["name"],
        pgm=s["pgm"],
        dds=tuple(_dd_from_json(d) for d in s["dds"]),
        conds=tuple(_cond_from_json(c) for c in s.get("cond", ())),
    )
```

Replace with:
```python
def _step_from_json(s: dict) -> Step:
    return Step(
        name=s["name"],
        pgm=s["pgm"],
        dds=tuple(_dd_from_json(d) for d in s["dds"]),
        conds=tuple(_cond_from_json(c) for c in s.get("cond", ())),
        parm=s.get("parm", ""),
    )
```

- [ ] **Step 5: Create `jackal/parm.py`**

```python
"""Build the OS halfword-prefixed PARM region for COBOL LINKAGE injection."""

from __future__ import annotations

import struct


def build_parm_region(parm: str) -> bytes:
    if len(parm) > 0x7FFF:
        raise ValueError(f"PARM too long: {len(parm)} bytes > 32767 (signed halfword max)")
    return struct.pack(">H", len(parm)) + parm.encode("latin-1")
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
uv run --no-sync pytest tests/unit/test_parm.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 7: Run full suite to check nothing regressed**

```bash
uv run --no-sync pytest tests/unit/ -v
```

Expected: all unit tests PASS.

- [ ] **Step 8: Commit**

```bash
git add jackal/model.py jackal/jcl/bridge_parser.py jackal/parm.py tests/unit/test_parm.py
git commit -m "feat(jcl): Step.parm field + build_parm_region (jackal-1o2.13)"
```

---

### Task 2: Java bridge — emit PARM

**Files:**
- Modify: `jcl-bridge/src/main/java/org/jackal/jcl/JclSerializer.java`
- Modify: `tests/integration/test_jcl_bridge_jar.py`

**Interfaces:**
- Consumes: `execParmPARM` grammar rule → `JCLParser.ExecParmPARMContext`
- Produces: `"parm": "<text-without-quotes>"` in step JSON (empty string when absent)

---

- [ ] **Step 1: Write the failing integration tests**

Append to `tests/integration/test_jcl_bridge_jar.py`:

```python
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_parm(jcl_bridge_jar):
    jcl = "//J JOB 1\n//STEP1 EXEC PGM=CBACT04C,PARM='2022071800'\n"
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert job.steps[0].parm == "2022071800"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_absent_parm_is_empty_string(jcl_bridge_jar):
    jcl = "//J JOB 1\n//STEP1 EXEC PGM=MYPGM\n"
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert job.steps[0].parm == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run --no-sync pytest tests/integration/test_jcl_bridge_jar.py -v -k "parm"
```

Expected: `assert job.steps[0].parm == "2022071800"` fails with `AttributeError` (no `parm` attribute on Step) — Task 1 must be done first, so after Task 1 this will fail with `AssertionError` since the bridge doesn't emit `parm` yet.

- [ ] **Step 3: Add PARM extraction to `JclSerializer.java`**

In `buildStep()` in `jcl-bridge/src/main/java/org/jackal/jcl/JclSerializer.java`, find the COND block (around line 210) and add the PARM block immediately after `step.add("cond", condArray);` and before the DD block:

```java
            // PARM= on the EXEC statement
            String parm = "";
            if (execStmt != null) {
                JCLParser.ExecParmPARMContext parmCtx =
                        findChild(execStmt, JCLParser.ExecParmPARMContext.class);
                if (parmCtx != null) {
                    JCLParser.KeywordOrSymbolicContext kwCtx =
                            findChild(parmCtx, JCLParser.KeywordOrSymbolicContext.class);
                    if (kwCtx != null) {
                        String raw = kwCtx.getText();
                        // Strip surrounding apostrophes from JCL quoted string convention
                        if (raw.startsWith("'") && raw.endsWith("'") && raw.length() >= 2) {
                            raw = raw.substring(1, raw.length() - 1);
                        }
                        parm = raw;
                    }
                }
            }
            step.addProperty("parm", parm);
```

The existing context in `buildStep()` where you insert this (after the cond block and before the DD block):

```java
            step.add("cond", condArray);

            // << INSERT PARM BLOCK HERE >>

            // DD statements — ddStatementAmalgamation children of jclStep
            JsonArray dds = new JsonArray();
```

- [ ] **Step 4: Rebuild the JAR**

```bash
cd jcl-bridge && mvn -DskipTests package -q && cd ..
```

Expected: BUILD SUCCESS (no output on success with -q). The JAR is at `jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar`.

Verify JAR was updated:
```bash
ls -la jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar
```

- [ ] **Step 5: Run integration tests to verify they pass**

```bash
uv run --no-sync pytest tests/integration/test_jcl_bridge_jar.py -v
```

Expected: all 4 tests PASS (2 existing + 2 new PARM tests).

- [ ] **Step 6: Commit**

```bash
git add jcl-bridge/src/main/java/org/jackal/jcl/JclSerializer.java \
        tests/integration/test_jcl_bridge_jar.py
git commit -m "feat(jcl-bridge): emit PARM= field in step JSON (jackal-1o2.13)"
```

---

### Task 3: Injection — cobol_step.py + end-to-end test

**Files:**
- Modify: `jackal/cobol_step.py`
- Create: `tests/integration/test_parm_cobol_step.py`

**Interfaces:**
- Consumes: `Step.parm: str` (Task 1), `build_parm_region` from `jackal.parm` (Task 1)
- Consumes from red-dragon:
  - `compile_cobol(source: bytes, *, copybook_dirs: list[Path] | None = None) -> tuple[Any, LinkedProgram]` from `interpreter.project.cobol_compile`
  - `run_linked(linked: LinkedProgram, entry_point: EntryPoint, ..., io_provider=None, initial_vm: VMState | None = None) -> VMState` from `interpreter.run`
  - `EntryPoint.top_level() -> EntryPoint` from `interpreter.project.entry_point`
  - `VMState` (mutable, `call_stack: list[StackFrame]`, `region_set(addr, data)`) from `interpreter.vm.vm_types`
  - `StackFrame(function_name: FuncName, local_vars: dict[VarName, TypedValue])` from `interpreter.vm.vm_types`
  - `Address(name: str)` from `interpreter.address`
  - `VarName(name: str)` from `interpreter.var_name`
  - `FuncName(name: str)` from `interpreter.func_name`
  - `TypedValue(value: Any, type: TypeExpr)` from `interpreter.types.typed_value`
  - `UNKNOWN: TypeExpr` from `interpreter.types.type_expr`

---

- [ ] **Step 1: Write the failing integration tests**

Create `tests/integration/test_parm_cobol_step.py`:

```python
"""Integration tests: PARM= injection into COBOL LINKAGE via run_linked."""

from __future__ import annotations

from pathlib import Path

import pytest

from jackal.catalog import DatasetCatalog
from jackal.cobol_step import run_cobol_step
from jackal.model import Step
from tests.covers import NotLanguageFeature, covers

# Minimal COBOL program that reads PARM-DATA and signals receipt via RETURN-CODE.
# PARM-LENGTH (S9(04) COMP) is a 2-byte big-endian halfword — matches build_parm_region.
# When PARM-DATA = 'HELLO     ', sets RETURN-CODE = 42; else 0.
_PARM_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPARM.
       LINKAGE SECTION.
       01  PARM-AREA.
           05  PARM-LENGTH  PIC S9(04) COMP.
           05  PARM-DATA    PIC X(10).
       PROCEDURE DIVISION USING PARM-AREA.
           IF PARM-DATA = 'HELLO     '
               MOVE 42 TO RETURN-CODE
           ELSE
               MOVE 0 TO RETURN-CODE
           END-IF
           STOP RUN.
"""

# Minimal COBOL program with no LINKAGE — tests the no-PARM path is unchanged.
_NO_PARM_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOPARM.
       PROCEDURE DIVISION.
           MOVE 7 TO RETURN-CODE.
           STOP RUN.
"""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parm_received_in_cobol_linkage(tmp_path, bridge_jar):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    # Pad to 10 chars so the region exactly fills PARM-DATA PIC X(10)
    step = Step(name="S", pgm="TESTPARM", dds=(), parm="HELLO     ")
    result = run_cobol_step(step, _PARM_PROGRAM, cat, bridge_jar, [])
    assert result.return_code == 42


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_no_parm_step_runs_unchanged(tmp_path, bridge_jar):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    step = Step(name="S", pgm="NOPARM", dds=())
    result = run_cobol_step(step, _NO_PARM_PROGRAM, cat, bridge_jar, [])
    assert result.return_code == 7
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run --no-sync pytest tests/integration/test_parm_cobol_step.py -v
```

Expected: `test_parm_received_in_cobol_linkage` — FAIL (PARM not injected so RETURN-CODE = 0, not 42). `test_no_parm_step_runs_unchanged` may PASS already (no-PARM path exists). Both should ultimately PASS after this task.

- [ ] **Step 3: Update imports in `jackal/cobol_step.py`**

Current imports (lines 1-16):
```python
"""Run an EXEC PGM COBOL step against the red-dragon VM."""

from __future__ import annotations

from pathlib import Path

from interpreter.cobol.cobol_parser import ProLeapCobolParser
from interpreter.cobol.real_file_provider import RealFileIOProvider
from interpreter.cobol.subprocess_runner import RealSubprocessRunner
from interpreter.cobol.return_code_readback import read_return_code
from interpreter.constants import Language
from interpreter.run import run

from jackal.catalog import DatasetCatalog
from jackal.model import Step
from jackal.results import StepDisposition, StepResult
```

Replace with:
```python
"""Run an EXEC PGM COBOL step against the red-dragon VM."""

from __future__ import annotations

from pathlib import Path

from interpreter.address import Address
from interpreter.cobol.cobol_parser import ProLeapCobolParser
from interpreter.cobol.real_file_provider import RealFileIOProvider
from interpreter.cobol.subprocess_runner import RealSubprocessRunner
from interpreter.cobol.return_code_readback import read_return_code
from interpreter.constants import Language
from interpreter.func_name import FuncName
from interpreter.project.cobol_compile import compile_cobol
from interpreter.project.entry_point import EntryPoint
from interpreter.run import run, run_linked
from interpreter.types.type_expr import UNKNOWN
from interpreter.types.typed_value import TypedValue
from interpreter.var_name import VarName
from interpreter.vm.vm_types import StackFrame, VMState

from jackal.catalog import DatasetCatalog
from jackal.model import Step
from jackal.parm import build_parm_region
from jackal.results import StepDisposition, StepResult
```

- [ ] **Step 4: Add the PARM injection path in `run_cobol_step`**

Current `run_cobol_step` body (lines 45-76):
```python
def run_cobol_step(
    step: Step,
    source: str,
    catalog: DatasetCatalog,
    bridge_jar: str,
    copybook_dirs: list[Path],
) -> StepResult:
    if not bridge_jar:
        raise ValueError(
            f"PROLEAP_BRIDGE_JAR not set; required to run COBOL step {step.name!r}"
        )
    overrides = _overrides(step, catalog)
    provider = RealFileIOProvider(
        base_dir=catalog.workdir,
        file_control=_file_control(source, bridge_jar, copybook_dirs),
        path_overrides=overrides,
    )
    vm = run(
        source,
        language=Language.COBOL,
        io_provider=provider,
        max_steps=500_000,
        copybook_dirs=copybook_dirs,
    )
    for dd in step.dds:
        catalog.dispose(dd)
    return StepResult(
        name=step.name,
        return_code=read_return_code(vm),
        ran=True,
        disposition=StepDisposition.EXECUTED,
    )
```

Replace with:
```python
def run_cobol_step(
    step: Step,
    source: str,
    catalog: DatasetCatalog,
    bridge_jar: str,
    copybook_dirs: list[Path],
) -> StepResult:
    if not bridge_jar:
        raise ValueError(
            f"PROLEAP_BRIDGE_JAR not set; required to run COBOL step {step.name!r}"
        )
    overrides = _overrides(step, catalog)
    provider = RealFileIOProvider(
        base_dir=catalog.workdir,
        file_control=_file_control(source, bridge_jar, copybook_dirs),
        path_overrides=overrides,
    )
    if step.parm:
        _, linked = compile_cobol(source.encode("utf-8"), copybook_dirs=copybook_dirs)
        parm_addr = Address("rgn_parm")
        parm_vm = VMState()
        parm_vm.region_set(parm_addr, bytearray(build_parm_region(step.parm)))
        parm_vm.call_stack.append(
            StackFrame(
                function_name=FuncName("__jcl_entry__"),
                local_vars={
                    VarName("__params_region"): TypedValue(value=parm_addr, type=UNKNOWN)
                },
            )
        )
        vm = run_linked(
            linked,
            EntryPoint.top_level(),
            io_provider=provider,
            initial_vm=parm_vm,
            max_steps=500_000,
        )
    else:
        vm = run(
            source,
            language=Language.COBOL,
            io_provider=provider,
            max_steps=500_000,
            copybook_dirs=copybook_dirs,
        )
    for dd in step.dds:
        catalog.dispose(dd)
    return StepResult(
        name=step.name,
        return_code=read_return_code(vm),
        ran=True,
        disposition=StepDisposition.EXECUTED,
    )
```

- [ ] **Step 5: Run the integration tests**

```bash
uv run --no-sync pytest tests/integration/test_parm_cobol_step.py -v
```

Expected: both tests PASS.

- [ ] **Step 6: Run the full suite**

```bash
uv run --no-sync pytest tests/ -v
```

Expected: all tests PASS. In particular:
- `tests/unit/test_parm.py` — 8 unit tests
- `tests/unit/test_cobol_step_guard.py` — guard test unchanged
- `tests/integration/test_jcl_bridge_jar.py` — 4 tests (2 old + 2 new)
- `tests/integration/test_parm_cobol_step.py` — 2 new tests

- [ ] **Step 7: Commit**

```bash
git add jackal/cobol_step.py tests/integration/test_parm_cobol_step.py
git commit -m "feat(cobol_step): inject PARM= into COBOL LINKAGE via run_linked (jackal-1o2.13)"
```

- [ ] **Step 8: Close the beads issue**

```bash
bd close jackal-1o2.13
bd export -o beads/issues.jsonl && git add beads/issues.jsonl
git commit -m "chore(beads): close jackal-1o2.13 — PARM= COBOL linkage injection"
```
