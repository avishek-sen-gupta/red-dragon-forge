"""cobble-fields-trace steps into a CALL, compiled by the real bridge.

TCALLA hands WS-REF BY REFERENCE and WS-CON BY CONTENT. TCALLB reads LK-CON, then
writes both parameters. The read must name the caller's MOVE as its definer; the
write through LK-REF must come back to the caller, which shares those bytes; the
write through LK-CON must not, because BY CONTENT handed over a copy.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cobble.dataflow.fields.trace import Budget, Trace, sampled

FORGE = Path(__file__).resolve().parents[4]
BRIDGE_GLOB = "vendor/red-dragon/proleap-bridge/target/proleap-bridge-*-shaded.jar"

CALLER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TCALLA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REF               PIC X(4) VALUE SPACES.
       01  WS-CON               PIC X(4) VALUE SPACES.
       01  WS-SINK              PIC X(4).
       01  WS-SINK2             PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'AAAA' TO WS-REF.
           MOVE 'BBBB' TO WS-CON.
           CALL 'TCALLB' USING WS-REF BY CONTENT WS-CON.
           MOVE WS-REF TO WS-SINK.
           MOVE WS-CON TO WS-SINK2.
           GOBACK.
"""

CALLEE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TCALLB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-GOT               PIC X(4).
       LINKAGE SECTION.
       01  LK-REF               PIC X(4).
       01  LK-CON               PIC X(4).
       PROCEDURE DIVISION USING LK-REF LK-CON.
       MAIN-PARA.
           MOVE LK-CON TO WS-GOT.
           MOVE 'CCCC' TO LK-REF.
           MOVE 'DDDD' TO LK-CON.
           GOBACK.
"""


def _bridge_jar() -> Path:
    found = sorted(FORGE.glob(BRIDGE_GLOB))
    if not found:
        pytest.skip(f"no bridge JAR at {BRIDGE_GLOB}; run `make jar`")
    return found[-1]


@pytest.fixture(scope="module")
def called(tmp_path_factory) -> Trace:
    from cobble.parsing.parse_corpus import Job, parse_one

    root = tmp_path_factory.mktemp("trace-call")
    cache = root / "asg"
    cache.mkdir()
    for program, source in (("TCALLA", CALLER), ("TCALLB", CALLEE)):
        path = root / f"{program}.cbl"
        path.write_text(source, encoding="utf-8")
        result = parse_one(
            Job(path, cache / f"{program}.json"), str(_bridge_jar()), (), ("cpy",)
        )
        assert result.ok, result.error
    return sampled("TCALLA", cache, Budget(paths=4))


def _definers(trace: Trace, program: str, field: str) -> set[str]:
    return {
        definer
        for dep in trace.deps
        if dep.program == program and dep.target.field_name == field
        for definer in dep.definers
    }


def test_a_call_carries_its_arguments_in_and_only_by_reference_back(
    called: Trace,
) -> None:
    assert (
        _definers(called, "TCALLB", "WS-GOT"),
        _definers(called, "TCALLA", "WS-SINK"),
        _definers(called, "TCALLA", "WS-SINK2"),
        {dead.reason for dead in called.dead_ends},
    ) == (
        {"TCALLA/MAIN-PARA/1"},
        {"TCALLB/MAIN-PARA/1"},
        {"TCALLA/MAIN-PARA/1"},
        set(),
    )
