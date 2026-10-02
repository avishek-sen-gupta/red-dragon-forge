# Design: src-cfg files as JSONL

**Date:** 2026-10-02
**Status:** proposed
**Scope:** `cobble` only. Precedes `docs/superpowers/specs/2026-10-02-execution-order-walk-design.md`,
whose output uses these rows.

## Why

Every src-cfg file is one JSON document, `{"cfgs": [...], "calls": [...]}`, so
nothing can be read until all of it is written, and a tool that walks a program
cannot stream what it finds. One row per node and per edge streams, and makes the
producers, the renderers and the new reachability tool share one format instead
of each choosing.

## Who writes and reads it today

Everything goes through `cobble/dataflow/srccfg/bundle.py`:

| Role | Code | Through |
|---|---|---|
| writer | `srccfg/build_corpus.py`, one file per member | `one_cfg_document` |
| writer | `srccfg/closure.py` (`cobble-srccfg-build`), a program and its callees | `bundle_to_json` |
| typed reader | `cobble-srccfg-dot`, `-webgl`, `-query`, `viz/pathwalk_viz.py` | `load_bundle` -> `Bundle` |
| raw reader | `viz/sequence_cmd.py`, `viz/callgraph_cmd.py`, `fields/access.py` | `load_cfg_dicts` -> parsed dicts |

The raw readers index the parsed JSON (`node.get("kind")`, `entry["program"]`),
which the text-is-a-boundary rule forbids. Every field they read is already on
the typed `Node`, `Edge` or `Cfg`.

## The format

One JSON object per line, each with a `type` discriminating it, parsed through a
Pydantic row union as `knowledge_graph/graph_file.py` parses the graph file:

| `type` | Carries | Becomes |
|---|---|---|
| `program` | `program` | a `Cfg` with that name, in file order |
| `node` | `program` and every `Node` field | a `Node` of that program's `Cfg` |
| `edge` | `program`, `source`, `target`, `kind` | an `Edge` of that program's `Cfg` |
| `call` | every `BundleCall` field | a `Bundle.calls` entry |

```
{"type": "program", "program": "PROGA"}
{"type": "node", "program": "PROGA", "id": "MAIN#label", "kind": "LABEL", "paragraph": "MAIN", ...}
{"type": "edge", "program": "PROGA", "source": "MAIN#label", "target": "MAIN/0", "kind": "FLOW"}
{"type": "call", "caller": "PROGA", "node": "MAIN/3", "transfer": "CICS_XCTL", "program": "PROGB", ...}
```

**Order, guaranteed by the writer and relied on by a streaming reader:** a
program's `program` row precedes its nodes; an edge follows both nodes it joins;
a `call` follows its caller's `program` row. The first `program` row is the
bundle's seed, as the first CFG is today. Programs are written one after another,
so a writer can emit each as it is built.

Enums are written by name and nested values (`atom`, `span`, `target_operand`)
as objects, exactly as `cfg_to_dict` writes them now, so a row is the same JSON a
CFG document holds today for that node.

## Reading

- `load_bundle(path) -> Bundle` stays the one entry point, reading rows instead
  of a document. A line that is not a valid row is a `CfgDocumentError` naming
  the file and the line number.
- A file in the old shape -- a first line holding a `cfgs` key -- is refused with
  the existing `REBUILD_HINT`, as the last change of shape refused the bare list.
  Existing CFG files must be rebuilt.
- `load_cfg_dicts` and `cfg_dicts_of` are deleted. The three raw readers read the
  `Bundle`'s typed `Cfg`s.
- A row type the reader does not build into a `Bundle` (the reachability tool's
  outcome and summary rows) is declared in the union, so a misspelt `type` still
  fails, and skipped by `load_bundle`.

## Writing

- `bundle.py` gains a writer that takes a `Bundle` (or a program's `Cfg` and its
  calls, one at a time) and writes rows in the order above. `one_cfg_document`
  and `bundle_to_json` are deleted.
- Per-member files from `build_corpus.py` are named `<program>.jsonl`.
  `cobble-srccfg-build --output` names its own file; the README's examples use
  `.jsonl`.

## Units, in order

Each is its own commit, with its tests:

1. **The raw readers onto `Bundle`.** `sequence_cmd`, `callgraph_cmd` and
   `access` read `load_bundle`'s typed `Cfg`s; `load_cfg_dicts` and
   `cfg_dicts_of` go. The format does not change yet, so each reader's existing
   tests are the check that its output did not.
2. **The row types**, one class per file under `srccfg/rows/`, with a round-trip
   test: a `Bundle` covering every `Node` field (`resume`, `atom`, `span`,
   `target_operand`, `using`), every `EdgeKind`, and a `BundleCall` with
   `reasons` and `certain`, written as rows and read back equal. Nothing uses
   them yet.
3. **The flip.** Both writers and `load_bundle` move to rows together, since a
   writer and its readers must agree. Tests: the order guarantee (every edge after
   both its endpoints, every node after its `program` row), the old shape refused
   with the rebuild hint, an invalid line named by number. README: both
   descriptions of the `{"cfgs", "calls"}` shape, and the file names.

## Out of scope

- The knowledge-graph file (`cobble-build`'s `graph.jsonl`): a different schema
  with its own rows, already JSONL.
- What any reader computes. Units 1 and 3 change how readers get their CFGs, not
  what they do with them. String handling inside a reader (e.g. `sequence_cmd`
  stripping `#label`) stays as it is.
- Streaming reads in the renderers. They load the whole file as now; the format
  makes streaming possible for a reader that wants it.
