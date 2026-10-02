"""The bundle file: the CFGs, the calls that join them, and the shapes it is read in.

A bundle used to be a list of CFGs with nothing between them, so every consumer that
wanted to cross a call re-derived the join and two of them could disagree. The calls
travel with the CFGs now. The two older shapes -- one CFG per file from the corpus
build, a list from a closure built before this key existed -- are files people have on
disk, so they still load, and what they do not carry is derived.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from cobble.dataflow.srccfg.bundle import (
    Bundle,
    CfgDocumentError,
    bundle_jsonl,
    bundle_of_rows,
    load_bundle,
    rows_of,
)
from cobble.dataflow.srccfg.cfg import Cfg, Edge, EdgeKind, Node, NodeKind
from cobble.dataflow.srccfg.dot import dot_of
from cobble.dataflow.srccfg.dynamic_targets import DynamicSite, DynamicTargets
from cobble.dataflow.srccfg.joined import CallKind, graph_of
from cobble.dataflow.srccfg.link import (
    COMMAREA_RECORD,
    BundleCall,
    aliases,
    bundle_calls,
)
from cobble.dataflow.srccfg.presentation import CrossCall, cross_calls
from cobble.dataflow.srccfg.rows.edge_row import CfgEdgeRow
from cobble.dataflow.srccfg.rows.node_row import CfgNodeRow
from cobble.dataflow.srccfg.rows.program_row import CfgProgramRow
from cobble.dataflow.srccfg.synthetic import using_field


def _label(paragraph: str) -> Node:
    return Node(id=f"{paragraph}#label", kind=NodeKind.LABEL, paragraph=paragraph)


def _call(
    node_id: str,
    program: str,
    resolved: bool = True,
    transfer: str = "CICS_LINK",
    using: tuple[str, ...] = (),
) -> Node:
    """One call node of any of the three kinds CALL_TRANSFERS holds.

    A static CALL carries its arguments in ``using`` and has no commarea; LINK and
    XCTL carry the commarea and no arguments, which is the split the aliasing and the
    edge label both turn on.
    """
    return Node(
        id=node_id,
        kind=NodeKind.CALL,
        paragraph="MAIN",
        transfer=transfer,
        target=program,
        target_resolved=resolved,
        transfer_operand="" if using else "WS-COMMAREA",
        using=using,
    )


def _caller(
    callee: str,
    program: str = "PROGA",
    resolved: bool = True,
    transfer: str = "CICS_LINK",
    using: tuple[str, ...] = (),
) -> Cfg:
    return Cfg(
        program=program,
        nodes=(_label("MAIN"), _call("MAIN/0", callee, resolved, transfer, using)),
        edges=(Edge(source="MAIN#label", target="MAIN/0", kind=EdgeKind.FLOW),),
    )


def _callee(program: str = "PROGB") -> Cfg:
    return Cfg(program=program, nodes=(_label("MAIN"),), edges=())


def _bundle(*cfgs: Cfg) -> Bundle:
    return Bundle(seed=cfgs[0].program, cfgs=cfgs, calls=bundle_calls(cfgs))


def _written(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "cfg.jsonl"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_bundle_round_trips_through_its_rows(tmp_path: Path) -> None:
    """The file is the whole handover: programs in order, an empty one included, and
    the calls joining them. Text that Unicode counts as a line break but JSON does not
    escape -- NEL, which is what EBCDIC 0x15 decodes to, and the two separators --
    stays inside its row."""
    breaking = Node(
        id="MAIN#label",
        kind=NodeKind.LABEL,
        paragraph="MAIN",
        target="A\x85B\u2028C\u2029D",
    )
    bundle = Bundle(
        seed="PROGA",
        cfgs=(
            _caller("PROGB"),
            _callee(),
            Cfg(program="PROGC", nodes=(), edges=()),
            Cfg(program="PROGD", nodes=(breaking,), edges=()),
        ),
        calls=_bundle(_caller("PROGB"), _callee()).calls,
    )

    read = load_bundle(_written(tmp_path, bundle_jsonl(bundle)))

    assert read == bundle


def test_rows_come_program_first_and_every_edge_after_both_its_nodes() -> None:
    """The order a streaming reader relies on, held by the writer."""
    rows = rows_of(_bundle(_caller("PROGB"), _callee()))
    seen = tuple((row.program, row.id) for row in rows if isinstance(row, CfgNodeRow))
    opened = tuple(row.program for row in rows if isinstance(row, CfgProgramRow))

    assert opened == ("PROGA", "PROGB")
    assert all(
        rows.index(row)
        > max(
            at
            for at, other in enumerate(rows)
            if isinstance(other, CfgNodeRow)
            and other.program == row.program
            and other.id in (row.source, row.target)
        )
        for row in rows
        if isinstance(row, CfgEdgeRow)
    )
    assert all(
        rows.index(row)
        > next(
            at
            for at, other in enumerate(rows)
            if isinstance(other, CfgProgramRow) and other.program == row.program
        )
        for row in rows
        if isinstance(row, CfgNodeRow)
    )
    assert len(seen) == len(set(seen))


@pytest.mark.parametrize(
    ("text", "line"),
    (
        ('{"cfgs": [], "calls": []}\n', 1),
        (
            '{"type": "program", "program": "PROGA"}\n{"type": "node", "program": "PRO',
            2,
        ),
    ),
    ids=("pre-jsonl document", "truncated row"),
)
def test_a_line_that_is_not_a_row_is_refused_by_number(
    tmp_path: Path, text: str, line: int
) -> None:
    """A file in the old one-document shape, or one cut off mid-write, says where it
    stops being a CFG file and what to run."""
    path = _written(tmp_path, text)

    with pytest.raises(
        CfgDocumentError, match=f"cfg.jsonl:{line}: .*cobble-srccfg-build"
    ):
        load_bundle(path)


def test_blank_lines_are_not_rows_and_are_skipped(tmp_path: Path) -> None:
    text = bundle_jsonl(_bundle(_callee()))

    read = load_bundle(_written(tmp_path, f"\n{text}\n\n"))

    assert read == _bundle(_callee())


def test_a_row_naming_a_program_no_program_row_opened_is_refused(
    tmp_path: Path,
) -> None:
    stray = '{"type": "edge", "program": "GHOST", "source": "A", "target": "B", "kind": "FLOW"}'
    text = f'{{"type": "program", "program": "PROGA"}}\n{stray}\n'

    with pytest.raises(CfgDocumentError, match="GHOST"):
        load_bundle(_written(tmp_path, text))


def test_a_bundle_carries_the_call_and_the_entry_node_it_lands_on() -> None:
    """The entry is the one thing a CallSite does not know, and the one thing a
    reader crossing to the callee needs."""
    bundle = _bundle(_caller("PROGB"), _callee())

    assert bundle.calls == (
        BundleCall(
            caller="PROGA",
            node="MAIN/0",
            transfer="CICS_LINK",
            program="PROGB",
            entry="MAIN#label",
            resolved=True,
            commarea="WS-COMMAREA",
        ),
    )


def _dynamic(node_id: str, field: str) -> Node:
    return _call(node_id, field, resolved=False)


def _dynamic_caller() -> Cfg:
    return Cfg(
        program="PROGA",
        nodes=(
            _label("MAIN"),
            _dynamic("MAIN/0", "WS-ONE"),
            _dynamic("MAIN/1", "WS-TWO"),
            _dynamic("MAIN/2", "WS-NONE"),
        ),
        edges=(),
    )


DYNAMIC_TARGETS = DynamicTargets(
    sites=MappingProxyType(
        {
            ("PROGA", "MAIN/0"): DynamicSite(candidates=("PROGB",), reasons=()),
            ("PROGA", "MAIN/1"): DynamicSite(
                candidates=("PROGB", "PROGC"), reasons=("from-callee",)
            ),
            ("PROGA", "MAIN/2"): DynamicSite(candidates=(), reasons=("uninitialised",)),
        }
    )
)


def _dynamic_call(
    node: str,
    program: str,
    expression: str,
    reasons: tuple[str, ...],
    certain: bool,
    entry: str = "MAIN#label",
) -> BundleCall:
    return BundleCall(
        caller="PROGA",
        node=node,
        transfer="CICS_LINK",
        program=program,
        entry=entry,
        resolved=False,
        commarea="WS-COMMAREA",
        expression=expression,
        reasons=reasons,
        certain=certain,
    )


def test_a_dynamic_site_is_one_call_per_candidate_each_saying_how_certain_it_is() -> (
    None
):
    """One candidate and no doubt is proven; anything else is a candidate; a site
    with no candidates stays the one unresolved call it always was, now with why."""
    cfgs = (_dynamic_caller(), _callee("PROGB"), _callee("PROGC"))

    calls = bundle_calls(cfgs, DYNAMIC_TARGETS)

    assert calls == (
        _dynamic_call("MAIN/0", "PROGB", "WS-ONE", (), True),
        _dynamic_call("MAIN/1", "PROGB", "WS-TWO", ("from-callee",), False),
        _dynamic_call("MAIN/1", "PROGC", "WS-TWO", ("from-callee",), False),
        _dynamic_call("MAIN/2", "WS-NONE", "WS-NONE", ("uninitialised",), False, ""),
    )
    rows = rows_of(Bundle(seed="PROGA", cfgs=cfgs, calls=calls))
    assert bundle_of_rows(rows).calls == calls


def test_a_dynamic_sites_candidates_are_drawn_and_only_a_proven_one_as_a_call() -> None:
    """A candidate drawn as a plain CALL claims a certainty the analysis does not
    have; one not drawn at all hides the path the closure was built to show."""
    cfgs = (_dynamic_caller(), _callee("PROGB"), _callee("PROGC"))
    calls = bundle_calls(cfgs, DYNAMIC_TARGETS)

    assert cross_calls(cfgs, calls) == (
        CrossCall("PROGA::MAIN/0", "PROGB::MAIN#label", "CICS_LINK", certain=True),
        CrossCall("PROGA::MAIN/1", "PROGB::MAIN#label", "CICS_LINK", certain=False),
        CrossCall("PROGA::MAIN/1", "PROGC::MAIN#label", "CICS_LINK", certain=False),
    )
    assert sorted(
        kind.value
        for _source, _target, kind in graph_of(cfgs, calls).edges(data="kind")
        if isinstance(kind, CallKind)
    ) == ["CALL", "CALL_CANDIDATE", "CALL_CANDIDATE"]
    assert [line for line in dot_of(cfgs, calls).splitlines() if "->" in line] == [
        '    "PROGA::MAIN/0" -> "PROGB::MAIN#label"'
        ' [color="#ef6c00", style=dashed, label="CICS_LINK"];',
        '    "PROGA::MAIN/1" -> "PROGB::MAIN#label"'
        ' [color="#9e9e9e", style=dotted, label="CICS_LINK"];',
        '    "PROGA::MAIN/1" -> "PROGC::MAIN#label"'
        ' [color="#9e9e9e", style=dotted, label="CICS_LINK"];',
    ]


def test_the_calls_a_bundle_carries_draw_what_deriving_them_draws() -> None:
    """The bundle's calls are not a second opinion: they say what the CFGs said."""
    cfgs = (_caller("PROGB"), _callee())

    assert cross_calls(cfgs, bundle_calls(cfgs)) == cross_calls(cfgs)
    assert cross_calls(cfgs) == (
        CrossCall(
            source="PROGA::MAIN/0", target="PROGB::MAIN#label", transfer="CICS_LINK"
        ),
    )


