"""A cobble-dataflow-fixpoint out-dir written out by hand: one member per program, holding given flow and sink rows."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from cobble.dataflow.fields.origin import NO_ORIGIN, Origin
from cobble.dataflow.fields.sink import Sink
from cobble.dataflow.fixpoint.member_counts import MemberCounts

Row = tuple[str, str]


def flow_row(
    program: str,
    node: str,
    target: str,
    source: str,
    origin: Origin = NO_ORIGIN,
    landing: tuple[int, ...] = (0,),
) -> Row:
    return (
        program,
        json.dumps(
            {
                "type": "edge",
                "source": f"{program}.SRC",
                "source_kind": "FIELD",
                "target": f"{program}.DST",
                "target_kind": "FIELD",
                "kind": "FLOWS_TO",
                "attrs": {
                    "node": node,
                    "source_extent": source,
                    "target_extent": target,
                    "origin": dict(origin.wire()),
                    "landing": list(landing) if origin.is_storage else [],
                    "rebuilt": False,
                },
            }
        ),
    )


def sink_row(
    program: str,
    node: str,
    source: str,
    sink: Sink,
    definers: Sequence[str] = (),
) -> Row:
    return (
        program,
        json.dumps(
            {
                "program": program,
                "node": node,
                "sink": dict(sink.wire()),
                "source_extent": source,
                "definers": list(definers),
            }
        ),
    )


def defs_row(
    program: str,
    node: str,
    extent: str,
    definers: Sequence[str] = (),
    reasons: Sequence[str] = (),
) -> Row:
    return (
        program,
        json.dumps(
            {
                "program": program,
                "node": node,
                "extent": extent,
                "definers": list(definers),
                "values": [],
                "reasons": list(reasons),
            }
        ),
    )


def _lines(path: Path, rows: Sequence[str]) -> None:
    path.write_text("".join(f"{row}\n" for row in rows), encoding="utf-8")


def fixpoint_dir(
    root: Path,
    flows: Sequence[Row],
    sinks: Sequence[Row],
    defs: Sequence[Row] = (),
    jumps: Sequence[Row] = (),
) -> Path:
    """``jumps`` rows are jump_row text, keyed by program like the rest."""
    for program in sorted({program for program, _ in (*flows, *sinks, *jumps)}):
        member = root / "members" / program
        member.mkdir(parents=True)
        _lines(member / "graph.jsonl", [row for at, row in flows if at == program])
        _lines(member / "sinks.jsonl", [row for at, row in sinks if at == program])
        _lines(member / "defs.jsonl", [row for at, row in defs if at == program])
        _lines(member / "jumps.jsonl", [row for at, row in jumps if at == program])
        (member / "counts.json").write_text(
            MemberCounts(member=program, program=program).model_dump_json(),
            encoding="utf-8",
        )
    return root
