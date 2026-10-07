# Fixpoint restricted to call targets — design

Date: 2026-10-07. Status: proposed.

## Problem

`cobble-dataflow-fixpoint` tracks every byte range any statement writes, at every CFG
node. On large CICS programs (about 7,000 lines, 4,000+ nodes) that costs gigabytes
per worker and minutes per member. The current consumer, the cross-program combine,
needs only the bytes that dynamic `CALL`, `XCTL` and `LINK` targets can depend on.

A scratch prototype on CardDemo restricted the walk to those bytes. In all 16 programs
with dynamic sites it resolved the same targets as the full walk. It tracked 2–14
ranges where the full walk tracked 30–310, and needed 1,949 steps where the full walk
needed 8,308 on the largest program.

## Goal

An option on `cobble-dataflow-fixpoint` that analyses each member only over the bytes
its call targets can depend on, here or in another program, and produces the same
`targets.jsonl` and the same combine results as a full run.

Non-goals: demand-driven seeding across programs (option B in the brainstorm),
restricting `cobble-fields-trace`, and restricting to anything other than call
targets.

## Design

### The relevant set

Computed per member, before its walk, from the statements alone. Nobody supplies it.

**Seeds**
1. The target operand of every CFG node in `CALL_TRANSFERS` whose target is not
   resolved to a literal. These are the nodes `resolved_targets` reports today.
2. The commarea operand of every jump the jumps table records: `XCTL`, `LINK`,
   `CALL USING` and `RETURN TRANSID`. These are the bytes the combine reads when a
   callee's target comes from its `DFHCOMMAREA`.
3. The target of every write into the LINKAGE region. This covers bytes a callee hands
   back to a caller after `LINK` or `CALL`.

**Closure.** Take every write that `writes_of(statement, node, index)` reports, with
no state needed. If a write's target overlaps a range in the set, add the ranges of
its sources that come from storage. Repeat until nothing is added. Overlap is byte
overlap within one region, which is the same test `values_at` and the kill rules use.

### The walk

`AnalysisOptions` gains a `scope` enum: `WHOLE` (the default, today's behaviour) or
`CALL_TARGETS`. With `CALL_TARGETS`, the fixpoint computes the relevant set and
hands it to the transfer, which drops every write whose target does not overlap the
set. Nothing else in the walk changes: join, kills, values, settling and the budget
all apply as they do today.

The result for any byte in the set is the same as the full walk's. A dropped write
cannot reach the set: it doesn't overlap it, and it isn't a source of any write that
does. So it cannot change what the set holds.

### Outputs

The usual six files, covering only the relevant set. `counts.json`
(`MemberCounts`) gains:
- `scope`;
- the size of the relevant set;
- the number of ranges a full walk would have tracked.

The run log reports both sizes per member, which is how option A's set sizes get
measured on a real corpus.

**Reuse.** If a member directory exists but its `counts.json` records a different
scope from the one requested, the run stops before analysing anything. It names the
members and asks for `--force`. Mixing scopes in one out-dir would publish a corpus
graph that is complete for some members and partial for others.

**Readers.** `cobble-dataflow-fixpoint-query` refuses an out-dir whose members were
restricted, and says why. Its questions are about arbitrary fields, which a
restricted run does not answer. The combine reads restricted output as it is.

### CLI

```
cobble-dataflow-fixpoint --asg-dir … --out-dir … --extents … --all --call-targets-only
```

The option combines with `--iteration-factor` and `--sweeps`, and with
`--member`/`--all`.

## Testing

Unit tests, no JVM:
- **Closure.** It reaches a target through a chain of MOVEs. It reaches a
  reference-modified source. It does not pull in a record that only shares a group
  with the target.
- **Restricted transfer.** It leaves the relevant bytes exactly as the full transfer
  does, on a hand-built statement sequence.

Integration tests, invented COBOL through the bridge, as in
`tests/dataflow/fixpoint/conftest.py`:
- **Local target.** The restricted run's `targets.jsonl` equals the full run's, with
  fewer steps.
- **Through a commarea.** A caller XCTLs with a literal moved into a commarea field,
  and the callee CALLs a field read from `DFHCOMMAREA`. The combine's targets and
  links from restricted output equal those from full output.
- **Through a write-back.** A caller LINKs, the callee writes a program name into
  its linkage, and the caller CALLs it. Same equality as above.
- **Mixed scopes.** A rerun in the other scope without `--force` stops and names the
  member.
- **Query refusal.** `fixpoint-query` refuses a restricted out-dir.

Cost: `test_fixpoint_cost_synthetic.py` gains a fixture with dynamic call sites,
recorded in both scopes.

## Documentation

The cobble README gets the option in the fixpoint stage's section and a line in the
pipeline sequence, in the same commit as the code.

## Open questions for review

1. The option name `--call-targets-only` and the enum name `scope`.
2. Whether mixed scopes should be refused (proposed) or the stale members re-analysed
   automatically.
