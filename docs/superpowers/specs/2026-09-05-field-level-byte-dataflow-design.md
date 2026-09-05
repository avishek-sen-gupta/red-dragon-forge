# Field-level byte dataflow for cobble

Status: design, approved in brainstorming 2026-09-05. Supersedes the standalone
byte-interval model sketched in `red-dragon-forge-pr2` / `ujr` / `pd9`, and closes
`red-dragon-forge-j7w` as subsumed.

## Why

Cobble's source CFG chains statements by matching operand **name strings**. Line 4275
of `PROG-A` writes `MST-COUNT`; line 5191 reads `REC-MASTER`. Those are the
same memory — the first is a group member of the second — so the chain snaps at exactly
the point a reader needs it to hold. `INITIALIZE REC-MASTER` kills nothing.
`derivation FILE:DATASET-M` yields a single line.

A name is not what a COBOL statement operates on. A MOVE copies a byte range. Stating
the analysis over byte extents makes group containment, REDEFINES aliasing, OCCURS
striding and reference modification fall out of range overlap rather than needing a rule
each.

## What already exists

Two substrates are built and must not be rebuilt.

**`cobble/cobble/dataflow/layout.py`** (bead `rzj`, closed, validated) computes absolute
byte extents for every field in a program's records. Public surface: `Cell`, `Record`,
`record_cells`, `section_records`, `program_records`, `UnsizeableFieldError`. It covers
the LINKAGE SECTION (`layout.py:60`), deliberately distrusts `CobolField.offset` on
level-01 and `CobolTypeDescriptor.char_positions`, and resolves a REDEFINES to the
nearest preceding item of that name. OCCURS is fully expanded into per-occurrence cells.

**`vendor/red-dragon/interpreter/cobol/memory_dataflow.py`** already implements
field-level dataflow over byte extents upstream, with `field_extent.py`,
`memory_effects.py` and `abstract_location.py`. Its governing asymmetry is the one this
design adopts verbatim: `may_alias` over-approximates, so an edge is kept when overlap is
uncertain; `must_cover` under-approximates, so only an EXACT extent may kill a
definition and a CLAMPED one — a computed subscript — never does.

## Decision: extract the algebra, not the driver

The upstream work sits under `interpreter/`, which `.importlinter`'s
`cobble-no-interpreter` contract forbids cobble from importing. The dependency footprint
splits cleanly.

Extracts — a closed set with no interpreter dependency beyond each other:

| module | lines | depends on |
| --- | --- | --- |
| `abstract_location.py` | 59 | stdlib |
| `storage_identifier.py` | 23 | `abstract_location` |
| `region_id.py` | 22 | stdlib |
| `field_extent.py` | 86 | `region_id` |

Does not extract: `memory_effects.py` (needs `InstructionId`, `SourceLocation`),
`memory_dataflow.py` and `dataflow.py` (need `CFG`, `BasicBlock`, `Opcode`, `Register`).
Those are bound to the interpreter's IR.

So the byte-range alias algebra crosses to the static surface and the fixpoint driver
does not. Cobble runs its own fixpoint over its own CFG, keyed on `FieldExtent`.

These four modules move to a new vendor package, `cobol_memory`, a sibling of
`cobol_asg`. Extents are storage algebra rather than ASG nodes, so folding them into
`cobol_asg` would blur what that package means.

**This is an upstream change.** `vendor/red-dragon` is never modified in this repo; the
extraction lands in red-dragon's own repository and arrives here as a submodule bump.
`cobol_memory` must then be added to the allowed-surface list in the `.importlinter`
comment block, which the file itself notes is a review obligation rather than a
machine-checked one.

## Architecture

New package `cobble/cobble/dataflow/fields/`, depending one-way on `srccfg` (reads
`Cfg`), `dataflow.layout` (reads `Record`, `Cell`) and `cobol_memory` (reads
`FieldExtent`). Nothing in `srccfg` imports back.

- `extent.py` — a statement operand to a `FieldExtent`, via `layout`'s cells. Constant
  subscripts and constant reference modification produce EXACT extents; computed ones
  produce CLAMPED extents widened to the enclosing table or field.
- `transfer.py` — one statement plus an in-state to an out-state. (`pr2`)
- `fixpoint.py` — intra-program worklist keyed on paragraph, storing each paragraph's
  entry state and re-analysing only when that entry state changes. (`ujr`)
