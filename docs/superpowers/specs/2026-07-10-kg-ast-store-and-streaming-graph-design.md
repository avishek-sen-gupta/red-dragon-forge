# Knowledge-Graph AST Store + Streaming Graph JSONL — Design

**Date:** 2026-07-10
**Status:** design (post-grill, pre-plan)

## Goal

Let the production `knowledge_graph` pipeline handle large (multimillion-line)
codebases by removing the two memory ceilings in today's single-process,
in-memory, full-rebuild design:

1. **Parsed ASGs held in RAM** — a strategy-backed **AST store** keeps parsed
   ASGs on disk and loads them one at a time, and parses **in parallel** so a
   large corpus finishes in reasonable wall-clock.
2. **The whole graph built in networkx before anything is written** — a
   **streaming graph sink** writes edges to JSONL as extractors produce them and
   buffer-merges nodes, never building the whole graph in memory; networkx is
   reconstructed *from* the JSONL only when the renderer needs it.

Plus a **git-tracked fitness golden** so the invariant this change must preserve
— the CardDemo graph is **449 nodes / 803 edges** — is enforced by a real
regression guard rather than today's partial structural assert.

## Scope / not touched (IMPORTANT)

All changes land in the **main production repos** — red-dragon (`interpreter/`),
cicada (`cics/`), forge (`knowledge_graph/`, `tests/`). The
`experiments/standalone-graph/` tree is **explicitly out of scope and must not
be modified** — it is a separate proof-of-concept that gets regenerated on its
own if ever needed. Nothing in this design edits `experiments/`.

## Locked decisions (from the grill)

- **Store key:** full `md5` hex (128-bit), **not** the inherited `[:8]` — 32-bit
  truncation collides at ~65k files, exactly the scale we target.
- **Store parses in parallel** (keeps `parallel_parse_to_cache`'s thread-pool),
  exposing `parse_all(sources)` (eager, parallel — the throughput path) +
  `get(path) -> CobolASG` (accessor).
- **Strategies:** `MEMORY` and `DISK`. **Default `DISK`** (bounded memory is the
  safe default for large corpora); `MEMORY` is an opt-in for speed on small
  corpora.
- **MEMORY ≡ DISK by construction:** the store carries the `preprocessor` and
  applies it on **both** paths (DISK applies it on load), so the two strategies
  return identical ASGs.
- **Consolidation:** one shared store; refactor `cobol_compile.parallel_parse_to_cache`
  onto it. (Its consumer reads the cached JSON as a dict; the KG reads it as a
  `CobolASG` via `from_dict` — the same cached JSON, one trivial adapter, not a
  divergence.)
- **Graph dedup:** stream **edges** (seen-set, keep-first); **buffer-merge
  nodes** (see Component B). No networkx during the build.
- **networkx fate:** rebuilt *from the final JSONL* for the renderer (its only
  consumer).
- **Streaming depth:** per-file for JCL / CALL-COPY / FILE-CONTROL; CICS streams
  per verb through the existing `on_verb` observer seam.
- **CICS failure isolation:** per-program `try/except`, matching the other
  extractors; the all-or-nothing outer catch is removed.
- **Loud failures:** every per-unit failure (all four extractors) emits a
  `logger.warning` at the failure point with the unit name + exception, on top
  of the end-of-run rollup. **Warn-and-continue** — a bad unit doesn't abort the
  build; the golden is the backstop for count regressions.
- **No backward compatibility:** the sink-based API replaces the list-returning
  `extract_transaction_flow_graph`; `extract_transaction_flow_map` (test-only) is
  deleted; callers/tests migrate.
- **Fitness golden:** git-tracked, deterministically sorted `nodes.jsonl` /
  `edges.jsonl`; **identity compare** (attrs + file_path excluded); a regen path.

## Component A — `AstStore` (red-dragon, `interpreter/`)

- **Home:** a new module next to the parser (e.g. `interpreter/cobol/ast_store.py`).
- **API:**
  - `parse_all(sources: dict[Path, bytes], preprocessor=_IDENTITY) -> None` —
    eager, **parallel** (thread pool, as `parallel_parse_to_cache` today),
    populate the cache. This is the parse-throughput path.
  - `get(path: Path) -> CobolASG` — return the parsed ASG for a
    previously-populated (or, if not present, lazily-parsed) path.
- **Strategies (the *where-cached* axis):**
  - `DISK` (**default**) — cache raw bridge JSON as `{stem}-{fullmd5}.ast.json`
    in a per-run dir; `get` does `read_text → json.loads → preprocessor →
    from_dict`, one ASG live at a time.
  - `MEMORY` (opt-in) — hold each parsed `CobolASG` in a dict.
- **Key:** **full** `md5(str(path))` hex. **Lifetime:** a per-run dir the store
  owns (`TemporaryDirectory`, cleaned at close) or a caller-supplied dir.
- **Preprocessor equivalence:** `parse_all`/`get` apply the same `preprocessor`
  in both strategies (DISK on load), mirroring `parse()` exactly — so a
  non-identity preprocessor can never make MEMORY and DISK diverge. Default
  identity preserves today's `cobol_compile` and FILE-CONTROL behavior verbatim.
- **Consolidation:** refactor `interpreter/project/cobol_compile.parallel_parse_to_cache`
  onto the store's `DISK` path. Guarded by its existing tests (`test_cobol_parser`,
  `test_cobol_compile`, `test_cobol_frontend_cache`).

