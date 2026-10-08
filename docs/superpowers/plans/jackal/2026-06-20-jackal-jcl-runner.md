# jackal JCL Runner (v1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a multi-step batch job described in JCL — parse the JCL, sequence its steps, resolve each step's DD statements to datasets, run each `EXEC PGM` step (COBOL via red-dragon, plus `IEFBR14`), and verify every step ran and intermediate datasets carried transformed data between steps.

**Architecture:** New repo `jackal` (at `~/code/jackal`), red-dragon vendored as a `vendor/red-dragon` git submodule. In-process Python orchestrator: `parse_jcl(text) → Job`; `JobRunner.run(job)` sequences steps, threading a job-scoped `DatasetCatalog` (DSN → backing file) that carries data step→step; each step runs a utility emulator or a COBOL load module via red-dragon `run()` with a `RealFileIOProvider` whose overrides are keyed by **DDname**.

**Tech Stack:** Python 3.13+, uv, pytest, Black, Lark (grammar), red-dragon (vendored, editable).

## Global Constraints

- **No regex. Anywhere.** No `import re`. All parsing/resolution/decisions are grammar-based (Lark). JCL card format, continuations, DISP parsing live in the grammar.
- **TDD** — failing test first for every unit; run it red before implementing.
- **FP principles** — functional core / imperative shell; `frozen=True` dataclasses; comprehensions/`map`/`filter` over mutating loops.
- **No defensive programming** — no `None` checks, no `None` defaults, no generic exception swallowing; null-object pattern over `None` returns.
- **Small, composable functions** — one responsibility each; no massive functions.
- **No external-codebase references in tracked artifacts** — no real dataset names, vendor names, or domains in committed code/tests. v1 uses synthetic anonymized COBOL + JCL.
- **Tooling:** Python 3.13+, `uv` (`uv run pytest`, `uv run black .`), Black, Beads (`bd`).
- **Commits:** real hooks; never `git add -A` (stage named files); end commit messages with the `Co-Authored-By` trailer.
- **COBOL frontend needs** `PROLEAP_BRIDGE_JAR` exported (built in `vendor/red-dragon/proleap-bridge`).

---

## File Structure

```
jackal/
  pyproject.toml                       # uv project; deps: lark, red-dragon (editable path)
  jackal/
    __init__.py
    model.py                           # Job, Step, DD, Disp, DispStatus, DispNormal
    jcl/
      __init__.py
      grammar.lark                     # JCL grammar (JOB/EXEC/DD/DISP, card format, continuation)
      parser.py                        # parse_jcl(text: str) -> Job  (Lark + Transformer)
    catalog.py                         # Dataset, DatasetCatalog
    cobol_step.py                      # run_cobol_step(...) -> StepResult  (red-dragon bridge)
    utilities.py                       # UTILITIES registry; iefbr14 handler
    results.py                         # StepResult, JobResult
    runner.py                          # JobRunner.run(job) -> JobResult
    cli.py                             # `jackal run <job.jcl> --source-dir DIR [--dataset DSN=PATH]`
  tests/
    conftest.py                        # bridge-jar guard fixture
    unit/
      test_model.py
      test_jcl_parser.py
      test_catalog.py
      test_utilities.py
      test_runner.py
    integration/
      test_pipeline.py                 # headline: synthetic multi-step pipeline
      fixtures/
        cbl/UPCASE.cbl
        cbl/STARRER.cbl
        pipeline.jcl
  vendor/red-dragon/                   # git submodule
```

---

### Task 0: Repo skeleton, uv project, red-dragon submodule

**Files:**
- Create: `pyproject.toml`, `jackal/__init__.py`, `tests/conftest.py`, `tests/unit/test_smoke.py`
- Submodule: `vendor/red-dragon`

**Interfaces:**
- Produces: an importable `jackal` package; `import interpreter.run` (from vendored red-dragon) works under `uv run`.

- [ ] **Step 1: Add the red-dragon submodule**

```bash
cd ~/code/jackal
git submodule add git@github.com:avishek-sen-gupta/red-dragon.git vendor/red-dragon
git -C vendor/red-dragon submodule update --init --recursive
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "jackal"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = ["lark>=1.1", "red-dragon"]

[tool.uv.sources]
red-dragon = { path = "vendor/red-dragon", editable = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["jackal"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 3: Create the package + smoke test**

`jackal/__init__.py`:
```python
"""jackal — JCL execution/orchestration layer over the red-dragon VM."""
```

`tests/conftest.py`:
```python
import os

import pytest


@pytest.fixture
def bridge_jar() -> str:
    """The ProLeap bridge JAR path; fail loudly if unset (COBOL steps need it)."""
    jar = os.environ["PROLEAP_BRIDGE_JAR"]
    assert jar, "PROLEAP_BRIDGE_JAR must point at the built bridge JAR"
    return jar
```

`tests/unit/test_smoke.py`:
```python
def test_red_dragon_importable():
    import interpreter.run  # vendored red-dragon

    assert hasattr(interpreter.run, "run")
