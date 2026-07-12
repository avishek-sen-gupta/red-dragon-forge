"""render_html() — a self-contained, interactive HTML visualization of a
merged knowledge graph. No server, no CDN: vis-network is vendored (see
knowledge_graph/vendor/) and inlined directly into the generated file.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import networkx as nx

_VENDOR_JS_PATH = Path(__file__).parent / "vendor" / "vis-network.min.js"

_NODE_COLORS = {
    "PROGRAM": "#4C72B0",
    "COPYBOOK": "#55A868",
    "TRANSACTION": "#C44E52",
    "JOB": "#8172B2",
    "STEP": "#CCB974",
    "DATASET": "#64B5CD",
    "BMS_MAP": "#DD8452",
}

_EDGE_COLORS = {
    "CALL": "#4C72B0",
    "COPY": "#55A868",
    "XCTL": "#C44E52",
    "LINK": "#C44E52",
    "RETURN_TRANSID": "#C44E52",
    "STARTS": "#8172B2",
    "SENDS_MAP": "#DD8452",
    "RECEIVES_MAP": "#DD8452",
    "JCL_STEP_RUNS": "#8172B2",
    "READS": "#64B5CD",
    "WRITES": "#64B5CD",
    "UPDATES": "#64B5CD",
}

_HTML_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  html, body {{ margin: 0; height: 100%; font-family: sans-serif; }}
  #graph {{ width: 100%; height: 80vh; border: 1px solid #ccc; }}
  #controls {{ padding: 8px; }}
  #controls fieldset {{ display: inline-block; vertical-align: top; margin-right: 16px; }}
  label {{ display: block; font-size: 13px; }}
</style>
</head>
<body>
<div id="controls">
  <fieldset id="node-filters"><legend>Node kinds</legend></fieldset>
  <fieldset id="edge-filters"><legend>Edge kinds</legend></fieldset>
  <fieldset id="search-box"><legend>Search</legend>
    <input type="text" id="search-input" placeholder="node name contains...">
  </fieldset>
</div>
<div id="graph"></div>
<script>{vis_js}</script>
<script>
const allNodes = new vis.DataSet({nodes_json});
const allEdges = new vis.DataSet({edges_json});
const container = document.getElementById("graph");
const data = {{ nodes: allNodes, edges: allEdges }};
const options = {{
  nodes: {{ shape: "dot", size: 12 }},
  edges: {{ arrows: "to", font: {{ size: 10, align: "middle" }} }},
  physics: {{ stabilization: true }},
}};
const network = new vis.Network(container, data, options);

// Override vendored .vis-tooltip's white-space:nowrap (added after vis.js
// runs, so it wins the cascade tie) — multi-line attrs (e.g. IDCAMS SYSIN
// text) need to wrap/break instead of running onto one unreadable line.
const tooltipStyle = document.createElement("style");
tooltipStyle.textContent = ".vis-tooltip {{ white-space: pre-wrap !important; max-width: 640px; font-family: monospace !important; }}";
document.head.appendChild(tooltipStyle);

function uniqueValues(dataset, field) {{
  return [...new Set(dataset.get().map(item => item[field]))].sort();
}}

function buildFilterCheckboxes(fieldsetId, values, onChange) {{
  const fieldset = document.getElementById(fieldsetId);
  values.forEach(value => {{
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = true;
    checkbox.addEventListener("change", onChange);
    checkbox.dataset.value = value;
    label.appendChild(checkbox);
    label.appendChild(document.createTextNode(" " + value));
    fieldset.appendChild(label);
  }});
}}

function checkedValues(fieldsetId) {{
  return [...document.querySelectorAll("#" + fieldsetId + " input:checked")].map(cb => cb.dataset.value);
}}

function applyFilters() {{
  const visibleNodeKinds = new Set(checkedValues("node-filters"));
  const visibleEdgeKinds = new Set(checkedValues("edge-filters"));
  allNodes.forEach(node => {{
    allNodes.update({{ id: node.id, hidden: !visibleNodeKinds.has(node.kind) }});
  }});
  allEdges.forEach(edge => {{
    allEdges.update({{ id: edge.id, hidden: !visibleEdgeKinds.has(edge.kind) }});
  }});
}}

buildFilterCheckboxes("node-filters", uniqueValues(allNodes, "kind"), applyFilters);
buildFilterCheckboxes("edge-filters", uniqueValues(allEdges, "kind"), applyFilters);

network.on("selectNode", params => {{
  const selected = params.nodes[0];
  const neighbors = new Set([selected]);
  allEdges.get().forEach(edge => {{
    if (edge.from === selected) neighbors.add(edge.to);
    if (edge.to === selected) neighbors.add(edge.from);
  }});
  allNodes.forEach(node => {{
    allNodes.update({{ id: node.id, opacity: neighbors.has(node.id) ? 1.0 : 0.15 }});
  }});
}});

network.on("deselectNode", () => {{
  allNodes.forEach(node => {{
    allNodes.update({{ id: node.id, opacity: 1.0 }});
  }});
}});

// Case-insensitive substring match against each node's label: dim
// non-matches, native-highlight matches via selectNodes (same halo style
// clicking a node already gives you) — clearing the box restores everyone.
const searchInput = document.getElementById("search-input");
searchInput.addEventListener("input", () => {{
  const query = searchInput.value.trim().toLowerCase();
  if (!query) {{
    network.unselectAll();
    allNodes.forEach(node => {{
      allNodes.update({{ id: node.id, opacity: 1.0 }});
    }});
    return;
  }}
  const matchIds = [];
  allNodes.forEach(node => {{
    const match = node.label.toLowerCase().includes(query);
    if (match) matchIds.push(node.id);
    allNodes.update({{ id: node.id, opacity: match ? 1.0 : 0.15 }});
  }});
  network.selectNodes(matchIds);
}});
</script>
</body>
</html>
"""


