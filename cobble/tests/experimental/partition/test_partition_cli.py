"""The three commands chained over files: a fixpoint out-dir and extents in, graph, clusters, report and page out."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict

import pytest
from tests.dataflow.fixpoint.fixpoint_dir import Row, fixpoint_dir, flow_row, sink_row
from tests.experimental.partition.graphs import LINKED

from cobble.experimental.partition import (
    clusters_cli,
    file_sites_cli,
    graph_cli,
    render_cli,
)
from cobble.experimental.partition.extent_row import ExtentRow
from cobble.experimental.partition.graph_file import write_graph
from cobble.experimental.partition.graph_index import graph_index
from cobble.dataflow.combine.link_row import LinkRow


class _Range(TypedDict):
    field: str
    region: str
    start: int
    end: int
    clamped: bool


def _extent(program: str, path: tuple[str, ...], span: str) -> str:
    return ExtentRow(
        program=program,
        extents=(f"{path[-1]}@{span}",),
        records=(path[0],),
        paths=(path,),
        pics=("X(4)",),
        indexes=((),),
    ).model_dump_json()


def _range(field: str, start: int, end: int) -> _Range:
    return _Range(
        field=field, region="working_storage", start=start, end=end, clamped=False
    )


def _text(found: _Range) -> str:
    return f"{found['field']}@{found['region']}[{found['start']}:{found['end']}]"


def _flow(
    program: str,
    node: str,
    target: _Range,
    source: _Range | None,
    origin: str = "",
    literal: str = "",
) -> Row:
    return flow_row(
        program, node, _text(target), _text(source) if source else "", origin, literal
    )


def _sink(program: str, node: str, source: _Range, sink: str) -> Row:
    return sink_row(program, node, _text(source), sink)


class _Placed(TypedDict):
    source: int
    target: int
    length: int


class _EdgeLine(TypedDict):
    source: str
    target: str
    sites: int
    clustered: bool
    cross_program: bool
    barrier: str
    alignments: list[_Placed]
    aligned: bool
    certainty: str
    reasons: list[str]
    rebuilt: bool


def _edge_line(
    ends: tuple[str, str],
    placed: Sequence[tuple[int, int, int]] = (),
    *,
    cross_program: bool = False,
) -> _EdgeLine:
    return _EdgeLine(
        source=ends[0],
        target=ends[1],
        sites=1,
        clustered=True,
        cross_program=cross_program,
        barrier="fanout-8",
        alignments=[_Placed(source=s, target=t, length=n) for s, t, n in placed],
        aligned=bool(placed),
        certainty="exact",
        reasons=[],
        rebuilt=False,
    )


def _jsonl(path: Path, lines: Sequence[str]) -> Path:
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return path


def test_the_commands_turn_a_fixpoint_out_dir_into_a_graph_clusters_a_report_and_a_page(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
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
            _extent("UNTRACED", ("REC",), "working_storage[0:8]"),
        ],
    )
    fixpoint = fixpoint_dir(
        tmp_path / "fixpoint",
        [
            _flow("P", "1", _range("OUT", 8, 16), _range("IN", 0, 8)),
            _flow("P", "2", _range("A", 0, 4), None, origin="LITERAL", literal="'Y'"),
        ],
        [_sink("P", "3", _range("OUT", 8, 16), "FILE:F")],
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
    graph_path = tmp_path / "graph" / "graph.jsonl"
    clusters_path = tmp_path / "clusters.jsonl"
    report_path, render_dir = tmp_path / "clusters.md", tmp_path / "render"

    with caplog.at_level(logging.INFO):
        assert (
            graph_cli.main(
                [
                    "--extents",
                    str(extents),
                    "--fixpoint",
                    str(fixpoint),
                    "--links",
                    str(links),
                    "--out",
                    str(graph_path),
                ]
            )
            == 0
        )
    assert [
        record.getMessage()
        for record in caplog.records
        if "extent rows" in record.getMessage()
    ] == [
        *(f"partition graph: extent rows read {n}/8" for n in range(1, 9)),
        "partition graph: extent rows read 8/8 done",
        "partition graph: extent rows kept 7 of 8, for 2 programs",
    ]
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
                "--out",
                str(render_dir),
            ]
        )
        == 0
    )

    graph_lines = [json.loads(line) for line in graph_path.read_text().splitlines()]
    assert [line["node"]["id"] for line in graph_lines if "node" in line] == [
        "P:IN.A",
        "P:IN.B",
        "P:OUT.C",
        "P:OUT.D",
        "P|origin|LITERAL 'Y'",
        "P|sink|FILE:F",
        "Q:LK.LK",
    ]
    assert [line["edge"] for line in graph_lines if "edge" in line] == [
        _edge_line(("P:IN.A", "P:OUT.C"), ((0, 0, 4),)),
        _edge_line(("P:IN.B", "P:OUT.D"), ((0, 0, 4),)),
        _edge_line(("P:OUT.C", "P|sink|FILE:F")),
        _edge_line(("P:OUT.C", "Q:LK.LK"), ((0, 0, 4),), cross_program=True),
        _edge_line(("P:OUT.D", "P|sink|FILE:F")),
        _edge_line(("P:OUT.D", "Q:LK.LK"), ((0, 4, 4),), cross_program=True),
        _edge_line(("P|origin|LITERAL 'Y'", "P:IN.A")),
    ]
    assert len(graph_lines) == 14
    assert [json.loads(line) for line in clusters_path.read_text().splitlines()] == [
        {
            "cluster": {
                "id": 0,
                "component": 0,
                "program": "P",
                "members": ["P:IN.A", "P:OUT.C"],
            }
        },
        {
            "cluster": {
                "id": 1,
                "component": 1,
                "program": "P",
                "members": ["P:IN.B", "P:OUT.D"],
            }
        },
        {"isolated": "Q:LK.LK"},
    ]
    assert report_path.read_text(encoding="utf-8") == (
        "# Field partitions (barrier fanout-8)\n"
        "\n"
        "2 components of 2+ fields, 2 clusters, 1 isolated field.\n"
        "\n"
        "## Component 0: P, 2 fields\n"
        "\n"
        "terminals: P FILE:F; P LITERAL 'Y'\n"
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
        (render_dir / "programs" / "P.html")
        .read_text(encoding="utf-8")
        .split("const DATA = ", 1)[1]
        .split(";\n", 1)[0]
    )
    assert [(n["id"], n["component"]) for n in payload["nodes"]] == [
        ("P:IN.A", 0),
        ("P:IN.B", 1),
        ("P:OUT.C", 0),
        ("P:OUT.D", 1),
        ("P|origin|LITERAL 'Y'", -1),
        ("P|sink|FILE:F", -1),
        ("Q:LK.LK", -1),
    ]


def _kg_edge(
    source: tuple[str, str], kind: str, target: tuple[str, str], **attrs: str
) -> str:
    return json.dumps(
        {
            "type": "edge",
            "source": source[0],
            "source_kind": source[1],
            "target": target[0],
            "target_kind": target[1],
            "kind": kind,
            "attrs": attrs,
        }
    )


def _dataset_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    extents = _jsonl(
        tmp_path / "extents.jsonl",
        [
            _extent("P", ("OUT",), "working_storage[8:16]"),
            _extent("P", ("OUT", "C"), "working_storage[8:12]"),
            _extent("P", ("OUT", "D"), "working_storage[12:16]"),
            _extent("R", ("RIN",), "working_storage[0:8]"),
            _extent("R", ("RIN", "RA"), "working_storage[0:4]"),
            _extent("R", ("RIN", "RB"), "working_storage[4:8]"),
            _extent("R", ("RCICS",), "working_storage[8:16]"),
        ],
    )
    fixpoint = fixpoint_dir(
        tmp_path / "fixpoint",
        [
            _flow("R", "1", _range("RIN", 0, 8), None, origin="FILE:IN-FILE"),
            _flow("R", "9", _range("RCICS", 8, 16), None, origin="FILE:LIT-ACCT"),
        ],
        [_sink("P", "3", _range("OUT", 8, 16), "FILE:OUT-FILE")],
    )
    graph = _jsonl(
        tmp_path / "knowledge-graph.jsonl",
        [
            _kg_edge(
                ("P", "PROGRAM"),
                "WRITES",
                ("OUT", "COBOL_FILE"),
                select_name="OUT-FILE",
            ),
            _kg_edge(("J.S1", "STEP"), "JCL_STEP_RUNS", ("P", "PROGRAM")),
            _kg_edge(("J.S1", "STEP"), "WRITES", ("DS.X", "DATASET"), ddname="OUT"),
            _kg_edge(
                ("R", "PROGRAM"), "READS", ("IN", "COBOL_FILE"), select_name="IN-FILE"
            ),
            _kg_edge(("J.S2", "STEP"), "JCL_STEP_RUNS", ("R", "PROGRAM")),
            _kg_edge(("J.S2", "STEP"), "READS", ("DS.X", "DATASET"), ddname="IN"),
        ],
    )
    targets = _jsonl(
        tmp_path / "targets.jsonl",
        [
            json.dumps(
                {
                    "caller": "R",
                    "node": "9",
                    "kind": "file",
                    "candidates": ["ACCTDAT"],
                    "reasons": [],
                }
            )
        ],
    )
    return extents, fixpoint, graph, targets


def _graph(arguments: Sequence[str], out: Path) -> list[dict[str, dict[str, str]]]:
    assert graph_cli.main([*arguments, "--out", str(out)]) == 0
    return [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]


def _dataset_view(
    lines: list[dict[str, dict[str, str]]],
) -> tuple[list[str], list[tuple[str, str, str]]]:
    return (
        [
            line["node"]["id"]
            for line in lines
            if "node" in line and line["node"]["kind"] == "dataset"
        ],
        [
            (line["edge"]["source"], line["edge"]["target"], line["edge"]["certainty"])
            for line in lines
            if "edge" in line and not line["edge"]["clustered"]
        ],
    )


def test_without_a_knowledge_graph_the_graph_has_no_dataset_links(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    extents, fixpoint, _, targets = _dataset_inputs(tmp_path)
    base = ["--extents", str(extents), "--fixpoint", str(fixpoint)]

    with caplog.at_level(logging.INFO):
        plain = _graph(base, tmp_path / "plain.jsonl")
        targeted = _graph(
            [*base, "--targets", str(targets)], tmp_path / "targeted.jsonl"
        )

    assert (tmp_path / "plain.jsonl").read_bytes() == (
        tmp_path / "targeted.jsonl"
    ).read_bytes()
    assert plain == targeted
    assert _dataset_view(plain) == ([], [])
    assert (
        caplog.text.count(
            "partition graph: no knowledge graph given, dataset links off"
        )
        == 2
    )


def test_with_a_knowledge_graph_file_sites_become_dataset_links(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    extents, fixpoint, graph, targets = _dataset_inputs(tmp_path)
    base = [
        "--extents",
        str(extents),
        "--fixpoint",
        str(fixpoint),
        "--knowledge-graph",
        str(graph),
    ]

    with caplog.at_level(logging.INFO):
        full = _graph([*base, "--targets", str(targets)], tmp_path / "full.jsonl")
        batch = _graph(base, tmp_path / "batch.jsonl")

    batch_links = [
        ("DS.X[0:4]", "R:RIN.RA", "exact"),
        ("DS.X[4:8]", "R:RIN.RB", "exact"),
        ("P:OUT.C", "DS.X[0:4]", "exact"),
        ("P:OUT.D", "DS.X[4:8]", "exact"),
    ]
    assert _dataset_view(full) == (
        ["ACCTDAT[0:8]", "DS.X[0:4]", "DS.X[4:8]"],
        [("ACCTDAT[0:8]", "R:RCICS.RCICS", "exact"), *batch_links],
    )
    assert _dataset_view(batch) == (
        ["DS.X[0:4]", "DS.X[4:8]", "R/9|?LIT-ACCT"],
        [*batch_links, ("R/9|?LIT-ACCT", "R:RCICS.RCICS", "possible")],
    )
    assert (
        caplog.text.count(
            "partition graph: no targets given, CICS file sites unresolved"
        )
        == 1
    )
    assert [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith(
            ("partition graph: dataset", "partition graph: 3 slots")
        )
    ] == [
        "partition graph: dataset sites 3 exact, 0 possible, 0 unresolved",
        "partition graph: 3 slots, 5 dataset edges",
        "partition graph: dataset sites 2 exact, 0 possible, 1 unresolved",
        "partition graph: 3 slots, 5 dataset edges",
    ]


def test_file_sites_report_each_route_and_why_the_rest_resolve_to_no_dataset(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _, fixpoint, graph, targets = _dataset_inputs(tmp_path)
    untargeted = _jsonl(tmp_path / "untargeted.jsonl", [])
    base = ["--fixpoint", str(fixpoint), "--knowledge-graph", str(graph)]

    with caplog.at_level(logging.INFO):
        assert file_sites_cli.main([*base, "--targets", str(targets)]) == 0
        assert file_sites_cli.main([*base, "--targets", str(untargeted)]) == 0

    assert [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("partition file sites: ")
        and "reading provenance" not in record.getMessage()
    ] == [
        "partition file sites: 3 file sites: 1 resolved by a CICS file target, "
        "2 by a SELECT, 0 unresolved-file",
        "partition file sites: 3 file sites: 0 resolved by a CICS file target, "
        "2 by a SELECT, 1 unresolved-file",
        "partition file sites: 1 unresolved-file sites: selects-under-other-names, "
        "e.g. R/9 LIT-ACCT",
    ]


def _embedded_ids(page: Path) -> list[str]:
    payload = json.loads(
        page.read_text(encoding="utf-8").split("const DATA = ", 1)[1].split(";\n", 1)[0]
    )
    return [node["id"] for node in payload["nodes"]]


def test_the_render_writes_a_map_shared_scripts_and_one_page_per_program(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    graph, out = tmp_path / "graph.jsonl", tmp_path / "render"
    write_graph(graph, LINKED)
    arguments = ["--graph", str(graph), "--out", str(out)]

    with caplog.at_level(logging.INFO):
        assert render_cli.main(arguments) == 0
    assert render_cli.main(arguments) == 0

    assert sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()) == [
        "index.html",
        "programs/P.html",
        "programs/Q.html",
        "programs/S.html",
        "scripts/graphology-library.min.js",
        "scripts/graphology.umd.min.js",
        "scripts/sigma.min.js",
    ]
    assert _embedded_ids(out / "programs" / "S.html") == [
        "Q:REC.B",
        "S:REC.A",
        "S:REC.B",
    ]
    assert (out / "programs" / "P.html").read_text(encoding="utf-8").count(
        '<script src="../scripts/sigma.min.js"></script>'
    ) == 1
    assert [
        record.getMessage()
        for record in caplog.records
        if "largest" in record.getMessage()
    ] == ["partition render: largest neighbourhood P, 11 nodes"]


def test_each_page_written_logs_its_program_size_and_the_time_left(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ticks = iter((100.0, 110.0, 120.0, 130.0))
    with caplog.at_level(logging.INFO):
        render_cli.write_pages(tmp_path, graph_index(LINKED), lambda: next(ticks))

    assert [record.getMessage() for record in caplog.records] == [
        "partition render: pages written 1/3: P, 11 nodes, about 0h00m20s left",
        "partition render: pages written 2/3: Q, 9 nodes, about 0h00m10s left",
        "partition render: pages written 3/3: S, 3 nodes, about 0h00m00s left",
        "partition render: largest neighbourhood P, 11 nodes",
    ]
