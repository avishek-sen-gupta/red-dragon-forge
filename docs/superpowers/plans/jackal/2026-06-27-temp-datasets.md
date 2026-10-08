# Temporary Datasets (&&NAME) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Honor `&&NAME` temporary datasets in JCL — allocate them from a job-scoped registry, pass them across steps, and clean up all survivors at job end.

**Architecture:** Introduce a `DSN` union type (`DirectDSN | TempRef`) to replace raw `str` in `DD.dsn`. The catalog gains a `_temp_registry: dict[str, DirectDSN]` that maps `&&NAME` aliases to their resolved backing DSNs. `JobRunner.run_job()` calls `catalog.cleanup_temps()` after all steps complete.

**Tech Stack:** Python 3.12 (structural pattern matching), frozen dataclasses, `uv run --no-sync pytest`.

## Global Constraints

- `uv run --no-sync` for ALL test runs and tool invocations — never plain `pytest`
- Export before running: `export PROLEAP_BRIDGE_JAR="$(pwd)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar"` and `export JCL_BRIDGE_JAR="$(pwd)/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar"` and `export CARDDEMO_HOME="$HOME/code/aws-mainframe-carddemo/app"`
- No Java changes — `make jar` not required
- `DD.dsn` is `DSN` (not `str`) everywhere after Task 1 — no raw-string fallback
- `TempRef` alias strips exactly two leading `&&` chars: `alias[2:]` gives the backing file name
- `TempRef` + `OLD`/`SHR` with no prior `NEW` → `KeyError(alias)` raised immediately in `allocate()`, not deferred to file open
- All tests must use `@covers(NotLanguageFeature.INFRASTRUCTURE)` decorator
- TDD: write failing test first, run to confirm failure, then implement
- Frequent commits — one per task at minimum
- If Talisman blocks a commit on JCL syntax false-positives, add a checksum entry to `.talismanrc` before `version: "1.0"` (append-only, never edit existing entries): run `git stash && talisman --checksum <file>` to get the checksum, add the entry, `git stash pop`, then re-commit

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `jackal/dsn.py` | Create | `DirectDSN`, `TempRef`, `DSN` type alias, `dsn_key()` helper |
| `jackal/model.py` | Modify | `DD.dsn: DSN` (was `str`) |
| `jackal/jcl/bridge_parser.py` | Modify | Task 1: always `DirectDSN`; Task 2: emit `TempRef` for `&&` |
| `jackal/catalog.py` | Modify | Task 1: use `dsn_key()`; Task 3: `_temp_registry`, `_allocate_temp()`, `cleanup_temps()` |
| `jackal/idcams/executor.py` | Modify | `outfile_dd.dsn.name` → `dsn_key(outfile_dd.dsn)` |
| `jackal/runner.py` | Modify | Call `catalog.cleanup_temps()` after step loop |
| `tests/unit/test_dsn.py` | Create | Unit tests for `DirectDSN`, `TempRef`, `dsn_key()` |
| `tests/unit/test_catalog.py` | Modify | Update `_dd()` helper; add temp dataset tests in Task 3 |
| `tests/unit/test_runner.py` | Modify | Update `DD(dsn="...")` → `DD(dsn=DirectDSN("..."))` |
| `tests/unit/test_jcl_bridge_deserialize.py` | Modify | Update any `dd.dsn == "..."` assertions; add `TempRef` tests in Task 2 |
| `tests/unit/test_parm.py` | Modify | Update `DD(dsn="...")` constructors if any |
| `tests/integration/test_temp_datasets.py` | Create | Two-step, three-step PASS chain, missing temp, job-end cleanup |

---

## Task 1: DSN type hierarchy + model migration (pure refactor)

**Goal:** Introduce `DirectDSN`/`TempRef` types and migrate every `DD.dsn` reference. No behavior change — all existing tests still pass.

**Files:**
- Create: `jackal/dsn.py`
- Create: `tests/unit/test_dsn.py`
- Modify: `jackal/model.py`
- Modify: `jackal/jcl/bridge_parser.py`
- Modify: `jackal/catalog.py`
- Modify: `jackal/idcams/executor.py`
- Modify: `tests/unit/test_catalog.py`
- Modify: `tests/unit/test_runner.py`
- Modify: `tests/unit/test_jcl_bridge_deserialize.py`

**Interfaces:**
- Produces: `DirectDSN(name: str)`, `TempRef(alias: str)`, `DSN = DirectDSN | TempRef`, `dsn_key(dsn: DSN) -> str` — all from `jackal.dsn`
- Produces: `DD.dsn: DSN` (was `str`)

- [ ] **Step 1: Write the failing test for the DSN types**

Create `tests/unit/test_dsn.py`:

```python
"""Unit tests for the DSN type hierarchy."""
from __future__ import annotations

import pytest

from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_direct_dsn_name():
    from jackal.dsn import DirectDSN

    assert DirectDSN("MY.DS").name == "MY.DS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_ref_alias():
    from jackal.dsn import TempRef

    assert TempRef("&&WORKIN").alias == "&&WORKIN"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_direct_dsn_equality():
    from jackal.dsn import DirectDSN

    assert DirectDSN("A") == DirectDSN("A")
    assert DirectDSN("A") != DirectDSN("B")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_ref_equality():
    from jackal.dsn import TempRef

    assert TempRef("&&A") == TempRef("&&A")
    assert TempRef("&&A") != TempRef("&&B")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dsn_key_extracts_direct_name():
    from jackal.dsn import DirectDSN, dsn_key

    assert dsn_key(DirectDSN("MY.DS")) == "MY.DS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dsn_key_raises_for_temp_ref():
    from jackal.dsn import TempRef, dsn_key

    with pytest.raises(TypeError, match="TempRef"):
        dsn_key(TempRef("&&WORKIN"))
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
uv run --no-sync pytest tests/unit/test_dsn.py -v
```
Expected: `ModuleNotFoundError: No module named 'jackal.dsn'`

- [ ] **Step 3: Create `jackal/dsn.py`**

```python
"""DSN type hierarchy: DirectDSN for permanent datasets, TempRef for &&NAME temps."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DirectDSN:
    name: str


@dataclass(frozen=True)
class TempRef:
    alias: str  # full &&NAME string, e.g. "&&WORKIN"


type DSN = DirectDSN | TempRef


def dsn_key(dsn: DSN) -> str:
    """Extract the string DSN name from a DirectDSN.

    Raises TypeError for TempRef — temp aliases must be resolved via the catalog
    before they can be used as a string key.
    """
    match dsn:
        case DirectDSN(name=n):
            return n
        case TempRef(alias=a):
            raise TypeError(f"TempRef '{a}' must be resolved via the catalog")
```

- [ ] **Step 4: Run DSN tests to confirm they pass**

```bash
uv run --no-sync pytest tests/unit/test_dsn.py -v
```
Expected: 6 tests PASS

- [ ] **Step 5: Update `jackal/model.py` — `DD.dsn: DSN`**

Change the `DD` dataclass. Import `DSN` from `jackal.dsn`. The `dsn` field changes from `str` to `DSN`. Keep field order identical to avoid breaking positional construction:

```python
"""Immutable JCL job model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from jackal.dsn import DSN


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


class DatasetOrg(Enum):
    PS = "PS"
    KSDS = "KSDS"


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
    step: str = ""


@dataclass(frozen=True)
class Disp:
    status: DispStatus
    normal: DispNormal
    abnormal: DispNormal


@dataclass(frozen=True)
class DD:
    ddname: str
    dsn: DSN
    disp: Disp
    in_stream: tuple[str, ...] = ()
    sysout: bool = False


@dataclass(frozen=True)
class Step:
    name: str
    pgm: str
    dds: tuple[DD, ...]
    conds: tuple[Cond, ...] = ()
    parm: str = ""


@dataclass(frozen=True)
class Job:
    name: str
    steps: tuple[Step, ...]
    cond: tuple[Cond, ...] = ()
```

- [ ] **Step 6: Update `jackal/jcl/bridge_parser.py` — always `DirectDSN` for now**

In `_dd_from_json`, wrap the raw DSN string in `DirectDSN`. Import `DirectDSN` at top of file:

```python
"""Bridge to the jcl-bridge JAR: JSON AST -> Job, and the JSON->model deserializer."""

from __future__ import annotations

import json
import subprocess

from jackal.dsn import DirectDSN
from jackal.model import Cond, CondOp, DD, Disp, DispNormal, DispStatus, Job, Step

_DEFAULT_DISP = Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP)


def _disp_from_words(words: tuple[str, ...]) -> Disp:
    status = DispStatus(words[0])
    normal = DispNormal(words[1]) if len(words) > 1 else DispNormal.KEEP
    abnormal = DispNormal(words[2]) if len(words) > 2 else normal
    return Disp(status, normal, abnormal)


def _dd_from_json(d: dict) -> DD:
    words = tuple(d.get("disp_words", ()))
    disp = _disp_from_words(words) if words else _DEFAULT_DISP
    return DD(
        ddname=d["ddname"],
        dsn=DirectDSN(d.get("dsn", "")),
        disp=disp,
        in_stream=tuple(d.get("in_stream", ())),
        sysout=d.get("sysout", False),
    )


def _cond_from_json(c: dict) -> Cond:
    return Cond(code=c["code"], op=CondOp(c["op"]), step=c.get("step", ""))


def _step_from_json(s: dict) -> Step:
    return Step(
        name=s["name"],
        pgm=s["pgm"],
        dds=tuple(_dd_from_json(d) for d in s["dds"]),
        conds=tuple(_cond_from_json(c) for c in s.get("cond", ())),
        parm=s.get("parm", ""),
    )


def _job_from_json(data: dict) -> Job:
    return Job(
        name=data["name"],
        steps=tuple(_step_from_json(s) for s in data["steps"]),
        cond=tuple(_cond_from_json(c) for c in data.get("cond", ())),
    )


class JclParseError(Exception):
    """Raised when the jcl-bridge fails to parse JCL."""


class JclSubprocessRunner:
    """Production runner: invoke the bridge JAR, fail loud on non-zero exit."""

    def run(self, command: list[str], input_data: str) -> str:
        result = subprocess.run(
            command, input=input_data, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise JclParseError(
                f"jcl-bridge failed (exit {result.returncode}): {result.stderr}"
            )
        return result.stdout


class JclBridgeParser:
    """Parse JCL by delegating to the jcl-bridge JAR via subprocess."""

    def __init__(self, runner: JclSubprocessRunner, bridge_jar: str):
        self._runner = runner
        self._bridge_jar = bridge_jar

    def parse(self, text: str) -> Job:
        command = ["java", "-jar", self._bridge_jar]
        out = self._runner.run(command, text)
        try:
            return _job_from_json(json.loads(out))
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            snippet = out[:120].replace("\n", " ")
            raise JclParseError(
                f"bridge returned malformed/incomplete JSON: {e} — output: {snippet!r}"
            ) from e
```