```

- [ ] **Step 4: Sync + run**

```bash
cd ~/code/jackal && uv sync
uv run pytest tests/unit/test_smoke.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml jackal/__init__.py tests/conftest.py tests/unit/test_smoke.py .gitmodules vendor/red-dragon uv.lock
git commit -m "chore: jackal package skeleton + red-dragon submodule (Task 0)"
```

---

### Task 1: red-dragon — resolve file overrides by ASSIGN name (DDname) [red-dragon-3mmk]

**Worked in the red-dragon repo** (`~/code/jackal/vendor/red-dragon`), committed + pushed there, then the submodule is bumped. This lets jackal key `path_overrides` by JCL DDname.

**Files:**
- Modify: `interpreter/cobol/real_file_provider.py` (`_resolve_path`, ~line 49)
- Test: `interpreter/cobol/` integration test (add to the existing real-file provider test module)

**Interfaces:**
- Produces: `RealFileIOProvider(path_overrides={<ASSIGN-name>: Path})` resolves a file whose `SELECT s ASSIGN TO <ASSIGN-name>` (with `s != <ASSIGN-name>`) to that path, provided `file_control` carrying the SELECT→assign mapping is passed to the provider.

- [ ] **Step 1: Write the failing test** (red-dragon test suite). A program with `SELECT IN-FILE ASSIGN TO INDD` (names differ), provider overrides keyed by `INDD`:

```python
def test_override_resolves_by_assign_name(tmp_path, bridge_jar):
    data = tmp_path / "in.dat"
    data.write_bytes(b"HELLO")
    from interpreter.cobol.cobol_statements import FileControlEntry
    from interpreter.cobol.real_file_provider import RealFileIOProvider
    prov = RealFileIOProvider(
        base_dir=tmp_path,
        file_control=[FileControlEntry(file_name="IN-FILE", assign_to="INDD")],
        path_overrides={"INDD": data},
    )
    # _open_file looks up assign_to via file_control, then _resolve_path must
    # match the override keyed by the ASSIGN name.
    res = prov._open_file("IN-FILE", "INPUT", 5, "SEQUENTIAL", 0, 0)
    assert res.status == "00"
```

- [ ] **Step 2: Run → fail**

```bash
cd ~/code/jackal/vendor/red-dragon
export PROLEAP_BRIDGE_JAR="$(pwd)/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar"
poetry run python -m pytest <new-test> -v
```
Expected: FAIL — `_resolve_path` only checks the SELECT name; override keyed by `INDD` is not found, OPEN returns `35` (not found).

- [ ] **Step 3: Implement** — `_resolve_path` resolves overrides by ASSIGN name too:

```python
    def _resolve_path(self, file_name: str, assign_to: str) -> Path:
        if file_name in self._overrides:
            return self._overrides[file_name]
        if assign_to and assign_to in self._overrides:  # red-dragon-3mmk: DDname binding
            return self._overrides[assign_to]
        if assign_to:
            clean = assign_to.strip("'\"")
            if "/" not in clean and "\\" not in clean and "." not in clean:
                env_val = os.environ.get(clean.upper())
                if env_val:
                    return Path(env_val)
            return self._base_dir / clean
        return self._base_dir / (file_name.lower().replace("-", "_") + ".dat")
```

- [ ] **Step 4: Run → pass.** Same command. Then the COBOL file-IO regression sweep:
```bash
poetry run python -m pytest tests/integration/test_cobol_use_declaratives.py tests/integration/test_cobol_read_at_end.py -q
```
Expected: all pass (change is additive; SELECT-name resolution unchanged).

- [ ] **Step 5: Commit + push red-dragon, bump jackal submodule**

```bash
cd ~/code/jackal/vendor/red-dragon
export PROLEAP_BRIDGE_JAR="$(pwd)/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar"
poetry run python -m black interpreter/cobol/real_file_provider.py <test-file>
git add interpreter/cobol/real_file_provider.py <test-file>
git commit -m "feat(cobol): resolve file overrides by ASSIGN name/DDname (red-dragon-3mmk)"
git push origin main
cd ~/code/jackal
git add vendor/red-dragon
git commit -m "chore: bump red-dragon (ASSIGN-name override resolution, red-dragon-3mmk) (Task 1)"
```

---

### Task 2: Model dataclasses

**Files:**
- Create: `jackal/model.py`
- Test: `tests/unit/test_model.py`

**Interfaces:**
- Produces: `DispStatus(NEW|OLD|SHR|MOD)`, `DispNormal(PASS|CATLG|KEEP|DELETE)` enums; `Disp(status, normal, abnormal)`, `DD(ddname, dsn, disp)`, `Step(name, pgm, dds)`, `Job(name, steps)` — all `frozen=True`.

- [ ] **Step 1: Write the failing test**

```python
from jackal.model import DD, Disp, DispNormal, DispStatus, Job, Step


def test_job_model_construction():
    dd = DD(ddname="INDD", dsn="J.IN", disp=Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP))
    step = Step(name="STEP1", pgm="UPCASE", dds=(dd,))
    job = Job(name="PIPE", steps=(step,))
    assert job.steps[0].dds[0].ddname == "INDD"
    assert job.steps[0].dds[0].disp.status is DispStatus.SHR
