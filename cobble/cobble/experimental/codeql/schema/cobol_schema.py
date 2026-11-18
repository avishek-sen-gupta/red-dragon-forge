"""The COBOL schema: the procedure division as the parser and its EXEC CICS and EXEC SQL dialects type it."""

import typing

import cobol_asg.cobol_statements as cobol_statements
from cics.statements import ExecCicsStatement
from cobble.experimental.codeql.schema.schema import Naming, Schema, schema_of
from cobol_asg.asg_types import CobolParagraph, CobolSection
from cobol_asg.cobol_expression import ExprNode
from cobol_asg.cobol_statements import (
    PerformSpec,
    RecordClause,
    SortCollation,
    SortSource,
)
from cobol_asg.condition import Condition
from cobol_asg.evaluate_selection import SelectionObject, SelectionSubject
from cobol_asg.ref_mod import RefModExpr
from cobol_asg.source_span import SourceSpan
from cobol_asg.write_advancing import WriteAdvancing
from squall.statements import ExecSqlStatement

STATEMENT = "Statement"

_STATEMENTS = typing.get_args(
    typing.get_type_hints(CobolParagraph, globalns=dict(vars(cobol_statements)))[
        "statements"
    ]
)[0]

_UNIONS = {
    frozenset(typing.get_args(_STATEMENTS)): STATEMENT,
    frozenset(typing.get_args(ExprNode)): "ExprNode",
    frozenset(typing.get_args(Condition)): "Condition",
    frozenset(typing.get_args(RefModExpr)): "RefModExpr",
    frozenset(typing.get_args(PerformSpec)): "PerformSpec",
    frozenset(typing.get_args(SelectionSubject)): "SelectionSubject",
    frozenset(typing.get_args(SelectionObject)): "SelectionObject",
    frozenset(typing.get_args(WriteAdvancing)): "WriteAdvancing",
    frozenset(typing.get_args(RecordClause)): "RecordClause",
    frozenset(typing.get_args(SortSource)): "SortSource",
    frozenset(typing.get_args(SortCollation)): "SortCollation",
}

COBOL_NAMING = Naming(
    location=SourceSpan,
    modules=(cobol_statements,),
    unions=_UNIONS,
    extended={STATEMENT: (ExecCicsStatement, ExecSqlStatement)},
)

COBOL_ROOTS: tuple[type, ...] = (CobolSection, CobolParagraph)


def cobol_schema() -> Schema:
    return schema_of(COBOL_ROOTS, COBOL_NAMING)
