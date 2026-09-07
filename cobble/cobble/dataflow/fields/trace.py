"""One concrete path at a time, with a real byte store and no join anywhere.

The fixpoint next door answers "could these bytes flow" over every path at once,
which costs it two things a path gets for free. A PERFORMed paragraph returns to
every caller, because ``srccfg/build.py`` lowers it once and gives it one RETURN
edge per site; on a path the stack says which site is yours. And a call is a
wall, because ``transfer`` credits a commarea to ``%CALL:<name>`` and knows
nothing of the callee; on a path a LINK is a step into the callee, and the
write-back needs no mechanism at all -- in a byte-addressable model the two sides
are the same storage.

What it gives up is soundness in the other direction. Every dependency here was
witnessed by an actual path, and absence means "not sampled", never "does not
exist". The two walks answer different questions and this one replaces nothing.

The store is keyed by program OUTSIDE the extent, because ``RegionId`` is an enum
of six DATA DIVISION sections and carries no program: two members'
``WORKING_STORAGE@100`` are the same ``FieldExtent``, and ``may_alias`` would
conflate them. Slicing by program keeps every may_alias/must_cover comparison
inside one program's storage, where those predicates are sound, and needs no
change to ``cobol_memory``, which is vendored.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from cobble.dataflow.fields.aliases import NO_EXTENT
from cobble.dataflow.fields.extent_text import byte_range
from cobble.dataflow.fields.side_tables import CommareaAlias
from cobble.dataflow.fields.state import State
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId

DEFAULT_PATHS = 200
DEFAULT_COVERAGE = 1.0
DEFAULT_MAX_DEPTH = 5000


@dataclass(frozen=True)
class Budget:
    """When to stop sampling, and how long one path may be.

    ``max_depth`` is a cost bound, not a correctness one: the re-entry rule
    already makes every path finite, but a program with thousands of paragraphs
    reachable in sequence can still make one path long enough to be useless.
    """

    paths: int = DEFAULT_PATHS
    coverage: float = DEFAULT_COVERAGE
    max_depth: int = DEFAULT_MAX_DEPTH


DEFAULT_BUDGET = Budget()


@dataclass(frozen=True)
class Window:
    """A commarea's two ends: the caller's bytes and the callee's, same length.

    ``known`` False is a call site with no window to bind -- a dynamic target, a
    callee absent from the cache, an operand naming no field. A sentinel rather
    than an absent value, so a caller compares windows the same way everywhere.
    """

    caller: str = ""
    caller_extent: FieldExtent = NO_EXTENT
    callee_extent: FieldExtent = NO_EXTENT
    known: bool = False


NO_WINDOW = Window()


@dataclass(frozen=True)
class Dep:
    """One statement's write, one source of it, and where that source was defined.

    ``origin`` is non-empty exactly when the source is not storage, and
    ``definers`` is then empty -- nothing in any program wrote a literal or a file
    record. ``definers`` are program-qualified node ids, which is what lets a
    definer that crossed a call name the member it is in. ``via`` is the call site
    this program was entered through, innermost when nested, and empty in the
    program the trace started from.
    """

    program: str
    node: str
    target: FieldExtent
    origin: str
    source: FieldExtent
    definers: tuple[str, ...]
    via: str


@dataclass(frozen=True)
class DeadEnd:
    """A call site a sampled path arrived at and could not cross.

    Its own stream rather than a field on ``Dep``, because there is no write to
    hang it on: the path did not enter the callee, so nothing was witnessed there.
    """

    program: str
    node: str
    transfer: str
    callee: str
    reason: str


@dataclass(frozen=True)
class Coverage:
    """Branch edges taken, against every branch edge in the programs entered.

    The denominator comes from the ``Cfg``s, never from what the walk produced:
    the 3ao post-mortem found an acceptance suite passing while its walk reached
    18% of nodes, because the denominator was derived from the answer.
    """

    taken: frozenset[tuple[str, str, str]] = frozenset()
    total: int = 0
    programs: frozenset[str] = frozenset()

    @property
    def fraction(self) -> float:
        """One, not zero, for a program with no branches: there is nothing left to
        sample, so a target of 1.0 is met rather than unreachable."""
        return len(self.taken) / self.total if self.total else 1.0


@dataclass(frozen=True)
class Trace:
    """Everything the sampled paths witnessed, deduplicated.

    No path ids. The report is the union over paths, and an id would only label a
    route the report does not print.
    """

    deps: frozenset[Dep] = frozenset()
    dead_ends: frozenset[DeadEnd] = frozenset()
    paths: int = 0
    coverage: Coverage = Coverage()


def _extent_at(text: str, program: str) -> FieldExtent:
    """The artefact's wire form back to an extent, or a length of nothing.

    ``FieldExtent.__str__`` spells the region as ``RegionId``'s own value, so the
    enum constructor is the way back and there is no mapping to keep in step.
    """
    found = byte_range(text, program)
    if not found.known:
        return NO_EXTENT
    return FieldExtent(
        region=RegionId(found.region),
        start=found.start,
        length=found.length,
        precision=Precision.EXACT if found.exact else Precision.CLAMPED,
        field_name=found.name,
    )


def _window(row: CommareaAlias, callee: str) -> Window:
    """The two ends of one site's shared storage, or NO_WINDOW.

    A zero-length end is not a narrow window, it is no window: overlap needs
    ``start < other.end``, so nothing can ever be bound through ``[n:n]``.
    """
    caller = _extent_at(row.caller_extent, row.caller)
    landed = _extent_at(row.callee_extent, callee)
    if not caller.length or not landed.length:
        return NO_WINDOW
    return Window(
        caller=row.caller, caller_extent=caller, callee_extent=landed, known=True
    )


def _rebased(
    extent: FieldExtent, source: FieldExtent, target: FieldExtent
) -> FieldExtent:
    """``extent``'s overlap with ``source``, at the same offset inside ``target``.

    Clipped to the window, because the bytes outside it are not shared storage and
    a rebase that kept them would claim the callee addresses the caller's whole
    record. Named for ``target``: spelling the caller's field name inside the
    callee's region names a field that is not declared there.
    """
    start = max(extent.start, source.start)
    end = min(extent.end, source.end)
    return replace(
        extent,
        region=target.region,
        start=target.start + start - source.start,
        length=end - start,
        field_name=target.field_name,
    )


def _seeded(held: State, source: FieldExtent, target: FieldExtent) -> State:
    """Every extent overlapping ``source``, rebased onto ``target``, provenance kept.

    A binding, not a flow: caller byte ``source.start + k`` *is* callee byte
    ``target.start + k``, so the sources carry across unchanged and no node is
    credited with a write.

    Unioned by rebased extent rather than built as a comprehension over it, because
    two distinct extents can clip to the same shared range -- a record and a
    redefinition of it -- and a comprehension keyed on the result would drop one of
    them silently.
    """
    bound = tuple(
        (_rebased(extent, source, target), sources)
        for extent, sources in held.items()
        if extent.may_alias(source)
    )
    keys = tuple(dict.fromkeys(extent for extent, _ in bound))
    return {
        key: frozenset(
            one for extent, sources in bound if extent == key for one in sources
        )
        for key in keys
    }
