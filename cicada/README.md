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

Cicada has no Makefile or build script: everything is built from the forge root.

```bash
git clone --recurse-submodules git@github.com:avishek-sen-gupta/red-dragon-forge.git
cd red-dragon-forge
make setup      # hlasm_export + both bridge JARs + uv sync (JDK 17+, Maven, CMake, Ninja, C++)
                # `make jar-force` after a red-dragon bump; delete the fork's build/ to rebuild hlasm_export
. ./bridge-env.sh
cd cicada
```

## Tests

```bash
uv run --no-sync python -m pytest                          # full suite incl. CardDemo e2e (needs the JAR)
uv run --no-sync python -m pytest tests/unit/ -x -q        # unit tests (no JAR required)
uv run --no-sync python -m pytest tests/integration/ -x -q # integration tests (needs ProLeap JAR)
uv run --no-sync python -m pytest -p no:xdist --override-ini=addopts= <path>  # one test, live stdout
```

`CARDDEMO_HOME` defaults to forge's `vendor/carddemo/app`; set it only to point elsewhere.

Always invoke `uv run` with `--no-sync`: red-dragon is an editable path dependency
(`vendor/red-dragon`), and a plain `uv run` re-checks the lockfile and rebuilds the large
red-dragon editable wheel whenever that submodule changed. `--no-sync` skips that; red-dragon's
Python is still picked up live via its editable `.pth`. Run a bare `uv sync` once after cloning
or after changing dependencies.

---

## Architecture overview

A hard invariant underlies all of cicada: **nothing in this repo touches RedDragon's core
engine.** There are zero edits to `interpreter/vm/**`, `ir.py`, `run.py`, `executor.py`, or
`cfg.py`. Every CICS-specific behaviour reaches the VM only through `CallFunction` IR to
registered builtins — the same mechanism any language frontend uses.

```
cics/
  strategy.py          # CicsLoweringStrategy (RedDragonExtensionLoweringStrategy impl)
  coprocessor.py       # build_cics_spec — wraps the strategy as a CoprocessorSpec
  statements.py        # ExecCicsStatement + CicsDialectParser (DialectParser impl)
  cics_visitor.py      # ANTLR visitor: parse_exec_cics_text
  cics_parser.py       # thin re-export of parse_exec_cics_text / CicsOperand
  cics_grammar/        # ANTLR4 EXEC CICS grammar + generated parser
  preprocessor.py      # apply_cics_prepass (inject_dfheiblk)
  dfhresp_prepass.py   # DFHRESP ASG pre-pass
  dispatcher.py        # CicsRegion, run_cics, _advance_routing
  vm_init.py           # make_cics_initial_vm, make_entry_point
  csd_parse.py         # parse_csd, parse_csd_files (transid→program, file→DSNAME)
  bootstrap.py         # compile_cics_program, run_carddemo_region
  conversational.py    # pseudo-conversational suspend/resume driver
  types.py             # CicsContext, DispatchResult, DispatchKind
  terminal.py          # ScreenChannel / InputChannel protocols
  le_stubs.py          # IBM LE service stubs (CEEDAYS, etc.)
  builtins/            # CICS service builtins: flow, screen, system, vsam
  vsam/                # VsamEngine (CICS adapter over shared drivers), eibresp, seed, format, dump CLI
  bms/                 # BMS symbolic-copybook generation (hlasm_export → bms_copybook_gen)
  flow_map.py, flow_graph_core.py, flow_observer.py, graph_sink.py, verb_source_lowering.py
                       # streaming CICS transaction-flow graph extraction (see §6)
```

RedDragon contributes two generic, dialect-agnostic seams — no CICS names remain in RedDragon:

- `interpreter/frontend_extension_lowering.py` — `RedDragonExtensionLoweringStrategy` protocol,
  the injectable extension-lowering seam.
- `interpreter/frontend_extension.py` — `DialectParser` protocol (+ `NullDialectParser` default)
  for turning bridge JSON into dialect statement objects.

