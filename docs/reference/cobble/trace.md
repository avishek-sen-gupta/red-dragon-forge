# cobble: path traces

`cobble-fields-trace` samples concrete paths through one program and the callees it enters,
recording per path where each field's bytes came from. `cobble-trace-query` walks that record.
The trace under-approximates: a flow it does not report was not sampled, and a loop body runs
once. The [fixpoint](field-dataflow.md) over-approximates. Neither replaces the other.

Code: `cobble/cobble/dataflow/fields/trace*.py`.

## cobble-fields-trace

```
cobble-fields-trace PROGRAM --asg-dir DIR --out OUT
    [--paths N] [--coverage F] [--max-depth N] [--record-paths FILE]
    [--single-program] [--force]
```

| Flag | Meaning |
|---|---|
| `PROGRAM` | the ASG cache stem to start from |
| `--asg-dir` | the ASG cache |
| `--out` | the JSONL trace. An existing file is left as it is |
| `--paths` | paths to sample before stopping (default 200) |
| `--coverage` | stop once this fraction of branch edges has been taken (default 1.0) |
| `--max-depth` | nodes one path may visit. Default: three times the CFG nodes of every program the entry can reach, or of its own CFG with `--single-program` |
| `--record-paths` | also write one path record per sampled path, for `cobble-viz-pathwalk` |
| `--single-program` | stay in PROGRAM's CFG. `LINK` and `XCTL` run as statements, crediting the commarea to `%CALL:<program>`, and no other program is loaded |
| `--force` | trace again and overwrite `--out` |

### Calls

A `LINK`ed callee is entered by binding its `DFHCOMMAREA` onto the caller's commarea window, so
the two sides are the same storage. A `CALL` is entered with one window per `USING` argument,
bound to the callee parameter at that position. On return only a `BY REFERENCE` window is
written back. An argument with no window is a dead end of its own, and the `CALL` is still
entered.

An entered call does not credit its windows to `%CALL:<program>`: the callee shares those
bytes, so a byte it never writes comes back with the caller's own provenance. Each window
gets a dep row at the callee's entry, from the caller's bytes to the callee's, with
`source_program` the caller, so a forward query crosses into the callee.

A callee the cache does not hold is an opaque block. The site is listed under dead ends with
the alias reason (`callee-not-in-cache`), the commarea is credited to `%CALL:<program>`, and
the path runs on past the call.

A path keeps a stack, so a performed paragraph returns to the site that performed it.

### Sampling

A path is a plan: the arm to take at each branch, in the order branches arise. The walk is a
pure function of the plan, so there is no random seed. Past its own end a plan takes the first
arm; arms that lead nowhere are ordered last. After a path runs, each branch it met with an
untried arm yields a new plan. Plans that would take a branch edge nothing has taken run first.
The run stops when the coverage target is met, the path budget is spent, or no plan can reach a
new branch (`nothing unexplored is reachable`).

### Output

JSONL, appended per path, so a killed run still leaves a queryable file. Footer rows (dead
ends, coverage, limits) are written at the end. Dep rows can repeat across paths. A dep row
carries `source_program` beside `source`, because at a `LINK` return the caller is credited
with bytes named in the callee's address space. A dep row whose origin is `LITERAL` carries the
literal as written in `literal` (`'Y'`, `SPACES`); the field is empty for every other row and for
`INITIALIZE`, which writes no literal of its own.

A dep row with a `sink` records bytes leaving the program, and its `target` is null. Its
`source` is what went out, and its definers are read after the statement's own writes:

| Statement | `source` | `sink` |
|---|---|---|
| `WRITE`/`REWRITE` record | the record area | `FILE:<select name>` |
| EXEC CICS `WRITE`/`REWRITE FROM` | `FROM` | `FILE:<file>` |
| EXEC CICS `SEND MAP` | `FROM`, or the map's `<map>O` record; nothing under `MAPONLY` | `MAP:<map>` |
| EXEC CICS `WRITEQ TS FROM` | `FROM` | `TSQ:<queue>` |
| EXEC CICS `WRITEQ TD FROM` | `FROM` | `TDQ:<queue>` |
| EXEC CICS `START FROM` | `FROM` | `TRANSID:<transid>` |

Progress goes to stderr, one line per path: nodes run, cumulative branch coverage, queue
sizes, programs entered and dead ends met, then the reason the run stopped.

## cobble-trace-query

```
cobble-trace-query {forward,backward} FIELD --trace TRACE [--depth N] [--extents EXTENTS]
```

| Flag | Meaning |
|---|---|
| `forward` / `backward` | what FIELD affects, or what feeds it |
| `FIELD` | a field name, or `PROGRAM.FIELD` |
| `--trace` | the trace file; a partial file with no footer is read as far as it goes |
| `--depth` | hops to follow (default 5) |
| `--extents` | an extents table, for a field no dep row names |

Matches by byte-extent containment within a program and deduplicates on load. The backward
walk narrows at each hop: when a dep's target is a group wider than the range being traced,
the source is clipped to the overlapping sub-range. Output is an indented tree, one line per
provenance edge, with origins (`FILE:`, `LITERAL`, `%CALL:`) at the backward leaves and
sinks at the forward ones.
