"""Wraps Squall's SqlLoweringStrategy as a CoprocessorSpec -- the seam
interpreter.project.coprocessor_compile.compile_program composes."""

from __future__ import annotations

from collections.abc import Mapping

from interpreter.project.coprocessor_compile import CoprocessorSpec
from squall.backend import SqlBackend
from squall.connector import DbConnector, NullDbConnector
from squall.db2_stubs import read_db2_stub_sources
from squall.preprocess import apply_sql_prepass
from squall.statements import SqlDialectParser
from squall.strategy import SqlLoweringStrategy

# A module-level singleton rather than a call in build_sql_spec's own default
# (B008 -- mirrors squall.strategy._NO_CONNECTOR exactly): a fresh
# NullDbConnector() is stateless, so every caller that doesn't pass its own can
# safely share this one instance.
_NO_CONNECTOR: DbConnector = NullDbConnector()


def build_sql_spec(
    connections: Mapping[str, SqlBackend],
    initial_connector: DbConnector = _NO_CONNECTOR,
    *,
    tolerant: bool = False,
) -> CoprocessorSpec:
    """Build the EXEC SQL CoprocessorSpec.

    ``source_prepass`` rewrites EXEC SQL INCLUDE -> COPY.

    ``initial_connector``, when it resolves a backend, is already current when
    the program starts -- models the CICS Db2 attachment facility, which hands
    a plan-bound program a live thread before its first SQL statement runs
    (the program itself never issues ``EXEC SQL CONNECT``, e.g. Bank-of-Z's
    ``INQCUST``). The default ``NullDbConnector()`` preserves squall's faithful
    disconnected-start behaviour for programs that CONNECT themselves; pass a
    ``squall.connector.NamedDbConnector(name)`` to model the attachment facility.

    ``tolerant=True`` skips host variables missing from the data layout
    rather than raising, so programs whose DCLGEN
    copybooks use non-standard naming conventions (e.g. ``DCLEX-`` instead of
    the ``DCL-`` prefix Squall derives from the SQL) still execute — host
    variables that can't be located stay at their initialized values.

    Every program this spec compiles gets its own strategy; the last one's
    ``__exec_sql`` is the one registered in ``Builtins.TABLE``, and it serves
    every program, because each call site carries its own statement,
    declaration and VARCHAR shapes.

    ``linked_subprogram_sources`` links squall's Db2 stubs (``DSNTIAC``) into
    every run unit this spec compiles. Linking them outright rather than
    contributing a ``source_search_dirs`` entry is forced, not a preference:
    the search path is walked from CALL edges a text scan found, and CardDemo
    reaches DSNTIAC by data-name, which no scan can discover (red-dragon-t3kl).
    See ``squall.db2_stubs`` for what each stub does and does not model.
    """

    def _make_strategy() -> SqlLoweringStrategy:
        return SqlLoweringStrategy(
            connections,
            initial_connector=initial_connector,
            tolerant=tolerant,
        )

    return CoprocessorSpec(
        name="sql",
        make_strategy=_make_strategy,
        source_prepass=apply_sql_prepass,
        owns_execution=False,
        dialect_parser=SqlDialectParser(),
        linked_subprogram_sources=read_db2_stub_sources,
    )
