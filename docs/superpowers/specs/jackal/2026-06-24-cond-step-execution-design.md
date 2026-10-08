# jackal — COND= conditional step execution — Design

**Status:** Designed (2026-06-24). Tracks `jackal-1o2.1` (label `jcl-language`). Resumes the
in-session brainstorm; refreshed for the ANTLR-bridge parser (was Lark at brainstorm time).
Awaiting user review of this spec.

## What this builds (plain terms)
Make jackal **honor `COND=`** — the JCL idiom that bypasses a step based on the return codes
of steps that already ran ("don't run this step if any prior step failed"). Today every step
runs unconditionally and every COBOL step reports success (`return_code=0` hardcoded), so a
failing step neither reports failure nor stops the chain. This is the most common step-flow
construct in real batch (5 of 38 CardDemo jobs) and the foundation the other step-flow
features build on.

## Scope
**In scope (`jackal-1o2.1`):**
- `COND=` on **EXEC** cards and on the **JOB** card (job-level applies to every step).
- Forms: `COND=(code,op)`, `COND=(code,op,stepname)`, and multiple `COND=((c,op),(c,op),…)`.
- Operators: `GT GE EQ NE LT LE`.
- **Real return codes**: COBOL steps read the VM's `RETURN-CODE` (Part 1, prerequisite);
  utilities already return real codes (IDCAMS MAXCC, IEFBR14 = 0).
- Bypassed steps recorded distinctly in the results.

**Out of scope (deferred):**
- `COND=EVEN` / `COND=ONLY` (abend-conditional) → `jackal-1o2.8` (needs the abend model).
  These **fail loud** here (clear "unsupported COND=EVEN/ONLY" error), not silently ignored.
- JCL `IF/THEN/ELSE/ENDIF` → `jackal-1o2.8`.
- True program abends (Sxxx/Uxxx) → `jackal-1o2.19`. COND operates on clean return codes; a
  hard VM crash keeps propagating as an exception (a real crash is a real failure).

## IBM semantics (not negotiable — these are the rules, baked in)
- **Reversed operands.** `COND=(code,op)` means "**bypass** this step if `code op RC` is true."
  `COND=(0,NE)` ⇒ bypass if `0 NE RC` ⇒ bypass when any prior RC ≠ 0 ("stop on first failure").
  `COND=(4,LT)` ⇒ bypass if `4 LT RC` ⇒ bypass when a prior RC > 4.
- **Which RCs are tested:** with no `stepname`, the test runs against **every prior step that
  actually executed**; with a `stepname`, only that step's RC. **Bypass if the condition is
  true for ANY tested step.**
- **Multiple conditions:** `COND=((c1,op1),(c2,op2))` ⇒ bypass if **ANY** condition is true.
- **JOB-level `COND=`:** evaluated for every step *in addition to* the step's own `COND=`;
  bypass if the job-level OR the step-level condition bypasses.
- **A named step that did not run** contributes no RC ⇒ that condition is false for it.
- **Bypassed steps contribute no RC** to later COND tests (only `EXECUTED` steps do).

## Architecture
The flat `Job.steps` tuple survives (COND= is a step/job *attribute*, no nesting). The two real
changes: (1) the runner gains **return-code state** (was a pure comprehension); (2) COBOL steps
report their **real** RC. Parsing is free — the mapa ANTLR grammar already parses `COND=`; the
work is surfacing it through the bridge JSON → model, and evaluating it.

```
JCL --(ANTLR bridge)--> JSON (now carries step.cond + job.cond)
   --> model: Job.cond, Step.conds: tuple[Cond,...]
JobRunner.run_job:  fold over steps, threading executed StepResults
   for each step: should_bypass(job.cond + step.conds, prior_executed) ?
       yes -> StepResult(disposition=BYPASSED, ran=False)   # not dispatched
       no  -> dispatch; StepResult(return_code=<real RC>, disposition=EXECUTED)
```

## Components

### 1. Java bridge — emit COND (`jcl-bridge/.../JclSerializer.java`)
Add a `cond` field to the JSON contract on each step, and a top-level `cond` for the JOB card.
Discover the mapa rule names for the COND parameter via `antlr4-parse -tree` (same method used
for the existing fields — do NOT guess). Serialize each condition as `{"code":int,"op":str,
"step":str}` (`step` = `""` when absent). `COND=EVEN`/`ONLY` → emit a marker the Python side
rejects loudly (e.g. `{"op":"EVEN"}`), so the fail-loud lives in one place. Forward-compatible:
absent `cond` ⇒ empty list (old behavior).

JSON contract addition:
```json
{ "name":"PIPE", "cond":[],
  "steps":[ {"name":"STEP1","pgm":"P","cond":[{"code":0,"op":"NE","step":""}],"dds":[…]} ] }
```

### 2. Python model (`jackal/model.py`)
```python
class CondOp(Enum):
    GT="GT"; GE="GE"; EQ="EQ"; NE="NE"; LT="LT"; LE="LE"

@dataclass(frozen=True)
class Cond:
    code: int
    op: CondOp
    step: str = ""          # "" = test all prior executed steps

# Step gains: conds: tuple[Cond, ...] = ()
# Job  gains: cond:  tuple[Cond, ...] = ()
```

