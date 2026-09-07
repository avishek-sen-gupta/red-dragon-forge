# Path-sampling byte trace — design

**Status:** approved 2026-09-07. Separate from the fixpoint, which stays exactly as it is.

## The problem

`cobble`'s field dataflow answers "could these bytes flow" over all paths at once. It joins
at every merge, so an `ELSE` arm's write and a `THEN` arm's write become one set of sources
and the answer cannot say which route carried what. Two consequences it has been paying for:

- **A `PERFORM`ed paragraph returns to every caller.** `srccfg/build.py` lowers a paragraph
  once, so two `PERFORM`s of it give it two `RETURN` edges and the walk takes both from
  either site. Its own docstring calls this "the deliberate imprecision".
- **A call is a wall.** `transfer.py` treats `LINK`/`XCTL` as a write to the commarea operand
  from the synthetic origin `%CALL:<program>`, with no knowledge of the callee. Crossing was
  then rebuilt at query time as a BFS over `aliases.jsonl` with its own hop budget, depth
  budget, cost model and pruning — machinery that exists only because the analysis stopped at
  the program boundary.

Neither is a bug in the fixpoint. They are what a path-insensitive analysis costs.

## What this builds

A second, independent walk that interprets **one concrete path at a time**, threading a
single store with no join anywhere, and samples enough paths to give a useful picture.

Because a path has a stack, both problems above vanish rather than being worked around:

- The `RETURN` edge taken is the one back to the caller actually on the stack.
- A `LINK` is a step into the callee. Bind the callee's `DFHCOMMAREA` onto the caller's
  window and keep interpreting. Write-back needs no mechanism: in a byte-addressable memory
  model the two sides are the same storage.

It is a **targeted CLI**, not an artefact producer. It writes no table and adds no artefact
contract. The corpus-wide question is already answered by the four existing tables.

### Not a replacement

The fixpoint keeps its guarantee — over-approximate, every real flow present. This walk
under-approximates: it reports flows witnessed on sampled paths and misses the rest. The two
answer different questions and both are worth having. Nothing in `fixpoint.py`,
`transfer.py`, `state.py`, `aliases.py`, `build_corpus.py` or `query.py` changes.

## Interface

```
cobble-fields-trace PROGRAM --asg-dir DIR --out FILE
                    [--paths N] [--coverage F] [--max-depth N]
```

`PROGRAM` is the ASG cache stem to start from. `--asg-dir` is the parse every other stage
reads — the same directory the `fields` config names. No artefact directory is needed: this
walk reads the ASG cache directly, which is what lets it enter a callee `aliases.jsonl` has
no rows for.

**The walk always emulates all of memory, and reports all of it.** There is no per-field
mode and could not be one: `transfer` writes whatever a statement writes, and tracking one
field means tracking everything that reaches it, which is everything. There is no per-field
*report* either — filtering is `grep`'s job on a file that is already grouped by extent, and
a flag for it would be a second way to ask a question the output already answers. `--out` is
required because a whole-memory report from a few hundred paths is a file, not a terminal.

This is also why the walk is cheap on memory: one store for the whole path. `fixpoint.py`
holds one per CFG node.

Stops at whichever of `--paths` or `--coverage` comes first. `--max-depth` bounds one path's
node count so a pathological program cannot run forever.

Output is the **union over the sampled paths**, deduplicated — grouped by the program a write
happened in and the call site that program was entered through, then by written extent, then
one summary:

```
PROGA
  WS-OUT-KEY@working_storage[0:4]
    <- WS-SEED@working_storage[12:16]      at PROGA/MAIN-PARA/1   defined at PROGA/MAIN-PARA/0
  WS-SEED@working_storage[12:16]
    <- LITERAL                             at PROGA/MAIN-PARA/0

PROGB   via PROGA/MAIN-PARA/2
  SUB-REC@working_storage[0:12]
    <- DFHCOMMAREA@linkage[0:12]           at PROGB/SUB-PARA/0    defined at PROGA/MAIN-PARA/1

dead ends:
  PROGA/MAIN-PARA/7   XCTL   PROGC   callee-not-in-cache

branch coverage: 412/489 (84%) over 200 paths, 3 programs entered
```

`via` is the call site the program was entered through, innermost when nested — so a reader
reconstructs the route without the walk printing every node it passed. No path ids: the
report is the union, and a path id would only label a route it does not print.

