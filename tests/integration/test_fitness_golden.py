# pyright: standard
"""The CardDemo graph must match the tracked golden on identity. Gated on the
bridge JARs + hlasm + the pinned vendor/carddemo submodule (same inputs the KG
build needs). Regenerate the golden via knowledge_graph.fitness.write_golden when
a change intentionally moves the graph."""

import subprocess
import sys
from pathlib import Path

from knowledge_graph.fitness import identity_diff

_ROOT = Path(__file__).resolve().parents[2]
_OUT = _ROOT / "tests" / "integration" / "output"
_GOLD = _ROOT / "tests" / "integration" / "fitness"


def test_carddemo_graph_matches_golden():
    subprocess.run([sys.executable, "knowledge_graph/build_carddemo_graph.py"],
                   cwd=_ROOT, check=True)
    ndiff, ediff = identity_diff(
        _OUT / "carddemo_graph.nodes.jsonl", _OUT / "carddemo_graph.edges.jsonl",
        _GOLD / "carddemo_graph.nodes.jsonl", _GOLD / "carddemo_graph.edges.jsonl",
    )
    assert not ndiff["nodes_missing"] and not ndiff["nodes_extra"], ndiff
    assert not ediff["edges_missing"] and not ediff["edges_extra"], ediff
