# litter

litter holds the package: a zip holding one linked image of COBOL programs, built once, which a
later run opens without parsing, lowering or linking. It provides `build` and `open_package`. The design is
[the forge runner spec](../../superpowers/specs/2026-10-15-forge-runner-design.md) (D3, D4).

litter requires Python 3.13. It depends on `pydantic` and `red-dragon` only. `.importlinter`
forbids it from importing cicada, squall, jackal, cobble, catnip or `red_dragon_forge`, and
forbids cobble from importing it. jackal, cicada and the forge root import it.

## What a package holds

A package is `<name>.zip`:

| Entry | Content |
|---|---|
| `manifest.json` | The `Manifest`: the programs linked into the image, coprocessor names, the CSD's transactions and files, mapset names |
| `image.linked.json` | The one linked image, written by red-dragon's `LinkedCodec` |
| `maps/<MAPSET>.json` | `hlasm_export`'s JSON for one BMS mapset, copied in unchanged |

The manifest is the only thing litter serialises itself. It refuses keys it does not define.
Program, mapset and transaction-program names are z/OS member names: 1 to 8 characters, the
first `A`-`Z`, `#`, `@` or `$`, the rest those or `0`-`9`. No name read from a package reaches a
filesystem path. A transaction is a
`Transaction(transid, program)`; a file is a `CicsFile(name, dsname)`, one CSD `DEFINE FILE`. A
coprocessor's name is its compile spec's strategy name, so a conversational CICS build records
`cics-conversational`.

## build

`build(name=, programs=, link=, sources=, parser=, specs=, copybook_dirs=, work_dir=, out_dir=,
transactions=, files=, mapsets=, tolerant=)` returns `out_dir/<name>.zip`.

- Each program in `programs` is lowered once, on its own, with red-dragon's `lower_program` and
  the given `CoprocessorSpec`s. `sources` maps each program to its source file. A source holding
  several programs, batch or nested, lowers to a unit per program, and linking it links them
  all, so the image and the manifest's `programs` list each of them.
- The programs in `link`, in that order, are linked into one image with red-dragon's
  `link_units`. `link` may be a subset of `programs`; a name in `link` that is not in `programs`
  raises `PackageError` (`<out_dir>/<name>.zip: link names <P>, which programs does not list`)
  before anything is lowered.
- Nothing is discovered. A program reached by `CALL 'LITERAL'` or `CALL identifier` is in the
  image only if it is in `link`. A coprocessor's own stubs (squall's `DSNTIAC`) and Language
  Environment stubs (`CEE3ABD`, `CEEDAYS`) are ordinary programs: list them. `litter` never
  reads a spec's `linked_subprogram_sources` or `source_search_dirs`.
- `name` is letters, digits, `_`, `-` and `.`, starting with a letter or digit; anything else
  raises `PackageError` before anything is written. The manifest's `programs` are the image's
  program names, its PROGRAM-IDs.
- red-dragon's unit files and the image go in `work_dir`, named by a digest of their inputs. A
  rebuild with the same work directory reuses them.
- `mapsets` maps each mapset name to the JSON file `hlasm_export` wrote for it.
- A name that is not a member name raises `PackageError`
  (`<out_dir>/<name>.zip: manifest.json: programs.0: String should match pattern …`) before
  anything is compiled or written.
- The zip is written as `<name>.zip.part` and renamed when complete. A build that fails leaves
  neither file behind.

## open_package

`open_package(path)` returns a `Package(manifest, image, mapsets)`: the manifest, the image read
with `LinkedCodec.read`, and each mapset's JSON text, which cicada parses on arrival. A run enters
the image by program name with red-dragon's `ProgramEntry`; the names it holds are
`image.programs`. It raises
`PackageError` naming the package and the entry when:

| Fault | Message |
|---|---|
| An entry the manifest names is absent | `<path>: <entry>: missing` |
| `manifest.json` fails validation | `<path>: manifest.json: <location>: <message>`, one per error, joined by `; ` |
| The image fails `LinkedCodec.read` | `<path>: image.linked.json: <codec message>` |

## Tests

`cd litter && . ../bridge-env.sh && uv run --no-sync python -m pytest`. The integration tests
compile COBOL, so they need `PROLEAP_BRIDGE_JAR` and fail when it is unset. They cover a package
opening to the image its link list produced (a lowered program left out of `link` is absent), a
link list naming an unlowered program, reuse of the work directory, mapsets shipped unchanged,
names that are paths refused by `build` and `open_package`, no partial package after a failed
build, and each `PackageError`.
