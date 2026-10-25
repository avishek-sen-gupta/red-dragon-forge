# Plain Mode Without jackal — Design

**Date:** 2026-10-26
**Issue:** red-dragon-6lic (wire the mixed COBOL+HLASM run-time stack in forge). This design is its
first two steps; assembler support in litter is a later design.
**Supersedes:** D7 of `2026-10-15-forge-runner-design.md`.

## Problem

`forge-run` in `[plain]` mode builds a one-step JCL job in memory (`plain_job`) and runs it through
jackal's `JobRunner`. Plain mode is neither JCL nor CICS, yet it gets JCL's job, step and DD
objects, `DISP=SHR`, and lenient step policies that turn failures into RC 0: a dataset that cannot
be allocated, and an unknown return code. (A `program` missing from the package is already refused
by `env_config` before anything runs.)
The parts of jackal that any program run needs — matching a program's files to datasets, the
COBOL file handler, the abend types, reading a CEE3ABD abend — are tangled with the JCL parts, so
plain mode cannot drop jackal without them moving out.

## Goal

Plain mode runs the package's image directly, importing nothing from jackal. jackal keeps exactly
its current behaviour, importing the moved parts from their new homes.

## Non-goals

- Assembler support in litter, HLASM run inputs, the floating-point builtins, and an assembler
  CEE3ABD. Those are step 3 (a later design).
- Any change to `[jcl]` or `[cics]` mode behaviour.
- Moving `interpreter.hlasm_run_inputs`, or the VM-bound part of `interpreter.record_io`.

## Order

1. Move the non-JCL parts out of jackal, and the drivers out of `interpreter` (D1–D4). No
   behaviour changes.
2. Plain mode runs the image directly (D5–D7).
3. (Later design) assembler in litter; CEE3ABD becomes an assembler source file and the COBOL
   stub and its storage reader are deleted.

## Decisions

