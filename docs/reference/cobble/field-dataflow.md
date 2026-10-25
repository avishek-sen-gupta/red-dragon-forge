# cobble: field dataflow

Byte-level dataflow over every field, from the ASG cache, with no JVM. Every stage below that
reads the cache, except `cobble-depgraph`, reads only a member's first program, the one the
member is named for; a batch or contained program after it is not analysed
(red-dragon-forge-1yoa). The stages:

1. `cobble-extents` writes every member's declared field layout.
2. `cobble-dataflow-fixpoint` settles each program alone: which writes reach each read, the
   values a field can hold, and the candidates at each dynamic call or CICS file site.
3. `cobble-dataflow-combine` links those results across programs.
4. `cobble-dataflow-fixpoint-query` answers questions over the output.

`cobble-dataflow-area-need`, `cobble-dataflow-fixpoint-diagnose`, the access commands and the
name-level `cobble-depgraph` are described after them.

Code: `cobble/cobble/dataflow/layout.py` (byte extents), `dataflow/fields/` (extents, transfer
functions, state, values, aliases, traces, accesses), `dataflow/fixpoint/` (solver, corpus run,
targets, query, area need), `dataflow/combine/`, `dataflow/depgraph/`.

## Extents

An extent reads `NAME@region[start:end]`. A trailing `~` marks a clamped range: a computed
subscript lands somewhere inside it. A field id is `<program>.<field>`. Synthetic origins
(`<program>.LITERAL`, `FILE:<name>`, `%CICS-STATE`, `%CALL:<target>`) are not storage.

## cobble-extents

```
cobble-extents --asg-dir ASG_DIR --out OUT [--max-workers N] [MEMBER ...]
```

| Flag | Meaning |
|---|---|
| `--asg-dir` | the ASG cache |
| `--out` | the extents table to write |
| `--max-workers` | worker processes (default 4). Output is in member order whatever the count |
| `MEMBER` | members to emit; default every `*.json` in the cache |

One row per declared name: `id`, `level`, `usage`, `extents` (one per occurrence, so `OCCURS`
gives several), `program`, then arrays parallel to `extents` holding each occurrence's record,
qualification, start, length, level, PIC, usage, `REDEFINES`, `OCCURS`, subscripts, `VALUE`
and parent, plus the record's origin and size. The fixpoint and the queries read their layout
from this table; `cobble.dataflow.fields.extents_input` is its reader. Run it again whenever
the ASG cache changes.

## cobble-dataflow-fixpoint

```
cobble-dataflow-fixpoint --asg-dir ASG_DIR --out-dir OUT_DIR --extents EXTENTS
    (--member NAME [NAME ...] | --all)
    [--iteration-factor N | --sweeps N] [--min-coverage F]
    [--call-targets-only [--narrow-areas FILE]] [--force] [--max-workers N]
```

| Flag | Meaning |
|---|---|
| `--asg-dir` | the ASG cache |
| `--out-dir` | output directory |
| `--extents` | the table `cobble-extents` wrote. Required |
| `--member`, `--all` | exactly one is required. A named member the cache lacks is exit 2 |
| `--iteration-factor` | worklist budget: dequeues allowed per CFG node (default 150) |
| `--sweeps` | run reverse-postorder passes instead, at most N. Exclusive with `--iteration-factor` |
| `--min-coverage` | floor for the fraction of writes resolved to storage (default 0.60) |
| `--call-targets-only` | keep only entries a dynamic call target, a dynamic file name or a handed-over area depends on |
| `--narrow-areas` | with `--call-targets-only`: of each handed-over area, track only the bytes the area-need file says some program reads |
| `--force` | discard every finished member directory and analyse again |
| `--max-workers` | worker processes (default 4) |
| `--max-rounds` | stop after N rounds even if the need has not settled (default 0: until it settles). A capped run warns how many members were still to walk; its need can miss bytes that only arrive through longer call chains, and a fixpoint narrowed by it can then miss candidates the settled need would keep |

