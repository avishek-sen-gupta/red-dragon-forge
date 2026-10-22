# CICS file sites resolved by the field dataflow

**Status:** design, approved in conversation 2026-10-22. Part 2 (the cross-program field picture
through datasets) is held in red-dragon-forge-qyz4 and is out of scope here.

## Intent

Today the knowledge graph names the CICS file a statement touches from the `VALUE` clause of the
operand: `EXEC CICS READ DATASET(WS-USRSEC-FILE)` becomes an edge to `USRSEC` because
`WS-USRSEC-FILE` is declared `VALUE 'USRSEC  '`. That guess is unsound: a `MOVE` can overwrite
the field before the `READ`, and the guess cannot tell. The same code already refuses this shortcut
for `XCTL PROGRAM(...)` for exactly that reason.

The field dataflow already resolves dynamic `CALL`/`XCTL`/`LINK` program operands soundly: the
fixpoint collects the values that reach the operand's bytes, with the reasons the set may be
incomplete, and the combine carries values across programs. This work gives CICS file-name
operands the same treatment, and makes the knowledge graph take its program-to-CICS-file edges
from that resolution, graded by certainty, the way it already grades dynamic call targets.

Why now: any cross-program picture of data at rest (an LLM guided by the dataflow graph, or a
deterministic dataset join) has to stand on a sound "this statement touches that file" fact.

## Goals

1. A CICS file statement whose `FILE(...)` or `DATASET(...)` operand is a data item is a dynamic
   site of the field dataflow, identified by program and statement node, exactly as a dynamic
   `XCTL PROGRAM(...)` is.
2. The fixpoint resolves its candidates and reasons with the existing value machinery; the
   narrowed `--call-targets-only` run keeps the operand's bytes live.
3. The combine resolves file names that reach the operand from another program, as it does for
   call targets.
4. `targets.jsonl` carries file sites, distinguishable from call sites by data, not by a naming
   convention.
5. The knowledge graph builds program-to-CICS-file edges for dynamic file operands from those rows,
   graded:

   | Candidates | Reasons | Edges |
   |---|---|---|
   | exactly one | none | one ordinary edge (`READS`, `WRITES`, ...) to the `CICS_FILE` |
   | one or more | any | one candidate edge per value (`READS_CANDIDATE`, ...) to each `CICS_FILE`, carrying the reasons |
   | none | | one edge of the verb's ordinary kind to a `DYNAMIC_TARGET` node carrying the reasons or dropped values |

   Every dynamic file site keeps an edge; its kind says how sure it is.
6. Every existing reader of `targets.jsonl` stays correct.

## Non-goals

- Joining writers to readers through datasets, dataset slots, bundles, and any change to the
  partition graph or page (red-dragon-forge-qyz4).
- Batch files. `SELECT ... ASSIGN` is static; nothing here changes.
- Alternate index paths resolved to their base cluster through IDCAMS `DEFINE PATH`/`RELATE`.
- File verbs the knowledge graph has no edge kind for today (`RESETBR`, `UNLOCK`).
- Letting values flow through files inside the combine (resolving `from-file` call targets).

## Anti-goals

- Any fallback to the `VALUE` clause for a data-item file operand. Where the dataflow cannot prove a
  name, the edge says so; it never guesses.
- An unresolved file site with no edge. Grading replaces dropping.
- A file name surfacing anywhere a program name is expected: as a `PROGRAM` node, as a callee in
  the area need, as a `srccfg` call target.

## Constraints

- "Always make lowering express the data explicitly in the IR": the CFG lowering states the file
  operand on the node, as it states `target_operand` for calls. No downstream re-reading of
  statement options.
- Decisions travel as data: a `targets.jsonl` row states what kind of site it is.
- No new builtins in red-dragon; `vendor/red-dragon` is untouched.
- More than 3-4 parameters is an anti-pattern; functional style; the forge's gates (pyright strict,
  python-fp-lint, import-linter, Talisman, both suites) apply.

## The how, as decided

### Which statements

`EXEC CICS` `READ`, `STARTBR`, `READNEXT`, `READPREV`, `WRITE`, `REWRITE`, `DELETE`, `ENDBR` — the
verbs the knowledge graph maps to `READS`/`WRITES`/`UPDATES`/`DELETES`/`ENDS_BROWSE` today. The
operand is `FILE(...)`, or `DATASET(...)` when `FILE` is absent (the older synonym; the trace's
origin side was just fixed to accept it, commit 97b45529). A literal operand is an ordinary edge,
as a literal `XCTL` target is.

### Lowering

The CFG lowering (`cobble/dataflow/srccfg/desugar.py`) today turns these verbs into plain nodes.
It must instead put the file operand on the node the way `_with_call` puts the program operand:
the operand as a reference (`_ref_mod_operand`), and whether it is a literal. Whether that reuses
`target`/`target_resolved`/`target_operand` or adds file-specific fields is the builder's call; the
constraint is that call-site code testing `transfer in CALL_TRANSFERS` keeps meaning calls only.

### Fixpoint

- `resolved_targets` (`cobble/dataflow/fixpoint/targets.py`) emits a row for every unresolved file
  site as well as every unresolved call site. Candidate filtering is per kind: `is_program_name`
  for calls, and for files a check that the value can name a CICS file (one to eight characters
  after trimming). Values failing it go to `dropped`, as non-program values do today.
