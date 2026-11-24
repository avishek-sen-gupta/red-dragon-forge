"""cobble-experimental-codeql-demo: CodeQL's graph and its dataflow paths, as one WebGL page."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest
from cobble.experimental.codeql.demo.demo_cli import main
from cobble.experimental.codeql.demo.drawn_edge import DrawnEdge
from cobble.experimental.codeql.demo.drawn_kind import DrawnKind
from cobble.experimental.codeql.demo.graph import control_graph, with_flows
from cobble.experimental.codeql.demo.results import load_results

NO_SFDP = shutil.which("sfdp") is None


def _decoded(path: Path, tuples: Sequence[Sequence[str]]) -> None:
    columns = [{"kind": "String"} for _ in tuples[0]] if tuples else []
    path.write_text(json.dumps({"#select": {"columns": columns, "tuples": tuples}}))


def _results(directory: Path) -> Path:
    directory.mkdir()
    _decoded(
        directory / "CfgNodes.json",
        [
            ["PROGA", "MAIN#label", "LABEL", "PROGA MAIN#label"],
            ["PROGA", "MAIN/0", "READ", "PROGA READ IN-FILE"],
            ["PROGA", "MAIN/1", "ASSIGN", "PROGA MOVE → OUT-ID"],
            ["PROGA", "MAIN/2", "WRITE", "PROGA WRITE OUT-REC"],
            ["PROGB", "MAIN/0", "DISPLAY", "PROGB DISPLAY"],
        ],
    )
    _decoded(
        directory / "CfgEdges.json",
        [
            ["PROGA", "MAIN#label", "MAIN/0", "FLOW"],
            ["PROGA", "MAIN/0", "MAIN/1", "FLOW"],
            ["PROGA", "MAIN/1", "MAIN/2", "FLOW"],
        ],
    )
    _decoded(
        directory / "ReadToWriteSteps.json",
        [["PROGA", "MAIN/0", "MAIN/1"], ["PROGA", "MAIN/1", "MAIN/2"]],
    )
    _decoded(directory / "ReadToDisplaySteps.json", [])
    return directory


def test_the_graph_is_codeqls_control_flow_with_each_query_as_an_edge_kind(
    tmp_path: Path,
) -> None:
    results = load_results(_results(tmp_path / "results"))
    control = control_graph(results)
    drawn = with_flows(control, results)

    assert sorted(
        (node[1], node[0], data["id"]) for node, data in drawn.nodes(data=True)
    ) == [
        ("PROGA:MAIN#label", DrawnKind.LABEL, "PROGA MAIN#label"),
        ("PROGA:MAIN/0", DrawnKind.READ, "PROGA READ IN-FILE"),
        ("PROGA:MAIN/1", DrawnKind.ASSIGN, "PROGA MOVE → OUT-ID"),
        ("PROGA:MAIN/2", DrawnKind.WRITE, "PROGA WRITE OUT-REC"),
        ("PROGB:MAIN/0", DrawnKind.DISPLAY, "PROGB DISPLAY"),
    ]
    assert sorted(
        (source[1], target[1], data["kind"].value)
        for source, target, data in control.edges(data=True)
    ) == [
        ("PROGA:MAIN#label", "PROGA:MAIN/0", "FLOW"),
        ("PROGA:MAIN/0", "PROGA:MAIN/1", "FLOW"),
        ("PROGA:MAIN/1", "PROGA:MAIN/2", "FLOW"),
    ]
    assert sorted(
        (source[1], target[1], data["kind"])
        for source, target, data in drawn.edges(data=True)
        if data["kind"] in (DrawnEdge.READ_TO_WRITE, DrawnEdge.READ_TO_DISPLAY)
    ) == [
        ("PROGA:MAIN/0", "PROGA:MAIN/1", DrawnEdge.READ_TO_WRITE),
        ("PROGA:MAIN/1", "PROGA:MAIN/2", DrawnEdge.READ_TO_WRITE),
    ]


def _page_constant(page: str, name: str) -> str:
    [found] = re.findall(rf"const {name} = (.*?);\n", page)
    return found


@pytest.mark.skipif(NO_SFDP, reason="needs graphviz's sfdp on PATH")
def test_the_command_writes_one_page_holding_every_program_and_flow(
    tmp_path: Path,
) -> None:
    output = tmp_path / "demo.html"

    assert (
        main(
            ["--results", str(_results(tmp_path / "results")), "--output", str(output)]
        )
        == 0
    )

    page = output.read_text()
    assert json.loads(_page_constant(page, "EDGE_KINDS")) == ["FLOW", "READ → WRITE"]
    assert sorted(json.loads(_page_constant(page, "NODE_KINDS"))) == [
        "ASSIGN",
        "DISPLAY",
        "LABEL",
        "READ",
        "WRITE",
    ]
    assert sorted(row[0] for row in json.loads(_page_constant(page, "NODES"))) == [
        "PROGA MAIN#label",
        "PROGA MOVE → OUT-ID",
        "PROGA READ IN-FILE",
        "PROGA WRITE OUT-REC",
        "PROGB DISPLAY",
    ]
    assert len(json.loads(_page_constant(page, "EDGES"))) == 5
