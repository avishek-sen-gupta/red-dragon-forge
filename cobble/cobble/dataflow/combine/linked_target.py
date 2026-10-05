"""LinkedTarget — a dynamic site after linking, with the outside callers it may miss."""

from dataclasses import dataclass

from cobble.dataflow.fixpoint.targets import ResolvedTarget


@dataclass(frozen=True)
class LinkedTarget:
    target: ResolvedTarget
    outside: tuple[str, ...] = ()
