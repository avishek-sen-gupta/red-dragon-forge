"""Which members an area-need round must walk again, given how the table changed."""

from __future__ import annotations

from collections.abc import Mapping
from itertools import groupby
from operator import itemgetter

from cobble.dataflow.fixpoint.area_table import NO_NEED, AreaTable


def dirtied(
    before: AreaTable,
    after: AreaTable,
    callers_of: Mapping[str, frozenset[str]],
    unresolved: frozenset[str],
) -> frozenset[str]:
    """A member's walk reads three things from the table: the entry rows of the
    programs its call sites reach, its own back row, and -- for a member with a
    call site no definition resolved -- the entry need of every member together.
    So it is walked again exactly when one of those changed."""
    old, new = dict(before.needs), dict(after.needs)
    entered = frozenset(
        member
        for member, need in new.items()
        if old.get(member, NO_NEED).entry != need.entry
    )
    backed = frozenset(
        member
        for member, need in new.items()
        if old.get(member, NO_NEED).back != need.back
    )
    widened = unresolved if before.dynamic != after.dynamic else frozenset()
    return frozenset(
        {caller for member in entered for caller in callers_of.get(member, frozenset())}
        | backed
        | widened
    )


def callers(callees: Mapping[str, frozenset[str]]) -> Mapping[str, frozenset[str]]:
    """Each program, to the members whose call sites can reach it."""
    pairs = sorted(
        {(callee, member) for member, reached in callees.items() for callee in reached}
    )
    return {
        callee: frozenset(member for _, member in group)
        for callee, group in groupby(pairs, itemgetter(0))
    }