Everything CICS-specific lives in cicada:

- `cics/statements.py` — `ExecCicsStatement` (relocated from RedDragon) + `CicsDialectParser`,
  the `DialectParser` that builds it from bridge JSON.
- `cics/cics_grammar/` — ANTLR4 grammar (`CICSzParser.g4`, `CICSzLexer.g4`) + generated `CICSzParser.py`.
- `cics/cics_visitor.py` — ANTLR visitor: `parse_exec_cics_text(text) -> (verb, {OPTION: CicsOperand | None})`.
- `cics/cics_parser.py` — thin re-export wrapper (`CicsOperand`, `parse_exec_cics_text`) used as the parse entry point.

`compile_cobol` accepts injectable `extension_strategies` and `dialect_parsers` arrays; cicada
supplies `CicsLoweringStrategy` and `CicsDialectParser`, composed via a `CoprocessorSpec` (see §1.6).

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

The pre-pass exists only because ProLeap cannot inject DFHEIBLK itself. The only other textual
step in the CICS path is comment stripping inside `CicsDialectParser.parse` (see §1.3), which
uses a small regex; the pre-pass detection itself is a word-split, not a regex.

### 1.3 EXEC CICS as a structured statement

When ProLeap surfaces an `EXEC CICS` block, the bridge emits its verbatim text as
`exec_cics_text` in the block's JSON. cicada's `CicsDialectParser.parse` (in
`cics/statements.py`) — the `DialectParser` injected into the compile — first strips comment
lines with `re.sub(r"\*>.*", "", …, flags=re.MULTILINE)`, then calls
**`parse_exec_cics_text(text) -> (verb, {OPTION: CicsOperand | None})`** from
`cics.cics_visitor`, and wraps the result in an `ExecCicsStatement`.

The grammar (ANTLR4):

- Verb is a grammar construct — single word or a small set of compound verbs (`SEND MAP`,
  `RECEIVE MAP`, `WRITEQ TD`, `HANDLE ABEND/CONDITION/AID`) — not Python string-joining.
- Each option value is a `CicsOperand(text, is_literal, subscripts, ref_mod_start, ref_mod_length)`.
  `is_literal` is set structurally when the grammar matched a quoted `ARG_STRING` terminal.
- Multi-word values such as `LENGTH OF WS-CA` arrive as a single operand with the full text
  preserved — `cics/strategy.py` inspects the `text` where needed (e.g., `_resolve_cics_length_option`).

**Comment lines inside EXEC CICS blocks** are stripped in Python by `CicsDialectParser.parse`
— `re.sub(r"\*>.*", "", exec_cics_text, flags=re.MULTILINE)` — before the text reaches
`parse_exec_cics_text`. (The bridge no longer filters them; it hands the block over verbatim.)

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

`compile_cobol` accepts a list of injected **`extension_strategies`** implementing
`RedDragonExtensionLoweringStrategy` (from `interpreter.frontend_extension_lowering`). When no
strategy handles an EXEC CICS statement the generic frontend emits no IR for it — a non-CICS
COBOL compile passes an empty list, so the CICS machinery is inert unless opted in.

- **`CicsLoweringStrategy`** (in cicada) — implements the protocol; registers CICS service
  builtins into the VM's `Builtins.TABLE` (closures over region runtime state), then translates
  each verb to IR.

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

### 1.6 Compiling a region program — `cics/bootstrap.py` + `cics/coprocessor.py`

`compile_cics_program(source, parser, spec, …)` produces a `LinkedProgram` ready for
`run_cics`. It is a thin wrapper over RedDragon's **coprocessor compile API**
(`interpreter.project.coprocessor_compile.compile_program`), which composes one or more
`CoprocessorSpec`s and calls `compile_cobol(…, extension_strategies=[…], dialect_parsers=[…])`.
cicada builds its `CoprocessorSpec` in `cics/coprocessor.py::build_cics_spec`:

- `make_strategy` → a fresh `CicsLoweringStrategy` over the shared region runtime state,
- `dialect_parser` → `CicsDialectParser`,
- `source_prepass` → `apply_cics_prepass`,
- `owns_execution=True` and `source_search_dirs` → the IBM LE stub dir.

The generic single/multi-module compile + transitive `CALL` resolution + linking live in
RedDragon. Callees that fail to compile are skipped with a warning. IBM LE services (`CEEDAYS`,
etc.) are supplied as stubs from `cics/le_stubs.py`. A *conversational* (non-pseudo-conversational)
program is compiled with `CicsLoweringStrategy(conversational=True)` and driven via
`cics/conversational.py`'s suspend/resume region — see that module.

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
- Delegates VM setup to `make_cics_initial_vm(context, ca_bytes)` — builds a fresh `VMState`
  with a `rgn_commarea` region and a `StackFrame` carrying `__cics_transid`, `__cics_eibcalen`,
  `__cics_eibaid`, and `__params_region` (stored as the region name string `"rgn_commarea"`,
  not an `Address` object, so region writes from LINKAGE section items resolve cleanly).
- Delegates entry-point selection to `make_entry_point(program)` — uses `entry_func_label`
  when present (multi-module link), otherwise the `func_*` prefix predicate.
- Runs via `run_linked`; returns the `DispatchResult` left in `result_holder`.

Both helpers live in `cics/vm_init.py` (module-level) so `EXEC CICS LINK` can reuse them for
linked sub-programs.

### 2.3 Synchronous program link — `EXEC CICS LINK`

`EXEC CICS LINK PROGRAM(name) COMMAREA(field) [LENGTH(n)] [RESP(var)]` calls a program
synchronously within the same transaction:

1. The lowering copies `COMMAREA` bytes into a register (honouring `LENGTH` when present via
   `_resolve_cics_length_option` — digit literal or `LENGTH OF fieldname`).
2. `__cics_link` builtin in `cics/builtins/flow.py`:
   - Looks up the target in `program_cache` (must be pre-compiled; no lazy compilation).
   - Saves and then restores `result_holder` around the inner execution so the linked program's
     `EXEC CICS RETURN` never affects the outer transaction's routing.
   - Builds a fresh `VMState` via `make_cics_initial_vm` and runs the target with `run_linked`.
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
semantics are defined exactly once. (`ABEND AZCT` — a terminal-input-wait timeout — is a
distinct, earlier codepath in the autonomous loop itself, before routing is even consulted; see
§2.5.)

### 2.5 Two ways to drive the region

**Autonomous loop — `_run_dispatcher_with_runner`.** Blocking `while True`; runs programs,
applies routing, and on pseudo-conversational `RETURN TRANSID` reads the next terminal event's
attention key via `_peek_input_event` — a get-then-put-back (not a real `queue.Queue.get()`
consume), so the event is left on the channel for the resumed turn's own `RECEIVE MAP` to
consume. `_peek_input_event` carries a hardcoded 30s timeout; if no further input ever arrives,
the loop returns `DispatchResult(kind=ABEND, abcode="AZCT")` — the real CICS abend code for a
terminal read-time-out — instead of hanging forever. Used by `run_carddemo_region`.

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

### 2.7 CSD and bootstrap — `cics/csd_parse.py`

`parse_csd(path)` reads a CICS CSD (`DEFINE TRANSACTION(x) PROGRAM(y)`) into a
`{transid: program}` mapping; `parse_csd_files(path)` reads each `DEFINE FILE(name) …
DSNAME(dataset)` into a `{logical file name: physical DSNAME}` mapping (resolving CICS FILE
CONTROL access to physical datasets — the DSN-model / CSD dataset-definition work). Both live in
the leaf module `cics/csd_parse.py` (a Lark grammar + transformer) and are re-exported through
`cics/dispatcher.py`. `run_carddemo_region` ties everything together: parse the CSD, build one
shared CICS `CoprocessorSpec`, eagerly compile every distinct program, then run
`_run_dispatcher_with_runner` from the entry transid.

