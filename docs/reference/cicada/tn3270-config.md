# cicada TN3270 server and config

`cicada-tn3270` serves a CICS region to 3270 emulators over TN3270. `carddemo-db2-cli` serves
the same kind of region with squall's SQL coprocessor composed in. Both read the config format
below. Steps to run them are in [run-carddemo.md](../../how-to/run-carddemo.md).

## CLI

```bash
uv run --no-sync cicada-tn3270 --config CONFIG [--host HOST] [--port PORT]
uv run --no-sync carddemo-db2-cli --config CONFIG [--host HOST] [--port PORT]
```

| Flag | Default | Meaning |
|---|---|---|
| `--config` | required | path to the TOML config |
| `--host` | `127.0.0.1` | address to listen on |
| `--port` | `3270` | port to listen on |

Environment:

| Variable | Needed by | Purpose |
|---|---|---|
| `PROLEAP_BRIDGE_JAR` | both | compiles the COBOL; exported by `bridge-env.sh` |
| `CARDDEMO_HOME`, `FORGE_ROOT` | the shipped configs | expanded in `${VAR}` paths; exported by `carddemo-env.sh` |
| `SQUALL_DB2_DSN` | `carddemo-db2-cli` | Db2 connection; exported by `tests/integration/db2_env.sh` |

At startup the server compiles every program in the config, then logs a line starting
`serving` that names the host and port. It seeds VSAM into a temporary directory, so the
source data is never written and a restart resets it.

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
| `data_dir` | path | directory holding the EBCDIC flat files named in `[datasets]` |
| `hlasm_export` | path | the `hlasm_export` binary built by `make hlasm` |
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

### `[datasets.NAME]`

One table per VSAM file. `NAME` is the CICS file name and is upper-cased.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `file` | string | required | flat file under `data_dir` to seed from |
| `record_length` | int | required | fixed record length in bytes |
| `key_offset` | int | `0` | key offset; non-zero makes the file a read-only alternate-key path |
| `key_length` | int | `0` | key length in bytes |

## Terminals

Any IBM-3278 or IBM-3279 model 2 to 5 is accepted, with or without `-E`. The server paints the
24x80 default partition. Colour is sent only to a terminal type ending in `-E`, so use a 3279
with `-E` for colour, for example `c3270 -model 3279-2-E localhost:3270`.
