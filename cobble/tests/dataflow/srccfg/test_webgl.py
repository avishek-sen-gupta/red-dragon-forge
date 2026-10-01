"""The CFG as the WebGL page: what goes into the graph the renderer draws.

graphviz's `dot` does not finish on a closure -- a 6,638-node bundle ran past twelve
minutes -- so this is the only target that shows a whole closure at once. The tests
here are about the graph handed to the renderer, because that is where a wrong
picture comes from; the page itself is knowledge_graph's and tested there.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from pathlib import Path

import networkx as nx
import pytest

from cobble.dataflow.srccfg.bundle import Bundle, bundle_to_json
from cobble.dataflow.srccfg.cfg import Atom, Cfg, Edge, EdgeKind, Node, NodeKind
from cobble.dataflow.srccfg.link import bundle_calls
from cobble.dataflow.srccfg.webgl import (
    EDGE_PALETTE,
    NODE_PALETTE,
    CallKind,
    graph_of,
    main,
    render,
    selected,
)

NO_SFDP = shutil.which("sfdp") is None


def _label(paragraph: str) -> Node:
    return Node(id=f"{paragraph}#label", kind=NodeKind.LABEL, paragraph=paragraph)


def _assign(node_id: str, field: str) -> Node:
    return Node(
        id=node_id,
        kind=NodeKind.ASSIGN,
        paragraph="MAIN",
        writes=(field,),
        transfer="MOVE",
    )


def _one_program(program: str = "PROGA") -> Cfg:
    return Cfg(
        program=program,
        nodes=(_label("MAIN"), _assign("MAIN/0", "WS-FLAG-A")),
        edges=(Edge(source="MAIN#label", target="MAIN/0", kind=EdgeKind.FLOW),),
    )


def _branching() -> Cfg:
    return Cfg(
        program="PROGA",
        nodes=(
            _label("MAIN"),
            Node(
                id="MAIN/0",
                kind=NodeKind.TEST,
                paragraph="MAIN",
                atom=Atom(text="WS-FLAG-A == 'A'"),
            ),
            _assign("MAIN/1", "WS-OUT"),
            _assign("MAIN/2", "WS-OTHER"),
        ),
        edges=(
            Edge(source="MAIN#label", target="MAIN/0", kind=EdgeKind.FLOW),
            Edge(source="MAIN/0", target="MAIN/1", kind=EdgeKind.TRUE),
            Edge(source="MAIN/0", target="MAIN/2", kind=EdgeKind.FALSE),
        ),
    )


def _caller(callee: str) -> Cfg:
    return Cfg(
        program="PROGA",
        nodes=(
            _label("MAIN"),
            Node(
                id="MAIN/0",
                kind=NodeKind.CALL,
                paragraph="MAIN",
                transfer="CICS_LINK",
                target=callee,
            ),
        ),
        edges=(Edge(source="MAIN#label", target="MAIN/0", kind=EdgeKind.FLOW),),
    )


def _labels(graph: nx.MultiDiGraph) -> tuple[str, ...]:
    return tuple(data["id"] for _key, data in graph.nodes(data=True))


def _edge_kinds(graph: nx.MultiDiGraph) -> tuple:
    return tuple(data["kind"] for _s, _t, data in graph.edges(data=True))


def test_every_node_of_the_cfg_is_a_node_of_the_graph() -> None:
    """A picture that drops nodes is a picture of a different program."""
    cfg = _branching()

    assert graph_of((cfg,)).number_of_nodes() == len(cfg.nodes)


def test_every_edge_of_the_cfg_is_an_edge_of_the_graph() -> None:
    cfg = _branching()

    assert graph_of((cfg,)).number_of_edges() == len(cfg.edges)


def test_an_edge_keeps_the_kind_it_had() -> None:
    """The colour of the two arrows out of a TEST is what says which way it goes."""
    kinds = _edge_kinds(graph_of((_branching(),)))

    assert EdgeKind.TRUE in kinds
    assert EdgeKind.FALSE in kinds


def test_a_repeated_node_id_in_two_programs_stays_two_nodes() -> None:
    """Every member has a MAIN/0, and one node with two labels is a false picture."""
    graph = graph_of((_one_program("PROGA"), _one_program("PROGB")))

    assert graph.number_of_nodes() == 4


def test_a_node_reads_with_the_program_it_belongs_to() -> None:
    """ "MOVE WS-FLAG-A" occurs in a dozen members of a closure; without the program
    the label leaves the reader unable to say which one they are looking at."""
    assert "PROGA MOVE WS-FLAG-A" in _labels(graph_of((_one_program("PROGA"),)))


def test_a_call_to_a_program_in_the_bundle_is_an_edge_to_its_entry() -> None:
    """Without it the page is a cloud of disconnected islands, and the closure --
    whose whole point is that these programs are one path -- bought nothing."""
    graph = graph_of((_caller("PROGB"), _one_program("PROGB")))

    assert CallKind.CALL in _edge_kinds(graph)
    assert graph.has_edge(
        (NodeKind.CALL, "PROGA::MAIN/0"), (NodeKind.LABEL, "PROGB::MAIN#label")
    )


def test_a_call_to_a_program_not_in_the_bundle_is_not_an_edge() -> None:
    """Its ASG was never in the cache, so it has no nodes here."""
    graph = graph_of((_caller("PROGZ"),))

    assert CallKind.CALL not in _edge_kinds(graph)
    assert graph.number_of_nodes() == 2


def test_every_node_kind_has_its_own_colour() -> None:
    """A kind missing from the palette falls back to grey, and the legend then shows
    two kinds with one swatch -- which is worse than no legend."""
    assert {kind.value for kind in NodeKind} <= set(NODE_PALETTE)
    assert len(set(NODE_PALETTE.values())) == len(NODE_PALETTE)


def test_every_edge_kind_including_the_cross_program_call_has_its_own_colour() -> None:
    assert {kind.value for kind in EdgeKind} | {kind.value for kind in CallKind} <= set(
        EDGE_PALETTE
    )


def _flat_layout(graph: nx.MultiDiGraph) -> Mapping:
    """A layout that needs no graphviz: every node on one line."""
    return {key: (float(index), 0.0) for index, key in enumerate(graph.nodes)}


def test_the_page_is_written_with_no_external_references(tmp_path: Path) -> None:
    """Self-contained: the page is passed around, and a src= is a broken picture on
    any machine that is not this one."""
    output = tmp_path / "page.html"

    render((_branching(),), output, title="PROGA", layout=_flat_layout)

    assert "<script src=" not in output.read_text(encoding="utf-8")


def test_the_page_carries_the_title_it_was_given(tmp_path: Path) -> None:
    output = tmp_path / "page.html"

    render((_one_program(),), output, title="PROGA source CFG", layout=_flat_layout)

    assert "PROGA source CFG" in output.read_text(encoding="utf-8")


def test_one_program_can_be_selected_out_of_a_closure() -> None:
    """A single member is the readable picture; the closure is the connected one."""
    cfgs = (_one_program("PROGA"), _one_program("PROGB"))

    assert [cfg.program for cfg in selected(cfgs, "PROGB")] == ["PROGB"]


def test_selecting_nothing_keeps_the_whole_closure() -> None:
    cfgs = (_one_program("PROGA"), _one_program("PROGB"))

    assert [cfg.program for cfg in selected(cfgs, "")] == ["PROGA", "PROGB"]


def _closure_file(tmp_path: Path, *cfgs: Cfg) -> Path:
    path = tmp_path / "closure.json"
    path.write_text(
        bundle_to_json(Bundle(seed=cfgs[0].program if cfgs else "", cfgs=cfgs)),
        encoding="utf-8",
    )
    return path


@pytest.mark.skipif(NO_SFDP, reason="the layout needs graphviz's sfdp")
def test_the_cli_writes_a_page_for_the_closure(tmp_path: Path) -> None:
    cfg_path = _closure_file(tmp_path, _branching())
    output = tmp_path / "page.html"

    assert main(("--cfg", str(cfg_path), "--output", str(output))) == 0
    assert output.is_file()


def test_the_cli_refuses_a_program_the_cfg_does_not_hold(tmp_path: Path) -> None:
    """An empty page for a mistyped member is a picture of nothing, and reads as a
    program with no code rather than as a typo."""
    cfg_path = _closure_file(tmp_path, _one_program("PROGA"))
    output = tmp_path / "page.html"

    assert main(("--cfg", str(cfg_path), "--output", str(output), "--program", "PROGZ"))
    assert not output.exists()


def test_the_page_draws_the_call_edge_the_bundle_names(tmp_path: Path) -> None:
    """render takes the bundle's calls, so the page and the DOT join the programs at
    the same two nodes rather than each working the join out for itself."""
    cfgs = (_caller("PROGB"), _one_program("PROGB"))

    graph = graph_of(cfgs, bundle_calls(cfgs))

    assert graph.has_edge(
        (NodeKind.CALL, "PROGA::MAIN/0"), (NodeKind.LABEL, "PROGB::MAIN#label")
    )
    assert _edge_kinds(graph) == _edge_kinds(graph_of(cfgs))
