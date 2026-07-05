# Backward References (DSN=*.STEP.DD) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Honor `DSN=*.STEP.DD` backward references in JCL, resolving them to the dataset allocated in a named prior step's DD; bypass the referencing step (IBM-faithful) when the referenced step didn't run.

**Architecture:** A third DSN variant `BackwardRef(step, ddname)` joins the `DirectDSN | TempRef` union. The Java bridge detects `*.STEP.DD` and emits structured JSON; the Python parser materialises `BackwardRef` from it. The runner resolves backward refs before dispatching each step, recording resolved DSNs in a per-job registry.

**Tech Stack:** Python 3.13, Java (Maven), ANTLR JCL grammar (ProLeap), pytest, `uv run --no-sync`

## Global Constraints

- TDD: write failing tests first, run to confirm failure, then implement.
- `uv run --no-sync pytest` — never plain `pytest`.
- `make jar-force` after any Java bridge change (rebuilds both JARs).
- `DD.dsn` is `DSN` everywhere — `BackwardRef` must never reach `catalog.allocate()` unresolved.
- IBM bypass propagation: if the referenced step did not run → bypass the referencing step (not an error).
- `DSN=*.STEP.PROCSTEP.DD` (three-segment) is out of scope — raise `ValueError` in the Python parser if encountered, message referencing `jackal-lz8`.
- Export env vars before any test run that touches the JAR:
  ```bash
  export PROLEAP_BRIDGE_JAR="$(pwd)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar"
  export JCL_BRIDGE_JAR="$(pwd)/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar"
  export CARDDEMO_HOME="$HOME/code/aws-mainframe-carddemo/app"
  ```
- All tests use `@covers(NotLanguageFeature.INFRASTRUCTURE)` decorator (see `tests/covers.py`).
- Talisman runs in the pre-commit hook. JCL keywords (PASS, NEW, OLD, DISP) trigger false positives. If commit fails, add a checksum entry for the offending file in `.talismanrc` **before** the `version: "1.0"` line (append-only).

---

## File Map

| File | Change |
|---|---|
| `jackal/dsn.py` | Add `BackwardRef`; update `DSN` union; add `case BackwardRef` to `dsn_key()` |
| `jcl-bridge/src/main/java/org/jackal/jcl/JclSerializer.java` | Detect `*.STEP.DD` DSN; emit `{"backref": {"step": ..., "ddname": ...}}` |
| `jackal/jcl/bridge_parser.py` | Dispatch on `"backref"` key in `_dd_from_json`; raise `ValueError` for three-segment form |
| `jackal/runner.py` | Add `_resolve_step()`, `_record_dds()`; update `run_job()` |
| `tests/unit/test_dsn.py` | 3 new tests for `BackwardRef` construction, equality, `dsn_key` error |
| `tests/unit/test_jcl_bridge_deserialize.py` | 2 new tests: `backref` JSON → `BackwardRef`; three-segment raises |
| `tests/integration/test_jcl_bridge_jar.py` | 1 new JAR test: `DSN=*.STEP1.WRK` parses to `BackwardRef` |
| `tests/unit/test_runner.py` | 3 new tests: resolve substitutes; returns `None` on missing step; TempRef recorded as DirectDSN |
| `tests/integration/test_backward_refs.py` | New file: 2 integration tests (happy path; bypass propagation) |

---

### Task 1: `BackwardRef` type in `jackal/dsn.py`

**Files:**
- Modify: `jackal/dsn.py`
- Modify: `tests/unit/test_dsn.py`

**Interfaces:**
- Produces:
  - `BackwardRef(step: str, ddname: str)` — frozen dataclass
  - `DSN = DirectDSN | TempRef | BackwardRef` — updated union alias
  - `dsn_key(BackwardRef(...))` raises `TypeError` with message containing `"BackwardRef"`

- [ ] **Step 1: Write 3 failing tests in `tests/unit/test_dsn.py`**

Append to the existing file:

```python
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_backward_ref_fields():
    from jackal.dsn import BackwardRef

    br = BackwardRef(step="STEP1", ddname="WRK")
    assert br.step == "STEP1"
    assert br.ddname == "WRK"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_backward_ref_equality():
    from jackal.dsn import BackwardRef

    assert BackwardRef("STEP1", "WRK") == BackwardRef("STEP1", "WRK")
    assert BackwardRef("STEP1", "WRK") != BackwardRef("STEP2", "WRK")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dsn_key_raises_for_backward_ref():
    from jackal.dsn import BackwardRef, dsn_key

    with pytest.raises(TypeError, match="BackwardRef"):
        dsn_key(BackwardRef("STEP1", "WRK"))
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run --no-sync pytest tests/unit/test_dsn.py::test_backward_ref_fields tests/unit/test_dsn.py::test_backward_ref_equality tests/unit/test_dsn.py::test_dsn_key_raises_for_backward_ref -v
```

