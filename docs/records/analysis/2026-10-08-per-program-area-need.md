# Per-Program Area Need

**Date:** 2026-10-08
**Component:** `cobble-dataflow-fixpoint`, `cobble-dataflow-area-need`
**Problem:** `--narrow-areas` provides zero narrowing on a large CICS corpus.

---

## 1. Background

`cobble-dataflow-area-need` is a corpus-wide pre-pass that computes which bytes
of handed-over areas (DFHCOMMAREA, USING parameters) each program actually reads
at entry and which bytes callers read back after a returning CALL or LINK. The
fixpoint's `--narrow-areas` flag feeds this result into liveness analysis: bytes
no callee reads and no caller reads back are pruned from the walk's tracked
state, which makes the fixpoint cheaper and the jump areas in `jumps.jsonl`
thinner.

The computation is a fixpoint itself: callees' entry reads propagate backward
through callers, making more caller bytes live, which in turn makes more bytes
live at those callers' own entries. Rounds repeat until stable.

The result is a single `AreaNeed` object:

```python
@dataclass(frozen=True)
class AreaNeed:
    entry: tuple[tuple[int, Bounds], ...]   # (parameter_position, byte_ranges)
    back:  tuple[tuple[int, Bounds], ...]
```

Each tuple element holds the bounds at a parameter position. Position 0 is
DFHCOMMAREA for CICS LINK and XCTL; positions 0, 1, 2, ... are the USING
arguments for CALL.

---

## 2. Why the Current Design Fails at Scale

### 2.1 The union is per-position, not per-callee

`joined()` unions every program's entry bounds at the same parameter position
into one global set. On a corpus where thousands of programs declare
DFHCOMMAREA at position 0, the union of all their entry reads produces a single
contiguous span `[0, max_commarea_length)`.

Measured on a 3779-member corpus:

| Corpus subset | Entry bytes | Shape |
|---|---|---|
| 100 programs | 6,250 | `[0:6250]` contiguous |
| 300 programs | 9,500 | `[0:9500]` contiguous |
| Full corpus | 32,720 | `[0:32700]` + 20 bytes from USING params |

The number grows monotonically with corpus size because different programs store
call targets at different offsets of their DFHCOMMARAs. With enough
contributors every offset is covered.

### 2.2 Clipping does not help

`AreaNeed._within()` clips the global bounds to each program's own area length
(`min(high, area.length)`). A program with a 950-byte DFHCOMMAREA gets
`[0, 950)` — its **entire** area. This is guaranteed whenever the global union
starts at 0 and extends past the program's area, which it always does (every
program reads at least byte 0).

### 2.3 The back-propagation snowball

The iterative rounds amplify the problem. Round 1 produces entry bounds up to
~24,000 bytes. Then the `back` table — bytes callers read after a returning
LINK — feeds back into later rounds' entry demand for programs with larger
COMMARENAs, pushing the global entry bound to ~32,700.

### 2.4 Per-program reads are sparse

Each individual program reads only the bytes that flow into its call-target
fields — typically a few dozen to a few hundred bytes, not thousands. The
liveness analysis computes this correctly per program. Precision is lost only at
aggregation: `joined()` collapses all programs' contributions into one range per
position.

---

## 3. Corpus Shape Supporting the Diagnosis

From the extents table and source corpus:

| Metric | Value |
|---|---|
| Programs with DFHCOMMAREA | 2,135 |
| Distinct DFHCOMMAREA sizes | 492 |
| Largest DFHCOMMAREA | 32,700 bytes |
| Median DFHCOMMAREA | ~643 bytes |
| Programs > 10,000 bytes | 51 |
| LINK sites (static / dynamic) | 2,987 / 191 (94% static) |
| XCTL sites (static / dynamic) | 3 / 4 |
| CALL sites (static / dynamic) | 1,183 / 1,707 (41% static) |

LINK is the primary COMMAREA-passing mechanism. 94% of LINKs name the callee
as a literal, so the callee is known at parse time without running the fixpoint.

---

## 4. Per-Program Area Need

### 4.1 Core idea

Replace the single corpus-wide `AreaNeed` with a per-program table. Each
program's fixpoint walk receives only **that callee's** entry and back bounds,
not the union of all programs.

