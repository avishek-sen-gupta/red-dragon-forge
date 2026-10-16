# forge-run

`forge-run ENV_TOML` runs a [litter](../litter/README.md) package as `env.toml` says: one program,
a JCL job, or a CICS region served over TN3270. A run never parses, lowers or links. It is
`red_dragon_forge.run_command:main`. Design: [the forge runner spec](../../superpowers/specs/2026-10-15-forge-runner-design.md) (D6–D9).

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
max_steps = 500000                  # optional; jackal's step budget by default

[plain.files]                       # ASSIGN name = cataloged dataset
ACCTFILE = "AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS"

[jcl]
job = "jcl/READACCT.jcl"
proclib_dirs = ["proc"]

[cics]
initial_transid = "CC00"
host = "127.0.0.1"                  # default
port = 3270                         # default
```

The section present picks the mode.

| Mode | What runs | Output and exit status |
|---|---|---|
| `[plain]` | a one-step job built in code: `EXEC PGM=<program>` with one `DD DSN=<dataset>,DISP=SHR` per `[plain.files]` entry, run by jackal with its CLI's defaults | `RC=<n>`; exit 1 on an abend, else 0 |
| `[jcl]` | the job, run by jackal against the package | jackal's per-step lines and exit status ([jackal CLI](../jackal/cli.md)) |
| `[cics]` | a region assembled from the package (`cics.tn3270.region.assemble_region`), served until interrupted | |

`[plain]` describes no dataset: each one is cataloged in the system directory, which supplies its
record format and length.

`[tolerant] permit_unresolved_call_targets` is passed to every program run in every mode: the
jackal step, the CICS task, and a program it LINKs to. Off, the default, a `CALL` to a program
the image does not hold stops a `[plain]` or `[jcl]` run: `forge-run: CALL to __entry_X, but
nothing in this run unit is registered under it`, exit 1. Under `[cics]` it abends the task with
code 4038, as LE's "module not found" (`CEE3501S`, `U4038`) does: the abend path runs (backout,
`Transaction abended: 4038` on the terminal) without driving HANDLE ABEND, and the terminal and
the region carry on. On, red-dragon's unresolved-call resolver returns a
symbolic result and the program runs on. `permit_missing_host_variables` is squall's runtime
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
| env.toml missing or not TOML | `<path>: No such file or directory`, or `env.toml: <TOML error>` |
| a key or value env.toml does not define | `env.toml: <location>: <message>` (a top-level `tolerant` is one) |
| the package missing or not a zip | `env.toml: package <path>: <reason>` |
| `[sql]` with `SQUALL_DB2_DSN` unset | `SQUALL_DB2_DSN is not set` |
| a DSN with no `DATABASE=` | `SQUALL_DB2_DSN names no DATABASE` |
| a `[jcl]` job file that cannot be read | `<path>: <reason>` |
| a CICS file whose dataset is not cataloged | `CICS file NAME: DSN is not cataloged` |
| a CALL to a program the image lacks (`[plain]`, `[jcl]`) | `CALL to __entry_X, but nothing in this run unit is registered under it` |

Every configuration fault stops the run with exit 1 before any runtime is installed; an
unresolved CALL stops it when the CALL runs.

## Tests

`tests/unit/test_env_config.py` covers mode selection and each fault;
`tests/integration/test_run_command.py` covers `[plain]` against the equivalent one-step
`[jcl]` job, a multi-step `[jcl]` job against `jackal run`, the CardDemo sign-on screen served
by `[cics]` over TN3270, and a `[plain]` Db2 program (needs `SQUALL_DB2_DSN`).
