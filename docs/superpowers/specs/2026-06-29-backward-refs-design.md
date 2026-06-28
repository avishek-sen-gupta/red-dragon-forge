# jackal — Backward References (DSN=*.STEP.DD) — Design

**Status:** Designed (2026-06-29). Tracks `jackal-1o2.10` (label `jcl-language`).

## What this builds

Honor `DSN=*.STEP.DD` backward references in JCL — a DD that inherits the
dataset allocated to a named DD in a prior step. Common in Tier-1 JCL that
chains steps without repeating dataset names.

Example:

```jcl
//STEP1  EXEC PGM=IEFBR14
//WRK    DD DSN=MY.WORK.FILE,DISP=(NEW,PASS)

//STEP2  EXEC PGM=CBACT04C
//INPUT  DD DSN=*.STEP1.WRK,DISP=(OLD,DELETE)
```

Step 2's `INPUT` DD resolves to the same dataset as `STEP1`'s `WRK` DD at
runtime. If `STEP1` was bypassed (COND= flushed it), `STEP2` is also bypassed
— IBM-faithful flush propagation.

## Out of scope

- `DSN=*.STEP.PROCSTEP.DD` (three-segment form for PROC-nested DDs) —
  deferred to `jackal-lz8`, blocked on PROC support (`jackal-1o2.2`).
- Backward refs to `&&NAME` temp datasets via `*.STEP.DD` are supported
  (the runner records `TempRef` backing names as `DirectDSN` in the registry).

## DSN type — BackwardRef

New frozen dataclass added to `jackal/dsn.py`:

```python
@dataclass(frozen=True)
class BackwardRef:
    step: str    # step name, e.g. "STEP1"
    ddname: str  # DD name, e.g. "WRK"

type DSN = DirectDSN | TempRef | BackwardRef
```

`dsn_key()` gains a `case BackwardRef()` arm that raises `TypeError` — same
policy as `TempRef`: unresolved backward refs must not reach consumers that
expect a string key.

## Components

### 1. `jackal/dsn.py`

Add `BackwardRef(step: str, ddname: str)`. Update `DSN` union alias. Add
`case BackwardRef()` to `dsn_key()` raising `TypeError`.

### 2. Java bridge — `jcl-bridge/.../JclSerializer.java`

The grammar's `datasetName` rule uses `keywordOrSymbolic`, which does not
match a leading `*`. Backward reference DSNs therefore need explicit handling:
detect a `DdParmDSNAMEContext` whose raw text starts with `*.` and emit a
structured JSON field instead of the plain `dsn` string:

```json
{ "backref": { "step": "STEP1", "ddname": "WRK" } }
```

Parse: split the raw text (e.g. `*.STEP1.WRK`) on `.`, discard the leading
`*`, take index 1 as `step` and index 2 as `ddname`.

When `backref` is present, omit or leave `dsn` empty — the Python parser
dispatches on `"backref"` first.

### 3. Python bridge parser — `jackal/jcl/bridge_parser.py`

`_dd_from_json` already dispatches on `&&` → `TempRef`. Add a `backref`
branch before the DSN string check:

```python
if "backref" in d:
    br = d["backref"]
    dsn: DSN = BackwardRef(step=br["step"], ddname=br["ddname"])
elif raw_dsn.startswith("&&"):
    dsn = TempRef(raw_dsn)
else:
    dsn = DirectDSN(raw_dsn)
```

### 4. `jackal/runner.py`

The runner gains a per-job `_resolved_dds: dict[str, dict[str, DirectDSN]]`
registry, mapping `step_name → ddname → DirectDSN`. It is populated after
each step's DDs are pre-resolved and before the step is dispatched.

**Pre-dispatch resolution (`_resolve_step`):**

```python
def _resolve_step(
    self, step: Step, resolved_dds: dict[str, dict[str, DirectDSN]]
) -> Step | None:
    """Substitute BackwardRefs; return None if step should be bypassed."""
    new_dds = []
    for dd in step.dds:
        match dd.dsn:
            case BackwardRef(step=s, ddname=dn):
                if s not in resolved_dds:
                    return None  # referenced step bypassed → bypass this step
                new_dds.append(
                    DD(dd.ddname, resolved_dds[s][dn], dd.disp,
                       dd.in_stream, dd.sysout)
                )
            case _:
                new_dds.append(dd)
    return Step(step.name, step.pgm, tuple(new_dds), step.conds, step.parm)
```

**Registry population — `_record_dds(step_name, dds, resolved_dds)` (after resolution, before dispatch):**

