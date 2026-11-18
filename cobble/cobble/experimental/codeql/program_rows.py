"""One program's rows: its file, its fields with their byte extents, its procedure division as the generated tables hold it, and the units it runs in order."""

from collections.abc import Mapping
from itertools import groupby

from cobble.dataflow.layout import Cell, program_records
from cobble.dataflow.srccfg.cfg import NO_SPAN, span_of
from cobble.dataflow.srccfg.paragraphs import ParagraphRef, paragraph_order
from cobble.experimental.codeql.label import Label
from cobble.experimental.codeql.program_facts import ProgramFacts
from cobble.experimental.codeql.schema.ast_rows import AstWriter, Rows, Value
from cobble.experimental.codeql.schema.cobol_schema import cobol_schema
from cobble.experimental.codeql.schema.schema import Schema, table_of
from cobble.experimental.codeql.scope import Ends, Scope
from cobble.experimental.codeql.trap_row import TrapRow, define
from cobol_asg.asg_types import CobolASG, CobolSection
from cobol_asg.pic_parser import parse_pic

FILE = Label("file")
PROGRAM = Label("program")


def program_rows(asg: CobolASG, source: str) -> Rows:
    cells = tuple(cell for record in program_records(asg) for cell in record.cells)
    schema = cobol_schema()
    units = tuple(zip(_unit_labels(asg, schema), paragraph_order(asg), strict=True))
    scope = Scope(FILE, source, _named(cells), _paragraphs(units), _sections(units))
    writer = AstWriter(schema, FILE, ProgramFacts(scope).rows)
    location, located = scope.location(PROGRAM, span_of(asg, source))
    return (
        define(FILE),
        TrapRow("files", (FILE, source)),
        define(PROGRAM),
        *located,
        TrapRow("programs", (PROGRAM, asg.program_id, location)),
        *(row for n, cell in enumerate(cells) for row in _field_rows(scope, n, cell)),
        *_contained(writer, "program_statements", "e", tuple(asg.statements)),
        *_contained(writer, "program_sections", "c", tuple(asg.sections)),
        *_contained(writer, "program_paragraphs", "d", tuple(asg.paragraphs)),
        *(
            TrapRow("units", (PROGRAM, n, label, unit.name, unit.section))
            for n, (label, unit) in enumerate(units)
        ),
    )


def _unit_labels(asg: CobolASG, schema: Schema) -> tuple[Label, ...]:
    """The node each unit of ``paragraph_order`` runs: the program for statements
    before any section or paragraph, a section for those at its head, else the
    paragraph."""
    within = next(
        i
        for i, f in enumerate(schema.node_of(CobolSection).fields)
        if f.name == "paragraphs"
    )
    return (
        *((PROGRAM,) if asg.statements else ()),
        *(
            label
            for i, section in enumerate(asg.sections)
            for label in (
                *((Label(f"c{i}"),) if section.statements else ()),
                *(Label(f"c{i}_{within}_{j}") for j in range(len(section.paragraphs))),
            )
        ),
        *(Label(f"d{k}") for k in range(len(asg.paragraphs))),
    )


def _contained(
    writer: AstWriter, table: str, prefix: str, parts: tuple[Value, ...]
) -> Rows:
    return tuple(
        row
        for n, part in enumerate(parts)
        for label in (Label(f"{prefix}{n}"),)
        for row in (
            *writer.rows(part, _table(part), label),
            TrapRow(table, (PROGRAM, n, label)),
        )
    )


def _table(part: Value) -> str:
    """A statement's table is named by its union; the walker finds its type."""
    return table_of(type(part).__name__)


def _field_rows(scope: Scope, n: int, cell: Cell) -> Rows:
    label = Label(f"f{n}")
    location, located = scope.location(label, NO_SPAN)
    row = TrapRow(
        "fields",
        (label, PROGRAM, cell.name, cell.record, cell.start, cell.length, location),
    )
    numeric = (TrapRow("numeric_fields", (label,)),) if _numeric(cell) else ()
    return (define(label), *located, row, *numeric)


def _numeric(cell: Cell) -> bool:
    return bool(cell.pic) and parse_pic(cell.pic, cell.usage).is_numeric


def _named(
    cells: tuple[Cell, ...],
) -> Mapping[str, tuple[tuple[Label, frozenset[str]], ...]]:
    labelled = sorted(
        (
            (cell.name.upper(), Label(f"f{n}"), cell.path)
            for n, cell in enumerate(cells)
        ),
        key=lambda one: one[0],
    )
    return {
        name: tuple(
            (label, frozenset(p.upper() for p in path)) for _, label, path in group
        )
        for name, group in groupby(labelled, key=lambda one: one[0])
    }


Unit = tuple[Label, ParagraphRef]


def _paragraphs(units: tuple[Unit, ...]) -> Mapping[str, Label]:
    """The first unit of each name: a duplicate name is renamed in
    ``paragraph_order`` and never shadows it."""
    return {unit.name.upper(): label for label, unit in reversed(units)}


def _sections(units: tuple[Unit, ...]) -> Mapping[str, Ends]:
    return {
        section: _ends(tuple(label for label, _ in group))
        for section, group in groupby(units, key=lambda one: one[1].section.upper())
    }


def _ends(labels: tuple[Label, ...]) -> Ends:
    return labels[0], labels[-1]