- `summary.py` — a program's caller-independent relation over its commarea extents.
- `interprocedural.py` — topological pass over the call DAG, applying summaries.
- `naming.py` — extent back to field names.
- `emit.py` — `FIELD` nodes and `FLOWS_TO` edges. (`pd9`)

Data flow: the ASG cache feeds `layout.program_records` and `srccfg`'s CFG builder
independently; `fixpoint` consumes both per program; `summary` reduces each program to
its commarea relation; `interprocedural` stitches them in topological order; `emit`
writes into the existing `out-<corpus>` graph.

## State and transfer

State maps a `FieldExtent` to a frozenset of `Source`. A `Source` is either another
extent or a synthetic origin (`FILE:DATASET-M`, `LITERAL`, `%CICS-STATE`), each paired
with the id of the CFG node that wrote it.

GEN/KILL dispatches through the extracted algebra. A write GENs its target extent and
KILLs a prior definition only when `must_cover` holds — so a CLAMPED write is a weak
update, adding provenance without removing any. A read matches by `may_alias`. Join at
a control-flow merge is union.

Termination: every extent a transfer can construct is determined statically by the
statement set — a group MOVE yields one per covered target field, and the offset
arithmetic is fixed per statement — so the set of extents is finite and known before
iteration, and the lattice has finite height. The `ujr` spike
measured the loop fixpoint as cheap (11,826 loops settled in one iteration, 1,599 in
two, the 30-iteration cap never reached); the cost was recursive PERFORM inlining
re-analysing a paragraph once per call path. Keying the worklist on paragraph entry
state bounds work at O(paragraphs × state changes) and removes the need for a depth cap.

Transfer rules, by statement class:

- **Group and alphanumeric MOVE** — target takes the source at matching relative offset,
  left-aligned, `min` length; a longer target's tail takes `LITERAL SPACES`.
- **Reference modification** — the sub-extent, as source and as target.
- **Numeric MOVE with differing scale, or any COMP operand** — whole target depends on
  whole source. No byte correspondence exists, so this is exact rather than a widening.
- **Computed subscript** — CLAMPED extent over the table's full declared span, weak
  update.
- **`INITIALIZE`** — every extent in the group takes `LITERAL`.
- **`ADD` / `COMPUTE` / `STRING`** — whole target takes the union of all operand extents.
- **`READ INTO` / `RECEIVE MAP` / SQL `INTO`** — target takes the synthetic record's
  matching offsets.

## Cross-program

The call graph is a DAG, so a topological pass suffices and no cross-program fixpoint is
needed.

Each program reduces to a **caller-independent summary**: a relation over its commarea
extents, mapping exit extents to entry extents and local sources. Caller-independence is
load-bearing — specialising a callee per caller would reproduce the `ujr` blowup one
level up, and summary size is bounded by commarea length.

At a `LINK` or `CALL` site the caller's `COMMAREA` record binds to the callee's
`DFHCOMMAREA` at offset 0, length `min` of the two. A size mismatch is recorded, not
silently truncated: it is a genuine defect signal.

The dominant idiom needs no special machinery. `PROG-B` declares
`01 DFHCOMMAREA PIC X(2000)` and does `MOVE DFHCOMMAREA TO REC-MASTER-ALT` on entry,
`MOVE REC-MASTER-ALT TO DFHCOMMAREA` on exit — so the callee's own MOVE transfer carries
the bytes into structure. Note that the caller passes `REC-MASTER` and the callee
calls the same 2000 bytes `REC-MASTER-ALT`: different copybook names over one piece of
storage, which is precisely the case names cannot express.

A flat `DFHCOMMAREA` is a single cell, and that costs nothing: extents are constructed
per reference rather than looked up from a fixed partition of the record, so
`MOVE DFHCOMMAREA TO REC-MASTER-ALT` yields one edge per target field, each sourced from
the matching sub-extent of `DFHCOMMAREA`. No boundary alignment step is needed.

`XCTL` transfers control without returning, so it gets no return edge and contributes no
exit summary to its caller.

Seams that do not resolve — a dynamic call target, or a literal target absent from the
ASG cache — fall back to a synthetic record. This is not a rare path: roughly 30% of
seams take it, so synthetic naming is a first-class part of the design rather than an
error case.

## Naming

