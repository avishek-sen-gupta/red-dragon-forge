"""The callee and caller sides of a line-up, read the way the alias table reads them."""

import json
from collections.abc import Callable, Mapping
from pathlib import Path

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.aliases import (
    NO_EXTENT,
    area_extents,
    callee_received_area,
    received_areas,
)
from cobble.dataflow.fields.extent_text import extent_text
from cobble.dataflow.fixpoint.fixpoint import analysed
from cobol_asg.asg_types import CobolASG

CICS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA.
           05  WS-A             PIC X(4).
           05  WS-B             PIC X(6).
       LINKAGE SECTION.
       01  DFHCOMMAREA          PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC CICS RETURN END-EXEC.
"""

SUBP = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBP.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-B                 PIC X(8).
       01  LK-A                 PIC X(6).
       PROCEDURE DIVISION USING LK-A LK-B.
       MAIN-PARA.
           GOBACK.
"""


def _asg(cache: Path, name: str) -> CobolASG:
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict(json.loads((cache / f"{name}.json").read_text()))


def test_both_sides_of_a_line_up_are_found(
    fixpoint_corpus: Callable[[Mapping[str, str]], Path],
) -> None:
    cache = fixpoint_corpus({"CICSP": CICS, "SUBP": SUBP}).parent / "parsed"
    cics, subp = _asg(cache, "CICSP"), _asg(cache, "SUBP")
    _, cics_index = analysed(cics)
    _, subp_index = analysed(subp)

    assert tuple(map(extent_text, area_extents("WS-AREA", cics_index))) == (
        "WS-AREA@working_storage[0:10]",
    )
    assert area_extents("NO-SUCH-FIELD", cics_index) == ()
    assert tuple(
        (param, extent_text(extent))
        for param, extent in received_areas(cics, cics_index)
    ) == ((0, "DFHCOMMAREA@linkage[0:10]"),)
    assert tuple(
        (param, extent.field_name) for param, extent in received_areas(subp, subp_index)
    ) == ((0, "LK-A"), (1, "LK-B"))
    assert callee_received_area(cache, "CICSP", False, 0).length == 10
    assert callee_received_area(cache, "SUBP", True, 1).field_name == "LK-B"
    assert callee_received_area(cache, "SUBP", True, 5) == NO_EXTENT
    assert callee_received_area(cache, "MISSING", False, 0) == NO_EXTENT
