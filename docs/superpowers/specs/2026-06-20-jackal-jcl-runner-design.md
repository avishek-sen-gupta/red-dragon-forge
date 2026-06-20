# jackal — JCL Execution Layer (v1) — Design

**Status:** Designed (2026-06-20). Approach A (in-process orchestrator + Lark JCL
grammar + job-scoped dataset catalog), approved.

**Goal:** Run a multi-step batch job described in JCL: parse the JCL, sequence its
steps, resolve each step's DD statements to datasets, and execute each
`EXEC PGM` step (COBOL load module or emulated utility) against the red-dragon VM
+ file engine — verifying that every step ran and that intermediate datasets
carried transformed data from one step to the next.

**Driver:** Running real-world mainframe batch (not NIST conformance). A spike
proved a real batch COBOL program runs ~end-to-end through red-dragon with only a
handful of small engine gaps; the missing layer is JCL orchestration. jackal is
that layer.

## Global Constraints (binding)

These bind every task. (Most are inherited from `.claude/conditional/design-principles.md`.)

- **No regex. Anywhere.** No `import re`. All parsing/resolution/decisions are
  grammar-based (Lark): JCL card format, continuations, and DISP parsing live in
  the grammar, never in regex prepasses.
- **TDD** — failing test first for every unit.
- **FP principles** — functional core / imperative shell; immutable values
  (`frozen=True` dataclasses); comprehensions/`map`/`filter` over mutating loops.
- **No defensive programming** — no `None` checks, no `None` defaults, no generic
  exception swallowing; null-object pattern over `None` returns.
- **Small, composable functions** — one responsibility; no massive functions.
- **No external-codebase references in tracked artifacts** — no real dataset
  names, vendor names, or domains in committed code/tests/specs. The real-batch
  corpus stays external (env-var path), introduced in a later milestone.
- Python 3.13+, `uv`, pytest, Black. Beads (`bd`) for tracking.
- red-dragon consumed as a git submodule at `vendor/red-dragon`.

## Scope

**In scope (v1):**
- Parse JCL: `JOB` card, `EXEC PGM=` step cards, `DD` statements with `DSN=` and
  `DISP=` (status `NEW/OLD/SHR/MOD`; normal/abnormal disposition
  `PASS/CATLG/KEEP/DELETE`). `//` card format and comma continuations — in the
  grammar.
- Sequence steps in order; run all steps (no conditional execution in v1).
- Job-scoped dataset catalog carrying data between steps.
- Execute `EXEC PGM` steps: COBOL programs via red-dragon; `IEFBR14` (no-op) as
  the one emulated utility.
- A `JobResult` (per-step ran/return-code) and byte-assertable datasets.

**Out of scope (later milestones):**
- In-stream data (`DD *`), `SYSOUT` capture.
- Symbolic parameters (`&VAR`), `PROC`/`PEND` expansion.
- DD concatenation, GDG.
- `IDCAMS`, `SORT`, `IEBGENER` and other utilities.
- Conditional execution (`COND`, `IF/THEN/ELSE`).
- The real external batch corpus (env-var path; after the engine gaps are fixed).

## Architecture — Approach A

New repo `jackal`, red-dragon as a `vendor/red-dragon` submodule (squall/cicada
pattern). In-process Python orchestrator. Pipeline:

```
JCL text → Lark parse → Job model → JobRunner (sequences steps)
   → per step: resolve DDs against the job-scoped DatasetCatalog
   → run PGM (utility emulator | COBOL via red-dragon run())
   → StepResult → JobResult
```

A **fresh `VMState` per step** models the real "each EXEC PGM is a separate
program" boundary. The **`DatasetCatalog` is the only state shared across steps** —
it is how data flows step → step.

## Components

Each is one module with one responsibility and a well-defined interface.

1. **`jcl/grammar.lark` + `jcl/parser.py`** — Lark grammar + transformer.
   `parse_jcl(text: str) -> Job`. Grammar owns `//` card format, comma
   continuations, and the v1 statement set. Transformer builds immutable model
   objects. No regex.

2. **`model.py`** — immutable (`frozen=True`) dataclasses:
   - `Disp(status: DispStatus, normal: DispNormal, abnormal: DispNormal)`
   - `DD(ddname: str, dsn: str, disp: Disp)`
   - `Step(name: str, pgm: str, dds: tuple[DD, ...])`
   - `Job(name: str, steps: tuple[Step, ...])`
   - Enums `DispStatus {NEW, OLD, SHR, MOD}`, `DispNormal {PASS, CATLG, KEEP, DELETE}`.

