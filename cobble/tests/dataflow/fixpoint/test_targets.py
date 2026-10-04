"""Which program a dynamic call site can reach, and why it may be unknown."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.emit import _declared_extents
from cobble.dataflow.fields.extents_input import declared_layouts
from cobble.dataflow.fields.program_layout import program_layout
from cobble.dataflow.fields.side_tables import extent_row
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


def _asg(member: str) -> CobolASG:
    if not (CACHE / f"{member}.json").is_file():
        pytest.skip(f"no parsed cache for {member}; run cobble-parse-corpus")
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict(
            json.loads((CACHE / f"{member}.json").read_text(encoding="utf-8"))
        )


def _targets(member: str, **options):
    asg = _asg(member)
    flow, _ = analysed(asg, AnalysisOptions(**options)) if options else analysed(asg)
    return {(t.node, t.expression): t for t in flow.targets}


def _candidates(flow) -> dict:
    return {
        (target.node, target.expression): tuple(sorted(target.candidates))
        for target in flow.targets
    }


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


def test_the_layout_read_from_the_extents_table_resolves_the_same_targets(
    tmp_path: Path,
):
    """The stage's input against the arithmetic it replaces, on the same member.

    This is what makes the extents table an input rather than a second opinion. The
    member is the one whose menu table is read at a computed subscript, so the
    candidate set depends on the VALUE image the entry state was seeded from, on
    every occurrence of the table, and on the REDEFINES view the literals were
    declared through -- a layout that lost any of the three would resolve a
    different set, not merely a differently-shaped one.
    """
    asg = _asg("COMEN01C")
    layout = program_layout(asg)
    rows = tuple(extent_row(one) for one in _declared_extents(layout, "COMEN01C"))
    path = tmp_path / "extents.jsonl"
    path.write_text("".join(f"{row}\n" for _, row in rows), encoding="utf-8")

    (published,) = tuple(declared_layouts(path))
    computed, _ = analysed(asg)
    from_file, _ = analysed(asg, layout=published.layout)

    assert _candidates(from_file) == _candidates(computed)
    menu = {
        candidates
        for (_, expression), candidates in _candidates(from_file).items()
        if expression.startswith("CDEMO-MENU-OPT-PGMNAME")
    }
    assert menu == {MENU_PROGRAMS}


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
        ("COUSR03C",),
    ]


def test_an_unsettled_walk_marks_every_site_incomplete():
    found = _targets("COACTUPC", factor=1)

    assert found
    assert all(
        UnresolvedReason.INCOMPLETE_WALK in target.reasons for target in found.values()
    )
    assert not any(target.complete for target in found.values())