The walk runs over each program's CFG from `program_cfg`, seeded from the `VALUE` image of the
member's records. Before walking, it removes a paragraph end's `FALLTHRU` edge unless control
can reach that end where it falls through. A program keeps every edge when it has a `GO TO`,
an `ALTER`, a `PERFORM` of an undeclared target, an inverted or undeclared `THRU` end, or a
`HANDLE CONDITION`/`HANDLE ABEND LABEL` naming a missing paragraph. `DECLARATIVES` are not in
the graph. Only the fixpoint's copy of the CFG is pruned.

An exact write removes every entry it fully covers. An exact write into part of an exact entry
splits it: the untouched bytes keep their writers and values. Nothing is split where either
side is clamped; the entry keeps its writers and its values become `not-a-literal`.

The transfer models `MOVE`, `INITIALIZE`, arithmetic, `COMPUTE`, `STRING`, `READ`, `CALL`,
`EXEC CICS` and `WRITE`/`REWRITE ... FROM`, which moves the `FROM` operand into the record
area. Any other statement that writes storage (`ACCEPT`, `UNSTRING`, `INSPECT`, `SET`,
`SEARCH`, the `CORRESPONDING` forms, `XML GENERATE`) is a weak
write of the names its CFG node lists: it adds a definer, removes nothing, and adds the reason
`unmodelled`. `EXEC SQL ... INTO` and `FETCH ... INTO` are not modelled.

The graph is intra-program. A `CALL` or `LINK` contributes a `%CALL:<target>` source;
`aliases.jsonl` states which bytes the site shares with its callee.

### Budgets

The worklist stops a member at `dequeue cap N reached`. Such a member is published unsettled:
its flows are a subset of the program's, it is named in a warning, it counts as `unsettled`
in the summary, and its call targets carry `incomplete-walk`. The heartbeat estimates the
remaining work from the queue's drain rate; `past the N cap` means raise the factor.

`--sweeps N` stops early on a pass that changes nothing, and then the member is settled.
A member still growing after N sweeps is unsettled, as above. Two is the useful floor: one sweep
misses what a loop body wrote for every reader after the loop. Settling takes one sweep more than
finding, since only a sweep that changes nothing settles a member: a loop's write is found on the
second sweep and the member is settled on the third. A paragraph `PERFORM`ed from two places is a
back edge too.

### Output

| File | One row per | Holds |
|---|---|---|
| `graph.jsonl` | `FIELD` endpoint, and `(node, source extent, target extent)` | node rows carry only the id; edge rows are `FLOWS_TO` with the `node` that moved the bytes |
| `defs.jsonl` | `(program, node, source extent)` read that feeds a write | `definers` (statements whose writes reach the read; empty for a `VALUE` or nothing), `values` (quoted literals only), `reasons` |
| `aliases.jsonl` | call site and caller window | `caller_extent` and `callee_extent` of the shared window, or the reason none is shared and the callee it stopped on |
| `targets.jsonl` | dynamic `CALL`/`XCTL`/`LINK` site, and dynamic CICS file site | `caller`, `node`, `kind` (`program` or `file`), `transfer`, `expression`, `candidates`, `reasons`, `dropped` (values that cannot name a program, or a CICS file); a file row also carries `operand`, its operand's fact (`extent`, `values`, `writers`, `reasons`), which the combine walks back from |
| `jumps.jsonl` | jump, exit, `RETRIEVE` and entry | what it hands over: target, transaction id, areas |
| `members/<MEMBER>/` | finished member | that member's five tables and `counts.json` |

The human report goes to stderr; a JSON summary goes to stdout. The summary carries
`analysed`, `writes`, `covered`, `coverage`, `unhandled`, `unmodelled`, `skipped`,
`unsettled`, `collisions`, `aliased` (sites) and `alias_dead_ends` (by reason).
A write to a name with no memory definition, such as a record whose copybook was never
delivered, is not tracked: it counts in `writes` but not `covered`, and the analysis logs a
warning naming the program, the statement's node and the name.

