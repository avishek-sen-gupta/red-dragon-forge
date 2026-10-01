"""render_webgl_html() — a self-contained WebGL view of a whole corpus graph.

A sibling of render.py, not a replacement for it. render.py's vis-network page
is for navigating a graph; this one is for showing a corpus-sized graph to
somebody, all of it at once, without lag. Everything here follows from that:

  - Positions arrive precomputed (see layout.sfdp_positions) and no force
    simulation ever runs in the browser. That is the difference between a page
    that opens and a page that hangs.
  - No per-edge label. Six figures of rendered text was the dominant cost of
    the vis-network page at this scale, and an edge's colour already carries
    its kind.
  - Edges name their endpoints by index into the node array, and both node and
    edge kinds are named once and referenced by index, so nothing long repeats
    six figures of times.
  - Filtering and highlighting go through sigma's node/edge reducers -- pure
    functions consulted per frame -- rather than mutating a dataset item by
    item, which is what made filtering the vis-network page a redraw per node.
  - attrs are dropped. They carry verbatim in-stream JCL (jcl_graph's
    attrs["text"]), which has no business in a file meant to be shown around,
    and they were most of the other page's weight.

sigma.js and graphology are vendored (see vendor/) and inlined, so the output
is one file that opens offline with no CDN and no server.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from enum import Enum
from math import sqrt
from pathlib import Path

import networkx as nx
from cobble.knowledge_graph.drawn_node import DrawnNode
from cobble.knowledge_graph.palette import DEFAULT_COLOR, EDGE_COLORS, NODE_COLORS

_VENDOR = Path(__file__).parent / "vendor"
_SIGMA_JS_PATH = _VENDOR / "sigma.min.js"
_GRAPHOLOGY_JS_PATH = _VENDOR / "graphology.umd.min.js"

# A leaf is legible, a hub stands out, and nothing grows so large it swallows
# its neighbourhood: sqrt keeps a degree-10000 node about 30x a degree-1 one in
# area rather than 10000x.
_BASE_SIZE = 2.0
_SIZE_PER_DEGREE = 1.4

_HTML_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  html, body {{ margin: 0; height: 100%; font-family: sans-serif; background: #fff; }}
  #graph {{ position: absolute; inset: 0; }}
  #panel {{
    position: absolute; top: 0; left: 0; max-height: 100%; overflow-y: auto;
    padding: 10px 14px; background: rgba(255,255,255,0.94);
    border-right: 1px solid #ddd; border-bottom: 1px solid #ddd; font-size: 13px;
  }}
  #panel h1 {{ font-size: 14px; margin: 0 0 2px; }}
  #counts {{ color: #666; font-size: 12px; margin-bottom: 8px; }}
  #search {{ width: 100%; box-sizing: border-box; margin-bottom: 8px; }}
  details {{ margin-bottom: 6px; }}
  summary {{ cursor: pointer; color: #444; }}
  label {{ display: block; line-height: 1.5; white-space: nowrap; }}
  .swatch {{
    display: inline-block; width: 9px; height: 9px; margin: 0 4px 0 2px;
    border-radius: 50%; vertical-align: baseline;
  }}
  #selected {{ margin-top: 8px; color: #222; font-family: monospace; font-size: 12px; }}
</style>
</head>
<body>
<div id="graph"></div>
<div id="panel">
  <h1>{title}</h1>
  <div id="counts">{node_count} nodes, {edge_count} edges</div>
  <input type="text" id="search" placeholder="find a name...">
  <details open><summary>Node kinds</summary><div id="node-kinds"></div></details>
  <details><summary>Edge kinds</summary><div id="edge-kinds"></div></details>
  <div id="selected"></div>
</div>
<script>{graphology_js}</script>
<script>{sigma_js}</script>
<script>
const NODE_KINDS = {node_kinds_json};
const EDGE_KINDS = {edge_kinds_json};
const NODE_COLORS = {node_colors_json};
const EDGE_COLORS = {edge_colors_json};
// [label, kindIndex, x, y, size] — see render_webgl.py's _node_row.
const NODES = {nodes_json};
// [sourceIndex, targetIndex, kindIndex] — see _edge_row.
const EDGES = {edges_json};

const DIMMED = "#e8e8e8";

// A hovered arrow has to win against six figures of others, and dimming them
// cannot do it: the emphasis redraw runs with skipIndexation, so sigma never
// re-sorts by zIndex and any edge drawn later paints over the bright one.
// Hiding the rest for the duration of the hover is both correct and the only
// way one arrow is legible in a mat this dense.
//
// Which is also why this is sigma's own minimum thickness rather than anything
// larger: hiding the others is what makes the arrow findable, so extra
// thickness buys nothing -- and it is not free, because the arrowhead below is
// nine times the thickness long. At 4 the head was 36px against the 15px every
// other arrow on the page draws, which reads as a different kind of object
// rather than as the one being pointed at.
const EMPHASIS_EDGE_SIZE = 1.7;

const graph = new graphology.MultiDirectedGraph();
NODES.forEach(([label, kind, x, y, size], index) => {{
  graph.addNode(String(index), {{
    label: label, kind: NODE_KINDS[kind], x: x, y: y, size: size,
    color: NODE_COLORS[NODE_KINDS[kind]],
  }});
}});
EDGES.forEach(([source, target, kind], index) => {{
  graph.addEdgeWithKey(index, String(source), String(target), {{
    kind: EDGE_KINDS[kind], color: EDGE_COLORS[EDGE_KINDS[kind]],
  }});
}});

// Visible kinds and the current search are read by the reducers below, which
// sigma calls per item per frame. Filtering is therefore a set lookup, not a
// mutation of the graph -- nothing is added or removed as you toggle.
const visibleNodeKinds = new Set(NODE_KINDS);
const visibleEdgeKinds = new Set(EDGE_KINDS);
let matching = null;

// What the pointer is over: the edges to keep drawn and the nodes to keep
// coloured. Both null when nothing is hovered. Computed once per hover rather
// than per frame -- graph.edges() on a degree-1361 hub is not a reducer's job.
let emphasisEdges = null;
let emphasisNodes = null;
let dragged = null;

// sigma sizes an arrowhead off the edge's thickness, and its stock ratios
// (2.5 long, 2 wide) off a 1.7px minimum give a head about 4px long -- not
// visible with a whole corpus on screen. Enlarging the head rather than
// thickening the edge puts the extra ink on the end that carries the
// direction, instead of on 113k edge bodies where it would just blur the
// graph into a mat.
const ArrowProgram = Sigma.rendering.createEdgeArrowProgram({{
  lengthToThicknessRatio: 9,
  widenessToThicknessRatio: 6,
}});

const renderer = new Sigma(graph, document.getElementById("graph"), {{
  edgeProgramClasses: {{ arrow: ArrowProgram }},
  // Arrowheads, because every edge kind here is directional and reads wrong
  // without one (A CALLS B is not B CALLS A). sigma's arrow program draws a
  // head quad on top of the body quad, so this is roughly twice the edge
  // geometry of its line program -- the deliberate cost of being readable.
  defaultEdgeType: "arrow",
  // Six figures of edges cannot be redrawn while the camera moves, and labels
  // are the most expensive thing on the canvas: drop both mid-gesture, restore
  // them the moment the gesture ends.
  hideEdgesOnMove: true,
  hideLabelsOnMove: true,
  // Only label a node big enough to be worth naming at the current zoom, so a
  // whole-corpus view draws almost none and zooming in reveals them.
  labelRenderedSizeThreshold: 9,
  labelDensity: 0.5,
  // Hovering an arrow names it, so edges are hit-tested. sigma does that by
  // drawing the whole edge scene a second time into an offscreen framebuffer,
  // one colour per edge, and reading a pixel back on every pointer move -- a
  // second geometry pass plus a GPU sync stall. That is the price of being able
  // to point at one arrow among six figures of them; hovering a NODE lights its
  // incident edges without any of it, so turning this off leaves that working.
  enableEdgeEvents: true,
  zIndex: false,
  nodeReducer: (node, data) => {{
    if (!visibleNodeKinds.has(data.kind)) return {{ ...data, hidden: true }};
    if (emphasisNodes) {{
      if (!emphasisNodes.has(node)) return {{ ...data, color: DIMMED, label: null }};
      return {{ ...data, forceLabel: true }};
    }}
    if (matching && !matching.has(node)) {{
      return {{ ...data, color: DIMMED, label: null, zIndex: 0 }};
    }}
    return data;
  }},
  edgeReducer: (edge, data) => {{
    if (!visibleEdgeKinds.has(data.kind)) return {{ ...data, hidden: true }};
    if (emphasisEdges) {{
      if (!emphasisEdges.has(edge)) return {{ ...data, hidden: true }};
      return {{ ...data, size: EMPHASIS_EDGE_SIZE }};
    }}
    if (matching) return {{ ...data, color: DIMMED }};
    return data;
  }},
}});

function buildKindToggles(containerId, kinds, colors, visible) {{
  const container = document.getElementById(containerId);
  kinds.forEach(kind => {{
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = true;
    checkbox.addEventListener("change", () => {{
      if (checkbox.checked) visible.add(kind); else visible.delete(kind);
      renderer.refresh({{ skipIndexation: true }});
    }});
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background = colors[kind];
    label.append(checkbox, swatch, document.createTextNode(kind));
    container.appendChild(label);
  }});
}}

buildKindToggles("node-kinds", NODE_KINDS, NODE_COLORS, visibleNodeKinds);
buildKindToggles("edge-kinds", EDGE_KINDS, EDGE_COLORS, visibleEdgeKinds);

const search = document.getElementById("search");
search.addEventListener("input", () => {{
  const query = search.value.trim().toLowerCase();
  matching = query
    ? new Set(graph.filterNodes((n, data) => data.label.toLowerCase().includes(query)))
    : null;
  renderer.refresh({{ skipIndexation: true }});
}});

// hideEdgesOnMove skips the edge programs for any frame the camera is moving.
// sigma's own recovery is a refresh scheduled at setTimeout(0) on mouseup,
// which fires while the 200ms inertia animation is still running -- so that
// frame is skipped as well, and once the animation ends nothing renders again.
// The edges then stay missing until the next gesture. A mouseup released
// outside the canvas loses that refresh altogether, with the same result.
// So: after the camera stops changing, and once it is no longer animating,
// redraw once.
let settle = null;
const redrawWhenSettled = () => {{
  clearTimeout(settle);
  settle = setTimeout(() => {{
    // Still coasting on inertia: a redraw now would be skipped too. Wait.
    if (renderer.getCamera().isAnimated()) return redrawWhenSettled();
    renderer.refresh({{ skipIndexation: true }});
  }}, 80);
}};
renderer.getCamera().on("updated", redrawWhenSettled);

function emphasise(edges, nodes) {{
  emphasisEdges = edges;
  emphasisNodes = nodes;
  renderer.refresh({{ skipIndexation: true }});
}}

function clearEmphasis() {{
  if (emphasisEdges === null) return;
  emphasisEdges = null;
  emphasisNodes = null;
  renderer.refresh({{ skipIndexation: true }});
}}

// An edge carries no label, so pointing at one is also the only way to read its
// kind and its direction off the page.
renderer.on("enterEdge", ({{ edge }}) => {{
  const [source, target] = graph.extremities(edge);
  emphasise(new Set([edge]), new Set([source, target]));
  document.getElementById("selected").textContent =
    graph.getEdgeAttribute(edge, "kind") + ": "
    + graph.getNodeAttribute(source, "label")
    + " -> " + graph.getNodeAttribute(target, "label");
}});
renderer.on("leaveEdge", clearEmphasis);
renderer.on("enterNode", ({{ node }}) => {{
  emphasise(new Set(graph.edges(node)), new Set([node, ...graph.neighbors(node)]));
}});
// A drag holds its node's neighbourhood lit even as the pointer leaves it --
// otherwise the thing being dragged goes grey the moment it moves.
renderer.on("leaveNode", () => {{ if (!dragged) clearEmphasis(); }});

// Dragging moves one node and nothing else: sigma redraws from the graph's own
// coordinates, so the incident edges follow and no layout is recomputed. The
// camera must not pan at the same time, hence preventSigmaDefault.
renderer.on("downNode", ({{ node }}) => {{ dragged = node; }});
renderer.on("moveBody", ({{ event }}) => {{
  if (!dragged) return;
  const point = renderer.viewportToGraph(event);
  graph.setNodeAttribute(dragged, "x", point.x);
  graph.setNodeAttribute(dragged, "y", point.y);
  event.preventSigmaDefault();
  event.original.preventDefault();
  event.original.stopPropagation();
}});
const dropNode = () => {{ dragged = null; }};
renderer.on("upNode", dropNode);
renderer.on("upStage", dropNode);

const selected = document.getElementById("selected");
renderer.on("clickNode", ({{ node }}) => {{
  const data = graph.getNodeAttributes(node);
  selected.textContent = data.kind + ": " + data.label
    + " (degree " + graph.degree(node) + ")";
}});
renderer.on("clickStage", () => {{ selected.textContent = ""; }});
</script>
</body>
</html>
"""


