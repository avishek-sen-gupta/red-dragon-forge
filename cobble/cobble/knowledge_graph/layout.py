"""sfdp_positions() — one (x, y) per node, computed once by graphviz's sfdp.

Why precompute at all: a force-directed simulation over a corpus-sized graph
(tens of thousands of nodes, six figures of edges) is the single thing that
makes a browser page unusable. Laying the graph out here, once, means the
renderer receives finished coordinates and never simulates anything -- the page
opens already arranged, with no stabilization pass and no jitter.

sfdp rather than networkx: sfdp is a multilevel C implementation built for
graphs this size, and networkx's own spring_layout needs numpy (not a
dependency here) to be anything but unusably slow. Measured: a corpus graph of
37,140 nodes / 112,629 edges lays out in 48 seconds.

Nodes are handed to graphviz as bare integer indices, never their real ids.
That keeps DOT quoting/escaping out of the picture entirely, and means nothing
graphviz echoes back -- including anything it writes to stderr and this module
puts in an exception -- can carry a corpus identifier.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence

import networkx as nx

from cobble.knowledge_graph.node_key import NodeKey

# -Goverlap=prism spreads overlapping nodes apart after the main layout, which
# is what stops dense neighbourhoods reading as one blob. -Gstart fixes the
# random seed, so the same graph lays out the same way every run.
_SFDP_COMMAND = ("sfdp", "-Tplain", "-Goverlap=prism", "-Gstart=7")

# Generous next to the 48 seconds a corpus-sized graph measured at: a bound
# that stops a hung graphviz hanging a build, not a performance target.
_TIMEOUT_SECONDS = 1800


def _dot(order: Sequence[NodeKey], graph: nx.MultiDiGraph) -> str:
    """The graph as undirected DOT over integer indices into ``order``.

    Undirected because a layout has no use for edge direction, and every node
    is declared explicitly: an isolated node that appears in no edge would
    otherwise be absent from the layout and end up at the origin.
    """
    index = {key: position for position, key in enumerate(order)}
    nodes = " ".join(f"{position};" for position in range(len(order)))
    edges = " ".join(
        f"{index[source]}--{index[target]};" for source, target in graph.edges()
    )
    return f"graph G {{ {nodes} {edges} }}"


def _run_sfdp(dot: str) -> str:
    """sfdp's -Tplain output for this DOT, or an error naming sfdp."""
    try:
        # A fixed command and no shell: nothing here is built from graph data.
        completed = subprocess.run(
            _SFDP_COMMAND,
            input=dot,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            "graphviz's sfdp is not on PATH — install graphviz "
            "(macOS: brew install graphviz; Debian/Ubuntu: apt install graphviz)"
        ) from exc
    if completed.returncode != 0:
        raise RuntimeError(
            f"sfdp failed ({completed.returncode}): {completed.stderr.strip()}"
        )
    return completed.stdout


def _plain_position(fields: Sequence[str]) -> tuple[int, tuple[float, float]]:
    """One "node <index> <x> <y> ..." line as the index and point it states."""
    return int(fields[1]), (float(fields[2]), float(fields[3]))


def _positions_from_plain(
    plain: str, order: Sequence[NodeKey]
) -> Mapping[NodeKey, tuple[float, float]]:
    """The node lines of -Tplain output, keyed back to the original nodes.

    -Tplain interleaves one ``graph`` line, the ``node`` lines, the ``edge``
    lines (which carry spline control points of their own, no node's position)
    and a final ``stop``.
    """
    return {
        order[index]: point
        for index, point in (
            _plain_position(line.split())
            for line in plain.splitlines()
            if line.startswith("node ")
        )
    }


def sfdp_positions(graph: nx.MultiDiGraph) -> Mapping[NodeKey, tuple[float, float]]:
    """Lay the graph out with sfdp and return one (x, y) per node.

    Keys are the graph's own node keys, so the result indexes straight from a
    node the renderer is emitting. Raises FileNotFoundError naming sfdp when
    graphviz is not installed, and RuntimeError carrying sfdp's own complaint
    when it runs but refuses the input — either way, never a layout in which
    every node silently sits at the same point.
    """
    order = tuple(graph.nodes)
    if not order:
        return {}
    return _positions_from_plain(_run_sfdp(_dot(order, graph)), order)
