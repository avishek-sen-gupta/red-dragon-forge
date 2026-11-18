"""One program's rows: its file, its fields with their byte extents, its paragraphs in order and their statements."""

from collections.abc import Mapping
from itertools import groupby

from cobble.dataflow.layout import Cell, program_records
from cobble.dataflow.srccfg.cfg import NO_SPAN, span_of
from cobble.dataflow.srccfg.paragraphs import ParagraphRef, paragraph_order
from cobble.experimental.codeql.label import Label
from cobble.experimental.codeql.schema.ast_rows import AstWriter, Value
from cobble.experimental.codeql.schema.cobol_schema import cobol_schema
from cobble.experimental.codeql.schema.schema import table_of
from cobble.experimental.codeql.scope import Ends, Scope
from cobble.experimental.codeql.slot import Slot
from cobble.experimental.codeql.statement_rows import Rows, body_rows
from cobble.experimental.codeql.trap_row import TrapRow, define
from cobol_asg.asg_types import CobolASG
from cobol_asg.pic_parser import parse_pic

FILE = Label("file")
PROGRAM = Label("program")


def program_rows(asg: CobolASG, source: str) -> Rows:
    cells = tuple(cell for record in program_records(asg) for cell in record.cells)
    order = paragraph_order(asg)
    scope = Scope(FILE, source, _named(cells), _paragraphs(order), _sections(order))
    location, located = scope.location(PROGRAM, span_of(asg, source))
    return (
        define(FILE),
        TrapRow("files", (FILE, source)),
        define(PROGRAM),
        *located,
        TrapRow("programs", (PROGRAM, asg.program_id, location)),
        *(row for n, cell in enumerate(cells) for row in _field_rows(scope, n, cell)),
        *(row for n, p in enumerate(order) for row in _paragraph_rows(scope, n, p)),
        *_procedure_rows(asg),
    )


def _procedure_rows(asg: CobolASG) -> Rows:
    """The procedure division in the generated tables: sections, then the
    paragraphs outside any section."""
    writer = AstWriter(cobol_schema(), FILE)
    return (
        *_contained(writer, "program_sections", "c", tuple(asg.sections)),
        *_contained(writer, "program_paragraphs", "d", tuple(asg.paragraphs)),
    )


def _contained(
    writer: AstWriter, table: str, prefix: str, parts: tuple[Value, ...]
) -> Rows:
    return tuple(
        row
        for n, part in enumerate(parts)
        for label in (Label(f"{prefix}{n}"),)
        for row in (
            *writer.rows(part, table_of(type(part).__name__), label),
            TrapRow(table, (PROGRAM, n, label)),
        )
    )


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


def _paragraph_rows(scope: Scope, n: int, paragraph: ParagraphRef) -> Rows:
    label = Label(f"p{n}")
    location, located = scope.location(label, paragraph.span)
    row = TrapRow(
        "paragraphs",
        (label, PROGRAM, paragraph.name, paragraph.section, n, location),
    )
    body = body_rows(scope, paragraph.statements, label, Slot.BODY, str(n))
    return (define(label), *located, row, *body)


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


def _paragraphs(order: tuple[ParagraphRef, ...]) -> Mapping[str, Label]:
    return {
        p.name.upper(): Label(f"p{n}") for n, p in reversed(tuple(enumerate(order)))
    }


def _sections(order: tuple[ParagraphRef, ...]) -> Mapping[str, Ends]:
    return {
        section: _ends(tuple(n for n, _ in group))
        for section, group in groupby(
            enumerate(order), key=lambda one: one[1].section.upper()
        )
    }


def _ends(numbers: tuple[int, ...]) -> Ends:
    return Label(f"p{numbers[0]}"), Label(f"p{numbers[-1]}")
