"""Number a program's HANDLE CONDITION and HANDLE ABEND LABEL target paragraphs.

The dispatcher's cascade compares a runtime index against compile-time constants,
so every paragraph a program can transfer to needs an index before the first
fallible command is lowered — and a HANDLE CONDITION may appear textually after
that command. Hence a pre-pass rather than collection during lowering.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from cics.cics_visitor import CicsOperand
from cics.statements import ExecCicsStatement

_HANDLE = "HANDLE CONDITION"
_HANDLE_ABEND = "HANDLE ABEND"
_ABEND_LABEL = "LABEL"


@dataclass(frozen=True)
class HandlerLabels:
    """Paragraph name -> 1-based dispatch index, plus the condition that named it.

    Index 0 is reserved for "no handler", which is what LOW-VALUES gives every
    slot of the injected table. The condition is carried alongside so a target
    that names no real paragraph can be rejected in the program's own terms.
    """

    indices: Mapping[str, int]
    conditions: Mapping[str, str]
    abend_exits: frozenset[str] = frozenset()

    def index_of(self, paragraph: str) -> int:
        return self.indices.get(paragraph, 0)

    def __bool__(self) -> bool:
        return bool(self.indices)


def _targets(
    statements: Sequence[ExecCicsStatement],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (condition, operand.text)
        for stmt in statements
        for condition, operand in stmt.options.items()
        if _names_a_target(stmt.verb, condition)
        and isinstance(operand, CicsOperand)
        and not operand.is_literal
    )


def _names_a_target(verb: str, option: str) -> bool:
    return verb == _HANDLE or (verb == _HANDLE_ABEND and option == _ABEND_LABEL)


def collect_handler_labels(
    statements: Sequence[ExecCicsStatement],
) -> HandlerLabels:
    """Number each HANDLE CONDITION and HANDLE ABEND LABEL target paragraph in
    first-appearance order."""
    targets = _targets(statements)
    paragraphs = tuple(dict.fromkeys(paragraph for _, paragraph in targets))
    return HandlerLabels(
        indices={name: index for index, name in enumerate(paragraphs, start=1)},
        conditions={paragraph: condition for condition, paragraph in reversed(targets)},
        abend_exits=frozenset(
            paragraph for option, paragraph in targets if option == _ABEND_LABEL
        ),
    )


def _paragraph_names_of(container: object) -> Iterable[str]:
    paragraphs = container.get("paragraphs", ()) if isinstance(container, dict) else ()
    return (
        str(para["name"])
        for para in paragraphs
        if isinstance(para, dict) and "name" in para
    )


def paragraph_names(program_dict: Mapping[str, object]) -> frozenset[str]:
    """Every paragraph name a ``Branch(CodeLabel("para_<name>"))`` can reach.

    Read from the raw bridge JSON rather than the EmitContext because
    ``on_procedure_entry`` — where the dispatcher is emitted — runs before
    ``ctx.section_paragraphs`` is populated, and standalone paragraphs never
    appear there at all.
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
    """Every section name a ``Branch(CodeLabel("section_<NAME>"))`` can reach."""
    return frozenset(
        str(section["name"])
        for section in _as_sequence(program_dict.get("sections", ()))
        if isinstance(section, dict) and "name" in section
    )


def _as_sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, list) else ()
