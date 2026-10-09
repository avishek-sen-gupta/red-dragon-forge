"""FileAccesses — what one batch program OPENs, by DD name: all a worker hands back for its graph."""

from dataclasses import dataclass

from cobol_asg.file_enums import OpenMode


@dataclass(frozen=True)
class FileAccesses:
    program_id: str
    accesses: tuple[tuple[OpenMode, str, str], ...] = ()
