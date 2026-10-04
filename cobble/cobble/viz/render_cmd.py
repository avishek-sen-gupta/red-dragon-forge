"""CLI: render cobble.viz artifacts as HTML diagrams.

Output is always a self-contained .html file — open in any browser.

Modes:

  --mode callgraph        vis.js force-directed graph of cross-program CICS LINK calls.
  --input call-dep.json

  --mode top              Mermaid sequence diagram: cross-program calls in execution order.
  --input sequences.json

  --mode program          Mermaid sequence diagram: intra-program PERFORM tree.
  --input sequences.json
  --program <ENTRY>
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from collections.abc import Callable, Mapping, Sequence
from itertools import groupby
from pathlib import Path

from cobble.path_utils import ensure_parent

_LOG = logging.getLogger(__name__)

_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
<style>
  body {{ font-family: sans-serif; padding: 2em; background: #fafafa; }}
  h1 {{ font-size: 1.1em; color: #444; margin-bottom: 1em; }}
  .mermaid {{ background: white; border: 1px solid #ddd; padding: 1.5em; border-radius: 4px; overflow-x: auto; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="mermaid">
{diagram}
</div>
<script>mermaid.initialize({{ startOnLoad: true }});</script>
</body>
</html>
"""

_DECISION = " ⬡"


def _make_short(programs: list[str]) -> Callable[[str], str]:
    """Return a label-shortening function that strips the common prefix of all
    program names -- unless that prefix is a whole name, which would leave an
    empty label."""
    prefix = os.path.commonprefix(programs) if len(programs) > 1 else ""
    if len(prefix) < 2 or not prefix.isupper() or prefix in programs:
        return lambda p: p
    return lambda p: p[len(prefix) :]


# ── Top-level cross-program diagram ──────────────────────────────────────────


def _render_top(cross: dict) -> str:
    calls = cross.get("calls", [])
    programs: list[str] = []
    seen: set[str] = set()
    for c in calls:
        for p in (c["from_program"], c["to_program"]):
            if p not in seen:
                programs.append(p)
                seen.add(p)
    short = _make_short(programs)

    lines = ["sequenceDiagram"]
    for p in programs:
        lines.append(f"    participant {short(p)} as {p}")
    for c in calls:
        src = short(c["from_program"])
        tgt = short(c["to_program"])
        para = c["via_paragraph"]
        lines.append(f"    {src}->>{tgt}: {para}")
        lines.append(f"    {tgt}-->>{src}: ")
    return "\n".join(lines)


# ── Per-program intra-program diagram ────────────────────────────────────────


def _render_steps(
    steps: Sequence[Mapping],
    program: str,
    pad: str,
    short: Callable[[str], str],
    level: int = 0,
) -> tuple[str, ...]:
    """Steps in order, the ones sharing a decision at ``level`` drawn as one ``alt``
    block with an arm per branch: only one branch runs, so drawing the arms one after
    another would show alternatives as a sequence."""
    return tuple(
        line
        for decision, run in groupby(steps, lambda step: _decision_at(step, level))
        for line in _render_run(tuple(run), decision, program, pad, short, level)
    )


def _decision_at(step: Mapping, level: int) -> str:
    arms = step.get("arms", [])
    return arms[level]["decision"] if len(arms) > level else ""


def _render_run(
    run: Sequence[Mapping],
    decision: str,
    program: str,
    pad: str,
    short: Callable[[str], str],
    level: int,
) -> tuple[str, ...]:
    if decision:
        return _render_alternatives(run, program, pad, short, level)
    return tuple(
        line for step in run for line in _render_step(step, program, pad, short)
    )


def _render_alternatives(
    run: Sequence[Mapping],
    program: str,
    pad: str,
    short: Callable[[str], str],
    level: int,
) -> tuple[str, ...]:
    arms = tuple(
        tuple(grouped)
        for _, grouped in groupby(run, lambda step: step["arms"][level]["arm"])
    )
    return (
        *(
            line
            for position, arm_steps in enumerate(arms)
            for line in (
                f"{pad}{'alt' if position == 0 else 'else'} "
                f"{arm_steps[0]['arms'][level]['label']}",
                *_render_steps(arm_steps, program, pad + "    ", short, level + 1),
            )
        ),
        f"{pad}end",
    )


def _render_step(
    step: Mapping, program: str, pad: str, short: Callable[[str], str]
) -> tuple[str, ...]:
    label = short(program)
    para = step["paragraph"]
    decision = _DECISION if step.get("has_decision") else ""
    children = step.get("children", [])
    calls = _call_arrows(step, label, pad + "    " if children else pad, short)
    if not children:
        return calls or (f"{pad}Note over {label}: {para}{decision}",)
    return (
        f"{pad}rect rgb(235,240,255)",
        f"{pad}    Note over {label}: {para}{decision}",
        *_render_steps(children, program, pad + "    ", short),
        *calls,
        f"{pad}end",
    )


def _call_arrows(
    step: Mapping, label: str, pad: str, short: Callable[[str], str]
) -> tuple[str, ...]:
    """The call a step makes to another program and its return, or nothing. The
    step does not record where the call falls among its paragraph's PERFORMs, so
    it is drawn after them."""
    callee = step.get("callee_program")
    if not callee:
        return ()
    callee_label = short(callee)
    return (
        f"{pad}{label}->>{callee_label}: {step['paragraph']}",
        f"{pad}{callee_label}-->>{label}: ",
    )