An edge names the smallest declared field covering the bytes it moved, so a group write leaves
its children out of the graph. Join on byte ranges, not ids; the query does.

### Exit status

| Exit | Meaning |
|---|---|
| 0 | every member analysed, coverage at or above the floor |
| 1 | coverage below the floor |
| 2 | ASG directory or extents table not found, or a `--member` the cache does not hold |
| 3 | a member skipped, unreadable, or sharing a non-empty `PROGRAM-ID` with another |

A member the extents table lacks is a recorded skip naming the command that fixes it.

### Resume

Each finished member is renamed into place as `members/<MEMBER>/`. A rerun reuses those
directories and analyses only the rest. The corpus files are rebuilt from the selected members'
directories once every member is done, so an interrupted run leaves the previous corpus files
unchanged. A `--member` run publishes only its members. Nothing checks that a member directory
came from the same `--sweeps`, cache or extents table; use `--force` after changing any of them.

An out-dir holds one scope. Switching between a whole run and `--call-targets-only` stops and
asks for `--force`. `cobble-dataflow-fixpoint-query` refuses a call-targets-only out-dir.

### Call-targets-only

Before each member's walk, a backward liveness pass finds what later reads need: every dynamic
call target, every dynamic file name, every handed-over area, and the `LINKAGE` areas read at an exit or a CICS
`RETURN`. Entries that overlap nothing live are dropped. `targets.jsonl`, `jumps.jsonl` and the
combine's results equal a full run's; `graph` and `defs` keep only rows for writes that are
live afterwards. `counts.json` records `scope`, `tracked` and `relevant`.

### Dynamic call targets

A site gets a `targets.jsonl` row when its transfer is `CALL`, `EXEC CICS XCTL` or
`EXEC CICS LINK` and its program operand is a data item. A literal target is an ordinary edge.

| Form | Resolved through |
|---|---|
| `CALL WS-PGM` | the bytes of `WS-PGM` |
| `CALL WS-PGM OF WS-REC` | the qualified field's bytes |
| `CALL WS-LONG(9:8)` | exactly the reference-modified bytes |
| `CALL WS-PGMS(I)` | every occurrence the subscript can reach |
| `USING`, `RETURNING`, `ON EXCEPTION` phrases | as the bare form |
| `XCTL`/`LINK PROGRAM(WS-PGM)` | as `CALL WS-PGM` |

A value is trimmed of trailing spaces. A candidate is any printable value; it is not checked
against the corpus's program names.

| Reason | Raised when |
|---|---|
| `uninitialised` | some path reaches the site with no write to those bytes and no `VALUE` |
| `not-a-literal` | a write whose content the walk cannot name |
| `from-file` | the bytes came from a `READ` or a CICS file command |
| `from-callee` | the bytes are a `LINK`/`XCTL` commarea a callee may have written back |
| `inbound-linkage` | the bytes are in `LINKAGE`, written by a caller |
| `no-extent` | the operand has no byte range |
| `over-budget` | more than 32 values reached it; the first 32 in sorted order are kept |
| `incomplete-walk` | the member did not settle |
| `unmodelled` | a statement with no transfer of its own may have written the bytes |
| `hop-limit` | combine only: a walk stopped at `--max-hops` crossings |
| `readback-skipped` | combine only: `--skip-readbacks` left a `LINK` write-back unfollowed |

A CICS file statement gets a row of kind `file` when its file is named by a data item:
`READ`, `STARTBR`, `READNEXT`, `READPREV`, `WRITE`, `REWRITE`, `DELETE` or `ENDBR` with
`FILE(...)`, or `DATASET(...)` (its older synonym) when `FILE` is absent. `transfer` is the verb
(`CICS_READ`). A literal file is no row. A candidate is a printable value of at most eight
characters, the CICS limit on a file name; a longer one goes to `dropped`. The reasons are the
same as for a call target. The run report counts file sites on a line of their own:
`fields: N dynamic file sites, N resolved to one file, N to several, N to none`.

The bridge does not serialise nested programs, so a `CALL` inside a nested `PROGRAM-ID` is not
seen.

