# cicada architecture

cicada is the CICS runtime for the RedDragon interpreter. It runs unmodified COBOL CICS
programs: pseudo-conversational transaction dispatch, VSAM file control and BMS screens. The
reference workload is the CardDemo online tier in `vendor/carddemo`.

To run CardDemo, see [run-carddemo.md](../../how-to/run-carddemo.md). The TN3270 server is
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
| `cics/strategy.py` | `CicsLoweringStrategy`: lowers each verb. Builds no builtins |
| `cics/runtime.py` | `install_cics_runtime`: the runtime surface. Builds the `__cics_*` service builtins over the region's live state and composes the region's builtins table |
| `cics/region_clock.py`, `cics/dat_form.py` | the region clock: the local time `ASKTIME` reads and the `DATFORM` a `FORMATTIME DATE` follows |
| `cics/formattime_ir.py` | `FORMATTIME` as IR: an `ABSTIME`'s calendar date and time of day, rendered per output option |
| `cics/cics_runtime.py` | `CicsRuntime`: what `install_cics_runtime` returns |
| `cics/transaction_hooks.py` | `TransactionHooks`: the task-end, syncpoint and rollback hooks, each a no-op by default |
| `cics/strategy_stores.py` | the strategy's writes into state it does not own |
| `cics/coprocessor.py` | `build_cics_spec`: the compile surface. The strategy, parser and pre-pass as one `CoprocessorSpec` |
| `cics/statements.py` | `ExecCicsStatement`, `CicsDialectParser` |
| `cics/cics_grammar/` | ANTLR4 grammar (`CICSzLexer.g4`, `CICSzParser.g4`) and generated parser |
| `cics/cics_visitor.py` | `parse_exec_cics_text(text) -> (verb, {OPTION: CicsOperand})` |
| `cics/cics_parser.py` | re-export of `parse_exec_cics_text` and `CicsOperand` |
| `cics/preprocessor.py` | `apply_cics_prepass`: injects `COPY DFHEIBLK.` after `WORKING-STORAGE SECTION.` |
| `cics/dfhresp_prepass.py` | `resolve_dfhresp_nodes`: replaces `DFHRESP(x)` nodes with numeric literals |
| `cics/conditions.py` | condition names, DFHRESP codes, the raisable set, the `UNSP` abend code |
| `cics/handler_labels.py` | numbers the paragraphs and sections `HANDLE CONDITION` and `HANDLE ABEND LABEL` can jump to, by red-dragon's procedure label |
| `cics/interval.py` | `StartQueue`, `StartRequest`: pending `START` requests |
| `cics/dispatcher.py` | `run_cics`, `_advance_routing`, `_run_dispatcher_with_runner`, `CicsRegion` |
| `cics/vm_init.py` | `make_cics_initial_vm` |
| `cics/entered_program.py`, `cics/entered_programs.py` | `EnteredProgram(name, image)`: a program with the name it is entered by; `EnteredPrograms`, a live view of a program cache handing out each one |
| `cics/tn3270/region.py` | `assemble_region`: a region from a litter package |
| `cics/csd_parse.py` | `parse_csd` (transid → program), `parse_csd_files` (file → DSNAME) |
| `cics/bootstrap.py` | `compile_cics_program`, `run_carddemo_region` |
| `cics/conversational.py` | conversational driver over the VM's suspend/resume primitive |
| `cics/types.py` | `CicsContext`, `DispatchKind`, `DispatchResult` |
| `cics/input_event.py` | `InputEvent`: attention identifier, field values, cursor |
| `cics/terminal.py` | `ScreenChannel`, `InputChannel` protocols |
| `cics/cell.py` | a mutable slot holding an immutable value |
| `cics/le_stubs.py`, `cics/stubs/` | IBM Language Environment stubs (`CEEDAYS`) |
| `cics/copybooks/` | `DFHAID`, `DFHBMSCA`, `DFHEIBLK`, `DFHHANDLE` |
| `cics/builtins/` | service builtins: `flow`, `screen`, `system`, `vsam`, `interval`, `cells`. They find working-storage fields through the program's layout `Data` (`field_positions(vm.declarations)`); `LINK` gives the inner VM the callee's declarations. |
| `cics/screen/` | `TerminalScreen` (24x80 field model), turn driver, cursor, screen payloads |
| `cics/vsam/` | `file_table`, `engine`, `key_match`, `eibresp`, `format`, `dump` |
| `cics/bms/` | `generate` (symbolic copybooks), `catalog` (parsed mapsets), `attributes`, `macros/` |
| `cics/tn3270/` | the TN3270 server: `region`, `session`, `negotiation`, `encoder`, `decoder`, `codes`, `wire` |
| `bms_copybook_gen/` | BMS macro invocations → COBOL symbolic copybook |
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
A region served over TN3270 is built differently: `forge-build` lowers each program its
`build.toml` lists once and links them into one [litter](../litter/README.md) image, with no CALL
discovery, and `assemble_region` installs the runtime over that image, its mapsets (parsed from
the package's `hlasm_export` JSON by `cics.bms.catalog.catalog_from_json`), its transaction table
and its CSD files ([config](tn3270-config.md)).
A conversational program is compiled with `build_cics_spec(conversational=True)`, which
lowers `RECEIVE MAP` to a VM suspend. The strategy is named `cics-conversational` rather than
`cics`, so the two modes' compiled files never share a name.

## Compile surface and runtime surface

The coprocessor has two entry points. `cics.coprocessor.build_cics_spec(*, conversational)` is
the compile surface: its `CicsLoweringStrategy` keeps only lowering state (the `HANDLE
CONDITION` statements the dialect parser collects, and the set of verbs it could not lower,
which a caller may pass in as `unsupported_verbs` to read back) and builds no builtins.
`cics.runtime.install_cics_runtime(context_holder, *, program_cache, transid_to_program, ...,
hooks, other_builtins)` is the runtime surface: it builds the `__cics_*` builtins over the
region's live state — the context and result holders, the program cache `LINK` and `INQUIRE`
resolve against, the transaction map `START` validates against, the TD queue, the screen and
input channels, the VSAM engine, the start queue and the `on_abend` rollback callable — and
returns a `CicsRuntime`: `entries` (cicada's own), `builtins` (the region's table: red-dragon's
core builtins, `entries` and `other_builtins`, composed with `compose_builtins`, which refuses a
name two of them define) and the start queue. `hooks` (`TransactionHooks`) fills
`__cics_task_end_hook`, `__cics_syncpoint_hook` and `__cics_rollback_hook`, one entry each, each
a no-op unless a composer passes another coprocessor's. Every task the region runs — dispatcher,
conversational, `START`, `XCTL` — is given `builtins`. `LINK` runs its target with the same
table in a new mapping, with `__cics_task_end_hook` replaced by a no-op and the abend builtins by ones that record the abend without running backout; it reaches the table through
a closure over the variable `install_cics_runtime` binds it to, so the table is built once and
never changed. No table is process-global, so two regions run side by side in one process.

## Supported verbs

| Family | Verbs | Notes |
|---|---|---|
| Program control | `RETURN [TRANSID] [COMMAREA]`, `XCTL`, `LINK`, `ABEND` | `LINK` runs a pre-compiled program synchronously and copies the COMMAREA back. An abend in the LINKed program comes back to the caller, which branches to its own `HANDLE ABEND` exit or abends the task with that program's code; backout runs once, only when no level handles it. `LINK` or `XCTL` to a program the region lacks raises `PGMIDERR` at the statement, so `RESP` sees it and an unhandled one abends the task |
| Interval control | `START`, `RETRIEVE` | `START` queues a task that runs when the issuing task ends; `RETRIEVE` reads its `FROM` data. `INTERVAL`, `AFTER` and `AT` are parsed and recorded, not scheduled |
| Unit of work | `SYNCPOINT`, `SYNCPOINT ROLLBACK` | act on a composed SQL runtime's unit of work; VSAM writes are not undone |
| Conditions | `HANDLE CONDITION`, `IGNORE CONDITION`, `HANDLE ABEND LABEL`, `HANDLE ABEND CANCEL` | `RESP` and `NOHANDLE` suppress handler dispatch. An abend the program raises (the `ABEND` verb, an unhandled condition, an unsupported verb, an unhandled abend in a program it LINKs to) transfers to the active `HANDLE ABEND LABEL` paragraph or section, and the exit is deactivated on entry; a handled abend does not run `on_abend`. `ABEND CANCEL` ignores the exit. `HANDLE ABEND RESET` and `PROGRAM` are logged no-ops. A handler target resolves as a COBOL procedure reference does: its case folds, and a paragraph name declared in several sections means the copy in the `HANDLE` statement's section |
| BMS | `SEND MAP`, `RECEIVE MAP`, `SEND TEXT`, `SEND` | A bare `SEND FROM` (terminal control) writes its data unformatted, as `SEND TEXT` does; the screen is always erased |
| File control | `READ`, `WRITE`, `REWRITE`, `DELETE`, `STARTBR`, `READNEXT`, `READPREV`, `ENDBR` | `GENERIC` keys, `KEYLENGTH` (literal or data-name), `READ GTEQ`, and `DELETE GENERIC NUMREC` are lowered to IR: the lowering cuts a generic key to `KEYLENGTH` bytes, raises `INVREQ` for a `KEYLENGTH` without `GENERIC` that is not the file's key length, and deletes generically in a loop over `READ` and `DELETE` |
| System | `ASSIGN`, `ASKTIME`, `FORMATTIME`, `INQUIRE`, `WRITEQ TD` | `ASKTIME ABSTIME` stores the region clock's local time in milliseconds since 1900. `FORMATTIME` is IR over the `ABSTIME` it is given: `YYYYMMDD`, `DDMMYYYY`, `YYMMDD`, `DDMMYY`, `MMDDYY`, `DATE` and `FULLDATE` (in the region's `DATFORM` order), `DATEFORM`, `TIME` and `YEAR`, with `DATESEP` and `TIMESEP`; any other output option is logged at lowering and its field left unchanged. The region clock (`cics.region_clock.RegionClock`) defaults to the machine's local time and `DATFORM` `MMDDYY`; `forge-run` sets it from `env.toml`'s `[cics] timezone` and `datform` |
| Built-in functions | `BIF DEEDIT` | |
| No-ops | `UNLOCK`, `HANDLE AID` | `UNLOCK` has nothing to release with one task; `HANDLE AID` is not dispatched |