def test_a_renderer_draws_the_same_graph_with_the_calls_and_without_them() -> None:
    """The fallback is not a different picture -- an older file draws as this one."""
    cfgs = (_caller("PROGB"), _callee())

    assert _edges(graph_of(cfgs, bundle_calls(cfgs))) == _edges(graph_of(cfgs))
    assert CallKind.CALL in {
        kind for _source, _target, kind in graph_of(cfgs).edges(data="kind")
    }


def _edges(graph) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        sorted(
            (source[1], target[1], data["kind"].value)
            for source, target, data in graph.edges(data=True)
        )
    )


def test_an_unresolved_call_site_is_carried_and_draws_no_edge() -> None:
    """A dynamic target names a field, not a program: the site is real and the edge
    would point at a program nobody established is on this path."""
    cfgs = (_caller("PROGB", resolved=False), _callee())

    (call,) = bundle_calls(cfgs)
    assert call.resolved is False
    assert cross_calls(cfgs, bundle_calls(cfgs)) == ()
    assert CallKind.CALL not in {
        kind
        for _source, _target, kind in graph_of(cfgs, bundle_calls(cfgs)).edges(
            data="kind"
        )
    }


def test_a_callee_missing_from_the_cache_draws_no_dangling_edge() -> None:
    """Its ASG was never parsed, so it has no entry here; an edge to a node that does
    not exist draws a program that looks built and is not."""
    cfgs = (_caller("PROGZ"),)

    (call,) = bundle_calls(cfgs)
    assert call.entry == ""
    assert cross_calls(cfgs, bundle_calls(cfgs)) == ()
    assert graph_of(cfgs, bundle_calls(cfgs)).number_of_edges() == 1


