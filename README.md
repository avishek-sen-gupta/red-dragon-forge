# cobble

[![reproduce-graph](https://github.com/avishek-sen-gupta/cobble/actions/workflows/reproduce.yml/badge.svg)](https://github.com/avishek-sen-gupta/cobble/actions/workflows/reproduce.yml)

A **standalone, VM-free** knowledge-graph extractor for COBOL/CICS/JCL
mainframe codebases. It is a file-by-file **port** of the streaming graph
pipeline in the `red-dragon-forge` monorepo, lifted into its own repository to
prove the extraction is decoupled from the RedDragon interpreter/VM. Point it
at any corpus via a YAML config (see [Point this at your own
codebase](#point-this-at-your-own-codebase)); the AWS **CardDemo** corpus is
this repo's proof case, where it reproduces the **exact same 449-node /
803-edge graph** starting from nothing but:

- the **CardDemo repo** (a git submodule, the source corpus), and
- the parsers/tools, all **built from source** (submodules + copied Maven source).

Everything generated (the ANTLR CICS parser **and** the BMS symbolic copybooks)
is **generated here from its grammar/source**. No production Python is imported at
runtime, and nothing pre-generated is shipped: the only things tracked are
hand-written source, grammar source (`.g4` / `.bms` / `.mac`), and submodule pins.

## Reproduce from a fresh clone

Requires: `git`, JDK 21+, Maven (bridges); a C++ toolchain (clang or gcc) with
CMake + Ninja (`hlasm_export`); and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone <this-repo> cobble && cd cobble
./build.sh   # submodules -> build tools -> generate parser+copybooks -> extract -> verify 449/803
```

`make` targets:

| Target | What it does |
|--------|--------------|
| `tools` | Build hlasm, proleap fork, and bridge JARs |
| `codegen` | Generate the CICS parser and BMS copybooks from their grammars |
| `build` | Extract the graph to `out/` |
| `compare` | Identity-diff vs `reference/` (449/803) |
| `render` | Render `out/` as an interactive HTML graph |
| `canonical` | Export `out/` as CodeConcise's canonical `manifest.json` |
| `test` | Run the pytest unit suite |
| `fmt` | Format with black |
| `lint` | Run import-linter, pyright, and python-fp-lint |
| `clean` | Drop all generated artifacts |

### Build the graph from CardDemo

`./build.sh` runs the full pipeline end to end. To run it step by step instead:

```bash
git submodule update --init                        # fetch the CardDemo corpus + parser/HLASM forks
make tools                                          # build hlasm_export + the proleap fork + both bridge JARs
make codegen CONFIG=config/carddemo.yaml            # generate the CICS parser (ANTLR) + BMS symbolic copybooks
make build CONFIG=config/carddemo.yaml              # extract the graph -> out/nodes.jsonl, out/edges.jsonl
make compare                                        # identity-diff out/ vs reference/ (must be empty: 449/803)
```

`CONFIG=` is a required argument to `make build`/`make sym` (and transitively
`make codegen`, which depends on `sym`); there's no default, so a bare
`make build` fails with a clear error instead of silently assuming CardDemo.
`build.sh` hardcodes `CONFIG=config/carddemo.yaml` for its own from-scratch
CardDemo run.

`make build` re-runs the four extractors (CALL/COPY, CICS flow, JCL, batch
FILE-CONTROL) over `vendor/carddemo` from scratch every time; safe to re-run
after touching any extractor code or the corpus submodule.

### Canonical export

```bash
make canonical NODES=out/nodes.jsonl EDGES=out/edges.jsonl OUTPUT=out/manifest.json PROJECT_NAME=carddemo
```

This is the point of cobble: converting a COBOL/CICS/JCL corpus's graph into
CodeConcise's canonical ingestion manifest shape (`{version, generator, nodes,
edges}`), so a mainframe corpus cobble has analyzed can be ingested the same
way any other language's analyzer output is. Synthesizes `FILE`/`DIRECTORY`
nodes and `MADE_OF` edges for every node whose `file_path` resolved to a real
file; nodes with no resolved file (`DATASET`, `COBOL_FILE`, unconfigured
`TRANSACTION`/`CICS_FILE`, `BMS_MAP`) get no such synthesis. Streaming and
thread-pool-parallel throughout, with bounded memory; see
`docs/superpowers/specs/2026-07-11-canonical-export-design.md` for the full
design, including the deliberate lack of schema validation and the known
lossy limitation (edge `attrs` have no home in the canonical edge shape and
are dropped).

Unlike `build`/`sym`/`render`, this doesn't take a `--config`/`CONFIG=` at
all: `NODES=`, `EDGES=`, `OUTPUT=`, and `PROJECT_NAME=` are all required
explicit paths/values, so it can run against any `nodes.jsonl`/`edges.jsonl`
pair regardless of which config (if any) produced them.

### Point this at your own codebase

`cobble.build_graph`/`cobble.generate_sym` take a required `--config <path>`
flag; nothing about a specific corpus is hardcoded in Python. `make build`/
`make sym` take a matching required `CONFIG=<path>` argument, which they
simply forward. `config/carddemo.yaml` is both the config CardDemo uses and a
template for your own corpus:

```yaml
corpus:
  cobol_dir: path/to/your/cobol
  cobol_globs: ["*.cbl", "*.CBL"]
  jcl_dir: path/to/your/jcl
  jcl_globs: ["*.jcl", "*.JCL"]
  proclib_dirs:
    - path/to/your/proclib
  csd_files:               # omit or leave empty ([]) if your corpus has no CICS
    - path/to/your/site.csd
  copybook_dirs:
    - path/to/your/copybooks
  copybook_extensions: ["cpy", "txt"]   # omit unless your copybooks are named unconventionally
  out_dir: out

bms:
  bms_dir: path/to/your/bms
  bms_globs: ["*.bms"]     # omit unless your map sources are named unconventionally
  macros_dir: bms-macros
  sym_dir: sym
```

Every path is relative to wherever you invoke the script from (not to the
config file's own location). Every field is required except `proclib_dirs`
and `csd_files`, which default to empty if omitted, and `copybook_extensions`
and `bms_globs`, which default to the conventions cobble ships with.

Those last two exist because a corpus that doesn't follow file-naming
convention would otherwise need a directory of symlinks. `cobol_globs`,
`jcl_globs` and `bms_globs` select files by listing a directory, so they take
globs; `copybook_extensions` is a list of bare extensions instead, because a
`COPY X` is resolved by ProLeap as *name + extension* rather than by listing
anything. Keep `cpy` in that list if you also generate BMS symbolic maps —
`generate_sym` writes them as `<mapname>.cpy`. The shape these options exist for
is a corpus where every member carries the same extension — say `.txt` — with
programs, copybooks and maps distinguished only by directory and name.

Then run:

```bash
uv run python -m cobble.build_graph --config your-corpus.yaml
uv run python -m cobble.generate_sym --config your-corpus.yaml   # only if you have BMS maps
uv run python -m cobble.render_graph --config your-corpus.yaml   # optional HTML visualization
```

`cobble.compare`'s golden-file check stays CardDemo-specific: it's not
meaningful against a different corpus's output.

### Render the HTML visualization

```bash
make render CONFIG=config/carddemo.yaml   # reads <out_dir>/{nodes,edges}.jsonl -> writes <out_dir>/graph.html
```

`CONFIG=` is required here too (same as `build`/`sym`): `out_dir` comes from
the config's `corpus.out_dir` field, so `render_graph.py` looks in the same
place `build_graph.py` wrote to. `<out_dir>/graph.html` is a single
self-contained file (vis-network is vendored at
`cobble/knowledge_graph/vendor/vis-network.min.js` and inlined; no server,
no CDN, no network access needed). Open it directly in a browser. It has
checkboxes to filter by node/edge kind, a search box that highlights matching
node labels, and click-to-highlight-neighbors on any node. Requires
`<out_dir>/nodes.jsonl` / `<out_dir>/edges.jsonl` to already exist (i.e. run `make build`
first).

### Unit tests

```bash
make test   # uv run pytest, no JARs, no corpus, runs in well under a second
```

Unlike `make verify` (one big end-to-end golden-file check over the real
CardDemo corpus, needing JDK/Maven/CMake), `tests/` unit-tests cobble's pure
modules in isolation (grammars, dataclass transforms, graph merging) with
hand-built inputs, giving localized signal on which piece broke rather than
just "449/803 doesn't match." Coverage is still partial; see `tests/` for
what's covered so far.

### Formatting, linting, and pre-commit hooks

```bash
make fmt    # uv run python -m black .
make lint   # uv run lint-imports && uv run pyright && uv run python -m python_fp_lint check cobble/
```

`.pre-commit-config.yaml` wires these up (plus the terminology guard and
`make test`) to run automatically on every commit: `black` auto-formats and
re-stages, `pyright` and `python-fp-lint` report warnings without blocking
the commit, and `import-linter` / the unit tests block it on failure.
Architecture contracts live in `.importlinter` (e.g. `interpreter` may not
import `cics`/`jackal`/`knowledge_graph`/`bms_copybook_gen`, and those four
consumers may not import each other).

## What's here

| Path | What |
|------|------|
| `cobble/` | The ported extraction code, plus this repo's own driver scripts (see below); everything lives under one package so there's no Python at the repo root. Extraction modules are byte-for-byte / import-rewired from their `red-dragon-forge` counterpart (imports → `cobble.*`). Imports **no** production Python: only `cobble.*`, stdlib, and pip (`lark`, `networkx`, `pyyaml`, `antlr4-python3-runtime`). Includes `cobble/bms_copybook_gen/` (the copybook generator, run as `python -m cobble.bms_copybook_gen`). |
| `cobble/cics/cics_grammar/*.g4` | The ANTLR grammar **source** (`CICSzLexer.g4`, `CICSzParser.g4`). `make codegen` generates the `CICSz*.py` parser from these; the generated `.py` is gitignored, never shipped. |
| `cobble/cics/verb_source_asg.py` | **The one seam.** Production sources CICS verbs by *lowering* each program through the CICS strategy (which needs the VM). This replaces that with a VM-free walk of the typed `CobolASG`: it reads each `EXEC CICS` statement, resolves operands to their static `VALUE` clauses, and routes the `CicsVerb`s through the byte-for-byte `flow_graph_core._verb_edge`. |
| `cobble/build_graph.py` / `cobble/compare.py` | This repo's own driver scripts (not ported from `red-dragon-forge`): extract the graph → `out/` (`python -m cobble.build_graph --config <path>`); identity-diff `out/` vs `reference/` (`python -m cobble.compare`). |
| `cobble/corpus_config.py` | `CorpusConfig`/`BmsConfig` dataclasses + YAML loading; `cobble.build_graph`/`cobble.generate_sym` read the corpus location/layout from here instead of a hardcoded CardDemo path. |
| `config/carddemo.yaml` | The tracked config `make build`/`make sym` use; captures CardDemo's layout in `corpus_config.py`'s schema. Copy this file as a starting point to point cobble at a different corpus. |
| `cobble/corpus_index.py` / `cobble/file_location.py` | `CorpusIndex` resolves every `(NodeKind, id)` to a `FileLocation` (a real `Path`, or a `NoFileLocation` explaining why not: not file-based, no CSD/definition source, or genuinely unresolved) once per run, from the same `CorpusConfig`. Every extractor and `GraphWriter` resolve a given node identically regardless of call order, which is what lets `GraphWriter` stream nodes keep-first with no merge step. |
| `cobble/render_graph.py` | Render `<out_dir>/{nodes,edges}.jsonl` as a self-contained interactive HTML graph at `<out_dir>/graph.html` (`python -m cobble.render_graph --config <path>`; `out_dir` comes from the config's `corpus.out_dir` field. `cobble/knowledge_graph/export.py` reads the NDJSON, `merge.py` builds one `networkx.MultiDiGraph`, `render.py` inlines the vendored `vis-network.min.js`). |
| `cobble/canonical_export.py` | Export a nodes/edges.jsonl pair as CodeConcise's canonical `manifest.json` (`python -m cobble.canonical_export --nodes <path> --edges <path> --output <path> --project-name <name>`; all four required, no config-derived defaults. The streaming/thread-pool/bounded-memory transform pipeline itself lives in `cobble/knowledge_graph/canonical_export.py`). |
| `tests/` | The pytest unit suite (`make test`), mirroring `cobble/`'s package structure. No JARs/corpus needed; pure modules tested in isolation with hand-built inputs. |
| `cobble/generate_sym.py` | **Stage-0.** Generates the BMS symbolic copybooks: `hlasm_export <map>.bms --syslib bms-macros/ | python -m cobble.bms_copybook_gen → sym/*.cpy` (`python -m cobble.generate_sym --config <path>`). |
| `reference/` | The 449/803 identity golden (copied from the production fitness golden, the *target*, not an input to the extraction). |
| `proleap-bridge/` | The COBOL→JSON ASG bridge (copied Maven source). Depends on the **forked** `proleap-cobol-parser` (`io.github.uwol:proleap-cobol-parser:4.0.0`, **not on Maven Central**) vendored as the submodule `proleap-bridge/proleap-cobol-parser`, built (`mvn install`) *before* the bridge. |
| `jcl-bridge/` | The JCL→JSON bridge (copied Maven source, self-contained). |
| `bms-macros/` | The hand-written `DFHMSD`/`DFHMDI`/`DFHMDF` prototype macros (assembler SYSLIB for `hlasm_export`). Source, not generated. |
| `vendor/carddemo/` | The CardDemo corpus, a git **submodule** (includes `app/bms`, the BMS map sources). |
| `vendor/che-che4z-lsp-for-hlasm/` | The HLASM language-server **fork** (submodule); `hlasm_export` is built from it (CMake + Ninja, OS-agnostic `build.sh`: CMake picks the system toolchain). |
| `.github/workflows/reproduce.yml` | CI: build everything from source on `ubuntu-latest` and verify 449/803. |

## Submodules (all pinned)

| Path | Repo |
|------|------|
| `vendor/carddemo` | `aws-mainframe-modernization-carddemo` (the corpus) |
| `vendor/che-che4z-lsp-for-hlasm` | forked che-che4z HLASM LSP (builds `hlasm_export`) |
| `proleap-bridge/proleap-cobol-parser` | forked `proleap-cobol-parser` (builds `4.0.0`) |

## Invariant

`cobble/**` imports zero live production Python (no bare `interpreter` / `cics` /
`jackal` / `knowledge_graph` absolute imports; only `cobble.*`):

```bash
grep -rE '^\s*(import|from)\s+(interpreter|cics|jackal|knowledge_graph)\b' cobble
# (no output)
```

The only coupling to RedDragon is (a) the two bridge JARs and `hlasm_export`,
invoked as subprocesses, all **built from source**, and (b) the one seam
(`cobble/cics/verb_source_asg.py`). The graph identity (449/803) is reached by
independent Python that shells out to those tools: the decoupling, proven from a
repo that contains no production interpreter code and ships no generated
artifacts.

## Acknowledgments

The JCL grammar (`jcl-bridge/src/main/antlr4/org/jackal/jcl/JCLLexer.g4` /
`JCLParser.g4`) and the CICS `EXEC CICS` grammar
(`cobble/cics/cics_grammar/CICSzLexer.g4` / `CICSzParser.g4`, adapted for the
Python3 ANTLR runtime) are both vendored from **Craig Schneiderwent's
[mapa](https://github.com/cschneid-the-elder/mapa)** project; thank you for
making these available. See `jcl-bridge/PROVENANCE.md` for the exact vendored
commit/files, and `jcl-bridge/LICENSE` for mapa's MIT license text.

## License

MIT; see [LICENSE.md](LICENSE.md). Project rationale in [PHILOSOPHY.md](PHILOSOPHY.md).
The vendored `cobble/knowledge_graph/vendor/vis-network.min.js` ships under its
own license: see `cobble/knowledge_graph/vendor/VIS_NETWORK_LICENSE.md`.
The vendored mapa grammars (see Acknowledgments above) ship under their own
MIT license: see `jcl-bridge/LICENSE`.
