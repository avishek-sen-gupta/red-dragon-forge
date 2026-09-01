"""expand_procs() — resolve and inline JCL EXEC PROC= calls: symbol
substitution, DD-qualified overriding, recursive nesting. Parses everything
(the outer job's already-parsed Step, and each referenced .prc file) through
the real jcl-bridge grammar — never a bespoke text scanner. See
jackal/docs/superpowers/specs/2026-07-08-jcl-proc-expansion-design.md.

SET statements are not supported (forge-6qr) — verified absent from every
real PROC in the CardDemo corpus.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from itertools import chain
from pathlib import Path

from jackal.dsn import DSN, DirectDSN, TempRef, temp_if_unresolved
from cobble.jackal.jcl.parser import parse_proc
from jackal.model import DD, Job, ProcDef, Step
from jackal.value_parts import Symbol, Value, ValuePart


class ProcExpansionError(Exception):
    """Raised when PROC resolution/inlining fails: PROC not found, an
    unbound symbol, or a circular PROC reference."""


def _proc_paths(name: str, proclib_dirs: Sequence[Path]) -> tuple[Path, ...]:
    """Every .prc file carrying this name, in proclib order.

    Empty when no proclib has one, which is how a step whose pgm is a program
    rather than a PROC call is told apart — a tuple rather than an optional
    path, so the "no such PROC" case is a length and not a None.
    """
    return tuple(
        candidate
        for proclib_dir in proclib_dirs
        if (candidate := proclib_dir / f"{name}.prc").is_file()
    )


# ── Symbol substitution ───────────────────────────────────────────


def _substitute_symbol(name: str, symbols: Mapping[str, Value]) -> Value:
    """The parts a symbol stands for — an error when nothing binds it, because
    a PROC parameter the caller never passed has no value to stand in."""
    if name not in symbols:
        raise ProcExpansionError(f"Unbound symbol '&{name}'")
    return symbols[name]


def _substitute_part(part: ValuePart, symbols: Mapping[str, Value]) -> Value:
    """One value part, as the parts it stands for once symbols are known."""
    if isinstance(part, Symbol):
        return _substitute_symbol(part.name, symbols)
    return (part,)


def _substitute(value: Value, symbols: Mapping[str, Value]) -> Value:
    """A value with every symbol replaced by the parts bound to it.

    Substitution splices, it does not re-join: ``&HLQ..DATA`` with HLQ=TEST
    stays two literals worth one name, which ``resolve`` reads as TEST.DATA.
    """
    return tuple(chain.from_iterable(_substitute_part(p, symbols) for p in value))


def _lone_unbound_symbol_dsn(name: Value, symbols: Mapping[str, Value]) -> DSN:
    """``temp_if_unresolved``'s reading of a DSN that is one symbol nothing
    binds, and the DSN unchanged for anything else."""
    match name:
        case (Symbol(name=n),) if n not in symbols:
            return temp_if_unresolved(DirectDSN(name))
        case _:
            return DirectDSN(name)


def _substitute_dsn(name: Value, symbols: Mapping[str, Value]) -> DSN:
    """The DSN a DD names once the PROC's symbols are known.

    One exception to plain substitution: a DSN that is a whole lone symbol
    nothing binds is the temporary dataset z/OS reads ``DSN=&NAME`` as, inside
    a PROC exactly as outside one — the same reading
    :func:`jackal.dsn.temp_if_unresolved` gives a job-level DD. Anything
    else unbound stays the error it is: a symbol too long to be a temp name, or
    one glued to literal text, is a parameter the caller forgot to pass, and
    reading it as a work file would invent a dataset.
    """
    temp = _lone_unbound_symbol_dsn(name, symbols)
    if isinstance(temp, TempRef):
        return temp
    return DirectDSN(_substitute(name, symbols))


def _substitute_dd(dd: DD, symbols: Mapping[str, Value]) -> DD:
    """Only a DirectDSN carries symbols; every other DSN passes through."""
    if isinstance(dd.dsn, DirectDSN):
        return replace(dd, dsn=_substitute_dsn(dd.dsn.name, symbols))
    return dd


# ── DD overriding ─────────────────────────────────────────────────


def _qualified_override(dd: DD, inner_name: str) -> tuple[tuple[str, DD], ...]:
    """A stepname.ddname override, keyed by the inner ddname it replaces —
    nothing, when it names a different step."""
    qualifier, real_ddname = dd.ddname.split(".", 1)
    if qualifier != inner_name:
        return ()
    return ((real_ddname, replace(dd, ddname=real_ddname)),)


def _override_for(
    dd: DD, inner_name: str, single_step: bool
) -> tuple[tuple[str, DD], ...]:
    """This outer DD as an override of one inner DD, or nothing at all.

    An unqualified override is only unambiguous when the PROC has a single
    step; with more there is no telling which step it meant.
    """
    if "." in dd.ddname:
        return _qualified_override(dd, inner_name)
    return ((dd.ddname, dd),) if single_step else ()


def _overrides(
    inner_step: Step, outer_dds: Sequence[DD], single_step: bool
) -> Mapping[str, DD]:
    """The outer step's overrides that apply to this inner step, keyed by the
    inner ddname, the last of two overrides of one ddname winning."""
    return dict(
        chain.from_iterable(
            _override_for(dd, inner_step.name, single_step) for dd in outer_dds
        )
    )


def _merged_dds(inner_dds: Sequence[DD], overrides: Mapping[str, DD]) -> tuple[DD, ...]:
    """Inner DDs with overridden ones replaced where they stand, then the
    overrides that matched no inner DD appended."""
    seen = {dd.ddname for dd in inner_dds}
    return (
        *(overrides.get(dd.ddname, dd) for dd in inner_dds),
        *(dd for ddname, dd in overrides.items() if ddname not in seen),
    )


def _merge_dd_overrides(
    inner_step: Step, outer_dds: tuple[DD, ...], single_step: bool
) -> Step:
    """Apply qualified (stepname.ddname) DD overrides from the outer step's
    own dds onto this inner step — full replace of a matching ddname, append
    if new. A single-step PROC also accepts an unqualified override."""
    overrides = _overrides(inner_step, outer_dds, single_step)
    if not overrides:
        return inner_step
    return replace(inner_step, dds=_merged_dds(inner_step.dds, overrides))


# ── Inlining ──────────────────────────────────────────────────────


def _inlined(
    outer_step: Step,
    inner_step: Step,
    symbols: Mapping[str, Value],
    single_step: bool,
) -> Step:
    """One inner step as it reads inside the calling step: name qualified by
    the caller's step name, DDs overridden and then substituted."""
    merged = _merge_dd_overrides(inner_step, outer_step.dds, single_step)
    return replace(
        merged,
        name=f"{outer_step.name}.{merged.name}",
        dds=tuple(_substitute_dd(dd, symbols) for dd in merged.dds),
        parm=_substitute(merged.parm, symbols),
    )


