"""In-place writes into the VM's working-storage region."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from interpreter.address import Address
from interpreter.cobol.field_position import FieldPosition
from interpreter.vm.vm_types import VMState


@dataclass(frozen=True)
class FieldWrite:
    name: str
    data: bytes
    pad: bytes = b"\x00"
    right_justify: bool = False


def _placed(write: FieldWrite, length: int) -> bytes:
    clipped = write.data[:length]
    if write.right_justify:
        return clipped.rjust(length, write.pad)[:length]
    return clipped.ljust(length, write.pad)[:length]


def write_fields(
    positions: Mapping[str, FieldPosition],
    region: bytearray,
    writes: Sequence[FieldWrite],
) -> frozenset[str]:
    missing = set()
    for write in writes:
        if write.name not in positions:
            missing.add(write.name)
            continue
        position = positions[write.name]
        offset, length = position.offset, position.length
        region[offset : offset + length] = _placed(write, length)
    return frozenset(missing)


def commit_region(vm: VMState, address: Address, region: bytearray) -> None:
    vm.region_set(address, region)


def write_at(region: bytearray, offset: int, data: bytes) -> None:
    region[offset : offset + len(data)] = data
