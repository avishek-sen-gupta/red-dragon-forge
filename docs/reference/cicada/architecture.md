# cicada architecture

cicada is the CICS runtime for the RedDragon interpreter. It runs unmodified COBOL CICS
programs: pseudo-conversational transaction dispatch, VSAM file control and BMS screens. The
reference workload is the CardDemo online tier in `vendor/carddemo`.

To run CardDemo, see [run-carddemo.md](../../how-to/run-carddemo.md). The server config is
described in [tn3270-config.md](tn3270-config.md). Open gaps are in
[the cicada roadmap](../../roadmaps/cicada.md).

Two explainer pages sit beside this one:

- [cicada-architecture.html](cicada-architecture.html) — the compile and dispatch pipeline.
- [conversational-suspend-resume.html](conversational-suspend-resume.html) — how a
  conversational program suspends at `RECEIVE MAP` and resumes with terminal input.

## Invariants

- RedDragon is not modified. `vendor/red-dragon` is a submodule; interpreter changes go
  upstream.
- CICS behaviour reaches the VM only through `CallFunction` IR to registered builtins. That is
  the same mechanism any language frontend uses.
- RedDragon holds no CICS names. It offers generic seams, and cicada implements them:

  | Seam (in `vendor/red-dragon`) | cicada implementation |
  |---|---|
  | `RedDragonExtensionLoweringStrategy` (`interpreter/frontend_extension_lowering.py`) | `CicsLoweringStrategy` (`cics/strategy.py`) |
  | `DialectParser` (`cobol_asg/frontend_extension.py`) | `CicsDialectParser` (`cics/statements.py`) |
  | `CoprocessorSpec` (`interpreter/project/coprocessor_compile.py`) | `build_cics_spec` (`cics/coprocessor.py`) |

- A COBOL compile without the CICS `CoprocessorSpec` lowers `EXEC CICS` to no IR. CICS is
  opt-in.
- Verb parsing is a grammar. The DFHEIBLK injection is a word split. DFHRESP lowering is
  structural. The one regex strips `*>` comment lines inside an `EXEC CICS` block, in
  `CicsDialectParser.parse`.
- `_advance_routing` in `cics/dispatcher.py` is the only definition of inter-program routing.
- CICS files are datasets in [catnip](../catnip/README.md)'s system catalog, the one jackal's
  jobs use. Record I/O goes through RedDragon's shared access-method drivers over the
  catalog's own bytes; cicada keeps no copy.

## Package layout

All paths are under `cicada/`.

| Path | Contents |
|---|---|
| `cics/strategy.py` | `CicsLoweringStrategy`: registers the service builtins and lowers each verb |
| `cics/strategy_stores.py` | the strategy's writes into state it does not own |
| `cics/coprocessor.py` | `build_cics_spec`: the strategy, parser and pre-pass as one `CoprocessorSpec` |
| `cics/statements.py` | `ExecCicsStatement`, `CicsDialectParser` |
| `cics/cics_grammar/` | ANTLR4 grammar (`CICSzLexer.g4`, `CICSzParser.g4`) and generated parser |
| `cics/cics_visitor.py` | `parse_exec_cics_text(text) -> (verb, {OPTION: CicsOperand})` |
| `cics/cics_parser.py` | re-export of `parse_exec_cics_text` and `CicsOperand` |
| `cics/preprocessor.py` | `apply_cics_prepass`: injects `COPY DFHEIBLK.` after `WORKING-STORAGE SECTION.` |
| `cics/dfhresp_prepass.py` | `resolve_dfhresp_nodes`: replaces `DFHRESP(x)` nodes with numeric literals |
| `cics/conditions.py` | condition names, DFHRESP codes, the raisable set, the `UNSP` abend code |
| `cics/handler_labels.py` | numbers the paragraphs `HANDLE CONDITION` can jump to |
| `cics/interval.py` | `StartQueue`, `StartRequest`: pending `START` requests |
| `cics/dispatcher.py` | `run_cics`, `_advance_routing`, `_run_dispatcher_with_runner`, `CicsRegion` |
| `cics/vm_init.py` | `make_cics_initial_vm`, `make_entry_point` |
| `cics/csd_parse.py` | `parse_csd` (transid → program), `parse_csd_files` (file → DSNAME) |
| `cics/bootstrap.py` | `compile_cics_program`, `run_carddemo_region` |
| `cics/conversational.py` | conversational driver over the VM's suspend/resume primitive |
| `cics/types.py` | `CicsContext`, `DispatchKind`, `DispatchResult` |
| `cics/input_event.py` | `InputEvent`: attention identifier, field values, cursor |
| `cics/terminal.py` | `ScreenChannel`, `InputChannel` protocols |
| `cics/cell.py` | a mutable slot holding an immutable value |
| `cics/le_stubs.py`, `cics/stubs/` | IBM Language Environment stubs (`CEEDAYS`) |
| `cics/copybooks/` | `DFHAID`, `DFHBMSCA`, `DFHEIBLK`, `DFHHANDLE` |
| `cics/builtins/` | service builtins: `flow`, `screen`, `system`, `vsam`, `interval`, `cells` |
| `cics/screen/` | `TerminalScreen` (24x80 field model), turn driver, cursor, screen payloads |
| `cics/vsam/` | `file_table`, `engine`, `browse`, `eibresp`, `format`, `dump` |
| `cics/bms/` | `generate` (symbolic copybooks), `catalog` (parsed mapsets), `attributes`, `macros/` |
| `cics/tn3270/` | the TN3270 server: `cli`, `config`, `region`, `session`, `negotiation`, `encoder`, `decoder`, `codes`, `wire` |
| `bms_copybook_gen/` | BMS macro invocations → COBOL symbolic copybook |
| `config/` | `carddemo-tn3270.toml`, `carddemo-db2-tn3270.toml` |
| `third-party/che-che4z-lsp-for-hlasm-fork/` | source of the `hlasm_export` binary |
| `tests/unit/`, `tests/integration/` | unit and integration suites |

