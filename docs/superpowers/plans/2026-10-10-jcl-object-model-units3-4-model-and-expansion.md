# JCL object model, units 3–4: parsed model and expansion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `parse_jcl` returns the blueprint's parsed `Job`; `expand_procs(job, library)` returns the blueprint's `ExpandedJob` or a `JclError`; jackal's runner and cobble read `ExpandedJob`; every acceptance test is green.

**Architecture:** `jackal.model`, `jackal.dsn` and `jackal.value_parts` are replaced in place by the blueprint §4 types (contract table in the unit 1 plan). `jackal.jcl.wire` builds them. A new `jackal.expansion` replaces `jackal.jcl.proc_expand`: it places every statement under its chain of PROC calls, applies symbols and overrides, then resolves every `StepRef` to the `QualifiedStep` it names. The runner, `cond.py`, `catalog.py`, the utilities and cobble move onto `ExpandedJob`, and the old model, `proc_expand` and their tests are deleted.

**Tech Stack:** Python 3.13 (ruff target py311: no PEP 695 syntax), dataclasses, Pydantic 2 at the wire, pytest.

**Spec:** `docs/superpowers/specs/2026-10-10-jackal-jcl-object-model-build-design.md` §6–§7 (units 3 and 4); blueprint `docs/superpowers/specs/2026-10-10-jackal-job-level-domain-model-design.md` §4, §5, §12.1; contract table and normalisation rules in `docs/superpowers/plans/2026-10-10-jcl-object-model-unit1-acceptance.md`.

## Ruling: units 3 and 4 land together

The spec has unit 3 move cobble and the runner onto the parsed model, then unit 4 onto the expanded one. Both consumers read only expanded jobs: the runner runs steps, and cobble draws them. Moving them onto the parsed model first needs an adapter from the new types back to the old, deleted one commit later. The spec allows such an adapter only if unit 3 grows too large. These units do the move once, onto `ExpandedJob`. The acceptance suite is green at the end of the one commit; every intermediate state stays local. Cost if wrong: one larger review.

## Decisions taken here

- **D6** (settled by the user, 2026-10-10): a COND or referback naming no step is `DanglingReference`. A name used in more than one run of a PROC resolves to the same run; `expand_procs` logs a warning when that choice is made (a sibling of the same name exists in another run).
- **JOB COND** keeps today's runtime reading (its tests are checked like bypass tests against every prior step). Its blueprint semantics (end the job) belong to the executor work, not this unit.
- **EVEN/ONLY at run time:** jackal records no abends (a failing program raises and ends the run), so `EVEN` behaves as `NORMAL` and an `ONLY` step is bypassed. Both now parse; before, they failed the job.
- **IF guards at run time:** the runner refuses a step whose guard is not `Always()`, naming the step (`2cy.7` said to reject until `jackal-1o2.8`).
- **Unbound symbols** stay as `Symbol` parts rather than failing expansion, as they already do at job level. The one exception is the lone-symbol DSN, which becomes `TempRef`.
- **Override COND targets** are resolved in the scope of the step the override lands on, as if coded there.
- **`ExpansionFailed(error)`** is the exception the shells (runner, cobble) raise from a `JclError`, so callers that skip a bad member keep one `except` clause.
- **Rendering** a `QualifiedStep` as `S1.P1.Q1` (every label, joined by `.`) happens only at the edges: `StepResult.name`, cobble's node ids, the CardDemo facts.

## Expansion algorithm

