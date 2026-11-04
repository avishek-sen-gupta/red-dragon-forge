# Lowering COBOL programs to constrained Horn clauses

## Why

cobble's `guards` query lists the tests along CFG paths. It has no solver and does not track
what the statements on a path assign, so it reports paths that cannot run. On CardDemo,
sign-on's XCTL to the user menu gets five paths, and four of them are infeasible: a blank user
id sets `WS-ERR-FLG` to `'Y'`, and the next test needs it off. For bill pay's account
`REWRITE`, 55 of the 64 returned paths contain a test together with its negation, and 64 is the
cap. The output can be neither a necessary nor a sufficient condition, so questions about the
conditions under which a statement runs get no answer from it.

A constrained Horn clause (CHC) encoding states the program's meaning once, independent of any
question: one predicate per program point, one clause per CFG edge, each with the constraint the
statement puts on the bytes. A question is then a goal clause, and a CHC solver (Z3's Spacer)
answers it in one of three ways:
- `unsat`, meaning no run does it, with an invariant as the certificate;
- `sat`, meaning a run does it, with a derivation as the witness;
- `unknown`.

## Decisions

Taken with the user, 2026-11-04:

- **Route A.** Lower from cobble's own artefacts (CFG, ASG expressions, extents, fixpoint,
  combine links), inside cobble's allowed imports. Not from red-dragon's IR: `.importlinter`'s
  `cobble-no-interpreter` forbids it.
- **Independent of the Datalog export.** The lowering neither reads the Datalog `.facts`
  files or rules nor needs the Datalog stage to have run. It reads the same artefacts the
  export reads. This is enforced by an `.importlinter` contract that forbids
  `cobble.experimental.horn` from importing `cobble.experimental.datalog`. The gate tests
  build their run without the Datalog stage.
- **No execution.** Evidence is static only: artefact rows, ASG facts, solver results and
  stated assumptions.
- **Assumptions are written in SMT-LIB.** An assumption about the environment, such as "USRSEC
  holds a user of type `'U'`", is a formula in the same language as the clauses. It is listed
  as an assumption, never proven.
- **Fidelity grows by stages, and each stage is gated by real questions.**
  - Each question's answer is established from the CardDemo source, with file and line, before
    the stage's code runs.
  - A stage passes only if the solver's answers match every one of them.
  - `unknown` is a failure, reported as `unknown`.
  - The questions get harder as the encoding gets more faithful.
- **A run of an online program is a conversation.** A run is not one CICS task. Tasks chain
  through `RETURN TRANSID` and `XCTL`, and each task's incoming commarea is whatever the task
  before it handed over, mapped byte for byte by `combine/links.jsonl`. A conversation starts
  when the terminal starts any transaction the CSD defines, with no commarea (`EIBCALEN = 0`).
  That includes typing `CB00` directly. If each task's commarea were left unconstrained, it
  could claim any user type, and "can an admin reach bill pay through the user menu" would be
  `sat` for the model and false for the system.
- **A gate passes under its assumptions.** An answer that holds only under assumptions passes if
  those assumptions are written in the test and reviewed with the stage, like any other part of
  the gate.

## Soundness rule

Anything a stage does not encode exactly becomes an unconstrained value. That covers:
- an unresolved test atom;
- a rebuilt edge before its expression is encoded;
- a move the stage does not model;
- a computed subscript's bytes;
- every input: a file read, map input, EIB fields, CICS `RESP`, a call result.

So an `unsat` answer stays valid at every stage. A `sat` answer may be spurious until the
statements it depends on are encoded. Each stage's gate questions are chosen to need only what
that stage encodes exactly.

## What is reused

| need | from | CardDemo coverage at 0ea1e3a0 |
|---|---|---|
| control flow: PERFORM ranges, resume, fall-through, GO TO | srccfg CFG; the PERFORM-aware stepper in `srccfg/reach` | every parsed program |
| test conditions | CFG TEST atoms (`left`, `op`, `right`) | 2755 of 2815 resolved |
| byte layout: offset, length, PIC, usage | `extents.jsonl` | every declared field |
| exact copies | fixpoint `FLOWS_TO` edges with a `landing` | 1994 edges |
| literal assignments | the ASG statement's literal operand; `defs.jsonl` `values` appear only at the tests that consult them | part of the 3431 copy edges without a landing |
| inputs | edge `origin` kinds `FILE`, `MAP`, `CICS_STATE`, `CALL` | each becomes an unconstrained value |
| expressions | ASG `ComputeStatement.expression` and the other arithmetic statements | 633 rebuilt edges |
| crossing programs | `combine/links.jsonl` byte maps | XCTL, LINK, RETURN TRANSID |
| keeping formulas small | fixpoint def-use and CFG control dependence | per-goal backward slice |

