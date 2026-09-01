# canonical_export — design spec

## Context

CodeConcise ingests per-language analyzer output through a canonical JSON manifest schema (`{version, generator, nodes: [...], edges: [...]}`, node shape `{id, display_name, type, code, path, language, generator, loc, cyclomatic_complexity, category, additional_properties}`, edge shape `{from_id, to_id, type}`). This spec designs `canonical_export`, a new output format for cobble — alongside the existing `nodes.jsonl`/`edges.jsonl`/`graph.html` — that converts cobble's own graph (`(kind, id)`-keyed, per `cobble/interpreter/project/graph_types.py`) into that manifest shape, so a CICS/JCL/COBOL corpus cobble has already analyzed can be ingested the same way any other language's analyzer output is.

This is only viable now because cobble's `CorpusIndex` (a recent addition) resolves `file_path` deterministically for every node kind that has one — `PROGRAM`, `COPYBOOK`, `JOB`, `STEP`, `INSTREAM_DATA` resolve to a real file; `TRANSACTION`/`CICS_FILE` resolve to a CSD file when configured; `DATASET`/`COBOL_FILE` are structurally not file-based and always resolve to `null`; `BMS_MAP` is not yet indexed. Without that, there would be nothing to synthesize file-locality structure from.

**This lives entirely inside cobble** — it is not a new loader in `CodeConcise-contributions-ingestion-tools`. It's cobble producing one more output format from data it already owns, with no dependency on that repo's loader conventions, `LOADER_PLAYBOOK.md`, or shared validation contract.

Two constraints shape the pipeline beyond just "produce the right JSON": the transform must be **as parallelized as possible**, and it must **bound memory usage** — no reading `nodes.jsonl`/`edges.jsonl` fully into memory before transforming.

## Placement & invocation

- `cobble/knowledge_graph/canonical_export.py` — the transform pipeline itself (streaming reader, thread-pool transform, incremental JSON writer). Sibling to the existing `graph_writer.py`/`export.py`/`render.py` in the same package — same role, another output format.
- `cobble/canonical_export.py` — thin CLI entrypoint, following `render_graph.py`'s exact convention:

  ```
  uv run python -m cobble.canonical_export --config <path>
  ```

  Derives `nodes.jsonl`/`edges.jsonl` from the same `corpus.out_dir` config field every other cobble script uses, writes to `<out_dir>/manifest.json`. `--project-name` is optional, defaulting to the config file's stem (e.g. `carddemo` from `config/carddemo.yaml`).

## Node identity

Canonical id: `f"{kind}::{id}"` (e.g. `"PROGRAM::CBEXPORT"`, `"JOB::CBEXPORT"`). Necessary because cobble's identity is `(kind, id)` — the same id string legitimately recurs under different kinds (CardDemo has `CBEXPORT` as both a `JOB` and a `PROGRAM`); a bare canonical id would silently merge them. Edges apply the same prefix to `from_id`/`to_id`.

## Type mapping

Node types carry over directly from cobble's `NodeKind` values (`PROGRAM`, `COPYBOOK`, `TRANSACTION`, `JOB`, `STEP`, `DATASET`, `BMS_MAP`, `CICS_FILE`, `INSTREAM_DATA`, `COBOL_FILE`), plus synthesized `FILE`/`DIRECTORY`. Edge types carry over from cobble's `EdgeKind` values (`CALL`, `COPY`, `XCTL`, `LINK`, `RETURN_TRANSID`, `STARTS`, `SENDS_MAP`, `RECEIVES_MAP`, `JCL_STEP_RUNS`, `READS`, `WRITES`, `UPDATES`, `DELETES`, `ENDS_BROWSE`, `DEFINES_DATASET`), plus synthesized `MADE_OF` for FILE_SYSTEM edges. The canonical schema's `type` field is free text, so no cross-loader vocabulary alignment is needed — this export is self-contained.

## Category mapping

- `CODE_CHUNK`: `PROGRAM`, `COBOL_FILE`, `COPYBOOK`, `BMS_MAP`, `JOB`, `STEP`, `TRANSACTION`, `INSTREAM_DATA` — procedural/source units.
- `DATABASE`: `DATASET`, `CICS_FILE` — external physical/logical storage references, not source.
- `FILE_SYSTEM`: synthesized `FILE`/`DIRECTORY` nodes.

