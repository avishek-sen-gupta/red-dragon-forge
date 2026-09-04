"""The CFG as graphviz DOT, for a person who wants to look at the shape of it.

A rendering, not an analysis: every node and every edge the CFG holds appears and
nothing is summarised, because a picture that drops nodes is a picture of a different
program. The queries in render.py answer questions about one field; "what does the
control flow here look like" has no textual answer that fits on a screen.
"""

from __future__ import annotations

import json
from pathlib import Path

from cobble.dataflow.srccfg.cfg import Atom, Cfg, Edge, EdgeKind, Node, NodeKind
from cobble.dataflow.srccfg.dot import dot_of, load_cfgs, main


def _label(paragraph: str) -> Node:
    return Node(id=f"{paragraph}#label", kind=NodeKind.LABEL, paragraph=paragraph)


def _test_node(node_id: str, text: str, paragraph: str = "MAIN") -> Node:
    return Node(
        id=node_id,
        kind=NodeKind.TEST,
        paragraph=paragraph,
        atom=Atom(text=text, left="WS-FLAG-A", op="==", right="'A'"),
    )


def _assign(node_id: str, field: str, paragraph: str = "MAIN") -> Node:
    return Node(
        id=node_id,
        kind=NodeKind.ASSIGN,
        paragraph=paragraph,
        writes=(field,),
        transfer="MOVE",
    )


def _call(node_id: str, program: str, paragraph: str = "MAIN") -> Node:
    return Node(
        id=node_id,
        kind=NodeKind.CALL,
        paragraph=paragraph,
        transfer="CICS_LINK",
        target=program,
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
            _test_node("MAIN/0", "WS-FLAG-A == 'A'"),
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
        nodes=(_label("MAIN"), _call("MAIN/0", callee)),
        edges=(Edge(source="MAIN#label", target="MAIN/0", kind=EdgeKind.FLOW),),
    )


def test_the_output_is_one_digraph() -> None:
    text = dot_of((_one_program(),))

    assert text.startswith("digraph ")
    assert text.rstrip().endswith("}")


def test_every_node_of_the_cfg_is_a_dot_node() -> None:
    cfg = _branching()

    text = dot_of((cfg,))

    for node in cfg.nodes:
        assert f'"{cfg.program}::{node.id}" [' in text


def test_every_edge_of_the_cfg_is_a_dot_edge() -> None:
    cfg = _branching()

    text = dot_of((cfg,))

    for edge in cfg.edges:
        assert f'"PROGA::{edge.source}" -> "PROGA::{edge.target}"' in text


def test_each_program_is_its_own_cluster_labelled_with_the_program_id() -> None:
    """Node ids repeat across programs -- every member has a MAIN/0 -- so without a
    cluster per program the graphs merge into one wrong graph."""
    text = dot_of((_one_program("PROGA"), _one_program("PROGB")))

    assert text.count("subgraph cluster_") == 2
    assert 'label="PROGA"' in text
    assert 'label="PROGB"' in text


def _declarations(text: str, node_id: str) -> int:
    """Lines that declare a node, not the edge lines that also name it as a target."""
    opening = f'"{node_id}" ['
    return len([line for line in text.split("\n") if line.strip().startswith(opening)])


def test_a_repeated_node_id_in_two_programs_stays_two_nodes() -> None:
    """The consequence of the clusters: PROGA's MAIN/0 and PROGB's MAIN/0 are
    different statements, and one node with two labels is a false picture."""
    text = dot_of((_one_program("PROGA"), _one_program("PROGB")))

    assert _declarations(text, "PROGA::MAIN/0") == 1
    assert _declarations(text, "PROGB::MAIN/0") == 1


def test_a_test_node_is_shaped_differently_from_an_assignment() -> None:
    """Where the branches are is the first thing a reader looks for."""
    text = dot_of((_branching(),))

    assert "shape=diamond" in text.split('"PROGA::MAIN/0" [')[1].split("\n")[0]
    assert "shape=box" in text.split('"PROGA::MAIN/1" [')[1].split("\n")[0]


def test_a_test_node_is_labelled_with_its_predicate() -> None:
    text = dot_of((_branching(),))

    assert "WS-FLAG-A == 'A'" in text


def test_an_assignment_is_labelled_with_what_it_writes() -> None:
    text = dot_of((_one_program(),))

    assert "WS-FLAG-A" in text
    assert "MOVE" in text


