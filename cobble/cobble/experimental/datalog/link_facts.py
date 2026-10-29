"""Every crossing between two programs -- linked and dead-ended -- as facts."""

from pathlib import Path

from cobble.dataflow.combine.link_row import LinkRow
from cobble.experimental.datalog.column import symbol
from cobble.experimental.datalog.encoding import yes_no
from cobble.experimental.datalog.facts import Facts, Row
from cobble.experimental.datalog.relation import Relation
from cobble.experimental.datalog.run_files import lines

LINKED = "ok"
LINK = Relation(
    "link",
    (
        symbol("caller"),
        symbol("n"),
        symbol("transfer"),
        symbol("callee"),
        symbol("cext"),
        symbol("eext"),
        symbol("returns"),
        symbol("why"),
    ),
)
LINK_FILES = ("combine/links.jsonl", "fixpoint/aliases.jsonl")


def _link(row: LinkRow) -> Row:
    return (
        row.caller,
        row.node,
        row.transfer,
        row.callee,
        row.caller_extent,
        row.callee_extent,
        yes_no(row.returns),
        row.reason if row.reason else LINKED,
    )


def link_facts(run: Path) -> tuple[Facts, ...]:
    return (
        Facts(
            LINK,
            tuple(
                _link(LinkRow.model_validate_json(line))
                for name in LINK_FILES
                for line in lines(run / name)
            ),
        ),
    )
