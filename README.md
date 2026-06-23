# Cicada

**Cicada** is a CICS runtime built on top of [RedDragon](vendor/red-dragon/README.md) — the
multi-language interpreter. It emulates the **CICS online tier** closely enough to run **real,
unmodified COBOL programs** end-to-end: pseudo-conversational transaction dispatch, VSAM KSDS
file control, and BMS screen handling. The reference workload is the Apache-licensed
`aws-mainframe-carddemo` online tier; sign-on, menu, account view/update, and transaction add
all execute through the pipeline described here.

RedDragon is included as an editable submodule at `vendor/red-dragon`, so its source can be
read and modified in place.

---

## Setup

**Prerequisites:** Python ≥ 3.10, [uv](https://docs.astral.sh/uv/), JDK 17+ and Maven (for
the ProLeap COBOL bridge).

```bash
git clone --recurse-submodules <repo>
cd cicada

# Python dependencies (installs red-dragon from vendor/ in editable mode)
uv sync

# ProLeap COBOL bridge (required for COBOL compilation and integration tests)
cd vendor/red-dragon/proleap-bridge && ./build.sh && cd -
# Produces: vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
```

## Tests

```bash
uv run python -m pytest tests/unit/ -x -q        # unit tests (no JAR required)
uv run python -m pytest tests/integration/ -x -q # integration tests (needs ProLeap JAR)
```

---

## Architecture overview

A hard invariant underlies all of cicada: **nothing in this repo touches RedDragon's core
engine.** There are zero edits to `interpreter/vm/**`, `ir.py`, `run.py`, `executor.py`, or
`cfg.py`. Every CICS-specific behaviour reaches the VM only through `CallFunction` IR to
registered builtins — the same mechanism any language frontend uses.

```
cics/
  strategy.py          # CicsLoweringStrategy — injected into CobolFrontend
  preprocessor.py      # apply_cics_prepass (inject_dfheiblk)
  dfhresp_prepass.py   # DFHRESP ASG pre-pass
  dispatcher.py        # CicsRegion, run_cics, _advance_routing
  bootstrap.py         # compile_cics_program, run_carddemo_region
  types.py             # CicsContext, DispatchResult, DispatchKind
  terminal.py          # ScreenChannel / InputChannel protocols
  le_stubs.py          # IBM LE service stubs (CEEDAYS, etc.)
  builtins/            # CICS service builtins: flow, screen, system, vsam
  vsam/                # VsamEngine, backends, flat-file codec, dump CLI
  bms/                 # BMS symbolic map generation (bms-tools pipeline)
```

RedDragon contributes one thin seam that lives in its COBOL layer:

- `interpreter/cobol/exec_cics_strategy.py` — `ExecCicsStrategy` protocol + `CatchAllLoweringStrategy` null object

The EXEC CICS parser lives in cicada (not in RedDragon):

- `cics/cics_grammar/` — ANTLR4 grammar (`CICSzParser.g4`, `CICSzLexer.g4`)
- `cics/cics_visitor.py` — ANTLR visitor: grammar parse tree → `(verb, {OPTION: CicsOperand | None})`

`CobolFrontend` accepts an injectable `CicsTextParser` seam; cicada supplies the ANTLR implementation at construction time.

---

## 1. The CICS pre-pass and compilation phases

### 1.1 Normal COBOL pipeline (RedDragon)

```
source bytes
   │  ProLeapCobolParser.parse  (Java bridge → JSON ASG)
   ▼
CobolASG  (data_fields, procedure statements, …)
   │  CobolFrontend.lower  (statement_dispatch → IR per statement)
   ▼
IR instruction list
   │  build_cfg → build_registry
   ▼
CFG + registry
   │  run_linked  (VM execution)
   ▼
result
```

`EXEC CICS … END-EXEC` is an opaque envelope to ProLeap — it does not parse the CICS verb or
options. CICS support therefore splits into a **text pre-pass** (before ProLeap) and a
**lowering strategy** (during frontend lowering).

### 1.2 Pre-pass — `cics/preprocessor.py`

