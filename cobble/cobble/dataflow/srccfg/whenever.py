"""The WHENEVER GO TO targets governing each EXEC SQL statement, by CFG node id.

A WHENEVER is a precompiler directive, not an executable statement. Db2 applies
it to "all subsequent SOURCE SQL statements until another WHENEVER is
encountered", regardless of program execution flow, so the governing set is a
source-order scan and not a reaching-definitions query over the CFG: a directive
that a branch jumps past still governs every statement textually after it.

    MAIN.  IF X GO TO SKIP.
           EXEC SQL WHENEVER NOT FOUND GO TO H END-EXEC.
    SKIP.  EXEC SQL SELECT ... END-EXEC.     <- governed, on both paths

That is the one way this differs from the CICS handler model next door, where
HANDLE CONDITION arms at run time and reaching definitions is the correct query.
"""

from __future__ import annotations

from collections.abc import Mapping
from itertools import accumulate

from cobble.dataflow.srccfg.conditions import ConditionData
from cobble.dataflow.srccfg.statements import Entry, statement_entries
from cobol_asg.asg_types import CobolASG
from cobol_asg.cobol_statements import CobolStatementType
from squall.statements import (
    ExecSqlStatement,
    GoTo,
    Kind,
    WheneverAction,
    WheneverCondition,
)

Governing = tuple[tuple[WheneverCondition, str], ...]

Active = Mapping[WheneverCondition, WheneverAction]


def governing_directives(asg: CobolASG) -> Mapping[str, Governing]:
    """Each executable EXEC SQL node id, mapped to the GO TO targets active there.

    accumulate's ``initial`` makes the state stream one longer than the entries,
    so zipping them pairs each statement with the state BEFORE it -- which is
    what "must textually precede the first statement it affects" means. The
    length difference is that mechanism, so the zip is deliberately not strict.
    """
    entries = statement_entries(asg)
    states = accumulate(entries, _advance, initial={})
    return {
        node_id: _active_gotos(active)
        for (node_id, statement), active in zip(entries, states, strict=False)
        if _is_executable_sql(statement)
    }


def _is_executable_sql(statement: CobolStatementType) -> bool:
    """A directive is recognised by its KIND, not by whether its condition parsed.
    The grammar admits conditions Db2 does not define, and those come back NONE --
    keying on the condition would lower such a directive as an executable
    statement and give it a node."""
    return (
        isinstance(statement, ExecSqlStatement) and statement.kind is not Kind.WHENEVER
    )


def _advance(active: Active, entry: Entry) -> Active:
    _, statement = entry
    if not isinstance(statement, ExecSqlStatement):
        return active
    if statement.kind is not Kind.WHENEVER:
        return active
    return {**active, statement.whenever_condition: statement.whenever_action}


def _active_gotos(active: Active) -> Governing:
    """Only conditions whose action is a GO TO and whose SQLCA test is known.
    CONTINUE overrides an earlier GO TO by replacing it with an action that names
    no label, and a condition Db2 does not define has no predicate to guard on."""
    return tuple(
        (condition, action.target)
        for condition, action in active.items()
        if isinstance(action, GoTo) and condition in SQLCA_CONDITIONS
    )


def _ref(name: str) -> Mapping[str, str]:
    return {"kind": "ref", "name": name}


def _lit(value: str) -> Mapping[str, str]:
    return {"kind": "lit", "value": value}


def _relation(left: str, op: str, right: str) -> Mapping[str, ConditionData]:
    return {"relation": {"left": _ref(left), "op": op, "right": _lit(right)}}


def _both(op: str, left: ConditionData, right: ConditionData) -> ConditionData:
    return {"op": op, "left": left, "right": right}


# What each condition tests, as the raw shape conditions.read_condition already
# reads, so the guard lowers through cobble's own AND/OR handling rather than a
# second condition lowering of its own. Values per IBM's WHENEVER reference; the
# SQLSTATE arms are omitted because squall populates only SQLCODE.
SQLCA_CONDITIONS: Mapping[WheneverCondition, ConditionData] = {
    WheneverCondition.NOT_FOUND: _relation("SQLCODE", "=", "100"),
    WheneverCondition.SQLERROR: _relation("SQLCODE", "<", "0"),
    WheneverCondition.SQLWARNING: _both(
        "OR",
        _relation("SQLWARN0", "=", "'W'"),
        _both(
            "AND",
            _relation("SQLCODE", ">", "0"),
            _relation("SQLCODE", "<>", "100"),
        ),
    ),
}
