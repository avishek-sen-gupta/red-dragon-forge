# Design: reachability from a PERFORM site, with return and abort semantics

**Status:** proposed, revised after review (first draft in commit `c8f5ce1`).

## Problem

"Which paragraphs can run from this `PERFORM` until control comes back, and how
can it fail to come back?" needs a walk over the src-cfg that knows which
`PERFORM` is active. A plain BFS/DFS over the exported CFG does not: a range's
`#end` carries one `RETURN` edge per `PERFORM` site that closes there plus a
`FALLTHRU` to the next paragraph, and which one control takes depends on the
call stack. Measured on a ~1250-node production member, following every
`FALLTHRU` reached ~85% of the program, excluding all of them stopped after a
handful of nodes, and a hand-rolled stack version stopped on the caller's
`#label` where a `RETURN` lands mid-paragraph, so it never stopped.

(Those measurements predate the `Node.resume` change: CFGs exported before it
also kept a `FLOW` edge past every returning `PERFORM`, which inflates the 85%.
A BFS is still wrong on a fresh export; the numbers should be re-taken.)

`cobble-fields-trace --record-paths` has a correct stack walker but answers a
different question: sampled paths from the program's entry, one arm per
decision, chosen for byte-provenance coverage. It cannot start at a given
`PERFORM`, and its helpers take its provenance walk's own types.

## The question this answers

Reachability, not path enumeration. Taking both arms of every decision along a
path is exponential in the decisions on it; reachability over (node, stack)
states visits each state once. The tool reports what *can* run and how the
`PERFORM` can end, not the routes between them.

## Input

