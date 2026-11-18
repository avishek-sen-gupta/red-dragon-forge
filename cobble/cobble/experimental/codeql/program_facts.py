"""The rows cobble derives for a node beyond its fields: the cells a data name denotes, the units a procedure name or a PERFORM reaches."""

from dataclasses import dataclass
from functools import singledispatchmethod

from cics.statements import CicsOperand, ExecCicsStatement, operand_reference
from cobble.dataflow.fields.condition_set import ConditionSet
from cobble.dataflow.fixpoint.fixpoint import with_condition_sets
from cobble.experimental.codeql.label import Label
from cobble.experimental.codeql.schema.ast_rows import Rows, Value
from cobble.experimental.codeql.scope import Scope
from cobble.experimental.codeql.trap_row import TrapRow
from cobol_asg.cobol_expression import (
    AddressOfNode,
    ExprNode,
    FieldRefNode,
    LengthOfNode,
    RefModNode,
)
from cobol_asg.cobol_statements import (
    CallUsingParam,
    ComputeTarget,
    PerformStatement,
    ProcedureRef,
    ReadStatement,
    ReleaseStatement,
    ReturnStatement,
    RewriteStatement,
    SetStatement,
    WriteStatement,
    XmlGenerateStatement,
)
from cobol_asg.operand_kind import OperandKind
from cobol_asg.ref_mod import RefModOperand, RefModReference
from cobol_asg.set_operand import SetOperand

RECEIVE_MAP = "RECEIVE MAP"
MAP_INPUT_SUFFIX = "I"

_NAMED_SET_OPERANDS = frozenset(
    {OperandKind.REF, OperandKind.ADDRESS_OF, OperandKind.LENGTH_OF}
)


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
        return self._named(label, value.name, value.qualifiers, value.subscripts)

    @rows.register
    def _(self, value: FieldRefNode | RefModNode | AddressOfNode, label: Label) -> Rows:
        return self._named(label, value.name, value.qualifiers, value.subscripts)

    @rows.register
    def _(self, value: LengthOfNode | RefModReference, label: Label) -> Rows:
        return self._named(label, value.name, value.qualifiers, ())

    @rows.register
    def _(self, value: ComputeTarget, label: Label) -> Rows:
        return self._named(label, value.name, value.qualifiers, value.subscripts)

    @rows.register
    def _(self, value: SetOperand, label: Label) -> Rows:
        if value.kind not in _NAMED_SET_OPERANDS:
            return ()
        return self._named(label, value.name, value.qualifiers, value.subscripts)

    @rows.register
    def _(
        self, value: WriteStatement | RewriteStatement | ReleaseStatement, label: Label
    ) -> Rows:
        return self._field_named(label, "record_name", value.record_name)

    @rows.register
    def _(self, value: XmlGenerateStatement, label: Label) -> Rows:
        return (
            *self._field_named(label, "xml_document", value.xml_document),
            *self._field_named(label, "from_record", value.from_record),
            *self._field_named(label, "count_in", value.count_in),
        )

    @rows.register
    def _(self, value: CallUsingParam, label: Label) -> Rows:
        if value.is_literal:
            return ()
        return self._named(label, value.name, value.qualifiers, value.subscripts)

    @rows.register
    def _(self, value: CicsOperand, label: Label) -> Rows:
        if value.is_literal:
            return ()
        reference = operand_reference(value)
        return self._named(label, reference.name, (), reference.subscripts)

    @rows.register
    def _(self, value: ExecCicsStatement, label: Label) -> Rows:
        """A RECEIVE MAP with no INTO fills the map's symbolic input record."""
        if value.verb.upper() != RECEIVE_MAP or "INTO" in value.options:
            return ()
        named = value.options.get("MAP") or value.options.get("MAPNAME")
        if not isinstance(named, CicsOperand):
            return ()
        return self._field_named(label, "map_input", named.text + MAP_INPUT_SUFFIX)

    @rows.register
    def _(self, value: ReadStatement | ReturnStatement, label: Label) -> Rows:
        """Every 01 record of the file read shares its record area."""
        return tuple(
            TrapRow("file_record_cell", (label, cell))
            for record, owner in self.scope.file_of_record.items()
            if owner == value.file_name.upper()
            for cell in self.scope.cells_named(record, (), ())
        )

    @rows.register
    def _(self, value: SetStatement, label: Label) -> Rows:
        """A SET ... TO TRUE whose condition names all resolve moves each one's first
        value into the field it tests, as cobble's fixpoint reads it."""
        rewritten = with_condition_sets({"": value}, self.scope.declared)[""]
        if not isinstance(rewritten, ConditionSet):
            return ()
        return tuple(
            TrapRow("condition_set_cell", (label, cell))
            for move in rewritten.moves
            for target in move.targets
            for cell in self.scope.cells_named(
                target.name, target.qualifiers, target.subscripts
            )
        )

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

    def _field_named(self, label: Label, field: str, name: str) -> Rows:
        """A name a statement holds as text rather than as an operand."""
        return tuple(
            TrapRow("field_names_cell", (label, field, cell))
            for cell in self.scope.cells_named(name, (), ())
        )

    def _named(
        self,
        label: Label,
        name: str,
        qualifiers: tuple[str, ...],
        subscripts: tuple[ExprNode, ...],
    ) -> Rows:
        return tuple(
            TrapRow("names_cell", (label, cell))
            for cell in self.scope.cells_named(name, qualifiers, subscripts)
        )
