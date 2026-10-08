"""One write in a program that touches a dynamic site's operand."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.dataflow.fixpoint.definition_kind import DefinitionKind


@dataclass(frozen=True)
class SiteDefinition:
    """The node that writes, what kind of write it is, the literal values it stores,
    the storage it copies from, and the reasons its values carry."""

    node: str
    kind: DefinitionKind
    values: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
