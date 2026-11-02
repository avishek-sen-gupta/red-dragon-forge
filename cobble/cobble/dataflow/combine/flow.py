"""Flow — one flow row: bytes copied (or synthetically written) at one node."""

from dataclasses import dataclass

from cobble.dataflow.fields.extent_text import ByteRange


@dataclass(frozen=True)
class Flow:
    node: str
    source: ByteRange
    target: ByteRange
