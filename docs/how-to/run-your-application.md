# Run your own COBOL application

Take an application's COBOL sources, copybooks and data, and run it: one batch program, a JCL
job, or a CICS region served over TN3270. You write three files and run three commands:

| File | Says | Command |
|---|---|---|
| `data.toml` | the datasets the application reads and writes | `catnip install` |
| `build.toml` | which programs to lower and link into one package | `forge-build` |
| `env.toml` | how to run the package, and which tolerances to allow | `forge-run` |

CardDemo's checked-in set, in `config/carddemo/`, is a worked example of all three
([Run CardDemo over TN3270](run-carddemo.md)). To do the same from Python, see
[Drive forge from Python](drive-forge-from-python.md). Paths inside each file are relative to that
file's directory. Commands run from the repo root.

## Prerequisites

- `make setup` has run ([setup.md](setup.md)).
- `. ./bridge-env.sh` in the shell that builds: it exports `PROLEAP_BRIDGE_JAR` and
  `HLASM_EXPORT`.
- The application's data as EBCDIC record files: fixed-length records, or variable-length with
  the RDW inline.
- For CICS: its BMS mapsets and its CSD (`DEFINE TRANSACTION`, `DEFINE FILE`).
- For Db2: Docker, `squall/.env` copied from `squall/.env.example`, and the application's DDL.

## 1. Declare and install the data

