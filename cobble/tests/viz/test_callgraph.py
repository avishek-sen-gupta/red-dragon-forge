import json
import logging
from pathlib import Path

import pytest
from cobble.viz.callgraph_cmd import _parse_args, _run, extract
from cobble.viz.models import CallDepGraph, CallEdge, ProgramNode


def _node(program: str) -> dict:
    return {
        "type": "node",
        "id": program,
        "kind": "PROGRAM",
        "file_path": f"cbl/{program}.cbl",
        "file_path_reason": None,
        "attrs": {},
    }


def _edge(source: str, target: str, kind: str, attrs: dict) -> dict:
    return {
        "type": "edge",
        "source": source,
        "source_kind": "PROGRAM",
        "target": target,
        "target_kind": "COPYBOOK" if kind == "COPY" else "PROGRAM",
        "kind": kind,
        "attrs": attrs,
    }


def _graph(tmp_path: Path) -> Path:
    rows = (
        _node("A"),
        _node("B"),
        _edge("A", "B", "LINK", {"paragraph": "P1", "commarea": "CA"}),
        _edge("A", "CPY", "COPY", {}),
        _edge("B", "A", "COPY", {}),
        _edge("B", "C", "LINK", {"paragraph": "P2"}),
    )
    path = tmp_path / "carddemo.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def test_only_link_edges_between_target_programs_are_kept(tmp_path: Path) -> None:
    graph = extract(_graph(tmp_path), frozenset({"A", "B"}))

    assert graph == CallDepGraph(
        entry="A",
        nodes=(
            ProgramNode(program="A", calls=("B",), called_by=()),
            ProgramNode(program="B", calls=(), called_by=("A",)),
        ),
        edges=(
            CallEdge(from_program="A", to_program="B", paragraph="P1", commarea="CA"),
        ),
    )


def test_a_missing_graph_file_names_the_command_that_writes_one(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.ERROR)
    absent = tmp_path / "absent.jsonl"
    args = _parse_args(
        [
            "--graph",
            str(absent),
            "--cfg",
            str(tmp_path / "cfg.json"),
            "--out",
            str(tmp_path / "out.json"),
        ]
    )

    assert _run(args) == 1
    assert caplog.messages == [
        f"error: {absent} not found — run `cobble-build --output` first"
    ]