def _read_vendored(path: Path) -> str:
    """A vendored library's source, or a clear word about which one is absent."""
    if not path.is_file():
        raise FileNotFoundError(f"WebGL renderer dependency not vendored at {path}")
    return path.read_text()


def _kind_names(kinds: Sequence[Enum]) -> tuple[str, ...]:
    """The distinct kind names present, in first-sighting order."""
    return tuple({kind.value: None for kind in kinds})


def _node_size(degree: int) -> float:
    return _BASE_SIZE + _SIZE_PER_DEGREE * sqrt(degree)


def _node_row(
    label: str,
    kind_index: int,
    point: tuple[float, float],
    degree: int,
) -> tuple[str, int, float, float, float]:
    """One node as the page reads it: [label, kindIndex, x, y, size]."""
    return (label, kind_index, point[0], point[1], _node_size(degree))


def _edge_row(
    source_index: int, target_index: int, kind_index: int
) -> tuple[int, int, int]:
    """One edge as the page reads it: [sourceIndex, targetIndex, kindIndex].

    Three integers and nothing else -- no label, no title, no repeated node id.
    """
    return (source_index, target_index, kind_index)


def _node_rows(
    graph: nx.MultiDiGraph,
    positions: Mapping[DrawnNode, tuple[float, float]],
    kind_names: Sequence[str],
) -> tuple[tuple, ...]:
    """Every node's row, in the graph's own node order.

    Indexes ``positions`` directly, so a node the layout has no point for is a
    KeyError here rather than a node silently drawn at the origin.
    """
    index_of = {name: position for position, name in enumerate(kind_names)}
    return tuple(
        _node_row(
            data["id"],
            index_of[data["kind"].value],
            positions[key],
            graph.degree(key),
        )
        for key, data in graph.nodes(data=True)
    )


