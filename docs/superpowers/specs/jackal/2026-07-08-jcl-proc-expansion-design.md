# JCL PROC expansion — design

## Context

CardDemo's real JCL corpus uses cataloged procedures (`.prc` files, e.g.
`app/proc/REPROC.prc`) via `EXEC PROC=NAME[,SYM=value,...]`. Neither the JCL
execution engine (`jackal/jackal/runner.py`) nor the static knowledge-graph
extractor (`jackal/jackal/jcl_graph.py`) resolves these today — a step
invoking `EXEC PROC=REPROC` is treated exactly like `EXEC PGM=REPROC`: the
runner tries (and fails) to find `REPROC.cbl`; the graph shows a `PROGRAM`
node named `REPROC` as if it were a real executable, with no visibility into
what actually runs. This is tracked as an open gap in
`jackal/docs/jcl-execution-roadmap.md` ("most production JCL is unrunnable
without it").

This design adds PROC resolution and inlining as a single shared pass, used
by both consumers.

## What a PROC actually is

Real z/OS JCL PROC semantics are closer to **macro inlining with parameter
binding** than a function call:

- **No call stack, no scope, no return value.** Once expanded, a PROC's
  steps become literal steps *of the calling job*, at the position the
  `EXEC PROC=` statement occupied — they participate in the same step
  sequence for `COND=` checks and backward dataset references (`*.STEP.DD`)
  as any other step in that job.
- **Two real entry surfaces**, though:
  - **Symbolic parameters**: a PROC can declare defaults on its own `PROC`
    statement (`//NAME PROC SYM=default,...`); the caller's
    `EXEC PROC=NAME,SYM=value,...` binds values that override those
    defaults. `SET` statements inside the PROC body can update a symbol for
    subsequent steps within that same PROC.
  - **DD-qualified overriding**: the caller can replace or add a DD
    belonging to a *specific inner step* of the PROC, by writing
    `//<inner-step-name>.<dd-name> DD ...` in the calling job right after
    the `EXEC PROC=` line. Example: `REPROC.prc` has one step, `PRC001`,
    whose `FILEIN`/`FILEOUT` DDs point at a placeholder dataset
    (`NULLFILE`) — the caller supplies the real files via
    `//PRC001.FILEIN DD ...` / `//PRC001.FILEOUT DD ...`. This is the
    mechanism that makes a PROC actually reusable rather than hardcoded to
    one dataset; if the PROC has exactly one step, an *unqualified* DD
    override targets that step implicitly.
- **Nesting is real but static**: `TRANREPT.prc` itself invokes `REPROC` as
  a nested PROC call. No PROC calls itself transitively in real JCL — it's a
  finite, resolvable-at-parse-time call tree, same shape as a COBOL CALL
  graph.
- **Naming stays two-level, not flattened**: the real z/OS addressing
  convention for a PROC-invoked step is `outerstep.innerstep`
  (`STEP05R.PRC001`) — this is not a display convenience, it's the same
  qualified form already used for the DD overrides themselves.

## Non-goal: system symbols

`&SYSUID` and other system symbols (e.g. on `TRANREPT.jcl`'s own
`NOTIFY=&SYSUID`) are resolved by the submitting environment, not by PROC
parameter binding. This feature only resolves symbols that are PROC
parameters — declared on a `PROC` statement or bound via `EXEC PROC=...`.
System symbols are left untouched.

## Why not text-level preprocessing

An earlier iteration of this design considered doing PROC expansion as pure
text-to-text macro substitution (splice `.prc` raw text into the caller's
raw text, using a bespoke lightweight line scanner to find statement
boundaries, before a single final parse). Rejected: JCL text has real
structural traps a bespoke scanner would have to solve *again*, badly —
comments, quoted-string literals, continuation lines, and `DD *` in-stream
data that can itself contain `//`-looking text without being a statement
boundary (this exact class of bug was just fixed in `DATA_MODE_TERMINATORX`
— a lexer rule that matched `//`/`/*` anywhere in in-stream data instead of
only at the start of a line). The ANTLR grammar already solves all of this
correctly. Re-solving it with regex/line-scanning in Python would be the
first regex shortcut introduced anywhere in this JCL pipeline — an audit
confirmed zero regex usage exists today in `jackal`'s Python source or the
`jcl-bridge` Java source, all the way down to the grammar itself. There's no
reason to break that.

**Decision: parse first (the real, unmodified grammar/bridge — for the
outer job and for each referenced `.prc` file), then expand at the
structured `Step`/`DD` level.** Finding `EXEC PROC=` statements, DD
boundaries, and in-stream data is exactly what the grammar already does
correctly; expansion is a data transformation over its output, not a second
parsing pass.

## No regex for symbol substitution either

The same principle applies to *finding* `&SYMBOL` references. The grammar's
lexer already classifies a `&NAME` reference as a distinct `SYMBOLIC` token
type — separate even from `QS_AMPERSAND` (an escaped literal `&&` inside a
quoted string, which is *not* a symbolic reference). Today,
`JclSerializer.java` discards that distinction: a DSN like
`&CNTLLIB(REPROCT)` gets flattened to the single opaque string
`"&CNTLLIB(REPROCT)"` in the JSON output — confirmed directly:

```
$ echo '...DSN=&CNTLLIB(REPROCT)' | jcl-bridge
{"dsn":"&CNTLLIB(REPROCT)", ...}
```

If `expand_procs` had to re-derive "is there a symbol in this string" from
that flattened text, that's the regex shortcut this design explicitly rules
out — even operating on an already-parsed field, not raw source text, it
would still be re-inferring something the lexer already determined
unambiguously.

**Decision: the serializer must preserve the token-type distinction as
structured output**, not re-derive it downstream. Wherever the grammar's
`keywordOrSymbolic` rule (a `(SYMBOLIC | KEYWORD_VALUE | ...)+` sequence)
produces a value that matters for this feature, the JSON carries an ordered
list of typed parts instead of a flattened string:

```json
"dsn": [{"symbol": "CNTLLIB"}, {"text": "(REPROCT)"}]
```

The Python model gets a matching structured type — a tuple of
`SymbolRef(name) | LiteralText(text)` parts. `expand_procs`'s substitution
step becomes a direct, mechanical walk: `SymbolRef` → look up in the symbol
table (bound value, or raise if unbound); `LiteralText` → pass through;
concatenate. Nothing is inferred; the classification already happened at
lex time.

**Scope of the structured-parts change**: only the fields this feature
actually needs — the DD `dsn` field, the step's `parm` field, and the new
`EXEC PROC=` override values (`proc_parms`, see below). Not every DD keyword
in the grammar (`UNIT=`, `VOL=`, etc.) — those aren't relevant to PROC
symbol substitution and restructuring them is out of scope here.

## Architecture

One new shared module: **`jackal/jackal/jcl/proc_expand.py`**

```python
def expand_procs(
    job: Job, proclib_dirs: Sequence[Path], *, _stack: frozenset[str] = frozenset()
) -> Job
```

Pipeline insertion point — one new call, nothing else touched:

```
raw JCL text
  → jcl-bridge (unchanged, except the proc_parms + structured-value additions below)
  → bridge_parser._job_from_json() → Job
  → expand_procs(job, proclib_dirs) → Job     ← the only new call
  → jcl_graph.py._job_to_graph(expanded_job)   ← unchanged internally
  → runner.py.JobRunner.run_job(expanded_job)  ← unchanged internally
```

Both `jcl_graph.py` and `runner.py` add exactly one line each
(`job = expand_procs(job, proclib_dirs)` right after `parse_jcl`). Neither
needs any other change — they keep operating on ordinary `Job`/`Step`
objects, unaware PROCs exist, which is the entire point of doing this as one
shared pass instead of two separate implementations.

### `expand_procs` algorithm

For each `step` in `job.steps`, in order:

1. **Resolve**: does `{proclib_dir}/{step.pgm}.prc` exist in any of
   `proclib_dirs`? If not, `step` is an ordinary program step — append
   unchanged to the output. No recursion, done.
2. **If it resolves** (it's a PROC call):
   - Cycle guard: if `step.pgm` is already in `_stack` (currently being
     expanded — A calls B calls A), raise.
   - Parse the `.prc` file's raw text via the same `parse_jcl` → its inner
     `steps` (e.g. `REPROC.prc` → one step, `PRC001`) and its declared
     parameter defaults (`PROC SYM=default,...`, if any).
   - Build this call site's symbol table: PROC's own defaults, overlaid by
     `step.proc_parms` (the caller's overrides) — caller wins on conflict.
   - Walk the PROC's inner steps in order, applying `SET` statements found
     among them to the table as encountered (affects only steps *after* the
     `SET`, ordinary imperative shadowing).
   - For each inner step:
     - Substitute `SymbolRef` parts in its `dsn`/`parm` fields using the
       table, producing a resolved copy (raise if a referenced symbol has
       no default and no caller override).
     - Merge in DD overrides from the *outer* step's `dds` that are
       qualified with this inner step's name (`PRC001.FILEIN` → replaces
       `PRC001`'s own `FILEIN` DD wholesale; appends if new; unqualified
       override targets the single step if the PROC has only one).
     - Rename it to the qualified form: `f"{step.name}.{inner_step.name}"`.
     - Recurse: run this renamed/merged step through the same
       resolve-and-expand logic (covers `TRANREPT.prc` → `REPROC`),
       threading `_stack | {step.pgm}`.
   - Append the resulting (possibly further-expanded) real steps to the
     output, at that position.
3. Return `Job(name=job.name, steps=tuple(new_steps))` — flat, fully
   resolved, zero PROC references left.

## Bridge/model changes required

Committing to structural (not textual) parsing means the caller's
`EXEC PROC=NAME,SYM=value` overrides have to actually reach the Python
model — today they don't:

- **`JCLParser.g4`**: `execProcParm` (line 236) already parses this; no
  grammar change needed.
- **`JclSerializer.java`**: currently discards `execProcParm` nodes
  entirely. Add serialization of a `"proc_parms"` object on the step JSON
  (`{"CNTLLIB": [...]}`, itself using the structured symbol/literal-part
  representation above, since an override value could itself be symbolic in
  principle).
- **`jackal/jackal/model.py`**: `Step` gains
  `proc_parms: dict[str, tuple[ValuePart, ...]] = field(default_factory=dict)`.
- **`bridge_parser.py`**: `_step_from_json` reads `proc_parms` through.
- **DSN/PARM fields**: change from `str` to `tuple[ValuePart, ...]` (or a
  thin wrapper preserving today's `str`-like ergonomics for the common
  all-literal case — an implementation detail to settle when writing the
  plan, not a design fork).

## Two open verification items (not design forks — check during implementation)

1. Does `parse_jcl` already succeed on a bare `//NAME PROC ...` document (no
   `JOB` card), or does the grammar's top-level rule require wrapping it? If
   the latter, a minimal grammar/parser accommodation is needed — scoped
   narrowly to accepting a PROC document as an alternative top-level
   construct, not a rewrite.
2. Does the grammar/model already expose `PROC`-statement-level symbol
   defaults and `SET` statements in some currently-unused form, or do those
   need their own serialization additions alongside `proc_parms`?

## Graph representation

Following the precedent set by `attrs["text"]` (SYSIN content) and
`attrs["select_name"]` (COBOL_FILE): the `JOB → STEP` edge for an expanded
step carries `attrs={"proc": "REPROC"}` so it's visibly distinguishable in
the graph/browser from a step written directly in the job. Where a
`dsn`/`parm` value was symbol-substituted, the edge/node also carries the
pre-substitution form (`attrs={"symbol": "&CNTLLIB", "resolved": "AWS.M2.CARDDEMO.CNTL"}`)
so the graph shows *where* a value came from, not just its resolved form.

## Error handling

Fail loud, consistent with this codebase's existing style
(`PROLEAP_BRIDGE_JAR` unset, `JclParseError`): PROC not found in any
`proclib_dir`, a referenced symbol with no default and no caller override, a
qualified DD override naming a step that doesn't exist in the PROC, and a
detected circular reference all raise clear, specific exceptions.
`build_carddemo_graph.py`'s existing per-file try/except already catches and
logs failures without aborting the whole corpus run — `expand_procs` doesn't
need its own swallow-and-continue logic.

## Testing

TDD throughout, matching this session's established pattern (synthetic
minimal JCL/PROC fixtures + the real `bridge_jar`/`jcl_bridge_jar` fixtures,
not mocks):

- Bridge: round-trip test that `EXEC PROC=NAME,SYM=val` now captures
  `proc_parms`, and that a DSN containing `&SYMBOL` round-trips as
  structured parts, not a flattened string.
- `proc_expand` unit tests: single-level substitution, PROC-default-vs-
  caller-override precedence, `SET` statement shadowing, DD-qualification
  replace-vs-append (including the single-step implicit-target case),
  nested-PROC scoping (distinct symbol tables per call site), circular-
  reference detection, missing-symbol error.
- Integration: the real `TRANREPT.jcl` + `REPROC.prc` + `TRANREPT.prc` from
  the CardDemo corpus, asserting the fully expanded step list matches
  expected (`TRANREPT.STEP05R.PRC001` with merged DDs, `STEP10R` unaffected
  since it's a plain `EXEC PGM=CBTRN03C`).
- `jcl_graph.py`: extend `test_jcl_graph.py` for qualified-id nodes and
  `attrs={"proc": ...}` on the edge.
- `runner.py`: an end-to-end run of a synthetic PROC-wrapping-IDCAMS job
  through `JobRunner`, asserting real side effects (mirroring the existing
  `test_runner_idcams_creates_ksds` style).
