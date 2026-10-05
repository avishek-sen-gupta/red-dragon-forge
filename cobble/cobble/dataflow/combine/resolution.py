"""Resolution — the values some bytes hold here, and the stops still to follow."""

from dataclasses import dataclass

from cobble.dataflow.combine.stop import Stop


@dataclass(frozen=True)
class Resolution:
    values: frozenset[str] = frozenset()
    stops: frozenset[Stop] = frozenset()


def joined(left: Resolution, right: Resolution) -> Resolution:
    return Resolution(left.values | right.values, left.stops | right.stops)
