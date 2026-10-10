# Building jackal's JCL object model

**Date:** 2026-10-10
**Status:** approved design; implementation plan to follow.
**Builds:** §4 (the parsed model), §5 (expansion) and §12.1 (IF guards, as model only) of
[`2026-10-10-jackal-job-level-domain-model-design.md`](2026-10-10-jackal-job-level-domain-model-design.md),
the blueprint. Type names below are the blueprint's; this document does not restate them.

## 1. Goal

Given any JCL script, and the PROCs it calls, jackal builds the correct `Job` and, from it, the
correct `ExpandedJob` or `JclError`. "Correct" means:

- every JCL construct in scope lands in the right typed field;
- every reference between steps resolves to the right `QualifiedStep`;
- every PROC override follows the rules checked against the JCL Reference (blueprint Appendix B).

Running steps (outcomes, gate, lifecycle, allocation) is out of scope. Today's runner keeps
working, adapted to the new types.

## 2. Scope

In scope:

- The blueprint's parsed model (§4) and `expand_procs → ExpandedJob | JclError` (§5).
- Three bridge defects that lose or distort JCL before it reaches the model:
  `DCB=(dsn,…)` and `DCB=dsn` failing the whole job (`red-dragon-forge-2cy.2`), concatenated DDs
  after the first dropped (`2cy.3`), and `IF/THEN/ELSE/ENDIF` flattened (`2cy.7`).
- IF/THEN/ELSE as model: the bridge keeps the structure, and `expand_procs` turns it into a `Guard`
  on each `ProgramStep` (blueprint §12.1). Guards are not evaluated yet.
- Moving cobble and today's runner onto the new types.

Out of scope: executing guards, outcomes, the gate, allocation, `DCB` attributes in the model
(`jackal-1o2.12`), GDG, symbols other than PROC symbolic parameters (`SET`, system symbols).

Before unit 4 starts, decision D6 in the blueprint must be settled: what a `COND` naming no step
does, and which occurrence a reused step name resolves to. The acceptance tests for both are
written against the drafted answers and change if the decision differs.

## 3. Approach

The old model is replaced in place, unit by unit, with no parallel copy. What makes that safe is
an acceptance suite written first, plus a frozen snapshot of what today's code reads from every
CardDemo job.

## 4. Acceptance tests

### 4.1 Construct fixtures

Each fixture is a small `.jcl` file with made-up names, plus `.prc` files where a PROC is called.
Each test asserts the exact `Job` and the exact `ExpandedJob` (or `JclError`) by equality. One
test per behaviour, so a test may hold several assertions about one construct. They are
committed first, marked `xfail` with their issue id, and each turns green as its unit lands.

The families, with what each must cover:

| Family | Behaviours |
|---|---|
| Steps and labels | `EXEC PGM=`, `EXEC <proc>`, `EXEC PROC=<proc>`, an unnamed step, PARM text with quotes and parentheses |
| COND | single and compound return-code tests, with and without a step name and `S1.P1`; `EVEN`; `ONLY`; tests mixed with `EVEN`/`ONLY` in any position; JOB-card `COND` |
| DISP | every status; every normal and abnormal value including `UNCATLG`; every omitted-position default from blueprint §4.4 |
| DSN kinds | catalogued name, `&&temp`, `&temp` read as a temp, referback `*.S1.DD` and `*.S1.P1.DD`, `DD *`, `DD DATA`, `DD DUMMY`, `DSN=NULLFILE`, `SYSOUT=` |
| Concatenation | two and three members; a member that is `DD *` or `DUMMY` |
| DCB | `DCB=dsn`, `DCB=(dsn,RECFM=…)`, `DCB=*.S1.DD`, `DCB=(RECFM=…)`: each parses, and the rest of the job is intact |
| PROC symbols | default only, overridden, symbol inside a symbol's value, `&HLQ..TRANS` concatenation, a lone undefined `&NAME` as a temp |
| PROC overrides | each row of blueprint §4.6: `COND=`, `COND.P1=`, `PARM=`, `PARM.P1=`, bare and qualified together, an empty value nullifying, an unqualified DD before any qualified one, an unqualified DD after `//P2.X`, a qualified DD that overrides, one that adds |
| Nesting | a PROC calling a PROC; an override placed inside the intermediate PROC; 15 levels |
| References | `OwnScope` at job level; inside a PROC to its own step; inside a PROC to a job-level program step; `CalledProcScope`; one PROC called twice (D6) |
| JCL errors | each `JclError` variant once: dangling reference, dangling DD reference, forward reference, reference to a PROC call, override naming no step, circular PROC |
| Unresolved PROC | a call to a PROC in no library becomes `UnresolvedProcCall` |
| IF/THEN/ELSE | `THEN` only; `THEN` and `ELSE`; nested; each relational term (`RC`, `S1.RC`, `ABEND`, `S1.ABEND`, negated `ABEND`, `ABENDCC`, `S1.RUN`); `AND`/`OR`/`NOT` and their symbols; an IF inside a PROC |

