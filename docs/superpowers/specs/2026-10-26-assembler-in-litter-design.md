# Assembler in litter — Design

**Date:** 2026-10-26
**Issue:** red-dragon-6lic (wire the mixed COBOL+HLASM run-time stack in forge). This design is
its first slice; the rest of 6lic is added differentially, each piece driven by a program that
needs it.
**Follows:** `2026-10-26-plain-mode-without-jackal-design.md` (step 3 of its Order).

## Intent

A litter package can hold assembler programs beside COBOL ones, and `forge-run [plain]` runs the
mixed image. The first target is CardDemo's batch program CBACT01C, which reads the account KSDS,
writes three sequential files, and calls the assembler subroutine COBDATFT to format dates. It
needs nothing from jackal.

## Goals

- `forge-build` lowers assembler programs and links them with COBOL programs into the one image.
- `build.toml` names each language's sources and programs in its own section.
- CBACT01C + COBDATFT (+ the CEE3ABD COBOL stub) builds and runs in plain mode against CardDemo's
  catalogued datasets, with no jackal imported.

## Non-goals

- HLASM PARM, the machine clock, DD run inputs (`dd_run_inputs`), `declare_file_builtins`, the
  floating-point builtins (red-dragon-6uyp.99), and an assembler CEE3ABD. Each comes later, with the
  program that needs it.
- `[jcl]` or `[cics]` running assembler. CardDemo's other assembler module, MVSWAIT, is not in scope.
- A planned red-dragon change: red-dragon already lowers HLASM per program
  (`lower_hlasm_program`) and links COBOL and HLASM units into one image
  (`tests/integration/hlasm/test_cobol_linkage.py`). An unplanned one is covered by D3.

## Anti-goals

- Deducing a program's language from its file extension or from which directory holds it.
- Keeping the old `build.toml` shape working beside the new one.

## Decisions (the user's)

**D1. `build.toml` has a section per language; the old shape is removed.** No backward
compatibility: every `build.toml`, fixture and doc in forge moves in the same commit.

```toml
[cobol]
source_dirs = ["app/cbl"]
source_exts = [".cbl"]
copybook_dirs = ["app/cpy"]
copybook_exts = ["cpy"]            # optional, as today
programs = ["CBACT01C", "CEE3ABD"]

[hlasm]
source_dirs = ["app/asm"]
source_exts = [".asm"]
maclib_dirs = ["app/maclib"]       # the macro library: COPY members and macros
programs = ["COBDATFT"]

[build]
name = "readacct"
link = ["CBACT01C", "COBDATFT", "CEE3ABD"]
coprocessors = []
tolerant = false
out_dir = "out"

[cics]                              # unchanged
```

- `[cobol]` takes today's `[paths]` keys and `[build].programs`. `[paths]` is gone.
- A program is found only in its own section's `source_dirs` and `source_exts`, with today's
  lookup rules (first hit wins, names match exactly).
- `link` names programs of either language; the image does not record languages.
- A name in both `[cobol].programs` and `[hlasm].programs` stops the build before lowering,
  whether or not `link` names it.
- `maclib_dirs` are passed as the HLASM parser's SYSLIB directories. Members are `<NAME>.mac`, as
  in red-dragon's own `hlasm-bridge/maclib`; there is no `maclib_exts` key.
- Either language section may be absent when it has no programs. `link` naming a program no
  section lists stops the build, as today.

**D2. Only what CBACT01C + COBDATFT needs.** If a mixed image needs builtins composed at run time
even when the assembler reads no PARM or clock, plain mode composes exactly those, and nothing
else from 6lic's list.

**D3. A gap the proof exposes is fixed in this slice.** If the run fails for a reason outside D2,
most likely a gap in red-dragon's HLASM lowering or COBOL–HLASM linkage that a real program
exposes, it is fixed here: in red-dragon (with its own tests and bead, pushed), then a vendor bump
folded into the forge commit. Each such fix is reported to the user when it is found, not only
at the end.

## Proof

One forge integration test, run through the commands:

1. Install CardDemo's datasets into a catnip system from `config/carddemo/data.toml`. CBACT01C's
   three outputs — `AWS.M2.CARDDEMO.ACCTDATA.PSCOMP` (FB 107), `.ARRYPS` (FB 110) and `.VBPS`
   (VB 84), as `READACCT.jcl` defines them — are declared there, catalogued with their labels.
   They are added to `config/carddemo/data.toml` itself, not a test-local file. The KSDS loads
   from CardDemo's `app/data/ASCII/acctdata.txt` through the existing declaration.
2. `forge-build` a `build.toml` listing CBACT01C and CEE3ABD under `[cobol]` and COBDATFT under
   `[hlasm]`, with CardDemo's `app/asm` and `app/maclib`. CEE3ABD comes from red-dragon's
   `interpreter/cobol/le_stubs/`, listed in `[cobol].source_dirs`.
3. `forge-run` a `[plain]` `env.toml` entered at CBACT01C, with `[plain.files]` mapping ACCTFILE,
   OUTFILE, ARRYFILE and VBRCFILE to those datasets.
4. Assert, with equality: the exit status and the `RC <n>` line; the stdout DISPLAY lines; and the
   records of the three output datasets. The reformatted date fields in the outputs show COBDATFT
   ran.

Existing build and run tests keep their assertions; only their `build.toml` text moves to the new
shape.

## Constraints

- Plain mode still imports no jackal and no cics (the contracts from red-dragon-forge-xauj).
- `forge-build` stays where it is (`red_dragon_forge.build_command`); litter's package format does
  not change.
- One forge commit; docs (`docs/reference/forge/build.md`, `run.md` if touched, the litter README
  if it names `build.toml` keys) change with it.

## Left to the builder

- How `HlasmCompileOptions` carries `maclib_dirs` to the HLASM bridge (its SYSLIB).
- Whether the unit cache keys need the maclib (today reuse ignores copybook contents,
  red-dragon-o819; the same limit may apply to macros, and is documented if so).

## Builder's calls already made (by the controller, reviewable)

- Expected output bytes are captured once from a run and reviewed. Then COBDATFT's date fields
  are asserted separately against values worked out by hand from the input records, so the test
  does not only check that the output matches itself.
- The migration is one commit however many fixtures it touches. The builder checks cicada,
  cobble and litter for readers of the old `build.toml` keys.
