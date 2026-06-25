# cicada VsamEngine → Shared Access-Method Engine Integration — Design

**Status:** Designed (2026-06-26). Brainstormed. Awaiting user review.

**Repos:** red-dragon (small engine prerequisite) + cicada (the bulk). cicada vendors
red-dragon; it bumps the submodule to pick up the prerequisite.

## What this builds (plain terms)
cicada's CICS file control currently runs on its own bespoke `VsamEngine` — an in-memory
`SortedDict` store with a pluggable persistence backend — which **duplicates** the KSDS logic
of red-dragon's shared `IndexedDriver`. This integration makes CICS file control use the
**shared access-method engine** instead, so the whole mainframe stack (jackal batch, cicada
CICS) runs on **one** storage implementation. `VsamEngine` becomes a thin **CICS adapter**:
its storage core delegates to the shared engine; its genuinely-CICS concerns (EIBRESP codes,
FCT enable/disable, last-read-for-update, task-scoped browse) stay on top.

## Driver (why now)
The shared engine just shipped (red-dragon `red-dragon-mc6u`), with jackal batch already on it.
cicada is the second consumer. Today the duplication is real: `VsamEngine` re-implements keyed
CRUD + browse that `IndexedDriver` already does, and the two only agree by sharing the on-disk
flat fixed-length-record format. Consolidating removes the duplicate and makes faithfulness a
single-place concern.

## Decisions locked in brainstorming
- **Canonical access model: file-resident** (the shared engine's drivers). cicada **adopts** it;
  its in-memory `SortedDict` model is **discarded**, not preserved behind the contract.
- **Discard the persistence backends** (`InMemoryBackend` + `FileBackend` write-through). The
  file-resident driver's **backing file IS the store** — there is no separate in-memory copy to
  persist. Seeding writes backing files the driver opens (cicada's `seed_vsam` already does this,
  in the same flat fixed-length format the drivers read).
- **Migrate or discard the in-memory backend's tests as needed** (see Testing).
- **RECFM: fixed-length only** (inherited from the engine; out of scope to change).

## The split: VsamEngine becomes a CICS adapter

| Concern (current `VsamEngine`) | Disposition |
|---|---|
| Record CRUD: `read`/`write`/`rewrite`/`delete` | → delegate to shared engine drivers (`read_key`/`write`/`rewrite`/`delete`) |
| Browse: `startbr`/`readnext`/`readprev`/`endbr` | → driver-instance-per-cursor (see below) |
| In-memory `SortedDict` store (`ds.store`) + `_persist`/`flush_to` | → **deleted** (backing file is the store) |
| `InMemoryBackend` / `FileBackend` (`backend.py`) | → **deleted** |
| EIBRESP codes (`RESP_NORMAL` … `RESP_IOERR`) | → adapter: map neutral `AccessCondition` → EIBRESP |
| FCT / enable-disable state, `_held_key` (keyless REWRITE/DELETE), task-scoped cursors | → **stay** in the adapter (never storage) |

The adapter's **public method signatures are unchanged** (`read`/`write`/`rewrite`/`delete`/
`startbr`/`readnext`/`readprev`/`endbr`/`load_all`/`dataset_count`, all returning EIBRESP ints) —
the EXEC CICS builtins that call them are untouched. Only the internals change.

## The browse model (the clean part)
Each CICS browse cursor `(task_id, file_name, cursor_id)` becomes **its own open driver
instance**, positioned by `start(key, ">=")` at STARTBR:
- `STARTBR(key)` → `open_driver(...)`, `start(key, ">=")` → maps neutral condition → EIBRESP.
- `READNEXT` → `read_seq()` (forward).
- `READPREV` → `read_prev()` (backward — the engine prerequisite below).
- `ENDBR` → `close()` and drop the instance.

The driver's internal cursor *is* the browse position; task-scoping falls out for free (one
instance per cursor). This replaces cicada's external between-records index + direction-reversal
bookkeeping — the file-resident cursor + `read_prev` provide the equivalent semantics directly.

## Prerequisite (red-dragon, small, behavior-additive)
The file-resident drivers have **no backward read** today — `IndexedDriver` has forward
`read_seq` (cursor `+= record_length`) and `start` positioning only. CICS `READPREV` needs
backward iteration. So, **first**, add `read_prev()` to the `FileOrganizationDriver` Protocol and
the drivers:
- Mirror of `read_seq`: move the cursor **back** one record (`cursor -= record_length`),
  bounds-checked; return the record at the new position, or `END_OF_FILE` at beginning-of-file.
- Forward I/O is **untouched** → behavior-additive; red-dragon's full suite stays green. Merged
  to red-dragon main and bumped into cicada before the cicada work.

## EIBRESP mapping (cicada adapter owns this table)
Neutral `AccessCondition` → EIBRESP, for the conditions the storage layer produces:
- `OK` → `RESP_NORMAL` (0)
- `END_OF_FILE` → `RESP_ENDFILE` (20)
- `NOT_FOUND` → `RESP_NOTFND` (13)
- `DUPLICATE_KEY` → `RESP_DUPREC` (14)

The remaining neutral conditions (`FILE_NOT_FOUND`, `NOT_OPEN`, `WRITE_NOT_PERMITTED`) are
**file-state** concerns the adapter already owns via FCT/enable-disable — in normal CICS flow
they arise from the adapter's own state checks (`RESP_DISABLED`, etc.), not from a storage op on
an open, enabled file. The mapping must be exhaustive (every neutral condition handled, fail loud
on an unmapped one), but these file-state conditions route to the adapter's existing FCT logic
rather than a storage-driven EIBRESP.

