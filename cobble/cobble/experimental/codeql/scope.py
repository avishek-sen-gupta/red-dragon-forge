"""One program's names, resolved to the labels of its fields and paragraphs."""

from collections.abc import Mapping
from dataclasses import dataclass

from cobble.dataflow.srccfg.cfg import SourceSpan
from cobble.experimental.codeql.label import Label
from cobble.experimental.codeql.trap_row import TrapRow, define
from cobol_asg.ref_mod import OperandKind, RefModOperand

Ends = tuple[Label, Label]


@dataclass(frozen=True)
class Scope:
    """``fields`` maps a name to each field so named and the names qualifying it;
    ``sections`` maps a section to its first and last paragraph. A procedure name
    is a paragraph if one is so named, else a section."""

    file: Label
    source: str
    fields: Mapping[str, tuple[tuple[Label, frozenset[str]], ...]]
    paragraphs: Mapping[str, Label]
    sections: Mapping[str, Ends]

    def fields_of(self, operand: RefModOperand) -> tuple[Label, ...]:
        if operand.kind is not OperandKind.REF:
            return ()
        qualifiers = frozenset(q.upper() for q in operand.qualifiers)
        return tuple(
            label
            for label, path in self.fields.get(operand.name.upper(), ())
            if qualifiers <= path
        )

    def procedure(self, name: str, section: str) -> tuple[Ends, ...]:
        key = (name or section).upper()
        if name and key in self.paragraphs:
            return ((self.paragraphs[key], self.paragraphs[key]),)
        return self._section(key)

    def _section(self, key: str) -> tuple[Ends, ...]:
        return (self.sections[key],) if key in self.sections else ()

    def location(
        self, owner: Label, span: SourceSpan
    ) -> tuple[Label, tuple[TrapRow, ...]]:
        label = Label(f"l{owner.name}")
        row = TrapRow(
            "locations_default",
            (
                label,
                self.file,
                span.line_start,
                span.col_start,
                span.line_end,
                span.col_end,
            ),
        )
        return label, (define(label), row)
