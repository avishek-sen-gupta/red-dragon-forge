# forge-build

`forge-build BUILD_TOML` turns an application's `build.toml` into `<out_dir>/<name>.zip`, a
[litter](../litter/README.md) package holding one linked image, and prints the zip's path. It is
`red_dragon_forge.build_command:main`. Design: [the forge runner spec](../../superpowers/specs/2026-10-15-forge-runner-design.md) (D1, D2, D5);
assembler programs: [the assembler-in-litter spec](../../superpowers/specs/2026-10-26-assembler-in-litter-design.md) (D1).

```bash
. ./bridge-env.sh
uv run --no-sync forge-build app/build.toml
```

## Environment

| Variable | Use |
|---|---|
| `PROLEAP_BRIDGE_JAR` | parses the COBOL |
| `HLASM_EXPORT` | generates BMS symbolic copybooks and the mapsets' JSON |
| `HLASM_AST_BRIDGE` | optional: parses the assembler; default red-dragon's built `hlasm_ast_bridge` |

`. ./bridge-env.sh` exports the first two. An unset one stops the build: `forge-build: HLASM_EXPORT
is not set`, exit 1. A build with `[hlasm]` programs needs the HLASM bridge (`make setup` builds
it); a missing one stops the build: `forge-build: hlasm_ast_bridge not found: <path>`, exit 1. A
COBOL-only build never looks for it.

## build.toml

Relative paths are relative to the file's directory.

```toml
[cobol]
source_dirs = ["app/cbl", "../squall/squall/stubs"]   # first hit wins
source_exts = [".cbl", ".CBL"]                         # tried in order; default [".cbl"]
copybook_dirs = ["app/cpy"]
copybook_exts = ["cpy", "CPY"]                         # optional
programs = ["COSGN00C", "CBACT01C", "DSNTIAC"]         # each lowered once, on its own

[hlasm]
source_dirs = ["app/asm"]
source_exts = [".asm"]                                 # default [".asm"]
maclib_dirs = ["app/maclib"]                           # COPY members and macros, as <NAME>.mac
programs = ["COBDATFT"]

[build]
name = "carddemo"                                # letters, digits, '_', '-', '.'; never a path
link = ["COSGN00C", "CBACT01C", "COBDATFT", "DSNTIAC"]   # linked into the one image
coprocessors = ["cics", "sql"]                   # any of sql, cics, cics-conversational
tolerant = false                                 # compile-time tolerance
out_dir = "out"

[cics]                                           # required with cics or cics-conversational
bms_dirs = ["app/bms"]
csd_files = ["app/csd/CARDDEMO.CSD"]
```

- A program's language is the section that lists it, never its extension or directory. A
  program in both `[cobol]` and `[hlasm]` stops the build. Either section may be left out.
- A program `P` is the file `<dir>/P<ext>`, for each directory in its section's `source_dirs`
  and each extension in `source_exts`, in order. Names match exactly, so `.cbl` does not find
  `P.CBL` on any filesystem.
- Program names are member names (1-8 characters, upper-case). `coprocessors` takes only `sql`,
  `cics` and `cics-conversational`.
- `link` names exactly the programs in the image, of either language, and may be a subset of
  the programs listed. Nothing is
  discovered: a program reached by `CALL 'LITERAL'` or `CALL identifier` is in the image only
  if it is in `link`.
- Stubs are ordinary programs. Language Environment stubs (`CEE3ABD` in red-dragon's
  `interpreter/cobol/le_stubs/`, `CEEDAYS` in `cicada/cics/stubs/`) are listed when a program
  CALLs them; nothing checks.
- A coprocessor's own stubs are required. With `sql`, every name in
  `squall.db2_stubs.DB2_STUB_PROGRAMS` (`DSNTIAC`) must be in `link`; a build without it stops
  before lowering: `forge-build: coprocessor sql requires DSNTIAC in [build] link`, exit 1, and no
  package is written. `cics` and `cics-conversational` require nothing.
- With `cics`, each BMS mapset in `bms_dirs` (an earlier directory's wins) yields symbolic
  copybooks, regenerated on every build in `<out_dir>/work/sym` and put on the copybook path
  with cicada's own copybooks, and its `hlasm_export` JSON, copied into the package. The transaction table and the file table come from the CSD files'
  `DEFINE TRANSACTION` and `DEFINE FILE`.
- Intermediate files go in `<out_dir>/work/`; a rebuild reuses red-dragon's units, keyed by
  source and settings. Reuse ignores a copybook's contents, including a regenerated BMS
  symbolic map (red-dragon-o819): after editing a copybook or a `.bms`, delete
  `<out_dir>/work/` before rebuilding. HLASM units are keyed on the `maclib_dirs` paths, not
  the members' contents: after editing a `.mac` member, delete `<out_dir>/work/` too.
- SYSLIB is red-dragon's maclib (system macros such as `STIMER`, `TIME`, `GETMAIN`), then
  `maclib_dirs` in order.
- `link` naming a program twice, or two members declaring one PROGRAM-ID, stops the build.
- The manifest lists the programs the image holds, by PROGRAM-ID or CSECT name. A COBOL
  `CALL 'X'` reaches an HLASM program `X` with standard linkage.

| Fault | Message (on stderr, after `forge-build: `) |
|---|---|
| a cics coprocessor without `[cics]` | `build.toml: [cics] is required when coprocessors include cics` |
| an unknown coprocessor | `build.toml: build.coprocessors.N: Input should be 'sql', 'cics' or 'cics-conversational'` |
| a key, value or name build.toml does not allow | `build.toml: <location>: <message>` |
| the old shape (`[paths]`, or `programs` in `[build]`) | `build.toml: paths: Extra inputs are not permitted`, or `build.toml: build.programs: …` |
| a program in both languages | `build.toml: X is listed in both [cobol] and [hlasm] programs` |
| build.toml missing or not TOML | `<path>: No such file or directory`, or `build.toml: <TOML error>` |
| a program in no source directory | `program X is in no [cobol] source_dirs as .cbl` |
| an HLASM program in no source directory | `program X is in no [hlasm] source_dirs as .asm` |
| an assembly error, such as a missing `COPY` member | `E058 line N: Copy member not found; …` |
| a `maclib_dirs` entry that is not a directory | `SYSLIB directory <dir> does not exist` |
| no HLASM bridge | `hlasm_ast_bridge not found: <path>` |
| a `link` name not in `programs` | `<zip>: link names X, which programs does not list` |

## Tests

`tests/unit/test_build_config.py` covers parsing and the config faults;
`tests/integration/test_build_command.py` covers a CICS and a batch program built into one
package (manifest, CSD tables, the earlier `bms_dirs` mapset, symbolic copybooks regenerated
over stale ones), a source found only by a listed extension, the missing-`DSNTIAC` refusal and
the unset tool variables, a COBOL program CALLing an HLASM one that `COPY`s a macro-library
member and runs in `[plain]`, the missing member, an HLASM program with no source, a missing
bridge, and a COBOL-only build that needs no bridge.
