"""Unit tests for the abbreviated-condition repair in condition_lowering.

COBOL abbreviated conditions like "EIBAID NOT = DFHENTER AND DFHPF7 AND DFHPF3"
expand to "EIBAID NOT = DFHENTER AND EIBAID NOT = DFHPF7 AND EIBAID NOT = DFHPF3".
ProLeap sometimes serialises the abbreviated operands (DFHPF7, DFHPF3) as
{"condition_name": X} when they are plain data fields rather than level-88 names.
The fix in _lower_condition_node detects this and reconstructs proper relations.

These tests verify _extract_implied_relation (the helper that finds the inherited
comparison subject) in isolation, since it is a pure dict transformation.
"""

from __future__ import annotations

from interpreter.cobol.condition_lowering import _extract_implied_relation
from tests.covers import covers, NotLanguageFeature

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
