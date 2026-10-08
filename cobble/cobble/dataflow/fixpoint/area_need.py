"""Which bytes of a handed-over area matter: what callees read on entry, and callers read back."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.dataflow.fields.spans import Spans, merged, pairs_of
from cobble.dataflow.fixpoint.area_slot import AreaSlot
from cobol_memory.field_extent import FieldExtent

Bounds = tuple[int, ...]
Slotted = tuple[tuple[AreaSlot, Bounds], ...]


@dataclass(frozen=True)
class AreaNeed:
    """Area-relative bytes per slot needed on entry, and read back after a LINK or
    CALL returns. ``whole`` keeps every byte of every area."""

    entry: Slotted = ()
    back: Slotted = ()
    whole: bool = False

    def at_entry(self, slot: AreaSlot, area: FieldExtent) -> tuple[FieldExtent, ...]:
        return self._within(self.entry, slot, area)

    def read_back(self, slot: AreaSlot, area: FieldExtent) -> tuple[FieldExtent, ...]:
        return self._within(self.back, slot, area)

    def _within(
        self,
        table: Slotted,
        slot: AreaSlot,
        area: FieldExtent,
    ) -> tuple[FieldExtent, ...]:
        if self.whole:
            return (area,)
        return tuple(
            FieldExtent(
                region=area.region,
                start=area.start + low,
                length=min(high, area.length) - low,
                precision=area.precision,
                field_name=area.field_name,
            )
            for low, high in pairs_of(dict(table).get(slot, ()))
            if low < area.length
        )


WHOLE_AREAS = AreaNeed(whole=True)


def relative(spans: Spans, area: FieldExtent) -> Bounds:
    """The bytes of ``area`` that ``spans`` holds, as offsets from its start."""
    end = area.start + area.length
    return merged(
        (max(low, area.start) - area.start, min(high, end) - area.start)
        for low, high in pairs_of(spans.get(area.region, ()))
        if low < end and area.start < high
    )


def _union(left: Slotted, right: Slotted) -> Slotted:
    """Pairs, not a mapping, so the need pickles into the worker processes."""
    lefts, rights = dict(left), dict(right)
    return tuple(
        (
            slot,
            merged(
                (
                    *pairs_of(lefts.get(slot, ())),
                    *pairs_of(rights.get(slot, ())),
                )
            ),
        )
        for slot in sorted({*lefts, *rights})
    )


def joined(left: AreaNeed, right: AreaNeed) -> AreaNeed:
    return AreaNeed(
        entry=_union(left.entry, right.entry),
        back=_union(left.back, right.back),
        whole=left.whole or right.whole,
    )
