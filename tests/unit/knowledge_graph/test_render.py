"""Unit tests for render_html() — checks the generated file is well-formed
and self-contained; does not render in a browser."""

from pathlib import Path

import networkx as nx
import pytest

from knowledge_graph.render import render_html
from interpreter.project.graph_types import EdgeKind, NodeKind


def _tiny_graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.add_node(
        (NodeKind.PROGRAM, "MAIN"),
        kind=NodeKind.PROGRAM,
        id="MAIN",
        file_path=None,
        attrs={},
    )
    graph.add_node(
        (NodeKind.PROGRAM, "HELPER"),
        kind=NodeKind.PROGRAM,
        id="HELPER",
        file_path=None,
        attrs={},
    )
    graph.add_edge(
        (NodeKind.PROGRAM, "MAIN"),
        (NodeKind.PROGRAM, "HELPER"),
        kind=EdgeKind.CALL,
        attrs={},
    )
    return graph


def test_render_html_writes_a_file(tmp_path: Path):
    output = tmp_path / "graph.html"
    render_html(_tiny_graph(), output)
    assert output.is_file()


def test_render_html_is_self_contained_no_cdn(tmp_path: Path):
    output = tmp_path / "graph.html"
    render_html(_tiny_graph(), output)
    content = output.read_text()
    assert "cdn." not in content.lower()
    assert "unpkg.com" not in content
    assert "<script src=" not in content


def test_render_html_embeds_node_and_edge_data(tmp_path: Path):
    output = tmp_path / "graph.html"
    render_html(_tiny_graph(), output)
    content = output.read_text()
    assert '"MAIN"' in content
    assert '"HELPER"' in content
    assert '"CALL"' in content


def test_render_html_includes_search_box(tmp_path: Path):
    output = tmp_path / "graph.html"
    render_html(_tiny_graph(), output)
    content = output.read_text()
    assert 'id="search-input"' in content
    assert "searchInput.addEventListener" in content
    assert "network.selectNodes(matchIds)" in content


def test_render_html_edge_title_includes_attrs(tmp_path: Path):
    output = tmp_path / "graph.html"
    graph = nx.MultiDiGraph()
    graph.add_node(
        (NodeKind.STEP, "DELJ.STEP1"),
        kind=NodeKind.STEP,
        id="DELJ.STEP1",
        file_path=None,
        attrs={},
    )
    graph.add_node(
        (NodeKind.INSTREAM_DATA, "DELJ.STEP1.SYSIN"),
        kind=NodeKind.INSTREAM_DATA,
        id="DELJ.STEP1.SYSIN",
        file_path=None,
        attrs={},
    )
    graph.add_edge(
        (NodeKind.STEP, "DELJ.STEP1"),
        (NodeKind.INSTREAM_DATA, "DELJ.STEP1.SYSIN"),
        kind=EdgeKind.READS,
        attrs={"ddname": "SYSIN", "text": "   DELETE A.B CLUSTER"},
    )
    render_html(graph, output)
    content = output.read_text()
    assert "DELETE A.B CLUSTER" in content


def test_render_html_raises_if_vis_network_not_vendored(tmp_path: Path, monkeypatch):
    import knowledge_graph.render as render_module

    monkeypatch.setattr(render_module, "_VENDOR_JS_PATH", tmp_path / "missing.js")
    with pytest.raises(FileNotFoundError):
        render_html(_tiny_graph(), tmp_path / "graph.html")
