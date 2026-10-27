"""A READ, with the record area its file fills named alongside its INTO field."""

from __future__ import annotations

from dataclasses import dataclass

from cobol_asg.ref_mod import RefModOperand


@dataclass(frozen=True)
class FileRead:
    """Every field a READ fills from ``file_name``: the FD's 01 records, which
    share the file's record area, and the INTO field when there is one."""

    file_name: str
    targets: tuple[RefModOperand, ...]
