"""Online programs as one conversation: each task entered with the commarea the task before it handed over, through combine's links."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import z3
from cobble.dataflow.combine.link_row import LinkRow
from cobble.dataflow.fields.extent_text import ByteRange, byte_range
from cobble.experimental.horn.context import top
from cobble.experimental.horn.every_test import EVERY_TEST
from cobble.experimental.horn.kept_tests import KeptTests
from cobble.experimental.horn.lower import (
    HornSystem,
    Lowering,
    body_rules,
    lowering_of,
    points_of,
    relations_of,
    sorts,
)
from cobble.experimental.horn.point import Point
from cobble.experimental.horn.program import Program
from cobble.experimental.horn.storage import (
    CALEN_BYTES,
    Place,
    Storage,
    storage_of,
)
from cobble.experimental.horn.terms import bits, concat, constant, every, holds
from cobol_memory.region_id import RegionId

TRANSFERS = frozenset({"XCTL", "RETURN_TRANSID"})
NO_WATCHED: Mapping[str, Sequence[str]] = MappingProxyType({})
COLD = 0


@dataclass(frozen=True)
class Window:
    """One link's bytes: the caller's it hands over and the callee's they become."""

    link: LinkRow
    caller: ByteRange
    callee: ByteRange

    def handed(self, region: RegionId, offset: int) -> tuple[Place, ...]:
        """The caller's byte that lands at the callee's ``offset``, if any."""
        callee, caller = self.callee, self.caller
        if region.value != callee.region or not callee.start <= offset < callee.end:
            return ()
        byte = caller.start + offset - callee.start
        return ((RegionId(caller.region), byte),) if byte < caller.end else ()


def _window(link: LinkRow) -> tuple[Window, ...]:
    caller = byte_range(link.caller_extent, link.caller)
    callee = byte_range(link.callee_extent, link.callee)
    if not (caller.known and callee.known and caller.exact and callee.exact):
        return ()
    return (Window(link, caller, callee),)


def _carried(storage: Storage) -> tuple[int, ...]:
    """The state a task is entered with: LINKAGE, EIBCALEN and the marks."""
    linkage = tuple(
        n
        for n, segment in enumerate(storage.segments)
        if segment.region is RegionId.LINKAGE
    )
    return (*linkage, *range(len(storage.segments), len(storage.widths)))


def _fed(window: Window, callee: Storage) -> frozenset[Place]:
    return frozenset(
        place
        for segment in callee.segments
        for offset in range(segment.start, segment.end)
        for place in window.handed(segment.region, offset)
    )


def _storages(
    programs: Mapping[str, Program],
    windows: Sequence[Window],
    watched: Mapping[str, Sequence[str]],
    marks: Sequence[Point],
    extra: Mapping[str, frozenset[Place]],
    kept: KeptTests,
) -> Mapping[str, Storage]:
    """Each program's storage, following too the bytes it hands to the tasks after
    it that those tasks follow, until no program follows another byte."""
    storages = {
        name: storage_of(
            program,
            watched.get(name, ()),
            marks,
            extra.get(name, frozenset()),
            kept,
        )
        for name, program in programs.items()
    }
    wanted = {
        name: frozenset(
            place
            for window in windows
            if window.link.caller == name
            for place in _fed(window, storages[window.link.callee])
        )
        | extra.get(name, frozenset())
        for name in programs
    }
    if wanted == {name: extra.get(name, frozenset()) for name in programs}:
        return storages
    return _storages(programs, windows, watched, marks, wanted, kept)


@dataclass(frozen=True)
class Tasks:
    """Each program's lowering and the relation a task of it is entered through."""

    lowerings: Mapping[str, Lowering]
    entered: Mapping[str, z3.FuncDeclRef]

    def enter(self, name: str, state: Sequence[z3.BitVecRef]) -> z3.BoolRef:
        return holds(self.entered[name], *state)


def _entered(name: str, storage: Storage) -> z3.FuncDeclRef:
    widths = tuple(storage.widths[n] for n in _carried(storage))
    return z3.Function(f"{name}:task", *sorts(widths), z3.BoolSort())


def _opened(tasks: Tasks, name: str, tag: str, calen: int) -> z3.BoolRef:
    """A task entered with nothing known but EIBCALEN."""
    storage = tasks.lowerings[name].storage
    base = len(storage.segments)
    calens = (base,) if storage.eib else ()
    fresh = {
        n: bits(f"{tag}!{n}", storage.widths[n])
        for n in _carried(storage)
        if n not in calens
    }
    state = tuple(
        fresh[n] if n in fresh else constant(calen.to_bytes(CALEN_BYTES, "big"))
        for n in _carried(storage)
    )
    return every(tuple(fresh.values()), tasks.enter(name, state))


def _byte(
    window: Window, caller: Lowering, tag: str, region: RegionId, offset: int
) -> tuple[z3.BitVecRef, tuple[z3.BitVecRef, ...]]:
    found = tuple(
        (place, n)
        for place in window.handed(region, offset)
        for n in (caller.storage.placed(*place),)
        if n >= 0
    )
    if not found:
        fresh = bits(f"{tag}!{offset}", 1)
        return (fresh, (fresh,))
    (_, byte), n = found[0]
    segment = caller.storage.segments[n]
    return (segment.slice(byte, byte + 1, caller.vars.now[n]), ())


