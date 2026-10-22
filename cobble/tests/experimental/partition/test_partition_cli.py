"""The three commands chained over files: traces and extents in, graph, clusters, report and page out."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict

from cobble.experimental.partition import clusters_cli, graph_cli, render_cli
from cobble.experimental.partition.extent_row import ExtentRow
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.link_row import LinkRow


class _Range(TypedDict):
    field: str
    region: str
    start: int
    end: int
    clamped: bool


class _Dep(TypedDict):
    kind: str
    program: str
    via: str
    target: _Range | None
    origin: str
    sink: str
    source: _Range | None
    source_program: str
    site: str
    definers: list[str]


def _extent(program: str, path: tuple[str, ...], span: str) -> str:
    return ExtentRow(
        program=program,
        extents=(f"{path[-1]}@{span}",),
        records=(path[0],),
        paths=(path,),
        pics=("X(4)",),
    ).model_dump_json()


def _range(field: str, start: int, end: int) -> _Range:
    return _Range(
        field=field, region="working_storage", start=start, end=end, clamped=False
    )


def _dep(
    site: str, target: _Range | None, source: _Range | None, sink: str = ""
) -> str:
    return json.dumps(
        _Dep(
            kind="dep",
            program="P",
            via="",
            target=target,
            origin="" if source else "LITERAL",
            sink=sink,
            source=source,
            source_program="P",
            site=site,
            definers=[],
        )
    )


def _jsonl(path: Path, lines: Sequence[str]) -> Path:
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return path


def test_the_commands_turn_traces_into_a_graph_clusters_a_report_and_a_page(
    tmp_path: Path,
) -> None:
    extents = _jsonl(
        tmp_path / "extents.jsonl",
        [
            _extent("P", ("IN",), "working_storage[0:8]"),
            _extent("P", ("IN", "A"), "working_storage[0:4]"),
            _extent("P", ("IN", "B"), "working_storage[4:8]"),
            _extent("P", ("OUT",), "working_storage[8:16]"),
            _extent("P", ("OUT", "C"), "working_storage[8:12]"),
            _extent("P", ("OUT", "D"), "working_storage[12:16]"),
            _extent("Q", ("LK",), "linkage[0:8]"),
        ],
    )
    traces = tmp_path / "traces"
    traces.mkdir()
    _jsonl(
        traces / "P.jsonl",
        [
            _dep("P/1", _range("OUT", 8, 16), _range("IN", 0, 8)),
            _dep("P/2", _range("A", 0, 4), None),
            _dep("P/3", None, _range("OUT", 8, 16), sink="FILE:F"),
            _dep("P/1", _range("OUT", 8, 16), _range("IN", 0, 8)),
            json.dumps({"kind": "coverage", "taken": 1, "total": 1}),
        ],
    )
    links = _jsonl(
        tmp_path / "links.jsonl",
        [
            LinkRow(
                caller="P",
                node="n",
                callee="Q",
                caller_extent="OUT@working_storage[8:16]",
                callee_extent="LK@linkage[0:8]",
                returns=False,
            ).model_dump_json()
        ],
    )
    graph_path, clusters_path = tmp_path / "graph.json", tmp_path / "clusters.json"
    report_path, page_path = tmp_path / "clusters.md", tmp_path / "page.html"

    assert (
        graph_cli.main(
            [
                "--extents",
                str(extents),
                "--traces",
                str(traces),
                "--links",
                str(links),
                "--out",
                str(graph_path),
            ]
        )
        == 0
    )
    assert (
        clusters_cli.main(
            [
                "--graph",
                str(graph_path),
                "--out",
                str(clusters_path),
                "--report",
                str(report_path),
            ]
        )
        == 0
    )
    assert (
        render_cli.main(
            [
                "--graph",
                str(graph_path),
                "--clusters",
                str(clusters_path),
                "--out",
                str(page_path),
            ]
        )
        == 0
    )

    graph = FieldGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
    assert graph.barrier == "fanout-8"
    assert [
        (e.source, e.target, e.sites, e.clustered, e.cross_program) for e in graph.edges
    ] == [
        ("P:IN.A", "P:OUT.C", 1, True, False),
        ("P:IN.B", "P:OUT.D", 1, True, False),
        ("P:OUT.C", "P|sink|FILE:F", 1, True, False),
        ("P:OUT.C", "Q:LK.LK", 1, True, True),
        ("P:OUT.D", "P|sink|FILE:F", 1, True, False),
        ("P:OUT.D", "Q:LK.LK", 1, True, True),
        ("P|origin|LITERAL", "P:IN.A", 1, True, False),
    ]
    assert report_path.read_text(encoding="utf-8") == (
        "# Field partitions (barrier fanout-8)\n"
        "\n"
        "2 components of 2+ fields, 2 clusters, 1 isolated field.\n"
        "\n"
        "## Component 0: P, 2 fields\n"
        "\n"
        "terminals: P FILE:F; P LITERAL\n"
        "\n"
        "- cluster 0, 2 fields; records IN (1), OUT (1)\n"
        "  - P.A, P.C\n"
        "\n"
        "## Component 1: P, 2 fields\n"
        "\n"
        "terminals: P FILE:F\n"
        "\n"
        "- cluster 1, 2 fields; records IN (1), OUT (1)\n"
        "  - P.B, P.D\n"
    )
    payload = json.loads(
        page_path.read_text(encoding="utf-8")
        .split("const DATA = ", 1)[1]
        .split(";\n", 1)[0]
    )
    assert [(n["id"], n["cluster"]) for n in payload["nodes"]] == [
        ("P:IN.A", 0),
        ("P:IN.B", 1),
        ("P:OUT.C", 0),
        ("P:OUT.D", 1),
        ("P|origin|LITERAL", -1),
        ("P|sink|FILE:F", -1),
        ("Q:LK.LK", -1),
    ]
