# cobble: entry points and configuration

cobble is the forge's static analyser. It reads a COBOL/CICS/JCL corpus without running it and
writes a knowledge graph, per-program control-flow graphs, and a byte-level field dataflow.
The end-to-end recipe is [analyse a corpus](../../how-to/analyse-a-corpus.md).

Every entry point runs from the forge root as `uv run --no-sync <command>`. Each prints its
full flag list with `--help`.

## Entry points

| Command | Reads | Page |
|---|---|---|
| `diagnose-copybooks` | corpus config | [diagnostics](diagnostics.md) |
| `diagnose-cobol` | corpus config | [diagnostics](diagnostics.md) |
| `diagnose-jcl` | corpus config | [diagnostics](diagnostics.md) |
| `cobble-sym` | corpus config `[bms]` | [knowledge-graph](knowledge-graph.md) |
| `cobble-csd` | corpus config | [knowledge-graph](knowledge-graph.md) |
| `cobble-parse-corpus` | corpus config | [knowledge-graph](knowledge-graph.md) |
| `cobble-expand-corpus` | corpus config | [knowledge-graph](knowledge-graph.md) |
| `cobble-build` | corpus config | [knowledge-graph](knowledge-graph.md) |
| `cobble-compare` | graph file | [knowledge-graph](knowledge-graph.md) |
| `cobble-render` | graph file | [knowledge-graph](knowledge-graph.md) |
| `cobble-render-webgl` | graph file | [knowledge-graph](knowledge-graph.md) |
| `cobble-srccfg-build` | srccfg config | [srccfg](srccfg.md) |
| `cobble-srccfg-query` | CFG file | [srccfg](srccfg.md) |
| `cobble-srccfg-reachability-walk` | CFG file | [srccfg](srccfg.md) |
| `cobble-srccfg-dfs-walk` | CFG file | [srccfg](srccfg.md) |
| `cobble-srccfg-dot` | CFG file | [srccfg](srccfg.md) |
| `cobble-srccfg-webgl` | CFG file | [srccfg](srccfg.md) |
| `cobble-srccfg-subgraph` | CFG file | [srccfg](srccfg.md) |
| `cobble-extents` | ASG cache | [field-dataflow](field-dataflow.md) |
| `cobble-dataflow-fixpoint` | ASG cache, extents | [field-dataflow](field-dataflow.md) |
| `cobble-dataflow-fixpoint-query` | fixpoint output | [field-dataflow](field-dataflow.md) |
| `cobble-dataflow-fixpoint-diagnose` | ASG cache | [field-dataflow](field-dataflow.md) |
| `cobble-dataflow-area-need` | ASG cache, extents | [field-dataflow](field-dataflow.md) |
| `cobble-dataflow-combine` | corpus config, fixpoint output | [field-dataflow](field-dataflow.md) |
| `cobble-fields-access` | CFG file, ASG cache | [field-dataflow](field-dataflow.md) |
| `cobble-access-query` | access rows, extents | [field-dataflow](field-dataflow.md) |
| `cobble-depgraph` | depgraph config | [field-dataflow](field-dataflow.md) |
| `cobble-depgraph-render` | depgraph config | [field-dataflow](field-dataflow.md) |
| `cobble-fields-trace` | ASG cache | [trace](trace.md) |
| `cobble-trace-query` | trace file | [trace](trace.md) |
| `cobble-viz-callgraph` | graph file, CFG file | [viz](viz.md) |
| `cobble-viz-sequence` | CFG file | [viz](viz.md) |
| `cobble-viz-render` | viz JSON | [viz](viz.md) |
| `cobble-viz-pathwalk` | CFG file, path records | [viz](viz.md) |
| `cobble-bms-metadata` | corpus config `[bms]` | [viz](viz.md) |
| `cobble-bms-render` | corpus config `[bms]` | [viz](viz.md) |

## Environment and tools

| Needed by | What | Source |
|---|---|---|
| `cobble-parse-corpus`, `cobble-expand-corpus`, `diagnose-cobol` | `PROLEAP_BRIDGE_JAR` | `. ./bridge-env.sh` |
| `cobble-build`, `diagnose-jcl` | `JCL_BRIDGE_JAR` | `. ./bridge-env.sh` |
| `cobble-sym`, `cobble-bms-metadata`, `cobble-bms-render` | `hlasm_export` at `cicada/third-party/che-che4z-lsp-for-hlasm-fork/build/bin/` | `make setup` or `make hlasm` |
| `cobble-render-webgl`, `cobble-srccfg-webgl`, `cobble-depgraph-render` | Graphviz `sfdp` | system package |
| `cobble-srccfg-subgraph` | Graphviz `dot`, and `unflatten` with `--balance` | system package |

Only the two parse stages start a JVM for COBOL. Every later stage reads the ASG cache they
write.

## Paths

Paths in every config expand `~` and environment variables. A relative path resolves against
the working directory of the command, not against the config file. One exception:
`cobble-bms-metadata` and `cobble-bms-render` resolve a relative `macros_dir` against `cobble/`
(red-dragon-forge-jy9).

## Corpus config

