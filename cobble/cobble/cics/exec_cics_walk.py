"""Every EXEC CICS statement under an ASG, in source order, by one walk linear in the ASG's size."""

import dataclasses

from cics.statements import ExecCicsStatement


def _children(node: object) -> tuple[object, ...]:
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        return tuple(getattr(node, f.name) for f in dataclasses.fields(node))
    if isinstance(node, (list, tuple)):
        return tuple(node)
    if isinstance(node, dict):
        return tuple(node.values())
    return ()


def exec_cics_statements(root: object) -> tuple[ExecCicsStatement, ...]:
    seen: set[int] = set()
    stack: list[object] = [root]
    found: list[ExecCicsStatement] = []
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, ExecCicsStatement):
            found.append(node)
            continue
        stack.extend(reversed(_children(node)))
    return tuple(found)
