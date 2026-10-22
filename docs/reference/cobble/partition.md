# cobble: field partitions (experimental)

**Experimental.** The commands and file shapes on this page can change without notice.

Field partitions group the fields of a program that exchange bytes. A cluster is a candidate for
one domain concept split across several fields: a customer's name moving between the screen,
the commarea, the record and its update copy, say, or a balance, its limits and the interest
computed from them. Clusters never cross a program boundary. Merging them across programs is
not done yet.

Code: `cobble/cobble/experimental/partition/`.

## Make targets

From the forge root. Each target runs the one before it.

| Target | Does |
|---|---|
| `partition-traces` | `cobble-parse-corpus`, `cobble-extents`, `cobble-dataflow-area-need`, `cobble-dataflow-fixpoint --call-targets-only`, `cobble-dataflow-combine --max-hops 5`, then one `cobble-fields-trace` per member |
| `partition-graph` | `cobble-experimental-partition-graph` |
| `partition-clusters` | `cobble-experimental-partition-clusters` |
| `partition-render` | `cobble-experimental-partition-render` |

| Variable | Default | Meaning |
|---|---|---|
| `PARTITION_CONFIG` | `config/carddemo-partition.toml` | the corpus config, relative to `cobble/` |
| `PARTITION_ASG` | `out-partition/asg` | the `asg_dir` that config names |
| `PARTITION_DIR` | `out-partition` | where every artefact goes |
| `PARTITION_PATHS` | `3000` | `--paths` for each trace |
| `PARTITION_BARRIER`, `PARTITION_FANOUT` | `fanout`, `8` | the barrier, below |

The CardDemo config parses into its own cache, so a cache written before a bridge change is
never read. `PARTITION_DIR` then holds `extents.jsonl`, `area-need.jsonl`, `fixpoint/`,
`combine/`, `traces/`, `graph.json`, `clusters.json`, `clusters.md` and `partition.html`.

## cobble-experimental-partition-graph

```
cobble-experimental-partition-graph --extents EXTENTS --traces DIR --out OUT
    [--links LINKS] [--barrier {none,fanout}] [--fanout-limit N]
```

| Flag | Meaning |
|---|---|
| `--extents` | the table `cobble-extents` wrote |
| `--traces` | a directory of `cobble-fields-trace` outputs; every `*.jsonl` in it is read |
| `--links` | `links.jsonl` from `cobble-dataflow-combine`. Without it, programs join only where a trace entered a callee |
| `--barrier`, `--fanout-limit` | which crossings clustering does not cross (default `fanout`, 8) |
| `--out` | the graph JSON |

A node is an elementary field: one with nothing declared under it, so every variant of a
`REDEFINES` has its own fields. Every occurrence of an `OCCURS` table is one node, named
`<program>:<record>.<field>`. Each program's origins (`LITERAL`, `FILE:`, `%CICS-STATE`,
`%CALL:`) and sinks (`FILE:`, `MAP:`, `TSQ:`, `TDQ:`, `TRANSID:`) are nodes of their own.

A dep row's range resolves to the elementary fields declared under the field it names that
overlap its bytes. A source range also takes the fields its definers wrote, when a definer's
write lies inside the range: `SEND MAP FROM(COTRN0AO)` reads `TDATE03I`, which shares its bytes,
when a `MOVE` to `TDATE03I` reached it. A definer that copied into one undivided field, such as a
`PIC X(500)` record, is followed back through its own source and definers, so the read takes the
fields that filled those bytes. A named field whose bytes such fields cover drops out. A write to
a whole record contributes nothing to a read of part of it, so one record type of a `REDEFINES`
never picks up another's fields. Edges then run from source fields to target fields:

| Fields on each side | Edges |
|---|---|
| one on either side | every source to every target |
| several on both | byte-aligned: each target field from the source fields at the same offsets |

A combine link binds the caller's window to the callee's the same way, and binds them back when
the link returns. An edge records how many sites move bytes along it, whether clustering crosses
it, and whether it joins two programs.

### Barriers

A barrier judges the field pairs one statement links. A blocked statement's edges stay in the
graph, drawn red, and clustering does not cross them.

| Barrier | Blocks |
|---|---|
| `none` | nothing: clusters over the raw graph |
| `fanout` | a statement in which one field is linked to more than `--fanout-limit` others: a record written from an undivided `PIC X(n)` area, a commarea saved whole, a report line assembled from many fields |

At 8 on CardDemo, a date or phone number assembled from its parts stays clustered and the
commarea, export and report crossings are blocked. A concept wider than the limit, such as a
13-part timestamp, splits into its parts.

## cobble-experimental-partition-clusters

```
cobble-experimental-partition-clusters --graph GRAPH --out OUT --report REPORT [--split-at N]
```

Connected components over the field edges that clustering crosses and that stay inside one
program. A component of at least `--split-at` fields (default 30) is split into Louvain
communities, seeded, so a run is repeatable. A field in no component of two or more is
isolated: only origins and sinks touch it, or only blocked edges. `--out` is the JSON;
`--report` is markdown, one section per component with the terminals it touches and each
cluster's records and fields.

## cobble-experimental-partition-render

```
cobble-experimental-partition-render --graph GRAPH --clusters CLUSTERS --out OUT
```

One self-contained WebGL page, using the sigma.js and graphology builds cobble vendors, dark on
light. Only clustered edges between two fields place nodes, cross-program ones included. Each
connected group of fields they link is a disc, laid out by a seeded networkx `spring_layout`
over its own edges. Discs are packed in a spiral, largest first, and pushed apart until none
overlap; where two discs sit says nothing. Unclustered fields, then origins and sinks, fill
rings around them. Dot sizes are in layout units, so they keep their spacing when zoomed out.
Labels show only for a hovered node and its neighbours, or the selected cluster. Colour shows the
cluster. The side panel lists
clusters or components. Clicking one zooms to it and lists its fields and terminals. Hovering a
node shows its edges. Edges are grey when clustered, orange when they cross programs, and red
when a barrier blocked them.

## Limits

- The trace samples paths, so a flow no sampled path took has no edge.
- The trace does not enter a callee named by a variable (`XCTL PROGRAM(CDEMO-TO-PROGRAM)`): it
  records a `dynamic-target` dead end. `--links` joins those programs through the combine's
  windows instead, which is not tied to any path (red-dragon-forge-fjx7).
- A `RETURN TRANSID` hop to the next task has no edge.
- A CICS file sink is named by the field holding the file name (`FILE:LIT-CUSTFILENAME`), so a
  writer and a reader of one file are not matched.
