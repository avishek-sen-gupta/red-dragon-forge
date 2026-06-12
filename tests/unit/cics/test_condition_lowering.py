"""Unit tests for condition_lowering helpers.

Covers:
- _extract_implied_relation: abbreviated-condition subject extraction
- _lower_expr_dict: unresolvable ref sentinel behaviour


COBOL abbreviated conditions like "EIBAID NOT = DFHENTER AND DFHPF7 AND DFHPF3"
expand to "EIBAID NOT = DFHENTER AND EIBAID NOT = DFHPF7 AND EIBAID NOT = DFHPF3".
ProLeap sometimes serialises the abbreviated operands (DFHPF7, DFHPF3) as
{"condition_name": X} when they are plain data fields rather than level-88 names.
The fix in _lower_condition_node detects this and reconstructs proper relations.

These tests verify _extract_implied_relation (the helper that finds the inherited
comparison subject) in isolation, since it is a pure dict transformation.
"""

from __future__ import annotations

from interpreter.cobol.condition_lowering import (
    _extract_implied_relation,
    _lower_expr_dict,
)
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

    def emit_inst(self, inst):  # type: ignore[no-untyped-def]
        self.emitted.append(inst)
        return inst

    def has_field(self, name, materialised) -> bool:  # type: ignore[no-untyped-def]
        return name in self._fields

    def const_to_reg(self, value):  # type: ignore[no-untyped-def]
        reg = self.fresh_reg()
        self.emit_inst(Const(result_reg=reg, value=value))
        return reg


_MAT = object()  # materialised layout sentinel — not inspected by these tests

_EIBAID = {"kind": "ref", "name": "EIBAID"}
_DFHENTER = {"kind": "ref", "name": "DFHENTER"}
_DFHPF7 = {"kind": "ref", "name": "DFHPF7"}


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_extract_implied_from_plain_relation():
    node = {"not": True, "relation": {"left": _EIBAID, "op": "==", "right": _DFHENTER}}
    result = _extract_implied_relation(node)
    assert result == (True, "==", _EIBAID)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_extract_implied_from_not_equal_relation():
    node = {"not": False, "relation": {"left": _EIBAID, "op": "!=", "right": _DFHENTER}}
    result = _extract_implied_relation(node)
    assert result == (False, "!=", _EIBAID)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_extract_implied_from_and_compound_prefers_left_when_right_has_no_relation():
    """EIBAID NOT= DFHENTER AND {condition_name: DFHPF7}: the right is an
    unresolvable condition_name so _extract_implied falls back to the left."""
    left = {"not": True, "relation": {"left": _EIBAID, "op": "==", "right": _DFHENTER}}
    node = {"op": "AND", "left": left, "right": {"condition_name": "DFHPF7"}}
    result = _extract_implied_relation(node)
    assert result == (True, "==", _EIBAID)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_extract_implied_from_nested_and_for_third_term():
    """Outer AND whose left is an inner AND (EIBAID NOT= DFHENTER AND DFHPF7).
    The right of the outer AND is {condition_name: DFHPF3}.  We need to find
    EIBAID from the inner AND's left."""
    left_full = {
        "not": True,
        "relation": {"left": _EIBAID, "op": "==", "right": _DFHENTER},
    }
    inner_and = {"op": "AND", "left": left_full, "right": {"condition_name": "DFHPF7"}}
    # outer AND left = inner_and, outer AND right = DFHPF3 condition_name
    result = _extract_implied_relation(inner_and)
    assert result == (True, "==", _EIBAID)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_extract_implied_returns_none_when_no_relation():
    assert _extract_implied_relation({"condition_name": "DFHPF7"}) is None
    assert _extract_implied_relation({"text": "DFHPF7"}) is None
    assert _extract_implied_relation({}) is None


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_extract_implied_from_nested_and_prefers_rightmost_full_relation():
    """When the right subtree of AND has a full relation, that is the more
    recent subject and should be preferred."""
    left_rel = {
        "not": False,
        "relation": {"left": _EIBAID, "op": "!=", "right": _DFHENTER},
    }
    right_rel = {
        "not": False,
        "relation": {"left": _DFHPF7, "op": "==", "right": _DFHENTER},
    }
    node = {"op": "AND", "left": left_rel, "right": right_rel}
    _, _, left_expr = _extract_implied_relation(node)
    assert left_expr == _DFHPF7


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
