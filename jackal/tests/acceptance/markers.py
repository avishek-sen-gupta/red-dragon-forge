"""Strict xfail markers naming the unit that makes each acceptance test pass."""

import pytest

PARSED = pytest.mark.xfail(
    reason="red-dragon-forge-2cy.9: blueprint parsed model not built yet",
    strict=True,
)
EXPANDED = pytest.mark.xfail(
    reason="red-dragon-forge-2cy.10: expand_procs -> ExpandedJob not built yet",
    strict=True,
)


def bridge_then_parsed(issue: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(
        reason=f"{issue} (bridge) and red-dragon-forge-2cy.9 (parsed model)",
        strict=True,
    )


def bridge_then_expanded(issue: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(
        reason=f"{issue} (bridge) and red-dragon-forge-2cy.10 (expansion)",
        strict=True,
    )
