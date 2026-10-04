"""CALL ON EXCEPTION / NOT ON EXCEPTION -- and CALL ON OVERFLOW, which IBM defines
as the same phrase -- and STRING/UNSTRING ON OVERFLOW / NOT ON OVERFLOW, from COBOL
source through cobble-srccfg-build: each phrase is an arm after its statement,
the first on TRUE and the NOT form on FALSE.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cobble.dataflow.srccfg.bundle import load_bundle
from cobble.dataflow.srccfg.cfg import Cfg, EdgeKind
from cobble.dataflow.srccfg.closure import main as build_main

FORGE = Path(__file__).resolve().parents[4]
BRIDGE_GLOB = "vendor/red-dragon/proleap-bridge/target/proleap-bridge-*-shaded.jar"

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARMSP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                 PIC X(4).
       01  WS-B                 PIC X.
       01  WS-C                 PIC X.
       01  WS-D                 PIC X(8).
       01  WS-E                 PIC X.
       01  WS-F                 PIC X(4).
       01  WS-G                 PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL 'PROGB' USING WS-A
               ON EXCEPTION MOVE 'E' TO WS-B
               NOT ON EXCEPTION MOVE 'N' TO WS-B
           END-CALL.
           CALL 'PROGC' ON OVERFLOW MOVE 'O' TO WS-C END-CALL.
           STRING WS-A DELIMITED BY SIZE INTO WS-D
               ON OVERFLOW MOVE 'X' TO WS-E
               NOT ON OVERFLOW MOVE 'Y' TO WS-E
           END-STRING.
           UNSTRING WS-D INTO WS-F
               ON OVERFLOW MOVE 'X' TO WS-G
               NOT ON OVERFLOW MOVE 'Y' TO WS-G
           END-UNSTRING.
           GOBACK.
"""


def _bridge_jar() -> Path:
    found = sorted(FORGE.glob(BRIDGE_GLOB))
    if not found:
        pytest.skip(f"no bridge JAR at {BRIDGE_GLOB}; run `make jar`")
    return found[-1]


def _built(tmp_path: Path) -> Cfg:
    from cobble.parsing.parse_corpus import Job, parse_one

    cache = tmp_path / "parsed"
    cache.mkdir()
    source = tmp_path / "ARMSP.cbl"
    source.write_text(SOURCE, encoding="utf-8")
    parsed = parse_one(
        Job(source, cache / "ARMSP.json"), str(_bridge_jar()), (), ("cpy",)
    )
    assert parsed.ok, parsed.error
    config = tmp_path / "srccfg.toml"
    config.write_text(f'[srccfg]\nasg_dir = "{cache}"\n', encoding="utf-8")
    built = tmp_path / "ARMSP.jsonl"
    assert build_main(["--config", str(config), "ARMSP", "--output", str(built)]) == 0
    cfg = load_bundle(built).cfgs[0]
    return cfg


def _entered(cfg: Cfg, fields: tuple[str, ...]) -> dict[str, set[tuple[str, EdgeKind]]]:
    """How each writer of ``fields`` is entered: by its node id, which names the
    phrase it sits in, the test it hangs off and on which edge."""
    return {
        writer.id: {(edge.source, edge.kind) for edge in cfg.predecessors(writer.id)}
        for writer in cfg.nodes
        if set(fields) & set(writer.writes)
    }


def test_each_phrase_is_an_arm_after_its_statement(tmp_path: Path) -> None:
    cfg = _built(tmp_path)
    tests = ("MAIN-PARA/0#arm", "MAIN-PARA/1#arm", "MAIN-PARA/2#arm", "MAIN-PARA/3#arm")

    assert {
        test: (
            cfg.node(test).atom.text,
            {(edge.source, edge.kind) for edge in cfg.predecessors(test)},
        )
        for test in tests
    } == {
        "MAIN-PARA/0#arm": ("ON EXCEPTION PROGB", {("MAIN-PARA/0", EdgeKind.FLOW)}),
        "MAIN-PARA/1#arm": ("ON EXCEPTION PROGC", {("MAIN-PARA/1", EdgeKind.FLOW)}),
        "MAIN-PARA/2#arm": ("ON OVERFLOW WS-D", {("MAIN-PARA/2", EdgeKind.FLOW)}),
        "MAIN-PARA/3#arm": ("ON OVERFLOW WS-D", {("MAIN-PARA/3", EdgeKind.FLOW)}),
    }
    assert _entered(cfg, ("WS-B", "WS-C", "WS-E", "WS-G")) == {
        "MAIN-PARA/0.on_exception.0": {("MAIN-PARA/0#arm", EdgeKind.TRUE)},
        "MAIN-PARA/0.not_on_exception.0": {("MAIN-PARA/0#arm", EdgeKind.FALSE)},
        "MAIN-PARA/1.on_exception.0": {("MAIN-PARA/1#arm", EdgeKind.TRUE)},
        "MAIN-PARA/2.on_overflow.0": {("MAIN-PARA/2#arm", EdgeKind.TRUE)},
        "MAIN-PARA/2.not_on_overflow.0": {("MAIN-PARA/2#arm", EdgeKind.FALSE)},
        "MAIN-PARA/3.on_overflow.0": {("MAIN-PARA/3#arm", EdgeKind.TRUE)},
        "MAIN-PARA/3.not_on_overflow.0": {("MAIN-PARA/3#arm", EdgeKind.FALSE)},
    }
