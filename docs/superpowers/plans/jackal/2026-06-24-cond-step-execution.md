# COND= Conditional Step Execution — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make jackal honor JCL `COND=` — bypass a step based on prior steps' real return codes ("stop the job if anything failed").

**Architecture:** The flat `Job.steps` model survives (COND= is a step/job *attribute*). Two changes: COBOL steps report their **real** `RETURN-CODE` (today hardcoded 0), and the runner becomes a **fold** that threads executed results and evaluates a pure `should_bypass()` before dispatching each step. The ANTLR mapa grammar already *parses* COND=; the work is surfacing it through the bridge JSON → model and evaluating it.

**Tech Stack:** Python 3.13 (frozen dataclasses, uv, pytest, black), Java 17 + ANTLR (the jcl-bridge), red-dragon VM (`read_return_code`).

## Global Constraints

- **No `None` defaults** in signatures; **no defensive guards**; **fail loud** (raise, don't swallow).
- **FP:** frozen dataclasses; pure functions; functional core / imperative shell.
- **No regex for parsing** — the ANTLR grammar parses COND=; Python never regex-parses JCL.
- **TDD:** write the failing test first; integration tests exercise VM execution via `run()`; cover **all** reachable paths.
- **IBM COND semantics (exact):** `COND=(code,op)` ⇒ **bypass if `code op RC` is true** (operands reversed). No `stepname` ⇒ test every prior **executed** step; with `stepname` ⇒ only that step. **Bypass if ANY condition is true** (multiple conditions, and job-level OR step-level). A named step that didn't run contributes no RC (condition false for it). Bypassed steps contribute no RC to later tests.
- **Operators:** `GT GE EQ NE LT LE` only.
- **`COND=EVEN`/`COND=ONLY`** → fail loud ("unsupported"), deferred to `jackal-1o2.8`.
- Tooling: `uv run --no-sync python -m pytest …`; `make jar` rebuilds the bridge; `uv run --no-sync python -m black .` before commit; commit through the real pre-commit hooks. Tests carry `@covers(NotLanguageFeature.INFRASTRUCTURE)`.
- Env for integration/e2e: `export PROLEAP_BRIDGE_JAR="$(pwd)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar" JCL_BRIDGE_JAR="$(pwd)/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar" CARDDEMO_HOME="$HOME/code/aws-mainframe-carddemo/app"`.

---

## File Structure

- **`jackal/results.py`** (modify) — add `StepDisposition` enum + `StepResult.disposition`.
- **`jackal/model.py`** (modify) — add `CondOp` enum, `Cond` dataclass, `Step.conds`, `Job.cond`.
- **`jackal/cond.py`** (create) — pure `should_bypass(conds, prior_executed) -> bool`.
- **`jackal/jcl/bridge_parser.py`** (modify) — deserialize `cond` JSON → model.
- **`jcl-bridge/src/main/java/org/jackal/jcl/JclSerializer.java`** (modify) — emit `cond` on steps + job.
- **`jackal/cobol_step.py`** (modify) — return the VM's real `RETURN-CODE`.
- **`jackal/runner.py`** (modify) — fold; evaluate COND before dispatch.

The JSON contract gains: step-level `"cond": [{"code":int,"op":str,"step":str}]` and top-level (job) `"cond": [...]`. Absent ⇒ empty list (back-compat).

---

## Task 1: StepDisposition enum + StepResult.disposition

**Files:**
- Modify: `jackal/results.py`
- Test: `tests/unit/test_results.py` (create)

**Interfaces:**
- Produces: `class StepDisposition(Enum)` with `EXECUTED`, `BYPASSED`; `StepResult` gains `disposition: StepDisposition = StepDisposition.EXECUTED` (keeps `name: str`, `return_code: int`, `ran: bool`).

- [ ] **Step 1: Write the failing test** — `tests/unit/test_results.py`:
```python
from tests.covers import NotLanguageFeature, covers
from jackal.results import StepResult, StepDisposition, JobResult


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_stepresult_defaults_to_executed():
    r = StepResult(name="A", return_code=0, ran=True)
    assert r.disposition is StepDisposition.EXECUTED


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_stepresult_bypassed_is_explicit():
    r = StepResult(
        name="B", return_code=0, ran=False, disposition=StepDisposition.BYPASSED
    )
    assert r.disposition is StepDisposition.BYPASSED and r.ran is False
    JobResult(steps=(r,))  # still composes
```

- [ ] **Step 2: Run → fail.** `uv run --no-sync python -m pytest tests/unit/test_results.py -v` → FAIL (`StepDisposition` undefined).

- [ ] **Step 3: Implement** — `jackal/results.py` becomes:
```python
"""Execution results."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class StepDisposition(Enum):
    EXECUTED = "EXECUTED"
    BYPASSED = "BYPASSED"


@dataclass(frozen=True)
class StepResult:
    name: str
    return_code: int
    ran: bool
    disposition: StepDisposition = StepDisposition.EXECUTED


@dataclass(frozen=True)
class JobResult:
    steps: tuple[StepResult, ...]
```

- [ ] **Step 4: Run → pass.** `uv run --no-sync python -m pytest tests/unit/test_results.py -v` → 2 passed.

- [ ] **Step 5: Commit.**
```bash
uv run --no-sync python -m black jackal/results.py tests/unit/test_results.py
git add jackal/results.py tests/unit/test_results.py
git commit -m "feat(results): StepDisposition enum + StepResult.disposition (jackal-1o2.1)"
```

---

## Task 2: COND model — CondOp, Cond, Step.conds, Job.cond

**Files:**
- Modify: `jackal/model.py`
- Test: `tests/unit/test_model.py` (append)

**Interfaces:**
- Produces: `class CondOp(Enum)` (`GT GE EQ NE LT LE`); `@dataclass(frozen=True) class Cond` with `code: int`, `op: CondOp`, `step: str = ""`; `Step` gains `conds: tuple[Cond, ...] = ()`; `Job` gains `cond: tuple[Cond, ...] = ()`.

- [ ] **Step 1: Write the failing test** — append to `tests/unit/test_model.py`:
```python
from jackal.model import CondOp, Cond


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cond_model_and_defaults():
    c = Cond(code=0, op=CondOp.NE)
    assert c.step == "" and c.op is CondOp.NE and c.code == 0
    step = Step(name="S", pgm="P", dds=(), conds=(c,))
    assert step.conds == (c,)
    job = Job(name="J", steps=(step,), cond=(Cond(code=4, op=CondOp.LT, step="S1"),))
    assert job.cond[0].step == "S1"
    # Step.conds and Job.cond default to empty
    assert Step(name="X", pgm="P", dds=()).conds == ()
    assert Job(name="J2", steps=()).cond == ()
```
(`Step`, `Job`, `covers`, `NotLanguageFeature` are already imported in this file.)

- [ ] **Step 2: Run → fail.** `uv run --no-sync python -m pytest tests/unit/test_model.py::test_cond_model_and_defaults -v` → FAIL (`CondOp` undefined).

- [ ] **Step 3: Implement** — in `jackal/model.py`, add after the `DatasetOrg` enum (and extend `Step`/`Job`):
```python
class CondOp(Enum):
    GT = "GT"
    GE = "GE"
    EQ = "EQ"
    NE = "NE"
    LT = "LT"
    LE = "LE"


@dataclass(frozen=True)
class Cond:
    code: int
    op: CondOp
    step: str = ""  # "" = test all prior executed steps
```
Then change `Step` and `Job`:
```python
@dataclass(frozen=True)
class Step:
    name: str
    pgm: str
    dds: tuple[DD, ...]
    conds: tuple[Cond, ...] = ()


@dataclass(frozen=True)
class Job:
    name: str
    steps: tuple[Step, ...]
    cond: tuple[Cond, ...] = ()
```

- [ ] **Step 4: Run → pass.** `uv run --no-sync python -m pytest tests/unit/test_model.py -v` → all pass (existing + new).

- [ ] **Step 5: Commit.**
```bash
uv run --no-sync python -m black jackal/model.py tests/unit/test_model.py
git add jackal/model.py tests/unit/test_model.py
git commit -m "feat(model): CondOp/Cond + Step.conds/Job.cond (jackal-1o2.1)"
```

---

## Task 3: COND evaluator — `jackal/cond.py`

**Files:**
- Create: `jackal/cond.py`
- Test: `tests/unit/test_cond.py` (create)

**Interfaces:**
- Consumes: `Cond`, `CondOp` (Task 2); `StepResult` (Task 1 — uses only `.name` and `.return_code`).
- Produces: `def should_bypass(conds: tuple[Cond, ...], prior_executed: tuple[StepResult, ...]) -> bool`.

**Semantics note for the implementer:** `prior_executed` is the runner's list of steps that **actually executed** (the runner filters; this function does not look at `disposition`). Reversed operand: a condition is true when `code <op> rc` holds for **any** relevant RC.

- [ ] **Step 1: Write the failing test** — `tests/unit/test_cond.py`:
```python
from tests.covers import NotLanguageFeature, covers
from jackal.cond import should_bypass
from jackal.model import Cond, CondOp
from jackal.results import StepResult


def _r(name: str, rc: int) -> StepResult:
    return StepResult(name=name, return_code=rc, ran=True)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_no_conditions_never_bypasses():
    assert should_bypass((), (_r("A", 8),)) is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_0_ne_bypasses_when_any_prior_failed():
    # COND=(0,NE): bypass if 0 NE rc, i.e. any prior rc != 0
    cond = (Cond(code=0, op=CondOp.NE),)
    assert should_bypass(cond, (_r("A", 0),)) is False
    assert should_bypass(cond, (_r("A", 0), _r("B", 8))) is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_4_lt_bypasses_when_prior_rc_above_4():
    # COND=(4,LT): bypass if 4 LT rc, i.e. rc > 4
    cond = (Cond(code=4, op=CondOp.LT),)
    assert should_bypass(cond, (_r("A", 4),)) is False
    assert should_bypass(cond, (_r("A", 8),)) is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_named_step_only_tests_that_step():
    cond = (Cond(code=0, op=CondOp.NE, step="A"),)
    assert should_bypass(cond, (_r("A", 0), _r("B", 8))) is False  # A is 0
    assert should_bypass(cond, (_r("A", 8), _r("B", 0))) is True   # A is 8


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_named_step_not_run_is_false():
    cond = (Cond(code=0, op=CondOp.NE, step="ZZZ"),)
    assert should_bypass(cond, (_r("A", 8),)) is False  # ZZZ never ran


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_multiple_conditions_bypass_if_any():
    cond = (Cond(code=4, op=CondOp.LT), Cond(code=8, op=CondOp.EQ))
    assert should_bypass(cond, (_r("A", 8),)) is True   # 8 EQ 8
    assert should_bypass(cond, (_r("A", 0),)) is False  # neither


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_all_six_operators():
    rc = (_r("A", 5),)
    assert should_bypass((Cond(6, CondOp.GT),), rc) is True    # 6 > 5
    assert should_bypass((Cond(6, CondOp.GE),), rc) is True
    assert should_bypass((Cond(5, CondOp.EQ),), rc) is True
    assert should_bypass((Cond(4, CondOp.NE),), rc) is True
    assert should_bypass((Cond(4, CondOp.LT),), rc) is True    # 4 < 5
    assert should_bypass((Cond(5, CondOp.LE),), rc) is True
    assert should_bypass((Cond(4, CondOp.GT),), rc) is False   # 4 > 5 false
```

- [ ] **Step 2: Run → fail.** `uv run --no-sync python -m pytest tests/unit/test_cond.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement** — `jackal/cond.py`:
```python
"""Pure evaluation of JCL COND= step-bypass conditions (IBM semantics)."""

from __future__ import annotations

import operator
from collections.abc import Callable

from jackal.model import Cond, CondOp
from jackal.results import StepResult

_OPS: dict[CondOp, Callable[[int, int], bool]] = {
    CondOp.GT: operator.gt,
    CondOp.GE: operator.ge,
    CondOp.EQ: operator.eq,
    CondOp.NE: operator.ne,
    CondOp.LT: operator.lt,
    CondOp.LE: operator.le,
}


def _condition_true(cond: Cond, prior_executed: tuple[StepResult, ...]) -> bool:
    # Reversed operands: bypass if `code <op> rc` for any relevant prior RC.
    if cond.step:
        rcs = [r.return_code for r in prior_executed if r.name == cond.step]
    else:
        rcs = [r.return_code for r in prior_executed]
    test = _OPS[cond.op]
    return any(test(cond.code, rc) for rc in rcs)


def should_bypass(
    conds: tuple[Cond, ...], prior_executed: tuple[StepResult, ...]
) -> bool:
    """True if this step should be bypassed — i.e. ANY condition is true."""
    return any(_condition_true(c, prior_executed) for c in conds)
```

- [ ] **Step 4: Run → pass.** `uv run --no-sync python -m pytest tests/unit/test_cond.py -v` → all pass.

- [ ] **Step 5: Commit.**
```bash
uv run --no-sync python -m black jackal/cond.py tests/unit/test_cond.py
git add jackal/cond.py tests/unit/test_cond.py
git commit -m "feat(cond): pure COND= bypass evaluator (jackal-1o2.1)"
```

---

## Task 4: Deserialize `cond` JSON → model

**Files:**
- Modify: `jackal/jcl/bridge_parser.py`
- Test: `tests/unit/test_jcl_bridge_deserialize.py` (append)

**Interfaces:**
- Consumes: `Cond`, `CondOp` (Task 2). The bridge JSON now carries `"cond": [{"code":int,"op":str,"step":str}]` on steps and a top-level `"cond"` on the job.
- Produces: `_cond_from_json(c: dict) -> Cond`; `_step_from_json` populates `conds`; `_job_from_json` populates `cond`. A bad/unsupported op (`EVEN`/`ONLY`) raises `ValueError` (→ `JclParseError` via the existing `parse()` wrapper).

- [ ] **Step 1: Write the failing test** — append to `tests/unit/test_jcl_bridge_deserialize.py`:
```python
import pytest
from jackal.model import CondOp


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_deserialize_step_and_job_cond():
    data = {
        "name": "J",
        "cond": [{"code": 0, "op": "NE", "step": ""}],
        "steps": [
            {
                "name": "S",
                "pgm": "P",
                "cond": [{"code": 4, "op": "LT", "step": "A"}],
                "dds": [],
            }
        ],
    }
    job = _job_from_json(data)
    assert job.cond[0].op is CondOp.NE and job.cond[0].code == 0
    assert job.steps[0].conds[0].op is CondOp.LT
    assert job.steps[0].conds[0].step == "A"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_deserialize_absent_cond_is_empty():
    data = {"name": "J", "steps": [{"name": "S", "pgm": "P", "dds": []}]}
    job = _job_from_json(data)
    assert job.cond == () and job.steps[0].conds == ()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_deserialize_even_op_fails_loud():
    data = {
        "name": "J",
        "steps": [
            {"name": "S", "pgm": "P", "cond": [{"code": 0, "op": "EVEN"}], "dds": []}
        ],
    }
    with pytest.raises(ValueError):
        _job_from_json(data)
```
(`_job_from_json`, `covers`, `NotLanguageFeature` are already imported in this file.)

- [ ] **Step 2: Run → fail.** `uv run --no-sync python -m pytest tests/unit/test_jcl_bridge_deserialize.py -v` → FAIL (cond not populated / no raise).

- [ ] **Step 3: Implement** — in `jackal/jcl/bridge_parser.py`: add `Cond, CondOp` to the model import, add `_cond_from_json`, and populate `conds`/`cond`:
```python
from jackal.model import Cond, CondOp, DD, Disp, DispNormal, DispStatus, Job, Step
```
```python
def _cond_from_json(c: dict) -> Cond:
    return Cond(code=c["code"], op=CondOp(c["op"]), step=c.get("step", ""))
```
```python
def _step_from_json(s: dict) -> Step:
    return Step(
        name=s["name"],
        pgm=s["pgm"],
        dds=tuple(_dd_from_json(d) for d in s["dds"]),
        conds=tuple(_cond_from_json(c) for c in s.get("cond", ())),
    )


def _job_from_json(data: dict) -> Job:
    return Job(
        name=data["name"],
        steps=tuple(_step_from_json(s) for s in data["steps"]),
        cond=tuple(_cond_from_json(c) for c in data.get("cond", ())),
    )
```
(No change needed in `JclBridgeParser.parse` — it already catches `ValueError` and re-raises `JclParseError`, so `CondOp("EVEN")` fails loud through the real parse path.)

- [ ] **Step 4: Run → pass.** `uv run --no-sync python -m pytest tests/unit/test_jcl_bridge_deserialize.py -v` → all pass.

- [ ] **Step 5: Commit.**
```bash
uv run --no-sync python -m black jackal/jcl/bridge_parser.py tests/unit/test_jcl_bridge_deserialize.py
git add jackal/jcl/bridge_parser.py tests/unit/test_jcl_bridge_deserialize.py
git commit -m "feat(jcl): deserialize COND= into Step.conds/Job.cond (jackal-1o2.1)"
```

---

## Task 5: Java bridge — emit `cond` on steps + job

**Files:**
- Modify: `jcl-bridge/src/main/java/org/jackal/jcl/JclSerializer.java`
- Test: `tests/integration/test_jcl_bridge_cond.py` (create)

**Interfaces:**
- Consumes: the Task-4 deserializer (the integration test parses through `parse_jcl`).
- Produces: the JAR emits `"cond"` arrays per the contract. `COND=EVEN`/`ONLY` → emit `{"code":0,"op":"EVEN"}` (or `"ONLY"`) so the Python deserializer fails loud in one place.

- [ ] **Step 1: Discover the mapa COND rule names.** Build the JAR if needed (`make jar`), then with antlr4-tools (in a throwaway venv, e.g. `python3 -m venv /tmp/antlr && /tmp/antlr/bin/pip install antlr4-tools`) inspect the parse tree for a COND step:
```bash
printf '//J JOB 1\n//S EXEC PGM=P,COND=(0,NE)\n//T EXEC PGM=Q,COND=((4,LT),(8,EQ))\n' > /tmp/c.jcl
antlr4-parse jcl-bridge/src/main/antlr4/org/jackal/jcl/JCLLexer.g4 \
             jcl-bridge/src/main/antlr4/org/jackal/jcl/JCLParser.g4 startRule -tree /tmp/c.jcl
```
Read the printed tree to find the rule(s) carrying the COND parameter and its `(code,op[,stepname])` / multi-`((..),(..))` structure (and the JOB-card COND). Record the rule names in a comment in `JclSerializer.java`. **Do not guess** — bind the walker to the actual rule names (same method used for the existing fields; see the comment block already atop `JclSerializer.java`).

- [ ] **Step 2: Write the failing integration test** — `tests/integration/test_jcl_bridge_cond.py`:
```python
import pytest
from tests.covers import NotLanguageFeature, covers
from jackal.jcl.parser import parse_jcl
from jackal.model import CondOp


@pytest.fixture(autouse=True)
def _require_jcl_bridge(jcl_bridge_jar):
    """parse_jcl shells to the bridge; ensure JCL_BRIDGE_JAR is set."""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bridge_emits_step_cond():
    job = parse_jcl("//J JOB 1\n//S EXEC PGM=P,COND=(0,NE)\n")
    assert job.steps[0].conds == (
        __import__("jackal.model", fromlist=["Cond"]).Cond(code=0, op=CondOp.NE),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bridge_emits_multiple_conditions():
    job = parse_jcl("//J JOB 1\n//S EXEC PGM=P,COND=((4,LT),(8,EQ))\n")
    ops = [(c.code, c.op) for c in job.steps[0].conds]
    assert ops == [(4, CondOp.LT), (8, CondOp.EQ)]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bridge_emits_cond_with_stepname():
    job = parse_jcl("//J JOB 1\n//A EXEC PGM=P\n//B EXEC PGM=Q,COND=(0,NE,A)\n")
    assert job.steps[1].conds[0].step == "A"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bridge_cond_even_fails_loud():
    from jackal.jcl.bridge_parser import JclParseError

    with pytest.raises(JclParseError):
        parse_jcl("//J JOB 1\n//S EXEC PGM=P,COND=EVEN\n")
```

- [ ] **Step 3: Run → fail.** With the JARs built and env exported:
```bash
uv run --no-sync python -m pytest tests/integration/test_jcl_bridge_cond.py -v
```
Expected: FAIL (`conds` empty — bridge doesn't emit `cond` yet).

- [ ] **Step 4: Implement** — in `JclSerializer.java`, in the step-building code, add a `cond` JSON array built from the discovered COND rule (one object per condition: `code` int, `op` string, `step` string or `""`). Add the same for the JOB card → top-level `cond`. For `COND=EVEN`/`COND=ONLY`, emit a single `{"code":0,"op":"EVEN"|"ONLY","step":""}`. Mirror the existing field-emission style (Gson, `getText()` on the rule's children). Then rebuild:
```bash
make jar
```

- [ ] **Step 5: Run → pass.**
```bash
uv run --no-sync python -m pytest tests/integration/test_jcl_bridge_cond.py -v
```
Expected: 4 passed. (If a mapping is off, fix `JclSerializer.java` + `make jar` — never weaken the test.)

- [ ] **Step 6: Commit.** (Talisman may flag the `.java`/test — append by-checksum entries to `.talismanrc` before the `version:` line if so.)
```bash
git add jcl-bridge/src/main/java/org/jackal/jcl/JclSerializer.java tests/integration/test_jcl_bridge_cond.py
git commit -m "feat(jcl-bridge): emit COND= conditions in the JSON AST (jackal-1o2.1)"
```

---

## Task 6: Real return code from COBOL steps (Part 1)

**Files:**
- Modify: `jackal/cobol_step.py`
- Test: `tests/integration/test_cobol_step_return_code.py` (create)

**Interfaces:**
- Consumes: red-dragon `interpreter.cobol.return_code_readback.read_return_code(vm) -> int`; `run(...)` returns a `VMState`.
- Produces: `run_cobol_step` returns `StepResult(return_code=<real RC>, disposition=EXECUTED, ran=True)` instead of hardcoded `0`.

- [ ] **Step 1: Write the failing integration test** — `tests/integration/test_cobol_step_return_code.py`:
```python
from pathlib import Path

import pytest

from tests.covers import NotLanguageFeature, covers
from jackal.catalog import DatasetCatalog
from jackal.cobol_step import run_cobol_step
from jackal.model import Step

_PGM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SETRC.
       PROCEDURE DIVISION.
           MOVE 8 TO RETURN-CODE.
           STOP RUN.
"""


@pytest.fixture(autouse=True)
def _require_bridge(bridge_jar):
    """Enforce PROLEAP_BRIDGE_JAR."""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cobol_step_returns_real_return_code(tmp_path: Path, bridge_jar):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    step = Step(name="S", pgm="SETRC", dds=())
    res = run_cobol_step(step, _PGM, cat, bridge_jar, [])
    assert res.return_code == 8 and res.ran is True
```
(The `bridge_jar` fixture lives in `tests/conftest.py`.)

- [ ] **Step 2: Run → fail.** With `PROLEAP_BRIDGE_JAR` exported:
```bash
uv run --no-sync python -m pytest tests/integration/test_cobol_step_return_code.py -v
```
Expected: FAIL (`return_code == 0`, hardcoded).

- [ ] **Step 3: Implement** — in `jackal/cobol_step.py`: import the helper + `StepDisposition`, capture the VM, read the RC. Add imports:
```python
from interpreter.cobol.return_code_readback import read_return_code
from jackal.results import StepResult, StepDisposition
```
Change the tail of `run_cobol_step` (the `run(...)` call + return) to:
```python
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
(If `StepResult` was imported elsewhere in the file, keep a single import; ensure `StepDisposition` is imported.)

- [ ] **Step 4: Run → pass.**
```bash
uv run --no-sync python -m pytest tests/integration/test_cobol_step_return_code.py -v
```
Expected: 1 passed.

- [ ] **Step 5: Guard — the gated CardDemo e2e still passes** (its steps legitimately return 0):
```bash
uv run --no-sync python -m pytest tests/integration/test_carddemo_acctfile_e2e.py -v
```
Expected: passes unchanged.

- [ ] **Step 6: Commit.**
```bash
uv run --no-sync python -m black jackal/cobol_step.py tests/integration/test_cobol_step_return_code.py
git add jackal/cobol_step.py tests/integration/test_cobol_step_return_code.py
git commit -m "feat(cobol-step): return the VM's real RETURN-CODE (jackal-1o2.1 Part 1)"
```

---

## Task 7: Runner fold — evaluate COND, bypass steps

**Files:**
- Modify: `jackal/runner.py`
- Test: `tests/unit/test_runner.py` (append), `tests/integration/test_cond_e2e.py` (create)

**Interfaces:**
- Consumes: `should_bypass` (Task 3); `StepResult`/`StepDisposition` (Task 1); `Job.cond`/`Step.conds` (Task 2); real RCs (Task 6).
- Produces: `JobRunner.run_job` evaluates COND before each step; a bypassed step yields `StepResult(name, return_code=0, ran=False, disposition=BYPASSED)` and is **not** dispatched; only EXECUTED results feed later tests.

- [ ] **Step 1: Write the failing unit tests** — append to `tests/unit/test_runner.py` (synthetic, no bridge — IEFBR14 returns RC 0; IDCAMS returns a real MAXCC from in-stream). Use IDCAMS to produce a nonzero RC: a `DELETE` of a missing DSN returns MAXCC 8.
```python
from jackal.model import Cond, CondOp
from jackal.results import StepDisposition


def _idcams_delete_missing(name: str, conds=()):
    # DELETE of an uncataloged DSN -> MAXCC 8 (real nonzero RC, no COBOL/bridge).
    return Step(
        name=name,
        pgm="IDCAMS",
        dds=(
            DD(
                ddname="SYSIN",
                dsn="",
                disp=_DUMMY_DISP,
                in_stream=("DELETE NOPE.NOPE CLUSTER",),
            ),
        ),
        conds=conds,
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cond_bypasses_step_after_failure(tmp_path: Path) -> None:
    job = Job(
        name="J",
        steps=(
            _idcams_delete_missing("A"),  # MAXCC 8
            Step(
                name="B",
                pgm="IEFBR14",
                dds=(),
                conds=(Cond(code=0, op=CondOp.NE),),  # bypass if any prior rc != 0
            ),
        ),
    )
    runner = JobRunner(
        source_dir=tmp_path, bridge_jar="unused", data_dir=tmp_path, copybook_dir=tmp_path
    )
    res = runner.run(job, workdir=tmp_path, seeds={})
    a, b = res.steps
    assert a.return_code == 8 and a.disposition is StepDisposition.EXECUTED
    assert b.disposition is StepDisposition.BYPASSED and b.ran is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cond_runs_step_when_clean(tmp_path: Path) -> None:
    job = Job(
        name="J",
        steps=(
            Step(name="A", pgm="IEFBR14", dds=()),  # RC 0
            Step(
                name="B",
                pgm="IEFBR14",
                dds=(),
                conds=(Cond(code=0, op=CondOp.NE),),
            ),
        ),
    )
    runner = JobRunner(
        source_dir=tmp_path, bridge_jar="unused", data_dir=tmp_path, copybook_dir=tmp_path
    )
    res = runner.run(job, workdir=tmp_path, seeds={})
    assert all(s.disposition is StepDisposition.EXECUTED for s in res.steps)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_job_level_cond_applies_to_all_steps(tmp_path: Path) -> None:
    job = Job(
        name="J",
        steps=(
            _idcams_delete_missing("A"),  # MAXCC 8
            Step(name="B", pgm="IEFBR14", dds=()),  # no own COND
        ),
        cond=(Cond(code=0, op=CondOp.NE),),  # job-level: bypass all after a failure
    )
    runner = JobRunner(
        source_dir=tmp_path, bridge_jar="unused", data_dir=tmp_path, copybook_dir=tmp_path
    )
    res = runner.run(job, workdir=tmp_path, seeds={})
    assert res.steps[1].disposition is StepDisposition.BYPASSED
```

- [ ] **Step 2: Run → fail.** `uv run --no-sync python -m pytest tests/unit/test_runner.py -v` → the 3 new tests FAIL (no bypass logic; step B runs).

- [ ] **Step 3: Implement** — rewrite `JobRunner.run_job` in `jackal/runner.py` as a fold, and import the pieces. Add imports:
```python
from jackal.cond import should_bypass
from jackal.results import JobResult, StepResult, StepDisposition
```
Replace `run_job`:
```python
    def run_job(self, job: Job, catalog: DatasetCatalog) -> JobResult:
        """Run a job against a pre-built catalog, honoring COND= step bypass.

        Threads the results of steps that actually executed; before each step,
        bypass it if job-level or step-level COND= is satisfied (IBM semantics:
        bypass if any condition is true against any prior executed step).
        """
        executed: list[StepResult] = []
        results: list[StepResult] = []
        for step in job.steps:
            conds = job.cond + step.conds
            if should_bypass(conds, tuple(executed)):
                results.append(
                    StepResult(
                        name=step.name,
                        return_code=0,
                        ran=False,
                        disposition=StepDisposition.BYPASSED,
                    )
                )
                continue
            result = self._run_step(step, catalog)
            executed.append(result)
            results.append(result)
        return JobResult(steps=tuple(results))
```
(`_run_step` and `run` are unchanged. `JobResult` import already present — ensure the combined import line is correct and `StepDisposition`/`StepResult`/`should_bypass` are imported.)

- [ ] **Step 4: Run → pass.** `uv run --no-sync python -m pytest tests/unit/test_runner.py -v` → all pass.

- [ ] **Step 5: Write the gated integration e2e** — `tests/integration/test_cond_e2e.py` (real COBOL RC + bridge-parsed COND, through `JobRunner`):
```python
from pathlib import Path

import pytest

from tests.covers import NotLanguageFeature, covers
from jackal.catalog import DatasetCatalog
from jackal.jcl.parser import parse_jcl
from jackal.results import StepDisposition
from jackal.runner import JobRunner

_FAIL_PGM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FAILS.
       PROCEDURE DIVISION.
           MOVE 8 TO RETURN-CODE.
           STOP RUN.
"""
_OK_PGM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OK.
       PROCEDURE DIVISION.
           STOP RUN.
"""


@pytest.fixture(autouse=True)
def _require(bridge_jar, jcl_bridge_jar):
    """Both JARs are required for this end-to-end COND test."""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cond_bypasses_real_cobol_step(tmp_path: Path, bridge_jar, jcl_bridge_jar):
    src = tmp_path / "src"
    src.mkdir()
    (src / "FAILS.cbl").write_text(_FAIL_PGM)
    (src / "OK.cbl").write_text(_OK_PGM)
    jcl = "//J JOB 1\n//A EXEC PGM=FAILS\n//B EXEC PGM=OK,COND=(0,NE)\n"
    job = parse_jcl(jcl)
    runner = JobRunner(
        source_dir=src, bridge_jar=bridge_jar, data_dir=tmp_path, copybook_dir=tmp_path
    )
    res = runner.run(job, workdir=tmp_path, seeds={})
    a, b = res.steps
    assert a.return_code == 8 and a.disposition is StepDisposition.EXECUTED
    assert b.disposition is StepDisposition.BYPASSED  # COND=(0,NE) bypassed after RC 8
```

- [ ] **Step 6: Run the e2e + the full suite.** With all three env vars exported:
```bash
uv run --no-sync python -m black .
uv run --no-sync python -m pytest tests/integration/test_cond_e2e.py -v
uv run --no-sync python -m pytest -q
```
Expected: the e2e passes and the **entire suite is green** (including the CardDemo e2e). Investigate any failure — do not weaken tests.

- [ ] **Step 7: Commit.**
```bash
git add jackal/runner.py tests/unit/test_runner.py tests/integration/test_cond_e2e.py
git commit -m "feat(runner): honor COND= — RC-gated step bypass via fold (jackal-1o2.1)"
```

---

## Self-Review

**Spec coverage:**
- `StepDisposition` enum + `StepResult.disposition` → Task 1 ✓
- `CondOp`/`Cond`/`Step.conds`/`Job.cond` → Task 2 ✓
- Pure `should_bypass` evaluator (reversed operands, any-true, named/all-prior, named-not-run=false, all 6 ops, multi-condition) → Task 3 ✓
- Deserialize `cond` JSON; EVEN/bad op fails loud → Task 4 ✓
- Bridge emits `cond` (steps + job; EVEN/ONLY marker); rule discovered via `antlr4-parse` → Task 5 ✓
- Part 1 real return code via `read_return_code` → Task 6 ✓
- Runner fold; job-level + step-level; bypassed excluded from prior; gated COBOL e2e → Task 7 ✓
- JOB-level COND → Task 7 Step 1 (`test_job_level_cond_applies_to_all_steps`) ✓
- Fail-loud EVEN/ONLY → Task 4 (deser) + Task 5 (bridge) ✓
- CardDemo e2e guard for the Part-1 behavior change → Task 6 Step 5 + Task 7 Step 6 ✓

**Placeholder scan:** No TBD/"handle edge cases"/"similar to". The one real unknown — mapa's COND rule names — is an explicit `antlr4-parse -tree` discovery step (Task 5 Step 1), not guessed, because those names live only in the vendored grammar.

**Type consistency:** `StepDisposition.{EXECUTED,BYPASSED}`, `CondOp.{GT,GE,EQ,NE,LT,LE}`, `Cond(code:int, op:CondOp, step:str="")`, `should_bypass(conds: tuple[Cond,...], prior_executed: tuple[StepResult,...]) -> bool`, `_cond_from_json(dict)->Cond`, `read_return_code(vm)->int` — consistent across Tasks 1–7. JSON field names (`cond`/`code`/`op`/`step`) identical in the Java emitter (Task 5) and the Python deserializer (Task 4).
