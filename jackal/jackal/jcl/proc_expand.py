"""expand_procs() — resolve and inline JCL EXEC PROC= calls: symbol
substitution, DD-qualified overriding, recursive nesting. Parses everything
(the outer job's already-parsed Step, and each referenced .prc file) through
the real jcl-bridge grammar — never a bespoke text scanner. See
jackal/docs/superpowers/specs/2026-07-08-jcl-proc-expansion-design.md.

SET statements are not supported (forge-6qr) — verified absent from every
real PROC in the CardDemo corpus.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from jackal.dsn import DirectDSN
from jackal.jcl.parser import parse_proc
from jackal.model import DD, Job, Step
from jackal.value_parts import Literal, Symbol, Value


class ProcExpansionError(Exception):
    """Raised when PROC resolution/inlining fails: PROC not found, an
    unbound symbol, or a circular PROC reference."""


def _resolve_proc_path(name: str, proclib_dirs: Sequence[Path]) -> Path | None:
    for proclib_dir in proclib_dirs:
        candidate = proclib_dir / f"{name}.prc"
        if candidate.is_file():
            return candidate
    return None


def _substitute(value: Value, symbols: dict[str, Value]) -> Value:
    parts: list[Literal] = []
    for part in value:
        match part:
            case Literal():
                parts.append(part)
            case Symbol(name=n):
                if n not in symbols:
                    raise ProcExpansionError(f"Unbound symbol '&{n}'")
                parts.extend(symbols[n])
    return tuple(parts)


def _substitute_dd(dd: DD, symbols: dict[str, Value]) -> DD:
    match dd.dsn:
        case DirectDSN(name=n):
            return DD(
                dd.ddname,
                DirectDSN(_substitute(n, symbols)),
                dd.disp,
                dd.in_stream,
                dd.sysout,
            )
        case _:
            return dd


def _merge_dd_overrides(
    inner_step: Step, outer_dds: tuple[DD, ...], single_step: bool
) -> Step:
    """Apply qualified (stepname.ddname) DD overrides from the outer step's
    own dds onto this inner step — full replace of a matching ddname, append
    if new. A single-step PROC also accepts an unqualified override."""
    targeted: dict[str, DD] = {}
    for dd in outer_dds:
        if "." in dd.ddname:
            qualifier, real_ddname = dd.ddname.split(".", 1)
            if qualifier == inner_step.name:
                targeted[real_ddname] = DD(
                    real_ddname, dd.dsn, dd.disp, dd.in_stream, dd.sysout
                )
        elif single_step:
            targeted[dd.ddname] = dd

    if not targeted:
        return inner_step

    new_dds: list[DD] = []
    seen: set[str] = set()
    for dd in inner_step.dds:
        if dd.ddname in targeted:
            new_dds.append(targeted[dd.ddname])
            seen.add(dd.ddname)
        else:
            new_dds.append(dd)
    for ddname, dd in targeted.items():
        if ddname not in seen:
            new_dds.append(dd)

    return Step(
        inner_step.name,
        inner_step.pgm,
        tuple(new_dds),
        inner_step.conds,
        inner_step.parm,
        inner_step.proc_parms,
    )


def _expand_step(
    step: Step, proclib_dirs: Sequence[Path], stack: frozenset[str]
) -> list[Step]:
    proc_path = _resolve_proc_path(step.pgm, proclib_dirs)
    if proc_path is None:
        return [step]

    if step.pgm in stack:
        raise ProcExpansionError(
            f"Circular PROC reference: {' -> '.join((*stack, step.pgm))}"
        )

    proc_def = parse_proc(proc_path.read_text())
    symbols: dict[str, Value] = dict(proc_def.defaults)
    symbols.update(step.proc_parms)
    single_step = len(proc_def.steps) == 1

    expanded: list[Step] = []
    for inner_step in proc_def.steps:
        merged = _merge_dd_overrides(inner_step, step.dds, single_step)
        substituted = Step(
            name=f"{step.name}.{merged.name}",
            pgm=merged.pgm,
            dds=tuple(_substitute_dd(dd, symbols) for dd in merged.dds),
            conds=merged.conds,
            parm=_substitute(merged.parm, symbols),
            proc_parms=merged.proc_parms,
        )
        expanded.extend(_expand_step(substituted, proclib_dirs, stack | {step.pgm}))
    return expanded


def expand_procs(job: Job, proclib_dirs: Sequence[Path]) -> Job:
    """Return a new Job with every EXEC PROC= step replaced by its real,
    recursively-expanded, symbol-substituted, DD-merged inner steps. A step
    whose pgm doesn't resolve to a {proclib_dir}/{pgm}.prc file is returned
    unchanged — this function is a safe no-op for a job with no PROC calls."""
    new_steps: list[Step] = []
    for step in job.steps:
        new_steps.extend(_expand_step(step, proclib_dirs, frozenset()))
    return Job(name=job.name, steps=tuple(new_steps), cond=job.cond)
