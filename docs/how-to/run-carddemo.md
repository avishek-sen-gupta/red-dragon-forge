# Run CardDemo over TN3270

Serve the CardDemo online tier to a 3270 emulator. `forge-build` lowers and links the programs
into a package once; `forge-run` serves the package over TN3270 without compiling anything. The
plain package covers the VSAM options. The Db2 package adds admin options 5 and 6. Commands run
from the repo root.

## Prerequisites

- `make setup` has run: both bridge JARs, `hlasm_export` and the Python workspace are built
  ([setup.md](setup.md)).
- The `vendor/carddemo` submodule is checked out.
- A 3270 emulator. `brew install x3270` installs `c3270` on macOS.
- For the Db2 package only: Docker, and `squall/.env` copied from `squall/.env.example`.

## The configs

Two pairs ship in `config/carddemo/`. Paths in them are relative to that directory.

| Build | Package | Run | Port |
|---|---|---|---|
| `build.toml` | `/tmp/carddemo-build/carddemo.zip` | `env.toml` | 3270 |
| `build-db2.toml` | `/tmp/carddemo-db2-build/carddemo-db2.zip` | `env-db2.toml` | 3271 |

Each build links every program CardDemo's CSD runs a transaction for, plus each callee:
`CSUTLDTC` (called by `COTRN02C` and `CORPT00C`) and the LE stub `CEEDAYS` (called by
`CSUTLDTC`). The Db2 build adds `COTRTLIC` and `COTRTUPC`, the Db2 tier's CSD, and squall's
`DSNTIAC` stub. A `CALL` to a program the package does not hold abends the task with code 4038;
the terminal and the region carry on. `env-db2.toml` sets `permit_missing_host_variables`, so
squall skips a host variable missing from the data layout.

## Install the data

Both packages read and write CardDemo's VSAM data in a system directory. Install it once:

```bash
make catnip-install-carddemo SYSTEM=/tmp/carddemo-system
```

Both `env.toml` files name this directory as their `system`. To use another, install into it and
change `system` in the file.

Expected: an `installed …` line per dataset, alternate index and path. The directory keeps every
change the region and any batch job make. To start clean, install into a new directory.

## Without Db2

1. Export the JARs and `HLASM_EXPORT`.

   ```bash
   . ./bridge-env.sh
   ```

   Expected: no output.

2. Build the package. The first build takes a few minutes; a rebuild reuses the lowered units.

   ```bash
   uv run --no-sync forge-build config/carddemo/build.toml
   ```

   Expected: the package's path, `/tmp/carddemo-build/carddemo.zip`, as the last line.

3. Serve it.

   ```bash
   uv run --no-sync forge-run config/carddemo/env.toml
   ```

   Expected: `INFO red_dragon_forge.run_command: serving on 127.0.0.1:3270`.

4. In a second terminal, connect.

   ```bash
   c3270 -model 3279-2-E localhost:3270
   ```

   Expected: the CardDemo sign-on screen, in colour.

5. Sign on as `USER0001` / `PASSWORD` for the main menu, or `ADMIN001` / `PASSWORD` for the
   admin menu.

   Expected: the menu for that user type.

Stop the server with `Ctrl+C`. Changes stay in the system directory and a restart keeps them.

## With Db2

1. Bring Db2 up ([db2.md](db2.md)).

   ```bash
   make db2-up
   ```

   Expected: `DB2 healthy.`

2. Check the instance answers.

   ```bash
   make db2-status
   ```

   Expected: a line starting `Db2 UP`. Exit code 1 means the instance is dead: run
   `make db2-restart`. Exit code 2 means `SQUALL_DB2_DSN` could not be set.

3. Create and seed the CardDemo Db2 tables. This drops and recreates them.

   ```bash
   make db2-seed
   ```

   Expected: `seeded -- serve it with ...`.

4. Export the JARs, `HLASM_EXPORT` and the DSN.

   ```bash
   . ./bridge-env.sh
   FORGE_ROOT=$PWD SQUALL_DIR=squall . squall/db2/dsn-env.sh
   ```

   Expected: no output.

5. Build the package.

   ```bash
   uv run --no-sync forge-build config/carddemo/build-db2.toml
   ```

   Expected: `/tmp/carddemo-db2-build/carddemo-db2.zip` as the last line.

6. Serve it. `forge-run` connects to `SQUALL_DB2_DSN` and makes its `DATABASE` current.

   ```bash
   uv run --no-sync forge-run config/carddemo/env-db2.toml
   ```

   Expected: `INFO red_dragon_forge.run_command: serving on 127.0.0.1:3271`.

7. In a second terminal, connect.

   ```bash
   c3270 -model 3279-2-E localhost:3271
   ```

   Expected: the CardDemo sign-on screen.

8. Sign on as `ADMIN001` / `PASSWORD` and select `5` or `6`.

   Expected: the transaction type list (`5`) or maintenance screen (`6`).

The server never resets the Db2 tables. Run `make db2-seed` again to reset them.

## Menu options

| Menu | Option | Package |
|---|---|---|
| Main | `01`–`08`, `10` | both |
| Main | `09` (reports) | neither: `CORPT00C` is linked, but a report needs JCL job submission behind the JOBS TD queue |
| Main | `11` | neither: no source ships; the menu shows "not installed" |
| Admin | `1`–`4` | both |
| Admin | `5`, `6` | Db2 package only |

Update screens save in two turns: `ENTER` validates, then `PF5` saves. Tab moves between
fields. `Ctrl+R` clears a locked keyboard. In `c3270`, `F5` sends PF5.

## Troubleshooting

- The connection drops after choosing an option. The option's program is not in the package,
  for example admin `5`/`6` on the plain package. An `XCTL` to an unknown program crashes the
  driver instead of painting an abend (`forge-6jj`).
- The server stops at startup with `CICS file NAME: DSN is not cataloged`: the system
  directory lacks a dataset the CSD's `DEFINE FILE` names. Install the data into it first.
- `forge-run` stops with `SQUALL_DB2_DSN is not set`: source `squall/db2/dsn-env.sh` (step 4).
- Screens are green only. The emulator is a 3278 or lacks `-E`. Use `-model 3279-2-E`.
- Every Db2 screen fails with `SQL30081N`. The Db2 instance died inside a running container.
  Run `make db2-restart`.
