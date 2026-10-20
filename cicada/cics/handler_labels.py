"""Number a program's HANDLE CONDITION and HANDLE ABEND LABEL target procedures.

The dispatcher's cascade compares a runtime index against compile-time constants,
so every procedure a program can transfer to needs an index before the first
fallible command is lowered — and a HANDLE CONDITION may appear textually after
that command. Hence a pre-pass rather than collection during lowering.

A target names a procedure the way PERFORM or GO TO does: its case folds, and a
paragraph name declared in two sections means the copy in the HANDLE statement's
own section. That section is known only while the statement is lowered, so the
pre-pass numbers every copy, keyed by its label.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from cics.cics_visitor import CicsOperand
from cics.statements import ExecCicsStatement
from interpreter.cobol.procedure_labels import ProcedureLabels
from interpreter.ir import CodeLabel

_HANDLE = "HANDLE CONDITION"
_HANDLE_ABEND = "HANDLE ABEND"
_ABEND_LABEL = "LABEL"


@dataclass(frozen=True)
class HandlerLabels:
    """Procedure label -> 1-based dispatch index, plus the condition that named
    each target.

    Index 0 is reserved for "no handler", which is what LOW-VALUES gives every
    slot of the injected table. The condition is carried alongside, keyed by the
    case-folded target name, so a target that names no real procedure can be
    rejected in the program's own terms.
    """

    indices: Mapping[CodeLabel, int]
    conditions: Mapping[str, str]
    abend_exits: frozenset[CodeLabel] = frozenset()

    def index_of(self, label: CodeLabel) -> int:
        return self.indices.get(label, 0)

    def abend_exit_handlers(self) -> tuple[tuple[CodeLabel, int], ...]:
        """Each HANDLE ABEND LABEL target with its index, in index order."""
        return tuple(
            (label, index)
            for label, index in self.indices.items()
            if label in self.abend_exits
        )

    def __bool__(self) -> bool:
        return bool(self.indices)


def _targets(
    statements: Sequence[ExecCicsStatement],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (condition, operand.text.upper())
        for stmt in statements
        for condition, operand in stmt.options.items()
        if _names_a_target(stmt.verb, condition)
        and isinstance(operand, CicsOperand)
        and not operand.is_literal
    )


def _names_a_target(verb: str, option: str) -> bool:
    return verb == _HANDLE or (verb == _HANDLE_ABEND and option == _ABEND_LABEL)


def candidate_labels(name: str, procedures: ProcedureLabels) -> tuple[CodeLabel, ...]:
    """Every label a target name can resolve to, from any section of the program."""
    if procedures.is_section(name):
        return (procedures.section(name),)
    owners = tuple(
        section for section, names in procedures.sections.items() if name in names
    )
    return tuple(
        dict.fromkeys(procedures.paragraph(name, owner) for owner in owners or ("",))
    )


def collect_handler_labels(
    statements: Sequence[ExecCicsStatement], procedures: ProcedureLabels
) -> HandlerLabels:
    """Number each HANDLE CONDITION and HANDLE ABEND LABEL target procedure in
    first-appearance order."""
    targets = _targets(statements)
    labels = tuple(
        dict.fromkeys(
            label for _, name in targets for label in candidate_labels(name, procedures)
        )
    )
    return HandlerLabels(
        indices={label: index for index, label in enumerate(labels, start=1)},
        conditions={name: condition for condition, name in reversed(targets)},
        abend_exits=frozenset(
            label
            for option, name in targets
            if option == _ABEND_LABEL
            for label in candidate_labels(name, procedures)
        ),
    )


def _paragraph_names_of(container: object) -> Iterable[str]:
    paragraphs = container.get("paragraphs", ()) if isinstance(container, dict) else ()
    return (
        str(para["name"]).upper()
        for para in paragraphs
        if isinstance(para, dict) and "name" in para
    )


def paragraph_names(program_dict: Mapping[str, object]) -> frozenset[str]:
    """Every paragraph name a handler can transfer to, case-folded.

    Read from the raw bridge JSON rather than ``ctx.procedures``, which records
    the paragraphs of each section but not standalone ones.
    """
    containers = (
        program_dict,
        *(
            section
            for key in ("sections", "declaratives")
            for section in _as_sequence(program_dict.get(key, ()))
        ),
    )
    return frozenset(
        name for container in containers for name in _paragraph_names_of(container)
    )


def section_names(program_dict: Mapping[str, object]) -> frozenset[str]:
    """Every section name a handler can transfer to, case-folded."""
    return frozenset(
        str(section["name"]).upper()
        for section in _as_sequence(program_dict.get("sections", ()))
        if isinstance(section, dict) and "name" in section
    )


def _as_sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, list) else ()
