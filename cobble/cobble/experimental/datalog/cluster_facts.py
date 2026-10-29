"""The aggregate classes -- graph fields holding one datum -- as facts, numbered in file order."""

from pathlib import Path

from cobble.experimental.aggregates.unified_line import UnifiedLine
from cobble.experimental.datalog.column import symbol
from cobble.experimental.datalog.facts import Facts
from cobble.experimental.datalog.relation import Relation
from cobble.experimental.datalog.run_files import lines

CLUSTER = Relation("cluster", (symbol("c"), symbol("member")))


def cluster_facts(run: Path) -> tuple[Facts, ...]:
    classes = tuple(
        UnifiedLine.model_validate_json(line)
        for line in lines(run / "aggregates" / "unified.jsonl")
    )
    return (
        Facts(
            CLUSTER,
            tuple(
                (f"c{at}", member)
                for at, one in enumerate(classes)
                for member in one.members
            ),
        ),
    )
