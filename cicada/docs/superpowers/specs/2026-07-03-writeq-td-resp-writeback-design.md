# EXEC CICS WRITEQ TD RESP/EIBRESP writeback — design

## Context

CORPT00C (a real CardDemo program) submits a JCL deck via a loop of
`EXEC CICS WRITEQ TD QUEUE('JOBS') FROM(JCL-RECORD) LENGTH(LENGTH OF
JCL-RECORD) RESP(WS-RESP-CD) RESP2(WS-REAS-CD) END-EXEC.`, immediately
followed by `EVALUATE WS-RESP-CD WHEN DFHRESP(NORMAL) CONTINUE WHEN OTHER
...error handling...` (`third-party/carddemo/app/cbl/CORPT00C.cbl:517-534`).

**Background** (for readers new to CICS): `RESP(field)` is an optional
clause on a CICS command that copies the command's outcome — a numeric
response code — into a field of the program's choosing, right after the
call. `0` always means `DFHRESP(NORMAL)` ("nothing went wrong"); other
numbers mean specific named error conditions. `EIBRESP` is a similar field
that CICS *always* updates automatically, regardless of whether `RESP()` was
used. `RESP2(field)` is a second, optional, more granular code that
supplements `RESP` for a handful of conditions — most commands don't set it.

`cics/strategy.py:918-930` (added this session as part of `cicada-vcq`)
lowers `WRITEQ TD` but never calls `emit_resp_writeback` (`cics/strategy.py:
282-298`, the shared helper that writes `EIBRESP` and `RESP()`) — unlike the
10 other verbs that already call it (`READ`/`WRITE`/`REWRITE`/`DELETE`,
`STARTBR`/`READNEXT`/`READPREV`/`ENDBR`, `INQUIRE`, `LINK`).
`make_writeq_td_builtin` (`cics/builtins/system.py:129-136`) doesn't even
return a numeric code — `BuiltinResult(value=None)`.

Today this is silent by luck, not correctness: `WS-RESP-CD` is declared
`VALUE ZEROS` (starts at `0`), and `0` also happens to be `DFHRESP(NORMAL)`
— so `EVALUATE WS-RESP-CD` always takes the success branch regardless.
Nothing in this VSAM/TD-queue emulation can currently fail a `WRITEQ TD`
(`make_writeq_td_builtin` just unconditionally appends to a list), so this
never currently produces an observably wrong result — but it will the
moment any future work models a `WRITEQ TD` failure mode.

The affected lowering code (`cics/strategy.py`) is exercised on every real
`WRITEQ TD` call regardless of which dispatcher drives the program
(`CicsRegion` or the autonomous loop fixed in `red-dragon-pz9g.14`) — it
runs ~20 times in `tests/integration/cics/test_carddemo_reports.py::
test_real_carddemo_custom_report_submitted`, a real, currently-passing test.
But because nothing can currently fail, this fix writes the same `0` the
field already holds — so it doesn't change that test's *observable* screen
output today. Its value is closing a correctness landmine for the future,
not fixing a currently-visible bug.

## Design

**1. Scope: narrow, `WRITEQ TD` only.** `RESP2` support is explicitly out of
scope — it doesn't exist anywhere in this codebase today (`emit_resp_writeback`
only handles `EIBRESP`/`RESP()`), for any of the 10 verbs that already use
the shared helper, not just `WRITEQ TD`. This fix doesn't touch that gap;
CORPT00C only branches on `RESP`, never `RESP2`. Explicit user decision, to
keep the change's blast radius to one verb rather than touching shared
plumbing used by 10 already-working, already-tested verb lowerings.

**2. Named constants — no magic numbers, ever, in new code** (explicit user
rule, applies beyond this one fix). Add to `cics/builtins/system.py`:

```python
_RESP_NORMAL = 0      # DFHRESP(NORMAL) — nothing went wrong
_RESP_PGMIDERR = 27   # DFHRESP(PGMIDERR) — INQUIRE's "program not found"
```

`make_inquire_builtin`'s existing `resp = 0 if name in program_cache else 27`
switches to use these two names (pre-existing magic numbers in the same
file, in scope per explicit user decision — "clean that up too"). No import
from `cics/vsam/eibresp.py` (which already defines its own `RESP_NORMAL`
for VSAM file-access conditions specifically): `WRITEQ TD` isn't a VSAM
operation, and `cics/builtins/system.py` currently imports nothing from that
module — a local constant avoids an otherwise-unneeded cross-package
coupling for what both files agree is just the universal "normal" code.

**3. The functional fix.** `make_writeq_td_builtin` returns
`BuiltinResult(value=_RESP_NORMAL)` instead of `BuiltinResult(value=None)` —
since nothing in this emulation can fail a `WRITEQ TD`, it's always
"normal." `cics/strategy.py`'s `WRITEQ TD` block adds one line after its
existing `CallFunction` emission: `emit_resp_writeback(ctx, r_res, opts,
materialised)` — the exact same helper call every other RESP-producing verb
already uses.

## Testing

The tricky part: `WS-RESP-CD` starts at `0` and this fix also writes `0`, so
a test that just checks "is it `0` after the call?" would pass identically
whether the fix exists or not — it can't distinguish "fixed" from "still
broken." The fix has to be proven by *poisoning* the field to a value that
could only change if the write-back genuinely executed.

- **Unit**: a lowering test proving `WRITEQ TD`'s emitted IR now includes
  the resp-writeback call — mirrors the existing `emit_resp_writeback`
  IR-shape tests in `tests/unit/cics/test_field_ref_wiring.py` (e.g.
  `test_resp_writeback_writes_eibresp_and_resp_field`).
- **Integration**: a new small synthetic COBOL program (same style already
  used this session for `ASKPGM`/`RESUMEPGM`/`DNPGM` in
  `tests/integration/cics/test_region_e2e.py`) that: sets a resp field to
  `-1` (not a real CICS response code — an impossible-to-reach-by-accident
  sentinel), calls `WRITEQ TD RESP(...)`, then renders the field's value on
  a screen so the test can assert it landed on `0`. Before the fix: stays
  `-1` (nothing touches it). After the fix: becomes `0`. This is the only
  design that actually falsifies the bug rather than trivially passing
  either way.

## Out of scope

- `RESP2` support (`emit_resp_writeback` and, by extension, all 10 verbs
  that call it) — explicit user decision to keep this change narrow.
- Any change to `CORPT00C.cbl` or other real CardDemo source — untouched,
  as always.
- Modeling any actual `WRITEQ TD` failure condition (a full queue, a
  disabled destination, etc.) — this fix wires up the plumbing for such a
  condition to be reported correctly in the future; it doesn't invent one.

## Verification

- `uv run --no-sync python -m pytest tests/unit/cics/ -x -q` (fast).
- With `JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home`,
  `PROLEAP_BRIDGE_JAR=vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar`,
  `CARDDEMO_HOME=third-party/carddemo/app`:
  `uv run --no-sync python -m pytest tests/integration/cics/ -x -q` — confirm
  the new synthetic-program test passes and the full suite stays green,
  including `test_real_carddemo_custom_report_submitted` (whose *observable*
  output is expected to be unchanged, per the "Context" section above —
  that's correct, not a gap in this fix).
