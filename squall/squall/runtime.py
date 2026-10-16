"""The SQL coprocessor's runtime surface: ``__exec_sql`` and its unit-of-work hooks over live connections."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from interpreter.func_name import FuncName
from squall.backend import SqlBackend
from squall.builtins.exec_sql import make_exec_sql_builtin
from squall.connector import DbConnector, NullDbConnector
from squall.sql_runtime import SqlRuntime

_NO_CONNECTOR: DbConnector = NullDbConnector()


def install_sql_runtime(
    connections: Mapping[str, SqlBackend],
    initial_connector: DbConnector = _NO_CONNECTOR,
    *,
    tolerant: bool = False,
) -> SqlRuntime:
    exec_sql_fn, reset_session_fn, syncpoint_fn, rollback_fn = make_exec_sql_builtin(
        connections, initial_connector=initial_connector, tolerant=tolerant
    )
    return SqlRuntime(
        entries=MappingProxyType({FuncName("__exec_sql"): exec_sql_fn}),
        reset_session=reset_session_fn,
        syncpoint=syncpoint_fn,
        rollback=rollback_fn,
    )
