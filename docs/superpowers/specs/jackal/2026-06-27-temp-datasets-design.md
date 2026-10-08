# jackal — Temporary Datasets (&&NAME) — Design

**Status:** Designed (2026-06-27). Tracks `jackal-1o2.11` (label `jcl-language`).

## What this builds

Honor `&&NAME` temporary datasets in JCL — datasets that live for the duration of a
job and are automatically deleted at job end. A step creates one with
`DISP=(NEW,PASS)`, subsequent steps reference it with `DISP=(OLD,...)`, and the
catalog cleans up any survivors at job end.

Example:
```jcl
//STEP1  EXEC PGM=SORT
//SORTOUT DD DSN=&&WORKIN,DISP=(NEW,PASS)

//STEP2  EXEC PGM=CBACT04C
//INPUT  DD DSN=&&WORKIN,DISP=(OLD,DELETE)
```

Multi-step PASS chains are fully supported: `&&WORKIN` survives as many steps as
needed until explicitly DELETEd or job end.

## Out of scope

- Backward references (`DSN=*.STEP.DD`) — deferred to `jackal-1o2.10`. The DSN
  type hierarchy introduced here (`DirectDSN | TempRef`) leaves a clean slot for a
  third `BackwardRef` variant when that issue is implemented.
- DCB attributes on temp datasets — deferred to `jackal-1o2.12`.

## DSN type hierarchy

New file `jackal/dsn.py`:

```python
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class DirectDSN:
    name: str

@dataclass(frozen=True)
class TempRef:
    alias: str  # full &&NAME string, e.g. "&&WORKIN"

type DSN = DirectDSN | TempRef
```

`DD.dsn` changes from `str` to `DSN`. The bridge parser constructs `TempRef` when the
raw JSON `dsn` string starts with `&&`, `DirectDSN` otherwise. All existing consumers
of `dd.dsn` as a string become `dd.dsn.name` (guarded by `isinstance` or `match` as
appropriate).

## Components

### 1. `jackal/dsn.py` (new)

Pure dataclasses — `DirectDSN`, `TempRef`, and the `DSN` union alias. No logic.

### 2. `jackal/model.py`

`DD.dsn` type changes from `str` to `DSN` (imported from `jackal.dsn`).

### 3. `jackal/jcl/bridge_parser.py`

`_dd_from_json` constructs the correct DSN variant:

```python
raw_dsn = d.get("dsn", "")
dsn: DSN = TempRef(raw_dsn) if raw_dsn.startswith("&&") else DirectDSN(raw_dsn)
```

### 4. `jackal/catalog.py`

**New internal state:** `_temp_registry: dict[str, DirectDSN]` — maps `&&NAME`
aliases to their resolved `DirectDSN`. Populated at `NEW` allocation, cleared by
`cleanup_temps()`.

**`allocate(dd)`** dispatches on `dd.dsn` type:

| `dd.dsn` type | `disp.status` | behaviour |
|---|---|---|
| `DirectDSN` | any | existing logic unchanged |
| `TempRef` | `NEW` | create backing file in workdir (name = `alias[2:]`, stripping exactly the two leading `&&`), register `alias → DirectDSN(name)` in `_temp_registry`, return `Dataset` |
| `TempRef` | `OLD`/`SHR` | look up `_temp_registry[alias]`; if absent raise `KeyError(alias)` immediately |
| `TempRef` | `MOD` | resolve via registry (raise if absent); extend or create |

**`dispose(dd)`** dispatches on `dd.dsn` type:

| `dd.dsn` type | `disp.normal` | behaviour |
|---|---|---|
| `DirectDSN` | `DELETE` | existing `delete_dsn` logic |
| `TempRef` | `DELETE` | resolve alias via `_temp_registry`; `delete_dsn(resolved.name)`; remove alias from `_temp_registry` |
| `TempRef` | `PASS`/`KEEP`/`CATLG` | no-op — dataset survives to job end |

**`cleanup_temps()`** — new public method:
```python
def cleanup_temps(self) -> None:
    for dsn in list(self._temp_registry.values()):
        self.delete_dsn(dsn.name)   # missing_ok — may already be DELETEd
    self._temp_registry.clear()
```

### 5. `jackal/runner.py`

`run_job()` calls `catalog.cleanup_temps()` unconditionally after the step loop
(whether the job succeeded, failed, or had bypassed steps):

```python
for step in job.steps:
    ...
catalog.cleanup_temps()
return JobResult(steps=tuple(results))
```

