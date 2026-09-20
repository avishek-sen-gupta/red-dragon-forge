"""Wraps Squall's SqlLoweringStrategy as a CoprocessorSpec -- the seam
interpreter.project.coprocessor_compile.compile_program composes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from interpreter.project.coprocessor_compile import CoprocessorSpec
from squall.backend import SqlBackend
from squall.connector import DbConnector, NullDbConnector
from squall.preprocess import apply_sql_prepass
from squall.statements import SqlDialectParser
from squall.strategy import SqlLoweringStrategy
from squall.strategy_stores import SharedSqlStores, absorb_field_meta

# A module-level singleton rather than a call in build_sql_spec's own default
# (B008 -- mirrors squall.strategy._NO_CONNECTOR exactly): a fresh
# NullDbConnector() is stateless, so every caller that doesn't pass its own can
# safely share this one instance.
_NO_CONNECTOR: DbConnector = NullDbConnector()


def build_sql_spec(
    connections: Mapping[str, SqlBackend],
    copybook_dirs: Sequence[Path] = (),
    initial_connector: DbConnector = _NO_CONNECTOR,
    *,
    tolerant: bool = False,
) -> CoprocessorSpec:
    """Build the EXEC SQL CoprocessorSpec.

    ``source_prepass`` expands EXEC SQL INCLUDE -> COPY and gathers the dclgen
    field metadata as a side effect, absorbing it straight into ``stores``, so
    ``make_strategy`` needs no sidecar metadata of its own. ``compile_program``
    always runs every spec's source-text stage before any spec's
    ``make_strategy``, so the store is populated in time (see
    CoprocessorSpec's docstring for why this ordering is required for SQL
    specifically, unlike CICS).

    ``initial_connector``, when it resolves a backend, is already current when
    the program starts -- models the CICS Db2 attachment facility, which hands
    a plan-bound program a live thread before its first SQL statement runs
    (the program itself never issues ``EXEC SQL CONNECT``, e.g. Bank-of-Z's
    ``INQCUST``). The default ``NullDbConnector()`` preserves squall's faithful
    disconnected-start behaviour for programs that CONNECT themselves; pass a
    ``squall.connector.NamedDbConnector(name)`` to model the attachment facility.

    ``tolerant=True`` skips DCLGEN field-name mismatches (``KeyError`` /
    ``FieldMetaMismatch``) rather than raising, so programs whose DCLGEN
    copybooks use non-standard naming conventions (e.g. ``DCLEX-`` instead of
    the ``DCL-`` prefix Squall derives from the SQL) still execute — host
    variables that can't be located stay at their initialized values.

    One ``SharedSqlStores`` is built here and handed to EVERY strategy this
    spec makes, so a region compiling several SQL programs from one spec
    keeps each program's plans, cursors and DCLGEN metadata reachable from
    the single ``__exec_sql`` builtin that survives in ``Builtins.TABLE``
    (forge-2xy; see ``SharedSqlStores`` for what breaks without it). Mirrors
    ``build_cics_spec``'s spec-level ``context_holder``/``result_holder``/
    ``program_cache``.
    """
    stores = SharedSqlStores()

    def _prepass(source: str) -> str:
        result = apply_sql_prepass(source, copybook_dirs)
        absorb_field_meta(
            stores.field_meta, result.field_meta, stores.sidecar_field_names
        )
        return result.source

    def _make_strategy() -> SqlLoweringStrategy:
        # An empty sidecar mapping, not an oversight: this program's sidecar
        # entries are already in stores.field_meta, put there by the
        # source-text stage above. The argument stays for the direct callers
        # that have no spec and hand their metadata in themselves.
        return SqlLoweringStrategy(
            connections,
            {},
            initial_connector=initial_connector,
            tolerant=tolerant,
            stores=stores,
        )

    return CoprocessorSpec(
        name="sql",
        make_strategy=_make_strategy,
        source_prepass=_prepass,
        owns_execution=False,
        dialect_parser=SqlDialectParser(),
    )