Read by the diagnoses, `cobble-sym`, `cobble-csd`, the two parse stages, `cobble-build`,
`cobble-dataflow-combine`, `cobble-dataflow-area-need` and the two BMS commands.
`cobble/config/carddemo.toml` is the CardDemo instance; its paths are relative to `cobble/`.

```toml
[corpus]
cobol_dir = "path/to/cobol"
cobol_globs = ["*.cbl", "*.CBL"]
jcl_dir = "path/to/jcl"
jcl_globs = ["*.jcl", "*.JCL"]
proclib_dirs = ["path/to/proclib"]
csd_files = ["path/to/site.csd"]
copybook_dirs = ["path/to/sym", "path/to/copybooks"]
copybook_extensions = ["cpy", "txt"]
asg_dir = "path/to/parsed"

[[corpus.transid_rules]]
member_pattern = "^PGM(?P<tail>.{3})$"
transid_template = "T{tail}"

[bms]
bms_dir = "path/to/bms"
bms_globs = ["*.bms"]
macros_dir = "cobble/bms-macros"
sym_dir = "path/to/sym"
```

| Key | Required | Default | Meaning |
|---|---|---|---|
| `cobol_dir`, `cobol_globs` | yes | | COBOL members, selected by listing the directory |
| `jcl_dir`, `jcl_globs` | yes | | JCL members |
| `proclib_dirs` | no | `[]` | cataloged PROC libraries |
| `csd_files` | no | `[]` | CSD exports. Empty skips the CICS flow stage. Each entry must be a readable file or `cobble-build` refuses to start |
| `copybook_dirs` | yes | | searched in order, not recursively. Each must exist or the parse stages refuse to start |
| `copybook_extensions` | no | `""`, `cpy`, `CPY`, `cob`, `cbl`, `copy`, `COPY` | a `COPY X` resolves to `X` or `X.<ext>`, case-insensitively. `""` resolves a bare name. Keep `cpy` when `cobble-sym` writes into a listed dir |
| `asg_dir` | yes | | the ASG cache `cobble-parse-corpus` writes and every later stage reads |
| `transid_rules` | no | `[]` | ordered regex and template pairs for `cobble-csd`. The first `member_pattern` that matches wins; its named groups fill `transid_template`. A table array ends the `[corpus]` table, so it comes after every bare key |
| `bms_dir`, `bms_globs` | `bms_dir` yes | `["*.bms"]` | BMS map sources |
| `macros_dir` | yes | | assembler SYSLIB for `hlasm_export`; `cobble/bms-macros` holds the `DFHMSD`/`DFHMDI`/`DFHMDF` macros |
| `sym_dir` | yes | | where `cobble-sym` writes `<map>.cpy` |

Keys a table does not declare are ignored.

## srccfg config

Read by `cobble-srccfg-build`. Copy `cobble/config/srccfg.example.toml`.

```toml
[srccfg]
asg_dir = "path/to/parsed"
out_dir = "path/to/srccfg"
source_dir = "path/to/cobol"
```

| Key | Required | Meaning |
|---|---|---|
| `asg_dir` | yes | the ASG cache |
| `out_dir` | yes | output directory for the per-member CFGs |
| `source_dir` | no | the member source directory. When set, each source span names `<source_dir>/<member>.txt`; when absent, the file is blank |

## depgraph config

Read by `cobble-depgraph` and `cobble-depgraph-render`.

```toml
[output]
asg_dir = "path/to/parsed"
graph_dir = "path/to/depgraph"

[collapse]
window = 1
passthrough_names = ["WS-TEMP"]
passthrough_patterns = ["^WS-EDIT($|-)"]
```

| Key | Required | Default | Meaning |
|---|---|---|---|
| `output.asg_dir` | yes | | the ASG cache |
| `output.graph_dir` | yes | | where `edges.jsonl`, `nodes.jsonl`, `pairs.json` and the page go |
| `collapse.window` | no | `1` | how many MOVEs apart `A -> B` and `B -> C` may be and still collapse through a pass-through `B` |
| `collapse.passthrough_names` | no | `[]` | variables the collapse routes through |
| `collapse.passthrough_patterns` | no | `[]` | regexes over variable names, same effect |

An absent `[collapse]` collapses nothing.

## Test configs

The acceptance tests read two optional configs and skip without them:
`cobble/config/fields-tests.toml` (copy `fields-tests.example.toml`) and
`cobble/config/srccfg-tests.toml` (copy `srccfg-tests.example.toml`).
`cobble/config/carddemo-fields-tests.toml` is the CardDemo instance. Every other file under
`cobble/config/` is git-ignored, because a config names the corpus it points at.

## Package boundaries

cobble uses the workspace's static surface only: `cobol_asg.*`, `cobol_memory`,
`cics.{cics_parser,cics_visitor,cics_grammar,csd_parse,statements,bms}`, `bms_copybook_gen`,
`jackal.{model,dsn,value_parts,tso,jcl.*}` and `squall.{statements,parser}`. It must not import
the interpreter or any runtime module (contracts `cobble-no-interpreter` and
`cobble-no-runtime`), and nothing imports cobble. The contracts are in
[`.importlinter`](../../../.importlinter).
