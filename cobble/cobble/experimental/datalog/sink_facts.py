"""Bytes leaving a program, and the statements that last wrote them, as facts."""

from pathlib import Path

from cobble.dataflow.fixpoint.sink_row import SinkRow
from cobble.experimental.datalog.column import symbol
from cobble.experimental.datalog.facts import Facts
from cobble.experimental.datalog.relation import Relation
from cobble.experimental.datalog.run_files import lines

_SITE = (symbol("p"), symbol("n"), symbol("skind"), symbol("sname"))
FP_SINK = Relation("fp_sink", (*_SITE, symbol("ext")))
FP_SINK_DEFINER = Relation("fp_sink_definer", (*_SITE, symbol("definer")))


def sink_facts(run: Path) -> tuple[Facts, ...]:
    rows = tuple(
        SinkRow.model_validate_json(line)
        for line in lines(run / "fixpoint" / "sinks.jsonl")
    )
    return (
        Facts(
            FP_SINK,
            tuple(
                (
                    row.program,
                    row.node,
                    str(row.sink.kind),
                    row.sink.name,
                    row.source_extent,
                )
                for row in rows
            ),
        ),
        Facts(
            FP_SINK_DEFINER,
            tuple(
                (row.program, row.node, str(row.sink.kind), row.sink.name, definer)
                for row in rows
                for definer in row.definers
            ),
        ),
    )