def _render_program(program: str, seq: dict) -> str:
    steps = seq.get("steps", [])
    entry = seq.get("entry_paragraph") or program
    callees: list[str] = []
    seen: set[str] = set()

    def _collect(ss: list[dict]) -> None:
        for s in ss:
            c = s.get("callee_program")
            if c and c not in seen:
                callees.append(c)
                seen.add(c)
            _collect(s.get("children", []))

    _collect(steps)
    short = _make_short([program] + callees)

    lines = ["sequenceDiagram"]
    lines.append(f"    participant {short(program)} as {program}")
    for c in callees:
        lines.append(f"    participant {short(c)} as {c}")
    lines.append(f"    Note over {short(program)}: {entry}")
    return "\n".join((*lines, *_render_steps(steps, program, "    ", short)))


# ── Call dependency graph (vis.js force-directed) ────────────────────────────

_VIS_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  body {{ margin: 0; background: #fafafa; font-family: sans-serif; }}
  h1 {{ font-size: 1em; color: #444; padding: 0.8em 1em 0; margin: 0; }}
  #graph {{ width: 100%; height: calc(100vh - 3em); }}
</style>
</head>
<body>
<h1>{title}</h1>
<div id="graph"></div>
<script>
const nodes = new vis.DataSet({nodes_json});
const edges = new vis.DataSet({edges_json});
const container = document.getElementById("graph");
const options = {{
  nodes: {{
    shape: "box",
    font: {{ size: 13, face: "monospace" }},
    color: {{ background: "#f0f4f8", border: "#7090b0", highlight: {{ background: "#d4e6f1", border: "#2980b9" }} }},
    margin: 8,
  }},
  edges: {{
    arrows: {{ to: {{ enabled: true, scaleFactor: 0.6 }} }},
    color: {{ color: "#aaa", highlight: "#555" }},
    smooth: {{ type: "continuous" }},
  }},
  physics: {{
    solver: "forceAtlas2Based",
    forceAtlas2Based: {{ gravitationalConstant: -60, springLength: 120, springConstant: 0.08 }},
    stabilization: {{ iterations: 200 }},
  }},
  layout: {{ improvedLayout: true }},
}};
new vis.Network(container, {{ nodes, edges }}, options);
</script>
</body>
</html>
"""
_VIS_HTML_STATIC = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  body {{ margin: 0; background: #fafafa; font-family: sans-serif; }}
  h1 {{ font-size: 1em; color: #444; padding: 0.8em 1em 0; margin: 0; }}
  #graph {{ width: 100%; height: calc(100vh - 3em); }}
</style>
</head>
<body>
<h1>{title}</h1>
<div id="graph"></div>
<script>
const nodes = new vis.DataSet({nodes_json});
const edges = new vis.DataSet({edges_json});
const container = document.getElementById("graph");
const options = {{
  nodes: {{
    shape: "box",
    font: {{ size: 11, face: "monospace" }},
    margin: 5,
  }},
  edges: {{
    arrows: {{ to: {{ enabled: true, scaleFactor: 0.5 }} }},
    smooth: {{ type: "straight" }},
  }},
  physics: {{ enabled: false }},
  interaction: {{ dragNodes: false, zoomView: true, dragView: true }},
}};
new vis.Network(container, {{ nodes, edges }}, options);
</script>
</body>
</html>
"""


def _render_callgraph_html(graph: dict) -> str:
    raw_nodes = graph.get("nodes", [])
    entry = graph.get("entry", "")
    short = _make_short([n["program"] for n in raw_nodes])

    vis_nodes = []
    for n in raw_nodes:
        prog = n["program"]
        vis_nodes.append(
            {
                "id": prog,
                "label": short(prog),
                "title": prog,
                "color": (
                    {"background": "#d4e6f1", "border": "#2980b9"}
                    if prog == entry
                    else None
                ),
                "font": {"bold": prog == entry},
            }
        )

    vis_edges = []
    eid = 0
    for n in raw_nodes:
        for callee in n.get("calls", []):
            vis_edges.append({"id": eid, "from": n["program"], "to": callee})
            eid += 1

    title = f"Call dependency: {entry}"
    return _VIS_HTML.format(
        title=title,
        nodes_json=json.dumps(vis_nodes),
        edges_json=json.dumps(vis_edges),
    )


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--input", required=True, type=Path, help="call-dep.json or sequences.json"
    )
    p.add_argument("--mode", required=True, choices=["callgraph", "top", "program"])
    p.add_argument("--program", default=None, help="program name for --mode program")
    p.add_argument("--out", required=True, type=Path, help="output .html file")
    args = p.parse_args()

    data: dict = json.loads(args.input.read_text())

    if args.mode == "callgraph":
        html = _render_callgraph_html(data)
    elif args.mode == "top":
        cross = data.get("cross_program", {})
        diagram = _render_top(cross)
        html = _HTML.format(
            title=f"Cross-program sequence: {cross.get('entry', '')}", diagram=diagram
        )
    else:
        if not args.program:
            raise SystemExit("--program required for --mode program")
        per = data.get("per_program", {})
        seq = per.get(args.program)
        if seq is None:
            raise SystemExit(f"Program {args.program!r} not found in sequences.json")
        diagram = _render_program(args.program, seq)
        html = _HTML.format(title=f"Internal sequence: {args.program}", diagram=diagram)

    ensure_parent(args.out).write_text(html)
    _LOG.info("Written: %s", args.out)