- The row states its kind (program or file) and the CICS verb, through `target_fields` /
  `target_row` (`cobble/dataflow/fields/side_tables.py`).
- The call-targets-only roots (`cobble/dataflow/jumps/discover.py`, `_parts`) add each unresolved
  file site's operand extents as local demand, the way `_target_extents` does for call targets.
  A file site hands over no area, so it adds no entry demand.
- The corpus report and counts (`cobble/dataflow/fixpoint/build_corpus.py`, `dynamic_sites`,
  resolved-one/several) report file sites separately from call sites.

### Combine

The combine seeds its resolution from `jumps.jsonl` and answers jump target operands. A file site
is not a control transfer and must not become a jump. It gets its own per-member fact table (node,
verb, operand `Fact`), written by the same discovery that writes jump facts, and the combine
answers those operands alongside jump targets (`cobble/dataflow/combine/link.py`
`_program_answers`, `_target`, `_linked`), so a file name handed over in a commarea resolves across
programs. Combined `targets.jsonl` file rows carry the same fields as the fixpoint's, plus
`outside`.

### Readers of targets.jsonl

| Reader | Today with a file row | Required |
|---|---|---|
| `cobble-build --dynamic-call-targets` (`cobble/build_graph.py` `_row_target`) | `KeyError` | build graded file edges (goal 5) |
| `cobble-build` not-attempted path (`_covered_sites`, `_unanswered_sites`) | matches on caller and operand name only, so a file row can mask a call site | match on site kind too; dynamic file sites with no row get a not-attempted edge, as dynamic call sites do |
| `cobble-srccfg-build --dynamic-call-targets` | inert (looked up only at call nodes) | stays inert; pinned by a test |
| area need (`cobble/dataflow/fixpoint/target_site.py`) | would add file names as callees | skip file rows |
| combine `load.py` | builds a site, then drops it | answers it (above) |

### Knowledge graph

- `cobble/cics/verb_source_asg.py` stops resolving a data-item `FILE`/`DATASET` operand through
  `_resolve_operand`. It carries the operand unresolved, as `_transfer_verb` carries a dynamic
  `PROGRAM`, and reports the site the way `_program_dynamic_sites` reports dynamic `XCTL`/`LINK`.
- `cobble/cics/flow_graph_core.py` keeps emitting edges for literal file operands only.
- Dynamic file sites get their edges from `--dynamic-call-targets` (goal 5), or the not-attempted
  edge without it. New edge kinds: `READS_CANDIDATE`, `WRITES_CANDIDATE`, `UPDATES_CANDIDATE`,
  `DELETES_CANDIDATE`, `ENDS_BROWSE_CANDIDATE` in `cobble/knowledge_graph/graph_types.py`.
- `CICS_FILE` → `DATASET` from the CSD is unchanged.

### Units, in order

1. Lowering, fixpoint rows, liveness roots, counts; the area-need reader skips file rows;
   `srccfg` inertness pinned.
2. Combine: the file-site fact table and its resolution across programs.
3. Knowledge graph: verb source stops guessing, graded edges, the not-attempted path.

Each unit carries its tests and the living docs it changes (`docs/reference/cobble/field-dataflow.md`
for 1-2, `docs/reference/cobble/knowledge-graph.md` for 3).

## Tests that define done

- A synthetic program: `READ DATASET(WS-F)` with `WS-F VALUE 'USRSEC  '` and nothing else writing
  it gives one file row, candidates `['USRSEC']`, no reasons; `READ FILE('ACCTDAT')` gives none.
- The same with a `MOVE WS-OTHER TO WS-F` on one path gives the reason the walk raises
  (`not-a-literal` or both values), never the `VALUE` alone.
- `--call-targets-only` resolves the same file rows as a whole run.
- A file name passed in a commarea resolves through the combine.
- `cobble-build` with the targets: an exact site is a `READS` edge, an uncertain one
  `READS_CANDIDATE` edges with reasons, an empty one a `READS` edge to a `DYNAMIC_TARGET`; without
  the targets, a not-attempted edge. No file name becomes a `PROGRAM` node.
- A call site and a file site in one caller sharing an operand name keep separate markings.
- The area need's resolved sites contain no file names; `srccfg` closure is unchanged by file rows.
- A knowledge-graph test asserting program-to-`CICS_FILE` edges from EXEC CICS verbs (none exists
  today).
- On CardDemo, every online program's `LIT-*`/`WS-*-FILE` operand resolves to the CSD file the
  `VALUE` clause names, with no reasons.

## Calls made without the user (check these)

- **`DYNAMIC_TARGET` ids keep their scheme** (`<caller>.<expression>`). "A call site and a file site
  sharing an operand name keep separate markings" means the not-attempted matching only. A field
  used as both a program name and a file name in one caller would share one node; that is rare
  enough not to change a public id scheme for.
- **A CardDemo file site that picks up a reason is marked, not fixed here.** If the acceptance
  check finds a file operand with a reason, that site's assertion becomes an expected failure
  with a reason and a new issue; fixpoint precision work is not pulled into this design. There is
  no fallback to the `VALUE` clause either way.
- **File candidate edges carry their reasons as attributes;** today's call candidate edges stay as
  they are (they carry none).

## Left to the builder

- Field names on the CFG node and in the `targets.jsonl` row, and the file-name validity check's
  exact form.
- The file-site fact table's name and shape, within "not a jump".
- How the corpus report lays out file-site counts.