- [ ] **Step 7: Update `jackal/catalog.py` — use `dsn_key()` throughout**

Replace every `dd.dsn` (used as a string) with `dsn_key(dd.dsn)`. Import `dsn_key, DirectDSN` from `jackal.dsn`. The `dispose()` method already only acts on DELETE — just update the key extraction. The full updated file:

```python
"""Job-scoped dataset catalog: DSN -> backing file, with DISP lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from interpreter.cobol.file_drivers import FileOrganizationDriver, open_driver
from interpreter.cobol.file_enums import FileOrganization, OpenMode
from jackal.dsn import DSN, DirectDSN, dsn_key
from jackal.model import DD, DatasetOrg, DispNormal, DispStatus


@dataclass(frozen=True)
class DatasetSpec:
    dsn: str
    org: DatasetOrg
    key_offset: int = 0
    key_length: int = 0
    record_size: int = 0


@dataclass(frozen=True)
class Dataset:
    dsn: str
    path: Path
    org: DatasetOrg = DatasetOrg.PS
    key_offset: int = 0
    key_length: int = 0
    record_size: int = 0


_ORG_MAP: dict[DatasetOrg, FileOrganization] = {
    DatasetOrg.PS: FileOrganization.SEQUENTIAL,
    DatasetOrg.KSDS: FileOrganization.INDEXED,
}


class DatasetCatalog:
    """Imperative shell: owns the job workdir and the DSN->file mapping."""

    def __init__(self, workdir: Path, data_dir: Path):
        self._workdir = workdir
        self._data_dir = data_dir
        self._datasets: dict[str, Dataset] = {}

    def seed(self, dsn: str, path: Path) -> None:
        self._datasets[dsn] = Dataset(dsn=dsn, path=path)

    def resolve(self, dsn: str) -> Dataset:
        return self._datasets[dsn]

    def allocate(self, dd: DD) -> Dataset:
        name = dsn_key(dd.dsn)
        if dd.disp.status in (DispStatus.OLD, DispStatus.SHR):
            if name in self._datasets:
                return self._datasets[name]
            candidate = self._data_dir / name
            if candidate.exists():
                ds = Dataset(dsn=name, path=candidate)
                self._datasets[name] = ds
                return ds
            raise KeyError(name)
        if dd.disp.status is DispStatus.MOD:
            if name in self._datasets:
                return self._datasets[name]
            candidate = self._data_dir / name
            if candidate.exists():
                ds = Dataset(dsn=name, path=candidate)
                self._datasets[name] = ds
                return ds
            path = self._workdir / name.replace(".", "_")
            path.write_bytes(b"")
            ds = Dataset(dsn=name, path=path)
            self._datasets[name] = ds
            return ds
        path = self._workdir / name.replace(".", "_")
        path.write_bytes(b"")
        ds = Dataset(dsn=name, path=path)
        self._datasets[name] = ds
        return ds

    def allocate_new(self, spec: DatasetSpec) -> Dataset:
        if spec.dsn in self._datasets:
            raise ValueError(f"DSN already allocated: {spec.dsn}")
        if spec.org is DatasetOrg.KSDS:
            if spec.record_size == 0:
                raise ValueError(f"KSDS record_size must be > 0: {spec.dsn}")
            if spec.key_length == 0:
                raise ValueError(f"KSDS key_length must be > 0: {spec.dsn}")
        path = self._workdir / spec.dsn.replace(".", "_")
        path.write_bytes(b"")
        ds = Dataset(
            dsn=spec.dsn,
            path=path,
            org=spec.org,
            key_offset=spec.key_offset,
            key_length=spec.key_length,
            record_size=spec.record_size,
        )
        self._datasets[spec.dsn] = ds
        return ds

    def open_dataset(
        self, dsn: str, mode: OpenMode, record_size: int | None = None
    ) -> FileOrganizationDriver:
        ds = self._datasets[dsn]
        rl = record_size if record_size is not None else ds.record_size
        return open_driver(
            _ORG_MAP[ds.org], ds.path, mode, rl, ds.key_offset, ds.key_length
        )

    def delete_dsn(self, dsn: str) -> bool:
        if dsn not in self._datasets:
            return False
        ds = self._datasets.pop(dsn)
        ds.path.unlink(missing_ok=True)
        return True

    def dispose(self, dd: DD) -> None:
        if dd.disp.normal is DispNormal.DELETE:
            self.delete_dsn(dsn_key(dd.dsn))

    @property
    def workdir(self) -> Path:
        return self._workdir
```

