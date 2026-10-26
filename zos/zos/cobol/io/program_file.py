"""One file a program declares: its SELECT and the record format its FD asks for."""

from __future__ import annotations

from dataclasses import dataclass

from cobol_asg.cobol_statements import FileControlEntry
from zos.cobol.io.record_format import ProgramFormat


@dataclass(frozen=True)
class ProgramFile:
    program: str
    entry: FileControlEntry
    fmt: ProgramFormat