The CICS transaction-flow graph code (`flow_map`, `flow_graph_core`, `flow_observer`,
`graph_sink`) is in `cobble/cobble/cics/`, not here.

## Compilation

1. `apply_cics_prepass` injects `COPY DFHEIBLK.` so EIB fields resolve to the real copybook.
2. ProLeap parses the COBOL. Each `EXEC CICS` block arrives as verbatim text.
3. `CicsDialectParser` strips comment lines and calls `parse_exec_cics_text`. The result is an
   `ExecCicsStatement`: a verb and a map of option name to `CicsOperand`.
4. `CicsLoweringStrategy.preprocess_program_dict` resolves `DFHRESP(x)` to a numeric literal.
5. `on_procedure_entry` emits `__cics_init_eib`. Each verb lowers to a `CallFunction` to a
   `__cics_*` builtin.

`compile_cics_program` (`cics/bootstrap.py`) wraps RedDragon's `compile_program` with the
spec from `build_cics_spec` and returns the `LinkedProgram`. Callees reached by `CALL` are
compiled and linked transitively. Each compile writes its AST, unit and linked files into a
new temporary directory; the region does not reuse them yet (red-dragon-forge-k6l).
A conversational program is compiled with `CicsLoweringStrategy(conversational=True)`, which
lowers `RECEIVE MAP` to a VM suspend. The strategy is named `cics-conversational` rather than
`cics`, so the two modes' compiled files never share a name.

## Supported verbs

| Family | Verbs | Notes |
|---|---|---|
| Program control | `RETURN [TRANSID] [COMMAREA]`, `XCTL`, `LINK`, `ABEND` | `LINK` runs a pre-compiled program synchronously and copies the COMMAREA back |
| Interval control | `START`, `RETRIEVE` | `START` queues a task that runs when the issuing task ends; `RETRIEVE` reads its `FROM` data. `INTERVAL`, `AFTER` and `AT` are parsed and recorded, not scheduled |
| Unit of work | `SYNCPOINT`, `SYNCPOINT ROLLBACK` | act on a composed SQL runtime's unit of work; VSAM writes are not undone |
| Conditions | `HANDLE CONDITION`, `IGNORE CONDITION`, `HANDLE ABEND` | `RESP` and `NOHANDLE` suppress handler dispatch |
| BMS | `SEND MAP`, `RECEIVE MAP`, `SEND TEXT` | |
| File control | `READ`, `WRITE`, `REWRITE`, `DELETE`, `STARTBR`, `READNEXT`, `READPREV`, `ENDBR` | |
| System | `ASSIGN`, `ASKTIME`, `FORMATTIME`, `INQUIRE`, `WRITEQ TD` | |
| Built-in functions | `BIF DEEDIT` | |
| No-ops | `UNLOCK`, `HANDLE AID` | `UNLOCK` has nothing to release with one task; `HANDLE AID` is not dispatched |

A verb the grammar parses but the strategy does not lower compiles to an abend with code
`UNSP`. The abend fires only if execution reaches that statement.

## Dispatch

`run_cics` runs one program for one task. It builds a fresh VM with `make_cics_initial_vm`:
the COMMAREA is argument 0 and binds the first LINKAGE 01 item. It returns a `DispatchResult`
of kind `RETURN`, `RETURN_TRANSID`, `XCTL` or `ABEND`.

`_advance_routing` decides what runs next:

| Result | Next |
|---|---|
| `RETURN_TRANSID` | the program the transaction table maps the transid to; unknown transid abends `TRNI` |
| `XCTL` | the named program, same transid; unknown program abends `PGMI` |
| `RETURN`, `ABEND` | stop |