```

- [ ] **Step 2: Run → fail** `uv run pytest tests/unit/test_model.py -v` (ImportError).

- [ ] **Step 3: Implement** `jackal/model.py`:

```python
"""Immutable JCL job model."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DispStatus(Enum):
    NEW = "NEW"
    OLD = "OLD"
    SHR = "SHR"
    MOD = "MOD"


class DispNormal(Enum):
    PASS = "PASS"
    CATLG = "CATLG"
    KEEP = "KEEP"
    DELETE = "DELETE"


@dataclass(frozen=True)
class Disp:
    status: DispStatus
    normal: DispNormal
    abnormal: DispNormal


@dataclass(frozen=True)
class DD:
    ddname: str
    dsn: str
    disp: Disp


@dataclass(frozen=True)
class Step:
    name: str
    pgm: str
    dds: tuple[DD, ...]


@dataclass(frozen=True)
class Job:
    name: str
    steps: tuple[Step, ...]
```

- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit** `git add jackal/model.py tests/unit/test_model.py && git commit -m "feat: JCL job model dataclasses (Task 2)"`

---

### Task 3: JCL grammar + parser

**Files:**
- Create: `jackal/jcl/__init__.py`, `jackal/jcl/grammar.lark`, `jackal/jcl/parser.py`
- Test: `tests/unit/test_jcl_parser.py`

**Interfaces:**
- Consumes: `jackal.model`.
- Produces: `parse_jcl(text: str) -> Job`.

**JCL shape handled (v1):** lines begin `//`; `//NAME JOB ...`; `//STEP EXEC PGM=NAME`; `//DDN DD DSN=name,DISP=(status,normal[,abnormal])` and `//DDN DD DSN=name,DISP=SHR`. A line ending in `,` continues on the next `//` card. Comments (`//*`) and the `// ` continuation are recognized and ignored where irrelevant.

- [ ] **Step 1: Write the failing tests**

```python
from jackal.jcl.parser import parse_jcl
from jackal.model import DispNormal, DispStatus

JCL = """//PIPE JOB 'demo'
//STEP1 EXEC PGM=UPCASE
//INDD DD DSN=J.IN,DISP=SHR
//WORKDD DD DSN=J.WORK,DISP=(NEW,PASS,DELETE)
//STEP2 EXEC PGM=STARRER
//WORKDD DD DSN=J.WORK,DISP=SHR
//OUTDD DD DSN=J.OUT,DISP=(NEW,CATLG,DELETE)
"""


def test_parse_job_steps_and_dds():
    job = parse_jcl(JCL)
    assert job.name == "PIPE"
    assert [s.name for s in job.steps] == ["STEP1", "STEP2"]
    assert [s.pgm for s in job.steps] == ["UPCASE", "STARRER"]
    s1 = job.steps[0]
    assert [d.ddname for d in s1.dds] == ["INDD", "WORKDD"]
    assert s1.dds[1].disp.status is DispStatus.NEW
    assert s1.dds[1].disp.normal is DispNormal.PASS
    assert s1.dds[1].disp.abnormal is DispNormal.DELETE


def test_disp_shr_shorthand_defaults_keep():
    job = parse_jcl(JCL)
    indd = job.steps[0].dds[0]
    assert indd.disp.status is DispStatus.SHR
    assert indd.disp.normal is DispNormal.KEEP
    assert indd.disp.abnormal is DispNormal.KEEP


def test_dd_continuation_line():
    jcl = "//J JOB 1\n//S EXEC PGM=P\n//D DD DSN=A.B,\n//   DISP=(NEW,CATLG,DELETE)\n"
    dd = parse_jcl(jcl).steps[0].dds[0]
    assert dd.dsn == "A.B" and dd.disp.status is DispStatus.NEW
```

- [ ] **Step 2: Run → fail** `uv run pytest tests/unit/test_jcl_parser.py -v` (ImportError).

- [ ] **Step 3: Implement the grammar** `jackal/jcl/grammar.lark`:

```lark
start: statement+

statement: job_card | exec_card | dd_card | comment

job_card:  "//" NAME "JOB" REST NEWLINE
exec_card: "//" NAME "EXEC" "PGM" "=" NAME _rest_params? NEWLINE
dd_card:   "//" NAME "DD" dd_params NEWLINE
comment:   COMMENT NEWLINE

dd_params: dd_param ("," _cont? dd_param)*
dd_param:  dsn_param | disp_param
dsn_param: "DSN" "=" DSNAME
disp_param: "DISP" "=" ( DISPWORD | "(" DISPWORD ("," DISPWORD)* ")" )

// a parameter list may continue onto the next // card when a card ends in ','
_cont: NEWLINE "//" /[ ]+/

NAME:    /[A-Z#@$][A-Z0-9#@$]*/
DSNAME:  /[A-Z0-9#@$.]+/
DISPWORD: "NEW" | "OLD" | "SHR" | "MOD" | "PASS" | "CATLG" | "KEEP" | "DELETE"
REST:    /[^\n]*/
COMMENT: /\/\/\*[^\n]*/
NEWLINE: /\r?\n/

%ignore /[ \t]+/
```
(If a production needs refinement during TDD — e.g. the continuation rule — adjust the grammar, never add a regex prepass. Card-format and continuation handling stay in the grammar.)

- [ ] **Step 4: Implement the transformer** `jackal/jcl/parser.py`:

```python
"""Grammar-based JCL parser: text -> Job."""
from __future__ import annotations

from importlib.resources import files

from lark import Lark, Transformer

from jackal.model import DD, Disp, DispNormal, DispStatus, Job, Step

_GRAMMAR = (files("jackal.jcl") / "grammar.lark").read_text()
_PARSER = Lark(_GRAMMAR, start="start", parser="lalr")

_DEFAULT_DISP = Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP)


def _disp_from_words(words: tuple[str, ...]) -> Disp:
    status = DispStatus(words[0])
    normal = DispNormal(words[1]) if len(words) > 1 else DispNormal.KEEP
    abnormal = DispNormal(words[2]) if len(words) > 2 else normal
    return Disp(status, normal, abnormal)


class _Build(Transformer):
    def NAME(self, t):
        return str(t)

    def DSNAME(self, t):
        return str(t)

    def DISPWORD(self, t):
        return str(t)

    def dsn_param(self, c):
        return ("dsn", c[0])

    def disp_param(self, c):
        return ("disp", _disp_from_words(tuple(c)))

    def dd_params(self, c):
        return dict(c)

    def dd_card(self, c):
        name, params = c[0], c[1]
        return ("dd", DD(ddname=name, dsn=params["dsn"], disp=params.get("disp", _DEFAULT_DISP)))

    def exec_card(self, c):
        return ("exec", c[0], c[1])

    def job_card(self, c):
        return ("job", c[0])

    def comment(self, c):
        return ("comment",)
```

Then a small assembler (functional, folds the flat statement tuples into the `Job`):

```python
def parse_jcl(text: str) -> Job:
    tree = _PARSER.parse(text if text.endswith("\n") else text + "\n")
    rows = _Build().transform(tree).children
    return _assemble(tuple(r for r in rows if r[0] != "comment"))


def _assemble(rows: tuple) -> Job:
    job_name = next(r[1] for r in rows if r[0] == "job")
    steps = _fold_steps(tuple(r for r in rows if r[0] in ("exec", "dd")))
    return Job(name=job_name, steps=steps)


def _fold_steps(rows: tuple) -> tuple[Step, ...]:
    # group each exec with the dd rows that follow it, functionally
    starts = [i for i, r in enumerate(rows) if r[0] == "exec"]
    bounds = list(zip(starts, starts[1:] + [len(rows)]))
    return tuple(
        Step(
            name=rows[s][1],
            pgm=rows[s][2],
            dds=tuple(r[1] for r in rows[s + 1 : e] if r[0] == "dd"),
        )
        for s, e in bounds
    )
```

- [ ] **Step 5: Run → pass** all three tests. Adjust the grammar (not regex) until green.
- [ ] **Step 6: Commit** `git add jackal/jcl tests/unit/test_jcl_parser.py && git commit -m "feat: grammar-based JCL parser (Task 3)"`

---

### Task 4: DatasetCatalog

**Files:**
- Create: `jackal/catalog.py`
- Test: `tests/unit/test_catalog.py`

**Interfaces:**
- Consumes: `jackal.model.DD`, `DispStatus`, `DispNormal`.
- Produces: `Dataset(dsn: str, path: Path)`; `DatasetCatalog(workdir: Path)` with `seed(dsn, path)`, `allocate(dd) -> Dataset`, `dispose(dd) -> None`, `resolve(dsn) -> Dataset`.

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path

import pytest

from jackal.catalog import DatasetCatalog
from jackal.model import DD, Disp, DispNormal, DispStatus


def _dd(dsn, status, normal=DispNormal.KEEP):
    return DD(ddname="D", dsn=dsn, disp=Disp(status, normal, DispNormal.DELETE))


def test_new_allocates_empty_file(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path)
    ds = cat.allocate(_dd("J.WORK", DispStatus.NEW))
    assert ds.path.exists() and ds.path.read_bytes() == b""


def test_seed_then_shr_resolves_same_file(tmp_path):
    src = tmp_path / "seed.dat"
    src.write_bytes(b"DATA")
    cat = DatasetCatalog(workdir=tmp_path)
    cat.seed("J.IN", src)
    ds = cat.allocate(_dd("J.IN", DispStatus.SHR))
    assert ds.path == src


def test_pass_retains_delete_removes(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path)
    keep = cat.allocate(_dd("J.A", DispStatus.NEW, DispNormal.PASS))
    cat.dispose(_dd("J.A", DispStatus.NEW, DispNormal.PASS))
    assert keep.path.exists()
    drop = cat.allocate(_dd("J.B", DispStatus.NEW, DispNormal.DELETE))
    cat.dispose(_dd("J.B", DispStatus.NEW, DispNormal.DELETE))
    assert not drop.path.exists()


def test_shr_on_unknown_dsn_raises(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path)
    with pytest.raises(KeyError):
        cat.allocate(_dd("J.MISSING", DispStatus.SHR))
```

- [ ] **Step 2: Run → fail** `uv run pytest tests/unit/test_catalog.py -v`.

- [ ] **Step 3: Implement** `jackal/catalog.py`:

```python
"""Job-scoped dataset catalog: DSN -> backing file, with DISP lifecycle."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jackal.model import DD, DispNormal, DispStatus


