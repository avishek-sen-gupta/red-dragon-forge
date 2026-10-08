# jackal-vxb: Dataset Catalog — Generalized Allocation + Access Face

**Date:** 2026-06-27  
**Issue:** jackal-vxb  
**Status:** Design approved (post-interview)

---

## Context

The red-dragon shared access-method engine is complete (as of vendor commit `7fa7834e`):
- `interpreter/cobol/access_result.py` — neutral `AccessResult`/`AccessCondition`
- `interpreter/cobol/file_drivers.py` — `FileOrganizationDriver` Protocol + `open_driver()` factory
- `interpreter/cobol/real_file_provider.py` — COBOL adapter mapping `AccessCondition` → FILE STATUS

This unblocks jackal-vxb. The re-scoped goal is **catalog only**: generalize allocation and add an access face. GDG generation resolution and PDS member resolution are deferred to `jackal-1o2.4` and `jackal-1o2.16` respectively.

### The two leaks being closed

1. **Allocation sprawl**: `DatasetCatalog.allocate_ksds()` is KSDS-specific. Adding RRDS, ESDS, GDG, or PDS would each require a new `allocate_*` method.
2. **Direct driver import**: `idcams/executor.py` calls `open_driver()` directly, hardcoding `FileOrganization.SEQUENTIAL` for the input dataset in REPRO, bypassing the catalog's knowledge of dataset org.

---

## Design Decisions (from interview)

| # | Decision |
|---|---|
| 1 | `DatasetSpec` lives in `catalog.py` — it's a catalog input type, not a JCL model type |
| 2 | `RRDS`/`ESDS` NOT added to `DatasetOrg` now — wait until `jackal-1o2.21` needs them (YAGNI) |
| 3 | `allocate_new` raises `ValueError` if DSN is already registered |
| 4 | `allocate_new` validates `record_size > 0` and `key_length > 0` for KSDS — fail loud at allocation, not in `DatasetSpec.__post_init__` |
| 5 | `allocate_new` silently wipes pre-existing disk files (same as `allocate_ksds`) |
| 6 | `open_dataset` takes `dsn: str` — catalog is the single owner |
| 7 | `open_dataset` uses explicit `close()` by caller — no context manager |
| 8 | `record_size` override in `open_dataset` is a `jackal-ifq` workaround only — must be removed when that bug is fixed |
| 9 | `allocate_ksds` deleted; `seed()` kept (active caller in `runner.py`) |
| 10 | `open_driver` and `FileOrganization` imports removed from `idcams/executor.py`; `OpenMode` stays |

---

## Design

### 1. `DatasetSpec` (new, in `jackal/catalog.py`)

```python
@dataclass(frozen=True)
class DatasetSpec:
    dsn: str
    org: DatasetOrg
    key_offset: int = 0
    key_length: int = 0
    record_size: int = 0
```

Plain data carrier — no validation in `__post_init__`. Validation lives in `allocate_new`.

---

### 2. `DatasetCatalog.allocate_new(spec: DatasetSpec) -> Dataset`

Replaces `allocate_ksds`. Raises `ValueError` in two cases:
- DSN already registered in `_datasets`
- `spec.org is DatasetOrg.KSDS` and (`spec.record_size == 0` or `spec.key_length == 0`)

Otherwise: creates backing file at `self._workdir / spec.dsn.replace(".", "_")`, wipes any pre-existing content, populates all `Dataset` fields from the spec, registers in `_datasets`, returns the `Dataset`.

`allocate_ksds` is deleted. Its only production caller (`idcams/executor.py:_handle_define_cluster`) is updated here.

---

### 3. `DatasetCatalog.open_dataset(dsn, mode, record_size=None) -> FileOrganizationDriver`

Module-level org map (only orgs currently in `DatasetOrg`):

```python
_ORG_MAP = {
    DatasetOrg.PS:   FileOrganization.SEQUENTIAL,
    DatasetOrg.KSDS: FileOrganization.INDEXED,
}
```