A verb the grammar parses but the strategy does not lower compiles to an abend with code
`UNSP`. The abend fires only if execution reaches that statement.

## Dispatch

`run_cics` runs one program for one task, entering its image at the program named by `entry`
(red-dragon's `ProgramEntry`). A region's program cache maps each program name to the image
that holds it: in a region assembled from a package every name maps to the one image, and a
task, an `XCTL` and a `LINK` each enter it by the program's name. With
`permit_unresolved_call_targets` false, a `CALL` to a program the image lacks abends the task
with code 4038 (LE's module-not-found `U4038`): `run_cics` logs `TRANSID: <error> — abending
4038` and runs the region's `on_abend`; a `HANDLE ABEND` exit is not taken for it, because the abend is raised beneath the program (`red-dragon-forge-k0ny`). It builds a fresh VM with `make_cics_initial_vm`:
the COMMAREA is argument 0 and binds the first LINKAGE 01 item. It returns a `DispatchResult`
of kind `RETURN`, `RETURN_TRANSID`, `XCTL` or `ABEND`.

`_advance_routing` decides what runs next:

| Result | Next |
|---|---|
| `RETURN_TRANSID` | the program the transaction table maps the transid to; unknown transid abends `TRNI` |
| `XCTL` | the named program, same transid. The `XCTL` builtin holds an `XCTL` only for a program in the region's cache, so the `PGMI` abend here is reached only when the dispatcher's cache differs from the runtime's |
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

File control runs over the system catalog in the directory `env.toml`'s `[paths] system` names.
The package's file table comes from CSD files, not datasets ([server](tn3270-config.md)).

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
  A keyed `READ` or `STARTBR` positions on the first record whose key equals, or with `GTEQ`
  is at least, the key it is given, compared over that key's length, so a generic key matches
  its prefix. Browses keep one open driver per task, file and cursor. The adapter owns the held
  read-for-update key and the browse cursors.
- A failure the declared shape causes is logged, not raised, since the program may handle the
  condition: a `NOTFND` whose program key length differs from the declared one (on `READ`,
  `DELETE`, or `STARTBR` with `EQUAL`) logs the file, its DSN, the declared key length and
  offset, and the program's key length; a `WRITE` or `REWRITE` whose record differs from the
  declared record length logs the file, the DSN and both lengths.
- `cics/vsam/eibresp.py` — maps the driver's `AccessCondition` to EIBRESP.
- `cics/vsam/format.py` — reads a fixed-length-record file as its records.
- `cics/vsam/dump.py` — decodes a cataloged dataset through a copybook into frozen
  `DecodedRecord`s (`cics/vsam/decoded_record.py`): a read-only mapping from field name to a
  string or number, a tuple of them for an `OCCURS` item, or a nested record. The record length is
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

`forge-run`'s `[cics]` mode serves a `CicsRegion` to stock 3270 emulators, one terminal and one task at a
time. It serves pseudo-conversational programs; conversational programs are not served.
It drives the same `cics/screen/driver.py` the headless tests use. `cics/tn3270/wire.py` holds
the socket code. Its configuration is in [tn3270-config.md](tn3270-config.md).
