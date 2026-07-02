# jackal-vxb: Dataset Catalog — Generalized Allocation + Access Face

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `allocate_ksds` with a general `allocate_new(DatasetSpec)`, add `open_dataset` as the catalog's access face, and update `idcams/executor.py` to go through the catalog instead of calling `open_driver` directly.

**Architecture:** Three incremental tasks, each leaving the test suite green. Tasks 1 and 2 extend `DatasetCatalog` without removing anything. Task 3 wires up the executor, removes `allocate_ksds`, and verifies the full suite.

**Tech Stack:** Python 3.13, pytest, `uv run --no-sync`, red-dragon vendor at `vendor/red-dragon/`.

## Global Constraints

- Always invoke tools with `uv run --no-sync` (e.g. `uv run --no-sync pytest`)
- `frozen=True` on all new dataclasses
- No `None` defaults, no defensive guards — fail loud
- No comments explaining WHAT; only add a comment when WHY is non-obvious
- Export env vars before running tests:
  ```bash
  export PROLEAP_BRIDGE_JAR="$(pwd)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar"
  export JCL_BRIDGE_JAR="$(pwd)/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar"
  export CARDDEMO_HOME="$HOME/code/aws-mainframe-carddemo/app"
  ```

---

## File Map

| File | Change |
|---|---|
| `jackal/catalog.py` | Add `DatasetSpec`; add `allocate_new`; add `open_dataset` + `_ORG_MAP`; delete `allocate_ksds`; new imports from red-dragon |
| `jackal/idcams/executor.py` | Use `allocate_new(DatasetSpec(...))` in `_handle_define_cluster`; use `catalog.open_dataset` in `_handle_repro`; remove `open_driver`/`FileOrganization` imports; add `DatasetSpec`/`DatasetOrg` imports |
| `tests/unit/test_catalog.py` | Rename `test_allocate_ksds` → `test_allocate_new_ksds`; add 5 new tests |

---

### Task 1: `DatasetSpec` + `allocate_new`

**Files:**
- Modify: `jackal/catalog.py`
- Modify: `tests/unit/test_catalog.py`

**Interfaces:**
- Produces: `DatasetSpec(dsn, org, key_offset=0, key_length=0, record_size=0)` in `jackal.catalog`; `DatasetCatalog.allocate_new(spec: DatasetSpec) -> Dataset`

- [ ] **Step 1: Write the failing tests**

Replace `test_allocate_ksds` and add three new tests. Update the import line at the top of `tests/unit/test_catalog.py`:

```python
from jackal.catalog import DatasetCatalog, DatasetSpec
```

Remove the existing `test_allocate_ksds` function (lines 61-67) and replace with:

```python
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_allocate_new_ksds(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    spec = DatasetSpec(dsn="A.B.KSDS", org=DatasetOrg.KSDS, key_offset=0, key_length=11, record_size=300)
    ds = cat.allocate_new(spec)
    assert ds.org is DatasetOrg.KSDS and ds.key_length == 11 and ds.record_size == 300
    assert ds.path.exists()
    assert cat.resolve("A.B.KSDS").org is DatasetOrg.KSDS


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_allocate_new_duplicate_dsn_raises(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    spec = DatasetSpec(dsn="A.B.KSDS", org=DatasetOrg.KSDS, key_offset=0, key_length=11, record_size=300)
    cat.allocate_new(spec)
    with pytest.raises(ValueError, match="A.B.KSDS"):
        cat.allocate_new(spec)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_allocate_new_ksds_zero_record_size_raises(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    spec = DatasetSpec(dsn="A.B.KSDS", org=DatasetOrg.KSDS, key_offset=0, key_length=11, record_size=0)
    with pytest.raises(ValueError, match="record_size"):
        cat.allocate_new(spec)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_allocate_new_ksds_zero_key_length_raises(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    spec = DatasetSpec(dsn="A.B.KSDS", org=DatasetOrg.KSDS, key_offset=0, key_length=0, record_size=300)
    with pytest.raises(ValueError, match="key_length"):
        cat.allocate_new(spec)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run --no-sync pytest tests/unit/test_catalog.py -v -k "allocate_new"
```

Expected: 4 failures — `ImportError: cannot import name 'DatasetSpec'` or `AttributeError: 'DatasetCatalog' object has no attribute 'allocate_new'`

