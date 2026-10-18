# cobble: corpus preparation and the knowledge graph

Covers the stages that read the corpus config: symbolic copybooks, CSD synthesis, the parse,
the expanded-source dump, and the knowledge graph with its comparison and renderers. Config
keys are in [config](config.md).

## Order

1. `cobble-sym` writes the BMS symbolic copybooks the parse resolves `COPY` against.
2. `cobble-parse-corpus` writes the ASG cache. Every later stage reads it.
3. The field dataflow (see [field-dataflow](field-dataflow.md)) writes `targets.jsonl`.
4. `cobble-build` writes the graph file, optionally with those targets.
5. `cobble-compare`, `cobble-render` and `cobble-render-webgl` read the graph file.

Changing the corpus means running the parse again. `cobble-build` reports a member with no
cached ASG as skipped; it never parses.

## cobble-sym

```
cobble-sym --config CONFIG
```

For each file in `bms_dir` matching `bms_globs`, runs `hlasm_export <map>.bms --syslib
<macros_dir>` piped through `bms_copybook_gen`, and writes `<sym_dir>/<stem>.cpy`. Fails if
`hlasm_export` is not built.

## cobble-csd

```
cobble-csd --config CONFIG --out OUT
```

Writes a synthetic CSD for a corpus that arrived without one. With `csd_files` empty,
`cobble-build` skips the CICS flow stage, so no CICS `LINK`/`XCTL` edges reach the graph.
This command reconstructs `DEFINE TRANSACTION(...) PROGRAM(...)` pairs from the members:

| Tier | Meaning |
|---|---|
| `corroborated` | `transid_rules` places a transaction id on the member, the member's source names that id literally, and no other member claims it |
| `convention` | `transid_rules` places it and nothing contradicts it |
| `return-transid` | the convention places nothing on the member, and the member's own `EXEC CICS RETURN TRANSID('...')` names exactly one id, which no other member returns to and the convention places on no member |
| `synthetic` | nothing establishes a transaction; the member gets `UNKNOWN.<member>` |

A transaction id two members claim, by convention or by both returning to it, demotes both
and is reported. A literal id no member claims is reported. With no `transid_rules`, only
`return-transid` can place a member; every other member is synthetic.

A synthetic entry gets the member onto the CICS worklist. `cobble-build` then drops the
placeholder `TRANSACTION` node and every edge touching it. `DEFINE FILE` cannot be
reconstructed, so a synthetic CSD yields no `DEFINES_DATASET` edges.

The output is not picked up automatically. Add its path to `csd_files` to use it.

## cobble-parse-corpus

```
cobble-parse-corpus --config CONFIG [--jobs JOBS] [--force]
```

| Flag | Meaning |
|---|---|
| `--config` | corpus config: `cobol_dir`, `cobol_globs`, `copybook_dirs`, `copybook_extensions`, `asg_dir` |
| `--jobs` | worker processes, one JVM each. Default: one per core |
| `--force` | parse every member, including those with an ASG |

Requires `PROLEAP_BRIDGE_JAR`. Refuses to start when the variable is unset, when the JAR is not
a file, or when any `copybook_dirs` entry is not an existing directory.

Writes one `<member>.json` per member to `asg_dir`, named for the member's file name, not its
`PROGRAM-ID`. It holds the member's compilation unit, `{"programs": [...]}`: every program in
the source, batch or nested, each carrying the programs it contains. A cache written before
this shape fails to read back, member by member; rebuild it with `--force`. A
member the bridge rejects gets `<member>.fail` with the bridge's message. A
member with a `.json` is skipped; a member with a `.fail` is retried on every run. A re-parse
whose outcome changes removes the other record, so a member never has both. A failure that is
not about the member (an unwritable `asg_dir`, a full disk) ends the run.

After a bridge or grammar change, parse into an empty `asg_dir`.

## cobble-expand-corpus

```
cobble-expand-corpus --config CONFIG --out-dir OUT_DIR [--jobs JOBS]
```

Writes `<member>.cbl` per member to `--out-dir`: the text the COBOL grammar receives, with
copybooks inlined, continuations folded and comments stripped. Use it to read a member that
does not parse. A member it cannot expand gets `<member>.fail`. It resumes on `--out-dir`, not
on `asg_dir`. Same JAR and copybook-directory checks as the parse. Nothing downstream reads
its output.

