"""The tn3270 region rolls back a task its dispatcher abends."""

from __future__ import annotations

from pathlib import Path

import pytest

from cics.bootstrap import compile_cics_program
from cics.coprocessor import build_cics_spec
from cics.runtime import install_cics_runtime
from cics.dispatcher import InputEvent
from cics.tn3270.config import RegionConfig
from cics.tn3270.region import _region, _wiring
from cics.types import DispatchKind
from interpreter.cobol.features import CobolFeature
from tests.covers import covers
from tests.integration.cobol_helpers import bridge_jar  # noqa: F401

_CICS_COPYBOOKS = Path(__file__).parents[3] / "cics" / "copybooks"

_UNKNOWN_NEXT_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HOPPER.
       PROCEDURE DIVISION.
           EXEC CICS RETURN TRANSID('ZZZZ') END-EXEC.
           STOP RUN.
"""


@pytest.fixture
def cobol_parser(bridge_jar):
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from cobol_asg.subprocess_runner import RealSubprocessRunner

    return ProLeapCobolParser(
        RealSubprocessRunner(), bridge_jar, copybook_dirs=[_CICS_COPYBOOKS]
    )


@covers(CobolFeature.EXEC_CICS)
def test_an_unknown_return_transid_runs_the_regions_rollback(cobol_parser, tmp_path):
    wiring = _wiring()
    program_cache: dict = {}
    install_cics_runtime(
        wiring.context_holder,
        start_queue=wiring.start_queue,
        result_holder=wiring.result_holder,
        program_cache=program_cache,
        transid_to_program={"HP00": "HOPPER"},
        screen_queue=wiring.screen_channel,
        input_queue=wiring.input_channel,
    )
    spec = build_cics_spec()
    program_cache["HOPPER"] = compile_cics_program(
        _UNKNOWN_NEXT_SRC.encode(), cobol_parser, spec
    )
    config = RegionConfig(
        source_dirs=(),
        copybook_dirs=(),
        bms_dirs=(),
        hlasm_export=tmp_path,
        initial_transid="HP00",
        min_commarea_len=0,
        transactions={"HP00": "HOPPER"},
        programs=frozenset({"HOPPER"}),
        system=tmp_path,
        csd_files=(),
    )
    rollbacks: list[str] = []

    region = _region(
        config, wiring, program_cache, lambda: rollbacks.append("rolled back")
    )
    result = region.start("HP00", input_event=InputEvent(eibaid="\x7d"))

    assert (result.kind, result.transid, region.done) == (
        DispatchKind.RETURN_TRANSID,
        "ZZZZ",
        True,
    )
    assert rollbacks == ["rolled back"]