## Component B — `GraphWriter` streaming sink (forge, `knowledge_graph/`)

- **Home:** `knowledge_graph/graph_writer.py`; a context manager owning two output
  files.
- **Edges — streamed.** Seen-set on `(source, source_kind, target, target_kind,
  kind)`; append the first occurrence, skip later ones (matches
  `_dedupe_edges`). Edges are written immediately and forgotten. Stream order =
  today's concat order (`jcl + call + cics + file`) so "keep-first" is preserved.
- **Nodes — buffered and merged.** A dict `(kind, id) -> {file_path, attrs}`; on
  each `add_node`, `file_path = existing or new` and `attrs = {**existing,
  **new}` (reproducing `merge_graph`, incl. the bare-endpoint-then-real-node
  upgrade); **flush all nodes at `close()`**. Memory is O(distinct nodes) — the
  seen-set floor we already accept, not a new ceiling. (Node attrs are unused
  today; file_path carries the placeholder values Component D excludes and
  issue-`c` will fix — buffer-merge *preserves* them rather than silently
  dropping them.)
- **Output:** `nodes.jsonl` / `edges.jsonl` in the exact row shape
  `export.write_ndjson` emits. **Crash safety:** write to temp files, `rename` on
  `close()` (a crashed build leaves no truncated output).
- **networkx-from-JSONL:** the renderer path does `merge_graph(*read_ndjson(...))`
  → print counts + `render_html(graph)` (unchanged signature). Render is the only
  networkx consumer.

## Component C — streaming wiring

### Per-file extractors (forge, `build_carddemo_graph.py`)

`_build_jcl_graph`, `_build_call_copy_graph`, `_build_batch_file_graph` take the
`GraphWriter` and, in their existing per-file loop, push each file's nodes/edges
via `writer.add_*` instead of `all_nodes.extend(...)`. Peak graph-object memory
becomes one file's worth. FILE-CONTROL adopts the store:
`extract_cobol_file_graph(asg: CobolASG)` (parse externalized), and the wrapper
does `asg = store.get(path)` after a `parse_all` of the batch files.

Each per-file `except` emits a **`logger.warning`** (unit name + exception,
`exc_info` for a traceback) at the failure point, in addition to the `failures`
rollup. Warn-and-continue.

### CICS via the existing observer seam (cicada)

The CICS lowering strategy already fires `self._observer.on_verb(verb)` per EXEC
CICS verb. Replace the accumulating `_CollectingObserver` with a streaming one:

- **`GraphSink` Protocol** (`add_node`/`add_edge` over `GraphNode`/`GraphEdge`) —
  **cicada-local** (Protocols are structural, so forge's `GraphWriter` satisfies
  it; `knowledge_graph`→`cics` imports are allowed, `cics`→`knowledge_graph` is
  not). No red-dragon / `graph_types` change for this.
- **`GraphEmittingObserver(program_name, bms_mapsets, sink)`** in
  `verb_source_lowering`: `on_verb(verb)` → `edge = _verb_edge(verb,
  bms_mapsets)` → if non-None, push endpoints + edge to the sink. `bms_mapsets`
  stays plumbed (KG passes `{}`; BMS field-attrs are a non-goal). `_verb_edge`
  stays in `flow_graph_core` (shared transducer — the flow_map split holds).
- **`extract_transaction_flow_graph(csd_source, bms_mapsets, cobol_sources,
  parser, sink, failures)`** — streaming, returns nothing: parse the CSD → emit
  structural edges (`STARTS` per transaction + `TRANSACTION`/`PROGRAM` nodes;
  `DEFINES_DATASET` per CSD file) to the sink; compile each program under a
  `GraphEmittingObserver`. **Per-program `try/except`** appends to `failures` and
  emits a `logger.warning`; the all-or-nothing outer catch is removed.
