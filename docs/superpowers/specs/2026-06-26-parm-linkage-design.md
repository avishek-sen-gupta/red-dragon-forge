# jackal — PARM= → COBOL LINKAGE — Design

**Status:** Designed (2026-06-26). Tracks `jackal-1o2.13` (label `jcl-language`).

## What this builds (plain terms)
Make jackal honor `EXEC PGM=prog,PARM='...'` — pass the PARM string into the executed
COBOL program the way the OS does. The program receives it through its LINKAGE SECTION as a
**halfword-length-prefixed** structure. CardDemo's `CBACT04C` is the exact, faithful case:

```cobol
LINKAGE SECTION.
01  EXTERNAL-PARMS.
    05  PARM-LENGTH  PIC S9(04) COMP.   *> 2-byte big-endian halfword = length
    05  PARM-DATE    PIC X(10).         *> the PARM text
PROCEDURE DIVISION USING EXTERNAL-PARMS.
```
Invoked as `//STEP15 EXEC PGM=CBACT04C,PARM='2022071800'` — the program reads `PARM-LENGTH`
then `PARM-DATE` and uses the date. Today jackal drops PARM entirely, so the program's
LINKAGE is unbound/garbage.

## Driver (why now)
`PARM=` is the most-used UNHANDLED JCL-language feature in CardDemo (4 jobs), and `CBACT04C`
genuinely consumes it (`STRING PARM-DATE …`). It is a bounded, demand-driven JCL-language
fidelity feature.

## Key finding — the receipt seam already exists (no red-dragon change)
A top-level COBOL program with `PROCEDURE DIVISION USING` binds its LINKAGE to a VM region
named `__params_region` (via `lower_data_division`). The `LoadVar("__params_region")`
instruction searches `vm.call_stack` frames in reverse order. We pre-seed a base frame in
an `initial_vm` with `__params_region → Address("rgn_parm")` and the region bytes, then
execute via `run_linked(linked, EntryPoint.top_level(), io_provider=..., initial_vm=...)`.

This is entirely jackal-side — red-dragon is unchanged; we use its existing public
`VMState`/`StackFrame`/`region_set`/`run_linked` APIs.

## Components

### 1. Model (`jackal/model.py`)
`Step` gains `parm: str = ""` (defaulted field last, after the existing `conds`). Empty string
= no PARM (today's behavior).

### 2. Java bridge — emit PARM (`jcl-bridge/.../JclSerializer.java`)
The grammar rule is `execParmPARM : EXEC_PARM EQUAL singleOrMultipleValue ;` with parser context
`JCLParser.ExecParmPARMContext`. Use `findChild(execStmt, JCLParser.ExecParmPARMContext.class)`
then `findChild(parmCtx, JCLParser.KeywordOrSymbolicContext.class).getText()`. Strip surrounding
apostrophes (JCL quoted string convention). Emit `"parm": "<text>"` on the step JSON.
Absent PARM ⇒ `""`.

### 3. Deserializer (`jackal/jcl/bridge_parser.py`)
Populate `Step.parm` from `s.get("parm", "")`. No `None`.

### 4. PARM region builder (`jackal/parm.py`, pure)
```python
def build_parm_region(parm: str) -> bytes
```
Returns `struct.pack(">H", len(parm)) + EbcdicTable.ascii_to_ebcdic(parm.encode("ascii"))`.
EBCDIC encoding is required because red-dragon stores PIC X fields as EBCDIC bytes internally; latin-1 would cause character comparisons to silently fail.
Fail loud if `len(parm) > 0x7FFF`.

### 5. Injection (`jackal/cobol_step.py`)
When `step.parm` is non-empty:
- `compile_cobol(source.encode("utf-8"), copybook_dirs=copybook_dirs)` → `linked`
- Build `initial_vm = VMState()` with `region_set(Address("rgn_parm"), bytearray(build_parm_region(step.parm)))` and a base `StackFrame` with `local_vars = {VarName("__params_region"): TypedValue(value=Address("rgn_parm"), type=UNKNOWN)}`
- `run_linked(linked, EntryPoint.top_level(), io_provider=provider, initial_vm=initial_vm, max_steps=500_000)`

When `step.parm` is empty: existing `run(...)` path unchanged.

## Data flow
```
JCL: EXEC PGM=CBACT04C,PARM='2022071800'
  --(mapa bridge)--> step JSON {"pgm":"CBACT04C","parm":"2022071800", ...}
  --> Step(parm="2022071800")
cobol_step: build_parm_region("2022071800") = b'\x00\x0a' + b'2022071800'   (len=10, BE)
  --> initial VMState: region rgn_parm = that; frame __params_region -> Address("rgn_parm")
  --> run_linked(linked, EntryPoint.top_level(), io_provider=provider, initial_vm=initial_vm)
  --> CBACT04C LINKAGE: PARM-LENGTH=10, PARM-DATE='2022071800'
```

## Error handling
- `len(parm) > 0x7FFF` ⇒ `ValueError` (fail loud, never truncate).
- No `None` defaults; no defensive guards.

## Testing
- **Unit — `build_parm_region`:** `''` ⇒ `b'\x00\x00'`; `'2022071800'` ⇒ `b'\x00\x0a2022071800'`; a > 0x7FFF parm ⇒ raises.
- **Unit — deserializer:** step JSON with `"parm"` ⇒ `Step.parm`; absent ⇒ `""`.
- **Bridge — real JAR:** `EXEC PGM=X,PARM='ABC'` parses into `Step(parm="ABC")`; no PARM ⇒ `parm == ""`.
- **Integration — real receipt via `run_linked`:** run a minimal COBOL program with LINKAGE that reads PARM-DATA and sets RETURN-CODE=42 when PARM='HELLO'. Assert receipt. Also: no-PARM step runs unchanged (behavior-preservation guard).

## Binding constraints
- TDD: write failing test first.
- No `None` defaults; no defensive guards; fail loud; frozen dataclasses.
- `make jar-force` or `cd jcl-bridge && mvn -DskipTests package -q` after the Java edit.
- `uv run --no-sync` for tests.

## Bookkeeping
- `jackal-1o2.13` under epic `jackal-1o2`. Jackal-side only (no red-dragon change).
- Out of scope: PARM symbolic substitution; PARM on `EXEC PROC=`; multi-line PARM continuation.