- [ ] **Step 8: Update `jackal/idcams/executor.py` — use `dsn_key()`**

In `_handle_repro`, change `catalog.resolve(outfile_dd.dsn)` to use `dsn_key`:

```python
from jackal.dsn import dsn_key
```

Add this import at the top alongside other jackal imports. Then change the one line in `_handle_repro`:

```python
out_ds = catalog.resolve(dsn_key(outfile_dd.dsn))
```

The full updated `_handle_repro`:

```python
def _handle_repro(
    cmd: Repro,
    dds_by_ddname: dict[str, DD],
    catalog: DatasetCatalog,
) -> int:
    infile_dd = dds_by_ddname[cmd.infile_dd]
    outfile_dd = dds_by_ddname[cmd.outfile_dd]

    in_ds = catalog.allocate(infile_dd)
    out_ds = catalog.resolve(dsn_key(outfile_dd.dsn))

    in_drv = catalog.open_dataset(
        in_ds.dsn, OpenMode.INPUT, record_size=out_ds.record_size
    )
    out_drv = catalog.open_dataset(out_ds.dsn, OpenMode.OUTPUT)

    while True:
        result = in_drv.read_seq()
        if result.condition is AccessCondition.END_OF_FILE:
            break
        if result.data is None:
            raise ValueError("driver returned non-EOF with no data")
        out_drv.write(result.data)

    in_drv.close()
    out_drv.close()
    return 0
```

- [ ] **Step 9: Update test fixtures that construct `DD` with a raw string**

In `tests/unit/test_catalog.py`, update the `_dd` helper to wrap the string in `DirectDSN`:

```python
from jackal.dsn import DirectDSN
from jackal.catalog import DatasetCatalog, DatasetSpec
from jackal.model import DD, Disp, DispNormal, DispStatus, DatasetOrg
from tests.covers import covers, NotLanguageFeature


def _dd(dsn: str, status: DispStatus, normal: DispNormal = DispNormal.KEEP) -> DD:
    return DD(ddname="D", dsn=DirectDSN(dsn), disp=Disp(status, normal, DispNormal.DELETE))
```

(The rest of `test_catalog.py` calls `_dd("J.WORK", ...)` — no changes needed in the call sites because the helper absorbs the string-to-DirectDSN wrapping.)

In `tests/unit/test_runner.py`, update the one DD constructed with a positional string:

```python
from jackal.dsn import DirectDSN
```

Change:
```python
DD("D", "J.X", Disp(DispStatus.NEW, DispNormal.DELETE, DispNormal.DELETE)),
```
to:
```python
DD("D", DirectDSN("J.X"), Disp(DispStatus.NEW, DispNormal.DELETE, DispNormal.DELETE)),
```

In `tests/unit/test_jcl_bridge_deserialize.py`: check whether any assertion compares `dd.dsn` to a string (e.g. `assert w.dsn == "J.WORK"`). If found, update to `assert w.dsn == DirectDSN("J.WORK")`. Add `from jackal.dsn import DirectDSN` at top if needed.

- [ ] **Step 10: Run the full test suite to confirm no regressions**

```bash
uv run --no-sync pytest tests/ -v
```
Expected: all previously passing tests still PASS. This is a pure refactor — zero behavior change.

- [ ] **Step 11: Commit**

```bash
git add jackal/dsn.py jackal/model.py jackal/jcl/bridge_parser.py jackal/catalog.py jackal/idcams/executor.py tests/unit/test_dsn.py tests/unit/test_catalog.py tests/unit/test_runner.py tests/unit/test_jcl_bridge_deserialize.py
git commit -m "refactor: introduce DirectDSN/TempRef type hierarchy for DD.dsn"
```

If Talisman blocks, compute the checksum and add it to `.talismanrc`:
```bash
talisman --checksum tests/unit/test_dsn.py
# copy the reported checksum, add to .talismanrc before version: "1.0":
# - filename: tests/unit/test_dsn.py
#   checksum: <checksum>
git add .talismanrc && git commit -m "refactor: introduce DirectDSN/TempRef type hierarchy for DD.dsn"
```

---

## Task 2: Bridge parser — `&&NAME` → `TempRef`

**Goal:** `_dd_from_json` emits `TempRef` for any DSN starting with `&&`.

**Files:**
- Modify: `jackal/jcl/bridge_parser.py`
- Modify: `tests/unit/test_jcl_bridge_deserialize.py`