- **No back-compat.** Delete `extract_transaction_flow_map` (test-only). Migrate
  `test_flow_graph.py` (×12) to a small list-collecting test sink; delete
  `test_flow_map.py`. Production callers: `build_carddemo_graph` (×1),
  `tests/integration/test_knowledge_graph_carddemo` (×1) — both migrate. Nothing
  external calls these.

## Component D — fitness golden (forge)

- **Golden data (git-tracked):** `tests/integration/fitness/carddemo_graph.nodes.jsonl`
  + `.edges.jsonl`, written **sorted** (nodes by `(kind, id)`, edges by
  `(source, source_kind, target, target_kind, kind)`) so review diffs are clean.
- **Compare (identity only):** run the build → set-compare output vs golden on
  node `(kind, id)` + edge `(source, source_kind, target, target_kind, kind)` —
  **attrs and file_path excluded** (matches today's `compare.py`; file_path is
  the placeholder handled by issue-`c`). Fail on any missing/extra.
- **Regen path:** a `make` target / script to refresh the golden when a change
  *intentionally* moves the graph (the diff shows exactly what shifted).
- **Test:** a `tests/integration` test (gated on the bridge JARs + hlasm + the
  pinned `vendor/carddemo` submodule) that builds the graph and asserts the
  output equals the golden — the real regression guard, replacing the current
  partial structural assert.

## Behavior preservation & fitness

- The full CardDemo build still produces **449 nodes / 803 edges**, now enforced
  by the golden.
- Streaming reproduces `_dedupe_edges` + `merge_graph` exactly: edge seen-set =
  `_dedupe_edges` keep-first; node buffer-merge = `merge_graph`'s file_path-or +
  attr-union. A **dedicated `GraphWriter` unit test** covers the three node-merge
  cases (attr-union new-wins; file_path first-non-None; bare-endpoint-then-real
  upgrade) — the guard for node correctness the identity golden can't see.
- Suites green per repo (gate = each repo's `make test`):
  - **red-dragon** — `AstStore` unit tests + `parallel_parse_to_cache`
    refactor's existing guards.
  - **cicada** — observer + streaming `extract_transaction_flow_graph`, with
    `test_flow_graph` migrated / `test_flow_map` deleted.
  - **forge** — `GraphWriter` unit tests (incl. node-merge), networkx-from-JSONL
    render, and the golden compare.

## Cross-repo execution (ordered by blast radius)

1. **red-dragon** — `AstStore` (parallel `parse_all` + `get`, MEMORY/DISK,
   full-hex, preprocessor-on-both) + refactor `parallel_parse_to_cache`.
   `make test`, commit, push, bump `vendor/red-dragon`.
2. **cicada** — `GraphSink` + `GraphEmittingObserver` + streaming
   `extract_transaction_flow_graph` + delete `extract_transaction_flow_map` +
   migrate/delete flow tests. `make test`, commit.
3. **forge** — `GraphWriter` (stream edges / buffer-merge nodes / temp-rename) +
   per-file streaming wiring + `extract_cobol_file_graph(asg)` adoption +
   networkx-from-JSONL render + fitness golden & compare + loud per-unit
   warnings. KG integration + golden green, commit.

## Non-goals

- **Content-hash / cross-run persistent cache** — per-run only.
- **LRU / hybrid store strategy** — `MEMORY` + `DISK` only.
- **Parallel *extractor* fan-out** — the store parses in parallel, but the four
  extractors run sequentially as today; only their memory profile changes.
- **Populating BMS field-attrs on edges** — `bms_mapsets` stays plumbed, KG
  passes `{}`.
- **Making `file_path` uniformly meaningful** — filed as issue-`c`; this design
  *preserves* the current placeholder behavior, it does not fix it.
- **Reducing the dedup/node buffer below O(graph size).**
- **Graph-DB adapters / replacing vis-network** — the JSONL is the interchange
  they *could* later consume.
- **Any change under `experiments/`** — out of scope (see Scope).

## Fitness function

- **Per change:** the owning repo's `make test` stays green.
- **Overall:** the full build produces **449 nodes / 803 edges**, matches the
  git-tracked golden on identity, `render_html` still renders from the JSONL, the
  `GraphWriter` node-merge unit test passes, and all three repos' suites are
  green.
