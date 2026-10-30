# forge-run

`forge-run ENV_TOML` runs a [litter](../litter/README.md) package as `env.toml` says: one program,
a JCL job, or a CICS region served over TN3270. A run never parses, lowers or links. It is
`red_dragon_forge.run_command:main`, which imports only its mode's command: `plain_command`,
`jcl_command` or `cics_command`. Design: [the forge runner spec](../../superpowers/specs/2026-10-15-forge-runner-design.md) (D6–D9).

```bash
. ./bridge-env.sh
uv run --no-sync forge-run app/env.toml
```

## env.toml

Relative paths are relative to the file's directory.

```toml
package = "out/carddemo.zip"

[tolerant]                          # each false unless set
permit_unresolved_call_targets = false   # a CALL to a program the image lacks runs symbolically
permit_missing_host_variables = false    # squall skips host variables missing from the layout

[paths]
system = "/tmp/carddemo-system"     # catnip's system directory

[sql]                               # required when the package was built with sql

# exactly one of [plain], [jcl], [cics]

[plain]
program = "CBACT01C"
max_steps = 500000                  # optional; the default

[plain.files]                       # ASSIGN name or DDNAME = cataloged dataset
ACCTFILE = "AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS"

[jcl]
job = "jcl/READACCT.jcl"
proclib_dirs = ["proc"]

[cics]
initial_transid = "CC00"
host = "127.0.0.1"                  # default
port = 3270                         # default
timezone = "Asia/Kolkata"           # IANA name; the machine's local time when omitted
datform = "MMDDYY"                  # default; or DDMMYY, YYMMDD
```

The section present picks the mode.

| Mode | What runs | Output and exit status |
|---|---|---|
| `[plain]` | the image entered at `program`, with `max_steps` as its budget; no job, DD or disposition | one line: `RC <n>`, exit 0; or the abend (`U1234`), exit 1; or `budget exhausted after <n> steps`, exit 1 |
| `[jcl]` | the job, run by jackal against the package | jackal's per-step lines and exit status ([jackal CLI](../jackal/cli.md)); an HLASM step gets the host clock, no DD definitions and its own `PARM=` |
| `[cics]` | a region assembled from the package (`cics.tn3270.region.assemble_region`), served until interrupted | |

`[cics] timezone` is the zone `ASKTIME` reads the region's local time in, and `datform` is the
region's `DATFORM`, the order of a `FORMATTIME DATE` or `FULLDATE`. An unknown zone stops the
run: `env.toml: cics.timezone: invalid timezone: Mars/Base`.

`[plain]` describes no dataset: each `[plain.files]` entry names one cataloged in the system
directory, which supplies its record format and length. A name not in the catalog stops the run
before the program starts; plain mode never creates a dataset. A dataset cataloged with a pending
label takes its label from the FD on its first OPEN OUTPUT or EXTEND. Each entry is also an
HLASM DD of that name: a sequential dataset supplies RECFM and LRECL from its label, a
pending one supplies neither (a DCB with no LRECL abends S013) and is labelled F or V at its first OPEN OUTPUT or EXTEND, from the
DCB. Any other dataset, or a DDNAME with no entry, fails the OPEN with R15 8. An abend wins over the
return code. An HLASM entry's return code is R15; an HLASM abend (`ABEND 42` gives `U0042`) is
reported whichever language the entry is. A RETURN-CODE left unknown by a tolerated CALL reports `RC 0`, with a warning on
stderr: `forge-run: warning: P's RETURN-CODE is unknown; reported as 0`.

`[tolerant] permit_unresolved_call_targets` is passed to every program run in every mode: the
`[plain]` program, the jackal step, the CICS task, and a program it LINKs to. Off, the default,
a `CALL` to a program the image does not hold stops a `[plain]` or `[jcl]` run:
`forge-run: CALL to __entry_X, but nothing in this run unit is registered under it`, exit 1.
Under `[cics]` it abends the task with code 4038, as LE's "module not found" (`CEE3501S`,
`U4038`) does: the abend path runs (backout, `Transaction abended: 4038` on the terminal) without
driving HANDLE ABEND, and the terminal and the region carry on. On, red-dragon's unresolved-call
resolver returns a symbolic result and the program runs on. `permit_missing_host_variables` is squall's runtime
tolerance: a host variable missing from the data layout is skipped rather than raised.

