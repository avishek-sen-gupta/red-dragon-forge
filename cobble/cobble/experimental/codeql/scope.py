"""One program's names, resolved to the labels of its cells and units."""

from collections.abc import Mapping
from dataclasses import dataclass

from cobble.dataflow.fields.extent import CellIndex, denoted_cells
from cobble.dataflow.layout import Cell
from cobble.dataflow.srccfg.cfg import SourceSpan
from cobble.experimental.codeql.label import Label
from cobble.experimental.codeql.trap_row import TrapRow, define
from cobol_asg.cobol_expression import ExprNode

Ends = tuple[Label, Label]


@dataclass(frozen=True)
class Scope:
    """``cells`` labels each cell ``index`` holds; ``sections`` maps a section to
    its first and last unit. A procedure name is a paragraph if one is so named,
    else a section."""

    file: Label
    source: str
    index: CellIndex
    cells: Mapping[Cell, Label]
    paragraphs: Mapping[str, Label]
    sections: Mapping[str, Ends]

    def cells_named(
        self, name: str, qualifiers: tuple[str, ...], subscripts: tuple[ExprNode, ...]
    ) -> tuple[Label, ...]:
        """The cells a data reference can denote, as cobble's dataflow resolves it."""
        return tuple(
            self.cells[cell]
            for cell in denoted_cells(name, qualifiers, subscripts, self.index)
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