At a CALL or LINK node, the demand on the handed-over area depends on which
callee the bytes flow into:

- **Static call** (`node.target_resolved is True`): the callee is a literal.
  Look up that callee's entry need from the per-program table.
- **Dynamic call** (`node.target_resolved is False`): the callee is unknown at
  this stage. Fall back to `WHOLE_AREAS` — track every byte of the handed-over
  area at that node.

The back table works symmetrically: after a returning CALL or LINK, the caller
reads back bytes the callee may have written. With per-callee back bounds, a
caller that calls a callee with a 100-byte-sparse read-back only demands those
100 bytes, not the 32,720 the corpus-wide union demands.

### 4.2 Computation (`cobble-dataflow-area-need`)

The area-need pre-pass already iterates per program in `need_found()` and knows
each program's individual contribution. Today `joined()` unions all programs
into one `AreaNeed`. The change:

1. Each program's `need_found()` result is stored under its member name rather
   than unioned into a global aggregate.

2. The iterative rounds still propagate: if callee Y needs bytes `[20:28]` at
   position 0, every caller that hands position 0 to Y must make those bytes
   live. The difference is that the caller looks up **Y's** need, not the union
   of all programs' needs. For static callers this is exact. For dynamic callers
   the round falls back to the current behaviour (all bytes).

3. The round's convergence criterion becomes: no program's individual entry or
   back bounds grew. This is still monotone and finite-height, so termination is
   unchanged.

#### Round mechanics

```
Round 1 (demand = per-program entry from previous round, initially empty):
  For each program P:
    demand_at_P = DemandParts.demand(callee_needs)
      - local:  target operand extents (unchanged)
      - entry:  for each CALL/LINK node:
                  if static → callee_needs[callee].at_entry(position, area)
                  if dynamic → WHOLE_AREAS for that node
      - back:   for each EXIT/GOBACK:
                  for each received area:
                    union of callee_needs[caller].read_back(position, area)
                    for all known callers of P
    live = backward liveness over P's CFG from demand_at_P
    P.entry_need = relative(live_at_entry, P.received_areas)
    P.back_need  = relative(live_after_each_returning_call, handed_areas)

  callee_needs = { P.member: AreaNeed(entry=P.entry_need, back=P.back_need) for P }

Repeat until callee_needs is stable.
```

The `back` side of the computation needs to know P's callers, which introduces
a dependency on the call graph. For the first version, two simplifications are
available:

- **Use only the entry side.** The back contribution is smaller (13,532 vs
  32,720 bytes on the measured corpus) and its propagation is what drives the
  snowball in later rounds. Dropping it is a sound over-approximation: at nodes
  where a caller reads back from a returning call, demand falls back to
  `WHOLE_AREAS`. This still narrows all the LINK/CALL entry demand — the larger
  contributor — without requiring caller-graph information.

- **Compute the call graph from static targets.** 94% of LINKs are static.
  The static edges are known from the CFG alone (no fixpoint). Build an
  adjacency table of `callee → set[caller]` from static LINK/CALL/XCTL nodes
  and use it for the back propagation. Dynamic edges fall back to "every program
  is a possible caller" — a coarser approximation, but one that still narrows
  relative to the current corpus-wide union.

### 4.3 File format

Today's `AreaNeedFile` is a single Pydantic model:

```python
class AreaNeedFile(BaseModel):
    entry: tuple[tuple[int, tuple[int, ...]], ...] = ()
    back:  tuple[tuple[int, tuple[int, ...]], ...] = ()
```

The new format is a JSONL file, one row per program:

```jsonl
{"member": "PROG_A", "entry": [[0, [20, 28, 100, 108]]], "back": [[0, [20, 28]]]}
{"member": "PROG_B", "entry": [[0, [0, 500]]], "back": []}
```

Each row's `entry` and `back` have the same shape as the current
`AreaNeedFile`'s fields: a list of `[position, bounds]` pairs where `bounds`
is a flat list of `[low, high, low, high, ...]` interval endpoints. The only
difference is that each row is one program, not a corpus-wide union.

A JSONL file rather than one large JSON object keeps the format streamable
(programs can be emitted as they settle) and avoids loading the entire table
into memory at once in the fixpoint, where only one program's row is needed at
a time.