@dataclass(frozen=True)
class Dataset:
    dsn: str
    path: Path


class DatasetCatalog:
    """Imperative shell: owns the job workdir and the DSN->file mapping."""

    def __init__(self, workdir: Path):
        self._workdir = workdir
        self._datasets: dict[str, Dataset] = {}

    def seed(self, dsn: str, path: Path) -> None:
        self._datasets[dsn] = Dataset(dsn=dsn, path=path)

    def resolve(self, dsn: str) -> Dataset:
        return self._datasets[dsn]

    def allocate(self, dd: DD) -> Dataset:
        if dd.disp.status in (DispStatus.OLD, DispStatus.SHR, DispStatus.MOD):
            return self._datasets[dd.dsn]
        path = self._workdir / dd.dsn.replace(".", "_")
        path.write_bytes(b"")
        ds = Dataset(dsn=dd.dsn, path=path)
        self._datasets[dd.dsn] = ds
        return ds

    def dispose(self, dd: DD) -> None:
        if dd.disp.normal is DispNormal.DELETE:
            self._datasets[dd.dsn].path.unlink()
            del self._datasets[dd.dsn]
```

- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit** `git add jackal/catalog.py tests/unit/test_catalog.py && git commit -m "feat: dataset catalog with DISP lifecycle (Task 4)"`

---

### Task 5: COBOL step bridge to red-dragon

**Files:**
- Create: `jackal/results.py`, `jackal/cobol_step.py`
- Test: `tests/integration/test_cobol_step.py`, fixture `tests/integration/fixtures/cbl/COPYUP.cbl`

**Interfaces:**
- Consumes: `jackal.model.Step`, `jackal.catalog.DatasetCatalog`, red-dragon `interpreter.run.run`, `interpreter.cobol.real_file_provider.RealFileIOProvider`, `interpreter.cobol.cobol_parser.ProLeapCobolParser`, `interpreter.cobol.subprocess_runner.RealSubprocessRunner`.
- Produces: `StepResult(name: str, return_code: int, ran: bool)` (in `results.py`); `run_cobol_step(step: Step, source: str, catalog: DatasetCatalog, bridge_jar: str) -> StepResult`.

**Mechanism:** jackal parses the program's source to get `file_control` (the SELECT→ASSIGN map), resolves each `DD` against the catalog, builds `RealFileIOProvider(base_dir, file_control, path_overrides={ddname: dataset.path})`, and runs via red-dragon `run()`. Because of Task 1, the provider resolves each SELECT file to its ASSIGN name (= DDname) and finds the override.

- [ ] **Step 1: Write `results.py`** (no test of its own; exercised below):

```python
"""Execution results."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StepResult:
    name: str
    return_code: int
    ran: bool


@dataclass(frozen=True)
class JobResult:
    steps: tuple[StepResult, ...]
```

- [ ] **Step 2: Write the failing integration test** + fixture.

`tests/integration/fixtures/cbl/COPYUP.cbl` (SELECT names differ from DDnames — exercises Task 1; reads 5-byte records, uppercases, writes; no status checks → no CLOSE abend):

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COPYUP.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE  ASSIGN TO INDD
                  ORGANIZATION IS SEQUENTIAL.
           SELECT OUT-FILE ASSIGN TO OUTDD
                  ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC   PIC X(5).
       FD  OUT-FILE.
       01  OUT-REC  PIC X(5).
       WORKING-STORAGE SECTION.
       01  EOF-FLAG PIC X VALUE 'N'.
       PROCEDURE DIVISION.
           OPEN INPUT IN-FILE.
           OPEN OUTPUT OUT-FILE.
           PERFORM UNTIL EOF-FLAG = 'Y'
               READ IN-FILE
                   AT END MOVE 'Y' TO EOF-FLAG
                   NOT AT END
                       MOVE FUNCTION UPPER-CASE(IN-REC) TO OUT-REC
                       WRITE OUT-REC
               END-READ
           END-PERFORM.
           CLOSE IN-FILE.
           CLOSE OUT-FILE.
           GOBACK.
```

`tests/integration/test_cobol_step.py`:

```python
from pathlib import Path

import pytest

from jackal.catalog import DatasetCatalog
from jackal.cobol_step import run_cobol_step
from jackal.model import DD, Disp, DispNormal, DispStatus, Step

CBL = Path(__file__).parent / "fixtures" / "cbl"


@pytest.fixture(autouse=True)
def _require_bridge(bridge_jar):
    """Enforce PROLEAP_BRIDGE_JAR."""


def _dd(ddname, dsn, status, normal=DispNormal.KEEP):
    return DD(ddname=ddname, dsn=dsn, disp=Disp(status, normal, DispNormal.DELETE))


def test_cobol_step_reads_transforms_writes(tmp_path, bridge_jar):
    src = (tmp_path / "in.dat")
    src.write_bytes(b"applemango")  # two 5-byte records
    cat = DatasetCatalog(workdir=tmp_path)
    cat.seed("J.IN", src)
    step = Step(
        name="S1", pgm="COPYUP",
        dds=(_dd("INDD", "J.IN", DispStatus.SHR),
             _dd("OUTDD", "J.OUT", DispStatus.NEW, DispNormal.PASS)),
    )
    result = run_cobol_step(step, (CBL / "COPYUP.cbl").read_text(), cat, bridge_jar)
    assert result.ran and result.return_code == 0
    assert cat.resolve("J.OUT").path.read_bytes() == b"APPLEMANGO"
```

- [ ] **Step 3: Run → fail** `uv run pytest tests/integration/test_cobol_step.py -v` (ImportError on `run_cobol_step`).

- [ ] **Step 4: Implement** `jackal/cobol_step.py`:

```python
"""Run an EXEC PGM COBOL step against the red-dragon VM."""
from __future__ import annotations

from pathlib import Path

from interpreter.cobol.cobol_parser import ProLeapCobolParser
from interpreter.cobol.real_file_provider import RealFileIOProvider
from interpreter.cobol.subprocess_runner import RealSubprocessRunner
from interpreter.constants import Language
from interpreter.run import run

from jackal.catalog import DatasetCatalog
from jackal.model import Step
from jackal.results import StepResult


def _file_control(source: str, bridge_jar: str) -> list:
    parser = ProLeapCobolParser(runner=RealSubprocessRunner(), bridge_jar=bridge_jar)
    return parser.parse(source.encode("utf-8")).file_control


def _overrides(step: Step, catalog: DatasetCatalog) -> dict[str, Path]:
    return {dd.ddname: catalog.allocate(dd).path for dd in step.dds}


def run_cobol_step(step: Step, source: str, catalog: DatasetCatalog, bridge_jar: str) -> StepResult:
    overrides = _overrides(step, catalog)
    provider = RealFileIOProvider(
        base_dir=catalog_workdir(catalog),
        file_control=_file_control(source, bridge_jar),
        path_overrides=overrides,
    )
    run(source, language=Language.COBOL, io_provider=provider, max_steps=500_000)
    for dd in step.dds:
        catalog.dispose(dd)
    return StepResult(name=step.name, return_code=0, ran=True)


def catalog_workdir(catalog: DatasetCatalog) -> Path:
    return catalog._workdir
```
(If `catalog._workdir` access reads awkwardly, add a `workdir` property to `DatasetCatalog` in Task 4's file and use it here — prefer that over reaching into a private attr.)

- [ ] **Step 5: Run → pass.**
- [ ] **Step 6: Commit** `git add jackal/results.py jackal/cobol_step.py tests/integration/test_cobol_step.py tests/integration/fixtures/cbl/COPYUP.cbl && git commit -m "feat: COBOL step bridge to red-dragon (Task 5)"`

---

### Task 6: IEFBR14 utility + registry

**Files:**
- Create: `jackal/utilities.py`
- Test: `tests/unit/test_utilities.py`

**Interfaces:**
- Consumes: `jackal.model.Step`, `jackal.catalog.DatasetCatalog`, `jackal.results.StepResult`.
- Produces: `UTILITIES: dict[str, Callable[[Step, DatasetCatalog], StepResult]]`; `iefbr14(step, catalog) -> StepResult` (allocates + disposes the step's DDs — its sole real effect — and returns RC 0).

- [ ] **Step 1: Write the failing test**

```python
from jackal.catalog import DatasetCatalog
from jackal.model import DD, Disp, DispNormal, DispStatus, Step
from jackal.utilities import UTILITIES


def test_iefbr14_allocates_then_deletes(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path)
    dd = DD(ddname="D", dsn="J.TMP",
            disp=Disp(DispStatus.NEW, DispNormal.DELETE, DispNormal.DELETE))
    step = Step(name="DEL", pgm="IEFBR14", dds=(dd,))
    result = UTILITIES["IEFBR14"](step, cat)
    assert result.ran and result.return_code == 0
    assert not (tmp_path / "J_TMP").exists()  # NEW then DELETE -> gone
```

- [ ] **Step 2: Run → fail** `uv run pytest tests/unit/test_utilities.py -v`.

- [ ] **Step 3: Implement** `jackal/utilities.py`:

```python
"""Emulated utility programs (no COBOL load module)."""
from __future__ import annotations

from collections.abc import Callable

from jackal.catalog import DatasetCatalog
from jackal.model import Step
from jackal.results import StepResult


def iefbr14(step: Step, catalog: DatasetCatalog) -> StepResult:
    """No-op program: its only effect is the DD allocate/dispose lifecycle."""
    for dd in step.dds:
        catalog.allocate(dd)
    for dd in step.dds:
        catalog.dispose(dd)
    return StepResult(name=step.name, return_code=0, ran=True)


UTILITIES: dict[str, Callable[[Step, DatasetCatalog], StepResult]] = {
    "IEFBR14": iefbr14,
}
```

- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit** `git add jackal/utilities.py tests/unit/test_utilities.py && git commit -m "feat: IEFBR14 utility + registry (Task 6)"`

---

### Task 7: JobRunner

**Files:**
- Create: `jackal/runner.py`
- Test: `tests/unit/test_runner.py`

**Interfaces:**
- Consumes: `jackal.model.Job/Step`, `jackal.catalog.DatasetCatalog`, `jackal.utilities.UTILITIES`, `jackal.cobol_step.run_cobol_step`, `jackal.results.StepResult/JobResult`.
- Produces: `JobRunner(source_dir: Path, bridge_jar: str)` with `run(job, workdir, seeds) -> JobResult`, where `seeds: dict[str, Path]` pre-seeds input DSNs. A step whose `pgm` is in `UTILITIES` runs the emulator; otherwise its COBOL source is read from `source_dir / f"{pgm}.cbl"` and run via `run_cobol_step`.

- [ ] **Step 1: Write the failing test** (utility-only job — no bridge needed, keeps this unit test fast):

```python
from pathlib import Path

from jackal.model import DD, Disp, DispNormal, DispStatus, Job, Step
from jackal.runner import JobRunner


def test_runner_runs_all_steps(tmp_path):
    job = Job(name="J", steps=(
        Step(name="A", pgm="IEFBR14",
             dds=(DD("D", "J.X", Disp(DispStatus.NEW, DispNormal.DELETE, DispNormal.DELETE)),)),
        Step(name="B", pgm="IEFBR14", dds=()),
    ))
    runner = JobRunner(source_dir=tmp_path, bridge_jar="unused")
    res = runner.run(job, workdir=tmp_path, seeds={})
    assert [s.name for s in res.steps] == ["A", "B"]
    assert all(s.ran and s.return_code == 0 for s in res.steps)
```

- [ ] **Step 2: Run → fail** `uv run pytest tests/unit/test_runner.py -v`.

- [ ] **Step 3: Implement** `jackal/runner.py`:

```python
"""Sequence a Job's steps, threading a job-scoped DatasetCatalog."""
from __future__ import annotations

