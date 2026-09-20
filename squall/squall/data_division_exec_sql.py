"""
squall.data_division_exec_sql
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Recovers ``DECLARE CURSOR`` plans from the raw ProLeap bridge JSON's
``data_division_exec_sql`` key — EXEC SQL data-description entries found
outside PROCEDURE DIVISION (WORKING-STORAGE, typically; CardDemo's
``COTRTLIC`` declares both its cursors this way).

Why this exists: a ``DECLARE CURSOR`` statement inside PROCEDURE DIVISION
lowers normally and reaches ``_h_declare_cursor`` (``squall.builtins.exec_sql``)
at run time, which registers it into the live cursor registry the same way
every other EXEC SQL statement runs. A ``DECLARE CURSOR`` in WORKING-STORAGE
is not a statement at all — nothing ever lowers it — so it must be recovered
here, from the same raw bridge JSON ``squall.dclgen_meta`` already reads for
DCLGEN VARCHAR metadata, and fed into the cursor registry before OPEN ever
looks it up. ``DataFieldSerializer.serializeExecSqlEntries`` (the ProLeap
bridge, a separate repo) is what makes this key exist at all: it used to
silently drop these entries (forge-qhi).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from squall.parser.parse import parse_exec_sql
from squall.parser.sql_model import Kind, NamedCursor, ParsedSql

# The raw bridge JSON dict SqlLoweringStrategy.preprocess_program_dict
# receives, and one entry of its data_division_exec_sql array: {"section",
# "exec_sql_text", "line_start", "col_start", "line_end", "col_end"}. `Any`
# is the JSON boundary itself (mirrors squall.dclgen_meta's own _Field),
# never a lazy stand-in for a type this module could otherwise state
# precisely.
_ProgramDict = Mapping[str, Any]
_ExecSqlEntry = Mapping[str, Any]


def derive_cursors(data: _ProgramDict) -> Mapping[str, ParsedSql]:
    """Parse every ``DECLARE CURSOR`` in ``data["data_division_exec_sql"]``
    into ``{cursor_name: plan}``.

    Other EXEC SQL kinds recovered from outside PROCEDURE DIVISION (e.g. a
    ``DECLARE TABLE``, which is documentation for the precompiler and has no
    runtime effect) parse without error but are not cursors, so they are
    silently excluded here rather than raising — only their absence from
    ``ctx.cursors`` would ever matter, and OPEN already reports a clear
    SQLCODE for an unknown cursor name.
    """
    entries: tuple[_ExecSqlEntry, ...] = tuple(data.get("data_division_exec_sql", ()))
    parsed = (parse_exec_sql(entry["exec_sql_text"]) for entry in entries)
    return {
        plan.cursor.name: plan
        for plan in parsed
        if plan.kind is Kind.DECLARE_CURSOR and isinstance(plan.cursor, NamedCursor)
    }