### Alias reasons

| Reason | Kind | Meaning |
|---|---|---|
| `no-commarea-operand` | fact | the call passes no `COMMAREA` |
| `callee-declares-no-commarea` | fact | the callee has no `DFHCOMMAREA` in `LINKAGE` |
| `empty-window` | fact | the shorter of the two areas is zero bytes |
| `argument-is-not-a-field` | fact | a `CALL ... USING` argument is a literal or `OMITTED` |
| `callee-declares-no-parameter-there` | fact | the callee's `USING` has no parameter at that position |
| `dynamic-target` | limit | the target is a field |
| `callee-not-in-cache` | limit | the ASG cache has no file for the target |
| `caller-field-unknown` | limit | the `COMMAREA` operand names nothing in the member's layout |
| `parameter-not-in-linkage` | limit | the callee's `USING` names a parameter its `LINKAGE` lacks |
| `unreadable` | limit | the callee's cache file would not parse |
| `unsizeable` | limit | the callee's `LINKAGE` layout never built |
| `alias-phase-failed` | limit | the phase failed on this member before reaching any site |

`callee` is blank when the target is a field.

## cobble-dataflow-combine

```
cobble-dataflow-combine --config CONFIG --fixpoint-dir DIR --out-dir DIR (--all | --member NAME [NAME ...])
    [--max-hops N] [--skip-readbacks]
```

| Flag | Meaning |
|---|---|
| `--config` | the corpus config: `csd_files` map transaction ids to programs; `asg_dir` supplies callees outside the linked set |
| `--fixpoint-dir` | a fixpoint `--out-dir` |
| `--out-dir` | where `targets.jsonl` and `links.jsonl` go |
| `--all` | link every program with results |
| `--member` | link only these (case-insensitive). One with no results refuses the run |
| `--max-hops` | program crossings one walk may make: into a caller, into a `LINK`ed callee's exits, or into a `START`er. A walk that would cross more stops there, keeps what it found, and its target gains `hop-limit`. Default: no limit. Each walk is then bounded by the programs within N crossings, not by the corpus |
| `--skip-readbacks` | do not walk into a `LINK`ed program for bytes it may have written back. Those bytes give `readback-skipped` |

Lets values cross programs, in rounds, until the set of links stops growing. Where a target
field lies inside the bytes handed over on a link, those bytes hold the callee's name. A target
with a computed subscript keeps the fixpoint's own candidates. A missing config, `members/`
directory or cache is exit 2, writing nothing.

| File | Row | Holds |
|---|---|---|
| `targets.jsonl` | dynamic site | the fixpoint's row after linking, plus `outside`: programs outside the linked set known to jump into the caller. A file site's name is answered across links the way a call target is, so a file name handed over in a commarea resolves |
| `links.jsonl` | link used | `caller`, `node`, `transfer`, `callee`, `caller_extent`, `callee_extent`, `returns`, `discovered` (exists only because linking resolved its target) |

The run report goes to stderr. `cobble-build --dynamic-call-targets` and
`cobble-srccfg-build --dynamic-call-targets` read this `targets.jsonl`.

Each round walks back from every jump's target bytes, through copies within a program and across
links. A place is a program, a node and a byte range, told apart by its bytes alone, so the same bytes
under a group, elementary or `REDEFINES` name are one place. Every place is answered once per
round, and within a program once per run, however many walks reach it. The progress log names
the jump being answered and how many places are done.

On a large corpus the walks across links can join into one cyclic group spanning most of the
corpus, and the unlimited run may not finish. Pick `--max-hops` by raising it until
`targets.jsonl` and `links.jsonl` stop changing between N and N+1. Within one round, a target
without `hop-limit` is what the unlimited walk gives over the same links. Across rounds it may not
be: a cut walk can miss a program name, the link to that program is then never found, and walks
that would have crossed it see fewer callers without being marked. Comparing N with N+1 catches
that too. Each extra hop costs more than the last.

## cobble-dataflow-fixpoint-query