## FILE_SYSTEM synthesis

For every node whose cobble `file_path` resolved to a real path (not `null`), synthesize `FILE`/`DIRECTORY` nodes (walking the path and splitting on `/`) and a `MADE_OF` edge from `FILE` to the node. Nodes with `file_path: null` (`DATASET`, `COBOL_FILE` always; `TRANSACTION`/`CICS_FILE` without a CSD; `BMS_MAP` always, since cobble doesn't index it yet; any `PROGRAM` cobble couldn't resolve — IBM system utilities, dynamic-dispatch targets) simply get no FILE_SYSTEM node — honest given they have no single file, rather than fabricating one.

## `code`, `loc`, `cyclomatic_complexity`

For every node with a resolved file, `code` is set to that file's full text. **Accepted tradeoff:** multiple nodes sharing a file (a `JOB`, its `STEP`s, and their `INSTREAM_DATA` all resolving to the same `.jcl` file) each carry a full duplicate copy of that file's text — this is the dominant memory cost in the design and is deliberately not optimized away (kept under control by the streaming pipeline never holding more than one chunk's worth of these in memory at a time — see below). `loc` is a plain non-blank-line count; `cyclomatic_complexity` is left `0` — cobble has no COBOL/JCL-specific complexity metric today, and fabricating one from full-file text (rather than the specific node's logic) would be misleading.

## Edge attrs

Dropped. The canonical schema's edge shape is `{from_id, to_id, type}` — no property field at all. cobble's edge `attrs` (`ddname`, `disp` on JCL dataset-access edges; the literal inline SYSIN text on `STEP → INSTREAM_DATA` `READS` edges) have nowhere to go without distorting node data to smuggle them through. Documented as a known, intentional lossy limitation.

## Pipeline architecture (parallel, bounded memory)

Three streaming stages — never a full read-then-transform batch:

1. **Node transform.** Streams `nodes.jsonl` line-by-line as a generator (never a full list). Lines are processed in bounded chunks through a `ThreadPoolExecutor` — the work is I/O-bound (reading each node's owning-file text for `code`) with light CPU cost (id-prefixing, category/type mapping), so threads parallelize well without the pickling overhead or shared-state complexity (`multiprocessing.Manager`, cross-process merge) a process pool would need. As each chunk's results complete, they're written straight into the output JSON's `nodes` array — never accumulated as a full list. A small thread-locked set tracks which `(FILE, path)` nodes have already been synthesized, bounded by unique file count (not node count); the first time a file is seen, its `FILE`/`DIRECTORY` nodes are emitted and the corresponding `MADE_OF` edge is buffered (small, bounded) for stage 2.
2. **Edge transform.** Same streaming/chunked/thread-pool treatment over `edges.jsonl`: id-prefixing on both endpoints, type carry-over, no file I/O. The buffered synthesized `MADE_OF` edges from stage 1 are emitted first, then cobble's real edges stream through and are written incrementally into the `edges` array.
3. **Direct streaming write.** Hand-writes the JSON incrementally — `{"version": "1.0", "generator": "cobble", "nodes": [` → comma-separated `json.dumps(node)` per completed result → `], "edges": [` → same for edges → `]}` — so the full manifest is never assembled as one in-memory Python object at any point.

No schema validation step (no `jsonschema`/canonical-schema dependency) — cobble has no such contract, and pulling one in would mean depending on `CodeConcise-contributions-ingestion-tools`'s schema file, which this design deliberately avoids per "lives entirely inside cobble" above. Correctness rests on the pipeline logic itself (e.g. FILE_SYSTEM synthesis only running for resolved file paths), not an external validator.

## Testing

`tests/knowledge_graph/test_canonical_export.py`, following cobble's existing `tmp_path`-based pytest style (same shape as `test_graph_writer.py`) — no yaml-fixture/spec-harness convention, since that's specific to the ingestion-tools repo this design doesn't touch. Should cover: node-id collision safety (two nodes sharing a raw id under different kinds resolve to distinct canonical ids), FILE_SYSTEM synthesis dedup (two nodes sharing a file produce exactly one `FILE` node and one `MADE_OF` edge per node), nodes with `file_path: null` producing no FILE_SYSTEM node, and that the output is valid JSON with the right top-level shape when read back.