### 4.4 Consumer changes (`cobble-dataflow-fixpoint`)

#### `AnalysisOptions`

`areas: AreaNeed` stays as it is. Each member's walk already receives its own
`AnalysisOptions`. The change is in `_narrowed()` (build_corpus.py), which
today reads one global `AreaNeedFile` and hands the same `AreaNeed` to every
member. Instead, it reads the JSONL file into a mapping and, for each member,
looks up that member's row:

```
# Pseudocode — actual implementation will differ
needs_by_member: dict[str, AreaNeed] = load_jsonl(path)

for each member M:
    options.areas = needs_by_member.get(M, WHOLE_AREAS)
    walk(M, options)
```

A member absent from the file (unanalysed, failed to parse) gets `WHOLE_AREAS`
— the same safe default as today.

#### `DemandParts`

`DemandParts.demand(need)` currently applies `need.at_entry(position, area)` at
every CALL/LINK node uniformly. With per-callee narrowing, two changes:

1. **`DemandParts.entry` carries the callee name alongside the areas.** Today
   it stores `tuple[tuple[str, _Areas], ...]` where the string is the node id.
   It gains an optional callee name per entry, populated from `Node.target`
   when `Node.target_resolved` is True.

2. **`DemandParts.demand()` accepts a callee-lookup function** instead of a
   single `AreaNeed`. For static-callee entries, it calls
   `lookup(callee).at_entry(position, area)`. For dynamic-callee entries (no
   callee name), it returns the whole area.

```python
CalleeLookup = Callable[[str], AreaNeed]

def demand(self, lookup: CalleeLookup) -> Demand:
    pieces = (
        *((node, extent) for node, extents in self.local for extent in extents),
        *(
            (node, piece)
            for node, callee, areas in self.entry
            for position, area in areas
            for piece in (
                lookup(callee).at_entry(position, area)
                if callee
                else (area,)
            )
        ),
        *(
            (node, piece)
            for node, areas in self.back
            for position, area in areas
            for piece in lookup_back(...)
        ),
    )
    ...
```

The exact signature and internal structure will follow from the implementation;
the point is that the callee name reaches the place where `at_entry` is called.

#### Liveness

No change to liveness itself (`liveness.py`). The `Demand` it receives is
already narrower because `DemandParts.demand()` produced narrower extents.

#### Jump emission

No change to `jumps_of()`. It reads the settled state and the `Live` object.
With narrower liveness, fewer cells are live at each CALL/LINK node, so `_fields`
emits fewer facts per jump area — the jump areas in `jumps.jsonl` become thinner
automatically.

---

## 5. Expected Improvement

### 5.1 Entry bytes per program

Today every program tracks its entire DFHCOMMAREA because the global bounds
cover `[0, max_length)`. With per-program bounds, each program tracks only the
bytes its call targets actually depend on.

Rough estimates from round-1 individual contributions measured on the corpus:

| Program profile | Current tracked | Per-program tracked |
|---|---|---|
| 500-byte DFHCOMMAREA, reads 50 bytes for targets | 500 | 50 |
| 5,000-byte, reads 200 bytes | 5,000 | 200 |
| 32,700-byte, reads 24,000 bytes | 32,700 | 24,000 |

The first two categories are the majority. Aggregate tracked bytes across the
corpus should drop by an estimated 10–50x.

### 5.2 Fixpoint cost

Fewer tracked bytes means fewer `FieldExtent` objects in the liveness sets,
fewer state entries in the worklist walk, and fewer facts written to
`jumps.jsonl`. The fixpoint cost scales with tracked state, so a 10–50x
reduction in tracked bytes produces a roughly proportional reduction in the
walk's work on the LINKAGE region.

### 5.3 Combine cost

Thinner jump areas mean fewer per-cell facts for the combine to resolve across
programs. The combine's walk, which currently crosses through every byte of every
handed-over area, would cross through only the relevant bytes.

---

## 6. Dynamic Call Sites

191 dynamic LINK sites (6% of all LINKs) and 1,707 dynamic CALL sites (59% of
all CALLs) do not know their callee at parse time. The per-program area-need
pre-pass cannot narrow these because it does not know which callee to look up.

