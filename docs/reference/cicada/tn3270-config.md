# cicada TN3270 server and config

`cicada-tn3270` serves a CICS region to 3270 emulators over TN3270. `carddemo-db2-cli` serves
the same kind of region with squall's SQL coprocessor composed in. Both read the config format
below. Steps to run them are in [run-carddemo.md](../../how-to/run-carddemo.md).

## CLI

```bash
uv run --no-sync cicada-tn3270 --config CONFIG --system DIR [--host HOST] [--port PORT]
uv run --no-sync carddemo-db2-cli --config CONFIG --system DIR [--host HOST] [--port PORT]
```

| Flag | Default | Meaning |
|---|---|---|
| `--config` | required | path to the TOML config |
| `--system` | required | the system directory: [catnip](../catnip/README.md)'s catalog and the datasets' bytes. Fill it with `catnip install` first |
| `--host` | `127.0.0.1` | address to listen on |
| `--port` | `3270` | port to listen on |

Environment:

| Variable | Needed by | Purpose |
|---|---|---|
| `PROLEAP_BRIDGE_JAR` | both | compiles the COBOL; exported by `bridge-env.sh` |
| `CARDDEMO_HOME`, `FORGE_ROOT` | the shipped configs | expanded in `${VAR}` paths; exported by `carddemo-env.sh` |
| `SQUALL_DB2_DSN` | `carddemo-db2-cli` | Db2 connection; exported by `tests/integration/db2_env.sh` |

At startup the server resolves every CICS file the CSDs define to a cataloged dataset, compiles
every program in the config, then logs a line starting `serving` that names the host and port.
A CICS file whose DSN is not cataloged, or is neither a KSDS nor a path, stops it with
`CICS file NAME: DSN is not cataloged` or `CICS file NAME: DSN is not a KSDS or path`. The
region reads and writes the cataloged datasets in place: its writes survive a restart, and a
batch job run against the same system directory sees them. Nothing locks the directory, so do
not run a job against it while the region is serving (red-dragon-forge-y6gk).

## Config file

The config is TOML, loaded by `load_config` in `cicada/cics/tn3270/config.py` into a
`RegionConfig`. Path values expand `${VAR}` and `~`. An unset variable is a `ConfigError`.

Shipped configs:

- `cicada/config/carddemo-tn3270.toml` — the CardDemo VSAM tier.
- `cicada/config/carddemo-db2-tn3270.toml` — adds the CardDemo Db2 source tree, for
  `carddemo-db2-cli`.

### `[paths]`

| Key | Type | Meaning |
|---|---|---|
| `source_dirs` | list of paths | directories searched for `<PROGRAM>.cbl`; the first hit wins |
| `copybook_dirs` | list of paths | copybook search path |
| `bms_dirs` | list of paths | `.bms` mapset sources; an earlier directory's mapset wins |
| `hlasm_export` | path | the `hlasm_export` binary built by `make hlasm` |
| `csd_files` | list of paths | CSD files; each `DEFINE FILE(NAME) ... DSNAME(DSN)` makes `NAME` a CICS file over the cataloged dataset `DSN`. A later file's definition of the same name wins |
| `copybook_exts` | list of strings, optional | copybook extensions passed to the bridge as `-copybook-ext`; empty uses the bridge's defaults |

### `[region]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `initial_transid` | string | `""` | transaction started when a terminal connects |
| `min_commarea_len` | int | `0` | each follow-on task's COMMAREA is padded with nulls to this length |
| `programs` | list of strings | `[]` | programs to compile in addition to those named in `[transactions]` |

### `[transactions]`

One entry per transaction: `TRANSID = "PROGRAM"`. This is the region's transaction table, the
equivalent of the CSD's `DEFINE TRANSACTION`. Every program named here is compiled.

### CICS files

The config holds no record lengths or key positions. A CICS file's record length and key come
from its dataset's catalog label: a KSDS's own key, or for a path, its alternate index's key over
the base cluster's records. The [cicada architecture page](architecture.md#vsam) describes file
control.

## Terminals

Any IBM-3278 or IBM-3279 model 2 to 5 is accepted, with or without `-E`. The server paints the
24x80 default partition. Colour is sent only to a terminal type ending in `-E`, so use a 3279
with `-E` for colour, for example `c3270 -model 3279-2-E localhost:3270`.