`defined at` is the payload, and it is what no existing artefact can say. It names the node
whose write last put those bytes there **on this path, in whichever program that was** — the
interprocedural chain the deleted crossing BFS had to rebuild at query time. A source that is
not storage prints as its origin (`LITERAL`, `FILE:<name>`, `%CALL:<name>`) with no
`defined at`, which also settles for this tool the confusion bead `bm7` names: an external
origin no longer reads like an absence.

### Provenance, not values

The store holds *where bytes came from*, which is what `state.Source` carries — an extent or
a synthetic origin, plus the defining node. It does not hold what the bytes **are**. Emulating
memory closely enough to evaluate a literal `MOVE`, an `ADD`, or a branch condition is a
different and much larger piece of work, and `vendor/red-dragon` is the thing that already
does it. Deliberately out of scope: the moment values enter, branch choice stops being a
cursor and becomes execution, and the sampling design no longer applies.

## Mechanism

Three pieces of state, all immutable and threaded:

```
store    : program -> {FieldExtent: frozenset[Source]}   # per-program slice, never joined
stack    : (Frame, ...)                                  # open invocations, innermost last
cursors  : (program, node) -> int                        # branch choice, global across paths
```

A `Frame` is one open invocation: the program it runs in, the node to resume at when it
returns, and **the nodes it has run so far**. It is popped whole on return, and that is what
makes the re-entry rule below come out right in all three of its cases — a paragraph's frame
takes its visited nodes with it when it returns, so a second `PERFORM` of the same paragraph
starts clean, while a frame that is still open still forbids re-entry. The root of a path is a
frame like any other, so the stack is never empty while the path is running.

The store is keyed by program **outside** the extent because `RegionId` is an enum of six
`DATA DIVISION` sections and carries no program: two programs' `WORKING_STORAGE@100` are the
same `FieldExtent`, and `may_alias` would conflate them. Slicing by program keeps every
`may_alias`/`must_cover` comparison inside one program's storage, where those predicates are
sound, and needs no change to `cobol_memory` — which is vendored and not ours to modify.

### One path

At each node, take `writes_of(statement, node, index)` and apply each `Write` to that
program's slice with `state.write`. Every write, for every field — the store is the program's
whole memory and the report is all of it. `state.join` is never called.

A witnessed dependency is recorded per `(write target, write source)` pair, and the source's
**definers** come from `state.reaching` against the slice as it stood *before* the statement.
That read is the whole reason the store exists: `transfer` builds a `Source` from the source
operand's own extents and never consults the state, so without `reaching` the walk would only
restate the statement. Node ids going into the store are qualified with their program
(`PROGA/MAIN-PARA/1`), because `state.Source` carries a bare node id and a definer that
crossed a call is in a different member.

Choose the next edge from `cfg.successors(node)`. Two edge kinds are decided by the stack
rather than sampled, because they are not branches:

- A **`PERFORM`** edge is always taken, and a frame is pushed whose resume point is the target
  of this node's own `FLOW` edge. The `FLOW` edge is never taken from a `PERFORM` node — it
  exists only so `build.py` can compute the `RETURN` targets, and taking it would skip the
  paragraph. If the `PERFORM` target is on the stack the edge is refused by the re-entry rule
  and the `FLOW` edge is taken instead, which is the right degradation: the paragraph is
  skipped rather than the path abandoned.
- A **`RETURN`** edge is taken only when its target is the innermost frame's resume point, and
  the frame is then popped. This is the first path-insensitivity cost paid off. When no
  `RETURN` target matches — a paragraph reached by falling through rather than by a `PERFORM`
  — every `RETURN` edge is dropped and the remaining successors are sampled normally, which is
  also correct and also something the fixpoint cannot do.

Everything else is a branch:

1. Drop any successor already visited by an open frame.
2. Take `admissible[cursors[node] % len(admissible)]`.
3. Advance that node's cursor.

The path ends when no successor is admissible, or at `--max-depth`.

### The re-entry rule

**Never traverse an edge back to a node already on the current path's stack.** One rule,
three cases:

- A loop's back edge targets a node on the stack, so it is refused: the body runs once and
  the walk takes the exit edge. That is the unroll-once decision, and it means a
  loop-carried dependency needing two iterations is not found.
- A paragraph `PERFORM`ed from two places in one path is *not* on the stack the second time —
  the first `PERFORM` already returned — so it is allowed. Two arms of it get explored in one
  trace, which is real: the two sites genuinely can behave differently.
- Recursive `PERFORM` and a `LINK` cycle across programs are the same rule, with no extra
  machinery.

### Crossing a call

`aliases.commarea_aliases(asg, index, asg_dir)` is called once per program entered and its
rows indexed by node, since it returns every site in the member at once.

