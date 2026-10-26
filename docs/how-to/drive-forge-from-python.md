# Drive forge from Python

Do from Python what `catnip install`, `forge-build` and `forge-run` do from the shell: install
data, build a package, run a batch job, or assemble a CICS region and drive its screens in
process. Each section shows the call and names the test that makes it, which is the maintained
example: the commit hooks keep it green. The files the calls read are those of
[Run your own COBOL application](run-your-application.md).

Run with `. ./bridge-env.sh` sourced, from the repo root, under `uv run --no-sync`.

## Install data

```python
from pathlib import Path
from catnip.declaration import load_declaration
from catnip.install import install
from catnip.system_catalog import SystemCatalog

installed = install(
    load_declaration(Path("app/data.toml")), SystemCatalog(Path("/tmp/app-system"))
)
```

`installed` is the tuple of DSNs written, in order. A bad declaration raises `DeclarationError`
before anything is written.

Example: `tests/carddemo_system.py` (`installed_carddemo`).

## Build a package

From a `build.toml`, exactly as `forge-build`:

```python
import os
from red_dragon_forge.build_command import run

exit_status = run(["app/build.toml"], os.environ)
```

It prints the package path, or `forge-build: <reason>` on stderr and returns 1.

Or call `litter.build.build` directly, with the parser, coprocessor specs, sources, CSD tables
and mapsets built yourself. It returns the package's path.

Examples: `tests/integration/test_build_command.py` (from `build.toml`);
`cicada/tests/integration/cics/tn3270_helpers.py` (`carddemo_package`, a CICS package);
`tests/integration/test_jackal_sql_step.py` (`_package`, an SQL batch package).

## Run a batch job

`JobRunner` runs parsed JCL against a package. `builtins` is the run's builtins table:
red-dragon's core table, plus each coprocessor's entries. Composing two tables that share a
name raises.

```python
from interpreter.vm.builtins import compose_builtins, core_builtins
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.jcl.parser import parse_jcl
from jackal.missing_data import StrictAllocation
from jackal.missing_program import AbendMissingProgram
from jackal.runner import JobRunner
from jackal.unresolved import RaiseErrorStrategy
from litter.open import open_package
from squall.runtime import install_sql_runtime

sql = install_sql_runtime({"SAMPLE": backend})
runner = JobRunner(
    package=open_package(Path("/tmp/app-build/app.zip")),
    system=SystemCatalog(Path("/tmp/app-system")),
    unresolved=RaiseErrorStrategy(),
    missing_data=StrictAllocation(),
    missing_program=AbendMissingProgram(),
    program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
    builtins=compose_builtins(core_builtins(), sql.entries),
)
result = runner.run(parse_jcl(jcl_text), scratch_dir)
```

Without `EXEC SQL`, `builtins=core_builtins()` is enough. `result.steps` holds each step's outcome.

Example: `tests/integration/test_jackal_sql_step.py`, with an in-memory SQLite backend.

## Assemble a CICS region

From an `env.toml`, exactly as `forge-run`'s `[cics]` mode assembles it, including the `[sql]`
connection and the `[tolerant]` settings:

```python
from red_dragon_forge.cics_command import cics_region

region = cics_region(Path("app/env.toml"), os.environ)
```

Or from a package and a system catalog, with no env.toml:

```python
from cics.tn3270.region import assemble_region

region = assemble_region(open_package(package_path), SystemCatalog(system_dir))
```

`region` is a `ServedRegion`: its `driver` runs tasks, `catalog` holds the mapsets, and
`builtins` is the region's own table, so two regions in one process do not interfere.

Examples: `tests/integration/test_carddemo_db2_headless.py` (`region`, via `cics_region`);
`cicada/tests/integration/cics/test_region_from_package.py` (via `assemble_region`).

## Drive screens in process

No terminal or socket: start a transaction, then send keys with field values. Each turn
returns the screens the task painted; apply them to a `TerminalScreen` to read the result.

```python
from cics.dispatcher import InputEvent
from cics.screen.terminal_screen import TerminalScreen

ENTER = "\x7d"
screen = TerminalScreen()
for payload in region.driver.start("CC00").screens:
    screen = screen.apply_payload(payload, region.catalog)

turn = region.driver.respond(InputEvent(ENTER, {"ACCTSID": "00000000011"}))
for payload in turn.screens:
    screen = screen.apply_payload(payload, region.catalog)

print(screen.text())
print(screen.field("ERRMSG").content)
```

A real terminal also sends back every field whose modified flag is set, not only what was
typed; the example test's `_Terminal` does the same.

Example: `tests/integration/test_carddemo_db2_headless.py` (`_Terminal`).

## Serve over TN3270

Serve the region and connect an emulator, or drive it with `s3270`:

```python
from functools import partial
from cics.tn3270.session import run_session
from cics.tn3270.wire import bind, serve_forever

serve_forever(
    bind("127.0.0.1", 3270),
    partial(run_session, driver=region.driver, catalog=region.catalog, initial_transid="CC00"),
)
```

Examples: `cicada/tests/integration/cics/tn3270_helpers.py` (`served_session`, on a background
thread); `tests/integration/test_carddemo_forge.py` (`forge-run` in a subprocess, driven by
`s3270`).
