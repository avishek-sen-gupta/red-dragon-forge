# cobble

[![reproduce-graph](https://github.com/avishek-sen-gupta/cobble/actions/workflows/reproduce.yml/badge.svg)](https://github.com/avishek-sen-gupta/cobble/actions/workflows/reproduce.yml)

A **standalone, VM-free** knowledge-graph extractor for the AWS CardDemo mainframe
corpus. It is a file-by-file **port** of the streaming graph pipeline in the
`red-dragon-forge` monorepo, lifted into its own repository to prove the
extraction is decoupled from the RedDragon interpreter/VM. It reproduces the
**exact same 449-node / 803-edge graph** starting from nothing but:

- the **CardDemo repo** (a git submodule — the source corpus), and
- the parsers/tools, all **built from source** (submodules + copied Maven source).

Everything generated — the ANTLR CICS parser **and** the BMS symbolic copybooks —
is **generated here from its grammar/source**. No production Python is imported at
runtime, and nothing pre-generated is shipped: the only things tracked are
hand-written source, grammar source (`.g4` / `.bms` / `.mac`), and submodule pins.

## Result

```
$ ./build.sh
==> [1/5] Fetching submodules (CardDemo corpus + proleap fork + che-che4z HLASM fork)...
==> [2/5] Building tools from source (hlasm_export + proleap fork + both bridge JARs)...
==> [3/5] Generating from grammars: the CICS parser (ANTLR) + the BMS copybooks...
==> [4/5] Extracting the CardDemo knowledge graph...
Merged graph: 449 nodes, 803 edges
==> [5/5] Verifying against the reference golden (must be 449/803, empty diff)...
RESULT: EMPTY DIFF — out matches reference exactly.
```

CI runs exactly this on every push/PR (`ubuntu-latest`) — a green badge means the
graph was reproduced from source, from nothing but the grammars and the corpus.

## Reproduce from a fresh clone

Requires: `git`, JDK 21+, Maven (bridges); a C++ toolchain (clang or gcc) with
CMake + Ninja (`hlasm_export`); and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone <this-repo> cobble && cd cobble
./build.sh   # submodules -> build tools -> generate parser+copybooks -> extract -> verify 449/803
```

`make` targets: `tools` (hlasm + proleap fork + bridge JARs) · `codegen`
(generate the CICS parser + BMS copybooks from their grammars) · `build`
(extract → `out/`) · `compare` (identity-diff vs `reference/`, 449/803) ·
`clean` (drop all generated artifacts).

## What's here

| Path | What |
|------|------|
| `cobble/` | The ported extraction code. Every module is byte-for-byte / import-rewired from its `red-dragon-forge` counterpart (imports → `cobble.*`). Imports **no** production Python — only `cobble.*`, stdlib, and pip (`lark`, `networkx`, `antlr4-python3-runtime`). Includes `cobble/bms_copybook_gen/` (the copybook generator, run as `python -m cobble.bms_copybook_gen`). |
| `cobble/cics/cics_grammar/*.g4` | The ANTLR grammar **source** (`CICSzLexer.g4`, `CICSzParser.g4`). `make codegen` generates the `CICSz*.py` parser from these — the generated `.py` is gitignored, never shipped. |
| `cobble/cics/verb_source_asg.py` | **The one seam.** Production sources CICS verbs by *lowering* each program through the CICS strategy (which needs the VM). This replaces that with a VM-free walk of the typed `CobolASG`: it reads each `EXEC CICS` statement, resolves operands to their static `VALUE` clauses, and routes the `CicsVerb`s through the byte-for-byte `flow_graph_core._verb_edge`. |
| `build_port.py` / `compare.py` | Extract the graph → `out/`; identity-diff `out/` vs `reference/`. |
| `generate_sym.py` | **Stage-0.** Generates the BMS symbolic copybooks: `hlasm_export <map>.bms --syslib bms-macros/ | python -m cobble.bms_copybook_gen → sym/*.cpy`. |
| `reference/` | The 449/803 identity golden (copied from the production fitness golden — the *target*, not an input to the extraction). |
| `proleap-bridge/` | The COBOL→JSON ASG bridge (copied Maven source). Depends on the **forked** `proleap-cobol-parser` (`io.github.uwol:proleap-cobol-parser:4.0.0`, **not on Maven Central**) vendored as the submodule `proleap-bridge/proleap-cobol-parser`, built (`mvn install`) *before* the bridge. |
| `jcl-bridge/` | The JCL→JSON bridge (copied Maven source, self-contained). |
| `bms-macros/` | The hand-written `DFHMSD`/`DFHMDI`/`DFHMDF` prototype macros (assembler SYSLIB for `hlasm_export`). Source, not generated. |
| `vendor/carddemo/` | The CardDemo corpus — a git **submodule** (includes `app/bms`, the BMS map sources). |
| `vendor/che-che4z-lsp-for-hlasm/` | The HLASM language-server **fork** (submodule) — `hlasm_export` is built from it (CMake + Ninja, OS-agnostic `build.sh`: CMake picks the system toolchain). |
| `.github/workflows/reproduce.yml` | CI: build everything from source on `ubuntu-latest` and verify 449/803. |

## Submodules (all pinned)

| Path | Repo |
|------|------|
| `vendor/carddemo` | `aws-mainframe-modernization-carddemo` (the corpus) |
| `vendor/che-che4z-lsp-for-hlasm` | forked che-che4z HLASM LSP (builds `hlasm_export`) |
| `proleap-bridge/proleap-cobol-parser` | forked `proleap-cobol-parser` (builds `4.0.0`) |

## Invariant

`cobble/**` imports zero live production Python (no bare `interpreter` / `cics` /
`jackal` / `knowledge_graph` absolute imports — only `cobble.*`):

```bash
grep -rE '^\s*(import|from)\s+(interpreter|cics|jackal|knowledge_graph)\b' cobble
# (no output)
```

The only coupling to RedDragon is (a) the two bridge JARs and `hlasm_export`,
invoked as subprocesses, all **built from source**, and (b) the one seam
(`cobble/cics/verb_source_asg.py`). The graph identity (449/803) is reached by
independent Python that shells out to those tools — the decoupling, proven from a
repo that contains no production interpreter code and ships no generated
artifacts.

## License

MIT — see [LICENSE.md](LICENSE.md). Project rationale in [PHILOSOPHY.md](PHILOSOPHY.md).
