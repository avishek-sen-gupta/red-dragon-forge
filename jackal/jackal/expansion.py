"""expand_procs: a parsed Job with its PROC calls inlined and every step reference looked up, each coordinate resolved or unresolved."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import reduce
from itertools import chain, islice
from pathlib import Path
from typing import Protocol, TypeAlias, TypeVar

from cobol_asg.source_text import decode_source
from jackal.jcl.parser import parse_proc
from jackal.model import (
    DD,
    DSN,
    AllOf,
    Always,
    BackwardRef,
    CalledProcScope,
    DdCoordinate,
    DdName,
    DirectDSN,
    Guard,
    IfBlock,
    InStreamProc,
    Job,
    JobStatement,
    Negated,
    NoDSN,
    NotCoded,
    NotOverridden,
    OwnScope,
    ProcCall,
    ProcCallCoordinate,
    ProcDef,
    ProcRef,
    ProcStepOverrides,
    ProgramStep,
    QualifiedStep,
    RcComparison,
    ResolvedDd,
    ResolvedProc,
    ResolvedProcCall,
    ResolvedProgramStep,
    SetStatement,
    StepLabel,
    StepName,
    StepRef,
    StepReference,
    Substitution,
    TempRef,
    UnexpandedCall,
    UnresolvedDd,
    UnresolvedProc,
    UnresolvedProcCall,
    UnresolvedProgramStep,
)
from jackal.value_parts import Literal, Symbol, SymbolName, Value, ValuePart

logger = logging.getLogger(__name__)

_MAX_TEMP_NAME = 8

T = TypeVar("T")

Run: TypeAlias = tuple[int, ...]
Runs: TypeAlias = tuple[Run, ...]
Coordinates: TypeAlias = tuple[ResolvedProcCall, ...]
Entry: TypeAlias = QualifiedStep | UnexpandedCall


@dataclass(frozen=True)
class ExpandedJob:
    name: str
    steps: tuple[Entry, ...]
    end_job_tests: tuple[RcComparison, ...] = ()


@dataclass(frozen=True)
class ErrorSite:
    coordinates: Coordinates
    step: ProgramStep[StepRef]


@dataclass(frozen=True)
class ForwardReference:
    site: ErrorSite
    ref: StepRef


@dataclass(frozen=True)
class ReferenceToProcCall:
    site: ErrorSite
    ref: StepRef


@dataclass(frozen=True)
class PathThroughProgramStep:
    site: ErrorSite
    ref: StepRef


@dataclass(frozen=True)
class OverrideNamesNoStep:
    call: ProcCall
    step: StepName


@dataclass(frozen=True)
class CircularProc:
    procs: tuple[ProcRef, ...]


JclError: TypeAlias = (
    ForwardReference
    | ReferenceToProcCall
    | PathThroughProgramStep
    | OverrideNamesNoStep
    | CircularProc
)


class ExpansionFailed(Exception):
    def __init__(self, error: JclError) -> None:
        super().__init__(repr(error))
        self.error = error


@dataclass(frozen=True)
class ProcNotFound:
    pass


class ProcLibrary(Protocol):
    def find(self, proc: ProcRef) -> ProcDef | ProcNotFound: ...


@dataclass(frozen=True)
class InStreamProcLibrary(ProcLibrary):
    """An in-stream procedure, found before the library the job had until its PROC statement."""

    proc: ProcDef
    rest: ProcLibrary

    def find(self, proc: ProcRef) -> ProcDef | ProcNotFound:
        if proc.name == self.proc.name:
            return self.proc
        return self.rest.find(proc)


@dataclass(frozen=True)
class DirectoryProcLibrary(ProcLibrary):
    dirs: tuple[Path, ...]

    def find(self, proc: ProcRef) -> ProcDef | ProcNotFound:
        paths = tuple(
            path for d in self.dirs if (path := d / f"{proc.name}.prc").is_file()
        )
        return (
            parse_proc(decode_source(paths[0].read_bytes()))
            if paths
            else ProcNotFound()
        )


def _or_own(override: T | NotOverridden, own: T) -> T:
    match override:
        case NotOverridden():
            return own
        case _:
            return override


def _merged(
    own: Sequence[DD[StepRef]], overrides: Sequence[DD[StepRef]]
) -> tuple[DD[StepRef], ...]:
    by_name = {dd.ddname: dd for dd in overrides}
    own_names = frozenset(dd.ddname for dd in own)
    return (
        *(_overridden(dd, by_name) for dd in own),
        *(_added(dd) for dd in overrides if dd.ddname not in own_names),
    )


def _overridden(
    dd: DD[StepRef], overrides: Mapping[DdName, DD[StepRef]]
) -> DD[StepRef]:
    return dd.overridden_by(overrides[dd.ddname]) if dd.ddname in overrides else dd


def _added(dd: DD[StepRef]) -> DD[StepRef]:
    return DD[StepRef](dd.ddname, NoDSN(), NotCoded()).overridden_by(dd)


@dataclass(frozen=True)
class _NoOverrides:
    def applied(
        self, step: ProgramStep[StepRef], position: Run
    ) -> ProgramStep[StepRef]:
        return step

    def called(self, call: ProcCall) -> ProcCall:
        return call


@dataclass(frozen=True)
class _Overrides:
    call: ProcCall
    first: Run

    def _per_step(self, label: StepLabel) -> ProcStepOverrides:
        return next(
            (o for name, o in self.call.per_step if name == label),
            ProcStepOverrides(),
        )

    def _first_parm(self, own: Value, first: bool) -> Value:
        unqualified = self.call.parm_for_first_step
        match unqualified:
            case NotOverridden():
                return own
            case _:
                return unqualified if first else ()

    def called(self, call: ProcCall) -> ProcCall:
        every = _or_own(self.call.cond_for_every_step, call.cond_for_every_step)
        return replace(call, cond_for_every_step=every)

    def applied(
        self, step: ProgramStep[StepRef], position: Run
    ) -> ProgramStep[StepRef]:
        per = self._per_step(step.label)
        first = position == self.first
        first_dds = self.call.dds_for_first_step if first else ()
        return ProgramStep(
            step.label,
            step.pgm,
            _merged(_merged(step.dds, first_dds), per.dds),
            _or_own(per.cond, _or_own(self.call.cond_for_every_step, step.cond)),
            _or_own(per.parm, self._first_parm(step.parm, first)),
            step.guard,
        )


@dataclass(frozen=True)
class _WrittenGuard:
    guard: Guard[StepRef]
    coordinates: Coordinates
    runs: Runs


@dataclass(frozen=True)
class _Scope:
    coordinates: Coordinates
    runs: Runs
    symbols: Mapping[SymbolName, Value]
    set_symbols: Mapping[SymbolName, Value]
    guards: tuple[_WrittenGuard, ...]
    stack: tuple[ProcRef, ...]
    overrides: _Overrides | _NoOverrides
    library: ProcLibrary
    nested: Mapping[SymbolName, Value]

    def visible(self) -> Mapping[SymbolName, Value]:
        return {**self.nested, **self.set_symbols, **self.symbols}


@dataclass(frozen=True)
class _Placed:
    coordinates: Coordinates
    runs: Runs
    step: ProgramStep[StepRef] | UnexpandedCall
    guards: tuple[_WrittenGuard, ...] = ()


@dataclass(frozen=True)
class _Placement:
    placed: tuple[_Placed, ...]
    scope: _Scope


def _part_value(part: ValuePart, symbols: Mapping[SymbolName, Value]) -> Value:
    match part:
        case Symbol(name=name) if name in symbols:
            rest = {k: v for k, v in symbols.items() if k != name}
            return _substitute(symbols[name], rest)
        case _:
            return (part,)


def _joined(parts: Value, part: ValuePart) -> Value:
    match (parts[-1:], part):
        case ((Literal(text=before),), Literal(text=after)):
            return (*parts[:-1], Literal(before + after))
        case _:
            return (*parts, part)


def _substitute(value: Value, symbols: Mapping[SymbolName, Value]) -> Value:
    spliced = chain.from_iterable(_part_value(p, symbols) for p in value)
    return reduce(_joined, spliced, ())


def _dataset(value: Value) -> DSN[StepRef]:
    match value:
        case (Symbol(name=name),) if len(name.text) <= _MAX_TEMP_NAME:
            return TempRef(name.text)
        case _:
            return DirectDSN(value)


def _substituted_dd(
    dd: DD[StepRef], symbols: Mapping[SymbolName, Value]
) -> DD[StepRef]:
    return dd.substituted(
        Substitution(lambda value: _substitute(value, symbols), _dataset)
    )


def _substituted_override(
    value: Value | NotOverridden, symbols: Mapping[SymbolName, Value]
) -> Value | NotOverridden:
    match value:
        case NotOverridden():
            return value
        case _:
            return _substitute(value, symbols)


def _substituted_step_overrides(
    overrides: ProcStepOverrides, symbols: Mapping[SymbolName, Value]
) -> ProcStepOverrides:
    return ProcStepOverrides(
        overrides.cond,
        _substituted_override(overrides.parm, symbols),
        tuple(_substituted_dd(dd, symbols) for dd in overrides.dds),
    )


def _substituted_call(call: ProcCall, symbols: Mapping[SymbolName, Value]) -> ProcCall:
    return replace(
        call,
        symbol_overrides=tuple(
            (name, _substitute(v, symbols)) for name, v in call.symbol_overrides
        ),
        parm_for_first_step=_substituted_override(call.parm_for_first_step, symbols),
        dds_for_first_step=tuple(
            _substituted_dd(dd, symbols) for dd in call.dds_for_first_step
        ),
        per_step=tuple(
            (name, _substituted_step_overrides(o, symbols)) for name, o in call.per_step
        ),
    )


def _substituted_step(
    step: ProgramStep[StepRef], symbols: Mapping[SymbolName, Value]
) -> ProgramStep[StepRef]:
    return replace(
        step,
        dds=tuple(_substituted_dd(dd, symbols) for dd in step.dds),
        parm=_substitute(step.parm, symbols),
    )


def _combined(guards: Sequence[Guard[StepReference]]) -> Guard[StepReference]:
    if len(guards) > 1:
        return AllOf(tuple(guards))
    return guards[0] if guards else Always()


def _flat(
    statements: Sequence[JobStatement], prefix: Run
) -> tuple[tuple[Run, ProgramStep[StepRef] | ProcCall], ...]:
    return tuple(
        chain.from_iterable(
            _flat_one(s, (*prefix, i)) for i, s in enumerate(statements)
        )
    )


def _flat_one(
    statement: JobStatement, position: Run
) -> tuple[tuple[Run, ProgramStep[StepRef] | ProcCall], ...]:
    match statement:
        case IfBlock(then=then, otherwise=otherwise):
            return (*_flat(then, (*position, 0)), *_flat(otherwise, (*position, 1)))
        case _:
            return _flat_leaf(statement, position)


def _flat_leaf(
    statement: ProgramStep[StepRef] | ProcCall | SetStatement | InStreamProc,
    position: Run,
) -> tuple[tuple[Run, ProgramStep[StepRef] | ProcCall], ...]:
    match statement:
        case SetStatement() | InStreamProc():
            return ()
        case _:
            return ((position, statement),)


def _named_by_overrides(call: ProcCall) -> bool:
    has_parm = not isinstance(call.parm_for_first_step, NotOverridden)
    return has_parm or bool(call.dds_for_first_step)


def _check_first_step(call: ProcCall, first: ProgramStep[StepRef] | ProcCall) -> None:
    if isinstance(first, ProcCall) and _named_by_overrides(call):
        raise ExpansionFailed(
            OverrideNamesNoStep(call, StepName(first.label.rendered()))
        )


def _check_overrides(
    call: ProcCall, steps: Sequence[ProgramStep[StepRef] | ProcCall]
) -> None:
    programs = tuple(s.label for s in steps if isinstance(s, ProgramStep))
    missing = tuple(name for name, _ in call.per_step if name not in programs)
    if missing:
        raise ExpansionFailed(OverrideNamesNoStep(call, missing[0]))
    for first in steps[:1]:
        _check_first_step(call, first)


def _inline(
    call: ProcCall, proc: ProcDef, scope: _Scope, position: Run
) -> tuple[_Placed, ...]:
    if call.proc in scope.stack:
        raise ExpansionFailed(CircularProc((*scope.stack, call.proc)))
    flat = _flat(proc.steps, ())
    _check_overrides(call, tuple(s for _, s in flat))
    resolved_call = _substituted_call(call, scope.visible())
    inner = _Scope(
        (*scope.coordinates, ResolvedProcCall(call, ResolvedProc(proc))),
        (*scope.runs, position),
        {**dict(proc.defaults), **dict(resolved_call.symbol_overrides)},
        {},
        scope.guards,
        (*scope.stack, call.proc),
        _Overrides(scope.overrides.called(resolved_call), flat[0][0] if flat else ()),
        scope.library,
        scope.visible(),
    )
    return _place_all(proc.steps, inner, ()).placed


def _place_call(call: ProcCall, scope: _Scope, position: Run) -> tuple[_Placed, ...]:
    found = scope.library.find(call.proc)
    match found:
        case ProcNotFound():
            here = (
                *scope.coordinates,
                ResolvedProcCall(call, UnresolvedProc(call.proc)),
            )
            unexpanded = UnexpandedCall(here)
            return (_Placed(here, (*scope.runs, position), unexpanded, scope.guards),)
        case _:
            return _inline(call, found, scope, position)


def _place_step(
    statement: ProgramStep[StepRef] | ProcCall, scope: _Scope, position: Run
) -> tuple[_Placed, ...]:
    match statement:
        case ProcCall():
            return _place_call(statement, scope, position)
        case _:
            step = scope.overrides.applied(
                _substituted_step(statement, scope.visible()), position
            )
            return (_Placed(scope.coordinates, scope.runs, step, scope.guards),)


def _place_if(block: IfBlock, scope: _Scope, position: Run) -> _Placement:
    def written(guard: Guard[StepRef], after: _Scope) -> _Scope:
        here = _WrittenGuard(guard, scope.coordinates, scope.runs)
        return replace(
            scope, guards=(*scope.guards, here), set_symbols=after.set_symbols
        )

    then = _place_all(block.then, written(block.condition, scope), (*position, 0))
    otherwise = _place_all(
        block.otherwise,
        written(Negated(block.condition), then.scope),
        (*position, 1),
    )
    return _Placement(
        (*then.placed, *otherwise.placed),
        replace(scope, set_symbols=otherwise.scope.set_symbols),
    )


def _set(statement: SetStatement, scope: _Scope) -> _Scope:
    def assign(
        symbols: Mapping[SymbolName, Value], assignment: tuple[SymbolName, Value]
    ) -> Mapping[SymbolName, Value]:
        name, value = assignment
        return {**symbols, name: _substitute(value, {**symbols, **scope.symbols})}

    return replace(
        scope, set_symbols=reduce(assign, statement.assignments, scope.set_symbols)
    )


def _place_leaf(
    statement: ProgramStep[StepRef] | ProcCall | SetStatement | InStreamProc,
    scope: _Scope,
    position: Run,
) -> _Placement:
    match statement:
        case SetStatement() | InStreamProc():
            return _Placement((), _defined(statement, scope))
        case _:
            return _Placement(_place_step(statement, scope, position), scope)


def _defined(statement: SetStatement | InStreamProc, scope: _Scope) -> _Scope:
    match statement:
        case SetStatement():
            return _set(statement, scope)
        case InStreamProc(proc=proc):
            return replace(scope, library=InStreamProcLibrary(proc, scope.library))


def _place(statement: JobStatement, scope: _Scope, position: Run) -> _Placement:
    match statement:
        case IfBlock():
            return _place_if(statement, scope, position)
        case _:
            return _place_leaf(statement, scope, position)


def _place_all(
    statements: Sequence[JobStatement], scope: _Scope, position: Run
) -> _Placement:
    def next_placement(
        done: _Placement, indexed: tuple[int, JobStatement]
    ) -> _Placement:
        index, statement = indexed
        here = _place(statement, done.scope, (*position, index))
        return _Placement((*done.placed, *here.placed), here.scope)

    return reduce(next_placement, enumerate(statements), _Placement((), scope))


def _procs(coordinates: Coordinates) -> tuple[ProcRef, ...]:
    return tuple(c.call.proc for c in coordinates)


def _is_program(placed: _Placed, scope: Runs, name: StepName) -> bool:
    match placed.step:
        case ProgramStep(label=label):
            return placed.runs == scope and label == name
        case _:
            return False


def _under_call(placed: _Placed, scope: Runs, name: StepName) -> bool:
    depth = len(scope)
    return (
        placed.runs[:depth] == scope
        and len(placed.coordinates) > depth
        and placed.coordinates[depth].call.label == name
    )


def _program(entry: Entry) -> ProgramStep[StepReference]:
    match entry:
        case QualifiedStep(step=step):
            return step
        case UnexpandedCall():
            raise TypeError("a program step's index named an unexpanded call")


@dataclass(frozen=True)
class _Resolver:
    placed: tuple[_Placed, ...]
    done: tuple[Entry, ...]
    at: int
    site_coordinates: Coordinates
    written: Coordinates
    bases: tuple[Runs, ...]
    step: ProgramStep[StepRef]

    def _site(self) -> ErrorSite:
        return ErrorSite(self.site_coordinates, self.step)

    def _rendered_site(self) -> str:
        labels = (*(c.call.label for c in self.site_coordinates), self.step.label)
        return ".".join(label.rendered() for label in labels)

    def _programs(self, scope: Runs, name: StepName) -> tuple[int, ...]:
        return tuple(
            i for i, p in enumerate(self.placed) if _is_program(p, scope, name)
        )

    def _calls(self, scope: Runs, name: StepName) -> tuple[int, ...]:
        return tuple(
            i for i, p in enumerate(self.placed) if _under_call(p, scope, name)
        )

    def _warn_if_reused(self, scope: Runs, name: StepName, index: int) -> None:
        found = self.placed[index].coordinates
        others = tuple(
            p
            for p in self.placed[:index]
            if p.runs != scope
            and len(p.runs) == len(scope)
            and isinstance(p.step, ProgramStep)
            and p.step.label == name
            and _procs(p.coordinates[-1:]) == _procs(found[-1:])
        )
        if scope and others:
            logger.warning(
                "%s names %s, which more than one run of PROC %s has; "
                "resolved to this run (blueprint D6)",
                self._rendered_site(),
                name.text,
                found[-1].call.proc.name,
            )

    def _unresolved(
        self, ref: StepRef, path: tuple[ProcCallCoordinate, ...]
    ) -> StepReference:
        reference = StepReference(path, UnresolvedProgramStep(ref.step))
        logger.warning(
            "%s refers to %s, which is not resolved (blueprint D6)",
            self._rendered_site(),
            reference.rendered(),
        )
        return reference

    def _resolved(self, ref: StepRef, scope: Runs, index: int) -> StepReference:
        self._earlier(ref, index)
        self._warn_if_reused(scope, ref.step, index)
        found = self.placed[index].coordinates
        return StepReference(found, ResolvedProgramStep(_program(self.done[index])))

    def _in_scope(self, ref: StepRef, scope: Runs) -> tuple[StepReference, ...]:
        programs = self._programs(scope, ref.step)
        if programs:
            return (self._resolved(ref, scope, programs[0]),)
        if self._calls(scope, ref.step):
            raise ExpansionFailed(ReferenceToProcCall(self._site(), ref))
        return ()

    def _own(self, ref: StepRef) -> StepReference:
        found = chain.from_iterable(self._in_scope(ref, base) for base in self.bases)
        return self._first(found, ref, self.written)

    def _first(
        self,
        found: Iterable[StepReference],
        ref: StepRef,
        path: tuple[ProcCallCoordinate, ...],
    ) -> StepReference:
        first = tuple(islice(found, 1))
        return first[0] if first else self._unresolved(ref, path)

    def _earlier(self, ref: StepRef, index: int) -> int:
        if index >= self.at:
            raise ExpansionFailed(ForwardReference(self._site(), ref))
        return index

    def _in_call(self, ref: StepRef, base: Runs, index: int) -> StepReference:
        self._earlier(ref, index)
        coordinates = self.placed[index].coordinates[: len(base) + 1]
        run = self.placed[index].runs[: len(base) + 1]
        match coordinates[-1].proc:
            case UnresolvedProc():
                return self._unresolved(ref, coordinates)
            case ResolvedProc():
                return self._first(self._in_scope(ref, run), ref, coordinates)

    def _through(
        self, ref: StepRef, call: StepName, base: Runs
    ) -> tuple[StepReference, ...]:
        calls = self._calls(base, call)
        if calls:
            return (self._in_call(ref, base, calls[0]),)
        if self._programs(base, call):
            raise ExpansionFailed(PathThroughProgramStep(self._site(), ref))
        return ()

    def _called(self, ref: StepRef, call: StepName) -> StepReference:
        found = chain.from_iterable(self._through(ref, call, b) for b in self.bases)
        return self._first(found, ref, (*self.written, UnresolvedProcCall(call)))

    def target(self, ref: StepRef) -> StepReference:
        match ref.scope:
            case CalledProcScope(call=call):
                return self._called(ref, call)
            case OwnScope():
                return self._own(ref)

    def _dd(self, reference: StepReference, ddname: DdName) -> DdCoordinate:
        match reference.target:
            case ResolvedProgramStep(step=step):
                return self._dd_on(step, reference, ddname)
            case UnresolvedProgramStep():
                return UnresolvedDd(ddname)

    def _dd_on(
        self,
        step: ProgramStep[StepReference],
        reference: StepReference,
        ddname: DdName,
    ) -> DdCoordinate:
        dds = tuple(dd for dd in step.dds if dd.ddname == ddname)
        if dds:
            return ResolvedDd(dds[0])
        logger.warning(
            "%s refers to DD %s of %s, which has no such DD (blueprint D6)",
            self._rendered_site(),
            ddname.text,
            reference.rendered(),
        )
        return UnresolvedDd(ddname)

    def backref(self, ref: BackwardRef[StepRef]) -> BackwardRef[StepReference]:
        reference = self.target(ref.step)
        return BackwardRef(reference, self._dd(reference, ref.dd.ddname()))


def _enclosing(runs: Runs) -> tuple[Runs, ...]:
    return tuple(runs[:depth] for depth in range(len(runs), -1, -1))


def _program_qualified(
    placed: tuple[_Placed, ...],
    done: tuple[Entry, ...],
    at: int,
    step: ProgramStep[StepRef],
) -> QualifiedStep:
    entry = placed[at]

    def resolver(written: Coordinates, runs: Runs) -> _Resolver:
        return _Resolver(
            placed, done, at, entry.coordinates, written, _enclosing(runs), step
        )

    own = resolver(entry.coordinates, entry.runs)
    guards = tuple(
        g.guard.mapped(resolver(g.coordinates, g.runs).target) for g in entry.guards
    )
    resolved = step.mapped(own.target, own.backref)
    return QualifiedStep(entry.coordinates, replace(resolved, guard=_combined(guards)))


def _entry(placed: tuple[_Placed, ...], done: tuple[Entry, ...], at: int) -> Entry:
    step = placed[at].step
    match step:
        case UnexpandedCall():
            return step
        case _:
            return _program_qualified(placed, done, at, step)


def _resolved_entries(placed: tuple[_Placed, ...]) -> tuple[Entry, ...]:
    def resolve_next(done: tuple[Entry, ...], at: int) -> tuple[Entry, ...]:
        return (*done, _entry(placed, done, at))

    none: tuple[Entry, ...] = ()
    return reduce(resolve_next, range(len(placed)), none)


def expand_or_fail(job: Job, library: ProcLibrary) -> ExpandedJob:
    scope = _Scope((), (), {}, {}, (), (), _NoOverrides(), library, {})
    placed = _place_all(job.steps, scope, ()).placed
    return ExpandedJob(job.name, _resolved_entries(placed), job.end_job_tests)


def expand_procs(job: Job, library: ProcLibrary) -> ExpandedJob | JclError:
    try:
        return expand_or_fail(job, library)
    except ExpansionFailed as failure:
        return failure.error
