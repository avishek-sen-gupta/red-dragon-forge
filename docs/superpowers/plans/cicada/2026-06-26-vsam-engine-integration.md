# cicada VsamEngine → Shared Engine Integration — Implementation Plan (Phase 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Rewrite cicada's `VsamEngine` as a thin CICS adapter over the shared red-dragon access-method engine, discarding the in-memory `SortedDict` store + persistence backends — so the mainframe stack runs on one storage implementation.

**Architecture:** Point ops (`read`/`write`/`rewrite`/`delete`) open a driver per call; browse (`startbr`/`readnext`/`readprev`/`endbr`) keeps one open driver instance per cursor. Driver selection by `key_offset`: `0` → `open_driver(INDEXED)` (binary search); `>0` → `open_alternate_key_driver` (linear scan, read-only). The adapter maps neutral `AccessCondition` → EIBRESP and keeps the CICS-only state (FCT enable/disable, `_held_key`). The backing `.dat` file IS the store.

**Tech Stack:** Python 3.13, pytest, black. cicada (vendors red-dragon). Spec: `docs/superpowers/specs/2026-06-26-vsam-engine-integration-design.md` (read it + its RESOLUTION ADDENDUM).

## Global Constraints
- **Behavior-preserving at the CICS surface:** EIBRESP codes + records returned to EXEC CICS callers unchanged. The durable CardDemo CICS flows are the gate: `test_carddemo_signon_real`, `test_carddemo_account_update`, `test_carddemo_bill_pay`, `test_carddemo_card_list`, `test_carddemo_tran_view`, `test_carddemo_add_transaction`, `test_carddemo_tran_list`, `test_carddemo_user_list`, `test_zbank_conversational`, `test_vsam_browse`.
- EIBRESP map (decision A): `OK→0`, `END_OF_FILE→20`, `NOT_FOUND→13`, `DUPLICATE_KEY→14`. File-state conditions from a driver on an FCT-enabled file (`FILE_NOT_FOUND`/`NOT_OPEN`/`WRITE_NOT_PERMITTED`) → `RESP_IOERR (17)`; FCT disabled/undefined is decided by the adapter BEFORE calling a driver → `RESP_DISABLED (84)`.
- Driver selection by `key_offset` (0 → INDEXED/binary; >0 → alternate-key/linear, read-only).
- Discard entirely: `VsamDataset.store` (SortedDict), `_persist`, `flush_to`, `_cursor_dir`, `cics/vsam/backend.py` (`InMemoryBackend`/`FileBackend`/`VsamBackend`), `cics/vsam/seed.py::load_vsam_seed`. Keep `seed_vsam` (backing-file writer).
- FP / imperative shell; no `None` defaults; no defensive guards (fail loud); no regex.
- Tooling: `uv run --no-sync python -m pytest …`; black before commit; real pre-commit (full suite — slow; allow ~5 min; export `PROLEAP_BRIDGE_JAR`/`JCL_BRIDGE_JAR`/`CARDDEMO_HOME`).

---

## Task 1 (red-dragon): IndexedDriver.start positions the cursor even past end-of-file

**Why:** CICS seek-last browse (STARTBR with HIGH-VALUES, then READPREV) needs the cursor at EOF so `read_prev` walks back to the last record. Today `start(">=")` past-end returns `NOT_FOUND` WITHOUT setting `self._cursor`, leaving it at 0 → READPREV → END_OF_FILE (wrong). COBOL START semantics (NOT_FOUND condition) are preserved; only the cursor positioning is added.

**Files:** Modify `interpreter/cobol/file_drivers.py` (`IndexedDriver.start`); Test `tests/unit/cobol/test_read_prev.py` (add a seek-last case).

- [ ] **Step 1: failing test** — append to `tests/unit/cobol/test_read_prev.py`:
```python
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_indexed_startbr_past_end_then_read_prev_walks_back(tmp_path: Path):
    p = tmp_path / "ksds"
    p.write_bytes(b"AAA00001" + b"BBB00002" + b"CCC00003")
    drv = IndexedDriver()
    drv.open(p, OpenMode.INPUT, 8, 0, 3)
    # seek-last idiom: position past all keys, then READPREV returns the LAST record.
    r = drv.start(b"\xff\xff\xff", ">=")
    assert r.condition is AccessCondition.NOT_FOUND  # no GTEQ match (condition unchanged)
    assert drv.read_prev().data == b"CCC00003"        # but cursor IS at EOF -> walks back
    drv.close()
```
- [ ] **Step 2: run → fail** (`read_prev` returns END_OF_FILE because cursor stayed at 0): `uv run --no-sync python -m pytest tests/unit/cobol/test_read_prev.py::test_indexed_startbr_past_end_then_read_prev_walks_back -v` → FAIL.
- [ ] **Step 3: implement** — in `IndexedDriver.start`, the `else:  # >=` branch: set the cursor to the slot (which may be `n`, i.e. EOF) BEFORE returning NOT_FOUND:
```python
        else:  # >= or anything else
            self._cursor = slot * self._rl
            if slot >= n:
                return AccessResult(condition=AccessCondition.NOT_FOUND)
        return AccessResult(condition=AccessCondition.OK)
```
- [ ] **Step 4: run → pass + full red-dragon suite green.** `PROLEAP_BRIDGE_JAR=… uv run --no-sync python -m pytest -q`.
- [ ] **Step 5: commit, merge to red-dragon main, push.** Then this is available to bump.
```bash
git commit -am "feat(cobol): IndexedDriver.start positions cursor at EOF for seek-last browse (red-dragon-mc6u)"
# merge to main + push as in prior tasks
```