`apply_cics_prepass(source: str) -> str` runs before ProLeap sees the source:

- **`inject_dfheiblk`** — inserts `COPY DFHEIBLK.` immediately after `WORKING-STORAGE SECTION.`
  so EIB references (`EIBRESP`, `EIBCALEN`, `EIBAID`, `EIBTRNID`) resolve to the real copybook.
  Detection uses a word-split (`line.strip().upper().split()`), not a regex.

There is no regex surgery anywhere in the CICS path. The pre-pass exists only because ProLeap
cannot inject DFHEIBLK itself; everything else is structural.

### 1.3 EXEC CICS as a structured statement

When ProLeap surfaces an `EXEC CICS` block, the COBOL frontend builds an `ExecCicsStatement`
from the block's raw text. `ExecCicsStatement.from_dict` calls
**`parse_exec_cics_text(text) -> (verb, {OPTION: CicsOperand | None})`** from RedDragon's
`interpreter.cobol.cics_parser`.

The grammar (ANTLR4):

- Verb is a grammar construct — single word or a small set of compound verbs (`SEND MAP`,
  `RECEIVE MAP`, `WRITEQ TD`, `HANDLE ABEND/CONDITION/AID`) — not Python string-joining.
- Each option value is a `CicsOperand(text, is_literal, subscripts, ref_mod_start, ref_mod_length)`.
  `is_literal` is set structurally when the grammar matched a quoted `ARG_STRING` terminal.
- Multi-word values such as `LENGTH OF WS-CA` arrive as a single operand with the full text
  preserved — `cics/strategy.py` inspects the `text` where needed (e.g., `_resolve_cics_length_option`).

**Comment lines inside EXEC CICS blocks** are filtered in the ProLeap fork's
`TagUtils.getExecCicsText` — any token whose untagged text starts with `*>` is skipped before
the string reaches the Python CICS parser.

### 1.4 DFHRESP structural lowering — `cics/dfhresp_prepass.py` + bridge grammar

`DFHRESP(condition)` (e.g. `IF WS-RC = DFHRESP(PGMIDERR)`) maps a symbolic condition to a
numeric EIBRESP code.

**Bridge side** — the ProLeap grammar reorders `literal | identifier` in `basis`/`evaluateValue`
rules so `DFHRESP(X)` is tried as `cicsDfhRespLiteral` first, emitted as
`{"kind": "dfhresp", "condition": "PGMIDERR"}`.

**Python side** — `CicsLoweringStrategy.preprocess_program_dict` delegates to
`resolve_dfhresp_nodes` (`cics/dfhresp_prepass.py`), a recursive walker that replaces every
`{"kind": "dfhresp", ...}` node with `{"kind": "lit", "value": "N"}` using the
`_DFHRESP_TABLE` in `preprocessor.py`. Generic COBOL lowering sees a plain numeric literal.

### 1.5 Lowering strategy — `cics/strategy.py`

`CobolFrontend` accepts an injected **`ExecCicsStrategy`** (from
`interpreter.cobol.exec_cics_strategy`). Two implementations:

- **`CatchAllLoweringStrategy`** (default, in RedDragon) — null object, logs a warning, emits
  no IR. Used by non-CICS COBOL compiles; the CICS machinery is inert unless opted in.
- **`CicsLoweringStrategy`** (in cicada) — registers CICS service builtins into the VM's
  `Builtins.TABLE` (closures over region runtime state), then translates each verb to IR.

Translation pattern: **each CICS verb lowers to a `CallFunction` to a registered builtin**
(`__cics_read`, `__cics_send_map`, `__cics_set_xctl_context`, …).

`on_procedure_entry` emits a single `CallFunction __cics_init_eib`.