```
cobble-dataflow-fixpoint-query QUERY SUBJECT --fixpoint-dir DIR --extents EXTENTS
    [--depth N] [--across-calls [--max-hops N] [--links LINKS]]
```

`QUERY` is one of `extents`, `writers`, `readers`, `reaches`, `reached-by`, `contains`,
`within`, `overlapping`. `SUBJECT` is a field name, or `PROGRAM.FIELD`.

| Flag | Meaning |
|---|---|
| `--fixpoint-dir` | a whole-scope fixpoint `--out-dir` |
| `--extents` | the extents table the fixpoint read |
| `--depth` | flows `reaches`/`reached-by` follow (default 6) |
| `--across-calls` | let `reaches`/`reached-by` cross a commarea window into the callee. Refused on the other queries |
| `--max-hops` | crossings per route (default 3) |
| `--links` | read the combine's `links.jsonl` in place of `aliases.jsonl`, so the walk also crosses links the combine resolved |

Every predicate intersects byte ranges within one program. `overlapping` is the only one that
reports partial overlap. `reaches` and `reached-by` follow statement order: each step goes to
a move that can see the previous one's result, by `defs.jsonl`. A literal or file read ends a
chain.

With `--across-calls`, `LINK` and `CALL ... BY REFERENCE` windows carry write-backs home;
`XCTL`, `BY CONTENT` and `BY VALUE` are inbound only. Each landing prints its bytes, `hops`
and `via` (the last site crossed). The answer lists landings only; where the analysis gave up
is in `aliases.jsonl` and the summary's `alias_dead_ends`.

Field names go to stdout only; the log on stderr is safe to share. The extents table is
streamed, so memory stays near one program's declarations.

## cobble-dataflow-area-need

```
cobble-dataflow-area-need --asg-dir DIR --extents EXTENTS --out OUT [--max-workers N] [--max-rounds N]
    [--config CONFIG] [--fixpoint-dir DIR --combined-dir DIR]
    [--sites FILE] [--explain MEMBER] [--explain-over BYTES]
```

One row per member: which bytes of its commarea or `USING` areas its call targets read on
entry (`entry`), and which its callers read back after it returns (`back`). The output feeds
`cobble-dataflow-fixpoint --call-targets-only --narrow-areas`, which refuses an older format.

| Flag | Meaning |
|---|---|
| `--config` | the corpus config the combine reads. Its CSD maps a `RETURN TRANSID` or `START` transaction to a program. Without it no transaction resolves |
| `--fixpoint-dir`, `--combined-dir` | add the sites a finished fixpoint and combine resolved completely |
| `--sites` | after loading, write every dynamic site as JSONL: its operand, how its own program resolved it or why not, and every write to the operand |
| `--explain` | after the rounds, write a JSONL row to stdout for MEMBER: what each demand source accounts for, and the writes that make more live than their target keeps |
| `--explain-over` | the same for every member needing at least BYTES on entry |
| `--max-workers` | worker processes (default 4) |
| `--max-rounds` | stop after N rounds even if the need has not settled (default 0: until it settles). A capped run warns how many members were still to walk; its need can miss bytes that only arrive through longer call chains, and a fixpoint narrowed by it can then miss candidates the settled need would keep |

A call naming its program by a literal is charged with that callee's row; a callee not in the
corpus is charged every byte. A `START` hands over its `FROM` area like a `LINK` hands over a
commarea. A dynamic `XCTL`, `LINK`, `CALL`, `RETURN TRANSID` or `START` resolves within its own
program when every definition reaching it overwrites all of it with a literal, or is the
program's own storage that no write reached. A resolved site is charged with the programs it
reaches. Any other dynamic site is charged with the union over every member for that kind of
area. A byte-for-byte `MOVE` counts only the bytes it copies. Liveness reruns in rounds until no
row changes: the first walks every member, each later one only the members whose callees' entry
rows, own back row, or -- with a site nothing resolved -- union of every member's entry need
changed. That reaches the same rows as walking every member every round. The log's round line
says how many were walked and how many come next.