### 6.1 Conservative first pass

The simplest approach: dynamic-callee nodes in `DemandParts.demand()` return
the whole handed-over area. This is what the current `WHOLE_AREAS` does, so
there is no regression for dynamic sites. All the narrowing benefit comes from
the 94% of LINKs and 41% of CALLs that are static.

### 6.2 Optional second pass with resolved targets

After the fixpoint resolves dynamic targets (via the combine), a second
area-need run could use the resolved callee names to narrow the dynamic sites.
This is a two-pass architecture:

```
1. area-need with static callees only → per-program entry/back bounds
2. fixpoint with per-program narrowing → resolves dynamic targets
3. area-need again, now with resolved callees → tighter per-program bounds
4. fixpoint again → cheaper, thinner jumps
```

Whether pass 3–4 is worth it depends on how many dynamic CALL/LINK sites
dominate the cost. LINK is the expensive one (COMMAREA is large), and only 6%
of LINKs are dynamic. Pass 3–4 is likely not worth the double run for this
corpus, but the architecture supports it if needed.

---

## 7. Changes Summary

| File | Change |
|---|---|
| `area_need.py` | No change to `AreaNeed` itself |
| `area_need_file.py` | New `AreaNeedRow` model; reader/writer for the JSONL format |
| `area_need_cli.py` | Stop calling `joined()` across programs; emit one row per program; round convergence checks per-program stability |
| `area_needs.py` | `need_found()` returns per-program needs (already does, just stop unioning at the caller) |
| `demand_parts.py` | `DemandParts.entry` carries the callee name per CALL/LINK node; `demand()` accepts a callee-lookup function |
| `discover.py` | `demand_parts()` populates the callee name from `Node.target` when `target_resolved` |
| `build_corpus.py` | `_narrowed()` loads the JSONL file as a per-member mapping; each member's walk gets its own `AreaNeed` |
| `options.py` | Unchanged (still `areas: AreaNeed` per member) |
| `prepared_program.py` | `DemandParts` now needs the callee lookup at demand time, not at preparation time; `PreparedProgram.parts` stays the same, but `need_found()` passes the lookup |
| `fixpoint.py` | `call_target_demand()` passes the callee-lookup through to `demand_parts().demand()` |

---

## 8. Risks and Mitigations

**Risk: the JSONL file is large.** 2,135 rows with sparse bounds — estimated
under 1 MB. The fixpoint worker reads only the row for its current member, so
memory is unaffected.

**Risk: the area-need pre-pass is slower with per-program tracking.** The rounds
already iterate per program and compute per-program results; the only extra work
is not throwing the per-program results away. The `joined()` call that unions
them is replaced by storing them, which is cheaper. No performance regression
expected.

**Risk: dynamic CALL sites get no narrowing.** This is a sound
over-approximation, not a correctness problem. The 6% of dynamic LINKs track
the full COMMAREA at those nodes, same as today. All other nodes benefit from
per-callee narrowing.

**Risk: round propagation changes.** In the current design, one global `AreaNeed`
is sent to every worker process each round. With per-program needs, the
coordinator sends the full per-program table. The table is small (a few thousand
`(member, bounds)` pairs) and is already transmitted per round, so the
communication cost change is negligible. Alternatively, each worker holds all
programs and the coordinator sends only the per-program needs that changed.

---

## 9. Invariants Preserved

- **Soundness.** Per-program entry bounds are a subset of (or equal to) the
  corpus-wide union. A fixpoint run with per-program narrowing tracks at least
  every byte the call-target demand actually reads. No flow is lost.

- **Monotonicity.** The per-program area-need fixpoint is monotone: each
  program's entry and back bounds can only grow across rounds, and the lattice
  height is bounded by the program's own DFHCOMMAREA length. Termination is
  guaranteed.

- **Backward compatibility.** `--narrow-areas` with the new JSONL file narrows
  more. Without the flag, or with a missing file, the fixpoint falls back to
  `WHOLE_AREAS` — identical to current behaviour.

- **Determinism.** The computation depends only on the ASG cache and the extents
  table, both of which are deterministic for a given parse. The per-program area
  need is deterministic and reproducible.
