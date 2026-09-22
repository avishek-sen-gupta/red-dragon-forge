"""The bundle file: the CFGs, the calls that join them, and the shapes it is read in.

A bundle used to be a list of CFGs with nothing between them, so every consumer that
wanted to cross a call re-derived the join and two of them could disagree. The calls
travel with the CFGs now. The two older shapes -- one CFG per file from the corpus
build, a list from a closure built before this key existed -- are files people have on
disk, so they still load, and what they do not carry is derived.
"""

from __future__ import annotations

import json
from pathlib import Path

from cobble.dataflow.srccfg.build_corpus import cfg_dicts_of, cfg_to_dict, load_cfgs
from cobble.dataflow.srccfg.bundle import (
    Bundle,
    bundle_of,
    bundle_to_json,
    load_bundle,
)
from cobble.dataflow.srccfg.cfg import Cfg, Edge, EdgeKind, Node, NodeKind
from cobble.dataflow.srccfg.joined import CallKind, graph_of
from cobble.dataflow.srccfg.link import (
    COMMAREA_RECORD,
    BundleCall,
    aliases,
    bundle_calls,
)
from cobble.dataflow.srccfg.presentation import CrossCall, cross_calls
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


def _written(tmp_path: Path, document) -> Path:
    path = tmp_path / "closure.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


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


def test_a_bundle_round_trips_through_json_with_its_calls() -> None:
    """The file is the whole handover: a call lost in writing is a join the reader
    has to derive again, which is what carrying them exists to stop."""
    bundle = _bundle(_caller("PROGB"), _callee())

    read = bundle_of(json.loads(bundle_to_json(bundle)))

    assert read.calls == bundle.calls
    assert [cfg.program for cfg in read.cfgs] == ["PROGA", "PROGB"]


def test_a_bundle_document_loads_as_its_cfgs_and_its_calls(tmp_path: Path) -> None:
    bundle = _bundle(_caller("PROGB"), _callee())

    read = load_bundle(_written(tmp_path, json.loads(bundle_to_json(bundle))))

    assert [cfg.program for cfg in read.cfgs] == ["PROGA", "PROGB"]
    assert read.calls == bundle.calls


def test_a_closure_list_loads_as_a_bundle_with_no_calls(tmp_path: Path) -> None:
    """A closure built before the calls were written: the CFGs are all it has."""
    path = _written(tmp_path, [cfg_to_dict(_caller("PROGB")), cfg_to_dict(_callee())])

    read = load_bundle(path)

    assert [cfg.program for cfg in read.cfgs] == ["PROGA", "PROGB"]
    assert read.calls == ()


def test_a_single_cfg_document_loads_as_a_bundle_of_one(tmp_path: Path) -> None:
    """What the corpus build writes, one member per file, and never a call between."""
    path = _written(tmp_path, cfg_to_dict(_caller("PROGB")))

    read = load_bundle(path)

    assert [cfg.program for cfg in read.cfgs] == ["PROGA"]
    assert read.calls == ()


def test_every_shape_loads_as_cfgs_for_a_reader_that_wants_only_those(
    tmp_path: Path,
) -> None:
    """load_cfgs is the older door into the same file and stays open on all three."""
    bundle = _bundle(_caller("PROGB"), _callee())
    documents = (
        json.loads(bundle_to_json(bundle)),
        [cfg_to_dict(_caller("PROGB")), cfg_to_dict(_callee())],
        cfg_to_dict(_caller("PROGB")),
    )

    loaded = [
        [cfg.program for cfg in load_cfgs(_written(tmp_path, document))]
        for document in documents
    ]

    assert loaded == [["PROGA", "PROGB"], ["PROGA", "PROGB"], ["PROGA"]]


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


def test_a_reader_that_wants_the_json_sees_the_same_three_shapes() -> None:
    """cobble.viz reads the CFG documents rather than building Cfgs out of them, and
    it is pointed at the same files -- so the branch it takes is this one."""
    bundle = _bundle(_caller("PROGB"), _callee())
    documents = (
        json.loads(bundle_to_json(bundle)),
        [cfg_to_dict(_caller("PROGB")), cfg_to_dict(_callee())],
        cfg_to_dict(_caller("PROGB")),
    )

    assert [
        [cfg["program"] for cfg in cfg_dicts_of(document)] for document in documents
    ] == [["PROGA", "PROGB"], ["PROGA", "PROGB"], ["PROGA"]]


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
