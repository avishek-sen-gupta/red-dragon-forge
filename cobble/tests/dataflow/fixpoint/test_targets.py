"""Which program a dynamic call site can reach, and why it may be unknown."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.fixpoint.fixpoint import analysed
from cobble.dataflow.fixpoint.options import AnalysisOptions
from cobol_asg.asg_types import CobolASG

CACHE = Path(__file__).resolve().parents[3] / "out-parsed"

MENU_PROGRAMS = (
    "COACTUPC",
    "COACTVWC",
    "COBIL00C",
    "COCRDLIC",
    "COCRDSLC",
    "COCRDUPC",
    "COPAUS0C",
    "CORPT00C",
    "COTRN00C",
    "COTRN01C",
    "COTRN02C",
)


def _targets(member: str, **options):
    if not (CACHE / f"{member}.json").is_file():
        pytest.skip(f"no parsed cache for {member}; run cobble-parse-corpus")
    with cached_asg_dialect_parsers_registered():
        asg = CobolASG.from_dict(
            json.loads((CACHE / f"{member}.json").read_text(encoding="utf-8"))
        )
    flow, _ = analysed(asg, AnalysisOptions(**options)) if options else analysed(asg)
    return {(t.node, t.expression): t for t in flow.targets}


def test_a_value_table_read_at_a_computed_subscript_yields_every_declared_program():
    found = _targets("COMEN01C")
    menu = [
        target
        for (_, expression), target in found.items()
        if expression.startswith("CDEMO-MENU-OPT-PGMNAME")
    ]

    assert menu, sorted(expression for _, expression in found)
    assert {tuple(sorted(t.candidates)) for t in menu} == {MENU_PROGRAMS}
    assert {t.reasons for t in menu} == {(UnresolvedReason.UNINITIALISED,)}


def test_a_local_literal_move_resolves_each_site_to_its_own_program():
    found = _targets("COUSR00C")
    per_site = {
        target.node: tuple(sorted(target.candidates))
        for target in found.values()
        if target.expression == "CDEMO-TO-PROGRAM"
    }

    assert sorted(per_site.values()) == [
        ("COADM01C", "COSGN00C"),
        ("COUSR02C",),
        ("COUSR02C",),
        ("COUSR03C",),
        ("COUSR03C",),
    ]


def test_an_unsettled_walk_marks_every_site_incomplete():
    found = _targets("COACTUPC", factor=1)

    assert found
    assert all(
        UnresolvedReason.INCOMPLETE_WALK in target.reasons for target in found.values()
    )
    assert not any(target.complete for target in found.values())