Each family's fixtures live under `jackal/tests/acceptance/<family>/`. The JCL Reference examples
in blueprint Appendix B are the source for expected values, with the two flagged IBM examples
excluded.

### 4.2 CardDemo snapshot

Before any code changes, a script records what today's code reads from every CardDemo job: for
each step, its name, program, PARM text, condition tests, and for each DD its ddname, DSN text and
DISP. The snapshot is committed as a JSON file next to the test that reads it.

After each unit, a test builds the new model for every CardDemo job, renders the same facts from
it, and compares. A difference fails the test unless the test lists it as an expected change with
the issue that causes it: for instance, a `COND` inside a PROC that now resolves, or an override
DD that now lands on the right step. Every expected change is reviewed when it is added.

### 4.3 Census corpus

Unit 5 runs `expand_procs` over the external census corpus. It records the share of jobs that
parse, the share that expand, and the failures grouped by `JclError` variant and by bridge error.
All output stays in an untracked experiment directory: no names from that corpus enter the repo
(guidelines/data-security.md). Each failure class found becomes either a new construct fixture,
with made-up names, and a fix, or an issue.

## 5. Bridge

The Java fixes land in `jackal/jcl-bridge`, each with a Java test beside `DcbContinuationTest`:

- `DCB=dsn`, `DCB=(dsn,…)`: the cause named in `2cy.2` is the lexer's DCB mode. Confirm it before
  changing anything, and do not add a second grammar rule.
- Concatenation: every unnamed DD after a named one is emitted as a member of it.
- IF/THEN/ELSE/ENDIF: emitted as nested blocks with the relational expression as a tree, in
  statement order with the steps around it.

The JSON contract is replaced by one that mirrors the parsed model:

- each statement has a `kind`: program, PROC call, or IF block;
- a program statement carries its condition tests and `EVEN`/`ONLY` as separate fields;
- a PROC call carries its symbol overrides, its parameter overrides (`COND`, `PARM`) with their procstep qualifier
  split out, and its override DDs, each with qualifier and ddname split;
- an IF block carries its expression and its `THEN` and `ELSE` statement lists;
- the JOB card carries its condition tests as `end_job_tests`.

Applying the unqualified-DD rule (an unqualified override DD belongs to the step named by the
nearest qualified DD above it) is the Python deserializer's job, because it depends only on
statement order, which the contract preserves.

## 6. Python

- **Wire models:** Pydantic models for the new contract in `jackal/jcl/wire.py`, read with
  `model_validate_json`. They replace today's hand-indexed dicts in `bridge_parser.py`. Nothing
  past the deserializer sees them.
- **Parsed model:** the blueprint's §4 types replace `jackal/model.py`'s `Job`, `Step`, `DD`,
  `Cond`, `Disp` and `ProcDef`, and `jackal/value_parts.py` gains `SymbolName`.
- **Expansion:** `expand_procs(job, library) -> ExpandedJob | JclError` replaces
  `jackal/jcl/proc_expand.py`. `ProcLibrary` replaces the list of directories.
- **Consumers:** cobble and today's runner move to the new types in the unit that changes the type
  they read. cobble keeps its graph node ids (`JOB.STEP`, `JOB.STEP.PROCSTEP`) by rendering them
  from `QualifiedStep`, so its graph output does not change except where a fix changes the facts.

## 7. Units

Each unit is one commit, keeps every suite green, and flips the acceptance tests it satisfies
from `xfail` to green.

1. **Acceptance suite and snapshot.** All §4.1 fixtures, `xfail`; the CardDemo snapshot and its
   comparison test, green against today's code.
2. **Bridge.** The three parse fixes and the new JSON contract, with Java tests. The Python
   deserializer is rewritten on Pydantic wire models in the same commit, still producing today's
   model, so nothing downstream changes yet.
3. **Parsed model.** The blueprint's §4 types replace the old model; the deserializer produces
   them; cobble and the runner are moved onto them. The parsed-model half of each fixture turns green.
4. **Expansion.** `expand_procs → ExpandedJob | JclError`, including references, overrides and
   guards; cobble and the runner consume `ExpandedJob`. The expanded half of each fixture turns green,
   and the CardDemo comparison lists every intended change.
5. **Census run.** Measure, then add fixtures and fixes for what it finds.

## 8. Risks

- **The bridge's DCB fix may be in the lexer's mode switching,** where a change can affect other
  parameters. The full existing Java suite runs with every bridge change, and the CardDemo snapshot
  catches a regression in any job that used to parse.
- **cobble's tests assert graph output.** A fix that changes facts, such as a now-resolved
  reference inside a PROC, changes cobble's expected output. Each such change is listed in the
  commit that causes it.
- **Unit 3 touches every consumer of the model at once.** If that commit grows past review size,
  it splits by consumer, with a temporary adapter from new types to old for the consumers not yet
  moved. The adapter is deleted in its own commit.