def _edge_rows(
    graph: nx.MultiDiGraph, kind_names: Sequence[str]
) -> tuple[tuple[int, int, int], ...]:
    node_index = {key: position for position, key in enumerate(graph.nodes)}
    kind_index = {name: position for position, name in enumerate(kind_names)}
    return tuple(
        _edge_row(
            node_index[source], node_index[target], kind_index[data["kind"].value]
        )
        for source, target, data in graph.edges(data=True)
    )


def _colors_for(kind_names: Sequence[str], palette: Mapping[str, str]) -> Mapping:
    return {name: palette.get(name, DEFAULT_COLOR) for name in kind_names}


def render_webgl_html(
    graph: nx.MultiDiGraph,
    positions: Mapping[DrawnNode, tuple[float, float]],
    output_path: Path,
    *,
    title: str = "Knowledge Graph",
    node_palette: Mapping[str, str] = NODE_COLORS,
    edge_palette: Mapping[str, str] = EDGE_COLORS,
) -> None:
    """Render graph as one self-contained WebGL HTML file at output_path.

    ``positions`` must carry a point for every node -- normally
    :func:`cobble.knowledge_graph.layout.sfdp_positions` of this same graph.
    A node missing from it raises KeyError rather than being drawn at the
    origin, since a pile of nodes at one point reads as a broken layout.

    The palettes default to the shared corpus-graph colours, and are arguments
    because a graph whose kinds are not NodeKind/EdgeKind has none of those names
    -- the variable dependency graph's kinds are declaring sections. Without
    them every kind in such a graph falls back to DEFAULT_COLOR and the legend
    is four identical grey swatches.

    Requires the vendored sigma.js and graphology builds under
    cobble/knowledge_graph/vendor/, and raises FileNotFoundError naming the
    absent one rather than writing a page that renders nothing.
    """
    sigma_js = _read_vendored(_SIGMA_JS_PATH)
    graphology_js = _read_vendored(_GRAPHOLOGY_JS_PATH)

    node_kinds = _kind_names([data["kind"] for _key, data in graph.nodes(data=True)])
    edge_kinds = _kind_names(
        [data["kind"] for _source, _target, data in graph.edges(data=True)]
    )
    node_rows = _node_rows(graph, positions, node_kinds)
    edge_rows = _edge_rows(graph, edge_kinds)

    output_path.write_text(
        _HTML_TEMPLATE.format(
            title=title,
            node_count=f"{len(node_rows):,}",
            edge_count=f"{len(edge_rows):,}",
            graphology_js=graphology_js,
            sigma_js=sigma_js,
            node_kinds_json=json.dumps(node_kinds),
            edge_kinds_json=json.dumps(edge_kinds),
            node_colors_json=json.dumps(_colors_for(node_kinds, node_palette)),
            edge_colors_json=json.dumps(_colors_for(edge_kinds, edge_palette)),
            nodes_json=json.dumps(node_rows),
            edges_json=json.dumps(edge_rows),
        )
    )