Expected: 3 failures — `ImportError: cannot import name 'BackwardRef'`

- [ ] **Step 3: Implement `BackwardRef` in `jackal/dsn.py`**

Replace the entire file with:

```python
"""DSN type hierarchy: DirectDSN for permanent datasets, TempRef for &&NAME temps,
BackwardRef for *.STEP.DD references resolved at runtime by the runner."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DirectDSN:
    name: str


@dataclass(frozen=True)
class TempRef:
    alias: str  # full &&NAME string, e.g. "&&WORKIN"


@dataclass(frozen=True)
class BackwardRef:
    step: str    # step name, e.g. "STEP1"
    ddname: str  # DD name, e.g. "WRK"


type DSN = DirectDSN | TempRef | BackwardRef


def dsn_key(dsn: DSN) -> str:
    """Extract the string DSN name from a DirectDSN.

    Raises TypeError for TempRef or BackwardRef — both must be resolved via
    the catalog / runner before they can be used as a string key.
    """
    match dsn:
        case DirectDSN(name=n):
            return n
        case TempRef(alias=a):
            raise TypeError(f"TempRef '{a}' must be resolved via the catalog")
        case BackwardRef(step=s, ddname=d):
            raise TypeError(
                f"BackwardRef '*.{s}.{d}' must be resolved via the runner"
            )
        case _:
            raise TypeError(f"Unhandled DSN type: {dsn!r}")
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run --no-sync pytest tests/unit/test_dsn.py -v
```

