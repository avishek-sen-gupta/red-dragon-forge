"""The rows cobble derives for a node beyond its fields: the cells a data name denotes, the units a procedure name or a PERFORM reaches."""

from dataclasses import dataclass
from functools import singledispatchmethod

from cobble.experimental.codeql.label import Label
from cobble.experimental.codeql.schema.ast_rows import Rows, Value
from cobble.experimental.codeql.scope import Scope
from cobble.experimental.codeql.trap_row import TrapRow
from cobol_asg.cobol_expression import (
    AddressOfNode,
    FieldRefNode,
    LengthOfNode,
    RefModNode,
)
from cobol_asg.cobol_statements import PerformStatement, ProcedureRef
from cobol_asg.operand_kind import OperandKind
from cobol_asg.ref_mod import RefModOperand, RefModReference


@dataclass(frozen=True)
class ProgramFacts:
    scope: Scope

    @singledispatchmethod
    def rows(self, value: Value, label: Label) -> Rows:
        return ()

    @rows.register
    def _(self, value: RefModOperand, label: Label) -> Rows:
        if value.kind is not OperandKind.REF:
            return ()
        return self._named(label, value.name, value.qualifiers)

    @rows.register
    def _(
        self,
        value: (
            FieldRefNode | RefModNode | AddressOfNode | LengthOfNode | RefModReference
        ),
        label: Label,
    ) -> Rows:
        return self._named(label, value.name, value.qualifiers)

    @rows.register
    def _(self, value: PerformStatement, label: Label) -> Rows:
        """An inline PERFORM reaches no range."""
        if value.children:
            return ()
        end = (
            (value.thru, value.thru_section)
            if value.thru or value.thru_section
            else (value.target, value.target_section)
        )
        return tuple(
            TrapRow("perform_range", (label, first, last))
            for first, _end in self.scope.procedure(value.target, value.target_section)
            for _start, last in self.scope.procedure(*end)
        )

    @rows.register
    def _(self, value: ProcedureRef, label: Label) -> Rows:
        return tuple(
            TrapRow("procedure_unit", (label, first))
            for first, _end in self.scope.procedure(value.paragraph, value.section)
        )

    def _named(self, label: Label, name: str, qualifiers: tuple[str, ...]) -> Rows:
        return tuple(
            TrapRow("names_cell", (label, cell))
            for cell in self.scope.cells_named(name, qualifiers)
        )