## Seeding (replaces in-memory load)
`load_all` currently loads records into the in-memory store via the backend. After the change,
seeding = ensuring each configured dataset has a **backing file** the driver opens:
- cicada's existing `seed_vsam(fct, data_dir, vsam_dir)` already writes flat fixed-length `.dat`
  files from the EBCDIC seed — that format is exactly what the file-resident driver reads.
- `load_all` becomes "materialize backing files for configured datasets" (or a no-op if the
  region is wired to seed up front); `dataset_count` reflects configured/seeded datasets.
- `flush_to` is **removed** — there is no in-memory state to flush; the backing file is current.

## Components
1. **red-dragon `interpreter/cobol/file_drivers.py`** — add `read_prev()` to the Protocol + the
   drivers (KSDS at minimum; the others mirror it for contract completeness).
2. **cicada `cics/vsam/engine.py`** — rewrite `VsamEngine` as the CICS adapter over `open_driver`:
   per-call drivers for CRUD, per-cursor driver instances for browse, EIBRESP mapping, `_held_key`
   + FCT preserved; delete `ds.store`/`_persist`/`flush_to`.
3. **cicada `cics/vsam/backend.py`** — **deleted** (`InMemoryBackend`/`FileBackend`/`VsamBackend`).
4. **cicada `cics/vsam/seed.py`** — keep `seed_vsam` (backing-file writer); drop `load_vsam_seed`
   (the InMemoryBackend dict path) and its `_read_seed` half if unused.
5. **cicada construction site(s)** — wherever `VsamEngine(config, backend=…)` is built, drop the
   backend arg; wire the workdir/vsam_dir the drivers open from.

## Error handling
- Fail loud on an unmapped neutral condition (the EIBRESP table is exhaustive and explicit).
- No `None` defaults; frozen where applicable; FP core / imperative shell; no regex.
- A genuinely missing/corrupt backing file surfaces as a real condition (the adapter maps to the
  appropriate CICS resp), not a silent empty read.

## Testing (TDD; behavior-preservation is the gate)
- **The guard:** cicada's durable CardDemo CICS integration flows must stay green — `test_carddemo_
  signon_real`, `test_carddemo_account_update`, `test_carddemo_bill_pay`, `test_carddemo_card_list`,
  `test_carddemo_tran_view`, `test_carddemo_user_add`, `test_zbank_conversational`. These exercise
  real READ/REWRITE/WRITE/browse through the CICS surface — they are the proof the storage swap
  changed no CICS-visible behavior.
- **`tests/unit/cics/test_vsam_engine.py`** — **migrate** to assert the adapter's CICS behavior
  (read/write/rewrite/delete/browse + EIBRESP) over the file-resident store, not the in-memory
  internals. Keep the behavioral assertions (correct records, correct EIBRESP, browse order incl.
  READPREV + READNEXT→READPREV reversal); drop assertions on `ds.store`/`SortedDict`/backend internals.
- **`tests/unit/cics/test_vsam_backend.py`** — **discard** (the backends it tests are deleted).
  Migrate any still-meaningful assertion (e.g. seed round-trip through `seed_vsam`) into a seed test
  if not already covered elsewhere.
- **`tests/unit/cics/test_vsam_builtins.py`** — EXEC CICS verb level; expected to stay green
  unchanged (public adapter contract preserved). Run as a guard; do not rewrite.
- **red-dragon:** unit test `read_prev` (backward scan returns records in reverse; `END_OF_FILE` at
  BOF; forward `read_seq` unaffected); full red-dragon suite green (behavior-additive).

## Constraints
- **Behavior-preserving at the CICS surface:** EIBRESP codes and record results returned to EXEC
  CICS callers are unchanged; cicada's CICS suite is the gate.
- FP / frozen where applicable; no `None` defaults; no defensive guards (fail loud); no regex.
- red-dragon stays language-agnostic (the engine knows records + conditions, never "EIBRESP"/"FCT").
- Cross-repo order: red-dragon `read_prev` merged + bumped first, then cicada.

## Risks
- **Deleting the in-memory store is a real behavioral swap.** In-transaction visibility is
  preserved (file-resident writes are immediately visible, same as the old write-through), but only
  cicada's CICS suite can vouch for the full semantics — run it as the gate, and treat any CardDemo
  flow regression as a storage-swap bug (systematic-debugging), not a test to weaken.
- **Browse reversal semantics.** The READNEXT→READPREV reversal cicada handles via an external
  direction flag must be reproduced by the `read_prev` cursor semantics. The `read_prev` spec + a
  focused reversal test pin this; the CardDemo browse flows (card list, tran view) are the e2e witness.
- **Multiple concurrent browse cursors** on one file now mean multiple open driver instances on the
  same backing file (read-only positioning). Confirm the driver permits concurrent read opens (it
  opens `rb`/`r+b`); no cross-cursor interference since each instance owns its cursor.
- **Per-call driver opens** for CRUD (open→op→close per read/write) is more file-open churn than the
  in-memory store. Acceptable for fidelity/correctness; note it, optimize only if a flow is measurably slow.

## Bookkeeping
- This is the **cicada `VsamEngine` merge** follow-on under red-dragon epic `red-dragon-mc6u`
  ("cicada VsamEngine merge + CICS adapter"). The `read_prev` prerequisite is a red-dragon change.
- Deferred (unchanged): jackal catalog (`jackal-vxb`); ESDS/AIX/PDS drivers; observability/tracing;
  fidelity hardening (DCB/LRECL, `jackal-1o2.12`/`jackal-ifq`).
