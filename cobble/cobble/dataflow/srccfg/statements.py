"""CFG node id to the ASG statement it lowered.

desugar.node_id is f"{paragraph}/{path}{suffix}", where path is the dotted
nesting address lower_statements builds. An id with no '#' addresses exactly one
statement; the '#'-suffixed ones (#test, #loop, #raise, #dispatch, #search,
#empty) are synthetic control nodes with no statement behind them.

Inverting the convention here rather than carrying the statement on Node: Node
is frozen and used in sets, and MoveStatement.targets is a list, so a statement
field would make it unhashable. test_statements.py holds the two conventions
together.

The paragraph names come from build.paragraph_order rather than from asg
directly, because a paragraph's CFG name is not always its ASG name: statements
belonging to no paragraph get a synthetic one, and a duplicate name -- legal
across sections -- is renamed on later occurrences. Re-deriving that would put
this index one refactor away from keys the CFG never uses.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from itertools import chain

from cobble.dataflow.srccfg.arm_clauses import ARM_CLAUSES
from cobble.dataflow.srccfg.paragraphs import paragraph_order
from cobble.dataflow.srccfg.varying import spec_operand, spec_text
from cobol_asg.asg_types import CobolASG
from cobol_asg.cobol_statements import (
    ArithmeticStatement,
    CobolStatementType,
    MoveStatement,
    PerformVaryingSpec,
)
from cobol_asg.ref_mod import RefModOperand

Arm = tuple[str, Sequence[CobolStatementType]]
Entry = tuple[str, CobolStatementType]

_PLAIN_ARMS = tuple(
    attribute for clause in ARM_CLAUSES for attribute in (clause[0], clause[1])
)


def _body(
    statement: CobolStatementType, attribute: str
) -> Sequence[CobolStatementType]:
    return tuple(getattr(statement, attribute, ()) or ())


def _plain_arms(statement: CobolStatementType) -> Iterator[Arm]:
    """desugar._plain lowers each ARM_CLAUSES attribute under its own name."""
    return ((attribute, _body(statement, attribute)) for attribute in _PLAIN_ARMS)


def _if_arms(statement: CobolStatementType) -> Iterator[Arm]:
    return iter(
        (
            ("then", _body(statement, "children")),
            ("else", _body(statement, "else_children")),
        )
    )


def _when_arms(whens: Sequence[CobolStatementType]) -> Iterator[Arm]:
    """A WHEN's body lowers at its branch path, with no segment of its own."""
    return (
        (f"when.{position}", _body(when, "children"))
        for position, when in enumerate(whens)
    )


def _evaluate_arms(statement: CobolStatementType) -> Iterator[Arm]:
    """EVALUATE keeps its WHENs in ``children``, not in ``whens``."""
    return _when_arms(_body(statement, "children"))


def _search_arms(statement: CobolStatementType) -> Iterator[Arm]:
    return chain(
        (("at_end", _body(statement, "at_end")),),
        _when_arms(_body(statement, "whens")),
    )


def _perform_arms(statement: CobolStatementType) -> Iterator[Arm]:
    """Only an inline PERFORM has a body; one with a target is a call."""
    target = str(getattr(statement, "target", "") or "")
    inline = (("body", _body(statement, "children")),)
    return iter(() if target else inline)


_ARMS_BY_KIND = {
    "IfStatement": _if_arms,
    "EvaluateStatement": _evaluate_arms,
    "SearchStatement": _search_arms,
    "PerformStatement": _perform_arms,
}


def _arms(statement: CobolStatementType) -> Iterator[Arm]:
    arms = _ARMS_BY_KIND.get(type(statement).__name__, _plain_arms)
    return ((segment, body) for segment, body in arms(statement) if body)


def _loop_assignments(statement: CobolStatementType, node: str) -> tuple[Entry, ...]:
    """A PERFORM VARYING's synthetic nodes, as the statements they execute: each
    loop's #init is MOVE FROM TO counter, its #step ADD BY TO counter. One level of
    AFTER specs, addressed as lowering addresses them."""
    spec = getattr(statement, "spec", "")
    if not isinstance(spec, PerformVaryingSpec):
        return ()
    return (
        *_assignments(spec, node),
        *(
            entry
            for position, after in enumerate(spec.after_specs)
            for entry in _assignments(after, f"{node}.after.{position}")
        ),
    )


def _assignments(spec: PerformVaryingSpec, node: str) -> tuple[Entry, ...]:
    counter = RefModOperand(name=spec_text(spec.varying_var))
    return (
        (
            f"{node}#init",
            MoveStatement(
                source=spec_operand(spec.varying_from),
                targets=[counter],
            ),
        ),
        (
            f"{node}#step",
            ArithmeticStatement(
                op="ADD",
                operands=[spec_operand(spec.varying_by)],
                targets=[counter],
            ),
        ),
    )


def _at(statement: CobolStatementType, paragraph: str, path: str) -> Iterator[Entry]:
    return chain(
        ((f"{paragraph}/{path}", statement),),
        _loop_assignments(statement, f"{paragraph}/{path}"),
        chain.from_iterable(
            _walk(body, paragraph, f"{path}.{segment}")
            for segment, body in _arms(statement)
        ),
    )


def _walk(
    statements: Sequence[CobolStatementType], paragraph: str, path: str
) -> Iterator[Entry]:
    prefix = f"{path}." if path else ""
    return chain.from_iterable(
        _at(statement, paragraph, f"{prefix}{position}")
        for position, statement in enumerate(statements)
    )


def statement_entries(asg: CobolASG) -> tuple[Entry, ...]:
    """Every statement-bearing CFG node id with its statement, in SOURCE order.

    Ordered rather than mapped because a precompiler directive governs what
    follows it textually, which a mapping cannot express (see srccfg/whenever.py).
    """
    return tuple(
        entry
        for ref in paragraph_order(asg)
        for entry in _walk(ref.statements, ref.name, "")
    )


def statement_index(asg: CobolASG) -> Mapping[str, CobolStatementType]:
    """Every statement-bearing CFG node id, mapped to its statement."""
    return dict(statement_entries(asg))