def _handed(
    window: Window, tasks: Tasks, tag: str
) -> tuple[tuple[z3.BitVecRef, ...], tuple[z3.BitVecRef, ...]]:
    """The callee's carried state as the caller hands it over: its bytes where
    the window holds them, the window's length as EIBCALEN, the caller's marks."""
    caller = tasks.lowerings[window.link.caller]
    callee = tasks.lowerings[window.link.callee].storage
    pieces = tuple(
        _carried_slot(window, caller, callee, tag, n) for n in _carried(callee)
    )
    return (
        tuple(term for term, _ in pieces),
        tuple(fresh for _, made in pieces for fresh in made),
    )


def _carried_slot(
    window: Window, caller: Lowering, callee: Storage, tag: str, n: int
) -> tuple[z3.BitVecRef, tuple[z3.BitVecRef, ...]]:
    base = len(callee.segments)
    if n < base:
        segment = callee.segments[n]
        found = tuple(
            _byte(window, caller, f"{tag}!{n}", segment.region, offset)
            for offset in range(segment.start, segment.end)
        )
        return (concat(*(t for t, _ in found)), tuple(f for _, m in found for f in m))
    if callee.eib and n == base:
        return (constant(window.callee.length.to_bytes(CALEN_BYTES, "big")), ())
    mark = callee.marks[n - base - int(callee.eib)]
    return (caller.storage.mark(mark, caller.vars.now), ())


def _chained(tasks: Tasks, window: Window, index: int) -> tuple[z3.BoolRef, ...]:
    caller = tasks.lowerings[window.link.caller]
    point = Point(window.link.caller, window.link.node)
    state, fresh = _handed(window, tasks, f"h!{index}")
    v = caller.vars
    return tuple(
        every(
            (*v.entry, *v.now, *fresh),
            z3.Implies(
                holds(relation, *_arguments(relation, v.entry, v.now)),
                tasks.enter(window.link.callee, state),
            ),
        )
        for relation in points_of(caller).get(point, ())
    )


def _arguments(
    relation: z3.FuncDeclRef,
    entry: Sequence[z3.BitVecRef],
    now: Sequence[z3.BitVecRef],
) -> tuple[z3.BitVecRef, ...]:
    return (*entry, *now) if relation.arity() > len(now) else tuple(now)


def _started(tasks: Tasks, name: str) -> z3.BoolRef:
    """A task begins with working storage as its VALUE clauses set it, and the
    rest as it was entered with."""
    lowering = tasks.lowerings[name]
    storage, program = lowering.storage, lowering.program
    carried = _carried(storage)
    entered = tuple(bits(f"k!{n}", storage.widths[n]) for n in carried)
    given = dict(zip(carried, entered, strict=True))
    pieces = tuple(
        _initial(program, storage, n) if n not in given else (given[n], ())
        for n in range(len(storage.widths))
    )
    state = tuple(term for term, _ in pieces)
    fresh = tuple(f for _, made in pieces for f in made)
    cfg = program.cfg
    head = lowering.at(top(cfg), cfg.entry, state, state)
    return every((*entered, *fresh), z3.Implies(tasks.enter(name, entered), head))


def _initial(
    program: Program, storage: Storage, n: int
) -> tuple[z3.BitVecRef, tuple[z3.BitVecRef, ...]]:
    segment = storage.segments[n]
    found = tuple(
        _value_byte(program, segment.region, offset, f"w!{n}!{offset}")
        for offset in range(segment.start, segment.end)
    )
    return (concat(*(t for t, _ in found)), tuple(f for _, m in found for f in m))


def _value_byte(
    program: Program, region: RegionId, offset: int, tag: str
) -> tuple[z3.BitVecRef, tuple[z3.BitVecRef, ...]]:
    byte = program.initial(region, offset) if region is RegionId.WORKING_STORAGE else -1
    if byte >= 0:
        return (constant(bytes((byte,))), ())
    fresh = bits(tag, 1)
    return (fresh, (fresh,))


def converse(
    programs: Sequence[Program],
    links: Sequence[LinkRow],
    watched: Mapping[str, Sequence[str]] = NO_WATCHED,
    marks: Sequence[Point] = (),
    kept: KeptTests = EVERY_TEST,
) -> HornSystem:
    """Any of ``programs`` may start a conversation with no commarea, EIBCALEN
    0; an XCTL or RETURN TRANSID among them hands its commarea on, EIBCALEN its
    length; one into them from any other program hands over bytes nothing knows.
    A mark is unknown wherever the chain of commareas begins. ``kept`` says
    which tests every program keeps."""
    named = {program.cfg.program: program for program in programs}
    windows = tuple(
        window
        for link in links
        if link.transfer in TRANSFERS and link.callee in named
        for window in _window(link)
    )
    inner = tuple(w for w in windows if w.link.caller in named)
    outer = tuple(w for w in windows if w.link.caller not in named)
    storages = _storages(named, inner, watched, marks, {}, kept)
    lowerings = {name: lowering_of(named[name], storages[name]) for name in named}
    tasks = Tasks(lowerings, {name: _entered(name, storages[name]) for name in named})
    rules = (
        *(_opened(tasks, name, f"c!{name}", COLD) for name in named),
        *(
            _opened(tasks, w.link.callee, f"o!{n}", w.callee.length)
            for n, w in enumerate(outer)
        ),
        *(rule for n, w in enumerate(inner) for rule in _chained(tasks, w, n)),
        *(_started(tasks, name) for name in named),
        *(rule for lowering in lowerings.values() for rule in body_rules(lowering)),
    )
    return HornSystem(
        rules,
        (
            *tasks.entered.values(),
            *(r for lowering in lowerings.values() for r in relations_of(lowering)),
        ),
        {
            point: relations
            for lowering in lowerings.values()
            for point, relations in points_of(lowering).items()
        },
        storages,
    )