Every dataset a program opens must be cataloged in a system directory, with its record format
and length. Write a `data.toml` naming each one; the format is in
[catnip](../reference/catnip/README.md#the-declaration).

```toml
data_dir = "data"                    # seed files, relative to this file

[[sequential]]
dsn   = "APP.ORDERS.DAILY"
from  = "ORDERS.DAILY.PS"
recfm = "FB"
lrecl = 120

[[ksds]]
dsn        = "APP.CUSTOMER.KSDS"
from       = "CUSTOMER.PS"           # omit to catalog the cluster empty
lrecl      = 300
key_offset = 0
key_length = 10

[[ksds.aix]]
dsn        = "APP.CUSTOMER.AIX"
path       = "APP.CUSTOMER.AIX.PATH"
key_offset = 10
key_length = 25
unique     = false

[[gdg]]
name    = "APP.ORDERS.HISTORY"
limit   = 5
empty   = "NOEMPTY"
scratch = "SCRATCH"
order   = "LIFO"
```

The record layouts come from the copybooks; the clusters, AIXs and GDG bases from the
application's IDCAMS JCL. Then install:

```bash
uv run --no-sync catnip install app/data.toml --system /tmp/app-system
```

Expected: an `installed …` line per dataset, AIX, path and GDG base. The whole declaration is
validated first; a bad entry names the dataset and field and writes nothing. Install into a new
directory to start clean.

## 2. Build the package

`build.toml` names the programs to lower, per language (`[cobol]`, `[hlasm]`), and the programs
to link into the one image
([reference](../reference/forge/build.md)).

```toml
[cobol]
source_dirs = ["cbl", "../../cicada/cics/stubs", "../../squall/squall/stubs"]
source_exts = [".cbl", ".CBL"]
copybook_dirs = ["cpy", "cpy-bms", "../../squall/squall/copybooks"]
copybook_exts = ["", "cpy", "CPY"]
programs = ["APPMENU", "APPORDR", "APPDATE", "CEEDAYS", "DSNTIAC"]

[build]
name = "app"
link = ["APPMENU", "APPORDR", "APPDATE", "CEEDAYS", "DSNTIAC"]
coprocessors = ["cics", "sql"]
out_dir = "/tmp/app-build"

[cics]
bms_dirs = ["bms"]
csd_files = ["csd/APP.CSD"]
```

```bash
uv run --no-sync forge-build app/build.toml
```

Expected: the package's path as the last line.

### Coprocessors

| The programs contain | `coprocessors` |
|---|---|
| `EXEC SQL` | `sql` |
| `EXEC CICS`, pseudo-conversational (`RETURN TRANSID`) | `cics` |
| `EXEC CICS` with `RECEIVE MAP` waiting mid-task | `cics-conversational`; it builds, but `forge-run` cannot serve it yet (red-dragon-forge-ffit) |

### What must be linked

Nothing is discovered. A program is in the image only if `link` names it, and `link` may name
only what `programs` lists.

| Program | Link it when | Source directory | Checked |
|---|---|---|---|
| `DSNTIAC` | `coprocessors` has `sql` | `squall/squall/stubs` | yes: the build stops with `coprocessor sql requires DSNTIAC in [build] link` |
| `CEEDAYS` | a program does `CALL 'CEEDAYS'` | `cicada/cics/stubs` | no |
| `CEE3ABD` | a program does `CALL 'CEE3ABD'` | `vendor/red-dragon/interpreter/cobol/le_stubs` | no |
| each `CALL` target | a program CALLs it, by literal or identifier | the application's | no |
| each `LINK`/`XCTL` target | a CICS program transfers to it | the application's | no |
| each CSD transaction's program | the transaction should run | the application's | only the initial transaction, at `forge-run` startup |

With `sql`, add `squall/squall/copybooks` to `copybook_dirs` if the application does not ship
its own `SQLCA`.

To find the callees, search the sources:

```bash
rg -n "CALL +'|CALL +[A-Z]|PROGRAM *\(" app/cbl
```

A missing callee does not fail the build. It fails the run, as the next section describes.

### Compile-time tolerance

`[build] tolerant = true` skips a statement red-dragon cannot lower, with a `skipped <Statement>:
<reason>` warning, instead of stopping the build. The program then runs without that statement.
Leave it `false` until a build stops on a statement you have decided to live without.

## 3. Run it

`env.toml` names the package, the system directory, and exactly one mode
([reference](../reference/forge/run.md)).

```toml
package = "/tmp/app-build/app.zip"

[tolerant]
permit_unresolved_call_targets = false
permit_missing_host_variables = false

[paths]
system = "/tmp/app-system"

[sql]                                # required when the package was built with sql

[cics]                               # or [plain] / [jcl]
initial_transid = "AP00"
port = 3270
```

| Mode | Use it for | Section |
|---|---|---|
| `[plain]` | one batch program, its files mapped to cataloged datasets | `program`, `[plain.files]` |
| `[jcl]` | a JCL job | `job`, `proclib_dirs` |
| `[cics]` | a CICS region over TN3270 | `initial_transid`, `host`, `port` |

```bash
uv run --no-sync forge-run app/env.toml
```

For `[cics]`, connect with `c3270 -model 3279-2-E localhost:3270`.

### Run-time tolerances

Both are off unless set. Turn one on only when you know what the run gives up.

| Tolerance | Off (default) | On |
|---|---|---|
| `permit_unresolved_call_targets` | a `CALL` to a program the image lacks stops a `[plain]`/`[jcl]` run with `CALL to __entry_X, but nothing in this run unit is registered under it`; under `[cics]` it abends the task with 4038 and the region carries on | the CALL returns a symbolic result and the program runs on, with whatever that result feeds now unknown |
| `permit_missing_host_variables` | squall raises on a host variable missing from the program's data layout | squall skips it; the statement runs without that variable |

The first is the usual sign that `link` is missing a program: fix `link` rather than turn it on.

## 4. With Db2

1. Start Db2 and export the DSN ([db2.md](db2.md)).

   ```bash
   make db2-up
   . ./bridge-env.sh
   FORGE_ROOT=$PWD SQUALL_DIR=squall . squall/db2/dsn-env.sh
   ```

   Expected: `DB2 healthy.`, then no output.

2. Create the application's tables in the database `SQUALL_DB2_DSN` names (`MOJO`), from its
   DDL. `make db2-seed` seeds CardDemo's schema only.

3. Build with `sql` in `coprocessors` and `DSNTIAC` linked, and put `[sql]` in `env.toml`.
   `forge-run` connects before anything runs and makes that database current. An abending CICS
   task rolls back; `SYNCPOINT` commits.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `CICS file NAME: DSN is not cataloged` | declare and install that dataset (step 1) |
| `program X is in no [cobol] source_dirs as .cbl` | add the directory to `source_dirs`, or the extension to `source_exts` |
| `transaction X runs P, which is not in <package>` | add `P` to its language's `programs` and to `link`, then rebuild |
| `CALL to __entry_X, but nothing in this run unit is registered under it`, or a task abending 4038 | add `X` to its language's `programs` and to `link`, then rebuild |
| The terminal drops after choosing an option | the option `XCTL`s to a program not linked (forge-6jj) |
| A copybook or `.bms` edit has no effect | delete `<out_dir>/work/` and rebuild; unit reuse ignores copybook contents |
| `[sql] is required: … was built with sql` | add `[sql]` to `env.toml` |
| `SQUALL_DB2_DSN is not set` | source `squall/db2/dsn-env.sh` (step 4) |