---

## 3. VSAM support

### 3.1 Configuration — `cics/vsam/fct.py`

`DatasetConfig(file, record_length, key_offset=0, key_length=0)` describes one dataset.
`FctConfig` maps upper-cased names to configs (`from_dict` / `from_yaml`).

### 3.2 Engine (CICS file-control adapter) — `cics/vsam/engine.py`

`VsamEngine(config, vsam_dir)` is a thin **CICS adapter** over red-dragon's shared
access-method drivers — it owns no storage of its own. Each dataset's backing `.dat` file under
`vsam_dir` **is** the store (file-resident, byte-faithful) — the same drivers COBOL batch
execution and jackal's IDCAMS use, so the whole mainframe stack shares one storage
implementation. (The former in-memory `SortedDict` store + pluggable persistence backends are
gone.)

`_open(file_name, mode)` gates on FCT enable/define first (returns `RESP_DISABLED` before
touching a driver) then routes by `key_offset`: `0` → `open_driver(INDEXED, …)` (binary search
over a key-sorted file); `>0` → `open_alternate_key_driver(…)` (linear scan, read-only — e.g.
the CARD-XREF ACCT-ID at offset 25).

The drivers return a language-agnostic `AccessCondition`; `cics/vsam/eibresp.py::to_eibresp`
maps it to CICS EIBRESP (`OK→0`, `END_OF_FILE→20`, `NOT_FOUND→13`, `DUPLICATE_KEY→14`;
file-state conditions on an enabled file → `RESP_IOERR` per decision A — the FCT, not the
driver, owns file state).

Point ops (`read`/`write`/`rewrite`/`delete`) open a driver per call. `read` holds the matched
key so a keyless `rewrite`/`delete` (read-for-update) targets the right record. Browse ops keep
one open driver instance per `(task, file, cursor_id)` in `_browse`: `startbr` positions via
`start(key, ">=")` (incl. the past-end `STARTBR HIGH-VALUES` → `READPREV` seek-last idiom),
`readnext`→`read_seq`, `readprev`→`read_prev` (the driver's cursor handles the
READNEXT→READPREV reversal directly), `endbr`→`close`. CICS-only state (FCT enable/disable,
held key, task cursors) stays in the adapter; record I/O is the shared drivers. VSAM service
builtins in `cics/builtins/vsam.py` adapt it to IR calling convention and EIBRESP write-back.

### 3.3 Seeding — `cics/vsam/seed.py`

The backing file IS the store, so there are no persistence backends — seeding just writes the
`.dat` files the drivers open:

```python
from cics.vsam.seed import seed_vsam
seed_vsam(fct_path="region.fct.yaml", data_dir="fixtures/vsam/", vsam_dir="/tmp/vsam/")
engine = VsamEngine(fct_config, vsam_dir="/tmp/vsam/")
```

`seed_vsam` reads the EBCDIC flat files named in the FCT and writes `<vsam_dir>/<NAME>.dat`.
Base-KSDS records (key_offset 0) are written **key-sorted** — the file-resident binary-search
driver requires the file sorted by its key; alternate-key datasets are written in source order.
(`seed_records` is the in-process helper it builds on.)

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
- **Structure over text.** The pre-pass transform `inject_dfheiblk` is a word-split, not a
  regex; DFHRESP lowering is structural; CICS verb parsing is a grammar. The one textual
  exception is comment stripping inside `CicsDialectParser.parse` (a small `re.sub`), done in
  Python because the bridge now hands the EXEC CICS block over verbatim.
- **One routing rule.** `_advance_routing` is the sole definition of inter-program routing.
- **VSAM file control is a thin adapter.** Record I/O delegates to RedDragon's shared
  access-method drivers; the backing `.dat` file is the store (no in-memory copy, no pluggable
  backend). The adapter never interprets record internals — only FCT state + EIBRESP mapping.