## Stages

Each stage is one commit or more. A stage's gate questions become CardDemo testbed tests in the
style of `cobble/tests/carddemo/test_answers.py`:
- the source citation and the expected answer go in the docstring;
- the test asserts the solver's answer, and the SMT-LIB of any assumptions.

The solver time for each question is recorded in the stage's plan.

0. **Qualified node ids, and a spike.**
   - Clauses name a point as program plus node id.
   - `guards` names the program in each block it prints. A CFG file holds every program the
     seed reaches, and `WRITE-TRANSACT-FILE/0` exists in COBIL00C and COTRN02C. The query
     printed a block for each program under the same unlabelled heading (40 paths and 4), and
     a reader cannot tell them apart. Other artefacts already carry `program` beside `node` and
     are left alone.
   - The spike lowers sign-on's control flow and test atoms, and measures solver time.
   - Gate: COSGN00C can reach its XCTL to COMEN01C and its XCTL to COADM01C (`sat`). It never
     reaches the first with `CDEMO-USER-TYPE = 'A'`, nor the second with any other type
     (`unsat`). A gate comparing the solver's derivation with `guards` path 0 was dropped:
     without assignments, the infeasible paths are just as satisfiable, and the solver may
     return any of them.
1. **Control flow, tests and flag assignments, one task.** `SET` and literal `MOVE` are
   encoded; everything else is unconstrained, the incoming commarea included.
   - Gate: sign-on's four blank-id and blank-password paths to COMEN01C are `unsat`, and path 0
     is `sat`.
2. **Exact copies, frame conditions, inputs, PIC lengths, and the conversation.** Tasks chain
   through `RETURN TRANSID` and `XCTL` with the commarea's bytes mapped by `links.jsonl`, from a
   start with no commarea.
   - Gate: can COBIL00C's `REWRITE` run without `CONF-PAY-YES`? The confirmation arrives in a
     later task than the screen that asks for it.
   - Gate: is the `TRAN-AMT` written to TRANSACT always the `ACCT-CURR-BAL` that was read?
   - Gate: is the account rewritten to the key the user typed?
3. **Arithmetic from ASG expressions, with decimal scale, and loops through Spacer
   invariants.**
   - Gate: is the rewritten balance always zero?
   - Gate: can bill pay run when the balance is ≤ 0?
   - Gate: does CBACT04C add interest once per account per run?
4. **Every online program in one conversation.** Dynamic XCTL targets come from
   `combine/targets.jsonl`.
   - Gate: can a user whose USRSEC type is `'A'` reach COBIL00C through COMEN01C?
   - Gate: can a non-admin reach COUSR01C?
5. **STRING, INSPECT, numeric to alphanumeric conversions, NUMVAL-C.**
   - Gate: can COACTUPC's screen balance input set `ACCT-CURR-BAL` when it is not a valid
     number?

The three questions this work started from land in stage 2 (which screen fields guard a
transaction write), 3 (where the balance comes from) and 4 (what each user type can do).

## Left to the builder

- **How questions are asked.** Goals are written as SMT-LIB in the gate tests. A query command
  that builds goals from a program point and field conditions waits until a stage needs one.
- **The clause shape.** Small-step clauses inside a paragraph range, with a summary predicate
  per PERFORM range, so returns match without stack frames. This is the builder's call, and it
  may change if the spike shows otherwise.
- **The state representation.** Per-byte variables, fields as bit-vectors, or an array of
  bytes, chosen by the spike's measurements.
- **The package.** `cobble/experimental/horn/`, beside the Datalog export, until a stage shows
  it answers the questions.

## Not in scope

- Execution, dynamic witnesses, and red-dragon's IR.
- Proving the encoder correct. It is the trusted base, checked by the gate questions.
- Questions outside the code's meaning: intent, naming, what a program is for.
