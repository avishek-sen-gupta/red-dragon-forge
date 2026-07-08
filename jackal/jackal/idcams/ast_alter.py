"""Typed AST for IDCAMS ALTER (comprehensive grammar).

ALTER is the second-largest command in the comprehensive IDCAMS grammar
(~45 optional parameters, transcribed verbatim from the design spec's
`Alter` section, 2026-07-08-idcams-comprehensive-grammar-design.md).

Per the plan's ratified mutual-exclusivity scoping decision, only ONE pair
of parameters in ALTER gets structural (grammar-level) single-occurrence
enforcement: LOCK/UNLOCK vs SUSPEND/RESUME, because the manual documents
both pairs as operating on the same underlying "catalog access state" --
providing e.g. both LOCK and SUSPEND on one ALTER would be an ontological
contradiction, not just a style choice. Modeled here as two independent
optional bool fields (`lock`, `suspend`) that the grammar's
`catalog_state_choice` rule guarantees are never both set by the same
parse (see ams.lark). Every other ON/OFF toggle pair in this command
(ERASE/NOERASE, EMPTY/NOEMPTY, INHIBIT/UNINHIBIT, PURGE/NOPURGE,
RECLAIMCA/NORECLAIMCA, REUSE/NOREUSE, RLSQUIESCE/RLSENABLE,
SCRATCH/NOSCRATCH, UNIQUEKEY/NONUNIQUEKEY, UPDATE/NOUPDATE,
UPGRADE/NOUPGRADE, WRITECHECK/NOWRITECHECK, FIFO/LIFO,
ECSHARING/NOECSHARING) is an ordinary freely-repeatable parameter --
last-wins-in-a-repeatable-list semantics is an accepted, low-risk
interpretation for simple binary toggles per the plan's ratified scope.

No `stage` field: the design spec explicitly defers STAGE (its real
definition wasn't recoverable from the manual excerpt read when the spec
was written). Not added here either -- see task report for whether this
task's implementer independently found it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from jackal.idcams.ast_values import Name, Retention

__all__ = ["NullifySpec", "Alter"]


@dataclass(frozen=True)
class NullifySpec:
    """The `NULLIFY(...)` sub-block: all 9 sub-options are independently
    settable (a single NULLIFY can plausibly nullify several attributes at
    once), so unlike `lock`/`suspend` above this is NOT a "pick one"
    choice -- every field here is its own independent flag."""

    authorization: Literal["MODULE", "STRING"] | None = None
    bwo: bool = False
    code: bool = False
    exception_exit: bool = False
    log: bool = False
    log_stream_id: bool = False
    management_class: bool = False
    owner: bool = False
    retention: bool = False


@dataclass(frozen=True)
class Alter:
    entry: Name
    account: str | None = None
    add_volumes: tuple[str, ...] = ()
    buffer_space: int | None = None
    bufnd: int | None = None
    bufni: int | None = None
    bwo: Literal["TYPECICS", "TYPEIMS", "NO"] | None = None
    catalog: str | None = None
    ccsid: int | None = None
    ec_sharing: bool | None = None
    empty: bool | None = None
    erase: bool | None = None
    exception_exit: str | None = None
    extended_addressable: bool = False
    order: Literal["FIFO", "LIFO"] | None = None
    file: str | None = None
    file_data: Literal["TEXT", "BINARY"] | None = None
    freespace: tuple[int, int] | None = None
    frlog: Literal["NONE", "REDO"] | None = None
    inhibit: bool | None = None  # INHIBIT | UNINHIBIT
    keys: tuple[int, int] | None = None
    limit: int | None = None
    lock: bool | None = None  # LOCK | UNLOCK (mutually exclusive with suspend)
    log: Literal["NONE", "UNDO", "ALL", "REDO"] | None = None
    log_replicate: bool | None = None
    log_stream_id: str | None = None
    management_class: str | None = None
    new_name: Name | None = None
    nullify: NullifySpec | None = None
    owner: str | None = None
    purge: bool | None = None
    reclaim_ca: bool | None = None
    record_size: tuple[int, int] | None = None
    remove_volumes: tuple[str, ...] = ()
    reuse: bool | None = None
    rls_mode: Literal["QUIESCE", "ENABLE"] | None = None
    roll_in: bool = False
    scratch: bool | None = None
    share_options: tuple[int, int | None] | None = None
    storage_class: str | None = None
    strno: int | None = None
    suspend: bool | None = None  # SUSPEND | RESUME
    retention: Retention | None = None
    to_linear: bool = False  # TYPE(LINEAR)
    unique_key: bool | None = None
    update: bool | None = None
    upgrade: bool | None = None
    write_check: bool | None = None
