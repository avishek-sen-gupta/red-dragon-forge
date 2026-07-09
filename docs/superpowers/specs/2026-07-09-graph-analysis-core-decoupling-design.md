# Graph-Analysis-Core Decoupling — Design

**Date:** 2026-07-09
**Status:** design (pre-plan)

## Goal

Refactor the production code so the **static-analysis core** that the knowledge-graph
pipeline needs (COBOL CALL/COPY extraction, CICS transaction-flow extraction, JCL structure,
the graph schema) is cleanly separated from the **heavy machinery** it does NOT need (the
red-dragon VM/executor, IR lowering, the tree-sitter multi-language extractors, IR-typed
project link types). After the refactor, the standalone graph extractor could copy the
separated core modules **byte-for-byte** (import-rewiring only, no deletions) — while
production behaves **identically**, importing the same core plus the heavy content it always
used.

This is **in-repo modularization only** — no repo split. The split (if ever wanted) becomes
trivial afterward: the graph pipeline's dependency collapses to a set of VM-free leaf modules.

Motivation and evidence: the experiment at `experiments/standalone-graph/` already proved the
graph is reproducible with zero lowering/VM (fitness 449 nodes / 803 edges), and a per-file
feasibility analysis classified all six deletion-bearing files as clean, behavior-preserving
seams (see "Evidence" below).

## The unifying principle

For each file, **extract the light analysis-core the graph pipeline needs into a clean leaf
module; leave the heavy content where it is; the fat file re-exports (or delegates to) the
leaf so every existing consumer is untouched.** The graph pipeline copies the *leaf*,
byte-for-byte; production imports the fat file exactly as before.

This is the inverse of "slim the file and re-import the deleted stuff" — we lift out the small
clean piece, not the large messy one. Consequence: near-zero consumer churn (re-export shims),
and the leaf modules are genuinely VM/lowering/tree-sitter-free.

## Per-file decomposition

The six files carry the graph pipeline's only couplings to heavy machinery. New leaf modules
are what the graph pipeline copies byte-for-byte.

| # | Repo | Fat file | New leaf module (graph pipeline copies this) | Heavy content that stays in the fat file | Back-compat mechanism |
|---|------|----------|----------------------------------------------|------------------------------------------|-----------------------|
| 1 | red-dragon | `interpreter/project/imports.py` | `interpreter/project/cobol_imports.py` — the COBOL Lark grammar/transformer + `_extract_cobol_imports` + a COBOL-facing `extract_imports` | tree-sitter parser factory + 14 per-language extractors + `_EXTRACTORS` registry dispatcher | fat `imports.py`'s `extract_imports` delegates COBOL to the leaf; consumers keep importing `extract_imports` from `imports` |
| 2 | cicada | `cics/dispatcher.py` | `cics/csd_parse.py` — CSD Lark grammar/transformer + `parse_csd`/`parse_csd_files` | the VM dispatcher (`run_cics`, `CicsRegion`, `_advance_routing`, `InputEvent`, …) | `dispatcher.py` re-exports `parse_csd`/`parse_csd_files` from `csd_parse` |
| 3 | red-dragon | `interpreter/project/types.py` | `interpreter/project/import_types.py` — `ImportRef` + `ImportKind` | `ExportTable`/`ModuleUnit`/`LinkedProgram`/`CyclicImportError` + their IR/CFG imports | `types.py` re-exports `ImportRef`/`ImportKind` from `import_types` |
| 4 | red-dragon | `interpreter/constants.py` | `interpreter/language.py` — the `Language` enum | label-prefix consts, `LLMProvider`, `FoundationTypeName`, `CanonicalLiteral`, `Variance`, … | `constants.py` re-exports `Language` from `language` |
| 5 | red-dragon | `interpreter/frontend_extension.py` | keep `DialectParser`/`NullDialectParser` here (already leaf) — move the heavy piece OUT to `interpreter/frontend_extension_lowering.py` (`RedDragonExtensionLoweringStrategy`) | (moves out) | `frontend_extension.py` re-exports `RedDragonExtensionLoweringStrategy` from the new module |
| 6 | cicada | `cics/flow_map.py` | `cics/flow_graph_core.py` — everything from `{program: [CicsVerb]}` onward (`_verb_edge`, `_enrich_verb`, node/edge build, CSD file edges, `extract_transaction_flow_map`/`extract_transaction_flow_graph`) | (see "flow_map split") | two thin sourcing drivers compose over the shared core |

### The `flow_map` split (the one genuine restructure)

`flow_map` is not "extract a leaf + re-export" — its heavy content (`_CollectingObserver` +
`compile_cics_program`/`build_cics_spec`) is *active production logic* that produces the
`{program: [CicsVerb]}` map. So it splits by **separating verb acquisition (varies) from graph
building (shared)**:

