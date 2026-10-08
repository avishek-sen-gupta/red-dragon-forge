"""Every member's area need, looked up by the callee a call names or the member a walk is in."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import cached_property, reduce

from cobble.dataflow.fixpoint.area_need import WHOLE_AREAS, AreaNeed, joined
from cobble.dataflow.fixpoint.area_slot import AreaSlot
from cobble.dataflow.fixpoint.call_site import CallSite
from cobble.dataflow.fixpoint.target_site import Sites
from cobol_memory.field_extent import FieldExtent

Receives = tuple[tuple[str, tuple[AreaSlot, ...]], ...]
NO_NEED = AreaNeed()


@dataclass(frozen=True)
class AreaTable:
    """Per member, its need and the slots it receives; ``sites`` the dynamic call
    sites the combined targets resolved, by caller and node, with their candidates;
    ``dynamic`` the entry need of every member together, for a dynamic site that did
    not resolve; ``member`` the program whose walk asks. ``whole`` keeps every byte
    of every area. Pairs, not mappings, so the table pickles into worker processes."""

    needs: tuple[tuple[str, AreaNeed], ...] = ()
    receives: Receives = ()
    sites: Sites = ()
    dynamic: AreaNeed = NO_NEED
    member: str = ""
    whole: bool = False

    @cached_property
    def _by_member(self) -> Mapping[str, AreaNeed]:
        return dict(self.needs)

    @cached_property
    def _resolved(self) -> Mapping[tuple[str, str], tuple[str, ...]]:
        return {(caller, node): callees for caller, node, callees in self.sites}

    @cached_property
    def _receiving(self) -> Mapping[str, tuple[AreaSlot, ...]]:
        return dict(self.receives)

    def seen_from(self, member: str) -> AreaTable:
        return replace(self, member=member)

    def callees_at(self, node: str, site: CallSite) -> tuple[str, ...]:
        """The programs the call at ``node`` in this member can reach: the one it
        names, the candidates its dynamic site resolved to, or none known."""
        if not site.dynamic:
            return (site.callee,)
        return self._resolved.get((self.member, node), ())

    def entry_at(
        self, node: str, site: CallSite, slot: AreaSlot, area: FieldExtent
    ) -> tuple[FieldExtent, ...]:
        """What the callees read on entry; for a dynamic call that did not resolve,
        what any member reads; for a callee not in the table or not receiving this
        slot, every byte."""
        if self.whole:
            return (area,)
        callees = self.callees_at(node, site)
        if not callees:
            return self.dynamic.at_entry(slot, area)
        return tuple(
            piece
            for callee in callees
            for piece in self._callee(callee, slot).at_entry(slot, area)
        )

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
    sites: Sites,
) -> AreaTable:
    """The table in member order, so two tables holding the same needs are equal."""
    by_member, receiving = dict(needs), dict(receives)
    return AreaTable(
        needs=tuple((member, by_member[member]) for member in sorted(by_member)),
        receives=tuple((member, receiving[member]) for member in sorted(receiving)),
        sites=tuple(sorted(sites)),
        dynamic=reduce(
            joined,
            (AreaNeed(entry=need.entry) for need in by_member.values()),
            AreaNeed(),
        ),
    )
