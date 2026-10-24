"""One statement that reads or writes a file, as the traces witnessed it."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.dataflow.fields.extent_text import ByteRange


@dataclass(frozen=True)
class FileSite:
    """The program and site of a file statement, the file it names, and the record bytes it reads into or writes from."""

    program: str
    site: str
    file: str
    record: ByteRange
    writes: bool
