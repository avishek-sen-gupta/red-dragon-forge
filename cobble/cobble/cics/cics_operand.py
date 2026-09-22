"""One EXEC CICS option operand, as cobble stores it and as cobble reads it.

``CicsOperand`` splits an operand in two on purpose: ``text`` is the name alone and
``subscripts`` carries each index as a structured ``ExprNode``. cobble read ``text``
and nothing else, so ``PROGRAM(CDEMO-MENU-OPT-PGMNAME(WS-OPTION))`` arrived at the
analysis as a scalar, resolved at arity 0 against a field declared ``OCCURS 12``,
matched no cell and came back with no extent at all -- a field-selection bug wearing
a layout bug's clothes (forge-zgn).

The loss started one stage earlier. cicada's ``ExecCicsStatement.to_dict`` keeps
``text`` and ``is_literal`` and drops the rest, which costs its own compile path
nothing because that path never reads the form back. cobble's ASG cache does read it
back: every stage after ``cobble-parse-corpus`` sees only what landed in the JSON. So
cobble owns both ends of its own cache format -- the writer here and the reader in
dataflow/depgraph/cics_cache.py -- and an operand carrying neither subscripts nor
reference modification still serializes to exactly the two keys it always did, so an
ASG cached before this existed reads back unchanged and one cached after it is
byte-identical.

``ExecCicsStatement`` here deliberately carries cicada's class NAME. desugar.py,
flows.py and graph.py dispatch on ``type(statement).__name__`` so that a subclass
with different operand semantics is skipped loudly rather than mishandled quietly;
this one's operand semantics are cicada's exactly, and only its serialized form
differs, so being skipped is the wrong outcome for it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from cics.statements import CicsDialectParser, CicsOperand
from cics.statements import ExecCicsStatement as CicsExecCicsStatement
from cobol_asg.cobol_expression import ExprNode, expr_from_dict, expr_to_dict
from cobol_asg.ref_mod import RefModOperand, ref_mod_expr_from_dict

_BOUNDS = ("ref_mod_start", "ref_mod_length")


def as_reference(operand: CicsOperand) -> RefModOperand:
    """The operand as the extent resolver takes it: name, indices and slice.

    ``RefModExpr`` and ``ExprNode`` are separate unions over the same JSON shapes,
    so a bound crosses between them through the dict form rather than by a cast.
    """
    return replace(
        RefModOperand(name=operand.text, subscripts=operand.subscripts),
        **{
            side: ref_mod_expr_from_dict(expr_to_dict(bound))
            for side, bound in _present_bounds(operand).items()
        },
    )


def as_written(operand: CicsOperand) -> str:
    """The operand as the source spells it, subscripts included.

    A subscripted callee names a table entry picked at runtime and stays
    unresolved, but it must not read as the same thing a plain field reads as:
    ``CDEMO-MENU-OPT-PGMNAME`` alone claims a scalar the program never declared.
    """
    if not operand.subscripts:
        return operand.text
    indices = ", ".join(_index_text(node) for node in operand.subscripts)
    return f"{operand.text}({indices})"


def operand_to_dict(operand: CicsOperand) -> dict:
    """One operand as the cache stores it, structure included."""
    return {
        "text": operand.text,
        "is_literal": operand.is_literal,
        **_structure(operand),
    }


def operand_from_dict(data: Mapping) -> CicsOperand:
    """One serialized option value as an operand.

    A bare flag -- NOHANDLE, RESP -- serializes as null rather than as a mapping and
    never reaches here; the key stays in the options with no operand behind it,
    which is what cicada's own parser produces for it too.
    """
    return CicsOperand(
        text=str(data.get("text", "")),
        is_literal=bool(data.get("is_literal", False)),
        subscripts=tuple(expr_from_dict(node) for node in data.get("subscripts", ())),
        **{
            side: expr_from_dict(bound)
            for side, bound in _serialized_bounds(data).items()
        },
    )


class ExecCicsStatement(CicsExecCicsStatement):
    """cicada's statement, serialized without dropping an operand's structure."""

    def to_dict(self) -> dict:
        return {
            "type": "EXEC_CICS",
            "verb": self.verb,
            "options": {
                option: (
                    operand_to_dict(operand)
                    if isinstance(operand, CicsOperand)
                    else None
                )
                for option, operand in self.options.items()
            },
        }


class StructuredCicsDialectParser(CicsDialectParser):
    """cicada's bridge-JSON parser, yielding the statement cobble's cache stores."""

    def parse(self, data: Mapping) -> CicsExecCicsStatement:
        parsed = super().parse(dict(data))
        return ExecCicsStatement(verb=parsed.verb, options=parsed.options)


def _structure(operand: CicsOperand) -> dict:
    indices = {"subscripts": [expr_to_dict(node) for node in operand.subscripts]}
    return {
        **(indices if operand.subscripts else {}),
        **{
            side: expr_to_dict(bound)
            for side, bound in _present_bounds(operand).items()
        },
    }


def _present_bounds(operand: CicsOperand) -> dict:
    declared = {side: getattr(operand, side) for side in _BOUNDS}
    return {side: bound for side, bound in declared.items() if bound}


def _serialized_bounds(data: Mapping) -> dict:
    return {side: data[side] for side in _BOUNDS if isinstance(data.get(side), Mapping)}


def _index_text(node: ExprNode) -> str:
    """A CICS subscript is a bare data-name or an integer; cicada rejects the rest."""
    serialized = expr_to_dict(node)
    return str(serialized.get("name") or serialized.get("value") or "")
