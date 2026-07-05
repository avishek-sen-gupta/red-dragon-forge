# WRITEQ TD RESP/EIBRESP Writeback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `EXEC CICS WRITEQ TD` write back `EIBRESP` and its `RESP(name)` field like every other RESP-producing CICS verb already does, instead of silently leaving them untouched.

**Architecture:** `make_writeq_td_builtin` starts returning a real numeric response code (always "normal," since nothing in this emulation can fail a TD-queue append) instead of `None`; `cics/strategy.py`'s `WRITEQ TD` lowering block gains one call to the existing shared `emit_resp_writeback` helper, exactly matching the pattern already used by 10 other verbs in the same file.

**Tech Stack:** Python, RedDragon IR (`interpreter.instructions`), pytest.

## Global Constraints

- CICS-layer-only fix: `cics/strategy.py`, `cics/builtins/system.py`, and tests. No RedDragon/VM core changes, no changes to `CORPT00C.cbl` or any real CardDemo source.
- Scope: `WRITEQ TD` and `RESP`/`EIBRESP` only. `RESP2` support is explicitly out of scope — it doesn't exist anywhere in this codebase for any verb, and this plan does not add it.
- No magic numbers, ever, in new code — introduce named constants for every numeric literal that carries meaning, even for "obvious" values like a success code.
- TDD: write the failing test before the implementation, for both new tests.
- Format before considering any task done: `uv run --no-sync python -m black cics tests`.
- Run tests via `uv run --no-sync python -m pytest ...` (never a bare `uv run`, which re-syncs and rebuilds the editable red-dragon wheel).
- Git: conservative policy — do not commit or push as part of any task step. Stage and report only; the user commits explicitly.

---

### Task 1: Unit test — WRITEQ TD's lowered IR includes the resp-writeback

**Files:**
- Modify (test only, add a new test function and a fuller fake context): `tests/unit/cics/test_strategy_screen.py`

**Interfaces:**
- Consumes: `cics.strategy.CicsLoweringStrategy.lower(ctx, stmt, materialised)` (existing), `interpreter.cobol.cobol_statements.ExecCicsStatement`/`CicsOperand` (existing).
- Produces: nothing new for later tasks — this test proves Task 2's implementation change.

