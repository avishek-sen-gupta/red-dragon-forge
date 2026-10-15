"""The SQL coprocessor's runtime surface: installs ``__exec_sql`` and the three CICS hooks over live connections."""

from __future__ import annotations

from collections.abc import Mapping

from squall.backend import SqlBackend
from squall.builtins.exec_sql import make_exec_sql_builtin
from squall.connector import DbConnector, NullDbConnector
from squall.strategy_stores import register

_NO_CONNECTOR: DbConnector = NullDbConnector()


def install_sql_runtime(
    connections: Mapping[str, SqlBackend],
    initial_connector: DbConnector = _NO_CONNECTOR,
    *,
    tolerant: bool = False,
) -> None:
    exec_sql_fn, reset_session_fn, syncpoint_fn, rollback_fn = make_exec_sql_builtin(
        connections, initial_connector=initial_connector, tolerant=tolerant
    )
    register("__exec_sql", exec_sql_fn)
    register("__cics_task_end_hook", reset_session_fn)
    register("__cics_syncpoint_hook", syncpoint_fn)
    register("__cics_rollback_hook", rollback_fn)
