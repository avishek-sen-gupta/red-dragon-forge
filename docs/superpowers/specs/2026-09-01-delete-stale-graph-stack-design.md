# Deleting the stale graph stack ahead of the cobble consolidation

**Date:** 2026-09-01
**Status:** design, approved in outline; not yet planned or implemented
**Supersedes in part:** `2026-08-29-cobble-consolidation-design.md` — see *Effect on
the consolidation design*.

## Problem

Forge's whole-system graph pipeline is the code cobble was extracted from. Cobble
has since rebuilt it: a richer node vocabulary carrying `FileLocation`, a
corpus-generic `build_graph` in place of forge's CardDemo-specific driver, a
replacement CALL/COPY extractor (`cobol_imports` + `import_types`) in place of
red-dragon's `cobol_connections`, an ASG-walk verb source in place of the
VM-based one, and modules forge never had at all (`node_key`, `layout`,
`palette`, `render_webgl`, `flow_observer`, `canonical_export`).

Forge's copy is not a lagging variant of cobble's. It is the ancestor. Keeping it
through the consolidation would mean merging a superseded implementation into its
successor, module by module, to arrive at the successor.

The 2026-08-29 design assumed the opposite direction — that forge's modules were
canonical and cobble's divergences had to be reconciled *into* them (its "Group A
— copies that genuinely differ", reconciled "before deleting, not after"). That
assumption is what this design reverses.

## Decision

**Delete forge's graph stack completely, in one sweep per repository, before any
cobble integration begins.** Forge keeps no graph capability in the interim;
cobble's own corpus suite becomes the gate when it lands.

## Scope

The graph stack is a clean leaf. No runtime imports any of it — not cicada's
dispatcher, VSAM, BMS or conversational layers, not jackal's runner, catalog or
IDCAMS, not squall, not `red_dragon_forge`. The only cross-package reach is
`build_carddemo_graph.py` and the two root integration tests, all of which are
themselves deleted. There is nothing to unpick.

The one exception is the `CicsFlowObserver` seam, which is graph machinery living
inside `cics/strategy.py`. It is removed as well, under the safety argument set
out in *The observer seam inside the lowering strategy* below.

### Deleted from red-dragon-forge

| Path | What it is |
| --- | --- |
| `knowledge_graph/` | The package: `build_carddemo_graph`, `merge`, `query`, `render`, `export`, `graph_writer`, `fitness`, plus `vendor/vis-network` and its `pyproject.toml` |
| `cicada/cics/flow_map.py` | CICS transaction flow extractor |
| `cicada/cics/flow_graph_core.py` | Shared CICS edge construction |
| `cicada/cics/graph_sink.py` | cicada-local sink protocol |
| `cicada/cics/verb_source_lowering.py` | VM-based `CicsVerb` source |
| `jackal/jackal/jcl_graph.py` | JCL job/step/dataset extractor |
| `jackal/jackal/cobol_file_graph.py` | FILE-CONTROL extractor |
| `tests/unit/knowledge_graph/` | `test_merge`, `test_graph_writer`, `test_render`, `test_query`, `test_export` |
| `tests/integration/test_knowledge_graph_carddemo.py` | CardDemo end-to-end build |
| `tests/integration/test_fitness_golden.py` | Golden identity comparison |
| `tests/integration/fitness/carddemo_graph.{nodes,edges}.jsonl` | The 449-node / 803-edge golden |
| `cicada/tests/integration/cics/test_flow_graph.py` | CICS flow extraction tests |
| `jackal/tests/unit/test_jcl_graph.py` | JCL extraction tests |
| `jackal/tests/unit/test_cobol_file_graph.py` | FILE-CONTROL extraction tests |
| `experiments/standalone-graph/` | Untracked VM-free port of the same pipeline |

`verb_source_lowering.py` deserves a note, because its name invites the wrong
reading. It is not part of lowering to IR; it is a *consumer* of it. It attaches
a `GraphEmittingObserver` to `build_cics_spec` and runs `compile_cics_program`
purely to harvest `CicsVerb`s as a side effect, and its only importer is
`flow_map.py`. Deleting it removes a caller of the lowering path, not machinery
the lowering path needs. It is the VM-based half of a two-implementation seam
whose other half is cobble's `verb_source_asg.py`; collapsing the seam to one
implementation is why the 2026-08-29 design's argument for keeping `flow_map`
inside cicada — that cicada owns both sides of it — no longer holds.

