"""
squall.dclgen
~~~~~~~~~~~~~
A squall-side DCLGEN: read a database table's schema and generate the COBOL
host-variable record (the copybook an ``EXEC SQL INCLUDE`` pulls in) plus a JSON
sidecar of per-field metadata.

The copybook is consumed by ProLeap (after ``INCLUDE → COPY``); the JSON carries
the *SQL-side* type each host var was generated for, so binding never has to
recover the column type from the COBOL PIC (which is lossy). This is the forward,
single-source-of-truth mapping — DB type → COBOL PIC + metadata.

Design
------
* Pure functions for the mapping/render; the only effect is reading the schema
  (``generate``) and writing files (``write``).
* v1 supports exactly the categories the binding codec can bind today:
  INTEGER/SMALLINT/BIGINT (binary COMP), DECIMAL/NUMERIC (COMP-3), CHAR (PIC X).
  VARCHAR / floating point / lengthless TEXT / BLOB raise ``NotImplementedError``
  rather than silently degrade (faithful VARCHAR is tracked separately).
* No regex: the declared-type string is split on fixed punctuation, not parsed
  with a pattern.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


# ── Name mapping ──────────────────────────────────────────────────────────────


def _cobolify(name: str) -> str:
    """Map a SQL identifier to a COBOL one: underscores → hyphens, uppercased."""
    return name.replace("_", "-").upper()


# ── Declared-type → COBOL mapping (the forward DCLGEN table) ───────────────────


def _split_decl(decl: str) -> tuple[str, list[int]]:
    """Split a declared type like ``DECIMAL(7,2)`` into (``DECIMAL``, [7, 2]).

    Fixed-punctuation split — not a regex over a sublanguage.
    """
    base, _, rest = decl.strip().partition("(")
    base = base.strip().upper()
    args: list[int] = []
    if rest:
        for part in rest.rstrip(")").split(","):
            part = part.strip()
            if part:
                args.append(int(part))
    return base, args


def _parse_sql_type(decl: str) -> dict:
    """Map a SQLite declared type to its COBOL field attributes.

    Returns a dict: ``{sql_type, category, total_digits, decimal_digits, length, pic}``.
    Raises ``NotImplementedError`` for types v1 does not support.
    """
    base, args = _split_decl(decl)

    if base in ("INTEGER", "INT", "INT4"):
        return _binary("INTEGER", 9)
    if base in ("SMALLINT", "INT2"):
        return _binary("SMALLINT", 4)
    if base in ("BIGINT", "INT8"):
        return _binary("BIGINT", 18)

    if base in ("DECIMAL", "NUMERIC", "DEC"):
        precision = args[0] if args else 9
        scale = args[1] if len(args) > 1 else 0
        integer_digits = precision - scale
        pic = (
            f"S9({integer_digits})V9({scale}) COMP-3"
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

    if base in ("CHAR", "CHARACTER"):
        n = args[0] if args else 1
        return {
            "sql_type": f"CHAR({n})",
            "category": "ALPHANUMERIC",
            # ProLeap reports total_digits = character count for PIC X(n); match it
            # so the metadata agrees with the data_layout it will be validated against.
            "total_digits": n,
            "decimal_digits": 0,
            "length": n,
            "pic": f"X({n})",
        }

    raise NotImplementedError(
        f"dclgen v1 does not support SQL type {decl!r} "
        f"(VARCHAR / floating point / lengthless TEXT / BLOB are not yet mapped)"
    )


def _binary(sql_type: str, total_digits: int) -> dict:
    return {
        "sql_type": sql_type,
        "category": "BINARY",
        "total_digits": total_digits,
        "decimal_digits": 0,
        "length": 0,
        "pic": f"S9({total_digits}) COMP",
    }


# ── Field + record assembly ───────────────────────────────────────────────────


@dataclass(frozen=True)
class GeneratedRecord:
    record_name: str
    copybook: str
    metadata: dict


def _field_meta(column: str, decl: str, notnull: int, prefix: str) -> dict:
    t = _parse_sql_type(decl)
    return {
        "column": column,
        "host_var": prefix + _cobolify(column),
        "sql_type": t["sql_type"],
        "nullable": not bool(notnull),
        "category": t["category"],
        "total_digits": t["total_digits"],
        "decimal_digits": t["decimal_digits"],
        "length": t["length"],
        "pic": t["pic"],
    }


def _render_copybook(record_name: str, fields: list[dict]) -> str:
    # 01 in Area A (column 8), 05 elementary items in Area B (column 12).
    width = max((len(f["host_var"]) for f in fields), default=0)
    lines = [f"       01  {record_name}."]
    for f in fields:
        lines.append(f"           05  {f['host_var']:<{width}}  PIC {f['pic']}.")
    return "\n".join(lines) + "\n"


def generate(
    conn, table: str, record_name: str | None = None, prefix: str = ""
) -> GeneratedRecord:
    """Read *table*'s schema from *conn* and build its host-var record + metadata.

    *conn* is any DB-API connection exposing ``PRAGMA table_info`` (SQLite).
    """
    record_name = record_name or _cobolify(table)
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if not rows:
        raise ValueError(f"table {table!r} has no columns (does it exist?)")

    # PRAGMA table_info row: (cid, name, type, notnull, dflt_value, pk)
    fields = [_field_meta(name, decl, notnull, prefix) for _, name, decl, notnull, _, _ in rows]

    metadata = {"record": record_name, "table": table, "fields": fields}
    return GeneratedRecord(
        record_name=record_name,
        copybook=_render_copybook(record_name, fields),
        metadata=metadata,
    )


def write(record: GeneratedRecord, out_dir) -> tuple[Path, Path]:
    """Write ``<RECORD>.cpy`` and ``<RECORD>.json`` into *out_dir*; return paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cpy = out / f"{record.record_name}.cpy"
    meta = out / f"{record.record_name}.json"
    cpy.write_text(record.copybook, encoding="utf-8")
    meta.write_text(json.dumps(record.metadata, indent=2), encoding="utf-8")
    return cpy, meta
