# Cross-program byte dataflow across a commarea

**Status:** approved design, not yet implemented
**Scope:** `cobble/cobble/dataflow/fields/` — a fifth artefact table and an opt-in query traversal
**Prior work:** the four normalised tables and the byte-interval query surface
(`red-dragon-forge-09s`, `red-dragon-forge-xiv`)

## The problem

The field dataflow pass is intra-program by construction. A `CALL` or an
`EXEC CICS LINK` contributes a synthetic `%CALL:<program>` source and no callee
summary, so a provenance question stops at the boundary: "where did these bytes
come from" answers `%CALL:PROGB` and goes no further. Nothing in the artefact
lets a consumer continue into `PROGB`.

`srccfg/link.py` already refuses to help, and says why: it aliases a commarea
record-to-record only, because "matching individual fields inside it needs
byte-offset-accurate layouts, which are out of scope here". That reasoning was
right when it was written. It no longer holds — `dataflow/layout.py` computes
byte-accurate extents for every section including LINKAGE, which is exactly the
missing input.

## What a commarea is

A `LINK ... COMMAREA(WS-AREA)` passes **shared storage, not a copy**. The
callee's `DFHCOMMAREA` occupies the same bytes as the caller's `WS-AREA`, so
caller byte `start(WS-AREA) + k` **is** callee byte `k` of `DFHCOMMAREA`.

That makes the relation a **byte-identity alias with an offset rebase**, not a
`FLOWS_TO` edge. Nothing converts, nothing is padded, and there is no
distribution rule to derive — unlike a MOVE, where whether byte `k` reached byte
`k` depends on the usage and clamping of both operands.

This is also what makes a field-level answer sound where a name-matched one
would be wrong. The two sides routinely declare the area differently; the bytes
are the same regardless of what either side calls them.

### Why the corpus shape makes this work end to end

The measured shape is a flat callee commarea unpacked into a working-storage
record:

```cobol
       LINKAGE SECTION.
       01  DFHCOMMAREA                      PIC X(400).
      ...
           MOVE DFHCOMMAREA TO  CALLEE-REC.
      ...
           MOVE CALLEE-REC  TO  DFHCOMMAREA.
```

Both are byte-positional group moves, which the walk already models. So a
traversal that hops at `DFHCOMMAREA@linkage[40:60]` lands on the callee's own
inbound MOVE, follows it to `CALLEE-REC@working_storage[40:60]`, and
`fields.query.contributed()` names the declared child owning those bytes. No new
modelling is needed inside the callee; the hop is the only missing link.

### The shared window

The alias covers `min(len(caller extent), len(callee DFHCOMMAREA))` bytes. Past
that, the two areas are not both addressable and the table must not claim they
are.

That `min` is load-bearing, not a formality. Sampling 100 linking members of one
production corpus, of 203 sites where both sides' declared lengths are
computable, **61 disagree** — 24 with the caller's area larger, 37 with the
callee's. Taking either side's length alone would over-claim on roughly a third
of sites.

`LENGTH` does not narrow it further. Measured over the same corpus's 4078 `LINK`
sites carrying the option: **zero** give a literal, 3535 give
`LENGTH OF <the caller's own commarea field>` — which restates the caller's
declared length and adds nothing — and the remaining 543 give a variable or an
expression, which is unknown statically. A runtime `LENGTH` shorter than the
declaration does not make the alias wrong either: the bytes are still the same
storage, and what the callee actually touched is bounded by its own declaration,
which is already one side of the `min`.

### LINK and XCTL differ in direction

`LINK` returns, so the caller can observe what the callee wrote back: the alias
is symmetric and a query may travel it either way. `XCTL` does not return, so no
caller ever observes a write-back: the alias is inbound-only. One `returns` flag
on the row carries the distinction.

## The artefact: `aliases.jsonl`

A fifth table beside `nodes`/`edges`/`extents`/`defs`, one row per call site and
shared window:

```json
{"caller":"PROGA","node":"2000-SEND-AREA/3","transfer":"LINK","callee":"PROGB",
 "caller_extent":"WS-AREA@working_storage[0:400]",
 "callee_extent":"DFHCOMMAREA@linkage[0:400]","returns":true}
```

- `node` names the statement the hop happened at, so an answer can say where.
- `caller_extent` and `callee_extent` use the existing wire form from
  `fields/extent_text.py`, including the `~` clamp mark, so `byte_range` parses
  them unchanged.
- A row is a relation between two programs, which is why it is its own table
  rather than an attribute on an edge: an edge belongs to one program's flow
  graph, and this belongs to neither.

### Dead ends are rows, not silence

A site that cannot be aliased still gets a row carrying `caller`, `node`,
`transfer` and a `reason`, with `callee` and both extent fields empty:

| `reason` | Meaning | Measured |
| --- | --- | --- |
| `callee-not-in-cache` | literal target, no ASG for it | 1300 sites (31.8%) |
| `dynamic-target` | `PROGRAM` operand is not a literal | 38 sites (0.9%) |
| `no-commarea-operand` | no `COMMAREA` given, so nothing is shared | 1 site |
| `callee-declares-no-commarea` | callee has no `DFHCOMMAREA` in LINKAGE | 0 sites |
| `unsizeable` | either side's extent cannot be computed (`layout` raises `UnsizeableFieldError`) | unmeasured: needs a layout run per callee, which is the implementation |

Aliasable: **2745 of 4084 sites (67.2%)** — 2173 where the callee declares a
flat elementary commarea and 572 where it declares a group or an unsized item.
The corpus holds 4079 `LINK` sites and 5 `XCTL`.

The one large gap is `callee-not-in-cache`: a third of sites name a program the
parse never covered. That is an onboarding gap, not a modelling one, and the
`reason` is what makes it visible rather than looking like an analysis that found
nothing.

