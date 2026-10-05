"""Read Facts — values, writers, reasons — for some bytes off a settled state."""

from collections.abc import Sequence

from cobble.dataflow.fields.extent_text import extent_text
from cobble.dataflow.fields.state import State, reaching, values_at
from cobble.dataflow.jumps.fact import Fact
from cobol_memory.field_extent import FieldExtent


def fact_at(state: State, extent: FieldExtent) -> Fact:
    held = values_at(state, extent)
    return Fact(
        extent=extent_text(extent),
        values=tuple(sorted(v.decode("utf-8", errors="replace") for v in held.values)),
        writers=tuple(
            sorted({s.node for s in reaching(state, extent) if not s.origin})
        ),
        reasons=tuple(sorted(held.reasons, key=str)),
    )


def merged(facts: Sequence[Fact]) -> Fact:
    if not facts:
        return Fact()
    return Fact(
        extent=facts[0].extent,
        values=tuple(sorted({v for fact in facts for v in fact.values})),
        writers=tuple(sorted({w for fact in facts for w in fact.writers})),
        reasons=tuple(sorted({r for fact in facts for r in fact.reasons}, key=str)),
    )
