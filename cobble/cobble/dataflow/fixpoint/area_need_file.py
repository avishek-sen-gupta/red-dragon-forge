"""The per-member area need as stored on disk, one JSON row per member, paid once per corpus."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from cobble.dataflow.fixpoint.area_kind import AreaKind
from cobble.dataflow.fixpoint.area_need import AreaNeed, Slotted
from cobble.dataflow.fixpoint.area_slot import AreaSlot
from cobble.dataflow.fixpoint.area_table import AreaTable, area_table
from pydantic import BaseModel, ConfigDict

_Slot = tuple[AreaKind, int]
_Bounded = tuple[tuple[_Slot, tuple[int, ...]], ...]


class AreaNeedRow(BaseModel):
    """One member: the slots it receives, per slot the area-relative bounds read on
    entry and read back by its callers, and the candidates of each of its dynamic
    call sites that resolved, by node."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    member: str
    receives: tuple[_Slot, ...] = ()
    entry: _Bounded = ()
    back: _Bounded = ()
    sites: tuple[tuple[str, tuple[str, ...]], ...] = ()


def _plain(slotted: Slotted) -> _Bounded:
    return tuple(((slot.kind, slot.position), bounds) for slot, bounds in slotted)


def _slotted(bounded: _Bounded) -> Slotted:
    return tuple((AreaSlot(*slot), bounds) for slot, bounds in bounded)


def rows_of(table: AreaTable) -> tuple[AreaNeedRow, ...]:
    receiving = dict(table.receives)
    return tuple(
        AreaNeedRow(
            member=member,
            receives=tuple((slot.kind, slot.position) for slot in receiving[member]),
            entry=_plain(need.entry),
            back=_plain(need.back),
            sites=tuple(
                (node, callees)
                for caller, node, callees in table.sites
                if caller == member
            ),
        )
        for member, need in table.needs
    )


def write_rows(rows: Iterable[AreaNeedRow], path: Path) -> None:
    path.write_text(
        "".join(f"{row.model_dump_json()}\n" for row in rows), encoding="utf-8"
    )


def read_rows(path: Path) -> tuple[AreaNeedRow, ...]:
    return tuple(
        AreaNeedRow.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    )


def table_of(rows: Iterable[AreaNeedRow]) -> AreaTable:
    held = tuple(rows)
    return area_table(
        tuple(
            (row.member, AreaNeed(entry=_slotted(row.entry), back=_slotted(row.back)))
            for row in held
        ),
        tuple(
            (row.member, tuple(AreaSlot(*slot) for slot in row.receives))
            for row in held
        ),
        tuple(
            (row.member, node, callees) for row in held for node, callees in row.sites
        ),
    )