A dead end a consumer can name beats an edge that is merely absent. This is the
same lesson as `red-dragon-forge-y02`: an answer that cannot distinguish
"nothing flows here" from "the analysis stopped here" is a plausible wrong
answer, which is worse than an admitted gap.

### Where it is computed

A new `fields/aliases.py`, from inputs that all already exist:

- `srccfg/link.py` for call sites, the commarea operand, and target resolvedness
- `dataflow/layout.py` for both sides' byte extents
- `fields/extent_text.py` for the wire form

**No fixpoint and no walk.** The callee is read from the ASG cache for its
LINKAGE layout only, so the pass costs one layout computation per distinct
callee. It therefore works under `--member` as well as `--all`: a single-member
run emits that member's outbound aliases, and the traversal that consumes them
is the thing that needs the callee's own tables to be present.

The existing `%CALL:<program>` synthetic origin **stays unchanged**. It is the
correct intra-program answer, every current edge depends on it, and the alias
table sits beside it rather than replacing it.

## The traversal

`FieldStore` already spans the corpus — it is keyed `by_program` and its layout
ordering notes that "a range query may span members" — so nothing about it needs
restructuring. It gains the alias rows and one method: given a `ByteRange`,
return the rebased ranges on the other side of every alias whose window overlaps
it.

The rebase is arithmetic on the existing type. A caller range
`[s, e)` inside a caller window starting at `w` maps to callee
`[s - w + v, e - w + v)` where `v` is the callee window's start, with `program`
set to the callee and `region` to `linkage`. `ByteRange._comparable` already
requires both program and region to match, so a rebased range compares only
against the callee's own flows — a hop cannot silently leak into a third member.

`origin`, `writers` and `readers` gain `--across-calls` with `--max-hops N`
defaulting to 3, **off by default**. A limit rather than an unbounded walk
because the answer degrades faster than it grows: the corpus's call graph reaches
most of itself within a few hops, so an unbounded provenance answer names half
the system and tells a reader nothing. Existing answers stay byte-identical until
a caller asks.
Every crossing answer states its hop count and why it stopped: the hop limit, a
named dead-end `reason`, or a genuine external origin such as a file or a
literal.

Cycles are real in this corpus — `PROGA` links `PROGB` which links `PROGA` — so
the traversal carries a `visited` set of `(program, range)` and reports a cycle
as a stop reason distinct from the hop limit.

```
$ cobble-fields-query origin --member PROGA --field WS-X --across-calls --max-hops 3

WS-X@working_storage[40:60]
  hop 0  PROGA  MOVE at 2000-BUILD/4
  hop 1  PROGB  READ INTO at 0800-READ-MASTER/1
         via COMMAREA at PROGA:2000-SEND-AREA/3
  stopped: external origin FILE:CUSTMAST
```

## Out of scope

**Static `CALL ... USING`.** The ASG carries `linkage_fields` but no
`PROCEDURE DIVISION USING` list — `AsgSerializer.java` never emits one — so
binding argument position *i* to a callee parameter would mean assuming the
LINKAGE level-01 declaration order is the USING order. That is wrong wherever
LINKAGE declares items the USING phrase omits, or orders them differently, and a
guess in this table is indistinguishable from a fact. `CALL` therefore emits
nothing new; a bead is filed against the bridge to emit the USING list, and this
design extends to it unchanged once it exists. The cost of waiting is nil here:
the corpus measured has zero `CallStatement`.

**Field-level claims where the callee declares a group commarea.** Where the
callee's `DFHCOMMAREA` has children rather than being a flat elementary, the
alias is computed identically — it is still one window of shared bytes — and the
callee's own declared extents resolve which child a range hits. No special case.

**Interprocedural reaching definitions.** `defs.jsonl` answers which
definitions reach a read *within* a program. A crossing traversal reports the
statement in the callee that wrote the bytes, which is the provenance question
asked in practice; extending the reaching-definitions relation itself across the
boundary would need the summary approach this design rejected.

## Testing

Synthetic COBOL only — no corpus member appears in a test.

- **Two-program fixture**: `PROGA` declares a group commarea, moves a value into
  one child, links `PROGB` which unpacks `DFHCOMMAREA` into its own record and
  writes a different child, then packs it back. Assertions: the alias row's two
  extents, the caller-to-callee hop landing on the right callee bytes, and the
  return direction finding the callee's write.
- **Differing declarations**: the two sides split the same 400 bytes into
  differently-named children of different sizes. The traversal must still land
  on the correct callee child, which is the case a name match gets wrong.
- **Window narrowing**: callee `DFHCOMMAREA` shorter than the caller's area; the
  alias covers the overlap only and a caller range past it yields no hop.
- **`XCTL` is inbound-only**: a caller range does not reach a callee write-back.
- **Each dead-end reason**: a dynamic target, an absent callee, a callee with no
  `DFHCOMMAREA`. Each produces a row whose reason the query reports as its stop.
- **A cycle terminates**: `PROGA` links `PROGB` links `PROGA`, reported as a
  cycle stop rather than a hop-limit stop.
- **Default is unchanged**: without `--across-calls`, every existing query's
  output is byte-identical to today's.

## Acceptance

- `aliases.jsonl` is emitted for every walked member, with a row for every
  `LINK`/`XCTL` site including the ones that cannot be aliased.
- A `--across-calls` provenance query on a two-program synthetic reports the
  callee statement that wrote the bytes, and names the call site it crossed.
- Without the flag, all four existing tables and all seven existing queries
  produce byte-identical output.
- The corpus pass reports how many sites aliased, and the count per dead-end
  reason, so the coverage of the table is a stated number rather than an
  assumption.
