# Horn clause lowering (experimental)

One program's control-flow graph written as constrained Horn clauses, and a question about it
answered by Z3's Spacer engine (the `z3-solver` package). The code is
`cobble/experimental/horn/`; nothing else in cobble imports it, and every use of z3 stays inside
it. There is no command yet: a question is asked from Python, as the CardDemo tests do.

## What it reads

A program's ASG, which gives the CFG (`program_cfg`), the statement at each node and the
88-levels, and that program's `extents.jsonl` rows. It neither reads the
[Datalog facts](datalog.md) nor needs that stage to have run; the `.importlinter` contract
`horn-not-datalog` forbids the import.

## The encoding

- **Tracked fields.** A name declared with exactly one extent, `PIC X…`, `USAGE DISPLAY`, and
  compared by some `==` or `!=` test. Its value is a z3 string of the field's length. A name
  declared twice, a numeric field, a group and anything never compared is not tracked.
- **Tests.** A TEST atom is encoded exactly when its op is `==` or `!=`, its left side is
  tracked, and its right side is a quoted literal no longer than the field (padded right with
  spaces), `SPACE(S)`, `LOW-VALUE(S)`, `HIGH-VALUE(S)`, or a tracked field of the same length.
  Every other test, unresolved ones included, constrains nothing.
- **Contexts.** One relation per node per context. A context is the top level, or one PERFORM
  range, named by the PERFORM's target label and its `range_end`. A range's relations carry the
  state it was entered with as well as the current one, and a summary relation joins the two at
  the range's end, so a PERFORM resumes only with the states its own call produced.
- **Edges.** FLOW, FALLTHRU, GOTO, TRUE and FALSE are followed; TRUE and FALSE carry the test or
  its negation. RETURN edges are not followed; returns go through summaries. A FALLTHRU out of a
  range's end is not followed inside that range. A node with no successors ends the task.
- **Writes.** Every tracked field whose bytes overlap a written name's extent becomes
  unconstrained after the write; the others keep their value.
- **Unconstrained.** The initial state, every input, every write, every untracked field and every
  test not encoded exactly. A missing fact therefore never removes a run, so `unsat` holds for
  the program the CFG describes.

The CFG's own over-approximations carry over: where `build.py` keeps the edge past a PERFORM whose
range end nothing reaches, the statement after it stays reachable.

## Asking

```python
system = lower(program_of(asg, extents))
verdict = reaches(system, Point("PROG", node_id), (Condition("FLD", Op.EQ, "'A'"),), clock)
```

`reaches` asks whether some run arrives at the node, in any context, with the conditions true
there, before the node's own statement runs. A condition on an untracked field raises
`ValueError`. The answer is one of:

- `UNSAT`: no run does;
- `SAT`: some run of the encoding does, which is a real run only as far as the encoding is exact;
- `UNKNOWN`: Spacer gave up.

`Verdict.seconds` is the solver's time, from the clock passed in.
