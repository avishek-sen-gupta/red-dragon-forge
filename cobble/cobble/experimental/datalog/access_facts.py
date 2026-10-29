"""Every field read at a CFG node, with its bytes, as facts."""

from pathlib import Path

from cobble.dataflow.fields.access_line import AccessLine
from cobble.experimental.datalog.column import number, symbol
from cobble.experimental.datalog.facts import Facts, Row
from cobble.experimental.datalog.relation import Relation
from cobble.experimental.datalog.run_files import lines, matching

ACCESS = Relation(
    "access",
    (
        symbol("p"),
        symbol("n"),
        symbol("f"),
        symbol("region"),
        number("s"),
        number("e"),
    ),
)


def _access(line: AccessLine) -> Row:
    extent = line.extent
    return (
        line.program,
        line.node,
        extent.field,
        extent.region,
        extent.start,
        extent.end,
    )


def access_facts(run: Path) -> tuple[Facts, ...]:
    return (
        Facts(
            ACCESS,
            tuple(
                _access(AccessLine.model_validate_json(line))
                for path in matching(run / "accesses", "*.jsonl")
                for line in lines(path)
            ),
        ),
    )
