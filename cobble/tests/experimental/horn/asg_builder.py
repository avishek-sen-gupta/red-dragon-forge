"""Synthetic one-program ASGs for the Horn tests, built from statement dictionaries."""

import json
from collections.abc import Callable, Iterator, Mapping, Sequence

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.srccfg.cfg import NodeKind
from cobble.experimental.horn.program import Program, program_of
from cobol_asg.asg_types import CobolASG

Statement = Mapping[str, object]


def clock() -> Callable[[], float]:
    ticks: Iterator[float] = iter(float(n) for n in range(100000))
    return lambda: next(ticks)


def asg(
    paragraphs: Sequence[tuple[str, Sequence[Statement]]],
    data: Sequence[Statement],
) -> CobolASG:
    body = {
        "program_id": "PROGA",
        "data_fields": list(data),
        "paragraphs": [
            {"name": name, "statements": list(statements)}
            for name, statements in paragraphs
        ],
    }
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict(json.loads(json.dumps(body)))


def program(
    paragraphs: Sequence[tuple[str, Sequence[Statement]]],
    data: Sequence[Statement] = (),
) -> Program:
    return program_of(asg(paragraphs, data or FIELDS))


def x(name: str, pic: str = "X") -> Statement:
    return {"name": name, "level": 1, "pic": pic}


def move(value: str, target: str) -> Statement:
    return {"type": "MOVE", "operands": [{"name": value}, {"name": target}]}


def move_literal(value: str, target: str) -> Statement:
    return {
        "type": "MOVE",
        "operands": [{"kind": "lit", "name": value}, {"name": target}],
    }


def if_(
    left: str | Mapping[str, object],
    right: str,
    then: Sequence[Statement],
    otherwise: Sequence[Statement] = (),
) -> Statement:
    return {
        "type": "IF",
        "condition": {
            "not": False,
            "relation": {
                "left": (
                    {"kind": "ref", "name": left} if isinstance(left, str) else left
                ),
                "op": "==",
                "right": {"kind": "lit", "value": right},
            },
        },
        "children": list(then),
        "else_children": list(otherwise),
    }


def perform(target: str) -> Statement:
    return {"type": "PERFORM", "operands": [target]}


def first_byte(name: str) -> Mapping[str, object]:
    return {
        "kind": "ref",
        "name": name,
        "ref_mod_start": {"kind": "lit", "value": "1"},
        "ref_mod_length": {"kind": "lit", "value": "1"},
    }


def goto(target: str) -> Statement:
    return {"type": "GOTO", "form": "simple", "target": {"paragraph": target}}


def writer(program: Program, field: str) -> str:
    return next(node.id for node in program.cfg.nodes if field in node.writes)


def branch_on(program: Program, left: str, right: str) -> str:
    return next(
        node.id
        for node in program.cfg.nodes
        if node.kind is NodeKind.TEST
        and (node.atom.left, node.atom.right) == (left, right)
    )


def branch_in(program: Program, paragraph: str, left: str, right: str) -> str:
    return next(
        node.id
        for node in program.cfg.nodes
        if node.kind is NodeKind.TEST
        and node.paragraph == paragraph
        and (node.atom.left, node.atom.right) == (left, right)
    )


STOP: Statement = {"type": "STOP_RUN"}
X_OUT = move("'x'", "X-OUT")
FIELDS = (x("F"), x("G"), x("X-OUT"))
