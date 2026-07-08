"""Typed AST for IDCAMS REPRO (comprehensive grammar), including its nested
ENCIPHER(...)/DECIPHER(...) cryptographic sub-blocks.

Field list and nested dataclass shapes (CipherSpec, DecipherSpec, RangeStart,
RangeEnd, Repro) transcribed verbatim from the design spec's `Repro` section
(2026-07-08-idcams-comprehensive-grammar-design.md).

Per the plan's ratified structural single-occurrence pattern (see
ast_delete.py's entry_type_param and ast_alter.py's catalog_state_choice for
prior art), REPRO has the most "pick one shape" choice groups of any command
so far -- eight independent, uncoupled groups (source, target, ENTRIES/LEVEL,
RangeStart's 4-way, RangeEnd's 4-way, ENCIPHER/DECIPHER, INSERTSHIFT/
INSERTALL, SKIPDBCSCHECK/NODBCSCHECK), plus two more nested inside the cipher
sub-blocks (CipherSpec's EXTERNALKEYNAME/INTERNALKEYNAME/PRIVATEKEY,
DecipherSpec's DATAKEYFILE/DATAKEYVALUE/SYSTEMKEY). Since none of the eight
top-level groups are coupled to each other, ams.lark enforces each with its
own small two-state (or, for the 4-way groups, still two-state -- one state
is "not yet consumed", the other "consumed") sequence chained one after
another in a fixed relative order, rather than the 2^8-state cross-product
DFA that would be needed to allow every possible relative ordering among all
eight groups structurally -- see ams.lark's REPRO section comment for the
full rationale.

Every other ON/OFF toggle pair mentioned in the design spec's Repro section
(CIMODE/NOCIMODE, MERGECAT/NOMERGECAT, REPLACE/NOREPLACE, REUSE/NOREUSE, and
CipherSpec's own STOREDATAKEY/NOSTOREDATAKEY) is an ordinary freely-
repeatable parameter, per the plan's ratified scope for simple binary
toggles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from jackal.idcams.ast_values import Name, Value

__all__ = ["CipherSpec", "DecipherSpec", "RangeStart", "RangeEnd", "Repro"]


@dataclass(frozen=True)
class CipherSpec:
    key_source: Literal["EXTERNALKEYNAME", "INTERNALKEYNAME", "PRIVATEKEY"]
    key_name: str | None = None  # present unless PRIVATEKEY
    cipher_unit: int = 1
    data_key_file: str | None = None
    data_key_value: str | None = None
    ship_key_names: tuple[str, ...] = ()
    store_data_key: bool | None = None
    store_key_name: str | None = None
    user_data: str | None = None


@dataclass(frozen=True)
class DecipherSpec:
    key_source: Literal["DATAKEYFILE", "DATAKEYVALUE", "SYSTEMKEY"]
    data_key_file: str | None = None
    data_key_value: str | None = None
    system_data_key: str | None = None
    system_key_name: str | None = None


@dataclass(frozen=True)
class RangeStart:
    kind: Literal["FROMKEY", "FROMADDRESS", "FROMNUMBER", "SKIP"]
    value: Value


@dataclass(frozen=True)
class RangeEnd:
    kind: Literal["TOKEY", "TOADDRESS", "TONUMBER", "COUNT"]
    value: Value


@dataclass(frozen=True)
class Repro:
    infile: str | None = None  # mutually exclusive with indataset
    indataset: Name | None = None
    outfile: str | None = None  # mutually exclusive with outdataset
    outdataset: Name | None = None
    cimode: bool | None = None
    dbcs: bool = False
    entries: tuple[Name, ...] = ()  # mutually exclusive with level
    level: str | None = None
    error_limit: int | None = None
    file: str | None = None
    range_start: RangeStart | None = None
    range_end: RangeEnd | None = None
    insert_shift: tuple[tuple[int, int], ...] = ()
    insert_all: bool = False
    merge_cat: bool | None = None
    message_level: Literal["ALL", "SHORT"] | None = None
    replace: bool | None = None
    reuse: bool | None = None
    skip_dbcs_check: tuple[tuple[int, int], ...] = ()
    no_dbcs_check: bool = False
    volume_entries: str | None = None
    encipher: CipherSpec | None = None
    decipher: DecipherSpec | None = None
    rls_source: Literal["NO", "YES", "QUIESCE"] | None = None
    rls_target: Literal["NO", "YES", "QUIESCE"] | None = None