- `cics/flow_graph_core.py` — **shared, verbs-as-data**: takes `transid_to_program` +
  `verbs_by_program: dict[str, list[CicsVerb]]` (+ BMS/CSD inputs) and builds the graph.
  `_verb_edge`, `_enrich_verb`, node/edge construction, CSD file edges, and the two public
  functions live here, **byte-identical** to today's downstream logic. This is the module the
  graph pipeline copies.
- `cics/verb_source_lowering.py` — **production driver**: compiles each program through the
  CICS lowering strategy and reads `_CollectingObserver` → `{program: [CicsVerb]}`. Holds the
  two lowering imports.
- The graph pipeline supplies its OWN sourcing driver (parse → ProLeap-JSON `EXEC_CICS` walk →
  verbs) — this already exists in the experiment; it never imports the lowering module.
- `cics/flow_map.py` becomes a thin back-compat composition: production's public entry points
  keep their signatures, internally calling `verb_source_lowering` then `flow_graph_core`.
  Existing callers of `extract_transaction_flow_graph` see no change.

No dependency-injection parameter, no public-API change — just composition over a
verbs-as-data boundary that already implicitly exists (`_compile_all_programs` already returns
exactly that dict).

## Behavior preservation (the hard constraint)

Every edit is a **pure move + re-export/delegate** — no logic is rewritten (except `flow_map`,
which is a pure *reorganization* of already-separated phases, not a logic change). The two-
sided proof:

1. **Every existing production suite stays green** — cicada (~377), jackal, red-dragon's own
   unit+integration suites, and the forge aggregate. This is the real regression gate; run
   each repo's suite after its files change.
2. **The experiment then copies the new leaf modules byte-for-byte** (import-rewiring only, the
   deletions in its current port become unnecessary) and still reproduces **449 nodes / 803
   edges** via `experiments/standalone-graph/compare.py`. This proves the seam lands exactly
   where the port's deletions were.

Re-export shims are permanent (approved) — no consumer import-site migration in this work;
the 215 importers of `interpreter.constants` and ~24 of `interpreter.project.types` are left
untouched by design.

## Cross-repo execution

The refactor spans three repos (approved: do it properly, bump pins):

- **red-dragon** (`~/code/red-dragon`, the canonical clone — NOT the `vendor/` read-through):
  files 1, 3, 4, 5. Run red-dragon's own suite, commit, push.
- **cicada** (`cicada/` in the monorepo): files 2, 6. Run cicada's suite (`make test`), commit,
  push.
- **red-dragon-forge**: bump `vendor/red-dragon` pin to the new red-dragon SHA; the forge
  aggregate suite + the standalone-graph experiment are the final cross-repo gate.

Order by blast radius ascending, so the risky wiring is validated on small changes first:
`dispatcher`/`frontend_extension` (tiny, self-contained) → `imports`/`flow_map` (the
interesting delegations) → `types`/`constants` (shim, wide but mechanical).

## Evidence (why each seam is clean)

From the per-file feasibility analysis (2026-07-09):

- **imports.py**: the COBOL path references none of the tree-sitter symbols; the 14 extractors
  + `_EXTRACTORS` + factory are strictly private (0 external consumers). `extract_imports`'s
  non-COBOL branch is the only core→heavy reference — resolved by delegation.
- **dispatcher.py**: CSD parser and VM dispatcher share nothing; the VM never calls
  `parse_csd`. Independent halves.
- **types.py**: `ImportRef`/`ImportKind` reference nothing deleted; the heavy types depend on
  `ImportRef` one-way (no cycle).
- **constants.py**: `Language` is a self-contained `StrEnum`; deletion only severs a
  `type_name` import `Language` never used.
- **frontend_extension.py**: `DialectParser` is independent of the lowering strategy (only a
  docstring mention); the strategy's type params are `TYPE_CHECKING`-only.
- **flow_map.py**: `_compile_all_programs` already returns `{program: [CicsVerb]}` — the
  verbs-as-data boundary is pre-existing; only the acquisition varies.

None of the six are entangled (no mutual recursion, no behavior-risk on separation).

## Non-goals

- **No repo split** — this makes it trivial later, but does not do it.
- **No consumer import-site migration** — re-export shims stay; the 215/24 importers are not
  touched.
- **No logic changes** — pure moves + re-exports; `flow_map` is a phase reorganization, not a
  rewrite. Production's CICS flow extraction keeps using the lowering verb-source by default.
- **No new graph capability** — this is decoupling only; the graph output is unchanged
  (449/803).

## Fitness function (per step and overall)

- Per file changed: the owning repo's full suite stays green (exact pre-change counts).
- Overall: forge aggregate green + `experiments/standalone-graph/` updated to copy the new
  leaf modules byte-for-byte (no deletions in those files' port copies) + `compare.py` still
  reports 449/803 empty diff.