def test_the_true_and_false_branches_are_labelled() -> None:
    """Two unlabelled edges out of a diamond leave the reader unable to say which
    way the condition goes -- which is the one thing the picture is for."""
    text = dot_of((_branching(),))

    assert 'label="TRUE"' in text
    assert 'label="FALSE"' in text


def test_a_flow_edge_carries_no_label() -> None:
    """Labelling every edge FLOW is noise on a 4,000-node graph."""
    text = dot_of((_one_program(),))

    assert 'label="FLOW"' not in text


def test_a_double_quote_in_a_predicate_does_not_break_the_dot() -> None:
    """COBOL literals are quoted, and an unescaped quote ends the label early --
    graphviz then fails on the rest of the line, so no picture comes out at all."""
    cfg = Cfg(
        program="PROGA",
        nodes=(_test_node("MAIN/0", 'WS-FLAG-A == "A"'),),
        edges=(),
    )

    text = dot_of((cfg,))

    assert r"WS-FLAG-A == \"A\"" in text


def test_a_backslash_in_a_label_is_escaped() -> None:
    cfg = Cfg(
        program="PROGA",
        nodes=(_test_node("MAIN/0", "WS-PATH == 'A\\B'"),),
        edges=(),
    )

    text = dot_of((cfg,))

    assert r"A\\B" in text


def test_a_call_to_a_program_in_the_bundle_is_an_edge_between_the_clusters() -> None:
    """Without it the SVG is a row of disconnected islands, and the closure -- whose
    whole point is that these programs are one path -- bought nothing."""
    text = dot_of((_caller("PROGB"), _one_program("PROGB")))

    assert '"PROGA::MAIN/0" -> "PROGB::MAIN#label"' in text


def test_a_call_to_a_program_not_in_the_bundle_is_not_an_edge() -> None:
    """A callee absent from the ASG cache has no nodes, and an edge to a node that
    does not exist makes graphviz invent an empty one."""
    text = dot_of((_caller("PROGZ"),))

    assert '-> "PROGZ::' not in text


def test_a_call_node_is_labelled_with_its_target() -> None:
    text = dot_of((_caller("PROGB"), _one_program("PROGB")))

    assert "CICS_LINK" in text
    assert "PROGB" in text


def _closure_file(tmp_path: Path, document) -> Path:
    path = tmp_path / "closure.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _as_dict(cfg: Cfg) -> dict:
    from cobble.dataflow.srccfg.build_corpus import cfg_to_dict

    return cfg_to_dict(cfg)


def test_a_closure_list_loads_as_every_cfg_in_it(tmp_path: Path) -> None:
    path = _closure_file(
        tmp_path, [_as_dict(_one_program("PROGA")), _as_dict(_one_program("PROGB"))]
    )

    assert [cfg.program for cfg in load_cfgs(path)] == ["PROGA", "PROGB"]


def test_a_single_cfg_document_loads_as_a_closure_of_one(tmp_path: Path) -> None:
    """build_one writes one CFG per file and the closure writes a list; a reader who
    has to know which shape they hold before drawing it will pass the wrong one."""
    path = _closure_file(tmp_path, _as_dict(_one_program("PROGA")))

    assert [cfg.program for cfg in load_cfgs(path)] == ["PROGA"]


def test_the_cli_writes_dot_to_stdout(tmp_path: Path, capsys) -> None:
    """stdout, so it pipes into `dot -Tsvg` without a temporary file."""
    path = _closure_file(tmp_path, [_as_dict(_one_program("PROGA"))])

    assert main(["--cfg", str(path)]) == 0
    assert capsys.readouterr().out.startswith("digraph ")


def test_output_sends_the_dot_to_a_file_and_leaves_stdout_empty(
    tmp_path: Path, capsys
) -> None:
    path = _closure_file(tmp_path, [_as_dict(_one_program("PROGA"))])
    out = tmp_path / "cfg.dot"

    main(["--cfg", str(path), "--output", str(out)])

    assert out.read_text(encoding="utf-8").startswith("digraph ")
    assert capsys.readouterr().out == ""


def test_the_cfg_argument_is_required(tmp_path: Path) -> None:
    """Nothing to draw without it, and an empty digraph is a well-formed answer."""
    import pytest

    with pytest.raises(SystemExit) as exit_info:
        main(["--output", str(tmp_path / "cfg.dot")])

    assert exit_info.value.code == 2
