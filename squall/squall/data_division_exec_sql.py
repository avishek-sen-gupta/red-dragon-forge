"""
squall.data_division_exec_sql
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Recovers ``DECLARE CURSOR`` texts from the raw ProLeap bridge JSON's
``data_division_exec_sql`` key — EXEC SQL data-description entries found
outside PROCEDURE DIVISION (WORKING-STORAGE, typically; CardDemo's
``COTRTLIC`` declares both its cursors this way).

Why this exists: a ``DECLARE CURSOR`` in WORKING-STORAGE is not a statement
the lowering ever sees, so it is recovered here, and the lowering writes its
text into each OPEN of that cursor. ``DataFieldSerializer.serializeExecSqlEntries``
(the ProLeap bridge, a separate repo) is what makes this key exist at all: it
used to silently drop these entries (forge-qhi).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from squall.parser.parse import parse_exec_sql
from squall.parser.sql_model import Kind, NamedCursor

# The raw bridge JSON dict SqlLoweringStrategy.preprocess_program_dict
# receives, and one entry of its data_division_exec_sql array: {"section",
# "exec_sql_text", "line_start", "col_start", "line_end", "col_end"}. `Any`
# is the JSON boundary itself (mirrors squall.dclgen_meta's own _Field),
# never a lazy stand-in for a type this module could otherwise state
# precisely.
_ProgramDict = Mapping[str, Any]
_ExecSqlEntry = Mapping[str, Any]


def derive_cursors(data: _ProgramDict) -> Mapping[str, str]:
    """Every ``DECLARE CURSOR`` in ``data["data_division_exec_sql"]``, as
    ``{cursor_name: declaration text}``.

    Other EXEC SQL kinds recovered from outside PROCEDURE DIVISION (e.g. a
    ``DECLARE TABLE``, which is documentation for the precompiler and has no
    runtime effect) parse without error but are not cursors, so they are
    silently excluded here rather than raising; OPEN reports a clear SQLCODE
    for an unknown cursor name.
    """
    entries: tuple[_ExecSqlEntry, ...] = tuple(data.get("data_division_exec_sql", ()))
    texts = (str(entry["exec_sql_text"]) for entry in entries)
    return {
        plan.cursor.name: text
        for text, plan in ((text, parse_exec_sql(text)) for text in texts)
        if plan.kind is Kind.DECLARE_CURSOR and isinstance(plan.cursor, NamedCursor)
    }
