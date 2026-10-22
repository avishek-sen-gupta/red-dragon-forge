"""The area need reads only call sites the combine resolved completely from the targets table."""

from __future__ import annotations

import json
from pathlib import Path

from cobble.dataflow.fixpoint.target_site import resolved_sites


def _row(node: str, kind: str, candidates: list[str]) -> str:
    return json.dumps(
        {
            "caller": "PROGA",
            "node": node,
            "kind": kind,
            "transfer": "CICS_XCTL" if kind == "program" else "CICS_READ",
            "expression": "WS-NAME",
            "candidates": candidates,
            "reasons": [],
            "dropped": [],
            "outside": [],
        }
    )


def test_a_resolved_file_site_never_reads_as_a_callee(tmp_path: Path) -> None:
    fixpoint, combined = tmp_path / "fixpoint", tmp_path / "combined"
    fixpoint.mkdir()
    combined.mkdir()
    (fixpoint / "jumps.jsonl").write_text("", encoding="utf-8")
    (combined / "targets.jsonl").write_text(
        "\n".join(
            (
                _row("MAIN-PARA/1", "program", ["PROGB"]),
                _row("MAIN-PARA/2", "file", ["USRSEC"]),
            )
        ),
        encoding="utf-8",
    )

    assert resolved_sites(fixpoint, combined, {}) == (
        ("PROGA", "MAIN-PARA/1", ("PROGB",)),
    )
