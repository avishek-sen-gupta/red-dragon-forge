"""Unit tests for condition_lowering's _lower_expr_dict: the unresolvable-ref
sentinel, and a numeric literal the bridge tagged as a ref."""

from __future__ import annotations

from interpreter.cobol.condition_lowering import _lower_expr_dict
from interpreter.instructions import Const
from interpreter.register import Register
from tests.covers import covers, NotLanguageFeature


class _FakeCtx:
    """Minimal EmitContext stub sufficient for testing _lower_expr_dict."""

    def __init__(self, fields: set[str]) -> None:
        self._fields = fields
        self.emitted: list = []
        self._counter = 0

    def fresh_reg(self) -> Register:
        reg = Register(f"%{self._counter}")
        self._counter += 1
        return reg

    def emit_inst(self, inst, *, span=None):  # type: ignore[no-untyped-def]
        self.emitted.append(inst)
        return inst

    def has_field(self, name, materialised) -> bool:  # type: ignore[no-untyped-def]
        return name in self._fields

    def const_to_reg(self, value, *, span=None):  # type: ignore[no-untyped-def]
        from interpreter.types.type_expr import UNKNOWN

        reg = self.fresh_reg()
        self.emit_inst(Const(result_reg=reg, value=value, type_expr=UNKNOWN))
        return reg

    def parse_literal(self, text):  # type: ignore[no-untyped-def]
        """Mirror EmitContext.parse_literal: int, then float, else the string."""
        try:
            return int(text)
        except ValueError:
            pass
        try:
            return float(text)
        except ValueError:
            pass
        return text


_MAT = object()  # materialised layout sentinel — not inspected by these tests


# ── _lower_expr_dict: unresolvable ref ────────────────────────────────────────


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_unresolvable_ref_emits_sentinel_not_field_name_literal():
    """A ref node whose name isn't in materialised must emit an obviously-wrong
    sentinel constant ('UNRESOLVABLE__X'), not silently coerce the name to a
    literal via parse_literal."""
    ctx = _FakeCtx(fields=set())
    _lower_expr_dict(ctx, {"kind": "ref", "name": "MISSING_FIELD"}, _MAT)
    consts = [i.value for i in ctx.emitted if isinstance(i, Const)]
    assert consts == [
        "UNRESOLVABLE__MISSING_FIELD"
    ], f"expected sentinel constant, got {consts}"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_numeric_literal_tagged_as_ref_is_parsed_not_sentinelled():
    """The bridge sometimes tags a numeric literal as a ref (e.g. an abbreviated
    condition operand '1'). It must be parsed as the literal, NOT sentinelled."""
    ctx = _FakeCtx(fields=set())
    _lower_expr_dict(ctx, {"kind": "ref", "name": "1"}, _MAT)
    consts = [i.value for i in ctx.emitted if isinstance(i, Const)]
    assert consts == [1], f"expected literal int 1, got {consts}"
