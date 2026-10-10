"""expand_procs: a parsed Job with its PROC calls inlined and every step reference resolved to the QualifiedStep it names."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import reduce
from itertools import chain
from pathlib import Path
from typing import Protocol, TypeAlias, TypeVar

from jackal.dsn import DSN, BackwardRef, DdName, DirectDSN, TempRef
from jackal.jcl.parser import parse_proc
from jackal.model import (
    DD,
    AllOf,
    Always,
    CalledProcScope,
    Guard,
    IfBlock,
    Job,
    JobStatement,
    Negated,
    NotOverridden,
    OwnScope,
    ProcCall,
    ProcDef,
    ProcRef,
    ProcStepOverrides,
    ProgramStep,
    RcComparison,
    StepLabel,
    StepName,
    StepRef,
    Unnamed,
)
from jackal.model import (
    QualifiedStep as QualifiedStep,
)
from jackal.model import (
    UnresolvedProcCall as UnresolvedProcCall,
)
from jackal.value_parts import Literal, Symbol, SymbolName, Value, ValuePart

logger = logging.getLogger(__name__)

_MAX_TEMP_NAME = 8

T = TypeVar("T")

Run: TypeAlias = tuple[int, ...]
Runs: TypeAlias = tuple[Run, ...]


@dataclass(frozen=True)
class ExpandedJob:
    name: str
    steps: tuple[QualifiedStep, ...]
    end_job_tests: tuple[RcComparison, ...] = ()


@dataclass(frozen=True)
class ErrorSite:
    calls: tuple[ProcCall, ...]
    step: ProgramStep[StepRef]


@dataclass(frozen=True)
class DanglingReference:
    site: ErrorSite
    ref: StepRef


@dataclass(frozen=True)
class DanglingDdReference:
    site: ErrorSite
    ref: StepRef
    ddname: DdName


@dataclass(frozen=True)
class ForwardReference:
    site: ErrorSite
    ref: StepRef


@dataclass(frozen=True)
class ReferenceToProcCall:
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
    DanglingReference
    | DanglingDdReference
    | ForwardReference
    | ReferenceToProcCall
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
class DirectoryProcLibrary(ProcLibrary):
    dirs: tuple[Path, ...]

    def find(self, proc: ProcRef) -> ProcDef | ProcNotFound:
        paths = tuple(
            path for d in self.dirs if (path := d / f"{proc.name}.prc").is_file()
        )
        return parse_proc(paths[0].read_text()) if paths else ProcNotFound()


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
        *(by_name.get(dd.ddname, dd) for dd in own),
        *(dd for dd in overrides if dd.ddname not in own_names),
    )


@dataclass(frozen=True)
class _NoOverrides:
    def applied(self, step: ProgramStep[StepRef]) -> ProgramStep[StepRef]:
        return step


@dataclass(frozen=True)
class _Overrides:
    call: ProcCall
    first: StepLabel

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

    def applied(self, step: ProgramStep[StepRef]) -> ProgramStep[StepRef]:
        per = self._per_step(step.label)
        first = step.label == self.first
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
class _Scope:
    calls: tuple[ProcCall, ...]
    runs: Runs
    symbols: Mapping[SymbolName, Value]
    guard: Guard[StepRef]
    stack: tuple[ProcRef, ...]
    overrides: _Overrides | _NoOverrides
    library: ProcLibrary


@dataclass(frozen=True)
class _Placed:
    calls: tuple[ProcCall, ...]
    runs: Runs
    step: ProgramStep[StepRef] | UnresolvedProcCall


def _part_value(part: ValuePart, symbols: Mapping[SymbolName, Value]) -> Value:
    match part:
        case Symbol(name=name) if name in symbols:
            return symbols[name]
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
    return dd.substituted(lambda name: _dataset(_substitute(name, symbols)))


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


def _and(outer: Guard[StepRef], guard: Guard[StepRef]) -> Guard[StepRef]:
    match outer:
        case AllOf(guards=guards):
            return AllOf((*guards, guard))
        case _:
            return AllOf((outer, guard))


def _conjoined(outer: Guard[StepRef], guard: Guard[StepRef]) -> Guard[StepRef]:
    match outer:
        case Always():
            return guard
        case _:
            return _and(outer, guard)


def _labels(statements: Sequence[JobStatement]) -> tuple[StepLabel, ...]:
    return tuple(chain.from_iterable(_statement_labels(s) for s in statements))


def _statement_labels(statement: JobStatement) -> tuple[StepLabel, ...]:
    match statement:
        case IfBlock(then=then, otherwise=otherwise):
            return _labels((*then, *otherwise))
        case _:
            return (statement.label,)


def _check_overrides(call: ProcCall, labels: Sequence[StepLabel]) -> None:
    missing = tuple(name for name, _ in call.per_step if name not in labels)
    if missing:
        raise ExpansionFailed(OverrideNamesNoStep(call, missing[0]))


def _inline(
    call: ProcCall, proc: ProcDef, scope: _Scope, position: Run
) -> tuple[_Placed, ...]:
    if call.proc in scope.stack:
        raise ExpansionFailed(CircularProc((*scope.stack, call.proc)))
    labels = _labels(proc.steps)
    _check_overrides(call, labels)
    resolved_call = _substituted_call(call, scope.symbols)
    inner = _Scope(
        (*scope.calls, call),
        (*scope.runs, position),
        {**dict(proc.defaults), **dict(resolved_call.symbol_overrides)},
        scope.guard,
        (*scope.stack, call.proc),
        _Overrides(resolved_call, labels[0] if labels else Unnamed()),
        scope.library,
    )
    return _place_all(proc.steps, inner, ())


def _place_call(call: ProcCall, scope: _Scope, position: Run) -> tuple[_Placed, ...]:
    found = scope.library.find(call.proc)
    match found:
        case ProcNotFound():
            return (_Placed(scope.calls, scope.runs, UnresolvedProcCall(call)),)
        case _:
            return _inline(call, found, scope, position)


def _place_step(
    statement: ProgramStep[StepRef] | ProcCall, scope: _Scope, position: Run
) -> tuple[_Placed, ...]:
    match statement:
        case ProcCall():
            return _place_call(statement, scope, position)
        case _:
            step = scope.overrides.applied(_substituted_step(statement, scope.symbols))
            return (_Placed(scope.calls, scope.runs, replace(step, guard=scope.guard)),)


def _place_if(block: IfBlock, scope: _Scope, position: Run) -> tuple[_Placed, ...]:
    then = replace(scope, guard=_conjoined(scope.guard, block.condition))
    otherwise = replace(scope, guard=_conjoined(scope.guard, Negated(block.condition)))
    return (
        *_place_all(block.then, then, (*position, 0)),
        *_place_all(block.otherwise, otherwise, (*position, 1)),
    )


def _place(
    statement: JobStatement, scope: _Scope, position: Run
) -> tuple[_Placed, ...]:
    match statement:
        case IfBlock():
            return _place_if(statement, scope, position)
        case _:
            return _place_step(statement, scope, position)


def _place_all(
    statements: Sequence[JobStatement], scope: _Scope, position: Run
) -> tuple[_Placed, ...]:
    return tuple(
        chain.from_iterable(
            _place(s, scope, (*position, i)) for i, s in enumerate(statements)
        )
    )


def _procs(calls: Sequence[ProcCall]) -> tuple[ProcRef, ...]:
    return tuple(c.proc for c in calls)


def _in_run(placed: _Placed, scope: Runs, name: StepName) -> bool:
    return placed.runs == scope and placed.step.step_label() == name


def _under_call(placed: _Placed, scope: Runs, name: StepName) -> bool:
    depth = len(scope)
    return (
        placed.runs[:depth] == scope
        and len(placed.calls) > depth
        and placed.calls[depth].label == name
    )


def _call_scopes(
    placed: Sequence[_Placed], base: Runs, call: StepName
) -> tuple[Runs, ...]:
    runs = tuple(p.runs[len(base)] for p in placed if _under_call(p, base, call))
    return ((*base, runs[0]),) if runs else ()


@dataclass(frozen=True)
class _Resolver:
    placed: tuple[_Placed, ...]
    done: tuple[QualifiedStep, ...]
    at: int
    calls: tuple[ProcCall, ...]
    runs: Runs
    step: ProgramStep[StepRef]

    def _site(self) -> ErrorSite:
        return ErrorSite(self.calls, self.step)

    def _bases(self) -> tuple[Runs, ...]:
        return (self.runs, ()) if self.runs else ((),)

    def _scopes(self, ref: StepRef) -> tuple[Runs, ...]:
        match ref.scope:
            case CalledProcScope(call=call):
                return tuple(
                    chain.from_iterable(
                        _call_scopes(self.placed, base, call) for base in self._bases()
                    )
                )
            case OwnScope():
                return self._bases()

    def _programs(self, scope: Runs, name: StepName) -> tuple[int, ...]:
        return tuple(
            i
            for i, p in enumerate(self.placed)
            if _in_run(p, scope, name) and p.step.runs_program()
        )

    def _names_a_call(self, scope: Runs, name: StepName) -> bool:
        return any(
            _under_call(p, scope, name) or _in_run(p, scope, name) for p in self.placed
        )

    def _warn_if_reused(self, scope: Runs, name: StepName, index: int) -> None:
        others = tuple(
            p
            for p in self.placed[:index]
            if p.runs != scope
            and len(p.runs) == len(scope)
            and p.step.step_label() == name
            and _procs(p.calls[-1:]) == _procs(self.calls[-1:])
        )
        if scope and others:
            logger.warning(
                "%s names %s, which more than one run of PROC %s has; "
                "resolved to this run (blueprint D6)",
                ".".join(
                    label.rendered()
                    for label in (*(c.label for c in self.calls), self.step.label)
                ),
                name.text,
                self.calls[-1].proc.name,
            )

    def _found(self, ref: StepRef, scope: Runs, index: int) -> int:
        if index >= self.at:
            raise ExpansionFailed(ForwardReference(self._site(), ref))
        self._warn_if_reused(scope, ref.step, index)
        return index

    def _index_in(self, ref: StepRef, scopes: Sequence[Runs]) -> int:
        hits = tuple((scope, self._programs(scope, ref.step)) for scope in scopes)
        found = tuple((scope, indices[0]) for scope, indices in hits if indices)
        if found:
            return self._found(ref, *found[0])
        if any(self._names_a_call(scope, ref.step) for scope in scopes):
            raise ExpansionFailed(ReferenceToProcCall(self._site(), ref))
        raise ExpansionFailed(DanglingReference(self._site(), ref))

    def target(self, ref: StepRef) -> QualifiedStep:
        return self.done[self._index_in(ref, self._scopes(ref))]

    def backref(self, ref: BackwardRef[StepRef]) -> BackwardRef[QualifiedStep]:
        step = self.target(ref.step)
        if ref.ddname not in step.step.dd_names():
            raise ExpansionFailed(
                DanglingDdReference(self._site(), ref.step, ref.ddname)
            )
        return BackwardRef(step, ref.ddname)


def _qualified(
    placed: tuple[_Placed, ...], done: tuple[QualifiedStep, ...], at: int
) -> QualifiedStep:
    entry = placed[at]
    match entry.step:
        case UnresolvedProcCall():
            return QualifiedStep(entry.calls, entry.step)
        case _:
            resolver = _Resolver(placed, done, at, entry.calls, entry.runs, entry.step)
            return QualifiedStep(
                entry.calls, entry.step.mapped(resolver.target, resolver.backref)
            )


def _resolved(placed: tuple[_Placed, ...]) -> tuple[QualifiedStep, ...]:
    def resolve_next(
        done: tuple[QualifiedStep, ...], at: int
    ) -> tuple[QualifiedStep, ...]:
        return (*done, _qualified(placed, done, at))

    none: tuple[QualifiedStep, ...] = ()
    return reduce(resolve_next, range(len(placed)), none)


def expand_or_fail(job: Job, library: ProcLibrary) -> ExpandedJob:
    scope = _Scope((), (), {}, Always(), (), _NoOverrides(), library)
    placed = _place_all(job.steps, scope, ())
    return ExpandedJob(job.name, _resolved(placed), job.end_job_tests)


def expand_procs(job: Job, library: ProcLibrary) -> ExpandedJob | JclError:
    try:
        return expand_or_fail(job, library)
    except ExpansionFailed as failure:
        return failure.error