**D1. `infrastructure` is a new red-dragon root package; `infrastructure.zos.abend` holds the
abend types.** `SystemAbend` (rendered `S0C7`, three hex digits) and `UserAbend` (rendered `U1234`,
four decimal digits) move from `jackal/model.py`. (Parsing the rendered form back has no caller
until step 3's HLASM reader, so it comes then.) `infrastructure` imports nothing under
`interpreter`, so importing it never loads the VM; modules under `interpreter` import it, never the
reverse. An import-linter contract enforces both. More may move into `infrastructure` later.

**D1a. The access-method drivers move to `infrastructure.zos.access_methods`.** catnip imports
`interpreter.record_io` today, and importing anything under `interpreter` runs
`interpreter/__init__.py`, which loads the VM: catnip loads the VM. catnip must not. The drivers
catnip uses (the driver, alternate-index, access-result, record-shape, prime and
alternate index-entry modules and the slot and variable-sequential modules they use) import only
each other and `cobol_asg.file_enums`; they move unchanged. They are generic
z/OS record access (sequential, relative and indexed), used by COBOL's file I/O and by HLASM's file
services alike. `interpreter.record_io` keeps the three modules that need VM values —
`io_provider`, `real_file_provider`, `file_frame` — and imports the drivers from their new home.
In forge, catnip then imports `infrastructure` and `cobol_asg` only, and a contract forbids it
anything under `interpreter`.

**D2. HLASM's abend recording stays in `interpreter.hlasm`.** COBOL never emits an abend itself:
until step 3 the CEE3ABD stub only stores its code (D3), and in step 3 the assembler CEE3ABD abends
through HLASM's own SVC 13 path. So `emit_abend` and the abend variable stay where they are. The
reader that returns a finished VM's HLASM abend as an `infrastructure.zos.abend` type belongs
beside them in `interpreter.hlasm`, and is added in step 3, when forge first runs HLASM.

**D3. The CEE3ABD storage reader moves to `interpreter.cobol`, temporarily.** `jackal/le_abend.py`
reads the abend code the COBOL stub `CEE3ABD.cbl` left in its WORKING-STORAGE (`-1` meaning not
called). It reads COBOL program-object internals, so it sits beside them in red-dragon's
`interpreter.cobol` and returns `infrastructure.zos.abend.UserAbend`. The stub moves with it, out of
`jackal/le_stubs/`, so the code that reads its storage layout and the stub that defines it change
together; red-dragon exports the stub directory's path (today's `LE_STUBS`) for builds and tests
to list it from. (Builder's call, recorded.) Both are deleted in step 3, when CEE3ABD becomes an assembler source that abends through D2's path.

**D4. A new forge package, `zos.cobol.io`, takes COBOL's file handling against catalogued
datasets.** It sits between catnip and the runtimes: it imports catnip and red-dragon, and jackal
and plain mode import it. It is not catnip, because the handler needs the VM and catnip must not
load it (D1a); and it is COBOL's link to datasets, not a general z/OS capability (an assembler
program reaches datasets through a DCB, and gets its own sibling in step 3). Into it, unchanged in
behaviour: `file_definitions` (each program's FDs read from the image); the record-format, record
position and label-conflict modules (the FD-against-label matching by Enterprise
COBOL's rules), and the generic core of `cobol_files`: opening a program's file against a catnip
`Dataset` — the FD-against-label check (status 39 on a conflict), labelling a new dataset on its
first OPEN OUTPUT or EXTEND, and choosing the driver — plus the per-program dispatch of
`program_files_provider`. That core takes, per file name, its `Dataset`, its path and whether it is
opened for append — what it reads from `DdEnvironment` today (`paths()`, `appended()`) — but not the
`DdEnvironment` itself. jackal keeps what exists only through DDs — concatenations, in-stream
`DD *`, `DUMMY`, `SYSOUT`, and building those inputs from a step's allocations — and builds on
`zos.cobol.io`. `zos` must not shadow anything: no script is run from inside `zos/cobol/`, whose
`io` would then hide the standard library's.

**D5. `[plain]` runs one program directly.** forge opens the package and calls red-dragon's
`run_linked_resumable` on its image, entered at `program`, with `max_steps` as the budget. There
is no job, step, DD or disposition. The builtins are the ones plain mode composes today
(`core_builtins()` plus coprocessing's). The VM's provider is `zos.cobol.io`'s file handler (D4).

**D6. `[plain.files]` names catalogued datasets, resolved through catnip.** Each entry maps an
ASSIGN name to a dataset in catnip's catalog, which supplies the label, as now. No file is
described in `env.toml`. A name not in the catalog is refused before the run, whatever the program
opens it for: a new output file is catalogued with catnip first. Plain mode never creates a
dataset (today it gets one by accident, through `LenientAllocation`).

**D7. Plain mode reports what happened, standing in only where `[tolerant]` asks.** One line on stdout:
- `RC <n>` when the program ends normally with a known return code, with exit status 0 whatever
  `n` is, as today;
- the abend's rendered code (`U1234`, `S0C7`), from D3's reader (and D2's once HLASM runs, in
  step 3), with exit status 1;
- budget exhausted, with exit status 1 — not `S322`, which is a job-step CPU-time abend;

and each of these stops the run with a message naming it, exit status 1:
- `program` is not in the image (already refused by `env_config`; kept);
- a `[plain.files]` name is not in the catalog;
- an unresolved call target, unless `[tolerant]` permits it, as it does today.

A symbolic RETURN-CODE (left by a CALL that `[tolerant]` let through to a program outside the
image) reports `RC 0`, exit status 0, with a warning that the code is unknown, as today. z/OS has no
such case — a dynamic CALL to a missing program abends S806 — so any code is a stand-in; 0 keeps
`[tolerant]` useful and the warning keeps the guess visible.

An abend wins over everything else: a program that called CEE3ABD reports its abend even if its
return code is unknown, as `cobol_step` does today. (Exit status and precedence are the builder's
calls, recorded.)

## What stays in jackal

`model`, `jcl/`, `allocation`, `catalog` (a job's temporary and passed datasets), `cond`,
`if_guard`, `expansion`, `dcb_label`, `concatenated_records`, `parm`, `value_parts`, the tolerance
strategies, `utilities`, `idcams`, `tso`, `tso_step`, `runner`, `cobol_step`, `cli`. cobble's
imports from jackal are all among these; cicada imports nothing from jackal.

## Commits

- red-dragon: D1, D1a and D3 (with a bead), each with its tests, pushed before forge uses them.
- forge: one commit for step 1 — the vendor bump, catnip importing the drivers from
  `infrastructure`, D4, and jackal importing from the new homes —
  because the bump does not pass forge's gate without the jackal changes. One commit for step 2
  (D5–D7), with the docs (`docs/reference/forge/run.md`) and the litter README updated.

## Testing

- red-dragon: unit tests on the types' rendering; the existing record-I/O and HLASM file tests pass
  with the drivers in their new home; a VM test that a COBOL CALL to the
  CEE3ABD stub reads back as `UserAbend`.
- forge step 1: jackal's and catnip's existing suites stay green unchanged, and catnip's new
  import contract holds; the moved tests move with their modules.
- forge step 2: an integration test per D7 line, run through `forge-run` on a built package,
  asserting the exact stdout line and exit status; and a test that `red_dragon_forge`'s plain path
  imports nothing from jackal (an import-linter contract, if forge's layout allows one).