### The observer seam inside the lowering strategy

The `CicsFlowObserver` seam exists only to feed the graph, but unlike everything
else above it lives inside runtime code: `cics/strategy.py` imports
`CicsFlowObserver`, `CicsVerb` and `NullCicsFlowObserver`, and
`CicsLoweringStrategy` calls `self._observer.on_verb(...)` at eight sites through
the lowering. With `verb_source_lowering.py` gone, `NullCicsFlowObserver` is the
only implementation that could ever be passed, and cobble will not revive it — it
sources the same verbs from an ASG walk. **The seam goes too.**

| Path | What goes |
| --- | --- |
| `cicada/cics/flow_observer.py` | Whole file: `CicsVerb`, `CicsFlowObserver`, `NullCicsFlowObserver`, `field_direction` |
| `cicada/tests/unit/cics/test_flow_observer.py` | Its unit test |
| `cicada/cics/strategy.py` | The `flow_observer` import, the `observer=` constructor parameter and `self._observer` assignment, the eight `on_verb(CicsVerb(...))` blocks, and the now-unused `_resolve_operand` / `_field_value` helpers |

This is the one edit in this design that touches code the runtime executes, so it
carries an explicit safety argument:

- `_resolve_operand` and `_field_value` are **pure** — they read
  `ctx._asg.data_fields` and return a string; neither calls `emit_inst` nor
  `fresh_reg` nor mutates `ctx`. Removing their call sites therefore cannot
  change the instruction stream.
- `map_op_text` and `mapset_op_text` (`strategy.py:749–750`) are the only locals
  the observer blocks compute, and their sole readers are the two `on_verb`
  blocks immediately below them. Nothing downstream in the SEND/RECEIVE MAP
  lowering reads either.
- Every `on_verb` block is a statement whose value is discarded. None sits in a
  conditional that guards subsequent lowering.

So the claim to falsify is: **the emitted IR is identical before and after.**
`build_cics_spec` passes `observer` through `**kwargs` and never names it, so no
edit is needed in `coprocessor.py`; the parameter simply stops being supplied.

After the removal, `_resolve_operand`, `_field_value`, and whichever `strategy.py`
imports they were the last users of (`CicsOperand` among them) become unreferenced
— fp-lint and Black in pre-commit are the check that none are left behind.

### Deleted from red-dragon

Committed in the standalone clone at `~/code/red-dragon` and picked up here as a
submodule bump.

| Path | What it is |
| --- | --- |
| `interpreter/project/graph_types.py` | Node/edge vocabulary |
| `interpreter/project/cobol_connections.py` | CALL/COPY extractor superseded by `cobol_imports` |
| `tests/unit/project/test_graph_types.py` | |
| `tests/unit/project/test_cobol_connections_defaults.py` | |
| `tests/integration/project/test_cobol_connections.py` | |
| `tests/fixtures/projects/cobol_connections_demo/` | That test's on-disk fixture |

**`cobol_imports.py` and `import_types.py` stay.** They look like graph code and
are not: `interpreter/project/imports.py` and `interpreter/project/types.py`
consume them, which puts them on the compile and link path. `cobol_connections.py`
is the only graph-specific consumer of `graph_types`, so the two files leave
together and nothing else in red-dragon references either.

### Configuration and documentation

Removing `knowledge_graph` as a workspace member touches five files:

- `pyproject.toml` — drop from `[tool.uv.workspace] members`
- `.importlinter` — drop from `root_packages`, and delete the
  `knowledge-graph-composition-only` contract, whose forbidden target ceases to
  exist
- `.pre-commit-config.yaml` — drop from the Black `files` regex and the fp-lint
  entry
- `.github/workflows/ci.yml` — drop from the Black `--check` path list
- `README.md` (the `knowledge_graph/` bullet, the import-contract sentence, the
  tree, the workspace-members line) and `CLAUDE.md` (the architecture bullet and
  the import-contract bullet)