def test_a_call_out_of_a_program_not_being_drawn_draws_no_edge() -> None:
    """--program takes one member of a closure; the bundle's calls are the whole
    closure's, and one whose caller is not on the page has nothing to leave."""
    cfgs = (_caller("PROGB"), _callee())

    assert cross_calls((_callee(),), bundle_calls(cfgs)) == ()


def _all_three() -> Cfg:
    """One program that LINKs, XCTLs and CALLs, in that order, and flows on."""
    return Cfg(
        program="PROGA",
        nodes=(
            _label("MAIN"),
            _call("MAIN/0", "PROGB", transfer="CICS_LINK"),
            _call("MAIN/1", "PROGC", transfer="CICS_XCTL"),
            _call("MAIN/2", "PROGD", transfer="CALL", using=("WS-ONE", "WS-TWO")),
        ),
        edges=(
            Edge(source="MAIN#label", target="MAIN/0", kind=EdgeKind.FLOW),
            Edge(source="MAIN/0", target="MAIN/1", kind=EdgeKind.FLOW),
            Edge(source="MAIN/1", target="MAIN/2", kind=EdgeKind.FLOW),
        ),
    )


def test_each_kind_of_transfer_is_carried_under_its_own_spelling() -> None:
    """CALL_TRANSFERS holds three and the renderers label an edge with what the entry
    says, so one spelling standing in for another mislabels the picture. Three calls
    out of one program are three entries, none of them collapsed into another."""
    cfgs = (_all_three(), _callee("PROGB"), _callee("PROGC"), _callee("PROGD"))

    assert [
        (call.node, call.transfer, call.program, call.entry)
        for call in bundle_calls(cfgs)
    ] == [
        ("MAIN/0", "CICS_LINK", "PROGB", "MAIN#label"),
        ("MAIN/1", "CICS_XCTL", "PROGC", "MAIN#label"),
        ("MAIN/2", "CALL", "PROGD", "MAIN#label"),
    ]