- The CFG file `cobble-srccfg-build` writes, read with `srccfg.bundle.load_bundle`
  into typed `Cfg`s (the seed's program). That export is
  `program_cfg`'s output, so it carries the HANDLE CONDITION edges
  `with_handler_edges` adds; `build_program` alone does not, and would hide every
  error-handler paragraph.
- A seed: the id of one `PERFORM` node in that CFG. Anything else is refused
  with a message naming what the node is.

## Semantics

A state is a node plus a stack of frames; a frame is an open `PERFORM`'s resume
point together with the range end its `RETURN` leaves from (`Node.range_end`,
which the build records beside `Node.resume`). The walk starts by entering the
seed's range with one frame, the seed's own.

(Revised after the implementation's review: a frame was first the resume point
alone, but the two arms of an IF can PERFORM different ranges that resume at one
statement, and a frame keyed by resume point took one range's RETURN for the
other's. A range end also returned only to the innermost frame, which left a GO
TO from inside a nested PERFORM to the outer range's exit with no outcome.)

| At | The walk |
|---|---|
| a `PERFORM` whose range resolves | pushes a frame of its resume point (`Node.resume`, else its `FLOW` successor, as `fields.trace._sequel` reads it) and its range end, and follows the `PERFORM` edge only. It never takes the `FLOW` edge past it: control comes back through a `RETURN` or not at all. |
| a `PERFORM` whose range does not resolve (no `PERFORM` edge) | follows its `FLOW` edge and records it as unresolved. |
| a `PERFORM` whose frame is already open | does not push: a recursive `PERFORM` is undefined in COBOL. Recorded as refused, and the walk continues at the resume point as if the range had run. |
| a range end (`#end` with `RETURN` edges) | returns from the innermost open frame whose range ends here, to its resume point, dropping the frames opened inside it (a `GO TO` out of a nested range abandons them). With no such frame it takes the `FALLTHRU`, as COBOL falls through an end no open `PERFORM` closes. Dropping the abandoned frames approximates the compiler, which leaves their ends armed. |
| the seed's own resume point, reached by that pop | records **returns** and stops that branch. |
| a `GO TO` (including one out of the range) | follows it with the stack unchanged. COBOL keeps the pending return, so a later arrival at that range's end still returns. |
| a `TEST` | follows both arms. |
| a CALL / LINK to another program | continues along its `FLOW` edge; the call is recorded, not entered. Cross-program reach is out of scope. |
| an abort | records the outcome and ends the branch (below). |

**Aborts.** A branch ends, recording its kind and node, at:

| Outcome | Where |
|---|---|
| `stop-run`, `goback`, `exit-program` | the terminator node (`transfer` `STOPRUN`, `GOBACK`, `EXITPROGRAM`) |
| `abend` | `EXEC CICS ABEND` (`transfer` `CICS_ABEND`) |
| `xctl`, `cics-return` | the command node (`transfer` `CICS_XCTL`, `CICS_RETURN`): a successful one leaves the program, and since the lowering gives success no edge, the walk classifies the command itself. Its failure path -- the raise arm to a handler, or under `RESP`/`NOHANDLE` the next statement -- is followed like any edge. |
| `unhandled-condition` | a `#dispatch` node with no outgoing edge: a CICS condition raised with no handler armed, which CICS turns into an abend |

A node with no successors that is none of these is recorded as `dead-end`
with its id, so a gap in the lowering shows up rather than reading as an abort.

**Termination.** A state is visited at most once. Stacks are bounded by the
program's nesting of open `PERFORM`s (a resume point is never pushed twice), so
the state space is finite. Its size is the risk: one paragraph performed from
many depths contributes one state per distinct stack. The run reports the
number of states it visited.

## Output

JSONL on stdout, in the src-cfg row format
(`docs/superpowers/specs/2026-10-02-srccfg-jsonl-design.md`, which lands first),
written as the walk goes, so a reader can stop early and still hold a valid
partial graph. `cobble-srccfg-dot` and `-webgl` render it, since they read that
format and skip the rows below that are not graph rows.

Graph rows -- the reached part of the CFG:

- one `program` row first;
- a `node` row the first time the walk reaches a node, unchanged from the input
  CFG. Row order is first-reached order of the breadth-first walk, nearest the
  seed first, which is the flat view of what runs;
- an `edge` row the first time the walk takes an edge, after both its nodes.
  Only taken edges appear: a `RETURN` to another `PERFORM` site, or a
  `FALLTHRU` the stack ruled out, is absent even when both its ends were reached.
  Every edge written was taken in some valid state, so a plain BFS from the seed
  over these rows reaches exactly the reachable set.

What the graph does not keep is the stack. A paragraph reached from two
`PERFORM` sites inside the walk keeps both their `RETURN` edges, so the picture
says what can happen, not which return belongs to which call, and one route
through it is not guaranteed to be a real execution.

Reach rows -- what the graph cannot carry, each written when it is found:

```
{"type": "outcome", "kind": "returns", "node": "CALLER/5"}
{"type": "outcome", "kind": "xctl", "node": "ERR-PARA/2"}
{"type": "unresolved", "node": "TARGET-PARA/3"}
{"type": "refused", "node": "TARGET-PARA/7"}
{"type": "summary", "seed": "CALLER/4", "states": 412}
```

- `outcome`: each distinct (kind, node) once.
- `unresolved`, `refused`: the `PERFORM` nodes the semantics table records.
- `summary`: last, so its presence says the walk finished; `states` is how many
  (node, stack) states it visited.

The graph is at statement level, like every other src-cfg file. A
paragraph-level collapse is a separate view and not part of this.

## Shape

- `cobble/dataflow/srccfg/reach.py`: the walk, a pure function of `Cfg` and seed.
  It imports from `srccfg` only. It does not import `fields.trace`: that
  module's helpers take its provenance `_Walk`/`Loaded`, and the rules it needs
  (`RETURN` matched to the innermost frame, the resume point) are a few lines over
  `Cfg`. Sharing them with trace is a later refactor, not a dependency now.
- `cobble-srccfg-reach --cfg <jsonl> --from <node-id>`: the command, beside
  `cobble-srccfg-query`, in the same form.
- README: the command in the command table, the semantics table above, the
  outcome kinds, and that the output renders with `cobble-srccfg-dot`/`-webgl`.

## Testing

Unit tests build CFGs with `build_program` / `program_cfg` from ASG dicts, as
the srccfg tests do, one test per behaviour:

- a `PERFORM ... THRU` range that falls through its own paragraphs and returns;
- a range end shared by two `PERFORM` sites returns only to the seed's;
- a nested `PERFORM` inside the range returns to its own site first;
- a `GO TO` out of the range continues and still returns at the range end;
- a branch ending in STOP RUN, GOBACK, `XCTL`, `ABEND`, and a raised condition
  with no handler each yields its outcome;
- a HANDLE CONDITION handler is reached through its dispatch edge;
- a recursive `PERFORM` is refused, not looped;
- an unresolved `PERFORM` target is recorded and stepped past;
- a non-`PERFORM` seed is refused;
- an edge whose ends were both reached but which the walk never took (a second
  site's `RETURN`) is absent from the subgraph.

One integration test compiles an invented program through the bridge,
`cobble-srccfg-build` and the command, asserting every row -- the subgraph's
node and edge rows in order and the reach rows -- and that `cobble-srccfg-dot`
renders the output.

## Out of scope

- Path enumeration, and per-call `RETURN` attribution in the graph.
- Following CALL/LINK/XCTL into other programs.
- Conditions: which guard makes a paragraph reachable is
  `cobble-srccfg-query guards`.
- `ALTER`, which the lowering does not model.

## Open questions

- Whether the state count stays small on the largest corpus members. If not,
  the follow-on is per-range summaries (each range's exits computed once), not
  a cap.
- The first draft's observation that a sampled `fields-trace` path continued
  past a `GOBACK` is unconfirmed. This tool does not depend on it; it should be
  reproduced and filed against trace separately, or dropped.
