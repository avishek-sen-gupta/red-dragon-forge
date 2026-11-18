"""The rows cobble derives for a node beyond its fields: the cells a data name denotes, the units a procedure name or a PERFORM reaches."""

from dataclasses import dataclass
from functools import singledispatchmethod

from cics.statements import CicsOperand, ExecCicsStatement, operand_reference
from cobble.dataflow.fields.condition_set import ConditionSet
from cobble.dataflow.fields.extent import denoted_cells, operand_extents
from cobble.dataflow.fields.initialized import initialized_extents
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
    InitializeStatement,
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
from cobol_memory.field_extent import Precision

RECEIVE_MAP = "RECEIVE MAP"
SEND_MAP = "SEND MAP"
MAP_INPUT_SUFFIX = "I"
MAP_OUTPUT_SUFFIX = "O"

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
        return (
            *self._named(label, value.name, value.qualifiers, value.subscripts),
            *self._exactness(label, value),
        )

    @rows.register
    def _(self, value: FieldRefNode | RefModNode | AddressOfNode, label: Label) -> Rows:
        reference = RefModOperand(
            name=value.name, qualifiers=value.qualifiers, subscripts=value.subscripts
        )
        return (
            *self._named(label, value.name, value.qualifiers, value.subscripts),
            *self._exactness(label, reference),
        )

    @rows.register
    def _(self, value: LengthOfNode | RefModReference, label: Label) -> Rows:
        return self._named(label, value.name, value.qualifiers, ())

    @rows.register
    def _(self, value: ComputeTarget | SetOperand, label: Label) -> Rows:
        if isinstance(value, SetOperand) and value.kind not in _NAMED_SET_OPERANDS:
            return ()
        reference = RefModOperand(
            name=value.name, qualifiers=value.qualifiers, subscripts=value.subscripts
        )
        return (
            *self._named(label, value.name, value.qualifiers, value.subscripts),
            *self._exactness(label, reference),
        )

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
        return (
            *self._named(label, reference.name, (), reference.subscripts),
            *self._exactness(label, reference),
        )

    @rows.register
    def _(self, value: ExecCicsStatement, label: Label) -> Rows:
        """A RECEIVE MAP with no INTO fills the map's symbolic input record, a SEND MAP
        with no FROM sends its output record."""
        named = value.options.get("MAP") or value.options.get("MAPNAME")
        if not isinstance(named, CicsOperand):
            return ()
        return self._map_record(label, value, named.text)

    def _map_record(
        self, label: Label, value: ExecCicsStatement, map_name: str
    ) -> Rows:
        verb = value.verb.upper()
        if verb == RECEIVE_MAP and "INTO" not in value.options:
            return self._field_named(label, "map_input", map_name + MAP_INPUT_SUFFIX)
        if verb == SEND_MAP and "FROM" not in value.options:
            return self._field_named(label, "map_output", map_name + MAP_OUTPUT_SUFFIX)
        return ()

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
    def _(self, value: InitializeStatement, label: Label) -> Rows:
        """INITIALIZE sets its operands' items but their FILLERs and the items under
        a REDEFINES below them, as cobble's ``initialized_extents`` runs give them."""
        index = self.scope.index
        return tuple(
            TrapRow("initialized_cell", (label, self.scope.cells[cell]))
            for operand in value.operands
            for extent in operand_extents(operand, index).extents
            for run in initialized_extents(operand, extent, index)
            for cell in dict.fromkeys(index.elementary_within(run))
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

    def _exactness(self, label: Label, reference: RefModOperand) -> Rows:
        """How exactly a name locates its bytes, as cobble's ``operand_extents``
        does: a computed subscript or bound is clamped, a constant slice exact."""
        index = self.scope.index
        extents = operand_extents(reference, index).extents
        if any(e.precision is Precision.CLAMPED for e in extents):
            return (TrapRow("names_clamped", (label,)),)
        return tuple(
            TrapRow(
                "names_slice",
                (label, self.scope.cells[cell], e.start - whole.start, e.length),
            )
            for e in extents
            for cell in denoted_cells(
                reference.name, reference.qualifiers, reference.subscripts, index
            )
            for whole in (index.extent_of(cell),)
            if whole.region is e.region
            and whole.start <= e.start
            and e.end <= whole.end
            and (e.start, e.length) != (whole.start, whole.length)
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