def _attrs_suffix(attrs: Mapping) -> str:
    """Format attrs as extra tooltip lines, e.g. IDCAMS SYSIN text — empty
    string (no suffix) when there's nothing to show."""
    if not attrs:
        return ""
    return "\n" + "\n".join(f"{k}: {v}" for k, v in attrs.items())


def _node_id_str(key: tuple) -> str:
    kind, node_id = key
    return f"{kind.value}:{node_id}"


def render_html(
    graph: nx.MultiDiGraph, output_path: Path, *, title: str = "Knowledge Graph"
) -> None:
    """Render graph as one self-contained interactive HTML file at output_path.

    Requires the vendored vis-network build at
    knowledge_graph/vendor/vis-network.min.js (Task 8's vendoring step) —
    raises FileNotFoundError with a clear message if it's missing, rather
    than silently producing a broken page.
    """
    if not _VENDOR_JS_PATH.is_file():
        raise FileNotFoundError(
            f"vis-network not vendored at {_VENDOR_JS_PATH} — see "
            "docs/superpowers/plans/2026-07-07-cobol-knowledge-graph.md Task 8"
        )
    vis_js = _VENDOR_JS_PATH.read_text()

    vis_nodes = []
    for key, data in graph.nodes(data=True):
        vis_nodes.append(
            {
                "id": _node_id_str(key),
                "label": data["id"],
                "kind": data["kind"].value,
                "color": _NODE_COLORS.get(data["kind"].value, "#999999"),
                "title": f"{data['kind'].value}: {data['id']}"
                + _attrs_suffix(data["attrs"]),
            }
        )

    vis_edges = []
    for i, (source, target, data) in enumerate(graph.edges(data=True)):
        vis_edges.append(
            {
                "id": i,
                "from": _node_id_str(source),
                "to": _node_id_str(target),
                "kind": data["kind"].value,
                "label": data["kind"].value,
                "color": _EDGE_COLORS.get(data["kind"].value, "#999999"),
                "title": data["kind"].value + _attrs_suffix(data["attrs"]),
            }
        )

    html = _HTML_TEMPLATE.format(
        title=title,
        vis_js=vis_js,
        nodes_json=json.dumps(vis_nodes),
        edges_json=json.dumps(vis_edges),
    )
    output_path.write_text(html)
