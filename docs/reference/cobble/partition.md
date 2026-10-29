# cobble: field partitions (experimental)

**Experimental.** The commands and file shapes on this page can change without notice.

Field partitions group the fields of a program that exchange bytes. The partition graph marks
which of its edges group fields (`clustered`), and the render's components are the fields those
edges connect inside one program: a candidate for one domain concept split across several fields,
such as a customer's name moving between the screen, the commarea, the record and its update
copy. Grouping across programs is the aggregates pipeline's job ([aggregates](aggregates.md)).

Code: `cobble/cobble/experimental/partition/`.

## Make targets

From the forge root. Each target runs the one before it.

| Target | Does |
|---|---|
| `partition-traces` | `cobble-parse-corpus`, `cobble-extents`, `cobble-dataflow-fixpoint --all --sweeps $(PARTITION_SWEEPS)`, `cobble-dataflow-combine --max-hops 5` |
| `partition-graph` | `cobble-build` (the knowledge graph), then `cobble-experimental-partition-graph` |
| `partition-render` | `cobble-experimental-partition-render` |

| Variable | Default | Meaning |
|---|---|---|
| `PARTITION_CONFIG` | `config/carddemo-partition.toml` | the corpus config, relative to `cobble/` |
| `PARTITION_ASG` | `out-partition/asg` | the `asg_dir` that config names |
| `PARTITION_DIR` | `out-partition` | where every artefact goes |
| `PARTITION_SWEEPS` | none; required | `--sweeps` for the fixpoint |
| `PARTITION_BARRIER`, `PARTITION_FANOUT` | `fanout`, `8` | the barrier, below |

The CardDemo config parses into its own cache, so a cache written before a bridge change is
never read. `PARTITION_DIR` then holds `extents.jsonl`, `fixpoint/`,
`combine/`, `knowledge-graph.jsonl`, `graph.jsonl` and `render/`.

## cobble-experimental-partition-graph

```
cobble-experimental-partition-graph --extents EXTENTS --fixpoint DIR --out OUT
    [--links LINKS] [--knowledge-graph GRAPH] [--targets TARGETS]
    [--barrier {none,fanout}] [--fanout-limit N]
```

| Flag | Meaning |
|---|---|
| `--extents` | the table `cobble-extents` wrote |
| `--fixpoint` | the out-dir `cobble-dataflow-fixpoint` wrote; each finished member's `FLOWS_TO` edges, reaching definitions and sinks are read one member at a time |
| `--links` | `links.jsonl` from `cobble-dataflow-combine`. Without it, no edge crosses a program |
| `--knowledge-graph` | the graph `cobble-build` wrote. Without it there are no dataset links and the graph is the one the fixpoint's provenance and the links alone give |
| `--targets` | `targets.jsonl` from `cobble-dataflow-combine`, for the CICS file names. Without it batch sites still link and every CICS file site is unresolved |
| `--barrier`, `--fanout-limit` | which crossings clustering does not cross (default `fanout`, 8) |
| `--out` | the graph JSONL |

It reads only the extents rows of the programs the provenance rows and links name, streaming the
file and logging how many rows it kept. It logs each fixpoint member it reads, and a progress line
every 1000 dep rows and links it works through, and one when each
run over them is done; with a knowledge graph, it also logs the dataset sites by certainty and the slots and
dataset edges added.

