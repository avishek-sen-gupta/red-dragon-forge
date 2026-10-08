# Per-Program Area Need — Design

**Date:** 2026-10-08
**Components:** `cobble-dataflow-area-need`, `cobble-dataflow-fixpoint --narrow-areas`
**Diagnosis:** `docs/analysis/2026-10-08-per-program-area-need.md`. This spec corrects its §4.4
lookup and its "entry side only" shortcut, and settles its dynamic-caller question.

## Problem

The area need is one union per parameter position over the whole corpus. On a large CICS corpus
the union of every program's commarea reads covers `[0, 32700)`, so every program keeps its
whole area and `--narrow-areas` narrows nothing. Each program's own reads are sparse; the
precision is lost only in the union.

## Goal and success

`--narrow-areas` narrows per program, and the call targets stay what a whole-area run finds.

- CardDemo: `--call-targets-only --narrow-areas` gives the same targets and the same graph as the
  whole-program run.
- Synthetic: two callees reading different slices of what their callers hand over each keep
  only their own slice; a dynamic site gets the union for its kind; an unknown callee gets the
  whole area.
- The large corpus: per-program needs fall well below each program's area length. Reported by
  the run, not asserted by a test.

## Decisions

1. **Areas are addressed by kind and position.** `AreaKind.COMMAREA` is what LINK and XCTL hand
   over and a program receives as `DFHCOMMAREA`, always position 0. `AreaKind.USING` is a CALL
   argument and a `PROCEDURE DIVISION USING` parameter, by position. A CALL's parameter 0 and a
   commarea no longer share a slot.
2. **Lookups go by callee, not by corpus.** A program's walk demands, at each call site, what
   *that callee* reads on entry, and at its exits what *its callers* read back.
3. **Dynamic sites use the union for their kind.** A call whose callee is not a literal demands
   the union of every program's entry need at that slot. A program's back need includes the
   read-backs of every dynamic call site of its kind. Both are supersets of any one callee or
   caller, so both are sound.
4. **Unknown means whole.** A static callee absent from the table, or present but not receiving
   that slot, demands the whole handed-over area. A member absent from the table is walked with
   whole areas, as today.
5. **One pass.** No second run with resolved dynamic targets.
6. **The positional-copy rule stays.** It decides what one program reads; this design decides
   whose reads a program is charged with.

## Data

- `AreaSlot(kind: AreaKind, position: int)` — frozen dataclass; `AreaKind` an enum.
- `AreaNeed` keeps its shape, addressed by `AreaSlot` instead of `int`: `entry` and `back` as pairs of
  `(AreaSlot, Bounds)`. `WHOLE_AREAS` stays.
- `CallSite(callee: str, kind: AreaKind)` per call node in `DemandParts.entry`, `callee` empty
  when the target is not a literal. `CallSite` and the areas replace the bare node id's areas.
- `AreaTable` — per member, its resolved `AreaNeed` and the slots it receives; plus, derived on
  construction, the entry union per slot over all members. Methods:
  - `entry_at(site, slot, area)` — the callee's entry bounds, the kind union for a dynamic site,
    or the whole area when the callee or slot is unknown.
  - `back_of(member, slot, area)` — the member's back bounds, or the whole area for an absent
    member.
- `DemandParts.demand(table, member)` replaces `demand(need)`. `call_target_demand` and the
  area-need rounds both go through it, so the two cannot disagree on what a lookup means.

## Area-need run (`cobble-dataflow-area-need`)

Unchanged machinery: members prepared once in resident shard workers, liveness over each
`LiveGraph`, rounds until nothing changes.

Each round the coordinator sends the current `AreaTable`. For every program a worker reports:

- its **entry need**: the received bytes live at its entry, by slot;
- its **read-backs**: per returning call site, `(CallSite, slot, bounds)` for the bytes of the
  handed-over area live after the call.

The coordinator resolves the next table:

- `entry[P]` = P's reported entry need;
- `back[P]` at slot k = union of read-backs from static sites naming P at k, and of every dynamic
  site's read-back at k.

It stops when the table equals the previous one. Monotone and bounded by each area's length, so
it terminates as today.

The log keeps `[i/N] member` per member per round, adding that member's entry bytes, and per
round the total entry and back bytes summed over members and the number of static callees not
found in the table.

## File

JSONL, one row per member, written by `cobble-dataflow-area-need`:

```json
{"member": "PROG_A", "receives": [["commarea", 0]],
 "entry": [[["commarea", 0], [20, 28, 100, 108]]], "back": [[["commarea", 0], [20, 28]]]}
```

Parsed by an `AreaNeedRow` Pydantic model on read. `--narrow-areas` reads the whole file into an
`AreaTable` (a few thousand small rows) and hands it to every member's walk. The old single-object
file fails validation, and the fixpoint refuses it with a message naming
`cobble-dataflow-area-need`.

## Fixpoint (`cobble-dataflow-fixpoint`)

`AnalysisOptions.areas` becomes an `AreaTable`; without `--narrow-areas` it is the empty table,
whose every lookup is whole. Each member's demand is `demand_parts(...).demand(table, member)`.
Liveness, the walk, and jump emission are unchanged; jump areas come out thinner because fewer
bytes are live.

## Tests

- **Unit, `AreaTable`:** static callee hit, dynamic union, unknown callee, unknown slot, absent
  member — exact bounds for each.
- **Synthetic corpus (new fixtures):** a caller LINKs two static callees that read different
  slices of the commarea, and CALLs a third by a data name. The area-need rows equal the
  expected bounds exactly; the narrowed fixpoint's targets equal the whole-program run's.
- **Existing narrow chain test:** its expectation becomes the per-member rows.
- **CardDemo, by hand before commit:** targets and graph equal to the whole-program run, and the
  per-member bytes reported.

## Out of scope

A second pass over resolved dynamic targets; seeds other than call targets; streaming one row at
a time.
