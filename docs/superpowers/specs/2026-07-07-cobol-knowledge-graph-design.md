# COBOL/CICS/JCL Knowledge Graph Design

## Problem

Reverse-engineering a legacy COBOL/CICS/JCL codebase in prep for
modernization means answering questions like "what's affected if I change
this program", "what does this transaction actually do end to end", or
"what batch jobs touch this dataset" — and today there is no single place
to ask them. The pieces exist but are scattered and disconnected:

- `interpreter/project/cobol_connections.py` (red-dragon) already builds a
  flat CALL/COPY graph from a set of COBOL sources — `ProgramRef` nodes,
  `Connection` edges. Analysis-only, NDJSON output. Has a known gap: COPY
  targets never get a resolved file path.
- `cics/flow_map.py` (cicada) already builds a static CICS transaction flow
  map from a CSD + BMS mapsets + COBOL sources — a list of `CicsVerb`
  events (SEND_MAP, RECEIVE_MAP, XCTL, LINK, RETURN_TRANSID) per program,
  enriched with BMS field metadata. Output is a flat JSON list, not a graph.
- Jackal has a real JCL parser (`jackal/jcl/parser.py:parse_jcl(text) ->
  Job`, an ANTLR-backed bridge) and a typed model (`Job`/`Step`/`DD` in
  `jackal/model.py`), but no graph — `JobRunner` just iterates
  `job.steps` as a list. JCL step sequencing is not represented at all.