```python
for dd in resolved_step.dds:
    match dd.dsn:
        case DirectDSN() as d:
            resolved_dds.setdefault(step.name, {})[dd.ddname] = d
        case TempRef(alias=a):
            resolved_dds.setdefault(step.name, {})[dd.ddname] = DirectDSN(a[2:])
```

`TempRef` is recorded as `DirectDSN(alias[2:])` — the backing file name —
so a backward ref to a temp-dataset DD resolves to the same file.

**`run_job()` integration:**

```python
resolved_dds: dict[str, dict[str, DirectDSN]] = {}
try:
    for step in job.steps:
        conds = job.cond + step.conds
        if should_bypass(conds, tuple(executed)):
            results.append(StepResult(..., disposition=StepDisposition.BYPASSED))
            continue
        resolved_step = self._resolve_step(step, resolved_dds)
        if resolved_step is None:
            results.append(StepResult(..., disposition=StepDisposition.BYPASSED))
            continue
        self._record_dds(step.name, resolved_step.dds, resolved_dds)
        result = self._run_step(resolved_step, catalog)
        executed.append(result)
        results.append(result)
finally:
    catalog.cleanup_temps()
```

## Error handling

| Situation | Behaviour |
|---|---|
| Referenced step was bypassed | Current step bypassed (IBM flush propagation) |
| Referenced step name is a typo / never appears in job | Same as bypassed — step not in registry → bypass |
| `BackwardRef` reaches `dsn_key()` unresolved | `TypeError` (defensive; shouldn't occur in normal flow) |
| `BackwardRef` reaches `catalog.allocate()` unresolved | `TypeError` from `case _:` guard |

## Data flow

```
JCL:  DSN=*.STEP1.WRK,DISP=(OLD,DELETE)
  --(bridge)--> {"backref": {"step": "STEP1", "ddname": "WRK"}, "disp_words": ["OLD","DELETE"]}
  --> DD(dsn=BackwardRef("STEP1", "WRK"), disp=Disp(OLD, DELETE, DELETE))

run_job():
  STEP1 runs → resolved_dds["STEP1"]["WRK"] = DirectDSN("MY.WORK.FILE")

  STEP2 pre-dispatch:
    _resolve_step: BackwardRef("STEP1","WRK") → DirectDSN("MY.WORK.FILE")
    resolved_step.dds = [DD("INPUT", DirectDSN("MY.WORK.FILE"), Disp(OLD,DELETE,DELETE))]
  STEP2 dispatched with resolved DDs → catalog.allocate() sees DirectDSN only
```

## Testing

**Unit — `jackal/dsn.py`:**
- `BackwardRef("STEP1", "WRK")` construction + equality
- `dsn_key(BackwardRef(...))` raises `TypeError`

**Unit — bridge parser (`tests/unit/test_jcl_bridge_deserialize.py` or similar):**
- JSON with `"backref": {"step": "STEP1", "ddname": "WRK"}` → `BackwardRef("STEP1", "WRK")`
- `&&` path and plain DSN path unchanged

**Unit — runner resolution:**
- `_resolve_step` substitutes `BackwardRef` with `DirectDSN` from registry
- `_resolve_step` returns `None` when referenced step absent from registry
- `TempRef` DD recorded as `DirectDSN(alias[2:])` in registry

**Integration — happy path:**
- Two-step job; step 1 allocates `MY.WORK.FILE` to DD `WRK`; step 2 references
  `*.STEP1.WRK` — both steps run, `catalog` sees `DirectDSN("MY.WORK.FILE")` in step 2

**Integration — bypass propagation:**
- Step 1 bypassed via COND=; step 2 references `*.STEP1.WRK`
- Step 2 result: `ran=False`, `disposition=BYPASSED`

## Binding constraints

- TDD: failing tests first.
- `BackwardRef` never reaches `catalog.allocate()` — runner resolves all backward
  refs before dispatch.
- IBM bypass propagation: referenced step not executed → referencing step bypassed,
  not errored.
- `DSN=*.STEP.PROCSTEP.DD` out of scope — raise `ValueError` in bridge parser if
  three-segment form is encountered, pointing at `jackal-lz8`.
- `uv run --no-sync` for all test runs.
- `make jar-force` after the Java bridge change.

## Bookkeeping

- `jackal-1o2.10` under epic `jackal-1o2`.
- Three-segment backward refs (`*.STEP.PROCSTEP.DD`) deferred to `jackal-lz8`,
  blocked on `jackal-1o2.2` (PROC support).
