"""One write touching a dynamic site's operand, as a sites row lists it."""

from __future__ import annotations

from cobble.dataflow.fixpoint.definition_kind import DefinitionKind
from pydantic import BaseModel, ConfigDict


class SiteRowDefinition(BaseModel):
    """Where the write is, what kind it is, the literal values it stores, the
    storage it copies from, and the reasons its values carry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    place: str
    kind: DefinitionKind
    values: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
