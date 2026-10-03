"""A stacked WHEN, from COBOL source through cobble-srccfg-build: the body the
two conditions share is one node, entered on TRUE from either."""

from __future__ import annotations

from pathlib import Path

import pytest
from cobble.dataflow.srccfg.bundle import load_bundle
from cobble.dataflow.srccfg.cfg import EdgeKind, NodeKind
from cobble.dataflow.srccfg.closure import main as build_main

FORGE = Path(__file__).resolve().parents[4]
BRIDGE_GLOB = "vendor/red-dragon/proleap-bridge/target/proleap-bridge-*-shaded.jar"

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STACKP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                 PIC 9.
       01  WS-B                 PIC X.
       01  WS-C                 PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EVALUATE WS-A
               WHEN 1
               WHEN 2
                   MOVE 'S' TO WS-B
               WHEN OTHER
                   MOVE 'O' TO WS-C
           END-EVALUATE.
           GOBACK.
"""


def _bridge_jar() -> Path:
    found = sorted(FORGE.glob(BRIDGE_GLOB))
    if not found:
        pytest.skip(f"no bridge JAR at {BRIDGE_GLOB}; run `make jar`")
    return found[-1]


def test_the_shared_body_is_one_node_entered_from_either_condition(
    tmp_path: Path,
) -> None:
    from cobble.parsing.parse_corpus import Job, parse_one

    cache = tmp_path / "parsed"
    cache.mkdir()
    source = tmp_path / "STACKP.cbl"
    source.write_text(SOURCE, encoding="utf-8")
    parsed = parse_one(
        Job(source, cache / "STACKP.json"), str(_bridge_jar()), (), ("cpy",)
    )
    assert parsed.ok, parsed.error
    config = tmp_path / "srccfg.toml"
    config.write_text(f'[srccfg]\nasg_dir = "{cache}"\n', encoding="utf-8")
    built = tmp_path / "STACKP.jsonl"
    assert build_main(["--config", str(config), "STACKP", "--output", str(built)]) == 0
    (cfg,) = load_bundle(built).cfgs

    tests = [node.id for node in cfg.nodes if node.kind == NodeKind.TEST]
    writers = [node.id for node in cfg.nodes if "WS-B" in node.writes]

    assert (
        len(tests),
        len(writers),
        {(edge.source, edge.kind) for edge in cfg.predecessors(writers[0])},
    ) == (
        2,
        1,
        {(tests[0], EdgeKind.TRUE), (tests[1], EdgeKind.TRUE)},
    )
