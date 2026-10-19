# Run a JCL job

Runs a CardDemo batch job through jackal. Flags are in
[../reference/jackal/cli.md](../reference/jackal/cli.md).

## Prerequisites

- `make setup` has completed at the repo root. See [setup.md](setup.md).
- The `vendor/carddemo` submodule is checked out.

## Steps

1. Export the bridge JAR paths.

   ```bash
   . ./bridge-env.sh
   ```

   Expected: no output. A `warning: … not built` line means `make setup` has not built that JAR.

2. Point jackal at the CardDemo checkout.

   ```bash
   export CARDDEMO_HOME="$PWD/vendor/carddemo"
   ```

   Expected: no output.

3. Install CardDemo's data into a system directory from its declaration,
   `config/carddemo/data.toml`: the sequential files with the record format and length
   CardDemo's README declares (its "Upload Sample Data" step), and the clusters, alternate
   indexes and paths its IDCAMS JCL defines, each cluster sorted by its primary key. The whole
   declaration is validated before anything is written; do it once per system directory.

   ```bash
   uv run catnip install config/carddemo/data.toml --system /tmp/jackal-system
   ```

   Expected: an `installed …` line per dataset, alternate index and path.
   A single dataset can be added by hand with `jackal catalog add`; see
   [the CLI reference](../reference/jackal/cli.md). The declaration format is in
   [catnip](../reference/catnip/README.md).

4. Build a [litter](../reference/litter/README.md) package of the COBOL programs the jobs run.
   jackal compiles nothing: a step's `PGM=X` enters the package's image at program `X`. List
   every program the image needs, callees and Language Environment stubs included; nothing is
   discovered. Save as `build_batch.py`:

   ```python
   import os
   from pathlib import Path

   from cobol_asg.cobol_parser import ProLeapCobolParser
   from cobol_asg.copybook_search import CopybookSearch
   from cobol_asg.subprocess_runner import RealSubprocessRunner
   from litter.build import build

   app = Path(os.environ["CARDDEMO_HOME"]) / "app"
   programs = ("CBACT01C",)
   build(
       name="carddemo-batch",
       programs=programs,
       link=programs,
       sources={p: app / "cbl" / f"{p}.cbl" for p in programs},
       parser=ProLeapCobolParser(
           runner=RealSubprocessRunner(),
           bridge_jar=os.environ["PROLEAP_BRIDGE_JAR"],
           copybooks=CopybookSearch(dirs=(app / "cpy",)),
       ),
       specs=(),
       copybook_dirs=(app / "cpy",),
       work_dir=Path("/tmp/carddemo-batch-work"),
       out_dir=Path("/tmp"),
       transactions=(),
       files=(),
       mapsets={},
       tolerant=False,
   )
   ```

   ```bash
   uv run --no-sync python build_batch.py
   ```

   Expected: `/tmp/carddemo-batch.zip`. Build once; rebuild only when a program changes.

5. Run `ACCTFILE.jcl`. It deletes, defines and loads the account VSAM KSDS with IDCAMS.

   ```bash
   uv run --no-sync jackal run vendor/carddemo/app/jcl/ACCTFILE.jcl --system /tmp/jackal-system \
     --package /tmp/carddemo-batch.zip
   ```

   Expected, with exit status 0:

   ```
   STEP05: RC=0
   STEP10: RC=0
   STEP15: RC=0
   ```

## Variations

### A job that calls cataloged procedures

`EXEC P` expands `P.prc` from the PROC library, `$CARDDEMO_HOME/app/proc` by default. Point
elsewhere with `--proclib DIR`, repeated to search several directories in order:

```bash
uv run --no-sync jackal run my.jcl --system /tmp/jackal-system --package /tmp/carddemo-batch.zip \
  --proclib ./proc --proclib ./more-procs
```

In-stream procedures (`PROC` … `PEND` in the job) need no flag.

### A job that uses a GDG

A GDG must be defined before a job can write generations of it. This pair of jobs defines one,
writes two generations, then reads them all back as one dataset. The second job is separate
because a job resolves relative generations against the GDG as it found it when it started.

```bash
printf '%-80s' 'FIRST RUN' > seed.dat
uv run --no-sync jackal catalog add DEMO.SEED --system /tmp/demo --file seed.dat --recfm FB --lrecl 80
```

`gdgload.jcl`:

```
//GDGLOAD  JOB 1
//DEFINE   EXEC PGM=IDCAMS
//SYSIN    DD *
  DEFINE GDG (NAME(DEMO.HIST) LIMIT(5))
/*
//GEN1     EXEC PGM=IDCAMS
//IN       DD DSN=DEMO.SEED,DISP=SHR
//OUT      DD DSN=DEMO.HIST(+1),DISP=(NEW,CATLG),RECFM=FB,LRECL=80
//SYSIN    DD *
  REPRO INFILE(IN) OUTFILE(OUT)
/*
//GEN2     EXEC PGM=IDCAMS
//IN       DD DSN=DEMO.SEED,DISP=SHR
//OUT      DD DSN=DEMO.HIST(+2),DISP=(NEW,CATLG),RECFM=FB,LRECL=80
//SYSIN    DD *
  REPRO INFILE(IN) OUTFILE(OUT)
/*
```

`gdgread.jcl` reads every generation (a DD naming the base with no generation number), newest
first unless `GDGORDER=FIFO` is coded, and deletes them:

```
//GDGREAD  JOB 1
//ALL      EXEC PGM=IDCAMS
//IN       DD DSN=DEMO.HIST,DISP=(OLD,DELETE)
//OUT      DD DSN=DEMO.ALL,DISP=(NEW,CATLG),RECFM=FB,LRECL=80
//SYSIN    DD *
  REPRO INFILE(IN) OUTFILE(OUT)
/*
```