### 6. Callers of `dd.dsn` as a raw string

Every site that currently reads `dd.dsn` as a string must be updated to resolve
through the DSN type. Primary sites: `catalog.allocate()`, `catalog.dispose()`,
`catalog.seed()` call sites, `idcams/executor.py`, `utilities.py`, any test
fixtures that construct `DD(dsn="...")` directly.

`DD(dsn="...")` in tests and fixtures becomes `DD(dsn=DirectDSN("..."))`.

## Data flow

```
JCL:   DSN=&&WORKIN,DISP=(NEW,PASS)
  --(bridge)--> {"dsn": "&&WORKIN", "disp_words": ["NEW","PASS"]}
  --> DD(dsn=TempRef("&&WORKIN"), disp=Disp(NEW, PASS, PASS))

catalog.allocate(dd):
  TempRef → backing path = workdir / "WORKIN"
  _temp_registry["&&WORKIN"] = DirectDSN("WORKIN")
  _datasets["WORKIN"] = Dataset(dsn="WORKIN", path=workdir/"WORKIN")
  returns Dataset

catalog.dispose(dd):  [PASS — no-op, dataset survives]

--- next step ---

catalog.allocate(DD(dsn=TempRef("&&WORKIN"), disp=Disp(OLD, DELETE, ...))):
  resolves "&&WORKIN" → DirectDSN("WORKIN") via _temp_registry
  returns existing Dataset

catalog.dispose(dd):  [DELETE]
  delete_dsn("WORKIN") → file removed, removed from _datasets
  _temp_registry.pop("&&WORKIN")

--- job end ---

catalog.cleanup_temps():
  _temp_registry is already empty (all explicitly DELETEd)
  → no-op
```

## Error handling

- `TempRef` + `OLD`/`SHR` with no prior `NEW` → `KeyError(alias)` raised immediately
  in `catalog.allocate()`. Does not defer to file-open time.
- `cleanup_temps()` calls `delete_dsn()` which uses `missing_ok=True` — datasets
  already DELETEd mid-job are silently skipped.
- No `&&` dataset survives past `cleanup_temps()` — the workdir is left clean.

## Testing

**Unit — `jackal/dsn.py`:**
- `DirectDSN("MY.DS").name == "MY.DS"`
- `TempRef("&&WORKIN").alias == "&&WORKIN"`

**Unit — bridge parser:**
- `dsn="&&WORKIN"` → `TempRef("&&WORKIN")`
- `dsn="MY.DS"` → `DirectDSN("MY.DS")`
- absent `dsn` → `DirectDSN("")`

**Unit — catalog:**
- Allocate `TempRef` with `NEW` → backing file created, registry populated
- Allocate same `TempRef` with `OLD` → same `Dataset` returned
- Allocate `TempRef` with `OLD` never previously `NEW`-allocated → `KeyError`
- `dispose` with `DELETE` → file deleted, alias removed from registry
- `dispose` with `PASS` → file survives, alias remains in registry
- `cleanup_temps()` deletes surviving temp files and clears registry
- `cleanup_temps()` is a no-op when all temps already DELETEd

**Integration — two-step job:**
- Step 1 writes `&&TEMP` (`NEW,PASS`); step 2 reads and deletes it (`OLD,DELETE`)
- After job: no temp files in workdir

**Integration — three-step PASS chain:**
- Step 1 creates `&&TEMP` (`NEW,PASS`); step 2 reads and passes (`OLD,PASS`); step 3 deletes (`OLD,DELETE`)
- All steps receive the same backing file; workdir clean after job

**Integration — missing temp dataset:**
- Step references `&&TEMP` with `OLD` but no prior step allocated it → job fails with `KeyError`

**Integration — job-end cleanup:**
- Step 1 creates `&&TEMP` (`NEW,PASS`); step 2 does NOT reference it
- After job: `cleanup_temps()` deletes the surviving file

## Binding constraints

- TDD: write failing tests first.
- `DD.dsn` is `DSN` (not `str`) everywhere — no raw-string fallback.
- `TempRef` + `OLD` with no prior allocation → `KeyError` immediately, not deferred.
- `uv run --no-sync` for all test runs.
- `make jar` not required — no Java changes.

## Bookkeeping

- `jackal-1o2.11` under epic `jackal-1o2`. Jackal-side only.
- Backward ref resolution (`DSN=*.STEP.DD`) deferred to `jackal-1o2.10`. The `DSN`
  union type introduced here accommodates a future `BackwardRef` variant.
