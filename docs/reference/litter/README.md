# litter

litter holds the package: a zip of COBOL programs compiled once, which a later run opens without
recompiling. It provides `build` and `open_package`. The design is
[the forge runner spec](../../superpowers/specs/2026-10-15-forge-runner-design.md) (D3, D4).

litter requires Python 3.13. It depends on `pydantic` and `red-dragon` only. `.importlinter`
forbids it from importing cicada, squall, jackal, cobble, catnip or `red_dragon_forge`, and
forbids cobble from importing it.

## What a package holds

A package is `<name>.zip`:

| Entry | Content |
|---|---|
| `manifest.json` | The `Manifest`: program names, coprocessor names, the CSD's transactions and files, mapset names |
| `programs/<PROGRAM>.linked.json` | One linked program, written by red-dragon's `LinkedCodec` |
| `maps/<MAPSET>.json` | `hlasm_export`'s JSON for one BMS mapset, copied in unchanged |

The manifest is the only thing litter serialises itself. A transaction is a
`Transaction(transid, program)`; a file is a `CicsFile(name, dsname)`, one CSD `DEFINE FILE`. A
coprocessor's name is its compile spec's strategy name, so a conversational CICS build records
`cics-conversational`.

## build

`build(name=, programs=, sources=, parser=, specs=, search_dirs=, work_dir=, out_dir=,
transactions=, files=, mapsets=, tolerant=)` compiles each program with red-dragon's
`compile_program` and the given `CoprocessorSpec`s, and returns `out_dir/<name>.zip`.

- `sources` maps each program to its source file; the programs it CALLs are found in
  `search_dirs` and linked in.
- red-dragon's intermediate files for program `P` go in `work_dir/P`. A rebuild with the same
  work directory reuses them.
- `mapsets` maps each mapset name to the JSON file `hlasm_export` wrote for it.

## open_package

`open_package(path)` returns a `Package`: the manifest, each program's `LinkedProgram` read with
`LinkedCodec.read`, and each mapset's JSON text, which cicada parses on arrival. It raises
`PackageError` naming the package and the entry when:

| Fault | Message |
|---|---|
| An entry the manifest names is absent | `<path>: <entry>: missing` |
| `manifest.json` fails validation | `<path>: manifest.json: <validation errors>` |
| A linked file fails `LinkedCodec.read` | `<path>: programs/<PROGRAM>.linked.json: <codec error>` |

## Tests

`cd litter && . ../bridge-env.sh && uv run --no-sync python -m pytest`. The integration tests
compile COBOL, so they need `PROLEAP_BRIDGE_JAR` and fail when it is unset. They cover the codec
round trip of a built package, reuse of the work directory, mapsets shipped unchanged, and each
`PackageError`.
