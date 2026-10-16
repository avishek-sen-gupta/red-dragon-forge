# Run CardDemo over TN3270

Serve the CardDemo online tier to a 3270 emulator. The plain server covers the VSAM options. The
Db2 server adds admin options 5 and 6. Commands run from the repo root.

## Prerequisites

- `make setup` has run: both bridge JARs, `hlasm_export` and the Python workspace are built
  ([setup.md](setup.md)).
- The `vendor/carddemo` submodule is checked out.
- A 3270 emulator. `brew install x3270` installs `c3270` on macOS.
- For the Db2 server only: Docker, and `squall/.env` copied from `squall/.env.example`.

## Install the data

Both servers read and write CardDemo's VSAM data in a system directory. Install it once:

```bash
make catnip-install-carddemo SYSTEM=/tmp/carddemo-system
```

Every shipped config (`config/carddemo/env.toml`, `config/carddemo/env-db2.toml` and both region
configs) names this directory as its `system`. To use another, install into it and change
`system` in the config.

Expected: an `installed …` line per dataset, alternate index and path. The directory keeps every
change the region and any batch job make. To start clean, install into a new directory.

## Build once, run from env.toml

`forge-build` lowers and links CardDemo's online programs into a package once; `forge-run` serves
that package over TN3270 without compiling anything. Two pairs of configs ship in
`config/carddemo/`:

| Build | Package | Run | Port |
|---|---|---|---|
| `build.toml` | `/tmp/carddemo-build/carddemo.zip` | `env.toml` | 3270 |
| `build-db2.toml` | `/tmp/carddemo-db2-build/carddemo-db2.zip` | `env-db2.toml` | 3271 |

Each build lists every program CardDemo's CSD runs a transaction for, plus each callee: `CSUTLDTC`
(called by `COTRN02C` and `CORPT00C`) and the LE stub `CEEDAYS` (called by `CSUTLDTC`). The Db2
build adds `COTRTLIC` and `COTRTUPC`, the Db2 tier's CSD, and squall's `DSNTIAC` stub. Paths in
the configs are relative to `config/carddemo/`.

1. Export the JARs and `HLASM_EXPORT`, and install the data (above).

   ```bash
   . ./bridge-env.sh
   ```

2. Build the package. The first build takes a few minutes; a rebuild reuses the lowered units.

   ```bash
   uv run --no-sync forge-build config/carddemo/build.toml
   ```

   Expected: the package's path, `/tmp/carddemo-build/carddemo.zip`, as the last line.

3. Serve it.

   ```bash
   uv run --no-sync forge-run config/carddemo/env.toml
   ```

4. In a second terminal, connect.

   ```bash
   c3270 -model 3279-2-E localhost:3270
   ```

   Expected: the sign-on screen. Sign on as `USER0001` / `PASSWORD` for the main menu, or
   `ADMIN001` / `PASSWORD` for the admin menu.

For Db2, do steps 1-4 of [With Db2](#with-db2) first, then build `config/carddemo/build-db2.toml`,
run `config/carddemo/env-db2.toml` and connect to port 3271. `forge-run` connects to
`SQUALL_DB2_DSN`.

A `CALL` to a program the package does not hold abends the task with code 4038; the terminal and
the region carry on.

## Without Db2

1. Export the paths and JARs.

   ```bash
   . ./carddemo-env.sh
   ```

   Expected: no output. A warning means `CARDDEMO_HOME` has no `cbl/` directory.

2. Start the server.

   ```bash
   uv run --no-sync cicada-tn3270 --config cicada/config/carddemo-tn3270.toml --port 3270
   ```

   Expected: BMS and compile log lines, then
   `INFO cics.tn3270.cli: serving cicada/config/carddemo-tn3270.toml on 127.0.0.1:3270`.

3. In a second terminal, connect.

   ```bash
   c3270 -model 3279-2-E localhost:3270
   ```

   Expected: the CardDemo sign-on screen, in colour.

4. Sign on as `USER0001` / `PASSWORD` for the main menu, or `ADMIN001` / `PASSWORD` for the
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

   Expected: `seeded -- start the server with ...`.

4. Export the paths, JARs and DSN.

   ```bash
   . ./carddemo-env.sh
   . tests/integration/db2_env.sh
   ```

   Expected: no output.

5. Start the server.

   ```bash
   uv run --no-sync carddemo-db2-cli --config cicada/config/carddemo-db2-tn3270.toml --port 3271
   ```

   Expected: BMS and compile log lines, then
   `INFO red_dragon_forge.carddemo_db2_cli: serving on 127.0.0.1:3271 -- ready for a 3270 to connect`.

6. In a second terminal, connect.

   ```bash
   c3270 -model 3279-2-E localhost:3271
   ```

   Expected: the CardDemo sign-on screen.

7. Sign on as `ADMIN001` / `PASSWORD` and select `5` or `6`.

   Expected: the transaction type list (`5`) or maintenance screen (`6`).

The server never resets the Db2 tables. Run `make db2-seed` again to reset them.

## Menu options

| Menu | Option | Server |
|---|---|---|
| Main | `01`–`08`, `10` | both |
| Main | `09` (reports) | neither: needs JCL job submission behind the JOBS TD queue |
| Main | `11` | neither: no source ships; the menu shows "not installed" |
| Admin | `1`–`4` | both |
| Admin | `5`, `6` | Db2 server only |

Update screens save in two turns: `ENTER` validates, then `PF5` saves. Tab moves between
fields. `Ctrl+R` clears a locked keyboard. In `c3270`, `F5` sends PF5.

## Troubleshooting

- The connection drops after choosing an option. The option's program is not in the region,
  for example `09`, or admin `5`/`6` on the plain server. An `XCTL` to an unknown program
  crashes the driver instead of painting an abend (`forge-6jj`).
- The server stops at startup with `CICS file NAME: DSN is not cataloged`: the system
  directory lacks a dataset the CSD's `DEFINE FILE` names. Install the data into it first.
- Screens are green only. The emulator is a 3278 or lacks `-E`. Use `-model 3279-2-E`.
- Every Db2 screen fails with `SQL30081N`. The Db2 instance died inside a running container.
  Run `make db2-restart`.