**Why this needs a fuller fake context than the existing `test_writeq_td_lowers_with_real_args`**: that test's `_Ctx` only has `fresh_reg`/`emit_inst` — enough to check `FROM`/`QUEUE` resolve to real args, but not enough to exercise `emit_resp_writeback`, which internally calls `ctx.has_field(...)`, `ctx.resolve_field_ref(...)`, `ctx.emit_encode_and_write(...)`, and `ctx.emit_to_string(...)`. `tests/unit/cics/test_field_ref_wiring.py` already has a `FakeCtx` class implementing exactly this fuller surface (used by its own `test_resp_writeback_writes_eibresp_and_resp_field` test) — this task writes a similarly-shaped local fake in `test_strategy_screen.py` (matching that file's existing convention of one local `_Ctx`/fake per test, not a shared import across test files).

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/cics/test_strategy_screen.py` (append at the end of the file):

```python
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_writeq_td_lowers_with_resp_writeback():
    """WRITEQ TD QUEUE('JOBS') FROM('SOME-DATA') RESP(WS-RC) writes both
    EIBRESP and the RESP(name) field — not silently dropped (cicada-y6l)."""
    from interpreter.instructions import CallFunction
    from interpreter.cobol.cobol_statements import ExecCicsStatement
    from interpreter.cobol.cobol_statements import CicsOperand
    from interpreter.cobol.cobol_types import CobolDataCategory, CobolTypeDescriptor
    from interpreter.cobol.data_layout import FieldLayout
    from interpreter.cobol.field_resolution import ResolvedFieldRef
    from interpreter.register import Register

    class _RespCtx:
        """Faithful fake EmitContext supporting the emit_resp_writeback path —
        mirrors tests/unit/cics/test_field_ref_wiring.py's FakeCtx."""

        def __init__(self, fields):
            self._fields = fields
            self.emitted = []
            self.encode_writes = []
            self._n = 0

        def fresh_reg(self):
            self._n += 1
            return Register(f"%r{self._n}")

        def emit_inst(self, inst):
            self.emitted.append(inst)
            return inst

        def has_field(self, name, materialised):
            return name in self._fields

        def resolve_field_ref(self, name, materialised, qualifiers=(), subscripts=()):
            offset, byte_length = self._fields[name]
            fl = FieldLayout(
                name=name,
                type_descriptor=CobolTypeDescriptor(
                    category=CobolDataCategory.ALPHANUMERIC,
                    total_digits=byte_length,
                ),
                offset=offset,
                byte_length=byte_length,
            )
            offset_reg = self.fresh_reg()
            self.emit_inst(("const_offset", offset_reg, offset))
            return ResolvedFieldRef(fl=fl, offset_reg=offset_reg), Register("%region")

        def emit_encode_and_write(self, region_reg, fl, value_str_reg, offset_reg=None):
            self.encode_writes.append((region_reg, fl, value_str_reg, offset_reg))

        def emit_to_string(self, value_reg):
            out = self.fresh_reg()
            self.emit_inst(("to_string", out, value_reg))
            return out

    ctx = _RespCtx({"EIBRESP": (0, 4), "WS-RC": (16, 4)})
    stmt = ExecCicsStatement(
        verb="WRITEQ TD",
        options={
            "QUEUE": CicsOperand("JOBS", True),
            "FROM": CicsOperand("SOME-DATA", True),
            "RESP": CicsOperand("WS-RC", False),
        },
    )
    strategy = CicsLoweringStrategy(context_holder=[None], result_holder=[None])
    strategy.lower(ctx, stmt, materialised=None)

    calls = [
        i
        for i in ctx.emitted
        if isinstance(i, CallFunction) and i.func_name == FuncName("__cics_writeq_td")
    ]
    assert len(calls) == 1, "expected exactly one __cics_writeq_td call"

    assert len(ctx.encode_writes) == 2, (
        f"expected EIBRESP + RESP(WS-RC) writes, got {ctx.encode_writes!r}"
    )
    written_names = {fl.name for (_, fl, _, _) in ctx.encode_writes}
    assert written_names == {"EIBRESP", "WS-RC"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync python -m pytest tests/unit/cics/test_strategy_screen.py::test_writeq_td_lowers_with_resp_writeback -v`

Expected: FAIL — `assert len(ctx.encode_writes) == 2` fails because `ctx.encode_writes == []` (the current `WRITEQ TD` lowering never calls `emit_resp_writeback`).

- [ ] **Step 3: Commit is deferred to Task 4** (this test and Task 2's implementation land together, same pattern as every fix this session — no permanently-red test sits alone).

---

### Task 2: Named constants + the functional fix

**Files:**
- Modify: `cics/builtins/system.py` (add named constants, fix `make_writeq_td_builtin` and `make_inquire_builtin`).
- Modify: `cics/strategy.py:918-930` (the `WRITEQ TD` lowering block).
- Modify: `tests/unit/cics/test_strategy_screen.py` (fix the pre-existing `test_writeq_td_lowers_with_real_args` test, which will otherwise start crashing once this task's change lands — see Step 4 below for why).

**Interfaces:**
- Consumes: `emit_resp_writeback(ctx, r_resp_result, opts, materialised)` (existing, `cics/strategy.py:282-298`).
- Produces: `make_writeq_td_builtin` now returns `BuiltinResult(value=_RESP_NORMAL)` (an `int`, `0`) instead of `BuiltinResult(value=None)`. `WRITEQ TD` lowering now calls `emit_resp_writeback` after its `CallFunction` emission.

- [ ] **Step 1: Add named constants to `cics/builtins/system.py` and use them in `make_inquire_builtin`**

Read the top of `cics/builtins/system.py` first — find the module-level area right after the imports (before `logger = logging.getLogger(__name__)` or right after it; match whatever the file's existing top-of-file layout is) and add:

```python
_RESP_NORMAL = 0  # DFHRESP(NORMAL) — nothing went wrong
_RESP_PGMIDERR = 27  # DFHRESP(PGMIDERR) — INQUIRE's "program not found"
```

Then find `make_inquire_builtin` (currently):

```python
def make_inquire_builtin(program_cache: dict) -> object:  # type: ignore[type-arg]
    def __cics_inquire(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        name = str(args[0].value).strip() if args else ""
        resp = 0 if name in program_cache else 27  # 27 = PGMIDERR
        return BuiltinResult(value=resp)

    return __cics_inquire
```

Change the `resp = ...` line to use the new constants:

```python
def make_inquire_builtin(program_cache: dict) -> object:  # type: ignore[type-arg]
    def __cics_inquire(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        name = str(args[0].value).strip() if args else ""
        resp = _RESP_NORMAL if name in program_cache else _RESP_PGMIDERR
        return BuiltinResult(value=resp)

    return __cics_inquire
```

- [ ] **Step 2: Make `make_writeq_td_builtin` return a real resp code**

Change:

```python
def make_writeq_td_builtin(queue: list[str]) -> object:
    def __cics_writeq_td(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        data = str(args[0].value) if args else ""
        name = str(args[1].value) if len(args) > 1 else "CSMT"
        queue.append(f"[{name}] {data}")
        return BuiltinResult(value=None)

    return __cics_writeq_td
```

to:

```python
def make_writeq_td_builtin(queue: list[str]) -> object:
    def __cics_writeq_td(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        data = str(args[0].value) if args else ""
        name = str(args[1].value) if len(args) > 1 else "CSMT"
        queue.append(f"[{name}] {data}")
        return BuiltinResult(value=_RESP_NORMAL)

    return __cics_writeq_td
```

- [ ] **Step 3: Add the resp-writeback call to `WRITEQ TD`'s lowering in `cics/strategy.py`**

Change:

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

to:

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
            emit_resp_writeback(ctx, r_res, opts, materialised)
            return
```

- [ ] **Step 4: Fix the pre-existing test that this change will otherwise break**

`tests/unit/cics/test_strategy_screen.py::test_writeq_td_lowers_with_real_args` (added earlier this session for `cicada-vcq`) uses a minimal fake `_Ctx` with only `fresh_reg`/`emit_inst`. Once Step 3 lands, `WRITEQ TD`'s lowering calls `emit_resp_writeback`, which calls `ctx.has_field("EIBRESP", materialised)` — a method that minimal `_Ctx` doesn't define at all, so the test would crash with `AttributeError` instead of passing. Add a `has_field` method that returns `False` (this test doesn't care about resp-writeback — it only asserts on `FROM`/`QUEUE` args — so the cleanest fix is to make the write-back cleanly no-op, matching what `emit_copy_back_str` already does when a field is unknown).

In `tests/unit/cics/test_strategy_screen.py`, find `test_writeq_td_lowers_with_real_args`'s `_Ctx` class:

```python
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
```

Change it to add the `has_field` method:

```python
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

        def has_field(self, name, materialised):
            return False

    ctx = _Ctx()
    stmt = ExecCicsStatement(
        verb="WRITEQ TD",
        options={
            "QUEUE": CicsOperand("JOBS", True),
            "FROM": CicsOperand("SOME-DATA", True),
        },
    )
```

(No `RESP` option is present in this test's `stmt.options`, and `EIBRESP`'s write-back is unconditional — `has_field` returning `False` makes both the `EIBRESP` write and the absent-`RESP` write no-op cleanly, without needing full field resolution machinery this test doesn't otherwise use.)

- [ ] **Step 5: Run Task 1's test to verify it now passes**

Run: `uv run --no-sync python -m pytest tests/unit/cics/test_strategy_screen.py::test_writeq_td_lowers_with_resp_writeback -v`

Expected: PASS.

- [ ] **Step 6: Run the full unit suite to check for regressions**

Run: `uv run --no-sync python -m pytest tests/unit/ -x -q`

Expected: all tests pass, including `test_writeq_td_lowers_with_real_args` (fixed in Step 4) and `test_system_builtins.py`'s existing INQUIRE/WRITEQ-TD-builtin tests (unaffected by the constant rename — they call the builtins directly with explicit args, not via the module-level constant names).

---

### Task 3: Integration test — proves the writeback actually executes (not just "already zero")

**Files:**
- Modify: `tests/integration/cics/test_region_e2e.py` (add a new synthetic COBOL program and test function).

**Interfaces:**
- Consumes: `cics.bootstrap.run_carddemo_region` (existing), `cics.dispatcher.InputEvent` (existing), `cics.preprocessor.apply_cics_prepass` (existing) — same imports this file already has, no new ones needed.
- Produces: nothing new for other tasks — this is the end-to-end proof.

**Why a synthetic program, and why the poisoned sentinel**: `WS-RESP-CD`-style fields in real CardDemo start at `0`, and this fix's "success" code is also `0` — so a test using real CardDemo source (like `CORPT00C`) can't tell "fixed" from "still broken," because both states produce `0`. This program deliberately starts its resp field at a non-zero sentinel (`999` — not a real CICS response code) so only a genuine write-back can bring it back to `0`.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/cics/test_region_e2e.py` (append at the end of the file, after `test_send_map_data_name_resolves_runtime_value`):

```python
# WRITEQ TD RESP writeback proof (cicada-y6l): WS-RESP-CD starts "poisoned" at
# a sentinel that is NOT a real CICS response code (999). Only a genuine
# RESP writeback can bring it back to 0 — a naive "assert it's 0" test can't
# distinguish "fixed" from "field was already 0 and nothing touched it",
# since 0 is also DFHRESP(NORMAL). The MOVE to a DISPLAY field before SEND
# MAP is required because WS-RESP-CD is COMP (binary) — not printable via a
# symbolic map directly; real COBOL programs always de-edit COMP fields to
# DISPLAY before showing them on screen, same as this test does.
TDRESPGM_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TDRESPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 TDRMAP.
          05 RESPO PIC 9(9).
       01 WS-DATA PIC X(8) VALUE 'HELLOTD!'.
       01 WS-RESP-CD PIC S9(09) COMP VALUE 999.
       PROCEDURE DIVISION.
           EXEC CICS WRITEQ TD QUEUE('TESTQ') FROM(WS-DATA)
                     RESP(WS-RESP-CD) END-EXEC.
           MOVE WS-RESP-CD TO RESPO.
           EXEC CICS SEND MAP('TDRMAP') FROM(TDRMAP) END-EXEC.
           EXEC CICS RETURN END-EXEC.
           STOP RUN.
"""


@covers(CobolFeature.EXEC_CICS)
def test_writeq_td_writes_back_resp(cobol_parser):
    """WRITEQ TD's RESP(WS-RESP-CD) is genuinely written, not silently
    dropped: a poisoned sentinel (999) becomes 0 (DFHRESP(NORMAL)) after the
    call — proving the writeback executed rather than the field already
    being 0 (cicada-y6l)."""
    screen_q: queue.Queue = queue.Queue()
    input_q: queue.Queue = queue.Queue()

    result = run_carddemo_region(
        transid_to_program={"CC00": "TDRESPGM"},
        program_sources={"TDRESPGM": apply_cics_prepass(TDRESPGM_SRC).encode()},
        parser=cobol_parser,
        entry_transid="CC00",
        screen_queue=screen_q,
        input_queue=input_q,
    )

    assert result.kind == DispatchKind.RETURN

    screens = drain(screen_q)
    assert len(screens) == 1
    assert screens[0]["map"] == "TDRMAP"
    assert screens[0]["fields"].get("RESP") == "000000000", (
        f"expected WS-RESP-CD written back to 0 (DFHRESP(NORMAL)), "
        f"got screen fields: {screens[0]['fields']!r}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Requires the JAR-gated environment (this sandbox's default JDK breaks the vendored ProLeap bridge):

```bash
export JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home
export PATH="$JAVA_HOME/bin:$PATH"
export PROLEAP_BRIDGE_JAR=~/code/cicada/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
export CARDDEMO_HOME=~/code/cicada/third-party/carddemo/app
uv run --no-sync python -m pytest tests/integration/cics/test_region_e2e.py::test_writeq_td_writes_back_resp -v
```

Expected: FAIL — `screens[0]["fields"].get("RESP")` is `"000000999"` (the poisoned sentinel, untouched), not `"000000000"`. (If Task 2 is already applied when this step runs — since these tasks land in the same working tree — this assertion will already pass; that's fine, the important verification is Step 3 below with Task 2 confirmed in place.)

- [ ] **Step 3: Run this test with Task 2's fix in place to verify it passes**

Same command as Step 2:

```bash
export JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home
export PATH="$JAVA_HOME/bin:$PATH"
export PROLEAP_BRIDGE_JAR=~/code/cicada/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
export CARDDEMO_HOME=~/code/cicada/third-party/carddemo/app
uv run --no-sync python -m pytest tests/integration/cics/test_region_e2e.py::test_writeq_td_writes_back_resp -v
```

Expected: PASS.

- [ ] **Step 4: Run the real CORPT00C test to confirm its observable behavior is unchanged**

```bash
export JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home
export PATH="$JAVA_HOME/bin:$PATH"
export PROLEAP_BRIDGE_JAR=~/code/cicada/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
export CARDDEMO_HOME=~/code/cicada/third-party/carddemo/app
uv run --no-sync python -m pytest tests/integration/cics/test_carddemo_reports.py::test_real_carddemo_custom_report_submitted -v
```

Expected: PASS — same as before this fix. This is correct, not a sign the fix did nothing: `WS-RESP-CD` in CORPT00C starts at `0` and this fix also writes `0`, so its `EVALUATE ... WHEN DFHRESP(NORMAL)` branch was already being taken (by coincidence) before this fix, and is now taken for the right reason. `test_writeq_td_writes_back_resp` (Steps 2-3 above) is what actually proves the fix works — this step only confirms no regression in real CardDemo behavior.

---

### Task 4: Full verification, formatting, beads bookkeeping

**Files:**
- Format: `cics/strategy.py`, `cics/builtins/system.py`, `tests/unit/cics/test_strategy_screen.py`, `tests/integration/cics/test_region_e2e.py`.
- Beads: `cicada-y6l` (close), `beads/issues.jsonl` (re-export).

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

Expected: all pass, no regressions, including the new `test_writeq_td_writes_back_resp` and the confirmed-unchanged `test_real_carddemo_custom_report_submitted`.

- [ ] **Step 4: Close `cicada-y6l` in beads**

```bash
bd close cicada-y6l --reason="Fixed: make_writeq_td_builtin now returns a real resp code (_RESP_NORMAL = 0, a named constant, since nothing in this emulation can fail a TD-queue append) instead of BuiltinResult(value=None), and WRITEQ TD's lowering in cics/strategy.py now calls emit_resp_writeback — the same shared helper the other 10 RESP-producing verbs already use. Also cleaned up make_inquire_builtin's pre-existing magic numbers (0/27) in the same file, using the same two new named constants (_RESP_NORMAL, _RESP_PGMIDERR). Scope: RESP/EIBRESP only, WRITEQ TD only — RESP2 support remains out of scope for all verbs, unchanged. TDD: unit test (tests/unit/cics/test_strategy_screen.py::test_writeq_td_lowers_with_resp_writeback) + a synthetic-COBOL integration test with a poisoned sentinel value (tests/integration/cics/test_region_e2e.py::test_writeq_td_writes_back_resp, since real CardDemo's WS-RESP-CD already starts at 0 and can't distinguish fixed-from-broken), both verified to fail without the fix. Confirmed CORPT00C's real observable behavior (test_carddemo_reports.py) is unchanged, as expected — nothing in this emulation can currently fail a WRITEQ TD, so this closes a correctness landmine for future failure-path modeling rather than fixing a currently-visible bug."
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

Report the list of modified/staged files (expected: `cics/strategy.py`, `cics/builtins/system.py`, `tests/unit/cics/test_strategy_screen.py`, `tests/integration/cics/test_region_e2e.py`, `beads/issues.jsonl`) and wait for the user to explicitly request a commit/push.
