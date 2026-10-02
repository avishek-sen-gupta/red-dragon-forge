"""The text of a PERFORM VARYING spec's FROM or BY: the name or literal it holds."""

from __future__ import annotations

from collections.abc import Mapping


def spec_text(value: Mapping[str, str] | str) -> str:
    """FROM is a structured expression dict in newer parses and text in older ones;
    either way what is wanted is the name or the literal."""
    if isinstance(value, Mapping):
        return str(value.get("name", value.get("value", ""))).upper()
    return str(value or "").upper()