| Verb family | Verbs | Lowers to |
|---|---|---|
| Flow control | `RETURN [TRANSID][COMMAREA]`, `XCTL PROGRAM COMMAREA`, `ABEND` | `__cics_set_return_context` / `__cics_set_xctl_context` / `__cics_abend`, then `Return_` |
| Program link | `LINK PROGRAM COMMAREA [LENGTH] [RESP]` | `__cics_link` (synchronous sub-call; see §2.3) |
| BMS screen | `SEND MAP`, `RECEIVE MAP`, `SEND TEXT` | `__cics_send_map` / `__cics_receive_map` / `__cics_send_text` |
| System | `ASSIGN`, `ASKTIME`, `FORMATTIME`, `INQUIRE`, `WRITEQ TD`, `HANDLE ABEND` | matching `__cics_*` builtin |
| File control (VSAM) | `READ`, `WRITE`, `REWRITE`, `DELETE`, `STARTBR`, `READNEXT`, `READPREV`, `ENDBR` | matching `__cics_*` builtin |

### 1.6 Compiling a region program — `cics/bootstrap.py`

`compile_cics_program(source, parser, strategy, …)` produces a `LinkedProgram` ready for
`run_cics`. It compiles the main program with the shared `CicsLoweringStrategy` injected, then
transitively resolves and links `CALL` targets via RedDragon's project linker. Callees that
fail to compile are skipped with a warning. IBM LE services (`CEEDAYS`, etc.) are supplied as
stubs from `cics/le_stubs.py`.

---

## 2. Transaction dispatcher loop

### 2.1 Shared types — `cics/types.py`

```python
@dataclass
class CicsContext:
    transid: str
    commarea: bytes
    eibaid: str          # attention id (e.g. "\x7d" = DFHENTER / PF keys)

class DispatchKind(Enum):
    RETURN; RETURN_TRANSID; XCTL; ABEND

@dataclass
class DispatchResult:
    kind: DispatchKind
    transid: str | None
    commarea: bytes | None
    program: str | None
    abcode: str | None
```

### 2.2 Running one program — `run_cics`

`run_cics(program, context, screen_queue, input_queue, *, context_holder, result_holder,
max_steps)` executes a single program for one turn:

- Seeds the context holder so `__cics_init_eib` can initialise `EIBTRNID`/`EIBCALEN`/`EIBAID`.
- Delegates VM setup to `_make_cics_initial_vm(context, ca_bytes)` — builds a fresh `VMState`
  with a `rgn_commarea` region and a `StackFrame` carrying `__cics_transid`, `__cics_eibcalen`,
  `__cics_eibaid`, and `__params_region` (stored as the region name string `"rgn_commarea"`,
  not an `Address` object, so region writes from LINKAGE section items resolve cleanly).
- Delegates entry-point selection to `_make_entry_point(program)` — uses `entry_func_label`
  when present (multi-module link), otherwise the `func_*` prefix predicate.
- Runs via `run_linked`; returns the `DispatchResult` left in `result_holder`.

Both helpers are module-level so `EXEC CICS LINK` can reuse them for linked sub-programs.

### 2.3 Synchronous program link — `EXEC CICS LINK`

`EXEC CICS LINK PROGRAM(name) COMMAREA(field) [LENGTH(n)] [RESP(var)]` calls a program
synchronously within the same transaction:

1. The lowering copies `COMMAREA` bytes into a register (honouring `LENGTH` when present via
   `_resolve_cics_length_option` — digit literal or `LENGTH OF fieldname`).
2. `__cics_link` builtin in `cics/builtins/flow.py`:
   - Looks up the target in `program_cache` (must be pre-compiled; no lazy compilation).
   - Saves and then restores `result_holder` around the inner execution so the linked program's
     `EXEC CICS RETURN` never affects the outer transaction's routing.
   - Builds a fresh `VMState` via `_make_cics_initial_vm` and runs the target with `run_linked`.
   - Writes the modified `rgn_commarea` back into the caller's WS at the original field's offset.
3. After the `CallFunction`, `emit_resp_writeback` writes `0` (DFHRESP NORMAL) to `EIBRESP` and
   to the optional `RESP(var)` field.

LINK targets must appear in `program_cache` before the region starts; they are compiled with the
same shared `CicsLoweringStrategy`. Unknown targets log a warning and are no-ops (EIBRESP = 0).

### 2.4 Routing rule — `_advance_routing`