3. **`catalog.py`** — `DatasetCatalog`: maps DSN → `Dataset(path: Path, ...)`.
   Job-scoped (owns a temp workdir). Operations: `allocate(dd) -> Dataset`
   (`NEW`→create; `OLD/SHR`→resolve existing; `MOD`→append-open existing) and
   `dispose(dd)` applying the normal disposition at step end (`DELETE`→remove,
   `PASS/CATLG/KEEP`→retain). This is the imperative shell (file I/O).

4. **`cobol_step.py`** — bridge to red-dragon. Given a `Step`, the resolved
   DDname→`Dataset` map, and a COBOL source resolver: build a `RealFileIOProvider`
   whose overrides map each file to its dataset's backing path, then
   `red-dragon run()` the program with a fresh `VMState`. Returns
   `StepResult(name, return_code, ran=True)`. Maps the program's `RETURN-CODE` /
   normal `GOBACK` to the step RC; an ABEND → `ran=True, return_code != 0`.

5. **`utilities.py`** — utility-emulator registry mapping PGM name → handler.
   v1: `IEFBR14` (no-op; the DD allocations/dispositions still apply, which is
   precisely IEFBR14's real use — dataset create/delete via DD). The registry is
   the extension point for IDCAMS/SORT later.

6. **`runner.py`** — `JobRunner.run(job: Job) -> JobResult`. Creates the
   job-scoped `DatasetCatalog`, then for each step in order: resolve DDs (allocate
   via catalog), dispatch PGM (utility registry → else COBOL step), collect the
   `StepResult`, apply dispositions. Returns `JobResult(steps: tuple[StepResult, ...])`.
   Functional core decides; catalog is the injected imperative shell.

7. **`cli.py`** — `jackal run <job.jcl> --source-dir <cbl-dir>
   [--dataset DSN=path ...]`. `--dataset` pre-seeds input DSNs to fixture files.

## Data flow

`JobRunner.run` creates the catalog (pre-seeded with input DSN→fixture files via
the CLI). For each step: resolve its DDs against the catalog (allocating `NEW`
datasets, resolving `OLD/SHR`), run the PGM with the DDname→file map, then apply
each DD's disposition. **Inter-step transfer:** step N writes `DSN.X`
(`DISP=(NEW,PASS)`) → catalog retains the file; step N+1 reads `DSN.X`
(`DISP=SHR`) → same backing file → the transformation is observable and
assertable.

## Error handling

- JCL parse error → a clear syntax error citing the line (from Lark).
- `OLD/SHR` on an uncataloged DSN → step fails with an "unresolved dataset" error
  (the JCL-error analogue). Not silently created.
- COBOL ABEND (program calls the LE abend service / red-dragon raises) →
  `StepResult(ran=True, return_code != 0)`; the job stops at that step (v1:
  stop-on-first-abend; `COND` deferred).
- Unknown PGM (no utility emulator, no COBOL source) → clear "unsupported
  program" error before any step side effects.
- No defensive `None` guards: missing required JCL fields are grammar errors, not
  runtime `None` checks.

## Integration seam (red-dragon)

The JCL **DDname** equals the COBOL `ASSIGN TO <name>`, but red-dragon's
`RealFileIOProvider` currently keys overrides by the **SELECT name** (the spike
had to supply both the SELECT name and the assign name). jackal must map JCL
DDname → the key red-dragon resolves files by. The clean fix is to have
red-dragon resolve files by the COBOL **ASSIGN name** (= DDname), which is the
mainframe contract. The implementation plan pins this down as its first
integration task (a small red-dragon change, picked up via the submodule), so
jackal can map purely by DDname.

## Testing (TDD)

- **Unit** — `jcl/parser`: JOB/EXEC/DD extraction, comma continuations, DISP
  parsing, parse-error cases. `catalog`: allocation per status + disposition
  lifecycle (PASS retains, DELETE removes).
- **Integration (headline acceptance)** — author 2–3 synthetic, anonymized COBOL
  batch programs (e.g. STEP1: read input FD → filter/transform → write
  intermediate FD; STEP2: read intermediate FD → aggregate → write output FD) and
  a JCL job wiring them via DD. Run via `JobRunner`. Assert: (a) every
  `StepResult.ran` and `return_code == 0`; (b) the intermediate and final dataset
  **bytes equal the expected transformed records**. This proves "all steps ran +
  intermediate transformations worked."

## Milestones

1. **v1 (this spec):** synthetic multi-step pipeline, in-process, grammar-based
   JCL parse, dataset catalog, COBOL + IEFBR14 steps, byte-assertable.
2. **v2:** `IDCAMS` (DEFINE/DELETE/REPRO) + in-stream data + SYSOUT — enough to
   self-provision VSAM datasets.
3. **v3:** point jackal at the real external batch corpus (env-var path) once the
   red-dragon engine gaps (COMP-3 write, CLOSE status, figurative-const
   arithmetic, DISPLAY fidelity) are fixed.