from pathlib import Path

from jackal.catalog import DatasetCatalog
from jackal.cobol_step import run_cobol_step
from jackal.model import Job, Step
from jackal.results import JobResult, StepResult
from jackal.utilities import UTILITIES


class JobRunner:
    def __init__(self, source_dir: Path, bridge_jar: str):
        self._source_dir = source_dir
        self._bridge_jar = bridge_jar

    def run(self, job: Job, workdir: Path, seeds: dict[str, Path]) -> JobResult:
        catalog = DatasetCatalog(workdir=workdir)
        for dsn, path in seeds.items():
            catalog.seed(dsn, path)
        return JobResult(steps=tuple(self._run_step(s, catalog) for s in job.steps))

    def _run_step(self, step: Step, catalog: DatasetCatalog) -> StepResult:
        if step.pgm in UTILITIES:
            return UTILITIES[step.pgm](step, catalog)
        source = (self._source_dir / f"{step.pgm}.cbl").read_text()
        return run_cobol_step(step, source, catalog, self._bridge_jar)
```

- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit** `git add jackal/runner.py tests/unit/test_runner.py && git commit -m "feat: JobRunner step sequencing (Task 7)"`

---

### Task 8: CLI

**Files:**
- Create: `jackal/cli.py`
- Test: `tests/unit/test_cli.py`
- Modify: `pyproject.toml` (add `[project.scripts] jackal = "jackal.cli:main"`)

**Interfaces:**
- Consumes: `jackal.jcl.parser.parse_jcl`, `jackal.runner.JobRunner`.
- Produces: `main(argv: list[str]) -> int`; CLI `jackal run <job.jcl> --source-dir DIR [--dataset DSN=PATH ...]`. Uses `argparse` (stdlib; not regex). Prints a per-step line and returns nonzero if any step failed.

- [ ] **Step 1: Write the failing test** (utility-only job, no bridge):

```python
from pathlib import Path