## cobble-build

```
cobble-build --config CONFIG --output OUTPUT [--dynamic-call-targets FILE]
```

| Flag | Meaning |
|---|---|
| `--config` | corpus config |
| `--output` | the graph file: one JSON line per node and per edge, tagged `"type": "node"` or `"type": "edge"` |
| `--dynamic-call-targets` | a `targets.jsonl` from `cobble-dataflow-fixpoint` or `cobble-dataflow-combine`. Without it, no dynamic-target edges. A named file that does not exist stops the build before it starts |

Requires `JCL_BRIDGE_JAR`. Runs four extractors: JCL, `CALL`/`COPY`, CICS flow, and batch
`FILE-CONTROL`. The CICS flow and `FILE-CONTROL` extractors read ASGs from `asg_dir`:
`FILE-CONTROL` reads every program of a member, the CICS flow only the first (the program the
member is named for, red-dragon-forge-1yoa). The
build refuses to start when a `csd_files` entry is not a readable file.

Skips are collected per extractor and reported at the end on stderr as a block headed
`N FAILURE(S) -- THIS GRAPH IS INCOMPLETE`, with a tally by category. The exit status stays 0.

### Dynamic-target edges

Each `targets.jsonl` row becomes edges by this rule:

| Candidates | Reasons | Edges |
|---|---|---|
| exactly one | none | one `CALL`/`XCTL`/`LINK` edge to the `PROGRAM` |
| one or more | any | one `CALL_CANDIDATE`/`XCTL_CANDIDATE`/`LINK_CANDIDATE` edge per candidate |
| none | | one edge to a `DYNAMIC_TARGET` node carrying the reasons or dropped values |

A `DYNAMIC_TARGET` id is `<program>.<expression>`, scoped to the program that names it.

### Node locations

`CorpusIndex` resolves each `(kind, id)` to a file location once per run, from the corpus
config. A node with no file carries a `NoFileLocation` with its reason: not file-based, no
definition source, or unresolved.

## cobble-compare

```
cobble-compare --graph GRAPH
```

Identity diff against `cobble/reference/graph.jsonl`, the CardDemo reference graph. Node
identity is `(kind, id)`; edge identity is `(source, source_kind, target, target_kind, kind)`.
Reports missing and extra nodes and edges. Exits non-zero on any difference. Only meaningful
for CardDemo built with the combine's targets.

## cobble-render

```
cobble-render --graph GRAPH
```

Writes `<stem>.html` beside the graph file: one self-contained page using the vendored
vis-network. It filters by node and edge kind, highlights matching labels from a search box,
and highlights a clicked node's neighbours. A missing graph file exits 1.

## cobble-render-webgl

```
cobble-render-webgl --graph GRAPH [--out FILE]
```

Writes `<stem>-webgl.html` beside the graph file, or to `FILE` if `--out` is given, creating
its directory if missing. The layout
is computed with Graphviz `sfdp` when the page is built, so the browser does no simulation. Use
it for graphs too large for `cobble-render`.

## Modules

| Path | Holds |
|---|---|
| `cobble/cobble/build_graph.py` | the build driver |
| `cobble/cobble/compare.py` | the identity diff |
| `cobble/cobble/corpus_config.py` | the corpus config loader |
| `cobble/cobble/corpus_index.py` | node-to-file resolution |
| `cobble/cobble/parsing/` | the parse and expand stages, and the ASG cache reader every stage uses |
| `cobble/cobble/cics/` | CICS flow extraction from the ASG (`verb_source_asg.py`, `flow_map.py`) and CSD synthesis (`synth_csd.py`). CSD parsing is cicada's `cics.csd_parse` |
| `cobble/cobble/jcl/` | the JCL and batch file graphs |
| `cobble/cobble/knowledge_graph/` | graph file, merge, and both renderers |
| `cobble/cobble/generate_sym.py`, `generate_csd.py` | `cobble-sym`, `cobble-csd` |
| `cobble/bms-macros/` | the BMS prototype macros |
| `cobble/reference/graph.jsonl` | the CardDemo reference graph |
