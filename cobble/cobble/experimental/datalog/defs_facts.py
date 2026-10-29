"""The definitions reaching each read, as facts."""

from pathlib import Path

from cobble.dataflow.fixpoint.reaching_row import ReachingRow
from cobble.experimental.datalog.column import symbol
from cobble.experimental.datalog.facts import Facts
from cobble.experimental.datalog.relation import Relation
from cobble.experimental.datalog.run_files import lines

_USE = (symbol("p"), symbol("n"), symbol("ext"))
FP_USE = Relation("fp_use", _USE)
FP_DEF = Relation("fp_def", (*_USE, symbol("definer")))
FP_DEF_VALUE = Relation("fp_def_value", (*_USE, symbol("v")))
FP_DEF_REASON = Relation("fp_def_reason", (*_USE, symbol("why")))


def defs_facts(run: Path) -> tuple[Facts, ...]:
    rows = tuple(
        ReachingRow.model_validate_json(line)
        for line in lines(run / "fixpoint" / "defs.jsonl")
    )
    return (
        Facts(FP_USE, tuple((row.program, row.node, row.extent) for row in rows)),
        Facts(
            FP_DEF,
            tuple(
                (row.program, row.node, row.extent, definer)
                for row in rows
                for definer in row.definers
            ),
        ),
        Facts(
            FP_DEF_VALUE,
            tuple(
                (row.program, row.node, row.extent, value)
                for row in rows
                for value in row.values
            ),
        ),
        Facts(
            FP_DEF_REASON,
            tuple(
                (row.program, row.node, row.extent, why)
                for row in rows
                for why in row.reasons
            ),
        ),
    )