**Interfaces:**
- Consumes: `TempRef`, `DirectDSN`, `DSN` from `jackal.dsn` (Task 1)
- Produces: `_dd_from_json` returns `DD(dsn=TempRef("&&NAME"))` for `&&` DSNs

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_jcl_bridge_deserialize.py`:

```python
from jackal.dsn import DirectDSN, TempRef


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dd_from_json_temp_ref_dsn():
    from jackal.jcl.bridge_parser import _job_from_json

    data = {
        "name": "J",
        "steps": [
            {
                "name": "S",
                "pgm": "P",
                "dds": [
                    {
                        "ddname": "WRK",
                        "dsn": "&&WORKIN",
                        "disp_words": ["NEW", "PASS"],
                        "in_stream": [],
                        "sysout": False,
                    }
                ],
            }
        ],
    }
    job = _job_from_json(data)
    dd = job.steps[0].dds[0]
    assert isinstance(dd.dsn, TempRef)
    assert dd.dsn.alias == "&&WORKIN"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dd_from_json_direct_dsn_unchanged():
    from jackal.jcl.bridge_parser import _job_from_json

    data = {
        "name": "J",
        "steps": [
            {
                "name": "S",
                "pgm": "P",
                "dds": [
                    {
                        "ddname": "IN",
                        "dsn": "MY.DATA",
                        "disp_words": ["SHR"],
                        "in_stream": [],
                        "sysout": False,
                    }
                ],
            }
        ],
    }
    job = _job_from_json(data)
    dd = job.steps[0].dds[0]
    assert isinstance(dd.dsn, DirectDSN)
    assert dd.dsn.name == "MY.DATA"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dd_from_json_absent_dsn_is_direct_empty():
    from jackal.jcl.bridge_parser import _job_from_json

    data = {
        "name": "J",
        "steps": [
            {
                "name": "S",
                "pgm": "P",
                "dds": [
                    {"ddname": "SYSOUT", "disp_words": [], "in_stream": [], "sysout": True}
                ],
            }
        ],
    }
    job = _job_from_json(data)
    dd = job.steps[0].dds[0]
    assert isinstance(dd.dsn, DirectDSN)
    assert dd.dsn.name == ""
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
uv run --no-sync pytest tests/unit/test_jcl_bridge_deserialize.py::test_dd_from_json_temp_ref_dsn tests/unit/test_jcl_bridge_deserialize.py::test_dd_from_json_direct_dsn_unchanged tests/unit/test_jcl_bridge_deserialize.py::test_dd_from_json_absent_dsn_is_direct_empty -v
```
Expected: `test_dd_from_json_temp_ref_dsn` FAILS (gets `DirectDSN` instead of `TempRef`); the other two PASS already (they confirm existing behavior).

- [ ] **Step 3: Update `_dd_from_json` in `jackal/jcl/bridge_parser.py`**

Change the import line at top from `from jackal.dsn import DirectDSN` to:

```python
from jackal.dsn import DSN, DirectDSN, TempRef
```

Update `_dd_from_json`:

```python
def _dd_from_json(d: dict) -> DD:
    words = tuple(d.get("disp_words", ()))
    disp = _disp_from_words(words) if words else _DEFAULT_DISP
    raw_dsn = d.get("dsn", "")
    dsn: DSN = TempRef(raw_dsn) if raw_dsn.startswith("&&") else DirectDSN(raw_dsn)
    return DD(
        ddname=d["ddname"],
        dsn=dsn,
        disp=disp,
        in_stream=tuple(d.get("in_stream", ())),
        sysout=d.get("sysout", False),
    )
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
uv run --no-sync pytest tests/unit/test_jcl_bridge_deserialize.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Run the full suite to confirm no regressions**

```bash
uv run --no-sync pytest tests/ -v
```
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add jackal/jcl/bridge_parser.py tests/unit/test_jcl_bridge_deserialize.py
git commit -m "feat: bridge parser emits TempRef for &&NAME DSNs"
```

---

## Task 3: Catalog temp registry

**Goal:** `DatasetCatalog` recognizes `TempRef` in `allocate()` and `dispose()`, maintains `_temp_registry`, and provides `cleanup_temps()`.

**Files:**
- Modify: `jackal/catalog.py`
- Modify: `tests/unit/test_catalog.py`

**Interfaces:**
- Consumes: `TempRef`, `DirectDSN`, `DSN` from `jackal.dsn` (Task 1)
- Produces: `DatasetCatalog.cleanup_temps() -> None` (called by Task 4 runner)

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_catalog.py`:

```python
import pytest
from jackal.dsn import DirectDSN, TempRef
from jackal.model import Disp, DispNormal, DispStatus


def _temp_dd(alias: str, status: DispStatus, normal: DispNormal = DispNormal.PASS) -> DD:
    return DD(ddname="W", dsn=TempRef(alias), disp=Disp(status, normal, DispNormal.DELETE))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_new_allocates_backing_file(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    ds = cat.allocate(_temp_dd("&&WORKIN", DispStatus.NEW))
    assert ds.path.exists()
    assert ds.path.name == "WORKIN"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_old_resolves_same_dataset(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    ds1 = cat.allocate(_temp_dd("&&WORKIN", DispStatus.NEW))
    ds2 = cat.allocate(_temp_dd("&&WORKIN", DispStatus.OLD))
    assert ds1.path == ds2.path


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_old_unregistered_raises(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    with pytest.raises(KeyError):
        cat.allocate(_temp_dd("&&GHOST", DispStatus.OLD))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_dispose_delete_removes_file(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    dd = _temp_dd("&&TEMP", DispStatus.NEW, DispNormal.DELETE)
    ds = cat.allocate(dd)
    cat.dispose(dd)
    assert not ds.path.exists()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_dispose_pass_retains_file(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    dd = _temp_dd("&&TEMP", DispStatus.NEW, DispNormal.PASS)
    ds = cat.allocate(dd)
    cat.dispose(dd)
    assert ds.path.exists()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cleanup_temps_deletes_surviving_file(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    ds = cat.allocate(_temp_dd("&&TEMP", DispStatus.NEW, DispNormal.PASS))
    cat.cleanup_temps()
    assert not ds.path.exists()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cleanup_temps_noop_when_all_deleted(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    dd = _temp_dd("&&TEMP", DispStatus.NEW, DispNormal.DELETE)
    cat.allocate(dd)
    cat.dispose(dd)
    cat.cleanup_temps()  # must not raise


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_new_duplicate_alias_raises(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    cat.allocate(_temp_dd("&&TEMP", DispStatus.NEW))
    with pytest.raises(ValueError, match="&&TEMP"):
        cat.allocate(_temp_dd("&&TEMP", DispStatus.NEW))
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
uv run --no-sync pytest tests/unit/test_catalog.py::test_temp_new_allocates_backing_file tests/unit/test_catalog.py::test_temp_old_resolves_same_dataset tests/unit/test_catalog.py::test_temp_old_unregistered_raises tests/unit/test_catalog.py::test_temp_dispose_delete_removes_file tests/unit/test_catalog.py::test_temp_dispose_pass_retains_file tests/unit/test_catalog.py::test_cleanup_temps_deletes_surviving_file tests/unit/test_catalog.py::test_cleanup_temps_noop_when_all_deleted tests/unit/test_catalog.py::test_temp_new_duplicate_alias_raises -v
```
Expected: all 8 FAIL (TypeError or similar — `allocate()` calls `dsn_key()` which raises for `TempRef`).

- [ ] **Step 3: Rewrite `jackal/catalog.py` with TempRef dispatch**

Replace `allocate()` and `dispose()` with type-dispatching versions, add `_temp_registry` and `cleanup_temps()`. Full updated file:

```python
"""Job-scoped dataset catalog: DSN -> backing file, with DISP lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from interpreter.cobol.file_drivers import FileOrganizationDriver, open_driver
from interpreter.cobol.file_enums import FileOrganization, OpenMode
from jackal.dsn import DirectDSN, TempRef, dsn_key
from jackal.model import DD, DatasetOrg, DispNormal, DispStatus


@dataclass(frozen=True)
class DatasetSpec:
    dsn: str
    org: DatasetOrg
    key_offset: int = 0
    key_length: int = 0
    record_size: int = 0


@dataclass(frozen=True)
class Dataset:
    dsn: str
    path: Path
    org: DatasetOrg = DatasetOrg.PS
    key_offset: int = 0
    key_length: int = 0
    record_size: int = 0


_ORG_MAP: dict[DatasetOrg, FileOrganization] = {
    DatasetOrg.PS: FileOrganization.SEQUENTIAL,
    DatasetOrg.KSDS: FileOrganization.INDEXED,
}


class DatasetCatalog:
    """Imperative shell: owns the job workdir and the DSN->file mapping."""

    def __init__(self, workdir: Path, data_dir: Path):
        self._workdir = workdir
        self._data_dir = data_dir
        self._datasets: dict[str, Dataset] = {}
        self._temp_registry: dict[str, DirectDSN] = {}

    def seed(self, dsn: str, path: Path) -> None:
        self._datasets[dsn] = Dataset(dsn=dsn, path=path)

    def resolve(self, dsn: str) -> Dataset:
        return self._datasets[dsn]

    def allocate(self, dd: DD) -> Dataset:
        match dd.dsn:
            case TempRef(alias=alias):
                return self._allocate_temp(alias, dd.disp.status)
            case DirectDSN(name=name):
                return self._allocate_direct(name, dd)

    def _allocate_temp(self, alias: str, status: DispStatus) -> Dataset:
        if status is DispStatus.NEW:
            if alias in self._temp_registry:
                raise ValueError(f"TempRef already allocated: {alias}")
            name = alias[2:]  # strip exactly the two leading &&
            path = self._workdir / name
            path.write_bytes(b"")
            self._temp_registry[alias] = DirectDSN(name)
            ds = Dataset(dsn=name, path=path)
            self._datasets[name] = ds
            return ds
        if status in (DispStatus.OLD, DispStatus.SHR, DispStatus.MOD):
            if alias not in self._temp_registry:
                raise KeyError(alias)
            return self._datasets[self._temp_registry[alias].name]
        raise ValueError(f"Unexpected DispStatus for TempRef: {status}")

    def _allocate_direct(self, name: str, dd: DD) -> Dataset:
        if dd.disp.status in (DispStatus.OLD, DispStatus.SHR):
            if name in self._datasets:
                return self._datasets[name]
            candidate = self._data_dir / name
            if candidate.exists():
                ds = Dataset(dsn=name, path=candidate)
                self._datasets[name] = ds
                return ds
            raise KeyError(name)
        if dd.disp.status is DispStatus.MOD:
            if name in self._datasets:
                return self._datasets[name]
            candidate = self._data_dir / name
            if candidate.exists():
                ds = Dataset(dsn=name, path=candidate)
                self._datasets[name] = ds
                return ds
            path = self._workdir / name.replace(".", "_")
            path.write_bytes(b"")
            ds = Dataset(dsn=name, path=path)
            self._datasets[name] = ds
            return ds
        # NEW
        path = self._workdir / name.replace(".", "_")
        path.write_bytes(b"")
        ds = Dataset(dsn=name, path=path)
        self._datasets[name] = ds
        return ds

    def allocate_new(self, spec: DatasetSpec) -> Dataset:
        if spec.dsn in self._datasets:
            raise ValueError(f"DSN already allocated: {spec.dsn}")
        if spec.org is DatasetOrg.KSDS:
            if spec.record_size == 0:
                raise ValueError(f"KSDS record_size must be > 0: {spec.dsn}")
            if spec.key_length == 0:
                raise ValueError(f"KSDS key_length must be > 0: {spec.dsn}")
        path = self._workdir / spec.dsn.replace(".", "_")
        path.write_bytes(b"")
        ds = Dataset(
            dsn=spec.dsn,
            path=path,
            org=spec.org,
            key_offset=spec.key_offset,
            key_length=spec.key_length,
            record_size=spec.record_size,
        )
        self._datasets[spec.dsn] = ds
        return ds

    def open_dataset(
        self, dsn: str, mode: OpenMode, record_size: int | None = None
    ) -> FileOrganizationDriver:
        ds = self._datasets[dsn]
        rl = record_size if record_size is not None else ds.record_size
        return open_driver(
            _ORG_MAP[ds.org], ds.path, mode, rl, ds.key_offset, ds.key_length
        )

    def delete_dsn(self, dsn: str) -> bool:
        if dsn not in self._datasets:
            return False
        ds = self._datasets.pop(dsn)
        ds.path.unlink(missing_ok=True)
        return True

    def dispose(self, dd: DD) -> None:
        if dd.disp.normal is not DispNormal.DELETE:
            return
        match dd.dsn:
            case TempRef(alias=alias):
                if alias in self._temp_registry:
                    direct = self._temp_registry.pop(alias)
                    self.delete_dsn(direct.name)
            case DirectDSN(name=name):
                self.delete_dsn(name)

    def cleanup_temps(self) -> None:
        """Delete all surviving temp datasets and clear the registry. Called at job end."""
        for direct in list(self._temp_registry.values()):
            self.delete_dsn(direct.name)
        self._temp_registry.clear()

    @property
    def workdir(self) -> Path:
        return self._workdir
```

- [ ] **Step 4: Run the new catalog tests to confirm they pass**

```bash
uv run --no-sync pytest tests/unit/test_catalog.py -v
```
Expected: all tests PASS including the 8 new temp dataset tests.

- [ ] **Step 5: Run the full suite to confirm no regressions**

```bash
uv run --no-sync pytest tests/ -v
```
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add jackal/catalog.py tests/unit/test_catalog.py
git commit -m "feat: catalog temp registry — allocate/dispose/cleanup_temps for &&NAME"
```

---

## Task 4: Runner cleanup + integration tests

**Goal:** `JobRunner.run_job()` calls `catalog.cleanup_temps()` unconditionally after the step loop. Integration tests verify the full end-to-end flow.

**Files:**
- Modify: `jackal/runner.py`
- Create: `tests/integration/test_temp_datasets.py`

**Interfaces:**
- Consumes: `DatasetCatalog.cleanup_temps()` (Task 3), `TempRef`, `DirectDSN` (Task 1)
- Consumes: `DD`, `Disp`, `DispNormal`, `DispStatus`, `Job`, `Step` from `jackal.model`

- [ ] **Step 1: Write the failing integration tests**

Create `tests/integration/test_temp_datasets.py`:

```python
"""Integration tests: &&NAME temporary dataset lifecycle via JobRunner."""
from __future__ import annotations

from jackal.dsn import DirectDSN, TempRef
from jackal.model import DD, Disp, DispNormal, DispStatus, Job, Step
from jackal.runner import JobRunner
from tests.covers import NotLanguageFeature, covers


def _pass_dd(alias: str) -> DD:
    """Create a DD that allocates a new temp dataset and passes it to the next step."""
    return DD(
        ddname="WRK",
        dsn=TempRef(alias),
        disp=Disp(DispStatus.NEW, DispNormal.PASS, DispNormal.DELETE),
    )