### 3. Results (`jackal/results.py`)
```python
class StepDisposition(Enum):
    EXECUTED = "EXECUTED"
    BYPASSED = "BYPASSED"

# StepResult gains: disposition: StepDisposition = StepDisposition.EXECUTED
# return_code stays int (0 for a bypassed step; disposition is the real signal).
# `ran: bool` retained for back-compat (ran == (disposition is EXECUTED)).
```

### 4. Deserializer (`jackal/jcl/bridge_parser.py`)
Map `cond` JSON → `tuple[Cond,…]`; map `op` via `CondOp(op)` (a bad/`EVEN`/`ONLY` op raises
`ValueError` → wrapped as `JclParseError`, the existing fail-loud path). No `None`.

### 5. Real return code (Part 1 — `jackal/cobol_step.py`)
`run(...)` returns a `VMState`; capture it and return
`StepResult(return_code=read_return_code(vm), disposition=EXECUTED, ran=True)` instead of the
hardcoded `0`. Wrap `run(...)` so dataset `dispose` still happens (it currently runs after
`run()`; keep that, but a VM exception still propagates — a crash is a real failure, not RC).

### 6. COND evaluator (`jackal/cond.py`, pure)
```python
def should_bypass(conds: tuple[Cond,...], prior_executed: tuple[StepResult,...]) -> bool
```
For each `Cond`: gather the relevant RCs (named step → that step's RC if it executed, else none;
unnamed → all `prior_executed` RCs). The condition is true if `code <op> rc` holds for **any**
relevant RC. **Bypass if any condition is true.** Pure, no I/O, table-driven ops (no eval).

### 7. Runner (`jackal/runner.py`)
`run_job` becomes a fold (not a comprehension): accumulate `StepResult`s; before dispatching a
step, evaluate `should_bypass(job.cond + step.conds, <prior EXECUTED results>)`; if bypass →
append `StepResult(name, return_code=0, disposition=BYPASSED, ran=False)` **without dispatching**;
else dispatch and record the real RC + `EXECUTED`. Only `EXECUTED` results feed later tests.

## Error handling
- `COND=EVEN`/`ONLY` and any unknown op → fail loud (`JclParseError`), never silently ignored.
- A `stepname` referencing a step that doesn't exist in the job → the condition simply finds no
  RC (false) — IBM treats an unmatched stepname as not-yet-run; do **not** error. (Document.)
- No `None` defaults; no defensive guards; FP/frozen; no regex (ANTLR grammar parses COND).

## Testing (TDD — unit AND integration, all reachable paths)
- **Unit — evaluator (`tests/unit/test_cond.py`):** each op; reversed-operand semantics
  (`(0,NE)`, `(4,LT)`); multi-condition = any; named vs all-prior; named-step-not-run ⇒ false;
  bypassed steps excluded from prior; job-level + step-level combine.
- **Unit — model/deserializer:** `cond` JSON → `Step.conds`/`Job.cond`; `EVEN`/bad op ⇒
  `JclParseError`.
- **Unit — runner fold:** synthetic steps (utility/IEFBR14 RCs, no bridge) — a step returning
  RC 8 makes a downstream `COND=(0,NE)` and `COND=(4,LT)` step `BYPASSED`; a clean chain runs
  all; job-level `COND=(0,NE)` stops the chain after a failure.
- **Integration — real RC (`tests/integration/`, gated):** a COBOL program that `MOVE n TO
  RETURN-CODE` → `StepResult.return_code == n` (proves Part 1 end-to-end via `run()`); a
  two-step job where step 1 sets RC 8 and step 2 has `COND=(0,NE)` → step 2 `BYPASSED`.
- **Bridge — real JAR:** a JCL with `COND=(0,NE)` and `COND=((4,LT),(8,EQ))` parses into the
  expected `Cond` tuples; `COND=EVEN` fails loud.

## Binding constraints (CLAUDE.md)
- TDD; integration tests exercise VM execution via `run()`; cover **all** reachable paths.
- No `None` defaults; no defensive guards; **fail loud**; FP / frozen dataclasses.
- No regex for parsing (ANTLR grammar). `make jar` rebuilds the bridge; `uv run --no-sync`.
- Python 3.13, black, the real pre-commit hooks; `bd export -o beads/issues.jsonl` before any
  issue change.

## Risks
- **Bridge rule discovery** — mapa's COND rule names are the one unknown; resolve via
  `antlr4-parse -tree`, not guesswork (same as the original field discovery).
- **Part 1 RC change is behavior-changing** — COBOL steps stop always-reporting-0. The existing
  gated CardDemo e2e must stay green (its steps legitimately return 0); run it as the guard.
- **`ran` vs `disposition`** — keep `ran` as a derived/back-compat field so existing assertions
  (`s.ran`) don't break; `disposition` is the new source of truth.