from jackal.cli import main


def test_cli_runs_utility_job(tmp_path, capsys):
    jcl = tmp_path / "j.jcl"
    jcl.write_text("//J JOB 1\n//A EXEC PGM=IEFBR14\n//D DD DSN=J.X,DISP=(NEW,DELETE,DELETE)\n")
    rc = main(["run", str(jcl), "--source-dir", str(tmp_path)])
    assert rc == 0
    assert "A" in capsys.readouterr().out
```

- [ ] **Step 2: Run → fail** `uv run pytest tests/unit/test_cli.py -v`.

- [ ] **Step 3: Implement** `jackal/cli.py`:

```python
"""jackal command-line entry point."""
from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from jackal.jcl.parser import parse_jcl
from jackal.runner import JobRunner


def _parse_dataset(spec: str) -> tuple[str, Path]:
    dsn, path = spec.split("=", 1)
    return dsn, Path(path)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="jackal")
    sub = ap.add_subparsers(dest="cmd", required=True)
    runp = sub.add_parser("run")
    runp.add_argument("jcl")
    runp.add_argument("--source-dir", required=True)
    runp.add_argument("--dataset", action="append", default=[])
    args = ap.parse_args(argv)

    job = parse_jcl(Path(args.jcl).read_text())
    seeds = dict(_parse_dataset(s) for s in args.dataset)
    runner = JobRunner(source_dir=Path(args.source_dir),
                       bridge_jar=os.environ.get("PROLEAP_BRIDGE_JAR", ""))
    workdir = Path(tempfile.mkdtemp(prefix="jackal_"))
    result = runner.run(job, workdir=workdir, seeds=seeds)
    for s in result.steps:
        print(f"{s.name}: RC={s.return_code} ran={s.ran}")
    return 0 if all(s.return_code == 0 for s in result.steps) else 1
