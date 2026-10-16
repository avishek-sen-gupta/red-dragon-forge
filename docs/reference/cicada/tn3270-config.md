# cicada TN3270 server

cicada's TN3270 server serves a CICS region to 3270 emulators. A region is assembled from a
[litter](../litter/README.md) package: [`forge-build`](../forge/build.md) builds the package from
a `build.toml` with `coprocessors = ["cics"]` (and `"sql"` for Db2), and
[`forge-run`](../forge/run.md) serves it from an `env.toml` with a `[cics]` section. Steps to run
CardDemo are in [run-carddemo.md](../../how-to/run-carddemo.md); its configs are in
`config/carddemo/`.

## What goes where

| Setting | File | Section |
|---|---|---|
| programs lowered and linked, coprocessors | `build.toml` | `[build]` |
| source, copybook and stub directories | `build.toml` | `[paths]` |
| BMS mapset directories, CSD files | `build.toml` | `[cics]` |
| the system directory | `env.toml` | `[paths] system` |
| first transaction, host, port | `env.toml` | `[cics]` |
| the Db2 connection | `env.toml` | `[sql]`, with `SQUALL_DB2_DSN` |

Nothing is discovered: every program a transaction program CALLs, and every stub it reaches, is
listed in `[build] link` (CardDemo's configs list `CSUTLDTC` and `CEEDAYS`, and `DSNTIAC` for
Db2). A CALL to a program the package does not hold abends the task with code 4038 unless
`env.toml`'s `[tolerant] permit_unresolved_call_targets` is set. The transaction table comes
from the CSD files' `DEFINE TRANSACTION`.

## Startup

`forge-run` assembles the region from the package (`cics.tn3270.region.assemble_region`): the
image, each mapset parsed from its `hlasm_export` JSON, the transaction table, and every CICS
file the CSDs define, resolved to a cataloged dataset. It then logs a line starting `serving`
that names the host and port.
A CICS file whose DSN is not cataloged, or is neither a KSDS nor a path, stops it with
`CICS file NAME: DSN is not cataloged` or `CICS file NAME: DSN is not a KSDS or path`. The
region reads and writes the cataloged datasets in place: its writes survive a restart, and a
batch job run against the same system directory sees them. Nothing locks the directory, so do
not run a job against it while the region is serving (red-dragon-forge-y6gk).

Each follow-on task's COMMAREA is padded with nulls to 32763 bytes (`MAX_COMMAREA`, CICS's
maximum COMMAREA length), so a successor that indexes a larger COMMAREA than its predecessor
passed reads nulls. There is no setting for it; red-dragon-forge-eqlr replaces the padding with
the caller's real storage.

## CICS files

No config holds record lengths or key positions. A CICS file's record length and key come from
its dataset's catalog label: a KSDS's own key, or for a path, its alternate index's key over the
base cluster's records. Each `DEFINE FILE(NAME) ... DSNAME(DSN)` in a CSD makes `NAME` a CICS
file over the cataloged dataset `DSN`; a later CSD's definition of the same name wins. The
[cicada architecture page](architecture.md#vsam) describes file control.

## Terminals

Any IBM-3278 or IBM-3279 model 2 to 5 is accepted, with or without `-E`. The server paints the
24x80 default partition. Colour is sent only to a terminal type ending in `-E`, so use a 3279
with `-E` for colour, for example `c3270 -model 3279-2-E localhost:3270`.