Expected: all 9 tests pass (6 existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add jackal/dsn.py tests/unit/test_dsn.py
git commit -m "feat: add BackwardRef DSN variant for *.STEP.DD resolution (jackal-1o2.10)"
```

---

### Task 2: Java bridge + Python parser

**Files:**
- Modify: `jcl-bridge/src/main/java/org/jackal/jcl/JclSerializer.java`
- Modify: `jackal/jcl/bridge_parser.py`
- Modify: `tests/unit/test_jcl_bridge_deserialize.py`
- Modify: `tests/integration/test_jcl_bridge_jar.py`

**Interfaces:**
- Consumes: `BackwardRef(step, ddname)` from Task 1
- Produces:
  - Java bridge emits `{"backref": {"step": "STEP1", "ddname": "WRK"}}` for `DSN=*.STEP1.WRK`
  - `_dd_from_json({"backref": {"step": "STEP1", "ddname": "WRK"}, ...})` → `DD(dsn=BackwardRef("STEP1", "WRK"), ...)`
  - `_dd_from_json({"dsn": "*.STEP1.PSTEP.WRK", ...})` → raises `ValueError`

- [ ] **Step 1: Write 2 failing unit tests in `tests/unit/test_jcl_bridge_deserialize.py`**

Append to the existing file (after the last test):

```python
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dd_from_json_backref_dsn():
    from jackal.dsn import BackwardRef
    from jackal.jcl.bridge_parser import _job_from_json

    data = {
        "name": "J",
        "steps": [
            {
                "name": "S",
                "pgm": "P",
                "dds": [
                    {
                        "ddname": "INPUT",
                        "dsn": "",
                        "backref": {"step": "STEP1", "ddname": "WRK"},
                        "disp_words": ["OLD", "DELETE"],
                        "in_stream": [],
                        "sysout": False,
                    }
                ],
            }
        ],
    }
    job = _job_from_json(data)
    dd = job.steps[0].dds[0]
    assert isinstance(dd.dsn, BackwardRef)
    assert dd.dsn.step == "STEP1"
    assert dd.dsn.ddname == "WRK"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dd_from_json_three_segment_backref_raises():
    from jackal.jcl.bridge_parser import _job_from_json

    data = {
        "name": "J",
        "steps": [
            {
                "name": "S",
                "pgm": "P",
                "dds": [
                    {
                        "ddname": "INPUT",
                        "dsn": "*.STEP1.PSTEP.WRK",
                        "disp_words": ["OLD", "DELETE"],
                        "in_stream": [],
                        "sysout": False,
                    }
                ],
            }
        ],
    }
    with pytest.raises(ValueError, match="jackal-lz8"):
        _job_from_json(data)
```

- [ ] **Step 2: Run unit tests to confirm they fail**

```bash
uv run --no-sync pytest tests/unit/test_jcl_bridge_deserialize.py::test_dd_from_json_backref_dsn tests/unit/test_jcl_bridge_deserialize.py::test_dd_from_json_three_segment_backref_raises -v
```

Expected: 2 failures — `AssertionError` (no `backref` key dispatched) and no `ValueError` raised.

- [ ] **Step 3: Write the failing JAR integration test in `tests/integration/test_jcl_bridge_jar.py`**

Append to the existing file:

```python
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_backward_ref(jcl_bridge_jar):
    jcl = (
        "//J JOB 1\n"
        "//STEP1 EXEC PGM=IEFBR14\n"
        "//WRK DD DSN=MY.FILE,DISP=(NEW,PASS)\n"
        "//STEP2 EXEC PGM=IEFBR14\n"
        "//INPUT DD DSN=*.STEP1.WRK,DISP=(OLD,DELETE)\n"
    )
    from jackal.dsn import BackwardRef
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    dd = job.steps[1].dds[0]
    assert isinstance(dd.dsn, BackwardRef)
    assert dd.dsn.step == "STEP1"
    assert dd.dsn.ddname == "WRK"
```

Run it to see what the current JAR emits (it will fail — this reveals what the grammar actually produces):

```bash
uv run --no-sync pytest tests/integration/test_jcl_bridge_jar.py::test_real_jar_parses_backward_ref -v
```

Expected: FAIL. Note the actual `dd.dsn` value printed by pytest — it tells you whether the grammar emits `dsn: "*.STEP1.WRK"` (a string) or `dsn: ""` (missed entirely).

- [ ] **Step 4: Update `JclSerializer.java` to emit `backref` JSON**

In `jcl-bridge/src/main/java/org/jackal/jcl/JclSerializer.java`, find the DSN extraction block (around line 426) inside the `if (inner instanceof JCLParser.DdParmDSNAMEContext)` branch. It currently reads:

```java
if (inner instanceof JCLParser.DdParmDSNAMEContext) {
    JCLParser.DdParmDSNAMEContext dsnCtx = (JCLParser.DdParmDSNAMEContext) inner;
    JCLParser.DatasetNameContext datasetName =
            findChild(dsnCtx, JCLParser.DatasetNameContext.class);
    if (datasetName != null) {
        dsn = datasetName.getText();
    }
}
```

Replace it with:

```java
if (inner instanceof JCLParser.DdParmDSNAMEContext) {
    JCLParser.DdParmDSNAMEContext dsnCtx = (JCLParser.DdParmDSNAMEContext) inner;
    JCLParser.DatasetNameContext datasetName =
            findChild(dsnCtx, JCLParser.DatasetNameContext.class);
    if (datasetName != null) {
        String raw = datasetName.getText();
        if (raw.startsWith("*.")) {
            // backward reference: *.STEPNAME.DDNAME (two-segment) or longer
            String[] parts = raw.substring(2).split("\\.");
            if (parts.length == 2) {
                JsonObject backref = new JsonObject();
                backref.addProperty("step", parts[0]);
                backref.addProperty("ddname", parts[1]);
                dd.add("backref", backref);
                // leave dsn="" — Python parser dispatches on "backref" key first
            } else {
                // three-segment or malformed — pass raw string; Python raises ValueError
                dsn = raw;
            }
        } else {
            dsn = raw;
        }
    }
}
```

**Note:** If Step 3's failure showed that `dsn` was `""` (grammar didn't parse `*.STEP1.WRK` at all), replace `datasetName.getText()` with `dsnCtx.getText()` to get the raw context text, then strip the leading `DSN=` or `DSNAME=` prefix before the `startsWith("*.")` check. Adjust accordingly.

- [ ] **Step 5: Rebuild the JAR**

```bash
make jar-force
```

Expected: BUILD SUCCESS, new JAR at `jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar`.

- [ ] **Step 6: Update `_dd_from_json` in `jackal/jcl/bridge_parser.py`**

Replace the `_dd_from_json` function (lines 21–32) with:

```python
def _dd_from_json(d: dict) -> DD:
    words = tuple(d.get("disp_words", ()))
    disp = _disp_from_words(words) if words else _DEFAULT_DISP
    raw_dsn = d.get("dsn", "")
    if "backref" in d:
        br = d["backref"]
        dsn: DSN = BackwardRef(step=br["step"], ddname=br["ddname"])
    elif raw_dsn.startswith("*."):
        raise ValueError(
            f"Three-segment backward reference '{raw_dsn}' is not yet supported "
            "(see jackal-lz8 — requires PROC support from jackal-1o2.2)"
        )
    elif raw_dsn.startswith("&&"):
        dsn = TempRef(raw_dsn)
    else:
        dsn = DirectDSN(raw_dsn)
    return DD(
        ddname=d["ddname"],
        dsn=dsn,
        disp=disp,
        in_stream=tuple(d.get("in_stream", ())),
        sysout=d.get("sysout", False),
    )
```

Also update the import at the top of `bridge_parser.py`:

```python
from jackal.dsn import DSN, DirectDSN, TempRef, BackwardRef
```

- [ ] **Step 7: Run all affected tests**

```bash
uv run --no-sync pytest tests/unit/test_jcl_bridge_deserialize.py tests/integration/test_jcl_bridge_jar.py -v
```

Expected: all pass (existing + 3 new).

- [ ] **Step 8: Run the full suite to catch regressions**

```bash
uv run --no-sync pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add jcl-bridge/src/main/java/org/jackal/jcl/JclSerializer.java \
        jackal/jcl/bridge_parser.py \
        tests/unit/test_jcl_bridge_deserialize.py \
        tests/integration/test_jcl_bridge_jar.py
git commit -m "feat: Java bridge emits backref JSON; parser materialises BackwardRef (jackal-1o2.10)"
```

---

### Task 3: Runner resolution + integration tests

**Files:**
- Modify: `jackal/runner.py`
- Modify: `tests/unit/test_runner.py`
- Create: `tests/integration/test_backward_refs.py`

**Interfaces:**
- Consumes: `BackwardRef(step, ddname)` from Task 1; updated `bridge_parser` from Task 2
- Produces:
  - `JobRunner._resolve_step(step, resolved_dds) -> Step | None` — returns resolved step or `None` (bypass)
  - `JobRunner._record_dds(step_name, dds, resolved_dds) -> None` — populates registry
  - `run_job()` calls both before dispatching each step

- [ ] **Step 1: Write 3 failing unit tests in `tests/unit/test_runner.py`**

Append to the existing file. The runner unit tests build `Job`/`Step`/`DD` objects directly (no JAR). Import the needed types at the top of the append block:

```python
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_resolve_step_substitutes_backref(tmp_path: Path) -> None:
    from jackal.dsn import BackwardRef, DirectDSN
    from jackal.model import DD, Disp, DispNormal, DispStatus, Step

    runner = JobRunner(
        source_dir=tmp_path, bridge_jar="unused",
        data_dir=tmp_path, copybook_dir=tmp_path,
    )
    resolved_dds = {"STEP1": {"WRK": DirectDSN("MY.FILE")}}
    step = Step(
        name="STEP2", pgm="IEFBR14",
        dds=(DD("INPUT", BackwardRef("STEP1", "WRK"),
                Disp(DispStatus.OLD, DispNormal.DELETE, DispNormal.DELETE)),),
    )
    result = runner._resolve_step(step, resolved_dds)
    assert result is not None
    assert result.dds[0].dsn == DirectDSN("MY.FILE")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_resolve_step_returns_none_when_referenced_step_absent(tmp_path: Path) -> None:
    from jackal.dsn import BackwardRef
    from jackal.model import DD, Disp, DispNormal, DispStatus, Step

    runner = JobRunner(
        source_dir=tmp_path, bridge_jar="unused",
        data_dir=tmp_path, copybook_dir=tmp_path,
    )
    step = Step(
        name="STEP2", pgm="IEFBR14",
        dds=(DD("INPUT", BackwardRef("MISSING", "WRK"),
                Disp(DispStatus.OLD, DispNormal.DELETE, DispNormal.DELETE)),),
    )
    assert runner._resolve_step(step, resolved_dds={}) is None


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_record_dds_stores_temp_ref_as_direct_dsn(tmp_path: Path) -> None:
    from jackal.dsn import DirectDSN, TempRef
    from jackal.model import DD, Disp, DispNormal, DispStatus

    runner = JobRunner(
        source_dir=tmp_path, bridge_jar="unused",
        data_dir=tmp_path, copybook_dir=tmp_path,
    )
    dds = (
        DD("WRK", TempRef("&&TEMP"),
           Disp(DispStatus.NEW, DispNormal.PASS, DispNormal.DELETE)),
        DD("OUT", DirectDSN("MY.FILE"),
           Disp(DispStatus.NEW, DispNormal.KEEP, DispNormal.DELETE)),
    )
    registry: dict = {}
    runner._record_dds("STEP1", dds, registry)
    assert registry["STEP1"]["WRK"] == DirectDSN("TEMP")   # alias[2:]
    assert registry["STEP1"]["OUT"] == DirectDSN("MY.FILE")
```

- [ ] **Step 2: Run unit tests to confirm they fail**

```bash
uv run --no-sync pytest tests/unit/test_runner.py::test_resolve_step_substitutes_backref tests/unit/test_runner.py::test_resolve_step_returns_none_when_referenced_step_absent tests/unit/test_runner.py::test_record_dds_stores_temp_ref_as_direct_dsn -v
```

Expected: 3 failures — `AttributeError: 'JobRunner' object has no attribute '_resolve_step'`

- [ ] **Step 3: Write 2 failing integration tests in `tests/integration/test_backward_refs.py`**

Create the file:

```python
"""Integration tests: DSN=*.STEP.DD backward reference resolution via JobRunner."""

from __future__ import annotations

from jackal.dsn import DirectDSN, TempRef
from jackal.model import DD, Disp, DispNormal, DispStatus, Job, Step
from jackal.results import StepDisposition
from jackal.runner import JobRunner
from tests.covers import NotLanguageFeature, covers


def _runner(tmp_path):
    return JobRunner(
        source_dir=tmp_path,
        bridge_jar="unused",
        data_dir=tmp_path,
        copybook_dir=tmp_path,
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_backward_ref_resolves_to_prior_step_dataset(tmp_path):
    """Step 2 DD with BackwardRef to step 1's WRK resolves to the same DirectDSN."""
    from jackal.dsn import BackwardRef

    job = Job(
        name="J",
        steps=(
            Step(
                name="STEP1",
                pgm="IEFBR14",
                dds=(
                    DD(
                        "WRK",
                        DirectDSN("MY.FILE"),
                        Disp(DispStatus.NEW, DispNormal.PASS, DispNormal.DELETE),
                    ),
                ),
            ),
            Step(
                name="STEP2",
                pgm="IEFBR14",
                dds=(
                    DD(
                        "INPUT",
                        BackwardRef("STEP1", "WRK"),
                        Disp(DispStatus.OLD, DispNormal.DELETE, DispNormal.DELETE),
                    ),
                ),
            ),
        ),
    )
    (tmp_path / "myfile").write_bytes(b"")
    result = _runner(tmp_path).run(job, workdir=tmp_path, seeds={"MY.FILE": tmp_path / "myfile"})
    assert all(s.ran and s.return_code == 0 for s in result.steps)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_backward_ref_to_bypassed_step_also_bypasses(tmp_path):
    """If step 1 is bypassed, step 2 referencing *.STEP1.WRK is also bypassed."""
    from jackal.dsn import BackwardRef
    from jackal.model import Cond, CondOp

    job = Job(
        name="J",
        steps=(
            Step(
                name="STEP1",
                pgm="IEFBR14",
                dds=(
                    DD(
                        "WRK",
                        DirectDSN("MY.FILE"),
                        Disp(DispStatus.NEW, DispNormal.PASS, DispNormal.DELETE),
                    ),
                ),
                conds=(Cond(code=0, op=CondOp.GE),),  # always true → STEP1 bypassed
            ),
            Step(
                name="STEP2",
                pgm="IEFBR14",
                dds=(
                    DD(
                        "INPUT",
                        BackwardRef("STEP1", "WRK"),
                        Disp(DispStatus.OLD, DispNormal.DELETE, DispNormal.DELETE),
                    ),
                ),
            ),
        ),
    )
    result = _runner(tmp_path).run(job, workdir=tmp_path, seeds={})
    step1, step2 = result.steps
    assert step1.disposition is StepDisposition.BYPASSED
    assert step2.disposition is StepDisposition.BYPASSED
    assert step2.ran is False
```

- [ ] **Step 4: Run integration tests to confirm they fail**

```bash
uv run --no-sync pytest tests/integration/test_backward_refs.py -v
```

Expected: 2 failures — `AttributeError` or wrong step dispositions.

- [ ] **Step 5: Implement `_resolve_step`, `_record_dds`, and update `run_job()` in `jackal/runner.py`**

Replace the entire file with:

```python
"""Sequence a Job's steps, threading a job-scoped DatasetCatalog."""

from __future__ import annotations

from pathlib import Path

from jackal.catalog import DatasetCatalog
from jackal.cobol_step import run_cobol_step
from jackal.cond import should_bypass
from jackal.dsn import BackwardRef, DirectDSN, TempRef
from jackal.model import DD, Job, Step
from jackal.results import JobResult, StepDisposition, StepResult
from jackal.utilities import UTILITIES


class JobRunner:
    def __init__(
        self,
        source_dir: Path,
        bridge_jar: str,
        data_dir: Path,
        copybook_dir: Path,
    ):
        self._source_dir = source_dir
        self._bridge_jar = bridge_jar
        self._data_dir = data_dir
        self._copybook_dir = copybook_dir

    def run(self, job: Job, workdir: Path, seeds: dict[str, Path]) -> JobResult:
        catalog = DatasetCatalog(workdir=workdir, data_dir=self._data_dir)
        for dsn, path in seeds.items():
            catalog.seed(dsn, path)
        return self.run_job(job, catalog)

    def run_job(self, job: Job, catalog: DatasetCatalog) -> JobResult:
        """Run a job against a pre-built catalog, honoring COND= and backward refs."""
        executed: list[StepResult] = []
        results: list[StepResult] = []
        resolved_dds: dict[str, dict[str, DirectDSN]] = {}
        try:
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
                resolved_step = self._resolve_step(step, resolved_dds)
                if resolved_step is None:
                    results.append(
                        StepResult(
                            name=step.name,
                            return_code=0,
                            ran=False,
                            disposition=StepDisposition.BYPASSED,
                        )
                    )
                    continue
                self._record_dds(step.name, resolved_step.dds, resolved_dds)
                result = self._run_step(resolved_step, catalog)
                executed.append(result)
                results.append(result)
        finally:
            catalog.cleanup_temps()
        return JobResult(steps=tuple(results))

    def _resolve_step(
        self,
        step: Step,
        resolved_dds: dict[str, dict[str, DirectDSN]],
    ) -> Step | None:
        """Substitute BackwardRefs with their resolved DirectDSN.

        Returns None if any referenced step is absent from resolved_dds
        (IBM behavior: bypass the referencing step when its predecessor didn't run).
        """
        new_dds: list[DD] = []
        for dd in step.dds:
            match dd.dsn:
                case BackwardRef(step=s, ddname=dn):
                    if s not in resolved_dds:
                        return None
                    new_dds.append(
                        DD(dd.ddname, resolved_dds[s][dn], dd.disp,
                           dd.in_stream, dd.sysout)
                    )
                case _:
                    new_dds.append(dd)
        return Step(step.name, step.pgm, tuple(new_dds), step.conds, step.parm)

    def _record_dds(
        self,
        step_name: str,
        dds: tuple[DD, ...],
        resolved_dds: dict[str, dict[str, DirectDSN]],
    ) -> None:
        """Record each DD's resolved DirectDSN into the registry for future backward refs."""
        entry: dict[str, DirectDSN] = {}
        for dd in dds:
            match dd.dsn:
                case DirectDSN() as d:
                    entry[dd.ddname] = d
                case TempRef(alias=a):
                    entry[dd.ddname] = DirectDSN(a[2:])  # strip leading &&
        resolved_dds[step_name] = entry

    def _run_step(self, step: Step, catalog: DatasetCatalog) -> StepResult:
        if step.pgm in UTILITIES:
            return UTILITIES[step.pgm](step, catalog)
        source = (self._source_dir / f"{step.pgm}.cbl").read_text()
        return run_cobol_step(
            step,
            source,
            catalog,
            self._bridge_jar,
            [self._copybook_dir],
        )
```

- [ ] **Step 6: Run all new tests**

```bash
uv run --no-sync pytest tests/unit/test_runner.py tests/integration/test_backward_refs.py -v
```

Expected: all 3 unit + 2 integration tests pass.

- [ ] **Step 7: Run the full suite**

```bash
uv run --no-sync pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add jackal/runner.py tests/unit/test_runner.py tests/integration/test_backward_refs.py
git commit -m "feat: runner resolves BackwardRef DDs; bypass propagation (jackal-1o2.10)"
```

If Talisman blocks (JCL keywords in the integration test), add a checksum entry in `.talismanrc` before `version: "1.0"` and re-run the commit.
