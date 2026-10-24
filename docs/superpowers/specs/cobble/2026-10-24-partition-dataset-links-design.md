# Dataset links for the partition graph

**Status:** design, approved in conversation 2026-10-24. Implements red-dragon-forge-qyz4. The
CICS file-site resolution it stands on (2026-10-22-cics-file-sites-design.md) landed in ba15cdcb.

## Intent

The partition graph links fields only inside a program and across call handovers. A record one
program writes to a file and another reads back is today two unrelated `FILE:` terminals. Two
uses:

1. The page shows connections that run through a dataset: a writer's field, the dataset bytes it
   lands on, and the reader fields that take those bytes, in one connected component.
2. Aggregate unification (`cobble-experimental-aggregate-unify`) joins a writer's field and a
   reader's field that hold the same bytes of the same dataset record, so per-program aggregates
   can be correlated across programs.

Everything is a deterministic join on dataset identity plus byte offset. No heuristics, no name
matching, no LLM.

## Goals

1. **Site resolution.** Every file read site and write site in the traces resolves to a dataset
   identity:
   - Batch: the trace's `FILE:<select name>` names the SELECT. The knowledge graph's
     `PROGRAM -READS/WRITES/UPDATES{select_name}-> COBOL_FILE` edge gives the DD name; each
     `STEP -JCL_STEP_RUNS-> PROGRAM` step binds that DD name to a DSN through its
     `STEP -READS/WRITES/UPDATES{ddname}-> DATASET` edge. One binding per step that runs the
     program, directly or through a chain of CALLs: a called program runs in its caller's step
     and opens files through that step's DD statements. Static calls come from the knowledge
     graph's `CALL` edges; a dynamic call follows the fixpoint's resolved program targets, and a
     binding reached through a `possible` call target is itself `possible` with that target's
     reasons. No other step attribution (no name or library conventions).
   - CICS: the trace's `FILE:<operand>` site is matched to the fixpoint's `targets.jsonl` row of
     `kind: file` for the same program and node. Its candidates are CICS file names; the CSD's
     `CICS_FILE -DEFINES_DATASET-> DATASET` gives the DSN where one is defined.
   - Identity: the DSN where known. A CICS file with no DSN in the CSD is identified by its CICS file name, so
     CICS programs sharing that file still link; such a file cannot link to batch.
2. **Certainty labels.** Every site resolution and every link is `exact` or `possible` with
   reasons:

   | Case | Label |
   |---|---|
   | one candidate (CICS) or one DD binding per step (batch), no reasons | `exact` |
   | several candidates | `possible: candidates`, one link per candidate |
   | fixpoint reasons present (e.g. `incomplete-walk` from a capped `--sweeps` run) | `possible: <reasons>` |
   | no candidate (e.g. `uninitialised`) | `possible: <reason>`, on a slot of its own named by the operand: `? LIT-CARDFILENAME-ACCT-PATH` |
   | batch program run by no JCL step | `possible: no-step`, on a slot of its own named by the select name |
   | batch DD bound to no dataset in a step | `possible: dd-unbound`, on a slot of its own named by the DD name |
   | a slot whose bytes have more than one layout on the writer's or reader's side (`REDEFINES`, several record types) | that slot's edges are `possible: overlapping layouts`; slots under bytes with one layout on both sides, such as a fixed header, stay `exact` |

   An unresolved site is never dropped and never guessed. Its slot is identified by program and site
   node, never by the operand or select name alone, so two programs sharing an operand name are
   not linked by it (designer's call).
3. **Dataset slots.** For each dataset identity, the record is cut at every field boundary any program
   uses on it: the boundaries of the elementary fields under each read site's target extent and
   each write site's source extent, offsets measured from the start of that extent. Each piece is
   a slot node, `<identity>[start:end]`, of a new node kind `dataset`, belonging to no program.
4. **Edges.** Writer field → slot for each write site, slot → reader field for each read site,
   each carrying byte alignments exactly as today's field edges do (`aligned` true for `exact`,
   false and no alignments for `possible`). A field whose bytes cover several slots has an edge
   to each. A link carries the DSN (or CICS file name), the label and the reasons.
5. **Graph and page.** Slot nodes and dataset edges are part of `graph.jsonl`. The page draws
   them (option B in the conversation's mockups): slots as their own nodes, dataset edges in a
   new colour, solid for exact, dashed for possible, the identity and reasons on hover. Fields linked
   through a slot are one connected component, so component colouring and search follow the
   chain across programs.
6. **Clusters do not merge.** Dataset edges are never clustered. A cluster stays one program's
   concept.
7. **Unify follows exact dataset edges.** A slot relays bytes the way a table occurrence does
   today, so a writer field and a reader field that cover the same slot bytes, same size, in
   different programs, become one class. `possible` dataset edges are ignored and never stop a
   field joining through its other exact edges.
8. **Fail-safe.** The stage is optional. Without its inputs the graph, clusters, page and unify
   are exactly today's. Each input turns off only its own half (designer's call): without the
   knowledge graph there are no dataset links at all; without `targets.jsonl` batch links are
   still made and CICS sites get none. A log line names each absent input; never an error.

## Non-goals

- Dataset-to-dataset copies: IDCAMS `REPRO`, DFSORT, or any non-COBOL step between writer and
  reader. Such a writer and reader are not linked.
- Alternate index paths resolved to their base cluster (IDCAMS `DEFINE PATH`/`RELATE`). An AIX
  file is identified by its own name or DSN.
- GDG generation alignment: a GDG base DSN is the identity, with relative generations not told apart.
- Values flowing through files inside the combine.
- Merging clusters across programs.

## Anti-goals

- Joining by copybook or field name.
- Any fallback to a `VALUE` clause for a file operand; the fixpoint's resolution is the only
  source for CICS file names.
- A `possible` link presented like an exact one, or used by unify.
- An unresolved site dropped from the graph.

## Constraints

- Lives in `cobble/cobble/experimental/partition/` and stays experimental; the aggregates code it
  touches is in `cobble/cobble/experimental/aggregates/`.
- Reads only existing artefacts: the traces, `extents.jsonl`, the fixpoint's `targets.jsonl`, and
  the knowledge graph `cobble-build` writes for the partition config.
- The site match uses typed fields (program, node id, kind), not string patterns.
- Docs: `docs/reference/cobble/partition.md` and `aggregates.md` change in the same commits.
- `make partition-graph` hands the new inputs when present; the knowledge graph is built by a
  `cobble-build` step added before it.

## Left to the builder

- Whether site resolution is its own CLI writing a `datasets.jsonl`, or a step inside
  `cobble-experimental-partition-graph` behind optional `--knowledge-graph` and `--targets`
  flags.
- Where slot nodes sit on the page. Today only clustered field-to-field edges place nodes; since
  dataset edges are unclustered, they would otherwise fall into the outer rings.
