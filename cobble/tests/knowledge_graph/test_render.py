import json
import logging
import shutil
from pathlib import Path

import networkx as nx
import pytest
from cobble.file_location import NOT_ATTEMPTED
from cobble.knowledge_graph import render as render_module
from cobble.knowledge_graph.graph_types import EdgeKind, NodeKind
from cobble.knowledge_graph.render import render_html

from cobble import render_graph, render_graph_webgl


def _sample_graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.add_node(
        (NodeKind.PROGRAM, "COACTVW"),
        kind=NodeKind.PROGRAM,
        id="COACTVW",
        location=NOT_ATTEMPTED,
        attrs={},
    )
    graph.add_node(
        (NodeKind.COPYBOOK, "COCOM01Y"),
        kind=NodeKind.COPYBOOK,
        id="COCOM01Y",
        location=NOT_ATTEMPTED,
        attrs={},
    )
    graph.add_edge(
        (NodeKind.PROGRAM, "COACTVW"),
        (NodeKind.COPYBOOK, "COCOM01Y"),
        kind=EdgeKind.COPY,
        attrs={},
    )
    return graph


def test_render_html_writes_self_contained_file(tmp_path: Path) -> None:
    output_path = tmp_path / "graph.html"

    render_html(_sample_graph(), output_path, title="Test Graph")

    html = output_path.read_text()
    assert "<title>Test Graph</title>" in html
    assert "PROGRAM:COACTVW" in html
    assert "COPYBOOK:COCOM01Y" in html
    assert "vis" in html.lower()


def test_render_html_raises_when_vendored_js_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        render_module, "_VENDOR_JS_PATH", tmp_path / "does-not-exist.js"
    )

    with pytest.raises(FileNotFoundError):
        render_html(_sample_graph(), tmp_path / "graph.html")


def _graph_file(path: Path) -> Path:
    rows = (
        {
            "type": "node",
            "id": "COACTVW",
            "kind": "PROGRAM",
            "file_path": None,
            "file_path_reason": "not_attempted",
            "attrs": {},
        },
        {
            "type": "node",
            "id": "COCOM01Y",
            "kind": "COPYBOOK",
            "file_path": None,
            "file_path_reason": "not_attempted",
            "attrs": {},
        },
        {
            "type": "edge",
            "source": "COACTVW",
            "source_kind": "PROGRAM",
            "target": "COCOM01Y",
            "target_kind": "COPYBOOK",
            "kind": "COPY",
            "attrs": {},
        },
    )
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def test_the_page_lands_beside_the_graph_and_is_titled_by_its_stem(
    tmp_path: Path,
) -> None:
    written = render_graph._render(_graph_file(tmp_path / "carddemo.jsonl"))

    assert written == tmp_path / "carddemo.html"
    assert "<title>carddemo Knowledge Graph</title>" in written.read_text()


def test_webgl_out_is_beside_the_graph_unless_named_and_a_named_path_is_taken_as_given() -> (
    None
):
    graph = Path("out/carddemo.jsonl")

    def placed(*out: str) -> Path:
        return render_graph_webgl._parse_args(["--graph", str(graph), *out]).out(graph)

    assert (placed(), placed("--out", "r/report.html"), placed("--out", ".")) == (
        Path("out/carddemo-webgl.html"),
        Path("r/report.html"),
        Path("."),
    )


@pytest.mark.skipif(
    shutil.which("sfdp") is None, reason="the layout needs graphviz's sfdp"
)
def test_webgl_page_is_written_where_asked_making_its_directory(tmp_path: Path) -> None:
    requested = tmp_path / "not" / "yet" / "report.html"

    written = render_graph_webgl._render(
        _graph_file(tmp_path / "carddemo.jsonl"), requested
    )

    assert written == requested
    assert "<title>carddemo Knowledge Graph</title>" in written.read_text()


@pytest.mark.parametrize("renderer", [render_graph, render_graph_webgl])
def test_a_missing_graph_file_names_the_command_that_writes_one(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, renderer
) -> None:
    caplog.set_level(logging.ERROR)
    absent = tmp_path / "absent.jsonl"

    assert renderer._run(renderer._parse_args(["--graph", str(absent)])) == 1
    assert caplog.messages == [
        f"error: {absent} not found — run `cobble-build --output` first"
    ]
