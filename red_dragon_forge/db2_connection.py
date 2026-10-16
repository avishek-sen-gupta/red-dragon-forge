"""The Db2 connection a run with [sql] uses: SQUALL_DB2_DSN, registered under its DATABASE name and current from the start, as a DSN RUN or CICS attachment thread is."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import ibm_db
from squall.backends.db2 import Db2Backend
from squall.connector import NamedDbConnector
from squall.runtime import install_sql_runtime

from red_dragon_forge.config_error import ConfigError

_DATABASE = "DATABASE"


@dataclass(frozen=True)
class Db2Connection:
    database: str
    backend: Db2Backend

    def install(self, tolerant: bool) -> Callable[[], None]:
        install_sql_runtime(
            {self.database: self.backend},
            NamedDbConnector(self.database),
            tolerant=tolerant,
        )
        return self.backend.rollback


def _database(dsn: str) -> str:
    named = tuple(
        value.strip().upper()
        for keyword, value in (
            part.split("=", 1) for part in dsn.split(";") if "=" in part
        )
        if keyword.strip().upper() == _DATABASE
    )
    if not named:
        raise ConfigError("SQUALL_DB2_DSN names no DATABASE")
    return named[0]


def connected(dsn: str) -> Db2Connection:
    database = _database(dsn)
    return Db2Connection(database, Db2Backend(ibm_db.connect(dsn, "", "")))