Unknown org → `KeyError` (fail loud; no defensive guard).

Implementation:
```python
def open_dataset(
    self, dsn: str, mode: OpenMode, record_size: int | None = None
) -> FileOrganizationDriver:
    # record_size override exists solely as a jackal-ifq workaround: PS inputs
    # allocated via allocate(dd) carry record_size=0; callers that know the true
    # record size (e.g. REPRO borrowing the output KSDS value) pass it here.
    # Remove this parameter and all call sites that supply it when jackal-ifq is fixed.
    ds = self._datasets[dsn]
    org = _ORG_MAP[ds.org]
    rl = record_size if record_size is not None else ds.record_size
    return open_driver(org, ds.path, mode, rl, ds.key_offset, ds.key_length)
```

`catalog.py` gains imports: `from interpreter.cobol.file_drivers import open_driver, FileOrganizationDriver` and `from interpreter.cobol.file_enums import FileOrganization, OpenMode`.

---

### 4. `idcams/executor.py` changes

**`_handle_define_cluster`:**
```python
catalog.allocate_new(DatasetSpec(
    dsn=cmd.name,
    org=DatasetOrg.KSDS,
    key_offset=cmd.key_offset,
    key_length=cmd.key_length,
    record_size=cmd.record_size,
))
```

**`_handle_repro`:**
```python
in_ds = catalog.allocate(infile_dd)
out_ds = catalog.resolve(outfile_dd.dsn)
# jackal-ifq workaround: PS input has record_size=0 (no DCB info at allocation time);
# pass the output KSDS record_size as override. Remove when jackal-ifq is fixed.
in_drv = catalog.open_dataset(in_ds.dsn, OpenMode.INPUT, record_size=out_ds.record_size)
out_drv = catalog.open_dataset(out_ds.dsn, OpenMode.OUTPUT)
```

Imports removed: `open_driver`, `FileOrganization`.  
Imports added: `DatasetSpec` from `jackal.catalog`.  
`OpenMode` stays (still used in `open_dataset` calls).

---

### 5. Test changes (`tests/unit/test_catalog.py`)

- **Update** `test_allocate_ksds` → use `allocate_new(DatasetSpec(...))` instead
- **Add** `test_allocate_new_duplicate_dsn_raises` — same DSN twice → `ValueError`
- **Add** `test_allocate_new_ksds_zero_record_size_raises` — `record_size=0`, `org=KSDS` → `ValueError`
- **Add** `test_allocate_new_ksds_zero_key_length_raises` — `key_length=0`, `org=KSDS` → `ValueError`
- **Add** `test_open_dataset_ps` — allocate PS, open INPUT, read returns `AccessCondition.END_OF_FILE` on empty file
- **Add** `test_open_dataset_ksds` — `allocate_new` a KSDS, `open_dataset` OUTPUT, write one record, close; reopen INPUT, `read_key` returns it

---

## Out of scope

| Topic | Tracked in |
|---|---|
| GDG generation resolution | `jackal-1o2.4` |
| PDS/PDSE member resolution | `jackal-1o2.16` |
| ESDS/RRDS org + driver usage | `jackal-1o2.21` |
| DCB attributes (LRECL/RECFM) at allocation | `jackal-1o2.12` |
| REPRO LRECL fix (PS input record_size) | `jackal-ifq` |
| Observability/tracing | deferred in epic notes |

---

## Verification

```bash
export PROLEAP_BRIDGE_JAR="$(pwd)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar"
export JCL_BRIDGE_JAR="$(pwd)/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar"
export CARDDEMO_HOME="$HOME/code/aws-mainframe-carddemo/app"
uv run --no-sync pytest tests/
```

Post-implementation checks:
- No `open_driver` or `FileOrganization` import remains in `jackal/idcams/executor.py`
- No `allocate_ksds` call remains anywhere in `jackal/` (method deleted from `catalog.py`)
- All five new catalog tests pass