A node is an elementary field: one with nothing declared under it, so every variant of a
`REDEFINES` has its own fields, named `<program>:<record>.<field>`. Each occurrence of an `OCCURS`
table element is a node of its own, with its subscripts from the extents table:
`COMEN01C:DFHCOMMAREA.LK-COMMAREA(9)`, `X(2,5)` for a nested table. A handover into a byte table
in linkage and the `MOVE` out of it then keep each byte apart, so the caller's `CDEMO-USER-ID`
reaches the callee's `CDEMO-USER-ID` through occurrences 25 to 32 and not through one node every
commarea field shares. A computed subscript reaches every occurrence it may hit. Each program's origins and sinks
([field-dataflow.md](field-dataflow.md#extents) lists the kinds) are nodes of their own, with id
`P|origin|<text>` or `P|sink|<text>` and the typed value in the node's `origin` or `sink` field
(`{"kind": "NONE", ...}` on every other node). Ids are opaque keys: read the field, not the id. A
literal origin is one node per literal as written, `P|origin|LITERAL:'Y'` apart from
`P|origin|LITERAL:SPACES`, so a program's literals do not meet in one hub. `SPACE` and `SPACES`
stay two nodes.

A dep row's range resolves to the elementary fields declared under the field it names that
overlap its bytes. A source range also takes the fields its definers wrote, when a definer's
write lies inside the range: `SEND MAP FROM(COTRN0AO)` reads `TDATE03I`, which shares its bytes,
when a `MOVE` to `TDATE03I` reached it. A definer that copied into one undivided field, such as a
`PIC X(500)` record, is followed back through its own source and definers, so the read takes the
fields that filled those bytes. A named field whose bytes such fields cover drops out. Each range
and its definers is followed back once and the answer reused, so the cost grows with the number of
copies, not the number of paths through them. Where copies feed each other in a loop, the walk
stops at a copy already on its way back, and the first read to reach a range fixes its answer for
every later read: a later read may keep the declared undivided field where it would have taken the
finer fields that came round the loop. A write to
a whole record contributes nothing to a read of part of it, so one record type of a `REDEFINES`
never picks up another's fields. Edges then run from source fields to target fields:

| Fields on each side | Edges |
|---|---|
| one on either side | every source to every target |
| several on both | byte-aligned: each target field from the source fields at the same offsets |

A combine link binds the caller's window to the callee's the same way, and binds them back when
the link returns. An edge records how many sites move bytes along it, whether clustering crosses
it, the barrier that decided that, and whether it joins two programs. It also records where the
bytes land: each alignment is `{"source", "target", "length"}`, `length` bytes from offset `source`
in the source field to offset `target` in the target field, the distinct placements over all its
sites. A dep's placement comes from the fixpoint's `landing`, clipped to the bytes actually read
and written; a source field none of whose bytes land in the target gets no edge. `aligned` is true
when every site's placement is known; a statement that rewrites the bytes (arithmetic, STRING, a
conversion between usages or into an edited picture), a move through a clamped extent, and every
origin and sink edge, have none. `rebuilt` is true when every site's statement built the target's
value in place (arithmetic, STRING); unify does not count such an edge as an unplaced copy. A field node carries its `size` in bytes.

The graph file is a flat list, one object per line: every node as `{"node": {...}}`, then every
edge as `{"edge": {...}}`.

### Dataset links

With `--knowledge-graph`, every file statement the fixpoint's provenance names is resolved to the dataset it
reads or writes, and writers and readers of one dataset are linked through it.

| Site | Resolved through |
|---|---|
| batch | its SELECT's DD name (`PROGRAM -READS/WRITES{select_name}-> COBOL_FILE`), then each JCL step that runs the program, directly or through `CALL`s: that step's DD statement of the same name gives the DSN |
| CICS | the `kind: file` row of `--targets` for the same program and node: each candidate file name, then the CSD's `DEFINE FILE ... DSNAME` |

A dataset is its DSN; a CICS file the CSD gives no DSN is its file name, so CICS programs sharing it
still link but no batch program reaches it. Each dataset's record is cut at every field boundary
any of its sites uses, offsets measured from the start of the bytes read into or written from, and
each piece is a `dataset` node, `<DSN>[start:end]`, of no program. A write site's fields link to
the slots their bytes cover and the slots link to a read site's fields, with byte alignments like
any field edge. A writer's `ACCT-ID [0:11]` and a reader's `GRP [0:5]` and `SEQ [5:11]` meet in
`[0:5]` and `[5:11]`.

Every dataset edge has a `certainty`:

| `certainty` | `reasons` | When |
|---|---|---|
| `exact` | none | one candidate or DD binding, no doubt from the dataflow, an exact record extent, one layout over the slot's bytes |
| `possible` | `candidates` | a CICS site with several candidate files: one link per candidate |
| `possible` | the target's reasons, e.g. `incomplete-walk` | the dataflow could not vouch for the file name |
| `possible` | `call-candidate` | the program runs in a step only through a dynamic call it may not make |
| `possible` | `clamped` | the record extent is clamped |
| `possible` | `overlapping-layouts` | the field overlaps another field of the same site in that slot (`REDEFINES`, several record types) |

A `possible` edge has no alignments. A site that resolves to no dataset keeps a slot of its own,
`<program>/<node>|?<name>`, and links nothing else: `uninitialised` (no candidate file name),
`no-step` (no JCL step runs the program), `dd-unbound` (the step has no such DD), or
`unresolved-file` (neither a file target nor a SELECT). Dataset edges are never clustered, so
components stay inside one program.

### Barriers

A barrier judges the field pairs one statement links. A blocked statement's edges stay in the
graph, drawn red, and components do not cross them.

| Barrier | Blocks |
|---|---|
| `none` | nothing: components over the raw graph |
| `fanout` | a statement in which one field is linked to more than `--fanout-limit` other declared fields, a table's occurrences counting as one: a record written from an undivided `PIC X(n)` area, a commarea saved whole, a report line assembled from many fields |

At 8 on CardDemo, a date or phone number assembled from its parts stays clustered, a commarea
handed over through a linkage byte table stays clustered byte by byte, and a commarea saved whole
(`WS-COMMAREA`), the export record and the report lines are blocked. A concept wider than the limit, such as a
13-part timestamp, splits into its parts.

## cobble-experimental-partition-render

```
cobble-experimental-partition-render --graph GRAPH --out OUT
```

`--out` is a directory, created if missing, every file overwritten:

| file | what it is |
|---|---|
| `index.html` | the program map |
| `programs/<PROGRAM>.html` | one page per program, of its neighbourhood |
| `scripts/graphology.umd.min.js`, `scripts/sigma.min.js`, `scripts/graphology-library.min.js` | the vendored builds, written once; every page loads them by relative `src` |

The graph is read one line at a time, logging every tenth of the lines, into slotted records, and
indexed once by node and by program, so no step scans the whole graph per program or per slot.

**The program map** has one node per program and one per dataset record, sized by how many graph
nodes it holds, and an edge between two of them when some graph edge links their nodes, thicker for
more such edges. It is placed by a seeded weighted networkx `forceatlas2_layout` with strong gravity,
then graphology's noverlap layout runs in the page so no two dots overlap. Clicking a program opens
its page; dragging a node moves it; hovering a node or searching its name (Enter) shows what it
links to, with link counts.

**A program's neighbourhood** is its own fields, origins and sinks; every node one edge from those;
and, for each dataset slot among them, every node one edge from that slot, so following a dataset
still shows all its writers and readers. It keeps every edge with both ends inside. The run logs
each page as it is written, with its program, node count and the time left, then the largest
neighbourhood.

Each program page draws its neighbourhood with the sigma.js and graphology builds cobble vendors, dark on
light. The render only places each program's patch, sized from its field count, and starts its
fields evenly inside it; the page lays each patch out when it is opened, by graphology's
ForceAtlas2 (Barnes–Hut above 500 fields, strong gravity, sizes adjusted) over the edges among the
patch's nodes, so linked fields pull together and dots keep apart, then scales the patch back inside
its radius.
The patches are placed by a seeded `spring_layout` over what links the programs, call handovers
and datasets they share, and pushed apart until none overlap, so programs that exchange bytes tend
to sit near each other. A dataset slot sits at the mean of the fields it links, jittered. A
component is the connected component of a field over clustered edges inside its program, worked out
from the graph alone. The page folds a run of consecutive occurrences of one table element that
share a component and have exactly the same edges into one drawn node, `LK-COMMAREA(9:16)`, whose
edges carry the largest site count among the edges they stand for; selecting it lists the
occurrences. Only the page folds: `graph.jsonl` keeps every occurrence. Dot sizes are in layout units, so they keep their spacing when zoomed out.
Labels show only for a hovered node and its neighbours, or for a clicked field and its neighbours; the rest of its component stays highlighted, unlabelled. Colour shows the
component. The side panel lists components or datasets. Clicking one zooms to it and lists its
fields and terminals. Hovering a
node shows its edges. Edges are grey when clustered, pale orange when they cross programs, and red
when a barrier blocked them. Dataset slots are blue dots in the outer rings. Dataset edges are not drawn until the "dataset links"
box is ticked, which draws every dataset's edges, or a dataset is followed: pick it in the `datasets` list (largest first, with its field and program counts), click
one of its slots, or type its name in search and press Enter. Following a dataset fades every other
node to light grey with no edges, draws its own edges (blue when `exact`, pale blue when `possible`) and opens its record layout
over the graph: one row per slot in byte order, one column per program, each cell the fields that
write (`→`) or read (`←`) those bytes, a `possible` one in grey with its reasons on hover. The side
panel lists the fields by program and every dataset edge with its certainty and reasons. In the `datasets`
view, clicking a field follows a dataset it touches; clicking a field no dataset touches switches
to `components` and selects its component.

`tests/experimental/partition/page_driver.py` drives a rendered page in headless Chromium
(Playwright): it loads it, checks for script errors, lists the datasets, follows the first and
searches for it, and reports what each step showed. The render tests run it on a small graph; it
can be pointed at any rendered page.

## cobble-experimental-partition-file-sites

```text
cobble-experimental-partition-file-sites --fixpoint FIXPOINT --knowledge-graph GRAPH --targets TARGETS
```

A diagnostic over the graph's dataset inputs, without building the graph. It logs how many file
sites a CICS file target resolves and how many a `SELECT` does, then the `unresolved-file` ones
under the first gap that explains each, with three examples: `target-not-file` (a target sits at
the site but names a program), `file-targets-at-other-nodes` (the program has file targets, none at
this site), `selects-under-other-names` (the program has `SELECT`s, not this one),
`only-non-file-targets` (the program has only program targets), `program-unknown` (neither table
names the program). On CardDemo all 181 sites resolve: 37 by a CICS file target, 144 by a `SELECT`.

## cobble-experimental-partition-copies

```text
cobble-experimental-partition-copies --graph GRAPH --extents EXTENTS --width N --start 'NODE_ID' [--start 'NODE_ID' ...]
```

Quote each id: a file slot such as `AWS.M2.CARDDEMO.CARDDATA.VSAM.KSDS[0:16]` is a glob to the shell.

Every place holding all `N` bytes of a value, followed byte by byte through `graph.jsonl` from each
start's offset 0. The walk goes forward to every copy, through buffers of any size, then back from
each copy no wider than the value to what fed it, never entering a wider field (where other values
share the bytes). `rebuilt` edges are not followed. A field and the field it directly `REDEFINES`
(from `extents.jsonl`) are one location; sibling record variants that only share bytes are not. A
file slot reached on the way starts the walk again. Prints one line per program, file slots first,
each place as its id plus `+base` when the value starts past offset 0. A start missing from the
graph, holding fewer than `N` bytes, or an `N` below 1, exits 2. Edges marked `overlapping-layouts` carry no
alignment, so a file written with several record layouts is not crossed.

## Limits

- The fixpoint merges paths: a move whose subscript takes several values reaches every candidate
  occurrence and has no single placement, so it joins nothing in unify.
- A fixpoint run capped with `--sweeps` that did not settle (its report says "NOT SETTLED") gives a
  subset of the flows; nothing is invented, some may be missing.
- Programs join only through combine's `links.jsonl` windows and dataset slots; the fixpoint's own
  rows never cross a program.
- A `RETURN TRANSID` hop to the next task has no edge.
- A CICS file sink is named by the field holding the file name (`FILE:LIT-CUSTFILENAME`), so a
  writer and a reader of one file are not matched.