```

Add to `pyproject.toml`:
```toml
[project.scripts]
jackal = "jackal.cli:main"
```

- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit** `git add jackal/cli.py tests/unit/test_cli.py pyproject.toml && git commit -m "feat: jackal CLI (Task 8)"`

---

### Task 9: Headline integration — synthetic multi-step pipeline

**Files:**
- Create: `tests/integration/fixtures/cbl/UPCASE.cbl`, `tests/integration/fixtures/cbl/STARRER.cbl`, `tests/integration/fixtures/pipeline.jcl`, `tests/integration/test_pipeline.py`

**Interfaces:**
- Consumes: everything above.

**Pipeline:** STEP1 `UPCASE` reads `J.IN` (seeded `"applemango"`) → uppercases each 5-byte record → writes `J.WORK` (NEW,PASS). STEP2 `STARRER` reads `J.WORK` (SHR) → replaces each record's first byte with `*` via reference modification → writes `J.OUT` (NEW,CATLG). Asserts the **intermediate** `J.WORK` = `b"APPLEMANGO"` (STEP1 transform) and the **final** `J.OUT` = `b"*PPLE*ANGO"` (STEP2 transform) — proving all steps ran and inter-step data flow worked.

- [ ] **Step 1: Write `UPCASE.cbl`** — identical structure to `COPYUP.cbl` (Task 5) but `PROGRAM-ID. UPCASE.` (copy the file; do not abbreviate).

(Full source — same as COPYUP.cbl from Task 5 with `PROGRAM-ID. UPCASE.`)

- [ ] **Step 2: Write `STARRER.cbl`** (reads `WRKDD`, sets first byte to `*`, writes `OUTDD`; SELECT≠DDname):

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARRER.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT W-FILE ASSIGN TO WRKDD ORGANIZATION IS SEQUENTIAL.
           SELECT O-FILE ASSIGN TO OUTDD ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  W-FILE.
       01  W-REC PIC X(5).
       FD  O-FILE.
       01  O-REC PIC X(5).
       WORKING-STORAGE SECTION.
       01  EOF-FLAG PIC X VALUE 'N'.
       PROCEDURE DIVISION.
           OPEN INPUT W-FILE.
           OPEN OUTPUT O-FILE.
           PERFORM UNTIL EOF-FLAG = 'Y'
               READ W-FILE
                   AT END MOVE 'Y' TO EOF-FLAG
                   NOT AT END
                       MOVE W-REC TO O-REC
                       MOVE '*' TO O-REC(1:1)
                       WRITE O-REC
               END-READ
           END-PERFORM.
           CLOSE W-FILE.
           CLOSE O-FILE.
           GOBACK.
```

