"""An alternate index: a second key position over a cataloged KSDS."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlternateIndex:
    dsn: str
    base: str
    key_offset: int
    key_length: int
    unique: bool

    def __post_init__(self) -> None:
        if self.key_offset < 0 or self.key_length <= 0:
            raise ValueError(
                f"{self.dsn}: key offset {self.key_offset}, length {self.key_length}"
            )
