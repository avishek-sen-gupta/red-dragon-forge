"""The dependency-graph walk over a parsed cache, run as the CLI runs it."""

import json
import subprocess
import sys
from pathlib import Path

from cobble.dataflow.depgraph.edge_line import EdgeLine


def _moving(program: str, source: str, target: str) -> dict:
    return {
        "program_id": program,
        "data_fields": [
            {"name": source, "level": 1, "pic": "X(4)", "offset": 0, "byte_length": 4},
            {"name": target, "level": 1, "pic": "X(4)", "offset": 4, "byte_length": 4},
        ],
        "paragraphs": [
            {
                "name": "MAIN",
                "statements": [
                    {
                        "type": "MOVE",
                        "operands": [{"name": source}, {"name": target}],
                    }
                ],
            }
        ],
    }


def test_every_program_a_member_holds_contributes_its_edges(tmp_path: Path) -> None:
    """A member holding a contained program is two programs, and each moves data of
    its own: the walk writes both programs' edges, attributed to the member."""
    asg_dir = tmp_path / "parsed"
    asg_dir.mkdir()
    (asg_dir / "MEMBERA.json").write_text(
        json.dumps(
            {
                "programs": [
                    {
                        **_moving("OUTER", "WS-A", "WS-B"),
                        "programs": [_moving("INNER", "WS-C", "WS-D")],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    config = tmp_path / "depgraph.toml"
    config.write_text(
        f'[output]\nasg_dir = "{asg_dir}"\ngraph_dir = "{tmp_path / "graph"}"\n',
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "-m",
            "cobble.dataflow.depgraph.build",
            "--config",
            str(config),
        ],
        check=True,
        capture_output=True,
    )

    edges = [
        EdgeLine.model_validate_json(line)
        for line in (tmp_path / "graph" / "edges.jsonl").read_text().splitlines()
    ]
    assert edges == [
        EdgeLine(src="WS-A", dst="WS-B", program="MEMBERA", seq=0, verb="MOVE"),
        EdgeLine(src="WS-C", dst="WS-D", program="MEMBERA", seq=0, verb="MOVE"),
    ]
