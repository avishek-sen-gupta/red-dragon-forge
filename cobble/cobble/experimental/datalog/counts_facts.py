"""Each fixpoint member's counts, dead ends and unresolved reasons as facts."""

from pathlib import Path

from cobble.dataflow.fixpoint.member_counts import MemberCounts
from cobble.experimental.datalog.column import number, symbol
from cobble.experimental.datalog.encoding import yes_no
from cobble.experimental.datalog.facts import Facts, Row
from cobble.experimental.datalog.relation import Relation
from cobble.experimental.datalog.run_files import matching

FP_COUNTS = Relation(
    "fp_counts",
    (
        symbol("p"),
        symbol("settled"),
        number("writes"),
        number("covered"),
        number("unhandled"),
        number("unmodelled"),
        number("dynamic"),
        number("files"),
    ),
)
FP_DEAD_END = Relation("fp_dead_end", (symbol("p"), symbol("why")))
FP_UNRESOLVED = Relation("fp_unresolved", (symbol("p"), symbol("why")))


def _counts(counts: MemberCounts) -> Row:
    return (
        counts.program,
        yes_no(counts.settled),
        counts.writes,
        counts.covered,
        counts.unhandled,
        counts.unmodelled,
        counts.dynamic_sites,
        counts.file_sites,
    )


def counts_facts(run: Path) -> tuple[Facts, ...]:
    members = tuple(
        MemberCounts.model_validate_json(path.read_text(encoding="utf-8"))
        for path in matching(run / "fixpoint" / "members", "*/counts.json")
    )
    return (
        Facts(FP_COUNTS, tuple(map(_counts, members))),
        Facts(
            FP_DEAD_END,
            tuple((one.program, why) for one in members for why in one.dead_ends),
        ),
        Facts(
            FP_UNRESOLVED,
            tuple(
                (one.program, why) for one in members for why in one.unresolved_reasons
            ),
        ),
    )