- [ ] **Step 3: Add `DatasetSpec` and `allocate_new` to `catalog.py`**

At the top of `jackal/catalog.py`, add these imports after `from __future__ import annotations`:

```python
from interpreter.cobol.file_drivers import FileOrganizationDriver, open_driver
from interpreter.cobol.file_enums import FileOrganization, OpenMode
```

After the `Dataset` dataclass definition (before `class DatasetCatalog`), add:

```python
@dataclass(frozen=True)
class DatasetSpec:
    dsn: str
    org: DatasetOrg
    key_offset: int = 0
    key_length: int = 0
    record_size: int = 0
```

Inside `DatasetCatalog`, add `allocate_new` after `allocate_ksds` (do NOT remove `allocate_ksds` yet — that happens in Task 3):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run --no-sync pytest tests/unit/test_catalog.py -v
```

Expected: all catalog tests PASS (including old `seed`, `allocate`, `dispose` tests — `allocate_ksds` still exists so nothing is broken)

- [ ] **Step 5: Commit**

```bash
git add jackal/catalog.py tests/unit/test_catalog.py
git commit -m "feat(catalog): DatasetSpec + allocate_new (generalises allocate_ksds)"
```

---

### Task 2: `open_dataset` access face

**Files:**
- Modify: `jackal/catalog.py`
- Modify: `tests/unit/test_catalog.py`

**Interfaces:**
- Consumes: `DatasetSpec`, `allocate_new` from Task 1; `open_driver` from `interpreter.cobol.file_drivers`; `FileOrganization`, `OpenMode` from `interpreter.cobol.file_enums`
- Produces: `DatasetCatalog.open_dataset(dsn: str, mode: OpenMode, record_size: int | None = None) -> FileOrganizationDriver`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_catalog.py`:

```python
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_open_dataset_ps_empty_returns_eof(tmp_path):
    from interpreter.cobol.access_result import AccessCondition
    from interpreter.cobol.file_enums import OpenMode
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    dd = DD("D", "J.FLAT", Disp(DispStatus.NEW, DispNormal.KEEP, DispNormal.DELETE))
    cat.allocate(dd)
    drv = cat.open_dataset("J.FLAT", OpenMode.INPUT, record_size=80)
    result = drv.read_seq()
    drv.close()
    assert result.condition is AccessCondition.END_OF_FILE


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_open_dataset_ksds_write_then_read(tmp_path):
    from interpreter.cobol.access_result import AccessCondition
    from interpreter.cobol.file_enums import OpenMode
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    spec = DatasetSpec(dsn="MY.KSDS", org=DatasetOrg.KSDS, key_offset=0, key_length=4, record_size=10)
    cat.allocate_new(spec)
    record = b"KEY DATA  "  # 10 bytes; key = first 4
    drv = cat.open_dataset("MY.KSDS", OpenMode.OUTPUT)
    drv.write(record)
    drv.close()
    drv2 = cat.open_dataset("MY.KSDS", OpenMode.INPUT)
    result = drv2.read_key(b"KEY ")
    drv2.close()
    assert result.condition is AccessCondition.OK
    assert result.data == record
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run --no-sync pytest tests/unit/test_catalog.py -v -k "open_dataset"
```

Expected: 2 failures — `AttributeError: 'DatasetCatalog' object has no attribute 'open_dataset'`

- [ ] **Step 3: Add `_ORG_MAP` and `open_dataset` to `catalog.py`**

Add the module-level map just before `class DatasetCatalog` (after `DatasetSpec`):

```python
_ORG_MAP: dict[DatasetOrg, FileOrganization] = {
    DatasetOrg.PS: FileOrganization.SEQUENTIAL,
    DatasetOrg.KSDS: FileOrganization.INDEXED,
}
```

Add `open_dataset` inside `DatasetCatalog`, after `allocate_new`:

```python
def open_dataset(
    self, dsn: str, mode: OpenMode, record_size: int | None = None
) -> FileOrganizationDriver:
    # record_size override exists solely as a jackal-ifq workaround: PS inputs
    # allocated via allocate(dd) carry record_size=0; callers that know the true
    # record size (e.g. REPRO borrowing the output KSDS value) pass it here.
    # Remove this parameter and all call sites that supply it when jackal-ifq is fixed.
    ds = self._datasets[dsn]
    rl = record_size if record_size is not None else ds.record_size
    return open_driver(_ORG_MAP[ds.org], ds.path, mode, rl, ds.key_offset, ds.key_length)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run --no-sync pytest tests/unit/test_catalog.py -v
```

