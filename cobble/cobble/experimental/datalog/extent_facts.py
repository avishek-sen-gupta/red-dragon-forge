"""Every declared field's extents and declared cells as facts."""

from pathlib import Path

from cobble.dataflow.fields.extent_line import ExtentLine
from cobble.dataflow.fields.extent_text import byte_range
from cobble.experimental.datalog.column import number, symbol
from cobble.experimental.datalog.facts import Facts, Row
from cobble.experimental.datalog.relation import Relation
from cobble.experimental.datalog.run_files import lines

FIELD_EXTENT = Relation(
    "field_extent",
    (
        symbol("fid"),
        symbol("p"),
        symbol("name"),
        symbol("region"),
        number("s"),
        number("e"),
    ),
)
FIELD_DECL = Relation(
    "field_decl",
    (
        symbol("fid"),
        symbol("p"),
        symbol("name"),
        symbol("record"),
        symbol("path"),
        number("level"),
        symbol("pic"),
        symbol("usage"),
        number("occurs"),
        symbol("origin"),
    ),
)
FIELD_VALUE = Relation("field_value", (symbol("fid"), symbol("v")))
FIELD_REDEFINES = Relation("field_redefines", (symbol("fid"), symbol("target")))


def _extents(line: ExtentLine) -> tuple[Row, ...]:
    return tuple(
        (line.id, line.program, found.name, found.region, found.start, found.end)
        for text in line.extents
        for found in (byte_range(text, line.program),)
        if found.known
    )


def _decls(line: ExtentLine) -> tuple[Row, ...]:
    return tuple(
        (
            line.id,
            line.program,
            name,
            record,
            ".".join(path),
            level,
            pic,
            usage,
            occurs,
            origin,
        )
        for name, record, path, level, pic, usage, occurs, origin in zip(
            line.names,
            line.records,
            line.paths,
            line.levels,
            line.pics,
            line.usages,
            line.occurs,
            line.origins,
            strict=True,
        )
    )


def _named(fid: str, texts: tuple[str, ...]) -> tuple[Row, ...]:
    return tuple((fid, text) for text in texts if text)


def extent_facts(run: Path) -> tuple[Facts, ...]:
    found = tuple(
        ExtentLine.model_validate_json(line) for line in lines(run / "extents.jsonl")
    )
    return (
        Facts(FIELD_EXTENT, tuple(row for line in found for row in _extents(line))),
        Facts(FIELD_DECL, tuple(row for line in found for row in _decls(line))),
        Facts(
            FIELD_VALUE,
            tuple(row for line in found for row in _named(line.id, line.values)),
        ),
        Facts(
            FIELD_REDEFINES,
            tuple(row for line in found for row in _named(line.id, line.redefines)),
        ),
    )
