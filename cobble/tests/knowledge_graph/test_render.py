from pathlib import Path

import networkx as nx
import pytest

from cobble.file_location import NOT_ATTEMPTED
from cobble.knowledge_graph.graph_types import EdgeKind, NodeKind
from cobble.knowledge_graph import render as render_module
from cobble.knowledge_graph.render import render_html


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
