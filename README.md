# cobble

A **standalone, VM-free** knowledge-graph extractor for the AWS CardDemo mainframe
corpus. It is a file-by-file **port** of the streaming graph pipeline in the
`red-dragon-forge` monorepo, lifted into its own repository to prove the
extraction is decoupled from the RedDragon interpreter/VM: it reproduces the
**exact same 449-node / 803-edge graph** using nothing but two Java bridge JARs
and pip packages — **no production Python is imported at runtime.**

## Result

```
$ make all
...
Merged graph: 449 nodes, 803 edges
RESULT: EMPTY DIFF — out matches reference exactly.
```

`out/{nodes,edges}.jsonl` matches `reference/{nodes,edges}.jsonl` (the identity
golden copied from production) exactly, on node `(kind,id)` and edge
`(source,source_kind,target,target_kind,kind)` identity.

## What's here

| Path | What |
|------|------|
| `port/` | The ported extraction code. Every module is a byte-for-byte / import-rewired copy of its `red-dragon-forge` counterpart, imports rewritten to `port.*`. Imports **no** `interpreter`/`cics`/`jackal`/`knowledge_graph` production Python — only `port.*`, stdlib, and pip (`lark`, `networkx`, `antlr4-python3-runtime`). |
| `port/cics/verb_source_asg.py` | **The one seam.** Production sources CICS verbs by *lowering* each program through the CICS strategy (which needs the VM). This file replaces that with a VM-free walk of the typed `CobolASG`: it reads each `EXEC CICS` statement, resolves data-name operands to their static `VALUE` clauses, and routes the resulting `CicsVerb`s through the byte-for-byte `flow_graph_core._verb_edge`. Everything else in `cics/` is verbatim. |
| `build_port.py` | Orchestrator — runs the four extractors (JCL, CALL/COPY, CICS flow, FILE-CONTROL) over the corpus, streams into the ported `GraphWriter`, writes `out/`. |
| `compare.py` | Identity-diff `out/` vs `reference/`. |
| `reference/` | The 449/803 identity golden (copied from the production fitness golden). |
| `proleap-bridge/`, `jcl-bridge/` | The two Java bridge Maven projects (COBOL→JSON ASG and JCL→JSON). Copied source, built here. `proleap-bridge` depends on a **forked** `proleap-cobol-parser` (`io.github.uwol:proleap-cobol-parser:4.0.0`, **not on Maven Central**), vendored as the submodule `proleap-bridge/proleap-cobol-parser` and built (`mvn install`) *before* the bridge — see the `jars` target. |
| `vendor/carddemo/` | The CardDemo corpus — a git **submodule**. |
| `sym/`, `cics-copybooks/` | Copybooks the ProLeap parse needs: `sym/` is the pre-generated BMS symbolic copybooks (see caveat below); `cics-copybooks/` are the CICS system copybooks. |

## Reproduce from a fresh clone

Requires: JDK 21+ and Maven (to build the bridges), and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone <this-repo> cobble && cd cobble
./build.sh          # one command: submodules -> fork + bridge JARs -> extract -> verify 449/803
```

Or step by step: `make jars` (build the two shaded JARs) → `make build`
(run the extractors) → `make compare` (check the empty diff).

## The one input that isn't regenerated here

`sym/` holds pre-generated **BMS symbolic copybooks** (one per CICS map). In
production these are generated from the BMS maps by an HLASM toolchain
(`hlasm_export` + the `cics.bms` production module). Regenerating them would pull
that toolchain (and production Python) in, which would break the decoupling
invariant — so they are **copied in as input data**, exactly like the corpus.
The COBOL parse needs them to resolve `COPY`s of the symbolic maps.

## Invariant

`port/**` imports zero live production Python — grep it:

```bash
grep -rE '^\s*(import|from)\s+(interpreter|cics|jackal|knowledge_graph|bms_copybook_gen)\b' port
# (no output)
```

The only coupling to RedDragon is the two bridge JARs (invoked as subprocesses)
and the copied copybook input data. The graph identity (449/803) is reached by
independent Python that shells out to those bridges — the decoupling, proven from
a repo that contains no production interpreter code.