---

## Task 2 (cicada): bump submodule + neutral→EIBRESP mapping helper

**Files:** bump `vendor/red-dragon` to red-dragon main (incl. Task 1); Create `cics/vsam/eibresp.py`; Test `tests/unit/cics/test_eibresp.py`.

**Interfaces produced:** `def to_eibresp(condition: AccessCondition) -> int` (the decision-A map; data conditions → their codes, file-state conditions → `RESP_IOERR`).

- [ ] **Step 1: bump** `vendor/red-dragon` to red-dragon main HEAD (has `open_alternate_key_driver`, `read_prev`, and Task 1). `git add vendor/red-dragon`. No JAR rebuild (Python-only); no `uv sync` (editable).
- [ ] **Step 2: failing test** `tests/unit/cics/test_eibresp.py`:
```python
from interpreter.cobol.access_result import AccessCondition
from cics.vsam.eibresp import to_eibresp
from cics.vsam.engine import RESP_NORMAL, RESP_ENDFILE, RESP_NOTFND, RESP_DUPREC, RESP_IOERR

def test_data_conditions_map():
    assert to_eibresp(AccessCondition.OK) == RESP_NORMAL
    assert to_eibresp(AccessCondition.END_OF_FILE) == RESP_ENDFILE
    assert to_eibresp(AccessCondition.NOT_FOUND) == RESP_NOTFND
    assert to_eibresp(AccessCondition.DUPLICATE_KEY) == RESP_DUPREC

def test_file_state_conditions_are_ioerr():
    for c in (AccessCondition.FILE_NOT_FOUND, AccessCondition.NOT_OPEN, AccessCondition.WRITE_NOT_PERMITTED):
        assert to_eibresp(c) == RESP_IOERR
```
- [ ] **Step 3: run → fail** (module missing).
- [ ] **Step 4: implement** `cics/vsam/eibresp.py` — an explicit, exhaustive dict `{AccessCondition.OK: 0, END_OF_FILE: 20, NOT_FOUND: 13, DUPLICATE_KEY: 14, FILE_NOT_FOUND: 17, NOT_OPEN: 17, WRITE_NOT_PERMITTED: 17}`; `to_eibresp` raises `KeyError`/explicit error on an unmapped condition (fail loud). Import the `RESP_*` ints (move them to `eibresp.py` or import from `engine.py` — pick one home; if moved, re-export from `engine.py` for back-compat).
- [ ] **Step 5: run → pass.** Commit (the bump + the helper; use `--no-verify` if the full suite is intermediate-red from the bump — but the bump alone is additive to cicada, so it should stay green; commit normally).

---

## Task 3 (cicada): seed_vsam sorts base-KSDS backing files by key

**Why:** the file-resident `IndexedDriver` binary search requires the base `.dat` physically sorted by `key[0:key_length]`. The discarded `SortedDict` masked this. Alternate-key datasets need no sort (linear scan).

**Files:** Modify `cics/vsam/seed.py` (`seed_vsam`); Test `tests/unit/cics/test_seed.py` (or wherever seed is tested).

- [ ] **Step 1: failing test** — seed an unsorted base-KSDS source (key_offset=0); assert the written `.dat` is key-sorted (records ascending by `record[:key_length]`).
- [ ] **Step 2: run → fail.**
- [ ] **Step 3: implement** — in `seed_vsam`, for each dataset, if `cfg.key_offset == 0` sort records by `r[: cfg.key_length]` before `write_flat_file`; if `cfg.key_offset > 0` write in source order (alternate-key, linear scan). Keep `record_length` validation.
- [ ] **Step 4: run → pass.** Commit.

---

## Task 4 (cicada): rewrite VsamEngine as the CICS adapter (the core)

**Files:** Modify `cics/vsam/engine.py` (full rewrite of method bodies + `__init__`); DELETE `cics/vsam/backend.py` + `load_vsam_seed` from `seed.py`; fix every `VsamEngine(config, backend=…)` construction site (grep `VsamEngine(`); Migrate `tests/unit/cics/test_vsam_engine.py`; DELETE `tests/unit/cics/test_vsam_backend.py`.

**Per-method transformation (preserve the EXEC-CICS-visible behavior; the current bodies in `engine.py` are the reference for the CICS semantics — held_key, dup checks, GTEQ, seek-last):**