Reports name the **smallest covering field** for an extent, so an edge reads
`MST-COUNT` rather than `REC-MASTER`. An opt-in flag expands to every field the
extent touches, including REDEFINES views, for the cases where alias information is the
answer.

Cells are used only here. The corpus expands to roughly 5.6M cells (mean 1,491 per
program, worst 121,001 in `PROG-WIDEST`), and keeping that expansion out of the lattice —
which is keyed on extents — is why the analysis does not pay for OCCURS.

## Edges

A `FLOWS_TO` edge carries source extent, target extent, and the id of the CFG node that
wrote it. It does **not** carry the guard condition. A reader wanting the condition asks
`srccfg` for that node's guards on demand.

This keeps conditions out of the lattice. Carrying them would multiply state by the
number of distinct guard paths and would depend on the path-enumeration walk that bead
`red-dragon-forge-3ao` found broken.

## Failure handling

- `layout.UnsizeableFieldError` — the program is skipped and recorded, never silently
  dropped.
- Program absent from the ASG cache, or a dynamic call target — synthetic record.
- Commarea size mismatch at a seam — bind `min`, surface the mismatch.
- A cycle in the call graph — none exists today; assert and report rather than hang.

## Relationship to the open srccfg beads

`red-dragon-forge-3ao` (the reaching-walk bug) does **not** block this work. It lives in
path enumeration; the gen-kill fixpoints (`reaching_definitions`, `def_use`) are
unaffected, and this design does not use guard paths. 3ao remains a real bug for guard
*text*, and its diagnosis settled the fix: expand a walk refused by the cap only when its
`(node, perform stack)` context is new. Bounding recording while expanding everything
exhausts memory.

`red-dragon-forge-j7w` (flattened group/member names) closes as subsumed. Containment,
REDEFINES, OCCURS and reference modification all fall out of extent overlap.

## Prerequisite: re-parse — discharged