## cobble-dataflow-fixpoint-diagnose

```
cobble-dataflow-fixpoint-diagnose --asg-dir DIR --member MEMBER
    [--max-steps N] [--every N] [--call-targets-only [--narrow-areas FILE]] [--anonymise]
```

Walks one member as the fixpoint does, stopping after `--max-steps` dequeues (default 50000),
and reports: the most-dequeued nodes and how often a dequeue grew a successor, the cycle each
sits in, the fields that keep gaining writers, the tallest writer sets, and a timeline every
`--every` steps (default 5000). `--anonymise` replaces paragraph and field names with stable
aliases (`PARA-001`, `FIELD-001`). `--narrow-areas FILE`, with `--call-targets-only`, walks the member as
`cobble-dataflow-fixpoint --narrow-areas FILE` does, tracking only the handed-over bytes the
area-need file says some program needs.

## cobble-fields-access

```
cobble-fields-access --cfg CFG --asg-dir DIR --out OUT
```

Every site in a CFG file that reads a field, with the bytes it reads: one `access` row per site
and extent.

## cobble-access-query

```
cobble-access-query FIELD --accesses ACCESSES --extents EXTENTS
```

The access sites for a field, by name and by overlapping bytes.

## Name-level dependency graph

### cobble-depgraph

```
cobble-depgraph --config CONFIG [--limit N]
```

Which variables feed which, by name, over every program of every member in the ASG cache.
Reads a depgraph config (see [config](config.md)). `--limit` stops after N members. Writes to
`graph_dir`:

| File | Holds |
|---|---|
| `edges.jsonl` | one row per edge: `src`, `dst`, `program` (the member), `seq` (the statement ordinal), `verb` |
| `nodes.jsonl` | one row per name: where it is declared, whether it is pass-through, the programs it appears in |
| `pairs.json` | `edges.jsonl` deduplicated: `src`, `dst`, `count`, per-verb `verbs` |

It prints a `CONDUIT CANDIDATES` table. One round of tuning is: run, read the table, add the
names that are conduits to `passthrough_names`, run again.

### cobble-depgraph-render

```
cobble-depgraph-render --config CONFIG [--min-degree N]
```

Writes `graph_dir/depgraph-webgl.html` from `nodes.jsonl` and `pairs.json`, laid out with
`sfdp`. Nodes are coloured by where they are declared (`WORKING-STORAGE`, `FILE`, `LINKAGE`,
`<undeclared>`) or by external kind (`DATASET`, `MAP`, `PROGRAM`, `TSQUEUE`, `TRANSID`); edges
by verb family. `--min-degree` drops variables with fewer edges (default 1, keep all).

## cobble-trace-query

```
cobble-trace-query {forward,backward} FIELD --fixpoint DIR [--links LINKS] [--depth N] [--extents EXTENTS]
```

| Flag | Meaning |
|---|---|
| `forward` / `backward` | what FIELD affects, or what feeds it |
| `FIELD` | a field name, or `PROGRAM.FIELD`; a program the out-dir holds no member for exits 2 |
| `--fixpoint` | the out-dir `cobble-dataflow-fixpoint` wrote; every finished member's `FLOWS_TO` edges, reaching definitions and sinks are read |
| `--links` | `links.jsonl` from `cobble-dataflow-combine`; each window carries the walk into the callee, and back when the call returns. Without it the walk stays in each program |
| `--depth` | hops to follow (default 5) |
| `--extents` | an extents table, for a field no row names |

Matches by byte-extent containment within a program and deduplicates the rows. The backward walk
narrows at each hop: when a row's target is a group wider than the range being traced, the source is
clipped to the overlapping sub-range. Output is an indented tree, one line per provenance edge, with
origins (`FILE:`, `LITERAL`, `%CALL:`) at the backward leaves and sinks at the forward ones. The rows
are the fixpoint's, merged over paths, so the walk shows every flow the analysis found, not the paths
that carried them; a run capped with `--sweeps` that did not settle shows a subset.
