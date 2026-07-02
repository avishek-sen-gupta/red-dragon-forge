# WRITEQ TD Operand Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `EXEC CICS WRITEQ TD`'s `QUEUE` and `FROM` operands actually reach the `__cics_writeq_td` builtin, so CORPT00C's JCL-deck submission enqueues real content instead of empty placeholders under the wrong queue name.

**Architecture:** Pull `WRITEQ TD` out of `cics/strategy.py`'s generic no-operand `_SYS_VERBS` dispatch into its own explicit `if verb == "WRITEQ TD":` block, resolving both operands via the existing `emit_operand_value` helper (already used for `MAP`/`MAPSET`/`PROGRAM`/`TRANSID` elsewhere in the same file) and passing them as real `CallFunction` args.

**Tech Stack:** Python, RedDragon IR (`interpreter.instructions`), pytest.

## Global Constraints

- CICS-layer-only fix: `cics/strategy.py` + tests. No changes to `cics/builtins/system.py` (its signature is already correct) and no changes under `vendor/red-dragon/interpreter/vm/**` or other core-VM paths (per this repo's CLAUDE.md).
- `LENGTH` option: explicitly out of scope (YAGNI) — do not implement.
- RESP/RESP2 writeback: explicitly out of scope — tracked separately as `cicada-y6l`. Do not add `WRITEQ TD` to `_RESP_PRODUCING_VERBS` in this plan.
- `INQUIRE`'s own operand-dropping bug: out of scope, do not touch.
- TDD: write the failing test before the implementation, for both the unit and integration tasks.
- Format before considering any task done: `uv run --no-sync python -m black cics tests`.
- Run tests via `uv run --no-sync python -m pytest ...` (never a bare `uv run`, which re-syncs and rebuilds the editable red-dragon wheel).
- Git: conservative policy — do not commit or push as part of any task step. Stage and report only; the user commits explicitly.

---

### Task 1: Unit test — WRITEQ TD lowers with real args (not `args=()`)

**Files:**
- Modify (test only, add a new test function): `tests/unit/cics/test_strategy_screen.py`

**Interfaces:**
- Consumes: `cics.strategy.CicsLoweringStrategy.lower(ctx, stmt, materialised)` (existing), `interpreter.cobol.cobol_statements.ExecCicsStatement`, `CicsOperand` (existing).
- Produces: nothing new — this is a pure test task confirming Task 2's lowering change.

This test uses literal operands only (`QUEUE('JOBS')`, `FROM('SOME-DATA')` as `CicsOperand(..., is_literal=True)`), matching the existing minimal-fixture style of `test_send_map_lowers_to_call_function` in the same file — `emit_operand_value` takes the simple `Const.string` branch for a literal operand and never calls `has_field`/`resolve_field_ref`/`emit_decode_field`, so the fake `_Ctx` needs no more than `fresh_reg`/`emit_inst`.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/cics/test_strategy_screen.py` (append at the end of the file):

```python
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_writeq_td_lowers_with_real_args():
    """WRITEQ TD QUEUE('JOBS') FROM('SOME-DATA') passes both operands as real
    args to __cics_writeq_td — not args=() (cicada-vcq)."""
    from interpreter.instructions import CallFunction, Const
    from interpreter.cobol.cobol_statements import ExecCicsStatement
    from interpreter.cobol.cobol_statements import CicsOperand
    from interpreter.register import Register

    class _Ctx:
        def __init__(self):
            self.emitted = []
            self._n = 0

        def fresh_reg(self):
            self._n += 1
            return Register(f"%r{self._n}")

        def emit_inst(self, inst):
            self.emitted.append(inst)
            return inst

    ctx = _Ctx()
    stmt = ExecCicsStatement(
        verb="WRITEQ TD",
        options={
            "QUEUE": CicsOperand("JOBS", True),
            "FROM": CicsOperand("SOME-DATA", True),
        },
    )
    strategy = CicsLoweringStrategy(context_holder=[None], result_holder=[None])
    strategy.lower(ctx, stmt, materialised=None)

    calls = [
        i
        for i in ctx.emitted
        if isinstance(i, CallFunction)
        and i.func_name == FuncName("__cics_writeq_td")
    ]
    assert len(calls) == 1
    call = calls[0]
    assert len(call.args) == 2, f"expected 2 real args, got {call.args!r}"
    consts = {i.result_reg: i.value for i in ctx.emitted if isinstance(i, Const)}
    # args[0] = FROM data, args[1] = QUEUE name (make_writeq_td_builtin's order).
    assert consts[call.args[0]] == "SOME-DATA"
    assert consts[call.args[1]] == "JOBS"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync python -m pytest tests/unit/cics/test_strategy_screen.py::test_writeq_td_lowers_with_real_args -v`

Expected: FAIL — `assert len(call.args) == 2` fails because `call.args == ()` (the current generic `_SYS_VERBS` path emits `args=()`).

- [ ] **Step 3: Commit is deferred to Task 4** (this test and Task 2's implementation land together so the repo never sits with a permanently-red test committed alone — see Task 4).

---

### Task 2: Lower WRITEQ TD with real operands in `cics/strategy.py`

**Files:**
- Modify: `cics/strategy.py:919-932` (the generic `_SYS_VERBS` dispatch block) and `cics/strategy.py:56-68` (the `_SYS_VERBS` dict).

**Interfaces:**
- Consumes: `emit_operand_value(ctx, operand, materialised)` (existing, `cics/strategy.py:222`) — returns a `Register` holding the decoded runtime value for a literal or data-name operand.
- Produces: `WRITEQ TD` now lowers via its own explicit block (no longer via the generic `_SYS_VERBS` dispatch), emitting `CallFunction(func_name=FuncName("__cics_writeq_td"), args=(r_from, r_queue))`.

- [ ] **Step 1: Remove `"WRITEQ TD"` from the `_SYS_VERBS` dict**

In `cics/strategy.py`, change:

```python
_SYS_VERBS: dict[str, str] = {
    "ASSIGN": "__cics_assign",
    "ASKTIME": "__cics_asktime",
    "FORMATTIME": "__cics_formattime",
    "INQUIRE": "__cics_inquire",
    "WRITEQ TD": "__cics_writeq_td",
    "HANDLE ABEND": "__cics_handle_abend",
    # HANDLE CONDITION / HANDLE AID are explicit no-ops for now — the real
    # runtime-dispatch machinery is a deferred follow-up
    # (docs/superpowers/plans/2026-06-07-cics-handle-condition-machinery.md).
    "HANDLE CONDITION": "__cics_handle_condition",
    "HANDLE AID": "__cics_handle_aid",
}
```

to:

```python
_SYS_VERBS: dict[str, str] = {
    "ASSIGN": "__cics_assign",
    "ASKTIME": "__cics_asktime",
    "FORMATTIME": "__cics_formattime",
    "INQUIRE": "__cics_inquire",
    "HANDLE ABEND": "__cics_handle_abend",
    # HANDLE CONDITION / HANDLE AID are explicit no-ops for now — the real
    # runtime-dispatch machinery is a deferred follow-up
    # (docs/superpowers/plans/2026-06-07-cics-handle-condition-machinery.md).
    "HANDLE CONDITION": "__cics_handle_condition",
    "HANDLE AID": "__cics_handle_aid",
}
```

(`"WRITEQ TD": "__cics_writeq_td",` line removed. `ASSIGN`/`FORMATTIME` stay in the dict even though they're intercepted earlier by their own `if verb == "ASSIGN":`/`if verb == "FORMATTIME":` blocks — pre-existing pattern in this file, not touched here.)

- [ ] **Step 2: Add the explicit `WRITEQ TD` block immediately before the generic `_SYS_VERBS` dispatch**

In `cics/strategy.py`, immediately before the `# ── System verbs ──` comment (currently at line 919), insert:

```python
        # ── WRITEQ TD ────────────────────────────────────────────────────
        if verb == "WRITEQ TD":
            r_from = emit_operand_value(ctx, opts.get("FROM"), materialised)
            r_queue = emit_operand_value(ctx, opts.get("QUEUE"), materialised)
            r_res = ctx.fresh_reg()
            ctx.emit_inst(
                CallFunction(
                    result_reg=r_res,
                    func_name=FuncName("__cics_writeq_td"),
                    args=(r_from, r_queue),
                )
            )
            return

```

Resulting order at that point in `lower()`: the new `WRITEQ TD` block, then the unchanged `# ── System verbs ──` comment and generic `_SYS_VERBS` dispatch. `emit_operand_value` and `FuncName`/`CallFunction` are already imported at the top of `cics/strategy.py` (used elsewhere in the same file) — no new imports needed.

- [ ] **Step 3: Run the Task 1 unit test to verify it now passes**

Run: `uv run --no-sync python -m pytest tests/unit/cics/test_strategy_screen.py::test_writeq_td_lowers_with_real_args -v`

Expected: PASS.

- [ ] **Step 4: Run the full unit suite to check for regressions**

Run: `uv run --no-sync python -m pytest tests/unit/ -x -q`

Expected: all tests pass (same count as before this change, plus the one new test).

---

### Task 3: Strengthen the integration test's assertion

**Files:**
- Modify: `tests/integration/cics/test_carddemo_reports.py:246` (the final assertion of `test_real_carddemo_custom_report_submitted`).

**Interfaces:**
- Consumes: `td_queue: list[str]` (existing fixture return value from `_drive_to_reports`), whose entries are now (after Task 2) formatted as `f"[{queue_name}] {data}"` by `make_writeq_td_builtin` (`cics/builtins/system.py:129-136`, unchanged).
- Produces: nothing new for other tasks — this is the end-to-end proof the fix works against real compiled CORPT00C.

The real JCL content comes from `third-party/carddemo/app/cbl/CORPT00C.cbl:81-127` (`JOB-DATA-1` / `JOB-DATA-2 REDEFINES JOB-DATA-1`) — the first literal JCL line is `"//TRNRPT00 JOB 'TRAN REPORT',CLASS=A,MSGCLASS=0,"`.

- [ ] **Step 1: Write the failing (stronger) assertion**

In `tests/integration/cics/test_carddemo_reports.py`, replace the final line of `test_real_carddemo_custom_report_submitted`:

```python
    # WRITEQ TD is now dispatched; JCL lines are streamed to the TD queue.
    assert len(td_queue) > 0, f"expected JCL lines in td_queue, got: {td_queue}"
```

with:

```python
    # WRITEQ TD is now dispatched with real operands; JCL lines are streamed
    # to the 'JOBS' TD queue with real content (cicada-vcq).
    assert len(td_queue) > 0, f"expected JCL lines in td_queue, got: {td_queue}"
    assert all(
        line.startswith("[JOBS] ") for line in td_queue
    ), f"expected every line under the 'JOBS' queue, got: {td_queue}"
    assert any(
        "//TRNRPT00 JOB" in line for line in td_queue
    ), f"expected the JCL job card in td_queue, got: {td_queue}"
```

- [ ] **Step 2: Run this test to verify it currently fails**

This requires the JAR-gated environment (this sandbox's default JDK breaks the vendored ProLeap bridge):

```bash
export JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home
export PATH="$JAVA_HOME/bin:$PATH"
export PROLEAP_BRIDGE_JAR=~/code/cicada/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
export CARDDEMO_HOME=~/code/cicada/third-party/carddemo/app
uv run --no-sync python -m pytest tests/integration/cics/test_carddemo_reports.py::test_real_carddemo_custom_report_submitted -v
```

Expected: FAIL on the `startswith("[JOBS] ")` assertion — current output is 20 entries of `"[CSMT] "` (empty data, wrong queue name), from before Task 2's fix lands in the same working tree. (If Task 2 is already applied when this step runs, this assertion will already pass — that's fine; the important verification is Step 3 below with Task 2 in place.)

- [ ] **Step 3: Run this test with Task 2's fix in place to verify it passes**

Same command as Step 2 (Task 2's changes to `cics/strategy.py` are already in the working tree by this point in the plan):

```bash
export JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home
export PATH="$JAVA_HOME/bin:$PATH"
export PROLEAP_BRIDGE_JAR=~/code/cicada/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
export CARDDEMO_HOME=~/code/cicada/third-party/carddemo/app
uv run --no-sync python -m pytest tests/integration/cics/test_carddemo_reports.py::test_real_carddemo_custom_report_submitted -v
```

Expected: PASS.

---

### Task 4: Full verification, formatting, beads bookkeeping

**Files:**
- Format: `cics/strategy.py`, `tests/unit/cics/test_strategy_screen.py`, `tests/integration/cics/test_carddemo_reports.py`.
- Beads: `cicada-vcq` (close), `beads/issues.jsonl` (re-export).

- [ ] **Step 1: Format changed files**

```bash
uv run --no-sync python -m black cics tests
```

Expected: `All done!` — 0 or more files reformatted, no errors.

- [ ] **Step 2: Run the full unit suite**

```bash
uv run --no-sync python -m pytest tests/unit/ -x -q
```

Expected: all pass.

- [ ] **Step 3: Run the full CICS integration suite**

```bash
export JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home
export PATH="$JAVA_HOME/bin:$PATH"
export PROLEAP_BRIDGE_JAR=~/code/cicada/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
export CARDDEMO_HOME=~/code/cicada/third-party/carddemo/app
uv run --no-sync python -m pytest tests/integration/cics/ -x -q
```

Expected: all pass (same 66-test count as the session's earlier full-suite baseline, plus no regressions from this change).

- [ ] **Step 4: Close `cicada-vcq` in beads**

```bash
bd close cicada-vcq --reason="Fixed: WRITEQ TD's dispatch-mismatch half was already resolved by the ANTLR4 grammar migration (WriteqTd rule -> composite verb string 'WRITEQ TD', matches _SYS_VERBS cleanly). The remaining operand-dropping bug is fixed: WRITEQ TD is now lowered in its own explicit block in cics/strategy.py (pulled out of the generic no-operand _SYS_VERBS dispatch), resolving QUEUE and FROM via emit_operand_value and passing them as real CallFunction args. TDD: unit test (tests/unit/cics/test_strategy_screen.py::test_writeq_td_lowers_with_real_args) + strengthened real-COBOL integration test (tests/integration/cics/test_carddemo_reports.py::test_real_carddemo_custom_report_submitted), both verified to fail without the fix. RESP/RESP2 writeback (a separate bug found at the same call site) is intentionally out of scope, tracked as cicada-y6l."
```

- [ ] **Step 5: Re-export the beads snapshot**

```bash
bd export -o beads/issues.jsonl
```

- [ ] **Step 6: Report status — do NOT commit**

Per this repo's conservative git policy, stop here. Run `git status` and `git diff --stat` and report the changed files to the user:

```bash
git status
git diff --stat
```

Report the list of modified/staged files (expected: `cics/strategy.py`, `tests/unit/cics/test_strategy_screen.py`, `tests/integration/cics/test_carddemo_reports.py`, `beads/issues.jsonl`) and wait for the user to explicitly request a commit/push.