- **`RETURN_TRANSID`** → resolve next program via `transid_to_program[next_transid]`. Unknown transid → `ABEND TRNI`.
- **`XCTL`** → switch to `program_cache[program]`; transid carries. Unknown program → `ABEND PGMI`.
- **`RETURN` / `ABEND`** → terminal; stop.

Both the autonomous loop and the turn-by-turn API funnel through `_advance_routing` — routing
semantics are defined exactly once.

### 2.5 Two ways to drive the region

**Autonomous loop — `_run_dispatcher_with_runner`.** Blocking `while True`; runs programs,
applies routing, blocks on `input_queue.get()` for the next terminal event on
pseudo-conversational `RETURN TRANSID`. Used by `run_carddemo_region`.

**Turn-by-turn — `CicsRegion`.** Explicit state machine for callers (tests, tools) that drive
one turn at a time without a blocking loop:

```python
region = CicsRegion(program_cache, transid_to_program, strategy)
region.start("SSGN", commarea=b"", input_event=InputEvent(eibaid=DFHENTER, map_data={}))
# inspect region.screen_output ...
region.step(input_event=InputEvent(eibaid=DFHENTER, map_data={"USERID": "user"}))
# continue until region.done
```

```
            ┌──────────────── _advance_routing ───────────────┐
            │  RETURN_TRANSID → next program via CSD map        │
 input_event│  XCTL          → named program, transid carries   │ terminal?
   ───────► run_cics ──► DispatchResult ─────────────────────► RETURN / ABEND ──► stop
            └───────────────────────────────────────────────────┘
```

### 2.6 Terminal channels — `cics/terminal.py`

Program ↔ driver I/O goes through explicit protocols: `ScreenChannel` (outbound: `SEND MAP`/
`SEND TEXT`) and `InputChannel` (inbound: `RECEIVE MAP`) are `put(item)` + `get(block, timeout)`
protocols. `queue.Queue` conforms; `queue.Empty` signals "no item."

### 2.7 CSD and bootstrap

`parse_csd(path)` reads a CICS CSD (`DEFINE TRANSACTION(x) PROGRAM(y)`) into a
`{transid: program}` mapping. `run_carddemo_region` ties everything together: parse the CSD,
construct a shared `CicsLoweringStrategy`, eagerly compile every distinct program, then run
`_run_dispatcher_with_runner` from the entry transid.

---

## 3. VSAM support

### 3.1 Configuration — `cics/vsam/fct.py`

`DatasetConfig(file, record_length, key_offset=0, key_length=0)` describes one dataset.
`FctConfig` maps upper-cased names to configs (`from_dict` / `from_yaml`).

### 3.2 Engine — `cics/vsam/engine.py`

`VsamEngine(config, backend=None)` holds one `SortedDict` per dataset keyed by the full record
bytes, giving ordered iteration for browse. Key matching slices
`record[key_offset : key_offset + klen]`.

Operations return CICS EIBRESP codes (`RESP_NORMAL=0`, `RESP_NOTFND=13`, `RESP_DUPREC=14`,
`RESP_ENDFILE=20`, `RESP_DISABLED=84`).

Point ops: `read`, `write` (DUPREC if key exists), `rewrite` (key from FROM record's own key
field), `delete`.

Browse ops (implicit per-`(task, file, cursor_id)` cursor): `startbr` positions at the first
key ≥ search prefix and past end-of-file when no key qualifies (enabling the
`STARTBR HIGH-VALUES` → `READPREV` idiom). `readnext`/`readprev` use a between-records cursor
with a recorded direction so reversal correctly steps back. `endbr` releases the cursor.

The engine is a **pure bytes/int API** — no CICS or VM coupling. VSAM service builtins in
`cics/builtins/vsam.py` adapt it to IR calling convention and EIBRESP write-back.

### 3.3 Persistence backends — `cics/vsam/backend.py`

```python
class VsamBackend(Protocol):
    def load(self, name, cfg) -> list[bytes]: ...
    def persist(self, name, cfg, records) -> None: ...
```