- **Default behaviour unchanged.** A non-CICS COBOL compile passes no `extension_strategies`,
  so EXEC CICS statements lower to no IR; CICS lowering + file control are opt-in (only an
  EXEC CICS program compiled with the CICS `CoprocessorSpec` reaches the adapter).

---

## 5. File map

| Concern | Files |
|---|---|
| Pre-pass | `cics/preprocessor.py` |
| DFHRESP structural lowering | `cics/dfhresp_prepass.py`; `_DFHRESP_TABLE` in `preprocessor.py`; grammar fix in ProLeap fork |
| EXEC CICS grammar | `cics/cics_grammar/` (ANTLR4); `cics/cics_visitor.py`; `cics/cics_parser.py` (re-export); `ExecCicsStatement` + `CicsDialectParser` in `cics/statements.py` |
| Lowering strategy | `cics/strategy.py`; protocol `RedDragonExtensionLoweringStrategy` in `interpreter/frontend_extension_lowering.py` (red-dragon); `DialectParser` in `interpreter/frontend_extension.py` (red-dragon) |
| Coprocessor compile | `cics/coprocessor.py` (`build_cics_spec`); `CoprocessorSpec`/`compile_program` in `interpreter/project/coprocessor_compile.py` (red-dragon) |
| Service builtins | `cics/builtins/{flow,screen,system,vsam}.py` (`flow.py` includes `__cics_link`) |
| Dispatcher / region | `cics/dispatcher.py` (`run_cics`, `_advance_routing`, `CicsRegion`), `cics/vm_init.py` (`make_cics_initial_vm`, `make_entry_point`), `cics/bootstrap.py`, `cics/types.py` |
| CSD parsing | `cics/csd_parse.py` (`parse_csd`, `parse_csd_files`) |
| Conversational driver | `cics/conversational.py` (suspend/resume) |
| Flow-graph extraction | `cics/flow_map.py`, `cics/flow_graph_core.py`, `cics/flow_observer.py`, `cics/graph_sink.py`, `cics/verb_source_lowering.py` |
| Terminal I/O | `cics/terminal.py` |
| LE service stubs | `cics/le_stubs.py` |
| VSAM | `cics/vsam/{fct,engine,eibresp,format,dump,seed}.py` |
| BMS maps | `cics/bms/generate.py` + `cics/bms/macros/` (symbolic copybooks: `hlasm_export` → `bms_copybook_gen`) |

---

## 6. Streaming CICS flow-graph extraction

Cicada can emit the CICS-flow portion of a knowledge graph as each program lowers, without a
separate analysis pass. `extract_transaction_flow_graph(...)` (`cics/flow_map.py`) is the public
entry point: given a transid→program map and program sources, it streams nodes and edges into a
`GraphSink` (`cics/graph_sink.py` — a structural `Protocol` with `add_node`/`add_edge`; the
knowledge-graph `GraphWriter` satisfies it without a hard import).

- `cics/flow_observer.py` — `CicsVerb` (verb-as-data record), the `CicsFlowObserver` protocol,
  and `NullCicsFlowObserver`. `CicsLoweringStrategy` notifies its observer on every verb via the
  `on_verb` seam — including VSAM / FILE CONTROL verbs (`READ`, `WRITE`, `REWRITE`, `DELETE`,
  `STARTBR`, `READNEXT`, `READPREV`), which carry the accessed `file_name`.
- `cics/verb_source_lowering.py` — `GraphEmittingObserver` (bridges `on_verb` events to graph
  edges) and `stream_program_verbs(...)`, production's "lower each program and emit edges" source.
- `cics/flow_graph_core.py` — the verbs-as-data leaf shared by production and the KG pipeline;
  `_verb_edge` maps each `CicsVerb` to a `GraphEdge`. VSAM verbs become `READS`/`WRITES`/`UPDATES`
  edges to a `CICS_FILE` node; the CSD contributes structural `STARTS` and `DEFINES_DATASET`
  (via `parse_csd_files`) edges.