With `[sql]`, the run connects to `SQUALL_DB2_DSN` (`squall/db2/dsn-env.sh` exports it) before
anything runs, registers the connection under the DSN's `DATABASE` name and makes it current
from the start, as a `DSN RUN` or CICS attachment thread is; an abending CICS task rolls it
back. `EXEC SQL CONNECT TO` another location is red-dragon-forge-b114.

| Fault | Message (on stderr, after `forge-run: `) |
|---|---|
| no mode section | `env.toml: exactly one of [plain], [jcl], [cics] is required; found none` |
| more than one | `env.toml: exactly one of [plain], [jcl], [cics] is required; found [plain], [jcl]` |
| `[cics]` without `initial_transid` | `env.toml: [cics] initial_transid is required` |
| a package built with sql, no `[sql]` | `env.toml: [sql] is required: out/app.zip was built with sql` |
| a `[plain]` program the image lacks | `env.toml: program X is not in out/app.zip` |
| an `initial_transid` the package lacks | `env.toml: transaction X is not in out/app.zip` |
| an `initial_transid` whose program is not linked | `env.toml: transaction X runs P, which is not in out/app.zip` |
| env.toml missing or not TOML | `<path>: No such file or directory`, or `env.toml: <TOML error>` |
| a key or value env.toml does not define | `env.toml: <location>: <message>` (a top-level `tolerant` is one) |
| the package missing or not a zip | `env.toml: package <path>: <reason>` |
| `[sql]` with `SQUALL_DB2_DSN` unset | `SQUALL_DB2_DSN is not set` |
| a DSN with no `DATABASE=` | `SQUALL_DB2_DSN names no DATABASE` |
| a `[plain.files]` dataset not cataloged | `[plain.files] NAME: DSN is not cataloged` |
| a `[jcl]` job file that cannot be read | `<path>: <reason>` |
| a CICS file whose dataset is not cataloged | `CICS file NAME: DSN is not cataloged` |
| a CALL to a program the image lacks (`[plain]`, `[jcl]`) | `CALL to __entry_X, but nothing in this run unit is registered under it` |

Every configuration fault stops the run with exit 1 before any runtime is installed; an
uncataloged `[plain.files]` dataset stops it before the program starts; an unresolved CALL
stops it when the CALL runs.

## Tests

`tests/unit/test_env_config.py` covers mode selection and each fault;
`tests/integration/test_plain_mode.py` covers each `[plain]` outcome and refusal, labelling on
first OPEN, two programs selecting the same name, and a run loading neither jackal nor cics;
`tests/integration/test_hlasm_dd_plain.py` covers an HLASM copy between DDs, FB and VB, under a
COBOL caller with its own file, and an unbound or pending input;
`tests/integration/test_run_command.py` covers `[plain]` against the equivalent one-step `[jcl]`
job, a multi-step `[jcl]` job against `jackal run`, the CardDemo sign-on screen served by `[cics]`
over TN3270, a `[jcl]` run loading no cics, a `[cics]` region loading no jackal, and a `[plain]`
Db2 program (needs `SQUALL_DB2_DSN`).
`tests/integration/test_carddemo_forge.py` builds CardDemo's checked-in `config/carddemo/build.toml`
and `build-db2.toml` (exact programs and CSD transactions), serves each with its `env.toml`, and
drives it with `s3270`: a user signs on and views an account; an admin reaches the Db2
transaction-type list (needs `SQUALL_DB2_DSN`); the Db2 package's region holds both trees'
mapsets. `tests/integration/test_carddemo_db2_headless.py` drives the Db2 screens in process
through `cics_region`, the region `[cics]` serves. `tests/unit/test_cics_sql_wiring.py` covers
`[sql]`'s commit at SYNCPOINT and rollback on abend.