Two drivers share that rule:

- `_run_dispatcher_with_runner` is a blocking loop used by `run_carddemo_region`. After a
  `RETURN TRANSID` it peeks at the next terminal event and leaves it on the channel for the
  next task's `RECEIVE MAP`. If no input arrives before its timeout it abends `AZCT`.
- `CicsRegion` is a turn-by-turn state machine (`start`, `step`, `done`). Tests and the
  TN3270 server drive it through `cics/screen/driver.py`.

After a task ends, either driver runs the next `START` queued for the region's terminal or for
no terminal. A `START` naming another terminal fails with `TERMIDERR`; one naming an unknown
transid fails with `TRANSIDERR`. Both are recorded on the `StartQueue`.

Screens and input travel over `ScreenChannel` and `InputChannel` (`cics/terminal.py`);
`queue.Queue` satisfies both.

## VSAM

File control runs over the system catalog in the directory the region TOML's `system` names. The
region TOML names CSD files, not datasets ([config](tn3270-config.md)).

- `cics/vsam/file_table.py` — `cics_files(system, dsnames)` resolves each CICS file, through the
  CSD's `DEFINE FILE(...) DSNAME(...)`, to its cataloged dataset, keyed by upper-cased file name.
  A DSN that is not cataloged, or is neither a KSDS nor a path, raises `FileTableError` naming
  the file and the DSN, and the region does not start.
- `cics/vsam/engine.py` — `VsamEngine(files)`, a CICS adapter over RedDragon's access-method
  drivers. The record length and key come from the dataset's catalog label. Each point
  operation opens the dataset, acts and closes it, so a write is on disk at once. A KSDS opens
  the indexed driver. A path opens `AlternateIndexDriver` over its base cluster: records come in
  alternate-key order, duplicates in primary-key order; `READ`, `READNEXT`, `READPREV` and
  `DELETE` return `DUPKEY` (RESP 15) when more records with the same alternate key follow; a
  `WRITE` or `REWRITE` through a path changes the base cluster, and one that repeats a key in a
  unique AIX returns `DUPREC`. A file not in the table returns `DISABLED`. `READ`, `READNEXT`
  and `READPREV` return a `ReadOutcome`: `RecordRead(record, resp)` when a record came back,
  `NoRecord(resp)` when none did; the builtins fill the `INTO` area only from a `RecordRead`.
  Browses keep one open driver per task, file and cursor. The adapter owns the held
  read-for-update key and the browse cursors.
- A failure the declared shape causes is logged, not raised, since the program may handle the
  condition: a `NOTFND` whose program key length differs from the declared one (on `READ`,
  `DELETE`, or `STARTBR` with `EQUAL`) logs the file, its DSN, the declared key length and
  offset, and the program's key length; a `WRITE` or `REWRITE` whose record differs from the
  declared record length logs the file, the DSN and both lengths.
- `cics/vsam/eibresp.py` — maps the driver's `AccessCondition` to EIBRESP.
- `cics/vsam/format.py` — reads a fixed-length-record file as its records.
- `cics/vsam/dump.py` — decodes a cataloged dataset through a copybook. The record length is
  the copybook's; a path's DSN dumps its base cluster's file in primary-key order:

  ```bash
  . ./bridge-env.sh
  uv run --no-sync python -m cics.vsam.dump --system DIR --dsn DSN --copybook RECORD.cpy --format block
  ```

  Flags: `--system`, `--dsn`, `--copybook`, `--record`, `--format jsonl|block`,
  `--copybook-dir`, `--jar` (defaults to `$PROLEAP_BRIDGE_JAR`).

z/OS returns duplicate alternate keys in the order they were written; cicada returns them in
primary-key order (red-dragon-forge-zqxf). Nothing locks a system directory against a batch job
running at the same time, and CICS file open and close state is not modelled
(red-dragon-forge-y6gk).

## BMS

`hlasm_export` is built by `make hlasm` from `third-party/che-che4z-lsp-for-hlasm-fork`.
`generate_symbolic_copybooks` (`cics/bms/generate.py`) runs `hlasm_export` on each `.bms` file
with `cics/bms/macros/` on SYSLIB, then `bms_copybook_gen`, and writes one `.cpy` per mapset.
`cics/bms/catalog.py` parses the same sources into the map catalog the TN3270 server paints
from.

## TN3270

`cicada-tn3270` serves a `CicsRegion` to stock 3270 emulators, one terminal and one task at a
time. It serves pseudo-conversational programs; conversational programs are not served.
It drives the same `cics/screen/driver.py` the headless tests use. `cics/tn3270/wire.py` holds
the socket code. The config format is in [tn3270-config.md](tn3270-config.md).
