# EXEC CICS WRITEQ TD operand resolution — design

## Context

`cicada-vcq` reports that `EXEC CICS WRITEQ TD` "is never dispatched." CORPT00C
(CardDemo's custom report submission) builds a JCL deck and submits it via
`EXEC CICS WRITEQ TD QUEUE('JOBS') FROM(JCL-RECORD) LENGTH(LENGTH OF
JCL-RECORD) RESP(WS-RESP-CD) RESP2(WS-REAS-CD)` in a loop
(`third-party/carddemo/app/cbl/CORPT00C.cbl:501-523`). The issue's original
two-part diagnosis was written against the pre-ANTLR4 Lark grammar and is now
half stale:

1. **"Dispatch mismatch" (verb key lookup fails)** — **already fixed.** The
   ANTLR4 grammar (post-migration) has a dedicated `WriteqTd` parse-tree rule;
   `cics/cics_visitor.py`'s `_get_verb` maps it directly to the composite
   string `"WRITEQ TD"`, which matches `cics/strategy.py`'s
   `_SYS_VERBS["WRITEQ TD"] = "__cics_writeq_td"` (line 61) cleanly. The
   builtin *is* called today.

2. **"Operands dropped"** — **still real.** The generic `_SYS_VERBS` dispatch
   path (`cics/strategy.py:919-932`) is verb-agnostic and always calls the
   builtin with `args=()`. Confirmed live: temporarily strengthening
   `test_real_carddemo_custom_report_submitted`'s assertion and running it
   under a correctly-configured JDK (JDK 17; this sandbox's default JDK 25
   breaks the vendored ProLeap bridge) produced
   `td_queue == ['[CSMT] ', '[CSMT] ', ...]` — 20 entries, all empty data
   under the wrong default queue name, instead of ~20 lines of real JCL text
   enqueued under `'JOBS'`.

While tracing this, a **third, separate** bug was found at the same call
site: `WRITEQ TD` is missing from `_RESP_PRODUCING_VERBS`, so
`RESP(WS-RESP-CD)`/`RESP2(WS-REAS-CD)` never gets written back — CORPT00C's
error-handling `EVALUATE` is silently unreachable today (masked by luck: the
field's `VALUE ZEROS` initial value happens to equal `DFHRESP(NORMAL)=0`).
Filed separately as `cicada-y6l` — deliberately **out of scope** for this fix,
per explicit scope decision, to keep this change narrow.

## Design

**1. Structural placement.** Pull `WRITEQ TD` out of the generic `_SYS_VERBS`
no-operand dispatch block into its own explicit `if verb == "WRITEQ TD":`
block in `cics/strategy.py`, placed alongside the other explicit per-verb
blocks (`ASSIGN`, `FORMATTIME`, the VSAM point/browse groups). This mirrors
precedent: `ASSIGN` and `FORMATTIME` were already pulled out of `_SYS_VERBS`
for the identical reason (per-operand handling), and both `return` before the
generic dispatch is ever reached. `_SYS_VERBS` keeps `ASKTIME`, `INQUIRE`, and
the three `HANDLE *` verbs — none of which need real input operands today.
(`INQUIRE` has its own separate, already-live operand-dropping bug — flagged
but explicitly not touched here; a future issue.)

**2. Operand resolution: `emit_operand_value` for both `QUEUE` and `FROM`.**
`td_queue` is a `list[str]` of decoded text, not a raw fixed-length byte
buffer (unlike VSAM records, which use `emit_copy_in` + `LoadRegion` to
preserve exact bytes). `emit_operand_value` (`cics/strategy.py:222`) already
does PIC-aware decoding via `ctx.emit_decode_field` and already handles
literal-vs-data-name operands transparently — exactly the CardDemo shape
(`QUEUE('JOBS')` is a literal; `FROM(JCL-RECORD)` is a data-name). Reuse it
for both, matching how it's already used for `MAP`/`MAPSET`/`PROGRAM`/
`TRANSID` elsewhere in the same file.

**3. `LENGTH` option: scoped out (YAGNI).** CORPT00C's real call passes
`LENGTH(LENGTH OF JCL-RECORD)` — a compile-time "whole field" length, not a
runtime-computed partial length. `emit_operand_value`'s full-field decode
already produces exactly that value. No CardDemo program passes a shorter
dynamic length to `WRITEQ TD`, so there's no real case to build against yet.

**4. Builtin call shape.** `make_writeq_td_builtin` (`cics/builtins/system.py:
129-136`) already has the right signature/behavior once given real args:
`args[0]` is the decoded `FROM` data, `args[1]` is the decoded `QUEUE` name.
No changes needed there — confirmed by the existing unit test
`tests/unit/cics/test_system_builtins.py::test_writeq_td_appends_to_queue`,
which already calls it with `(data, name)` in that order.

## Testing

- **Integration**: strengthen
  `tests/integration/cics/test_carddemo_reports.py::test_real_carddemo_custom_report_submitted`'s
  final assertion from `len(td_queue) > 0` to check both the queue name
  (`'JOBS'`) and real JCL content — the first enqueued line should contain
  `"//TRNRPT00 JOB"` (traced from `CORPT00C.cbl`'s `JOB-DATA-1` /
  `JOB-DATA-2 REDEFINES JOB-DATA-1` literal JCL table). Assert on content
  substrings, not an exact entry count, to avoid brittleness against
  `OCCURS`/`REDEFINES` lowering details unrelated to this fix.
- **Unit**: add a focused strategy-lowering test (new file or an existing
  `tests/unit/cics/test_strategy_*.py`) asserting that lowering a `WRITEQ TD
  QUEUE(...) FROM(...)` statement emits a `CallFunction` to
  `__cics_writeq_td` with two non-empty args (not `args=()`), following the
  existing pattern for asserting lowered IR shape in that test module.

## Out of scope

- `cicada-y6l` (RESP/RESP2 writeback) — filed separately, not touched here.
- `INQUIRE`'s own operand-dropping bug (found in passing; `make_inquire_builtin`
  reads `args[0]` but is still routed through the generic `args=()` path) —
  not filed yet, flagged for a future pass.

## Verification

- `uv run --no-sync python -m pytest tests/unit/cics/ -x -q` (fast).
- With `JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home`,
  `PROLEAP_BRIDGE_JAR=vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar`,
  `CARDDEMO_HOME=third-party/carddemo/app`:
  `uv run --no-sync python -m pytest tests/integration/cics/test_carddemo_reports.py -x -q`
  and the full `tests/integration/cics/` suite to confirm no regressions.
