"""Every member's area need, looked up by the callee a call names or the member a walk is in."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import cached_property, reduce

from cobble.dataflow.fixpoint.area_need import WHOLE_AREAS, AreaNeed, joined
from cobble.dataflow.fixpoint.area_slot import AreaSlot
from cobble.dataflow.fixpoint.call_site import CallSite
from cobol_memory.field_extent import FieldExtent

Receives = tuple[tuple[str, tuple[AreaSlot, ...]], ...]
NO_NEED = AreaNeed()


@dataclass(frozen=True)
class AreaTable:
    """Per member, its need and the slots it receives; ``dynamic`` the entry need of
    every member together, for a call that names its program by a data item;
    ``member`` the program whose walk asks. ``whole`` keeps every byte of every area.
    Pairs, not mappings, so the table pickles into worker processes."""

    needs: tuple[tuple[str, AreaNeed], ...] = ()
    receives: Receives = ()
    dynamic: AreaNeed = NO_NEED
    member: str = ""
    whole: bool = False

    @cached_property
    def _by_member(self) -> Mapping[str, AreaNeed]:
        return dict(self.needs)

    @cached_property
    def _receiving(self) -> Mapping[str, tuple[AreaSlot, ...]]:
        return dict(self.receives)

    def seen_from(self, member: str) -> AreaTable:
        return replace(self, member=member)

    def entry_at(
        self, site: CallSite, slot: AreaSlot, area: FieldExtent
    ) -> tuple[FieldExtent, ...]:
        """What the callee reads on entry; for a dynamic call, what any member reads;
        for a callee not in the table or not receiving this slot, every byte."""
        if self.whole:
            return (area,)
        if site.dynamic:
            return self.dynamic.at_entry(slot, area)
        return self._callee(site.callee, slot).at_entry(slot, area)

    def _callee(self, callee: str, slot: AreaSlot) -> AreaNeed:
        if slot not in self._receiving.get(callee, ()):
            return WHOLE_AREAS
        return self._by_member[callee]

    def back_at(self, slot: AreaSlot, area: FieldExtent) -> tuple[FieldExtent, ...]:
        """What this member's callers read back after it returns."""
        if self.whole or self.member not in self._by_member:
            return (area,)
        return self._by_member[self.member].read_back(slot, area)


WHOLE_TABLE = AreaTable(whole=True)


def area_table(
    needs: Sequence[tuple[str, AreaNeed]],
    receives: Sequence[tuple[str, tuple[AreaSlot, ...]]],
) -> AreaTable:
    """The table in member order, so two tables holding the same needs are equal."""
    by_member, receiving = dict(needs), dict(receives)
    return AreaTable(
        needs=tuple((member, by_member[member]) for member in sorted(by_member)),
        receives=tuple((member, receiving[member]) for member in sorted(receiving)),
        dynamic=reduce(
            joined,
            (AreaNeed(entry=need.entry) for need in by_member.values()),
            AreaNeed(),
        ),
    )