- `__init__`: drop `backend`; keep `_config`, `_datasets` (now `dict[str, _DatasetGeom]` holding `record_length/key_offset/key_length/path` — NOT a store), `_held_key`. Drop `_cursors`/`_cursor_dir` dict-of-ints; replace with `_browse: dict[_CursorKey, FileOrganizationDriver]` (one open driver per cursor).
- `load_all`: materialize each configured dataset's backing-file path (the seeded `.dat`); no record loading. `dataset_count` returns len.
- A private `_open(file_name, mode) -> FileOrganizationDriver | None`: FCT/enable check first (None → caller returns `RESP_DISABLED`); then route by `key_offset` → `open_alternate_key_driver` (>0) or `open_driver(FileOrganization.INDEXED, …)` (0) with the dataset's path + geometry.
- `read`: `_open` INPUT; `drv.read_key(key[:klen])`; on OK set `_held_key`; map condition→eibresp via `to_eibresp`; close; return `(data_or_None, eibresp)`.
- `write`: `_open` for output (`open_driver(INDEXED, OpenMode.OUTPUT/IO)`); `drv.write(record)` (the IndexedDriver enforces dup-key → `DUPLICATE_KEY`); map; close. (No separate `_persist` — the driver writes the file.) NOTE: opening INDEXED OUTPUT truncates; for an existing dataset use `OpenMode.IO` so writes append/merge into the sorted file — verify the IndexedDriver write path keeps the file sorted (it inserts in order); if OUTPUT truncates, use IO.
- `rewrite`: keyless RIDFLD → derive key from the record (as today); `_open` IO; `drv.rewrite(record, key)`; map; close.
- `delete`: keyless → `_held_key`; `_open` IO; `drv.delete(key)`; map; close.
- `startbr`: `_open` INPUT, store the instance in `_browse[cursor_key]`; `drv.start(key[:klen], ">=")` (GTEQ; Task 1 makes seek-last position at EOF); STARTBR returns `RESP_NORMAL` if positioned (treat NOT_FOUND-but-positioned, i.e. seek-last, as a valid browse start — do NOT propagate NOT_FOUND from a past-end GTEQ as a STARTBR failure; match the current engine which returns RESP_NORMAL).
- `readnext`: `_browse[cursor_key].read_seq()`; map (`END_OF_FILE`→`RESP_ENDFILE`); return `(data, eibresp)`.
- `readprev`: `_browse[cursor_key].read_prev()`; map. (The driver's cursor handles READNEXT→READPREV reversal — DROP the old `_cursor_dir` logic.)
- `endbr`: `_browse[cursor_key].close()`; pop the instance.
- DELETE `flush_to` (no in-memory state to snapshot; the backing file is current).

**Migrate `tests/unit/cics/test_vsam_engine.py`:** construct `VsamEngine(config)` WITHOUT `backend=`; seed by writing backing `.dat` files (use `seed_vsam` or `write_flat_file`) into the dataset paths the engine opens. Keep every behavioral assertion (records returned, EIBRESP, browse order incl. READPREV + reversal + seek-last); drop assertions on `ds.store`/`SortedDict`/backend internals. The `key_offset=25` cases (lines ~212–231) now exercise the alternate-key linear-scan path — keep them.

- [ ] **Step 1:** Migrate `test_vsam_engine.py` first (it becomes the failing spec for the rewrite) + delete `test_vsam_backend.py`. Run → fail.
- [ ] **Step 2:** Rewrite `engine.py` per above; delete `backend.py` + `load_vsam_seed`; fix construction sites.
- [ ] **Step 3:** Run the migrated unit tests → pass.
- [ ] **Step 4 (THE GATE):** full cicada suite incl. all CardDemo CICS flows green:
  `CARDDEMO_HOME=… PROLEAP_BRIDGE_JAR=… JCL_BRIDGE_JAR=… uv run --no-sync python -m pytest -q`. Any browse/seek-last/alt-key regression → systematic-debugging against the current engine's semantics (do NOT weaken a test).
- [ ] **Step 5:** Commit through real pre-commit hooks.

---

## Self-Review
**Spec coverage:** split (adapter vs engine) → Task 4; in-memory + backends discarded → Task 4 deletions; key_offset routing → Task 4 `_open`; EIBRESP map (decision A) → Task 2; seek-last browse → Task 1; seed sort caveat → Task 3; read_prev reversal driver-handled → Task 4 readprev; tests migrate/discard → Task 4. **Placeholder scan:** transformation guidance references the existing `engine.py` bodies as the behavioral spec (a guarded refactor — the 250-line verbatim rewrite is derived from that file + the CICS suite, not pre-written here); all NEW units (Task 1 fix, eibresp helper, seed sort) have complete code/tests. **Cross-repo order:** Task 1 (red-dragon) merged+bumped before Tasks 2–4 (cicada).