---

## 6a. Green screen over TN3270

`cicada-tn3270` serves a compiled CICS region to stock 3270 emulators over the TN3270 wire —
the same `CicsRegion` / `RegionDriver` headless tests drive, adapted by `cics/tn3270/`
(`codes.py`, `encoder.py`, `decoder.py`, `negotiation.py`, `session.py`, `config.py`,
`region.py`, `cli.py`; `wire.py` is the one excluded socket module).

```bash
make setup             # or at least: make hlasm + the bridge JARs
. ./carddemo-env.sh    # FORGE_ROOT + CARDDEMO_HOME, and bridge-env.sh's JARs
uv run cicada-tn3270 --config cicada/config/carddemo-tn3270.toml --port 3270
```

The server expands `${CARDDEMO_HOME}`/`${FORGE_ROOT}` from the config and reads
`PROLEAP_BRIDGE_JAR` to compile, so all three must be exported in the shell it starts from —
`carddemo-env.sh` is `bridge-env.sh` plus those two, with the CardDemo submodule as the
default source tree.

Then connect with any stock 3270 client, e.g. `c3270 localhost:3270` or `x3270` (macOS:
`brew install x3270`). Accepted terminal models are IBM-3278/3279 model 2–5, with or without
`-E` — Erase/Write always selects the 24x80 default partition, so any of them works (x3270's
default model 4 included).

The TOML config (`RegionConfig`, `cics/tn3270/config.py`) has two tables:

- `[paths]` — `source_dirs` (list, first-hit-wins per program), `copybook_dirs` (list),
  `bms_dirs` (list), `data_dir`, `hlasm_export`, optional `copybook_exts` (list; empty by
  default so the bridge's own `-copybook-ext` defaults apply), all `${VAR}`-expandable
  (`CARDDEMO_HOME`/`FORGE_ROOT` in the shipped config).
- `[region]` — `initial_transid`, `min_commarea_len`, `programs` (extra programs beyond the
  transaction table's values).
- `[transactions]` — `TRANSID = "PROGRAM"` entries (the CSD's transid→program map).
- `[datasets.NAME]` — `file`, `record_length`, optional `key_offset`/`key_length` (VSAM seed).

`CARDDEMO_HOME` (or the vendored `vendor/carddemo` submodule) supplies the COBOL, BMS and
EBCDIC seed data the shipped `cicada/config/carddemo-tn3270.toml` points at.

One terminal and one task at a time: pseudo-conversational programs (CardDemo) are served;
conversational programs (zBANK-style) are not yet served over the wire (a later epic). SEND
CONTROL and a bare SEND FROM remain unsupported.

Headless driving through `RegionDriver` + `TerminalScreen` remains the primary, permanent test
path (`cics-headless-first-class`): every screen-fidelity feature is asserted headlessly first,
and the wire is a thin adapter over the same driver, not a parallel code path.

### Driving CardDemo once connected

Sign on as `USER0001` / `PASSWORD` for the main menu, or `ADMIN001` / `PASSWORD` for the admin
menu — the vendored `USRSEC` holds `USER0001`-`USER0005` (type `U`) and `ADMIN001`-`ADMIN005`
(type `A`), and COSGN00C routes on that type. A 3270 has no edit mode: the cursor starts in the
first input field and you type straight into it. Tab and Shift+Tab move between fields; typing
into a protected area locks the keyboard, which `Ctrl+R` (Reset) clears. Enter sends; function
keys are PF1-PF24 (`F5` in c3270, or `PF(5)` at its `Ctrl+]` command line).

These flows are the ones known to work end to end. Every row but the last two is covered by the
wire tests in `tests/integration/cics/test_tn3270_crud_e2e.py`; admin `5`/`6` need a live Db2
and are driven headlessly instead, by `tests/integration/test_carddemo_db2_headless.py` — see
"Admin 5/6: the Db2 tier" below for why and for the verified command sequence.

| Menu | Option | Flow | Commits with |
|---|---|---|---|
| Main | `01` | View account, then PF3 back | read-only |
| Main | `02` | Update account: fetch, edit, ENTER validates, PF5 saves | PF5 → `REWRITE` |
| Main | `05` | Update card: same two-turn shape | PF5 → `REWRITE` |
| Main | `08` | Add transaction: fill the fields, ENTER, then `Y` in `CONFIRM` | ENTER → `WRITE` |
| Main | `10` | Bill pay: account id, ENTER, then `Y` in `CONFIRM` | ENTER → `REWRITE` + `WRITE` |
| Admin | `2` / `3` / `4` | Add / update / delete a user | `WRITE` / PF5 → `REWRITE` / PF5 → `DELETE` |
| Admin | `5` | Transaction type list/update (`COTRTLIC`) — **needs a live Db2** | ENTER validates, PF10 → `UPDATE`/`DELETE` |
| Admin | `6` | Transaction type maintenance (`COTRTUPC`) — **needs a live Db2** | ENTER validates, PF5 → `UPDATE`/`INSERT`, PF4+PF4 → `DELETE` |

The update programs only honour PF5 *after* an ENTER turn has validated the change ("Changes
validated. Press F5 to save"), so the two turns are mandatory, not a convention. On the wire
every `FSET` field is returned whether or not you retyped it, which is why COUSR02C's update
screen needs every editable field re-entered — see `forge-1zu.8` for why that is faithful BMS
behaviour rather than a runtime defect.

These five are also wired (transaction + program) but have no wire test — each is a read-only
browse/view screen, so a CRUD-style wire test would add nothing a manual headless smoke check
doesn't already cover:

| Menu | Option | Flow |
|---|---|---|
| Main | `03` | Card list (browses `CARDDAT`) |
| Main | `04` | Card view (reads `CARDDAT`, plus the `CARDAIX` alternate-index path) |
| Main | `06` | Transaction list (browses `TRANSACT`) |
| Main | `07` | Transaction view (reads `TRANSACT`) |
| Admin | `1` | User list (browses `USRSEC`) |

Everything the programs write goes to a VSAM copy seeded into a temp directory (`region.py`'s
`_vsam_engine` reads `data_dir` and seeds into the server's work dir), so the vendored EBCDIC
data is never touched and restarting the server resets the world.

The remaining options cannot work in this snapshot, each for a different reason. Main `09`
(Transaction Reports) needs JCL job submission behind the JOBS TDQ, which this server does not
drive. Main `11` has no `COPAUS0C` source here at all, and degrades gracefully because COMEN01C
guards that one XCTL with `EXEC CICS INQUIRE PROGRAM` ("This option ... is not installed...").

Admin `5`/`6` are the **Db2** options — "Transaction Type List/Update" (`COTRTLIC`) and
"Transaction Type Maintenance" (`COTRTUPC`), bracketed in `COADM02Y.cpy` as added for the Db2
release, which is also why that copybook raises `CDEMO-ADMIN-OPT-COUNT` from 4 to 6. Their
source ships in a separate tree (`vendor/carddemo/app/app-transaction-type-db2/`) from the rest
of CardDemo, which is why they are not on the plain `cicada-tn3270`/`carddemo-tn3270.toml` path
above: they need `red_dragon_forge`'s composition layer (CICS + squall's SQL `CoprocessorSpec`
composed into one region, `red_dragon_forge.carddemo_db2_region.build_db2_region`) and a live
Db2, not just a CICS-only config entry.

### Admin 5/6: the Db2 tier

Both programs are wired, compiled, and run headlessly end to end against a real Db2 by
`tests/integration/test_carddemo_db2_headless.py`, using
`cicada/config/carddemo-db2-tn3270.toml` (a second, Db2-tree-inclusive config, not
`carddemo-tn3270.toml`). The `CARDDEMO.TRANSACTION_TYPE` / `TRANSACTION_TYPE_CATEGORY` tables
are dropped, recreated from the vendored DDL, and reseeded at the START of every test run
(`red_dragon_forge.carddemo_db2_schema.apply_schema`, run by the `carddemo_db2_schema` fixture)
— so a restart always resets the world, the same guarantee the VSAM-backed options above get
from their own seeded temp directory.

Verified end to end against the `squall-db2` container -- if it's up but the instance died
(`SQL30081N`), use `make db2-restart`, not `make db2-up`:

```bash
make db2-up                              # or make db2-restart if already up but unhealthy
cd red-dragon-forge
. ./carddemo-env.sh                      # FORGE_ROOT + CARDDEMO_HOME + the bridge JARs
. tests/integration/db2_env.sh           # SQUALL_DB2_DSN, from squall/.env's DB2_PORT
uv run --no-sync python -m pytest tests/integration/test_carddemo_db2_headless.py -q
```

`red_dragon_forge.carddemo_db2_cli` (installed as `carddemo-db2-cli`) is the live-3270-server CLI
for this composed region, analogous to `cics/tn3270/cli.py` but built on `build_db2_region`
instead of `build_region`.

Preparing the database and serving it are **separate commands**, deliberately. `carddemo-db2-seed`
(`make db2-seed`) is the only thing that ever issues `DROP TABLE`; the server only ever reads, and
fails loudly at startup if the schema is missing rather than abending the first screen a terminal
paints. Both go through the same `apply_schema` the test fixture above uses, so the green screen
cannot show data the tests never exercised.

```bash
make db2-status                          # 0 up, 1 dead (-> make db2-restart), 2 DSN unset
cd red-dragon-forge
. ./carddemo-env.sh                      # FORGE_ROOT + CARDDEMO_HOME + the bridge JARs
. tests/integration/db2_env.sh           # SQUALL_DB2_DSN, from squall/.env's DB2_PORT
make db2-seed                            # once -- drops, recreates and reseeds
uv run carddemo-db2-cli --config cicada/config/carddemo-db2-tn3270.toml --port 3271
c3270 -model 3279-2-E localhost:3271   # 3279 + -E, or you get monochrome
```

Sign on as `ADMIN001`/`PASSWORD` and select admin `5` or `6`. Re-run `make db2-seed` whenever you
want the world reset; the server never resets it for you.

Because COADM01C XCTLs straight to the option's program with no INQUIRE guard, selecting admin
`5`/`6` from the plain CICS-only `cicada-tn3270` server (which has no SQL coprocessor composed
in) still hits `forge-6jj`: the unknown-program XCTL abends PGMI internally but crashes the
driver rather than painting a diagnostic. That failure mode does not apply to the composed Db2
region above, which has both programs actually compiled in.

---

## 7. HLASM / BMS build path

BMS symbolic copybooks are generated from raw `.bms` map sources by an out-of-process HLASM
assembler front end:

- `make hlasm` at the forge root (part of `make setup`) builds the `hlasm_export` binary from
  `cicada/third-party/che-che4z-lsp-for-hlasm-fork` via its OS-agnostic `build.sh`
  (output: `third-party/che-che4z-lsp-for-hlasm-fork/build/bin/hlasm_export`).
- `cics/bms/generate.py` (`generate_symbolic_copybooks`) runs, per `.bms` file,
  `hlasm_export <map>.bms --syslib <macros>` piped into `python -m bms_copybook_gen`, writing
  `<out_dir>/<stem>.cpy`. `hlasm_export` only recognises the BMS macros (`DFHMSD`/`DFHMDI`/
  `DFHMDF`) when their HLASM prototype definitions are on the assembler SYSLIB, so cicada ships
  minimal prototypes in `cics/bms/macros/` (the default syslib). `bms_copybook_gen` is a
  first-class package (not a vendored tool).