- **`InMemoryBackend`** (default) — loads from seeded data; `persist` is a no-op.
- **`FileBackend(backing_dir)`** — loads from `<backing_dir>/<NAME>.dat` if present, else from
  seeds; `persist` write-throughs the backing file. Seeds are never overwritten.

Seeding APIs:

```python
# InMemoryBackend: pre-populate from IDCAMS flat files
from cics.vsam.seed import load_vsam_seed
backend = load_vsam_seed(fct_path="region.fct.yaml", data_dir="fixtures/vsam/")
engine = VsamEngine(fct_config, backend=backend)

# FileBackend: seed from flat files, persist mutations
from cics.vsam.seed import seed_vsam
seed_vsam(fct_path="region.fct.yaml", data_dir="fixtures/vsam/", vsam_dir="/tmp/vsam/")
engine = VsamEngine(fct_config, backend=FileBackend("/tmp/vsam/"))
```

`flush_to(directory)` snapshots every dataset regardless of backend.

### 3.4 Raw codec — `cics/vsam/format.py`

- `read_flat_file(path, record_length)` — split into fixed-length records; missing → `[]`;
  size-not-a-multiple → `ValueError`.
- `write_flat_file(path, records, record_length)` — validate lengths, write **atomically**
  (temp file + `os.replace`).

### 3.5 Dump CLI — `cics/vsam/dump.py`

Copybook-driven decoder for persisted `.dat` files (EBCDIC text, zoned-decimal, COMP-3, binary):

```bash
python -m cics.vsam.dump --data ACCTDAT.dat --copybook CVACT01Y.cpy \
       [--record NAME] [--format jsonl|block] [--jar PATH]
```

Wraps the copybook in a minimal program skeleton, parses via ProLeap, extracts `DataLayout`,
then decodes each record field by field. Renderers: `jsonl` (default; one JSON object per
record) and `block` (human-readable `@offset name value 0xRAW` lines).

---

## 4. Design invariants

- **No core-engine edits.** Nothing under `interpreter/vm/**`, `ir.py`, `run.py`, `executor.py`,
  `cfg.py` is modified. CICS verbs reach the VM only as `CallFunction` to registered builtins.
- **Structure over text.** The only textual transform is `inject_dfheiblk` (word-split, not
  regex). DFHRESP lowering is structural. CICS verb parsing is a grammar. Comment filtering is
  in the ProLeap fork's `TagUtils` because ProLeap treats the EXEC CICS envelope as opaque.
- **One routing rule.** `_advance_routing` is the sole definition of inter-program routing.
- **Pure VSAM engine.** Bytes/int store; never interprets record internals; persistence is a
  pluggable backend.
- **Default behaviour unchanged.** A non-CICS COBOL compile uses `CatchAllLoweringStrategy`; a
  default `VsamEngine` writes no files. CICS and persistence are strictly opt-in.

---

## 5. File map

| Concern | Files |
|---|---|
| Pre-pass | `cics/preprocessor.py` |
| DFHRESP structural lowering | `cics/dfhresp_prepass.py`; `_DFHRESP_TABLE` in `preprocessor.py`; grammar fix in ProLeap fork |
| EXEC CICS grammar | `cics/cics_grammar/` (ANTLR4); `cics/cics_visitor.py`; `ExecCicsStatement` in `interpreter/cobol/cobol_statements.py` (red-dragon) |
| Lowering strategy | `cics/strategy.py`; protocol in `interpreter/cobol/exec_cics_strategy.py` (red-dragon) |
| Service builtins | `cics/builtins/{flow,screen,system,vsam}.py` (`flow.py` includes `__cics_link`) |
| Dispatcher / region | `cics/dispatcher.py` (`run_cics`, `_make_cics_initial_vm`, `_make_entry_point`, `CicsRegion`), `cics/bootstrap.py`, `cics/types.py` |
| Terminal I/O | `cics/terminal.py` |
| LE service stubs | `cics/le_stubs.py` |
| VSAM | `cics/vsam/{fct,engine,backend,format,dump,seed}.py` |
| BMS maps | `cics/bms/generate.py` (symbolic copybooks via bms-tools pipeline) |
