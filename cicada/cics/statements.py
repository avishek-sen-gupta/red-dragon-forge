"""CICS-owned COBOL statement types, relocated from RedDragon (red-dragon
commit b54471dc's DialectParser migration) — RedDragon itself now has zero
CICS-specific type names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from cics.cics_visitor import CicsOperand, parse_exec_cics_text
from cobol_asg.ref_mod import RefModOperand
from cobol_asg.source_span import SourceSpan

_STRUCTURE = ("subscripts", "ref_mod_start", "ref_mod_length")


def operand_to_dict(operand: CicsOperand) -> dict:
    """One option operand as JSON, keeping everything CicsOperand carries.

    ``text`` is the name alone, so an operand that dropped its ``subscripts`` here
    came back a scalar: ``PROGRAM(TBL(WS-OPTION))`` read as ``TBL``, which then
    resolves at arity 0 against a field declared OCCURS and matches nothing. Each
    entry below appears only when the operand has it, so an operand with neither a
    subscript nor a slice serializes to exactly the two entries it always did.
    """
    return {
        "text": operand.text,
        "is_literal": operand.is_literal,
        **_structure(operand),
    }


def operand_reference(operand: CicsOperand) -> RefModOperand:
    """The operand as a COBOL operand reference: name, indices and slice.

    A consumer resolving a CICS operand to storage needs the same three parts a
    MOVE operand carries, and this is the same reference under another name. Reading
    ``text`` alone instead makes a subscripted operand a scalar, which then resolves
    at arity 0 against a field declared OCCURS and matches no cell.
    """
    return RefModOperand(
        name=operand.text,
        subscripts=operand.subscripts,
        ref_mod_start=operand.ref_mod_start,
        ref_mod_length=operand.ref_mod_length,
    )


def operand_from_dict(data: dict) -> CicsOperand:
    """The inverse of ``operand_to_dict``, including a payload written before it.

    An older payload carries ``text`` and ``is_literal`` alone and reads back as the
    unsubscripted, unmodified operand it described.
    """
    read = RefModOperand.from_dict(
        {"name": "", **{part: data[part] for part in _STRUCTURE if part in data}}
    )
    return CicsOperand(
        text=str(data.get("text", "")),
        is_literal=bool(data.get("is_literal", False)),
        subscripts=read.subscripts,
        ref_mod_start=read.ref_mod_start,
        ref_mod_length=read.ref_mod_length,
    )


@dataclass(frozen=True)
class ExecCicsStatement:
    """EXEC CICS verb-with-options block."""

    verb: str
    options: dict[str, "CicsOperand | None"]
    span: SourceSpan | None = None

    def to_dict(self) -> dict:
        """The statement as JSON, losslessly: ``from_dict`` reconstructs it.

        RedDragon's to_dict() convention is an informational round-trip, but this
        one is load-bearing — cobble's parsed-ASG cache IS ``CobolASG.to_dict()``,
        and every stage after its parse reads the JSON rather than the source. A key
        dropped here is a key no consumer can ever recover.
        """
        serialised: dict[str, Any] = {
            name: operand_to_dict(operand) if isinstance(operand, CicsOperand) else None
            for name, operand in self.options.items()
        }
        result = {"type": "EXEC_CICS", "verb": self.verb, "options": serialised}
        if self.span is not None:
            self.span.write_into(result)
        return result

    @classmethod
    def from_dict(cls, data: dict) -> ExecCicsStatement:
        """Reconstruct from a ``to_dict`` payload.

        A bare flag — NOHANDLE, RESP — carries no value and serializes as null. It
        stays an option with no operand behind it, which is what parsing the source
        text produces for it too.
        """
        options = data.get("options") or {}
        return cls(
            verb=str(data.get("verb", "")),
            options={
                name: operand_from_dict(value) if isinstance(value, dict) else None
                for name, value in options.items()
            },
            span=SourceSpan.from_dict(data),
        )


class CicsDialectParser:
    """Constructs ExecCicsStatement from raw EXEC CICS bridge JSON.

    Also accumulates every statement into ``statements``, in program order.
    This instance is shared across every module a compile lowers, so a reader
    consuming ``statements`` must clear it once read, per module — see
    CicsLoweringStrategy.on_procedure_entry.
    """

    def __init__(self) -> None:
        self.statements: list[ExecCicsStatement] = []

    def applies(self, data: dict) -> bool:
        return data.get("type") == "EXEC_CICS"

    def parse(self, data: dict) -> ExecCicsStatement:
        text = re.sub(
            r"\*>.*", "", data.get("exec_cics_text", ""), flags=re.MULTILINE
        ).strip()
        verb, options = parse_exec_cics_text(text)
        stmt = ExecCicsStatement(
            verb=verb, options=options, span=SourceSpan.from_dict(data)
        )
        self.statements.append(stmt)
        return stmt


def _structure(operand: CicsOperand) -> dict:
    """The subscripts and slice bounds, each key present only when the operand has it.

    A CICS operand is a COBOL operand reference wearing a different name: same
    indices, same ``(start:length)``, same node types on both. RefModOperand already
    serializes all three and omits each when absent, so it is borrowed as the codec
    rather than copied into a second one that would drift from it.

    """
    written = operand_reference(operand).to_dict()
    return {part: written[part] for part in _STRUCTURE if part in written}