def _old_pass_dd(alias: str) -> DD:
    """Create a DD that opens an existing temp and passes it onward."""
    return DD(
        ddname="WRK",
        dsn=TempRef(alias),
        disp=Disp(DispStatus.OLD, DispNormal.PASS, DispNormal.DELETE),
    )


def _old_delete_dd(alias: str) -> DD:
    """Create a DD that opens and deletes an existing temp dataset."""
    return DD(
        ddname="WRK",
        dsn=TempRef(alias),
        disp=Disp(DispStatus.OLD, DispNormal.DELETE, DispNormal.DELETE),
    )


def _runner(tmp_path):
    return JobRunner(
        source_dir=tmp_path,
        bridge_jar="unused",
        data_dir=tmp_path,
        copybook_dir=tmp_path,
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_two_step_temp_dataset(tmp_path):
    """Step 1 creates &&TEMP (PASS); step 2 opens and deletes it."""
    job = Job(
        name="J",
        steps=(
            Step(name="S1", pgm="IEFBR14", dds=(_pass_dd("&&TEMP"),)),
            Step(name="S2", pgm="IEFBR14", dds=(_old_delete_dd("&&TEMP"),)),
        ),
    )
    result = _runner(tmp_path).run(job, workdir=tmp_path, seeds={})
    assert all(s.ran and s.return_code == 0 for s in result.steps)
    assert not (tmp_path / "TEMP").exists()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_three_step_pass_chain(tmp_path):
    """Step 1 creates &&TEMP; step 2 reads+passes; step 3 deletes."""
    job = Job(
        name="J",
        steps=(
            Step(name="S1", pgm="IEFBR14", dds=(_pass_dd("&&TEMP"),)),
            Step(name="S2", pgm="IEFBR14", dds=(_old_pass_dd("&&TEMP"),)),
            Step(name="S3", pgm="IEFBR14", dds=(_old_delete_dd("&&TEMP"),)),
        ),
    )
    result = _runner(tmp_path).run(job, workdir=tmp_path, seeds={})
    assert all(s.ran and s.return_code == 0 for s in result.steps)
    assert not (tmp_path / "TEMP").exists()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_missing_temp_raises(tmp_path):
    """Referencing an unallocated &&GHOST with OLD raises KeyError."""
    import pytest

    job = Job(
        name="J",
        steps=(Step(name="S1", pgm="IEFBR14", dds=(_old_delete_dd("&&GHOST"),)),),
    )
    with pytest.raises(KeyError):
        _runner(tmp_path).run(job, workdir=tmp_path, seeds={})


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_job_end_cleanup_removes_undeleted_temp(tmp_path):
    """&&TEMP PASSed by step 1 but never explicitly deleted is cleaned at job end."""
    job = Job(
        name="J",
        steps=(Step(name="S1", pgm="IEFBR14", dds=(_pass_dd("&&TEMP"),)),),
    )
    result = _runner(tmp_path).run(job, workdir=tmp_path, seeds={})
    assert result.steps[0].ran
    assert not (tmp_path / "TEMP").exists()
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
uv run --no-sync pytest tests/integration/test_temp_datasets.py -v
```
Expected: `test_job_end_cleanup_removes_undeleted_temp` FAILS (the backing file still exists because `cleanup_temps()` is not called yet). The other three tests PASS already — Task 3 gave the catalog full TempRef support, so allocate/dispose/delete work correctly; only the job-end cleanup hook in the runner is missing.

- [ ] **Step 3: Update `jackal/runner.py` — call `cleanup_temps()` after step loop**

```python
"""Sequence a Job's steps, threading a job-scoped DatasetCatalog."""

from __future__ import annotations

from pathlib import Path

from jackal.catalog import DatasetCatalog
from jackal.cobol_step import run_cobol_step
from jackal.cond import should_bypass
from jackal.model import Job, Step
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
        """Run a job against a pre-built catalog, honoring COND= step bypass."""
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
        catalog.cleanup_temps()
        return JobResult(steps=tuple(results))

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

- [ ] **Step 4: Run the integration tests to confirm they pass**

```bash
uv run --no-sync pytest tests/integration/test_temp_datasets.py -v
```
Expected: all 4 PASS.

- [ ] **Step 5: Run the full suite to confirm no regressions**

```bash
uv run --no-sync pytest tests/ -v
```
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add jackal/runner.py tests/integration/test_temp_datasets.py
git commit -m "feat: &&NAME temp dataset lifecycle — runner cleanup + integration tests (jackal-1o2.11)"
```

If Talisman blocks on JCL patterns in the integration test file, add a checksum entry:
```bash
talisman --checksum tests/integration/test_temp_datasets.py
# add entry to .talismanrc before version: "1.0":
# - filename: tests/integration/test_temp_datasets.py
#   checksum: <checksum>
git add .talismanrc
git commit -m "feat: &&NAME temp dataset lifecycle — runner cleanup + integration tests (jackal-1o2.11)"
```