None of these three share a node identity scheme, so there is no way today
to ask a single cross-cutting question ("everything reachable from program
X") that spans CALL/COPY, CICS transaction flow, and JCL sequencing
together.

## Goal

Build one connected graph — material for a knowledge graph used to query
the codebase and support reverse-engineering/modernization work — where:

- Each COBOL program, copybook, CICS transaction, BMS map, JCL job, JCL
  step, and dataset is a node.
- CALL and COPY relationships between programs are edges.
- CICS transaction conversation flow (which program a transaction starts,
  XCTL/LINK transfers between programs, RETURN TRANSID handoffs, and the
  screens sent/received along the way) is represented as edges.
- JCL step sequencing (which job runs which steps in what order, which
  program each step runs, which datasets each step reads/writes) is
  represented as edges.
- One interactive HTML visualization of the merged CardDemo graph, as
  proof the graph is actually usable for reverse engineering, not just
  structurally correct.

Validation target: CardDemo, since it already has COBOL, a CICS CSD, BMS
maps, and JCL — the one fixture that exercises all three sources.

## Non-goals

- No new graph database server (Neo4j or similar) — see Backend below.
- No new COBOL, CICS, or JCL *parsing* — every extractor here reshapes
  data an existing, tested component already parses. The one new piece is
  the JCL *graph-shaping* layer over jackal's already-parsed `Job`/`Step`.
- No attempt to resolve dynamic CALL targets (a CALL by a variable rather
  than a literal program name) or dynamic XCTL/LINK targets — out of scope
  for this pass, same limitation the existing extractors already have.

## Design

### Node identity

Every node's true key is `(kind, id)`, where `id` is a **logical name** —
program-id, copybook name, transaction-id, `JOBNAME.STEPNAME`, dataset
name, or `MAPSET.MAP` — not a file path. File path is metadata on the node
(`file_path` field), not part of its identity. `kind` is included in the
key so a program and a dataset that happen to share a name after case
normalization don't collide.

This is the load-bearing decision that makes the graph "connected" rather
than three disjoint graphs: a program referenced by a COBOL `CALL`, a CICS
CSD `PROGRAM(...)` entry, and a JCL `EXEC PGM=...` all resolve to the exact
same node because they share a name. It also sidesteps
`cobol_connections.py`'s existing COPY-target file-path gap — copybook
nodes are keyed by name regardless of whether a path was ever resolved.

Names are normalized to uppercase at extraction time (the standard COBOL/
JCL convention), so `EXEC PGM=cosgn00c` and `PROGRAM-ID. COSGN00C` land on
the same node.

### Shared schema (new, in red-dragon)

`cobol_connections.py` already lives in red-dragon, and red-dragon is the
one package every consumer here (its own code, cicada, jackal) already
depends on — the schema has to live where the dependency direction allows
everyone to reach it. New module, `interpreter/project/graph_types.py`:

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeKind(Enum):
    PROGRAM = "PROGRAM"
    COPYBOOK = "COPYBOOK"
    TRANSACTION = "TRANSACTION"
    JOB = "JOB"
    STEP = "STEP"
    DATASET = "DATASET"
    BMS_MAP = "BMS_MAP"


class EdgeKind(Enum):
    CALL = "CALL"
    COPY = "COPY"
    XCTL = "XCTL"
    LINK = "LINK"
    RETURN_TRANSID = "RETURN_TRANSID"
    STARTS = "STARTS"                # TRANSACTION -> PROGRAM (from the CSD)
    SENDS_MAP = "SENDS_MAP"          # PROGRAM -> BMS_MAP
    RECEIVES_MAP = "RECEIVES_MAP"    # PROGRAM -> BMS_MAP
    JCL_STEP_RUNS = "JCL_STEP_RUNS"  # JOB -> STEP, and STEP -> PROGRAM
    READS = "READS"                  # STEP -> DATASET
    WRITES = "WRITES"                # STEP -> DATASET
    UPDATES = "UPDATES"              # STEP -> DATASET


@dataclass(frozen=True)
class GraphNode:
    id: str
    kind: NodeKind
    file_path: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    kind: EdgeKind
    attrs: dict[str, Any] = field(default_factory=dict)
```

`attrs` carries kind-specific detail that doesn't need to be a first-class
field: a JCL edge's raw `DISP` value, a `SENDS_MAP` edge's BMS field
list, a `STEP` node's `PARM=` string. Keeping these in `attrs` rather than
growing the dataclasses means new detail doesn't force a schema change.

### Extractor changes

**red-dragon: `cobol_connections.py`.** Modified in place to emit
`GraphNode`/`GraphEdge` directly instead of `ProgramRef`/`Connection` —
`CALL` and `COPY` edges, `PROGRAM` and `COPYBOOK` nodes. This is a
refactor of existing, tested logic, not new extraction.

**cicada: `flow_map.py`.** Modified in place. `extract_transaction_flow_map`
already collects everything needed per program (`CicsVerb.xctl_target` is
reused for both XCTL and LINK targets; `CicsVerb.transid` carries
RETURN_TRANSID's target transaction; `parse_csd` already returns the
`transid_to_program` mapping used for `STARTS` edges) — the change is a new
output shape, not new capture. BMS field lists already collected by
`_enrich_verb` become `SENDS_MAP`/`RECEIVES_MAP` edge `attrs`.

**jackal: new extractor**, `jackal/graph.py` (module name illustrative).
Walks an already-parsed `Job` (via the existing `parse_jcl`):

- `Job` → `GraphNode(kind=JOB)`
- Each `Step` → `GraphNode(kind=STEP, id=f"{job.name}.{step.name}")`
- `Step.pgm` → `GraphNode(kind=PROGRAM, id=step.pgm)` — the cross-link
  point shared with the CALL/COPY and CICS graphs
- Each `DD.dsn` → `GraphNode(kind=DATASET)`
- `JOB -[JCL_STEP_RUNS]-> STEP` for each step, in step order (so
  traversal reflects execution sequence)
- `STEP -[JCL_STEP_RUNS]-> PROGRAM`
- `STEP -[READS|WRITES|UPDATES]-> DATASET` per `DD`, kind derived from
  `DD.disp.status`: `NEW`→WRITES, `OLD`→UPDATES, `SHR`→READS, `MOD`→WRITES.
  The raw `DispStatus` value is kept in the edge's `attrs` regardless, so a
  misclassification is inspectable and correctable without re-extraction —
  this mapping is a standard convention, not a guaranteed-correct read of
  program intent (an `OLD` dataset could still be opened read-only).

This is the one genuinely new piece of extraction logic in this design;
everything else is a reshape of an existing extractor's output.

### Merge and query (new, red-dragon-forge)

New package `knowledge_graph/`, depending on red-dragon, cicada, squall,
and jackal (squall is not a source of graph data yet, but the package
lives alongside the other coprocessor-composition work in
`red_dragon_forge`, and squall's SQL access could plausibly become a
future edge kind here — no reason to block that door).

- `knowledge_graph/merge.py`: takes the `GraphNode`/`GraphEdge` sequences
  from all three extractors and builds one `networkx.MultiDiGraph`.
  `MultiDiGraph` (not `DiGraph`) because two nodes can be legitimately
  connected by more than one edge kind — e.g. a program that both `CALL`s
  another program and also runs it as a JCL step's `PGM=` in some batch
  flow. Networkx nodes are keyed by `(node.kind, node.id)`, matching the
  identity rule above. Duplicate node registration (the same `PROGRAM`
  node emitted by more than one extractor) merges `attrs` rather than
  last-write-wins overwriting.
- `knowledge_graph/query.py`: thin helpers over the merged graph —
  `reachable_from(node_id)`, `callers_of(node_id)`, `paths_between(a, b)`,
  each optionally filterable by `EdgeKind` (e.g. "only JCL edges from this
  program").
- `knowledge_graph/export.py`: NDJSON writer/reader (`nodes.ndjson` +
  `edges.ndjson`), following the same analysis-only NDJSON precedent
  `cobol_connections.py` already established.

### Backend

In-memory `networkx.MultiDiGraph` plus NDJSON export — no graph database
server for now. This avoids standing up new infrastructure before the
representation itself is proven out, while keeping NDJSON as a clean seam
to feed a real graph database (or the `code-review-graph` MCP tool
available in this environment) later without touching the schema or
extraction layer at all.

### Visualization

`knowledge_graph/render.py`: `render_html(graph: nx.MultiDiGraph,
output_path: Path) -> None`, producing one self-contained HTML file — no
server, no CDN, no external network access at view time, matching the
"no new infrastructure" spirit of the backend decision.

- **Rendering engine:** vis-network (MIT-licensed, single-file), vendored
  into the repo (e.g. `knowledge_graph/vendor/vis-network.min.js`) and
  inlined directly into the generated HTML's `<script>` tag at render
  time — proven pan/zoom/click interactivity without hand-rolling a
  force-directed layout.
- **Node styling:** color-coded by `NodeKind` (7 kinds), with a legend.
- **Edge styling:** color/label by `EdgeKind`.
- **Filtering:** checkboxes to show/hide by `NodeKind` and `EdgeKind` —
  essential once JCL/CICS/CALL edges are all in the same view, since an
  unfiltered CardDemo graph (29+ programs, transactions, jobs, datasets)
  is otherwise too dense to read.
- **Neighbor highlighting:** clicking a node highlights its direct
  neighbors and dims the rest — vis-network's selection API covers this
  with a small amount of glue JS, not a custom implementation.
- Generation is a CLI-invokable function (e.g. `knowledge_graph render
  <ndjson-dir> <output.html>`), not wired into any test-running path — a
  human opens the resulting file in a browser to explore it.

### Import-linter contract

`red-dragon-forge`'s `.importlinter` already enforces cics/squall/jackal
independence from each other. Add `knowledge_graph` to `root_packages` and
a forbidden-import contract: `cics`, `squall`, and `jackal` must never
import `knowledge_graph` — the same "coprocessor never knows about the
composition layer" direction already established for
`interpreter.project.coprocessor_compile`.

## Testing

- Unit tests per extractor change: `cobol_connections.py` emits the right
  `GraphNode`/`GraphEdge` shapes for CALL/COPY; `flow_map.py` emits the
  right shapes for XCTL/LINK/RETURN_TRANSID/STARTS/SENDS_MAP/RECEIVES_MAP;
  the new jackal extractor emits the right shapes for JOB/STEP/PROGRAM/
  DATASET and the DISP→edge-kind mapping.
- Unit tests for `knowledge_graph/merge.py`: cross-source node identity
  (the same `PROGRAM` node from two extractors merges rather than
  duplicating or overwriting), case normalization, `MultiDiGraph` multi-
  edge behavior.
- One integration test running the full pipeline over a representative
  slice of CardDemo (one JCL job, a handful of CICS-routed programs and
  their CALL/COPY dependencies) and asserting the merged graph actually
  connects a JCL step to a program to its CICS transaction — proving the
  cross-source linking works end to end, not just that each extractor
  works in isolation (the same discipline used to validate the
  `__cics_task_end_hook` composition work).
- One test generating `render_html` for the full CardDemo graph and
  verifying the output is well-formed (valid HTML, contains the expected
  node/edge counts embedded as data, vis-network's script is actually
  inlined rather than CDN-referenced) — not a browser-rendering test, just
  confirming the generator produces a complete, self-contained artifact.

## Open risks

- **Dynamic targets.** CALL/XCTL/LINK by variable, and PGM= by symbolic
  parameter, are invisible to all three extractors today. Out of scope for
  this pass (noted above), but worth flagging as a known coverage gap for
  reverse-engineering completeness.
- **DISP heuristic accuracy.** The NEW/OLD/SHR/MOD → WRITES/UPDATES/READS
  mapping is a convention, not a guarantee. Raw DISP is preserved in edge
  attrs specifically so this is auditable.
- **Case/name collisions.** Uppercase normalization assumes COBOL/JCL's
  own case-insensitivity conventions hold across the whole corpus; a
  program and a dataset that happen to share a name after normalization
  would collide unless kind is also part of node identity (it is — see
  schema — so a `PROGRAM` node and a `DATASET` node with the same string
  id do not collide, since identity is really `(kind, id)`).
