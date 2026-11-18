"""The rows for one statement and the statements nested in it: kind, place, reads, writes and jump targets."""

from collections.abc import Mapping
from functools import singledispatch

from cobble.dataflow.srccfg.cfg import span_of
from cobble.experimental.codeql.label import Label
from cobble.experimental.codeql.scope import Scope
from cobble.experimental.codeql.slot import Slot
from cobble.experimental.codeql.stmt_kind import StmtKind
from cobble.experimental.codeql.trap_row import TrapRow, define
from cobol_asg.cobol_statements import (
    AcceptStatement,
    AlteredGoto,
    CobolStatementType,
    ComputedGoto,
    DisplayStatement,
    GobackStatement,
    GotoStatement,
    IfStatement,
    MoveStatement,
    PerformStatement,
    ProcedureRef,
    SimpleGoto,
    StopRunStatement,
)
from cobol_asg.ref_mod import RefModOperand

Rows = tuple[TrapRow, ...]

_KINDS: Mapping[type, StmtKind] = {
    MoveStatement: StmtKind.MOVE,
    AcceptStatement: StmtKind.ACCEPT,
    DisplayStatement: StmtKind.DISPLAY,
    GotoStatement: StmtKind.GOTO,
    IfStatement: StmtKind.IF,
    StopRunStatement: StmtKind.STOP_RUN,
    GobackStatement: StmtKind.GOBACK,
}


def body_rows(
    scope: Scope,
    statements: tuple[CobolStatementType, ...],
    parent: Label,
    slot: Slot,
    path: str,
) -> Rows:
    return tuple(
        row
        for index, statement in enumerate(statements)
        for row in statement_rows(
            scope, statement, parent, slot, index, f"{path}_{slot}_{index}"
        )
    )


def statement_rows(
    scope: Scope,
    statement: CobolStatementType,
    parent: Label,
    slot: Slot,
    index: int,
    path: str,
) -> Rows:
    label = Label(f"s{path}")
    location, located = scope.location(label, span_of(statement, scope.source))
    row = TrapRow("stmts", (label, _kind(statement), parent, slot, index, location))
    return (define(label), *located, row, *_facts(statement, scope, label, path))


@singledispatch
def _kind(statement: CobolStatementType) -> StmtKind:
    return _KINDS.get(type(statement), StmtKind.OTHER)


@_kind.register
def _(statement: PerformStatement) -> StmtKind:
    return StmtKind.INLINE_PERFORM if statement.children else StmtKind.PERFORM


@singledispatch
def _facts(
    statement: CobolStatementType, scope: Scope, label: Label, path: str
) -> Rows:
    return ()


@_facts.register
def _(statement: MoveStatement, scope: Scope, label: Label, path: str) -> Rows:
    sources = (statement.source,) if isinstance(statement.source, RefModOperand) else ()
    return (
        *(row for s in sources for row in _access(scope, "stmt_reads", label, s)),
        *(
            row
            for t in statement.targets
            for row in _access(scope, "stmt_writes", label, t)
        ),
    )


@_facts.register
def _(statement: AcceptStatement, scope: Scope, label: Label, path: str) -> Rows:
    return _access(scope, "stmt_writes", label, statement.target)


@_facts.register
def _(statement: DisplayStatement, scope: Scope, label: Label, path: str) -> Rows:
    return tuple(
        row
        for o in statement.operands
        for row in _access(scope, "stmt_reads", label, o)
    )


@_facts.register
def _(statement: PerformStatement, scope: Scope, label: Label, path: str) -> Rows:
    if statement.children:
        return body_rows(scope, tuple(statement.children), label, Slot.THEN, path)
    repeats = (TrapRow("perform_repeats", (label,)),) if statement.spec else ()
    return (*_perform_range(scope, statement, label), *repeats)


@_facts.register
def _(statement: GotoStatement, scope: Scope, label: Label, path: str) -> Rows:
    return tuple(
        TrapRow("goto_targets", (label, first))
        for ref in _goto_refs(statement.form)
        for first, _ in scope.procedure(ref.paragraph, ref.section)
    )


@_facts.register
def _(statement: IfStatement, scope: Scope, label: Label, path: str) -> Rows:
    return (
        *body_rows(scope, tuple(statement.children), label, Slot.THEN, path),
        *body_rows(scope, tuple(statement.else_children), label, Slot.ELSE, path),
    )


def _perform_range(scope: Scope, statement: PerformStatement, label: Label) -> Rows:
    thru = statement.thru or statement.thru_section
    end = (
        (statement.thru, statement.thru_section)
        if thru
        else (statement.target, statement.target_section)
    )
    return tuple(
        TrapRow("perform_ranges", (label, first, last))
        for first, _end in scope.procedure(statement.target, statement.target_section)
        for _start, last in scope.procedure(*end)
    )


@singledispatch
def _goto_refs(
    form: SimpleGoto | ComputedGoto | AlteredGoto,
) -> tuple[ProcedureRef, ...]:
    return ()


@_goto_refs.register
def _(form: SimpleGoto) -> tuple[ProcedureRef, ...]:
    return (form.target,)


@_goto_refs.register
def _(form: ComputedGoto) -> tuple[ProcedureRef, ...]:
    return form.targets


def _access(scope: Scope, table: str, label: Label, operand: RefModOperand) -> Rows:
    partial = operand.is_reference_modified or bool(operand.subscripts)
    return tuple(
        row
        for field in scope.fields_of(operand)
        for row in (
            TrapRow(table, (label, field)),
            *((TrapRow("partial_accesses", (label, field)),) if partial else ()),
        )
    )