1. **Place.** Walk the job's statements with `(calls, runs, symbols, guard, stack)`:
   - a `ProgramStep` inside a PROC gets its symbols substituted, then is placed with the enclosing guard;
   - an `IfBlock` places `then` under `guard ∧ condition` and `otherwise` under `guard ∧ ¬condition` (`AllOf` flattened; `Always` is the identity);
   - a `ProcCall` is looked up in the library: absent → `UnresolvedProcCall` placed at the caller's calls; in `stack` → `CircularProc`; otherwise its symbols are the PROC defaults overridden by the call's symbol overrides (each resolved in the caller's symbols), its keyword overrides are checked against the PROC's step labels (`OverrideNamesNoStep`) and applied to each PROC step per blueprint §4.6, and its statements are placed recursively with `calls + (call,)` and a fresh run id.
2. **Resolve.** Walk the placed steps in order, building each `QualifiedStep` from earlier ones. A `StepRef` is looked up in the scope it was written in (its run ids): `OwnScope` → a step of that run with that label; `CalledProcScope(c)` → a step of the run of sibling call `c`; inside a PROC, failing both, the job level. A match that is the current step or later is `ForwardReference`; a match that is a PROC call is `ReferenceToProcCall`; no match is `DanglingReference`; a referback whose step lacks the DD is `DanglingDdReference`.
3. **Normalise.** After substitution, adjacent literals join into one `Literal`; an empty value is `()`; a DSN that is one unbound symbol is `TempRef(name)`.

## Tasks

### Task 1: The parsed model and the deserializer
- [ ] Remove `PARSED` from the parse-stage acceptance tests; run them: they fail on the missing names.
- [ ] Write `jackal.value_parts` (`SymbolName`, `Symbol(name: SymbolName)`), `jackal.dsn` (`TempRef(name)`, `BackwardRef[R]`, generic `DSN`), `jackal.model` per the contract table, with `QualifiedStep` and `UnresolvedProcCall` defined in `jackal.model` (they are the bound of the stage parameter) and re-exported by `jackal.expansion`.
- [ ] `wire` builds the new types; the deserializer applies the unqualified-override-DD rule (nearest qualified DD above, else first step) and merges repeated qualifiers; DISP's abnormal default after `PASS` is `DELETE` for `NEW`, else `KEEP`.
- [ ] Run the parse-stage acceptance tests: green.

### Task 2: Expansion
- [ ] Remove `EXPANDED` from the expansion acceptance tests; add a test that the D6 warning is logged for the second run in `refs/refs.jcl` and not for the first.
- [ ] Write `jackal.expansion` per the algorithm above; `DirectoryProcLibrary` parses `<dir>/<proc>.prc` with the bridge.
- [ ] Run the whole acceptance suite: green.

### Task 3: Consumers
- [ ] Runner, `cond.py`, `catalog.py`, utilities, `cobol_step.py`, IDCAMS executor, CLI: onto `ExpandedJob` and `ProgramStep[QualifiedStep]`; unit tests rewritten to build the new types; `jackal.jcl.proc_expand` and its tests deleted, its behaviours covered by the acceptance suite.
- [ ] cobble: `jcl_graph`, `corpus_index_builder`, `jcl_store`, `build_graph`, diagnosis; PROC provenance read from `QualifiedStep.calls` instead of reconstructed from names; cobble's jackal tests rewritten.
- [ ] CardDemo facts rendered from `ExpandedJob`; every snapshot difference listed with its issue.
- [ ] Gate: `make fmt`, pyright, lint-imports, fp-lint on touched files, jackal, cobble and root suites. Docs: jackal architecture page, roadmap row. Commit; close `2cy.9`, `2cy.10`, `jackal-lz8`.

## Rulings during execution

- **Typed entity references** (the user, mid-unit): a model field never holds a `str` for an entity. `ProgramStep.pgm` is a `ProgramRef`, `ProcCall.proc` a `ProcRef`, ddnames a `DdName`, `CircularProc.procs` a tuple of `ProcRef`. The acceptance builders wrap names accordingly; strings remain only where text leaves (rendering, logging).
- **No `match` chains in gated code:** each model and wire variant carries the small method a caller needs (`mapped`, `substituted`, `dataset_name`, `guard`, `statement`), keeping every function within the complexity ceiling.
- **The catalog's table** moved to `jackal/jackal/catalog_stores.py`, excluded in `fp.json` with its reason, so `catalog.py`'s logic is gated and its adopted violations fixed.
- **Tests deleted as duplicates** of the acceptance suite or of rewritten tests: `jackal/tests/unit/test_model.py`, `test_proc_expand.py`, `jackal/tests/integration/test_backward_refs.py`, `test_jcl_bridge_cond.py`, `cobble/tests/jackal/test_proc_expand.py`, `test_dsn.py`. Their behaviours are covered by the acceptance suite, the rewritten runner tests and the new expansion unit tests.
- **Deferred:** the presentation capture script still reads the old model (`red-dragon-forge-whk`); IDCAMS `Repro` keeps `str` DD names, wrapped by the executor (`red-dragon-forge-a1b`).