- [ ] **Step 3: Write `pipeline.jcl`**:

```jcl
//PIPE JOB 'demo'
//STEP1 EXEC PGM=UPCASE
//INDD DD DSN=J.IN,DISP=SHR
//OUTDD DD DSN=J.WORK,DISP=(NEW,PASS,DELETE)
//STEP2 EXEC PGM=STARRER
//WRKDD DD DSN=J.WORK,DISP=SHR
//OUTDD DD DSN=J.OUT,DISP=(NEW,CATLG,DELETE)
```
Note: `J.WORK` is `PASS`ed by STEP1 and read `SHR` by STEP2 — the inter-step handoff.

- [ ] **Step 4: Write the failing test** `tests/integration/test_pipeline.py`:

```python
from pathlib import Path

import pytest

from jackal.jcl.parser import parse_jcl
from jackal.runner import JobRunner

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _require_bridge(bridge_jar):
    """Enforce PROLEAP_BRIDGE_JAR."""


def test_two_step_pipeline_transforms_through_intermediate(tmp_path, bridge_jar):
    seed = tmp_path / "in.dat"
    seed.write_bytes(b"applemango")
    job = parse_jcl((FIX / "pipeline.jcl").read_text())
    runner = JobRunner(source_dir=FIX / "cbl", bridge_jar=bridge_jar)
    result = runner.run(job, workdir=tmp_path, seeds={"J.IN": seed})

    assert [s.name for s in result.steps] == ["STEP1", "STEP2"]
    assert all(s.ran and s.return_code == 0 for s in result.steps)
    # STEP1 transform (intermediate, PASSed): uppercased
    assert (tmp_path / "J_WORK").read_bytes() == b"APPLEMANGO"
    # STEP2 transform (final): first byte of each 5-byte record starred
    assert (tmp_path / "J_OUT").read_bytes() == b"*PPLE*ANGO"
```

- [ ] **Step 5: Run → fail, then iterate to pass.**
```bash
cd ~/code/jackal
export PROLEAP_BRIDGE_JAR="$(pwd)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar"
uv run pytest tests/integration/test_pipeline.py -v
```
Expected: PASS. (`J.WORK` is `PASS`ed in STEP1 so it survives for STEP2; both DELETE on abnormal only. The final assertions read the catalog's backing files at `J_WORK`/`J_OUT`.)

- [ ] **Step 6: Full suite + format + commit**
```bash
uv run black .
uv run pytest -q
git add tests/integration/fixtures tests/integration/test_pipeline.py
git commit -m "test: synthetic two-step JCL pipeline end-to-end (Task 9)"
```

---

## Self-Review

**Spec coverage:** JCL parse (Task 3) ✓; multi-step sequencing (Task 7) ✓; DD→dataset resolution + inter-step handoff (Task 4 catalog + Task 9 PASS/SHR) ✓; COBOL via red-dragon (Task 5) ✓; IEFBR14 (Task 6) ✓; DDname binding via ASSIGN-name resolution (Task 1) ✓; verify-all-ran + intermediate-transformation (Task 9 assertions) ✓; no-regex/grammar-only (Task 3 grammar; argparse not regex) ✓; FP/frozen/no-defensive (all dataclasses frozen; no None defaults/guards) ✓; no external refs (synthetic fixtures) ✓; uv/pytest/Black ✓.

**Deferred (per spec, not gaps):** IDCAMS/SORT/IEBGENER, in-stream data, SYSOUT capture, symbolic params, PROCs, DD concatenation, GDG, COND/IF — all v2/v3.

**Type consistency:** `parse_jcl(str)->Job`; `Job.steps: tuple[Step,...]`; `Step.dds: tuple[DD,...]`; `DatasetCatalog.allocate(DD)->Dataset`/`.dispose(DD)`/`.seed(str,Path)`/`.resolve(str)->Dataset`; `run_cobol_step(Step,str,DatasetCatalog,str)->StepResult`; `UTILITIES[str](Step,DatasetCatalog)->StepResult`; `JobRunner(Path,str).run(Job,Path,dict[str,Path])->JobResult`. Names consistent across tasks.

**Known follow-ups (file as Beads after v1):** `DatasetCatalog.workdir` property (Task 5 note); step return-code from the program's actual `RETURN-CODE` (v1 hardcodes 0 on normal completion — fine until COND/abend handling lands).
