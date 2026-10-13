"""
squall.dclgen
~~~~~~~~~~~~~
A squall-side DCLGEN: read a database table's schema and generate the COBOL
host-variable record (the copybook an ``EXEC SQL INCLUDE`` pulls in).

The copybook is consumed by ProLeap (after ``INCLUDE → COPY``) and alone carries
each host variable's type: binding reads it from the data layout ProLeap builds,
and a VARCHAR column renders as the DCLGEN 49-level LEN/TEXT group the lowering
recognises. This is the forward mapping — DB type → COBOL PIC.

Design
------
* Pure functions for the mapping/render; the only effect is reading the schema
  (``generate``) and writing files (``write``).
* v1 supports exactly the categories the binding codec can bind today:
  INTEGER/SMALLINT/BIGINT (binary COMP), DECIMAL/NUMERIC (COMP-3), CHAR (PIC X),
  and VARCHAR as a 49-level LEN/TEXT group. Floating point / lengthless TEXT /
  BLOB raise ``NotImplementedError`` rather than silently degrade.
* No regex: the declared-type string is split on fixed punctuation, not parsed
  with a pattern.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from squall.dclgen_field import DclgenField

# ── Name mapping ──────────────────────────────────────────────────────────────


def _cobolify(name: str) -> str:
    """Map a SQL identifier to a COBOL one: underscores → hyphens, uppercased."""
    return name.replace("_", "-").upper()


# ── Declared-type → COBOL mapping (the forward DCLGEN table) ───────────────────


def _split_decl(decl: str) -> tuple[str, list[int]]:
    """Split a declared type like ``DECIMAL(7,2)`` into (``DECIMAL``, [7, 2]).

    Fixed-punctuation split — not a regex over a sublanguage.
    """
    raw_base, _, rest = decl.strip().partition("(")
    base = raw_base.strip().upper()
    args = [int(p.strip()) for p in rest.rstrip(")").split(",") if p.strip()]
    return base, args


def _parse_sql_type(decl: str) -> dict:
    """Map a SQLite declared type to its COBOL field attributes.

    Returns a dict: ``{sql_type, category, total_digits, decimal_digits, length, pic}``.
    Raises ``NotImplementedError`` for types v1 does not support.
    """
    base, args = _split_decl(decl)
    match _TYPES.get(base):
        case None:
            raise NotImplementedError(
                f"dclgen v1 does not support SQL type {decl!r} "
                f"(floating point / lengthless TEXT / BLOB are not yet mapped)"
            )
        case build:
            return build(args)


def _binary(sql_type: str, total_digits: int) -> dict:
    return {
        "sql_type": sql_type,
        "category": "BINARY",
        "total_digits": total_digits,
        "decimal_digits": 0,
        "length": 0,
        "pic": f"S9({total_digits}) COMP",
    }


def _decimal(args: Sequence[int]) -> dict:
    precision = args[0] if args else 9
    scale = args[1] if len(args) > 1 else 0
    pic = (
        f"S9({precision - scale})V9({scale}) COMP-3"
        if scale > 0
        else f"S9({precision}) COMP-3"
    )
    return {
        "sql_type": f"DECIMAL({precision},{scale})",
        "category": "COMP3",
        "total_digits": precision,
        "decimal_digits": scale,
        "length": 0,
        "pic": pic,
    }


def _char(args: Sequence[int]) -> dict:
    char_len = args[0] if args else 1
    return {
        "sql_type": f"CHAR({char_len})",
        "category": "ALPHANUMERIC",
        "total_digits": char_len,
        "decimal_digits": 0,
        "length": char_len,
        "pic": f"X({char_len})",
    }


def _varchar(args: Sequence[int]) -> dict:
    varchar_len = args[0] if args else 1
    return {
        "sql_type": f"VARCHAR({varchar_len})",
        "category": "VARCHAR",
        "total_digits": 0,
        "decimal_digits": 0,
        "length": varchar_len,
        "pic": None,
    }


_TYPE_FAMILIES: tuple[tuple[tuple[str, ...], Callable[[Sequence[int]], dict]], ...] = (
    (("INTEGER", "INT", "INT4"), lambda _args: _binary("INTEGER", 9)),
    (("SMALLINT", "INT2"), lambda _args: _binary("SMALLINT", 4)),
    (("BIGINT", "INT8"), lambda _args: _binary("BIGINT", 18)),
    (("DECIMAL", "NUMERIC", "DEC"), _decimal),
    (("CHAR", "CHARACTER"), _char),
    (("VARCHAR", "VARYING", "CHARACTER VARYING"), _varchar),
)

_TYPES: Mapping[str, Callable[[Sequence[int]], dict]] = {
    name: build for names, build in _TYPE_FAMILIES for name in names
}


# ── Field + record assembly ───────────────────────────────────────────────────


@dataclass(frozen=True)
class GeneratedRecord:
    record_name: str
    copybook: str


def _field(column: str, decl: str, prefix: str) -> DclgenField:
    t = _parse_sql_type(decl)
    return DclgenField(
        host_var=prefix + _cobolify(column),
        category=t["category"],
        length=t["length"],
        pic=t["pic"] or "",
    )


def _record_lines(field: DclgenField, width: int) -> tuple[str, ...]:
    match field.category:
        case "VARCHAR":
            return (
                f"           05  {field.host_var}.",
                f"               49  {field.host_var + '-LEN':<{width}}  PIC S9(4) COMP.",
                f"               49  {field.host_var + '-TEXT':<{width}}  PIC X({field.length}).",
            )
        case _:
            return (f"           05  {field.host_var:<{width}}  PIC {field.pic}.",)


def _render_copybook(record_name: str, fields: Sequence[DclgenField]) -> str:
    width = max((len(f.host_var) for f in fields), default=0)
    lines = (
        f"       01  {record_name}.",
        *(line for field in fields for line in _record_lines(field, width)),
    )
    return "\n".join(lines) + "\n"


def generate(
    conn, table: str, record_name: str = "", prefix: str = ""
) -> GeneratedRecord:
    """Read *table*'s schema from *conn* and build its host-var record.

    *conn* is any DB-API connection exposing ``PRAGMA table_info`` (SQLite).
    """
    resolved_name = record_name or _cobolify(table)
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if not rows:
        raise ValueError(f"table {table!r} has no columns (does it exist?)")

    # PRAGMA table_info row: (cid, name, type, notnull, dflt_value, pk)
    fields = [
        _field(name, decl, prefix) for _cid, name, decl, _notnull, _dflt, _pk in rows
    ]

    return GeneratedRecord(
        record_name=resolved_name,
        copybook=_render_copybook(resolved_name, fields),
    )


def write(record: GeneratedRecord, out_dir) -> Path:
    """Write ``<RECORD>.cpy`` into *out_dir*; return its path."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cpy = out / f"{record.record_name}.cpy"
    cpy.write_text(record.copybook, encoding="utf-8")
    return cpy