This was recorded as bead `red-dragon-forge-8y0`, closed 2026-09-03 as retracted —
*"My evidence was a stale ASG cache, not the current bridge."* Upstream commit
`1a99c445` ("emit structured subscripts (bare name + all subscripts), retire
flattening") makes the bridge emit them, and `57cf80e9` retired the Python-side
`_SUBSCRIPT_RE` because subscripts became fully structural. 8y0's close note left a
standing instruction — *"Rebuild the cache with the current jar and re-run before quoting
any of them"* — and the figures below discharge it.

The current cache is `cobble/out-<corpus>-parsed-2/`, written by the current JAR: 3,779
files, no failures. The parse is skip-if-cached and its own config comment records the
cost — *"557 MB and four hours of JVM"* — so it wrote to a fresh `asg_dir` rather than
clobber `out-<corpus>-parsed`, which the existing srccfg work still depends on.
`cobble/cobble/diagnosis/asg_operands.py` (`diagnose-asg-operands`) is the gate
`extent.py` runs against a cache before trusting it, and over MOVE operands it reports:

| cache | bare | subscripted | ref-modified | total |
| --- | --- | --- | --- | --- |
| previous | 1,441,310 | 0 | 11,252 | 1,452,562 |
| current | 1,339,269 | 102,922 | 11,252 | 1,452,562 |

Three properties of that pair show the re-parse was faithful rather than a different
parse. `total` is identical, so what changed is what an operand carries, not which
statements exist. `ref-modified` is identical, and that is the control: reference
modification always reached the cache, so the JAR change was scoped to subscripts. And
`bare` falls by 102,041 while `subscripted` rises by 102,922 — a gap of exactly 881, the
operands carrying both a subscript and reference modification, which were never counted
`bare` because that bucket means neither. Nothing is left unexplained.

The two caches' DATA and LINKAGE field trees hash identically, so every layout-derived
figure — the cell counts under **Naming** — is unaffected by the re-parse.

The follow-on plan that builds `cobble/cobble/dataflow/fields/` can therefore write
`extent.py`'s fixtures against an observed operand shape rather than an invented one: a
subscript is `{"kind": "lit" | "ref" | "binop", …}` under an operand's `subscripts`, and
reference modification is `ref_mod_start` / `ref_mod_length` carrying the same `kind`.
It should also switch its own parse config to the current cache, which no consumer has
done yet.

## Corpus measurements

Evidence base: `cobble/out-<corpus>-parsed-2`, 3,779 files carrying 3,770 distinct
program ids.

Statement counts come from a walk that descends to any depth without enumerating nesting
keys. The counts previously carried here came from one that descended incompletely, so
they were **undercounts** rather than measurements of an older cache — the correction is
about the walk, not the re-parse. Running the current walk against the previous cache
reproduces every figure below except the operand shapes, which is what confines the
re-parse's effect to operand contents.

Linkage shape: 1,923 programs declare a lone flat `DFHCOMMAREA`, 1,574 declare no
linkage, 282 declare a structured one — unchanged, and the "needs no special machinery"
argument in **Cross-program** rests on it. Seven of the 282 carry a childless
`DFHCOMMAREA` beside another level-01 item. Flat `DFHCOMMAREA` is read by MOVE and
`INITIALIZE` alone: 3,644 MOVEs and 57 `INITIALIZE`s name it, and no condition in the
corpus tests it — the 974 IFs that look like consumers merely enclose those MOVEs.

Call graph: 3,759 distinct literal call edges, 2,610 with the target in the cache; 1,149
edges name a target absent from it and 38 sites compute their target, so 31% of seams
fall back to a synthetic record. No program is self-recursive, and a topological peel
over the resolved edges leaves nothing — the graph is acyclic, as **Cross-program**
assumes.

Statement mix: MOVE 668,462, IF 193,684, PERFORM 171,787, EXEC CICS 49,893, GOTO 32,596,
ADD 29,201, STRING 27,157, EVALUATE 25,921, COMPUTE 22,060, WRITE 21,775, INITIALIZE
11,047, batch READ 5,839. Within EXEC CICS, the record- and seam-bearing verbs: READ
9,562, LINK 4,079, START 3,138, READNEXT 2,437, STARTBR 2,421, REWRITE 1,809, WRITE 1,374,
RECEIVE MAP 1,048, XCTL 5 — so a seam is a LINK almost without exception.

Operand precision, which is `extent.py`'s input: of the 102,922 subscripted MOVE
operands, 24,929 subscript only by literal and yield EXACT extents while 77,993 have a
computed subscript and yield CLAMPED ones; of the 11,252 reference-modified operands,
10,889 are constant. Three quarters of subscripted operands are therefore CLAMPED, which
makes the never-kill asymmetry the common path for a subscripted write, not a corner. These
supersede the source-text counts previously quoted here (68,350 subscripted MOVEs, 18,315
of them constant, 32,927 reference modifications), which counted source occurrences and
not cache operands; per statement the cache carries 79,356 MOVEs with a subscripted
operand and 10,001 with a reference-modified one.

Storage forms, counted recursively over WORKING-STORAGE and LINKAGE: DISPLAY 2,404,740,
COMP 115,036, COMP-3 3,096, POINTER 10, COMP-5 2. So packed-decimal realignment is a
corner case and binary COMP has no byte-wise digit correspondence in any event.

## Testing

- `extent.py` — table-driven per operand form: bare name, group, constant subscript,
  computed subscript, constant reference modification, computed reference modification,
  multi-dimensional. Assert EXACT versus CLAMPED precision on each.
- `transfer.py` — one case per rule above, including the asymmetry that a CLAMPED write
  never kills.
- `fixpoint.py` — hand-built CFGs covering loop convergence and the PERFORM re-entry case
  the `ujr` spike measured.
- `summary.py` / `interprocedural.py` — the `PROG-A` to `PROG-B` seam, asserting that
  provenance crosses into `REC-MASTER-ALT` despite the name change.
- Acceptance — a **coverage** assertion, not merely a termination one. The 3ao
  post-mortem found the existing acceptance suite passing while the walk reached 18% of
  nodes, because nothing measured reach. Assert the fraction of writes producing at least
  one edge, and pin the end-to-end oracle: `MST-COUNT` derives from `SCR-COUNT` at
  `PARA-UPDATE/57` and reaches VSAM dataset `DATASET-M` through
  `PARA-REWRITE`.
- Performance guard — `PROG-WORST` took 710.58s under recursive inlining. Assert it
  completes under a bound with the paragraph-keyed worklist.

## Out of scope

Guard conditions on edges. Cross-program flow through MQ or shared files. Extracting
`memory_effects.py` or the upstream fixpoint. Lifting the precision ceiling on computed
subscripts, which no byte model removes.