def test_every_kind_of_transfer_draws_its_own_edge() -> None:
    cfgs = (_all_three(), _callee("PROGB"), _callee("PROGC"), _callee("PROGD"))

    assert cross_calls(cfgs, bundle_calls(cfgs)) == (
        CrossCall(
            source="PROGA::MAIN/0", target="PROGB::MAIN#label", transfer="CICS_LINK"
        ),
        CrossCall(
            source="PROGA::MAIN/1", target="PROGC::MAIN#label", transfer="CICS_XCTL"
        ),
        CrossCall(source="PROGA::MAIN/2", target="PROGD::MAIN#label", transfer="CALL"),
    )


def test_an_xctl_gets_its_edge_and_keeps_the_flow_past_it() -> None:
    """XCTL does not return, and link.py's docstring records why the node keeps a FLOW
    exit anyway: cutting it would claim the code after an XCTL is unreachable when
    another path may reach it. The over-approximation is deliberate -- pinned here so
    that adding the cross edge is never read as licence to drop the flow one."""
    cfgs = (_all_three(), _callee("PROGC"))

    graph = graph_of(cfgs, bundle_calls(cfgs))

    assert graph.has_edge(
        (NodeKind.CALL, "PROGA::MAIN/1"), (NodeKind.LABEL, "PROGC::MAIN#label")
    )
    assert ("PROGA::MAIN/1", "PROGA::MAIN/2", EdgeKind.FLOW.value) in _edges(graph)


def test_a_static_call_is_carried_with_its_arguments_and_no_commarea() -> None:
    """A batch CALL ... USING has no commarea to name: the interface is positional,
    and a commarea invented for it would alias the wrong storage."""
    cfgs = (_caller("PROGB", transfer="CALL", using=("WS-ONE",)), _callee())

    (call,) = bundle_calls(cfgs)

    assert (call.transfer, call.commarea, call.entry) == ("CALL", "", "MAIN#label")


def test_the_two_kinds_of_interface_alias_storage_differently() -> None:
    """The one place the kinds part company in the analysis: USING binds argument by
    position, a commarea binds one record onto DFHCOMMAREA."""
    static = _caller("PROGB", transfer="CALL", using=("WS-ONE", "WS-TWO"))
    transferred = _caller("PROGB", transfer="CICS_XCTL")

    assert [(a.caller_field, a.callee_field) for a in aliases(static)] == [
        ("WS-ONE", using_field(0)),
        ("WS-TWO", using_field(1)),
    ]
    assert [(a.caller_field, a.callee_field) for a in aliases(transferred)] == [
        ("WS-COMMAREA", COMMAREA_RECORD)
    ]
