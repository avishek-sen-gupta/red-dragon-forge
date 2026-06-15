"""
squall.parser.sql_model
~~~~~~~~~~~~~~~~~~~~~~~~~
Pure-data types for the parsed EXEC SQL model. No interpreter / binding imports:
behaviour (lowering, host-var resolution) lives in the consumers (strategy,
binding/exec_sql), which ``match`` on these sums.

Design tenets: no ``None`` in the model — every "absent" case is an explicit
null object; dataless closed sets are proper ``enum.Enum`` (NOT ``StrEnum`` — no
implicit ``==`` with ``str``); sums that carry data are frozen-dataclass unions.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import TypedDict


# ── Host variables ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class HostVar:
    name: str  # e.g. "WS-BAL" (no leading colon)
    indicator: str | None  # e.g. "WS-IND" for :WS-BAL:WS-IND, else None


# ── Statement kind (one member per grammar `?stmt` alternative) ───────────────
class Kind(enum.Enum):
    SELECT_INTO = "select_into"
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
    DECLARE_CURSOR = "declare_cursor"
    DECLARE_TABLE = "declare_table"
    DECLARE_STATEMENT = "declare_statement"
    DECLARE_VARIABLE = "declare_variable"
    FETCH = "fetch"
    OPEN = "open_"
    CLOSE = "close"
    COMMIT = "commit"
    ROLLBACK = "rollback"
    SAVEPOINT = "savepoint"
    RELEASE = "release"
    CONNECT = "connect"
    SET_CONNECTION = "set_connection"
    DISCONNECT = "disconnect"
    INCLUDE = "include"
    WHENEVER = "whenever"
    ALLOCATE_CURSOR = "allocate_cursor"
    MERGE = "merge"
    VALUES_INTO = "values_into"
    PREPARE = "prepare"
    EXECUTE = "execute_"
    DESCRIBE = "describe"
    GET_DIAGNOSTICS = "get_diagnostics"
    SIGNAL = "signal"
    BEGIN_DECLARE = "begin_declare"
    END_DECLARE = "end_declare"
    FREE_LOCATOR = "free_locator"
    HOLD_LOCATOR = "hold_locator"
    ASSOCIATE = "associate"
    CALL = "call"
    SET = "set"
    LOCK = "lock"
    GENERIC = "generic"


# ── Cursor reference ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class NamedCursor:
    name: str


@dataclass(frozen=True)
class NoCursor:
    pass


CursorRef = NamedCursor | NoCursor


# ── INCLUDE target ────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class IncludeName:
    name: str


@dataclass(frozen=True)
class NoInclude:
    pass


IncludeRef = IncludeName | NoInclude


# ── Connection target ─────────────────────────────────────────────────────────
@dataclass(frozen=True)
class LiteralDb:
    name: str  # upper-cased literal database name


@dataclass(frozen=True)
class HostVarDb:
    var: HostVar  # resolved at run time by the consumer


DbName = LiteralDb | HostVarDb


@dataclass(frozen=True)
class ConnectTo:
    # The named connection target for CONNECT TO / SET CONNECTION / DISCONNECT
    # <name>. The Kind distinguishes the operation; this carries the target db.
    db: DbName


@dataclass(frozen=True)
class ConnectReset:
    pass


@dataclass(frozen=True)
class NoConnect:
    pass


ConnectSpec = ConnectTo | ConnectReset | NoConnect


# ── WHENEVER condition (dataless closed set → enum) ───────────────────────────
class WheneverCondition(enum.Enum):
    SQLERROR = "SQLERROR"
    NOT_FOUND = "NOT FOUND"
    SQLWARNING = "SQLWARNING"
    NONE = "none"  # null object: the statement carries no WHENEVER condition


# ── WHENEVER action (GoTo carries data → dataclass union) ─────────────────────
@dataclass(frozen=True)
class GoTo:
    target: str


@dataclass(frozen=True)
class Continue:
    pass


@dataclass(frozen=True)
class NoOpAction:
    pass


WheneverAction = GoTo | Continue | NoOpAction


# ── dclgen sidecar descriptor (host var -> FieldMeta) ─────────────────────────
class FieldMeta(TypedDict, total=False):
    category: str  # ZONED_DECIMAL | ALPHANUMERIC | COMP3 | BINARY | VARCHAR
    offset: int
    length: int
    total_digits: int
    decimal_digits: int
    signed: bool
    len_var: str  # VARCHAR group only
    text_var: str  # VARCHAR group only


# ── The parsed statement ──────────────────────────────────────────────────────
@dataclass(frozen=True)
class ParsedSql:
    kind: Kind  # the statement kind
    in_vars: tuple[HostVar, ...]  # input (bind) host vars, in source order
    out_vars: tuple[HostVar, ...]  # output (INTO) host vars, in order
    cursor: str | None  # cursor name for cursor statements  (→ CursorRef, Task 3)
    query: str  # cleaned SQL for the DB
    include_name: str | None = None  # INCLUDE target  (→ include: IncludeRef, Task 4)
    # Connection management  (→ connect: ConnectSpec, Task 5)
    connect_variant: str | None = None
    connect_db: str | HostVar | None = None
    # WHENEVER directive  (→ WheneverCondition / WheneverAction, Task 6)
    whenever_condition: str | None = None
    whenever_action: str | None = None
    whenever_target: str | None = None
