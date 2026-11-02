"""Flow — one flow row: bytes copied (or synthetically written) at one node."""

from dataclasses import dataclass

from cobble.dataflow.fields.extent_text import ByteRange
from cobble.dataflow.fields.origin import NO_ORIGIN, Origin


@dataclass(frozen=True)
class Flow:
    """``origin`` names a value from outside storage; ``landing`` is where the
    source's first byte lands, as an offset into the target, when the bytes moved
    unchanged, and nothing when the statement rewrote them or their place is not known.
    """

    node: str
    source: ByteRange
    target: ByteRange
    origin: Origin = NO_ORIGIN
    landing: tuple[int, ...] = ()