def _expand_proc(
    step: Step, proc_def: ProcDef, proclib_dirs: Sequence[Path], stack: frozenset[str]
) -> tuple[Step, ...]:
    """The PROC's steps inlined into the calling step, each one then expanded
    itself — a PROC step may name another PROC."""
    symbols = {**proc_def.defaults, **step.proc_parms}
    single_step = len(proc_def.steps) == 1
    return tuple(
        chain.from_iterable(
            _expand_step(
                _inlined(step, inner_step, symbols, single_step),
                proclib_dirs,
                stack | {step.pgm},
            )
            for inner_step in proc_def.steps
        )
    )


def _expand_step(
    step: Step, proclib_dirs: Sequence[Path], stack: frozenset[str]
) -> tuple[Step, ...]:
    paths = _proc_paths(step.pgm, proclib_dirs)
    if not paths:
        return (step,)
    if step.pgm in stack:
        raise ProcExpansionError(
            f"Circular PROC reference: {' -> '.join((*stack, step.pgm))}"
        )
    return _expand_proc(step, parse_proc(paths[0].read_text()), proclib_dirs, stack)


def expand_procs(job: Job, proclib_dirs: Sequence[Path]) -> Job:
    """Return a new Job with every EXEC PROC= step replaced by its real,
    recursively-expanded, symbol-substituted, DD-merged inner steps. A step
    whose pgm doesn't resolve to a {proclib_dir}/{pgm}.prc file is returned
    unchanged — this function is a safe no-op for a job with no PROC calls."""
    return replace(
        job,
        steps=tuple(
            chain.from_iterable(
                _expand_step(step, proclib_dirs, frozenset()) for step in job.steps
            )
        ),
    )
