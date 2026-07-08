"""Typed AST for IDCAMS DEFINE ALTERNATEINDEX (comprehensive grammar).

DEFINE ALTERNATEINDEX (AIX) creates an alternate index over a base cluster.
Like DEFINE CLUSTER it has DATA(...)/INDEX(...) trailer sub-clauses, but the
component shapes here (`AixDataComponent`/`AixIndexComponent`) are distinct
dataclasses from `DataComponent`/`IndexComponent` (Task 2) -- they add
ATTEMPTS/AUTHORIZATION/CODE/UNIQUEKEY and omit SPANNED/NONSPANNED (not valid
for an AIX component per the IDCAMS manual).

Unlike DefineCluster, DefineAlternateIndex also carries several *_ignored
fields for genuinely obsolete parameters (IMBED, KEYRANGES, ORDERED/
UNORDERED, REPLICATE/NOREPLICATE) that real (old) JCL may still specify --
these must still parse, but carry no semantic weight for a modern AIX.

Field lists are transcribed verbatim from the design spec's
`DefineAlternateIndex` section
(2026-07-08-idcams-comprehensive-grammar-design.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from jackal.idcams.ast_values import Name, Retention, SpaceAllocation

__all__ = [
    "AixDataComponent",
    "AixIndexComponent",
    "DefineAlternateIndex",
]


@dataclass(frozen=True)
class AixDataComponent:
    # Same shape as DataComponent minus SPANNED/NONSPANNED (not valid for AIX per manual)
    name: Name | None = None
    space: SpaceAllocation | None = None
    volumes: tuple[str, ...] = ()
    attempts: int | None = None
    authorization: tuple[str, str | None] | None = None
    buffer_space: int | None = None
    code: str | None = None
    control_interval_size: int | None = None
    erase: bool | None = None
    exception_exit: str | None = None
    file: str | None = None
    freespace: tuple[int, int] | None = None
    keys: tuple[int, int] | None = None
    model: tuple[Name, Name | None] | None = None
    owner: str | None = None
    record_size: tuple[int, int] | None = None
    reuse: bool | None = None
    share_options: tuple[int, int | None] | None = None
    speed: bool | None = None
    unique_key: bool | None = None
    write_check: bool | None = None


@dataclass(frozen=True)
class AixIndexComponent:
    name: Name | None = None
    space: SpaceAllocation | None = None
    volumes: tuple[str, ...] = ()
    attempts: int | None = None
    authorization: tuple[str, str | None] | None = None
    code: str | None = None
    control_interval_size: int | None = None
    exception_exit: str | None = None
    file: str | None = None
    model: tuple[Name, Name | None] | None = None
    owner: str | None = None
    reuse: bool | None = None
    share_options: tuple[int, int | None] | None = None
    write_check: bool | None = None


@dataclass(frozen=True)
class DefineAlternateIndex:
    name: Name
    relate: Name
    space: SpaceAllocation | None = None
    volumes: tuple[str, ...] = ()
    buffer_space: int | None = None
    catalog: str | None = None
    control_interval_size: int | None = None
    data_class: str | None = None
    erase: bool | None = None
    exception_exit: str | None = None
    file: str | None = None
    freespace: tuple[int, int] | None = None
    imbed: bool | None = None  # accepted, ignored (obsolete per manual)
    key_ranges_ignored: bool = False  # KEYRANGES: accepted, ignored (obsolete)
    keys: tuple[int, int] | None = None
    alt_keys: tuple[tuple[str, Literal["A", "D"]], ...] | None = None  # ALTKEYS
    alt_keys_utf8: tuple[tuple[str, Literal["A", "D"]], ...] | None = None  # ALTKEYSU
    model: tuple[Name, Name | None] | None = None
    order_ignored: bool = False  # ORDERED|UNORDERED: accepted, ignored (obsolete)
    owner: str | None = None
    recatalog: bool | None = None
    record_size: tuple[int, int] | None = None
    replicate_ignored: bool = (
        False  # REPLICATE|NOREPLICATE: accepted, ignored (obsolete)
    )
    reuse: bool | None = None
    share_options: tuple[int, int | None] | None = None
    speed: bool | None = None
    retention: Retention | None = None
    unique_key: bool | None = None  # UNIQUEKEY | NONUNIQUEKEY
    upgrade: bool | None = None  # UPGRADE | NOUPGRADE
    write_check: bool | None = None
    data: "AixDataComponent | None" = None
    index: "AixIndexComponent | None" = None