Expected: all catalog tests PASS

- [ ] **Step 5: Commit**

```bash
git add jackal/catalog.py tests/unit/test_catalog.py
git commit -m "feat(catalog): open_dataset — org-dispatched access face (jackal-vxb)"
```

---

### Task 3: Wire executor, delete `allocate_ksds`, verify full suite

**Files:**
- Modify: `jackal/idcams/executor.py`
- Modify: `jackal/catalog.py` (delete `allocate_ksds`)

**Interfaces:**
- Consumes: `allocate_new`, `open_dataset` from Tasks 1–2
- Produces: no new public API — this task removes `allocate_ksds` and `open_driver` from the executor

- [ ] **Step 1: Update `executor.py` imports**

Replace the current import block at the top of `jackal/idcams/executor.py` with:

```python
from __future__ import annotations

from collections.abc import Sequence

from interpreter.cobol.access_result import AccessCondition
from interpreter.cobol.file_enums import OpenMode

from jackal.catalog import DatasetCatalog, DatasetSpec
from jackal.idcams.commands import Command, DefineCluster, Delete, IfMaxcc, Repro
from jackal.model import DD, DatasetOrg
```

(Removed: `open_driver` from `file_drivers`, `FileOrganization` from `file_enums`. Added: `DatasetSpec` from `jackal.catalog`, `DatasetOrg` from `jackal.model`.)

- [ ] **Step 2: Update `_handle_define_cluster`**

Replace the body of `_handle_define_cluster`:

```python
def _handle_define_cluster(cmd: DefineCluster, catalog: DatasetCatalog) -> int:
    catalog.allocate_new(DatasetSpec(
        dsn=cmd.name,
        org=DatasetOrg.KSDS,
        key_offset=cmd.key_offset,
        key_length=cmd.key_length,
        record_size=cmd.record_size,
    ))
    return 0
```

- [ ] **Step 3: Update `_handle_repro`**

Replace the body of `_handle_repro`:

```python
def _handle_repro(
    cmd: Repro,
    dds_by_ddname: dict[str, DD],
    catalog: DatasetCatalog,
) -> int:
    infile_dd = dds_by_ddname[cmd.infile_dd]
    outfile_dd = dds_by_ddname[cmd.outfile_dd]

    in_ds = catalog.allocate(infile_dd)
    out_ds = catalog.resolve(outfile_dd.dsn)

    # jackal-ifq workaround: PS input has record_size=0 (no DCB info at allocation time);
    # pass the output KSDS record_size as override. Remove when jackal-ifq is fixed.
    in_drv = catalog.open_dataset(in_ds.dsn, OpenMode.INPUT, record_size=out_ds.record_size)
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

- [ ] **Step 4: Delete `allocate_ksds` from `catalog.py`**

Remove the entire `allocate_ksds` method from `jackal/catalog.py` (currently lines 65-79):

```python
    def allocate_ksds(
        self, dsn: str, key_offset: int, key_length: int, record_size: int
    ) -> Dataset:
        path = self._workdir / dsn.replace(".", "_")
        path.write_bytes(b"")
        ds = Dataset(
            dsn=dsn,
            path=path,
            org=DatasetOrg.KSDS,
            key_offset=key_offset,
            key_length=key_length,
            record_size=record_size,
        )
        self._datasets[dsn] = ds
        return ds
```

- [ ] **Step 5: Run the full test suite**

```bash
uv run --no-sync pytest tests/ -v
```

Expected: all tests PASS. In particular:
- `tests/unit/test_catalog.py` — all 10 tests pass
- `tests/unit/test_idcams_executor.py` — `test_repro_loads_ps_into_ksds` passes
- `tests/integration/test_carddemo_acctfile_e2e.py` — e2e REPRO test passes

- [ ] **Step 6: Confirm no `allocate_ksds` or `open_driver` remains in `jackal/`**

```bash
grep -rn "allocate_ksds\|open_driver\|FileOrganization" jackal/ --include="*.py"
```

Expected: no output (zero matches)

- [ ] **Step 7: Commit**

```bash
git add jackal/catalog.py jackal/idcams/executor.py
git commit -m "refactor(catalog): wire executor through open_dataset; delete allocate_ksds (jackal-vxb)"
```
