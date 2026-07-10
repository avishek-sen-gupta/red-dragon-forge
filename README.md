# cobble

A **standalone, VM-free** knowledge-graph extractor for the AWS CardDemo mainframe
corpus. It is a file-by-file **port** of the streaming graph pipeline in the
`red-dragon-forge` monorepo, lifted into its own repository to prove the
extraction is decoupled from the RedDragon interpreter/VM. It reproduces the
**exact same 449-node / 803-edge graph** starting from nothing but:

- the **CardDemo repo** (a git submodule — the source corpus), and
- the parsers/tools, all **built from source** (a submodule + copied Maven source).

Everything else — including the BMS symbolic copybooks — is **generated here from
source**. No production Python is imported at runtime, and nothing pre-generated
is shipped.

## Result

```
$ ./build.sh
==> [1/5] Fetching submodules ...
==> [2/5] Building tools from source (hlasm_export + proleap fork + both bridge JARs)...
==> [3/5] Generating the BMS symbolic copybooks from the .bms sources...
==> [4/5] Extracting the CardDemo knowledge graph...
Merged graph: 449 nodes, 803 edges
==> [5/5] Verifying against the reference golden (must be 449/803, empty diff)...
RESULT: EMPTY DIFF — out matches reference exactly.
```

## Reproduce from a fresh clone

Requires: `git`, JDK 21+, Maven (bridges); CMake, Ninja, LLVM@18 (`hlasm_export`);
and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone <this-repo> cobble && cd cobble
./build.sh          # submodules -> build tools -> generate copybooks -> extract -> verify 449/803
```

Individual `make` targets: `tools` (hlasm + fork + bridge JARs) · `sym` (generate
the copybooks) · `build` (extract) · `compare` (check 449/803).

## What's here

| Path | What |
|------|------|
| `cobble/` | The ported extraction code. Every module is byte-for-byte / import-rewired from its `red-dragon-forge` counterpart (imports → `cobble.*`). Imports **no** production Python — only `cobble.*`, stdlib, and pip (`lark`, `networkx`, `antlr4-python3-runtime`). Includes `cobble/bms_copybook_gen/` (the copybook generator, run as `python -m cobble.bms_copybook_gen`). |
| `cobble/cics/verb_source_asg.py` | **The one seam.** Production sources CICS verbs by *lowering* each program through the CICS strategy (which needs the VM). This replaces that with a VM-free walk of the typed `CobolASG`: it reads each `EXEC CICS` statement, resolves operands to their static `VALUE` clauses, and routes the `CicsVerb`s through the byte-for-byte `flow_graph_core._verb_edge`. |
| `build_port.py` / `compare.py` | Extract the graph → `out/`; identity-diff `out/` vs `reference/`. |
| `generate_sym.py` | **Stage-0.** Generates the BMS symbolic copybooks: `hlasm_export <map>.bms --syslib bms-macros/ | python -m cobble.bms_copybook_gen → sym/*.cpy`. |
| `reference/` | The 449/803 identity golden (copied from the production fitness golden — the *target*, not an input to the extraction). |
| `proleap-bridge/` | The COBOL→JSON ASG bridge (copied Maven source). Depends on the **forked** `proleap-cobol-parser` (`io.github.uwol:proleap-cobol-parser:4.0.0`, **not on Maven Central**) vendored as the submodule `proleap-bridge/proleap-cobol-parser`, built (`mvn install`) *before* the bridge. |
| `jcl-bridge/` | The JCL→JSON bridge (copied Maven source, self-contained). |
| `third-party/che-che4z-lsp-for-hlasm/` | The HLASM language-server **fork** (submodule) — `hlasm_export` is built from it (CMake + Ninja + LLVM@18). |
| `bms-macros/` | The hand-written `DFHMSD`/`DFHMDI`/`DFHMDF` prototype macros (assembler SYSLIB for `hlasm_export`). Source, not generated. |
| `vendor/carddemo/` | The CardDemo corpus — a git **submodule** (includes `app/bms`, the BMS map sources). |

## Submodules (all pinned)

| Path | Repo |
|------|------|
| `vendor/carddemo` | `aws-mainframe-modernization-carddemo` (the corpus) |
| `proleap-bridge/proleap-cobol-parser` | forked `proleap-cobol-parser` (builds `4.0.0`) |
| `third-party/che-che4z-lsp-for-hlasm` | forked che-che4z HLASM LSP (builds `hlasm_export`) |

## Invariant

`cobble/**` imports zero live production Python:

```bash
grep -rE '^\s*(import|from)\s+(interpreter|cics|jackal|knowledge_graph)\b' port
# (no output)
```

The only coupling to RedDragon is (a) the two bridge JARs and `hlasm_export`,
invoked as subprocesses, all **built from source**, and (b) the one seam
(`cobble/cics/verb_source_asg.py`). The graph identity (449/803) is reached by
independent Python that shells out to those tools — the decoupling, proven from a
repo that contains no production interpreter code and ships no generated
artifacts.
