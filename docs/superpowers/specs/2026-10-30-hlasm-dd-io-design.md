# HLASM DD file I/O in forge

Part of red-dragon-6lic. red-dragon already runs QSAM for HLASM: `DCB`, `OPEN`, `CLOSE`, `GET`
and `PUT`, RECFM F, FB, V and VB, end of file to EODAD, the S337, S0C1, S013 and S002 abends,
and OPEN filling empty DCB fields from the DD. Its DDs arrive as `DdDefinition(path, recfm,
lrecl, blksize)` through `dd_run_inputs(dds)`. Forge never supplies any: `[jcl]` composes
`dd_builtins(NO_DDS)`, and `[plain]` composes none. This design wires forge's DDs in.

## Goals

1. **Plain.** Each `[plain.files]` entry is a DD for HLASM: the DDNAME is the entry's name, the
   path the cataloged dataset's, RECFM and LRECL from its label.
2. **JCL.** Each step's dataset DDs are DDs for HLASM, the same way: path from the allocation,
   RECFM and LRECL from the dataset's label. DDs are per step, as PARM already is.
3. **Labels.** A new dataset first written by HLASM gets its label in the catalog, as COBOL
   output already does, so a later step can read it.

## Proof (agreed with the user, 2026-10-30)

- Plain: an HLASM program copies `INDD` to `OUTDD`; the output file equals the input byte for
  byte, once RECFM FB and once RECFM VB.
- JCL: a two-step job. Step 1, an HLASM program, writes a new dataset (`DISP=(NEW,CATLG)`);
  step 2, a COBOL program, reads it and `DISPLAY`s each record. The test asserts the lines.
- A DDNAME the program opens that the config does not bind fails the OPEN with R15 8, as
  red-dragon does today. Forge adds no configuration check for it.

## Non-goals

- JCL DDs other than a dataset: in-stream (`DD *`), `SYSOUT`, `DUMMY`, concatenations. They
  stay unsupplied, so an OPEN of one returns 8. Follow-up issue.
- BSAM, VSAM, EXCP, BLKSIZE semantics beyond passing the label through.
- SYSIN (red-dragon-f8pe); HLASM I/O under CICS (CICS programs use EXEC CICS file control).
- red-dragon changes, unless the wiring finds a defect there.

## Constraints

- No import-linter relaxation in either repo. No GPL or unlicensed code; fixtures are our own.
- Forge guidelines: frozen dataclasses, no `Any`, one-line module headers only, few
  whole-behaviour tests with concrete assertions, Talisman rules, no attribution trailers.

## Decisions

- **Where the DDs are built.** One function in forge's `zos` package turns a name-to-`Dataset`
  mapping into `Mapping[str, DdDefinition]`. Plain mode and jackal both call it: plain with its
  `FileBindings.datasets`, jackal with the step's `DatasetAllocation`s.
- **Which datasets are DDs.** A dataset whose label is `SequentialLabel` or `LabelPending` is
  supplied. A KSDS or any other label is left unsupplied, so its OPEN returns R15 8 rather than
  abending S013 later.
- **Label to DD facts.** `SequentialLabel(recfm, lrecl)` gives RECFM F, FB, V or VB and its
  LRECL. `LabelPending` gives `RecordFormat.UNSPECIFIED` and 0, so the DCB's own fields stand;
  an LRECL still 0 abends S013 as red-dragon already does. A JCL DD that codes RECFM and LRECL
  already labels its new dataset at allocation (`jackal/dcb_label.py`), so its facts arrive.
- **Builtins per step.** In `[jcl]`, `dd_builtins` moves from the per-run table to the
  per-step one, beside `job_parm_builtins`, since `compose_builtins` refuses duplicate names.
  In `[plain]`, `dd_builtins` joins the existing composition.
- **The path.** `__hlasm_dd` carries no path. HLASM's OPEN calls `__cobol_open_file` with the
  DDNAME as the file name, so the file provider finds the path by DDNAME. The same name-to-
  `Dataset` mapping that builds the DD facts also binds the provider, so the two cannot drift.
- **An HLASM slot in the file provider.** red-dragon's HLASM file calls carry the program name
  `""` (`declare_file_builtins.NO_PROGRAM`). `ProgramFilesIOProvider` keys its providers by
  program and has none for `""`, so it raises today. It gains a provider for `""`: a new
  `DatasetFileIOProvider` subclass in `zos` keyed by DDNAME (no FDs), whose datasets are the
  DD mapping above. It admits an open by the format the declared frame gives (fixed or
  variable, record length), where the COBOL providers use the FD. Plain mode and jackal build
  it from their own bindings; COBOL programs keep their per-program providers, so a run that
  mixes COBOL and HLASM files keeps both.
- **Labelling HLASM output.** On an OUTPUT or EXTEND open of a dataset whose label is pending,
  the label comes from the declared frame. Fixed: `SequentialLabel(F, record length)`.
  Variable: `SequentialLabel(V, record length + 4)`, since red-dragon declares a V file's
  record length as LRECL less the RDW and labels store the LRECL with it, as COBOL's
  `VariableFormat` does. The frame does not say whether the DCB was blocked, so the label is
  F or V, never FB or VB, as `label_for` already does for COBOL. The existing relabeller writes
  it to the catalog, so a later step sees it.
- **Pending label, INPUT open.** Treated as COBOL's is today: no conflict is found, the file
  does not exist, so the OPEN fails and R15 is 8.
- **DDNAME case.** DDNAMEs are upper case in both modes; the `[plain.files]` key is the DDNAME
  as written.

- **Step 1 of the JCL proof.** Its DD codes `RECFM` and `LRECL`, as a real job would, so the
  label exists before the program runs.

## Left to the builder

Fixture and test names; the exact records in the fixtures; how the JCL test drives `[jcl]`
(follow forge's existing JCL integration tests); where in `zos` the shared function lives.