```bash
uv run --no-sync jackal run gdgload.jcl --system /tmp/demo --package /tmp/carddemo-batch.zip
ls /tmp/demo/datasets
uv run --no-sync jackal run gdgread.jcl --system /tmp/demo --package /tmp/carddemo-batch.zip
ls /tmp/demo/datasets
```

Expected: `DEFINE: RC=0`, `GEN1: RC=0` and `GEN2: RC=0`; then `DEMO.HIST.G0001V00`,
`DEMO.HIST.G0002V00` and `DEMO.SEED`; then `ALL: RC=0`; then `DEMO.ALL` (160 bytes, both
generations) and `DEMO.SEED`.

### A program that CALLs through a variable

A `CALL WS-PGM` reaches any program the image holds, so list the callee in both `programs`
and `link`. A callee left out of `link` is not in the image: a CALL through a data-name stops the
run with `UnresolvedProgramError: CALL resolved at run time to __entry_CALLSUB, but nothing in
this run unit is registered under it`. A CALL by a quoted name does the same under `forge-run`;
under `jackal run` it goes to red-dragon's unresolved-call resolver, which returns a symbolic
result instead of running anything (`JobRunner(..., permit_unresolved_call_targets=True)`, the
default).

### A Db2 step (IKJEFT01 with DSN RUN PROGRAM)

The `jackal` command composes no SQL support. A program with `EXEC SQL` runs under
[`forge-run`](../reference/forge/run.md) with `[jcl]` and `[sql]`, or through the Python
API: built into a package with squall's coprocessor, and run with squall's `__exec_sql` composed into the runner's builtins table. A Db2 batch program
does not `CONNECT`; DSN attaches it to its subsystem, which `initial_connector` stands in for. This runs a SYSTSIN of
`DSN SYSTEM(DB2P)` / `RUN PROGRAM(RPTPGM) PLAN(RPTPLAN)` against an SQLite database:

```python
import os, sqlite3, tempfile
from pathlib import Path

from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.copybook_search import CopybookSearch
from cobol_asg.subprocess_runner import RealSubprocessRunner
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.jcl.parser import parse_jcl
from jackal.missing_data import StrictAllocation
from jackal.missing_program import AbendMissingProgram
from jackal.runner import JobRunner
from catnip.system_catalog import SystemCatalog
from jackal.unresolved import RaiseErrorStrategy
from squall.backends.sqlite import SqliteBackend
from squall.connector import NamedDbConnector
from squall.coprocessor import build_sql_spec
from squall.runtime import install_sql_runtime
from interpreter.vm.builtins import compose_builtins, core_builtins
from litter.build import build
from litter.open import open_package

package = build(
    name="db2job",
    programs=("RPTPGM",),
    link=("RPTPGM",),
    sources={"RPTPGM": Path("cbl/RPTPGM.cbl")},
    parser=ProLeapCobolParser(
        runner=RealSubprocessRunner(),
        bridge_jar=os.environ["PROLEAP_BRIDGE_JAR"],
        copybooks=CopybookSearch(dirs=(Path("cpy"),)),
    ),
    specs=(build_sql_spec(),),
    copybook_dirs=(Path("cpy"),),
    work_dir=Path("/tmp/db2job-work"),
    out_dir=Path("/tmp"),
    transactions=(),
    files=(),
    mapsets={},
    tolerant=False,
)
conn = sqlite3.connect("bank.db")
sql = install_sql_runtime({"DB2P": SqliteBackend(conn)}, NamedDbConnector("DB2P"))
runner = JobRunner(
    package=open_package(package),
    system=SystemCatalog(Path("/tmp/demo")),
    unresolved=RaiseErrorStrategy(),
    missing_data=StrictAllocation(),
    missing_program=AbendMissingProgram(),
    program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
    builtins=compose_builtins(core_builtins(), sql.entries),
)
with tempfile.TemporaryDirectory() as scratch:
    result = runner.run(parse_jcl(Path("db2job.jcl").read_text()), Path(scratch))
for step in result.steps:
    print(f"{step.name}: {step.outcome.rendered()}")
```

Run it with `uv run --no-sync python` after step 1. `squall.backends.db2.Db2Backend` serves a
real Db2 instead; see [db2.md](db2.md). The step's return code is the highest of its programs';
an abend in one gives 12 under IKJEFT01 and `S04C` under IKJEFT1A/1B.

## Troubleshooting

- `the following arguments are required: --package`: pass the package step 4 built.
- A step ends `RC=0` with a warning `no program X; stubbed with RC 0`: the package does not
  hold `X`. Add it to `programs` in step 4 and rebuild.
- A step ends `allocation failed (DD …: DATASET_NOT_FOUND)`, or a warning says an empty dataset
  stood in for one: the dataset is not in the system directory. Add it with
  `jackal catalog add`, or run step 3.
- `DSN: from: … does not exist`, or another `DSN: field: …` line from step 3: the declaration
  does not match the seed files. Change the named field; nothing was installed.
- `KeyError: 'JCL_BRIDGE_JAR'`: step 1 was not run in this shell.
- `No module named jackal.__main__`: use `uv run --no-sync jackal`, not `python -m jackal`.
- `jackal: S1: PROC P is in no proclib`: `P.prc` is not in the PROC library. Pass
  `--proclib`, or set `CARDDEMO_HOME`.
- `UnresolvedProgramError: CALL resolved at run time to …`: the program is CALLed through a
  variable, which a package does not link (red-dragon-forge-8urg).
- A step ends `abended Unnnn`: the program called LE's `CEE3ABD` with that user code.
