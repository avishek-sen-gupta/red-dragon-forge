"""Every jump out of a program, and what its target operand can hold, as facts."""

from pathlib import Path

from cobble.dataflow.jumps.rows import jump_from_row
from cobble.experimental.datalog.column import symbol
from cobble.experimental.datalog.encoding import yes_no
from cobble.experimental.datalog.facts import Facts
from cobble.experimental.datalog.relation import Relation
from cobble.experimental.datalog.run_files import lines

JUMP = Relation("jump", (symbol("p"), symbol("n"), symbol("kind"), symbol("returns")))
JUMP_TARGET_VALUE = Relation(
    "jump_target_value", (symbol("p"), symbol("n"), symbol("v"))
)
JUMP_TARGET_REASON = Relation(
    "jump_target_reason", (symbol("p"), symbol("n"), symbol("why"))
)


def jump_facts(run: Path) -> tuple[Facts, ...]:
    jumps = tuple(map(jump_from_row, lines(run / "fixpoint" / "jumps.jsonl")))
    return (
        Facts(
            JUMP,
            tuple(
                (jump.program, jump.node, jump.kind.value, yes_no(jump.returns))
                for jump in jumps
            ),
        ),
        Facts(
            JUMP_TARGET_VALUE,
            tuple(
                (jump.program, jump.node, value)
                for jump in jumps
                for value in jump.target.values
            ),
        ),
        Facts(
            JUMP_TARGET_REASON,
            tuple(
                (jump.program, jump.node, reason.value)
                for jump in jumps
                for reason in jump.target.reasons
            ),
        ),
    )