At a `CALL` node whose verb is `LINK` or `XCTL`, take the site's window and parse the two
extents with `extent_text.byte_range`, rebuilding a `FieldExtent` from each — the region text
is a `RegionId` value, so `RegionId(text)` is the way back. A row carrying a `reason` instead
of two extents has no window to bind, so no crossing happens and the path continues at the
call node's successor — the caller's own path is not over, and `transfer` has already credited
the commarea to `%CALL:<program>` exactly as the fixpoint does. The reason is reported in its
own `dead ends` section, keyed by site, so a reader sees why that route stopped short without
it being mixed into the dependencies.

One site can yield several rows, when its operand name matched cells in two records. That is a
layout ambiguity, not a branch, so the first row is used rather than sampled.

Seed the callee's slice: for every extent in the caller's slice that overlaps
`caller_extent`, insert the same sources at the extent rebased onto `callee_extent` — the
shift and clip `query.py`'s `_rebased` already performs. Push `(program, node)`, load the
callee's ASG with the same reader `aliases.py` uses, build its `Cfg`, and walk from its entry.

The callee's slice starts **empty** and is seeded only through the window. That is CICS's own
semantics — a `LINK`ed program gets fresh `WORKING-STORAGE` — and it means a program entered
twice on one path does not inherit its own earlier run's memory.

On the callee's path ending, `returns` decides: `LINK` seeds the caller's window back from the
callee's `DFHCOMMAREA` slice and resumes at the call node's successor; `XCTL` does not return,
so the path ends there.

`Cfg`s, `CellIndex`s, statement indexes and alias tables are built once per program per
process and reused across paths, memoised on `(asg_dir, program)` the way `aliases.py`
memoises its callee reads. A program whose `WORKING-STORAGE` cannot be laid out
(`UnsizeableFieldError`) cannot be entered, and its call site becomes a dead end with that
reason — the callee's `LINKAGE` laying out is not evidence that the rest of it does.

### Coverage

Branch coverage counts distinct `(program, node, edge)` triples taken over `TEST` nodes,
against the total such edges in every `Cfg` the walk entered. Denominator grows as new
programs are entered, so it is reported alongside the program count and never derived from
what the walk produced — the `3ao` post-mortem found an acceptance suite passing while its
walk reached 18% of nodes, because the denominator came from the answer.

## Stated limits

These go in the CLI's own output, not only here. A number a reader can act on, not a verdict
tuple — the query-time stop layer was deleted on 2026-09-07 for being unreadable, and this
must not reintroduce it in another shape.

- **Unsampled paths' flows are missing.** The coverage percentage is the disclosure.
- **Unroll-once misses a loop-carried dependency** that needs a second iteration.
- **Conditions are not evaluated**, so some sampled paths cannot happen at run time. The
  fixpoint has this too and worse, since it takes every path including the infeasible ones.
  `srccfg`'s reaching conditions could prune later; out of scope here.
- **Sound in one direction only.** Every reported dependency is witnessed by an actual path.
  Absence means "not sampled", never "does not exist".

## Constraints

Two new modules: `cobble/cobble/dataflow/fields/trace.py` for the walk, which knows nothing
about text, and `cobble/cobble/dataflow/fields/trace_report.py` for the rendering and the
argparse CLI. Entry point `cobble-fields-trace` in `cobble/pyproject.toml`. Tests in
`cobble/tests/dataflow/fields/test_fields_trace.py`. Two modules rather than one because
`query.py` is the counter-example in this same directory: it grew to a thousand lines by
holding a walk and its output format together.

- The `.python-fp-lint` rule set must pass at zero for the new module: no `Optional`, no
  `X | None`, no `None` defaults, no `is None`, no `Any`, no unfrozen dataclass, no
  `list.append`/`extend`/`insert`/`pop`/`remove`, no subscript or augmented mutation, no
  `dict.update`/`setdefault`, no static method, no mutation inside a loop, no deep nesting,
  no reassignment, no inline suppression.
- Black, line length 88. Ruff clean. `lint-imports` must stay at 11 kept / 0 broken: the
  module may read `cobble.dataflow.*`, `cobol_asg`, `cobol_memory`, and nothing from
  `cicada`/`squall`/`jackal`.
- `vendor/red-dragon` is not modified.
- No corpus identifier in any tracked file, commit message included. Fixtures use `PROGA`,
  `PROGB`, `WS-*`; `DFHCOMMAREA` is a standard CICS name and is fine.
- Comments are a smell. One survives only by carrying an external constraint, a non-obvious
  why, or a reference.
