"""build_carddemo_graph.py — run all four knowledge-graph extractors over
the FULL CardDemo corpus (all JCL jobs, all COBOL programs, the real CSD),
merge, and render one HTML visualization.

Extends Task 9's small, hand-picked slice (docs/superpowers/plans/
2026-07-07-cobol-knowledge-graph.md) to full coverage, per that plan's own
"Post-plan notes" — this was always the expected next step; nothing in the
extractors themselves needed to change.

Requires PROLEAP_BRIDGE_JAR, JCL_BRIDGE_JAR, and the bms-tools toolchain
(a built hlasm_export binary) on the environment: several CardDemo programs
(not just the obviously-online ones) COPY a BMS-generated symbolic map
copybook and/or use EXEC CICS DFHRESP(...), so the CALL/COPY pass and the
CICS flow pass both need the same generated symbolic-copybook directory and
CICS dialect parsing — a file is not reliably "batch" just because it isn't
one of the CSD's own DEFINE PROGRAM entries.

A single bad file (COBOL that fails to parse, a JCL job the bridge chokes
on) does not abort the whole run — failures are collected and reported at
the end, so the graph still reflects everything that DID compile.

Usage (from the red-dragon-forge repo root):
    PROLEAP_BRIDGE_JAR=... JCL_BRIDGE_JAR=... \\
        uv run --no-sync python knowledge_graph/build_carddemo_graph.py
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from cics.bms.generate import generate_symbolic_copybooks
from cics.coprocessor import build_cics_spec
from cics.dispatcher import parse_csd
from cics.flow_map import extract_transaction_flow_graph
from interpreter.cobol.ast_store import AstStore, AstStrategy
from interpreter.cobol.cobol_parser import ProLeapCobolParser
from interpreter.cobol.subprocess_runner import RealSubprocessRunner
from interpreter.project.cobol_connections import extract_cobol_connections
from jackal.cobol_file_graph import extract_cobol_file_graph
from jackal.jcl_graph import extract_jcl_graph

from knowledge_graph.export import read_ndjson
from knowledge_graph.graph_writer import GraphWriter
from knowledge_graph.merge import merge_graph
from knowledge_graph.render import render_html

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parents[1]
_CARDDEMO_HOME = _REPO_ROOT / "vendor" / "carddemo" / "app"
_CICS_COPYBOOKS = _REPO_ROOT / "cicada" / "cics" / "copybooks"
_HLASM_EXPORT_BIN = (
    _REPO_ROOT
    / "cicada"
    / "third-party"
    / "che-che4z-lsp-for-hlasm-fork"
    / "build"
    / "bin"
    / "hlasm_export"
)
_OUTPUT_PATH = (
    _REPO_ROOT / "tests" / "integration" / "output" / "carddemo_knowledge_graph.html"
)


def _bridge_jar() -> str:
    return os.environ["PROLEAP_BRIDGE_JAR"]


def _make_parser(copybook_dirs: Sequence[Path]) -> ProLeapCobolParser:
    return ProLeapCobolParser(
        RealSubprocessRunner(), _bridge_jar(), copybook_dirs=copybook_dirs
    )


def _build_jcl_graph(writer: GraphWriter, failures: list[str]) -> None:
    jcl_dir = _CARDDEMO_HOME / "jcl"
    proclib_dirs = [_CARDDEMO_HOME / "proc"]
    jcl_files = sorted(jcl_dir.glob("*.jcl")) + sorted(jcl_dir.glob("*.JCL"))
    for path in jcl_files:
        try:
            nodes, edges = extract_jcl_graph(
                path.read_text(), proclib_dirs=proclib_dirs
            )
        # one bad job must not abort the run
        except Exception as exc:  # noqa: BLE001
            logger.warning("JCL %s failed: %s", path.name, exc, exc_info=True)
            failures.append(f"JCL {path.name}: {exc}")
            continue
        writer.add_all(nodes, edges)
    print(f"JCL: {len(jcl_files)} files")


def _build_call_copy_graph(
    copybook_dirs: Sequence[Path],
    cics_program_names: set[str],
    writer: GraphWriter,
    failures: list[str],
) -> None:
    """CALL/COPY graph for every CardDemo COBOL program.

    A program named in the real CSD's DEFINE PROGRAM/TRANSACTION entries
    (``cics_program_names``) is compiled with the full CICS lowering
    strategy (source prepass + dialect parser + extension strategy) built
    by ``build_cics_spec`` — the same machinery extract_transaction_flow_graph
    already uses successfully — because EXEC CICS DFHRESP(...) condition
    handling needs real IR lowering, not just statement parsing; a bare
    ``dialect_parsers=[CicsDialectParser()]`` (enough for the small
    synthetic program in Task 9's test) is not enough for these. Every
    other program compiles as plain batch COBOL.
    """
    cbl_dir = _CARDDEMO_HOME / "cbl"
    plain_parser = _make_parser(copybook_dirs)
    cics_spec = build_cics_spec(context_holder=[None], result_holder=[None])
    cics_parser = _make_parser(copybook_dirs)
    cbl_files = sorted(cbl_dir.glob("*.cbl"))
    for path in cbl_files:
        is_cics = path.stem.upper() in cics_program_names
        try:
            if is_cics:
                nodes, edges = extract_cobol_connections(
                    path.read_bytes(),
                    copybook_dirs=copybook_dirs,
                    program_source_dirs=[cbl_dir],
                    parser=cics_parser,
                    extension_strategies=[cics_spec.make_strategy()],
                    dialect_parsers=[cics_spec.dialect_parser],
                    source_transform=cics_spec.source_prepass,
                )
            else:
                nodes, edges = extract_cobol_connections(
                    path.read_bytes(),
                    copybook_dirs=copybook_dirs,
                    program_source_dirs=[cbl_dir],
                    parser=plain_parser,
                )
        # one bad program must not abort the run
        except Exception as exc:  # noqa: BLE001
            logger.warning("COBOL %s failed: %s", path.name, exc, exc_info=True)
            failures.append(f"COBOL {path.name}: {exc}")
            continue
        writer.add_all(nodes, edges)
    print(f"CALL/COPY: {len(cbl_files)} programs")


def _build_batch_file_graph(
    copybook_dirs: Sequence[Path],
    cics_program_names: set[str],
    writer: GraphWriter,
    failures: list[str],
) -> None:
    """PROGRAM -> COBOL_FILE graph (READS/WRITES/UPDATES, from OPEN mode) for
    every CardDemo batch COBOL program's FILE-CONTROL SELECT/OPEN statements.

    CICS programs are skipped, not attempted-and-failed: they access files
    via EXEC CICS READ/WRITE FILE(...) (already traced as CICS_FILE edges by
    _build_cics_flow_graph), not plain OPEN/READ/WRITE — and the bare
    parser.parse() this pass uses (no CICS extension_strategies/
    dialect_parsers, unlike _build_call_copy_graph) can't even parse EXEC
    CICS statement nodes, since that needs red-dragon's CICS IR lowering.
    """
    cbl_dir = _CARDDEMO_HOME / "cbl"
    parser = _make_parser(copybook_dirs)
    cbl_files = [
        p
        for p in sorted(cbl_dir.glob("*.cbl"))
        if p.stem.upper() not in cics_program_names
    ]
    store = AstStore(AstStrategy.DISK)  # default DISK; MEMORY opt-in later
    store.parse_all({p: p.read_bytes() for p in cbl_files}, parser)
    for path in cbl_files:
        try:
            nodes, edges = extract_cobol_file_graph(store.get(path))
        # one bad program must not abort the run
        except Exception as exc:  # noqa: BLE001
            logger.warning("FILE-CONTROL %s failed: %s", path.name, exc, exc_info=True)
            failures.append(f"FILE-CONTROL {path.name}: {exc}")
            continue
        writer.add_all(nodes, edges)
    store.close()
    print(f"FILE-CONTROL: {len(cbl_files)} batch programs")


def _build_cics_flow_graph(
    copybook_dirs: Sequence[Path],
    transid_to_program: Mapping[str, str],
    writer: GraphWriter,
    failures: list[str],
) -> None:
    """CICS transaction-flow graph (STARTS/XCTL/LINK/RETURN_TRANSID/
    SENDS_MAP/RECEIVES_MAP) for every transaction the real CSD defines."""
    csd_path = _CARDDEMO_HOME / "csd" / "CARDDEMO.CSD"

    cbl_dir = _CARDDEMO_HOME / "cbl"
    cobol_sources: dict[str, bytes] = {}
    for prog_name in set(transid_to_program.values()):
        cbl_path = cbl_dir / f"{prog_name}.cbl"
        if cbl_path.is_file():
            cobol_sources[prog_name] = cbl_path.read_bytes()
        else:
            logger.warning("CICS program %s: no %s found", prog_name, cbl_path.name)
            failures.append(f"CICS program {prog_name}: no {cbl_path.name} found")

    parser = _make_parser(copybook_dirs)
    try:
        extract_transaction_flow_graph(
            csd_source=csd_path.read_text(),
            bms_mapsets={},
            cobol_sources=cobol_sources,
            parser=parser,
            sink=writer,
            failures=failures,
        )
    # a malformed CSD must not abort the run
    except Exception as exc:  # noqa: BLE001
        logger.warning("CICS flow graph (whole CSD) failed: %s", exc, exc_info=True)
        failures.append(f"CICS flow graph (whole CSD): {exc}")

    print(
        f"CICS flow: {len(transid_to_program)} transactions, "
        f"{len(cobol_sources)} programs compiled"
    )


def main() -> int:
    failures: list[str] = []

    sym_dir = _REPO_ROOT / ".knowledge_graph_scratch" / "sym"
    sym_dir.mkdir(parents=True, exist_ok=True)
    generate_symbolic_copybooks(
        bms_dir=_CARDDEMO_HOME / "bms",
        out_dir=sym_dir,
        hlasm_export_bin=str(_HLASM_EXPORT_BIN),
    )
    # sym_dir first so generated map copybooks win over shipped cpy-bms/*.CPY
    # sharing the same basename (same precedence test_carddemo_signon_real.py
    # uses) — shared by every pass below, since a program doesn't have to be
    # a CSD-routed transaction's own entry program to need one.
    copybook_dirs = [
        sym_dir,
        _CARDDEMO_HOME / "cpy",
        _CARDDEMO_HOME / "cpy-bms",
        _CICS_COPYBOOKS,
    ]

    transid_to_program = parse_csd(_CARDDEMO_HOME / "csd" / "CARDDEMO.CSD")
    cics_program_names = set(transid_to_program.values())

    nodes_jsonl = _OUTPUT_PATH.parent / "carddemo_graph.nodes.jsonl"
    edges_jsonl = _OUTPUT_PATH.parent / "carddemo_graph.edges.jsonl"
    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with GraphWriter(nodes_jsonl, edges_jsonl) as writer:
        _build_jcl_graph(writer, failures)
        _build_call_copy_graph(copybook_dirs, cics_program_names, writer, failures)
        _build_cics_flow_graph(copybook_dirs, transid_to_program, writer, failures)
        _build_batch_file_graph(copybook_dirs, cics_program_names, writer, failures)

    graph = merge_graph(*read_ndjson(nodes_jsonl, edges_jsonl))

    print(
        f"\nMerged graph: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges"
    )

    render_html(graph, _OUTPUT_PATH, title="CardDemo Knowledge Graph (full corpus)")
    print(f"Wrote {_OUTPUT_PATH}")

    if failures:
        logger.warning("%d failure(s) (skipped, did not abort the run)", len(failures))
        print(f"\n{len(failures)} failure(s) (skipped, did not abort the run):")
        for f in failures:
            print(f"  - {f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
