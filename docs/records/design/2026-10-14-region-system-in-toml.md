# cicada: The Region's System Directory Is in Its TOML — Decision Record

**Date:** 2026-10-14
**Status:** accepted
**Issues:** red-dragon-forge-zave
**Supersedes:** in [the catnip extraction record](2026-10-14-catnip-catalog-extraction.md), the
sentence of N11 that passes the system directory as `--system DIR` on `cicada-tn3270` and
`carddemo-db2-cli`. N11 otherwise stands. That record is immutable and is not edited.

Where a CICS region learns which system directory it runs on.

## Decisions

**R1. `system` is a `[paths]` setting of the region TOML.** It sits beside `csd_files`, as N11 of
[the catnip spec](../../superpowers/specs/2026-10-14-catnip-system-catalog-design.md) says
(`system = "DIR"`). It expands `${VAR}` and `~` and is otherwise taken as written, the same as
every other path in the file. `load_config` takes only the TOML's path. `cicada-tn3270` and
`carddemo-db2-cli` lose `--system`.

The user ruled on 2026-10-14 that the system directory is region configuration, like everything
else in the TOML. The earlier `--system` flag was a deviation from the approved spec, made during
implementation. The argument for it, that one region TOML could then serve any system
directory, does not outweigh keeping a region's whole configuration in one file.

**R2. The shipped CardDemo configs name `/tmp/carddemo-system`.** It is the directory
[run-carddemo.md](../../how-to/run-carddemo.md) already installs CardDemo into with
`make catnip-install-carddemo SYSTEM=...`. Tests write a copy of the TOML under their own
temporary directory, naming the system they installed.

**R3. The VSAM dump tool keeps `--system`.** `python -m cics.vsam.dump` is not a region. It
decodes one dataset from a catalog and reads no region TOML, so the flag is the only place its
catalog can come from.