**CI's `hlasm_export` build.** The root job builds the native binary with the
comment "needed by the fitness-golden extraction". Cicada's own job builds it
too, for the CICS e2e path. Whether the root job still needs it after the golden
goes is a question about which tests that job actually selects — **verify against
the job's test selection before removing the step**; do not remove it on the
strength of the comment alone.

### Out of scope

Anything cobble-side. This design ends at a forge with no graph pipeline; how
cobble's arrives is the consolidation design's business.

## Sequencing

One sweep per repository, two commits:

1. **red-dragon-forge** — every path in *Deleted from red-dragon-forge*, plus the
   five configuration and documentation files, in one commit.
2. **red-dragon** — the six paths above, committed and pushed in `~/code/red-dragon`
   (never edited inside forge's vendored checkout), then a submodule-pointer bump
   in forge.

Forge's commit must land first. Its modules are what import
`interpreter.project.graph_types`; bumping the submodule while they still exist
breaks the build.

## Verification

The suite passing is a weak gate for the deletions — they remove the tests that
would fail. It is the *only* real gate for the `strategy.py` edit, which is the
one change that could alter behaviour:

- **The CICS lowering and e2e suites must pass unchanged.** `cicada/tests` covers
  the strategy directly; a difference in the emitted instruction stream shows up
  there, not in a grep.
- Stronger, if cheap to arrange: capture the IR for a representative CICS program
  before and after and diff it. The design's claim is byte-identical output, so
  anything other than an empty diff falsifies the safety argument and the seam
  removal should stop rather than be patched around.

The remaining checks are mechanical:

- `grep` for `knowledge_graph`, `graph_types`, `flow_map`, `flow_graph_core`,
  `graph_sink`, `verb_source_lowering`, `flow_observer`, `CicsVerb`, `on_verb`,
  `jcl_graph`, `cobol_file_graph`,
  `cobol_connections` across both repositories, excluding `.venv`, `__pycache__`
  and historical `docs/superpowers/plans/`, returns nothing outside prose that
  describes the past
- `uv run lint-imports` passes with the reduced contract set
- `make test-all` passes in forge, and red-dragon's own suite passes in the
  standalone clone
- `make python` succeeds — the workspace resolves without the removed member

## Effect on the consolidation design

`2026-08-29-cobble-consolidation-design.md` needs amending, not annotating. Three
of its sections now read backwards:

- **Reconciliation, Group A** — its four "reconcile before deleting" modules
  (`flow_map`, `flow_graph_core`, `render`, `graph_types`) are deleted here
  instead. Group B is unaffected.
- **What cobble deletes** — the table's `cics/`, `jackal/`, `knowledge_graph/`
  and `interpreter/project/graph_types.py` rows had cobble deleting its copies in
  favour of forge's. Those rows invert or disappear.
- **What moves into cicada rather than staying in cobble** — `verb_source_asg.py`
  was to land beside cicada's `verb_source_lowering.py`. With that sibling gone
  and the graph stack living wholly inside cobble, it stays in cobble.
- **Architecture** — the diagram shows `knowledge_graph` as a workspace member
  and cobble importing it. Both change: cobble owns the graph stack; cicada,
  jackal and red-dragon keep only parsing and runtime.

The design's central claim survives intact — the duplication runs in one
direction, from one consumer, and folding cobble into the workspace removes it.
Only the direction of the deletions changes.

## Consequences

**Gained.** The consolidation stops being a merge. Cobble's modules arrive as
themselves rather than as a reconciliation against their own ancestor, and the
eight-item Group A merge phase — whose cost the 2026-08-29 design measured at
roughly 530 diverged lines and growing — disappears.

**Lost.** Forge has no whole-system graph until cobble lands: no CardDemo HTML,
no fitness golden, no CALL/COPY extraction from red-dragon. This is accepted
deliberately. The golden is not kept as a frozen contract for cobble to
reproduce, because cobble builds a different graph on a different vocabulary and
a corpus-generic driver; a CardDemo-shaped target would constrain it toward the
implementation being deleted.

**Also lost.** `experiments/standalone-graph/`, which proved the pipeline
reproduces exactly (449 nodes, 803 edges, empty identity diff) without the VM.
That result is the evidence the graph does not need what is being deleted; it is
recorded here because the directory is not.
