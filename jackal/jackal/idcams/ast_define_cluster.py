"""Typed AST for IDCAMS DEFINE CLUSTER (comprehensive grammar).

DEFINE CLUSTER is the largest single IDCAMS command: ~50 real parameters
split across three "levels" -- the CLUSTER level itself, plus optional
DATA(...) and INDEX(...) trailer sub-clauses that override component-level
attributes. INDEX(...) accepts a strict subset of DATA(...)'s parameters
(no SPANNED/NONSPANNED, ERASE/NOERASE, BUFFERSPACE, FREESPACE, KEYS,
RECORDSIZE, or SPEED/RECOVERY -- those are meaningless for an index
component per the IDCAMS manual), so DataComponent and IndexComponent are
deliberately separate dataclasses rather than one shared shape.

Field lists are transcribed verbatim from the design spec's `DefineCluster`
section (2026-07-08-idcams-comprehensive-grammar-design.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from jackal.idcams.ast_values import Name, Retention, SpaceAllocation

__all__ = [
    "DataComponent",
    "IndexComponent",
    "DefineCluster",
    "DatabaseSpec",
]


@dataclass(frozen=True)
class DataComponent:
    name: Name | None = None
    space: SpaceAllocation | None = None
    volumes: tuple[str, ...] = ()
    buffer_space: int | None = None
    control_interval_size: int | None = None
    erase: bool | None = None  # ERASE | NOERASE
    exception_exit: str | None = None
    file: str | None = None
    freespace: tuple[int, int] | None = None
    keys: tuple[int, int] | None = None  # length, offset
    model: tuple[Name, Name | None] | None = None
    owner: str | None = None
    record_size: tuple[int, int] | None = None  # average, maximum
    reuse: bool | None = None
    share_options: tuple[int, int | None] | None = None
    spanned: bool | None = None  # SPANNED | NONSPANNED
    speed: bool | None = None  # SPEED (True) | RECOVERY (False)
    write_check: bool | None = None


@dataclass(frozen=True)
class IndexComponent:
    name: Name | None = None
    space: SpaceAllocation | None = None
    volumes: tuple[str, ...] = ()
    control_interval_size: int | None = None
    exception_exit: str | None = None
    file: str | None = None
    model: tuple[Name, Name | None] | None = None
    owner: str | None = None
    reuse: bool | None = None
    share_options: tuple[int, int | None] | None = None
    write_check: bool | None = None


@dataclass(frozen=True)
class DatabaseSpec:
    format: Literal["BSON", "JSON"]
    key_name: str
    key_name_is_utf8: bool  # KEYNAME (False) vs KEYNAMEU (True)


@dataclass(frozen=True)
class DefineCluster:
    name: Name
    space: SpaceAllocation | None = None  # required unless MODEL or SMS-managed
    volumes: tuple[str, ...] = ()  # required unless MODEL or SMS-managed
    account: str | None = None
    buffer_space: int | None = None
    bwo: Literal["TYPECICS", "TYPEIMS", "NO"] | None = None
    catalog: str | None = None
    control_interval_size: int | None = None
    database: DatabaseSpec | None = None  # DATABASE(BSON|JSON) KEYNAME|KEYNAMEU(...)
    data_class: str | None = None
    eattr: Literal["NO", "OPT"] | None = None
    erase: bool | None = None
    exception_exit: str | None = None
    file: str | None = None
    freespace: tuple[int, int] | None = None
    frlog: Literal["ALL", "NONE", "REDO", "UNDO"] | None = None
    organization: Literal["INDEXED", "LINEAR", "NONINDEXED", "NUMBERED", "ZFS"] = (
        "INDEXED"
    )
    key_label: str | None = None
    keys: tuple[int, int] | None = None
    log: Literal["NONE", "UNDO", "ALL"] | None = None
    log_replicate: bool | None = None
    log_stream_id: str | None = None
    management_class: str | None = None
    model: tuple[Name, Name | None] | None = None
    owner: str | None = None
    recatalog: bool | None = None
    record_size: tuple[int, int] | None = None
    reuse: bool | None = None
    rls_mode: Literal["QUIESCE", "ENABLE"] | None = None
    share_options: tuple[int, int | None] | None = None
    spanned: bool | None = None
    speed: bool | None = None
    storage_class: str | None = None
    retention: Retention | None = None  # TO(date) | FOR(days)
    write_check: bool | None = None
    data: DataComponent | None = None
    index: IndexComponent | None = None
