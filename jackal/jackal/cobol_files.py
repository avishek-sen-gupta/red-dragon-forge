"""jackal's COBOL file handler: red-dragon's, opening each file as its DD was allocated."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from cobol_asg.cobol_statements import FileControlEntry
from cobol_asg.file_enums import OpenMode
from interpreter.cobol.io_provider import IOResult
from interpreter.cobol.real_file_provider import RealFileIOProvider
from jackal.allocation import DdEnvironment


class AllocatedFileIOProvider(RealFileIOProvider):
    """A file whose DD was allocated with DISP=MOD is opened to append when written."""

    def __init__(
        self,
        base_dir: Path,
        file_control: Sequence[FileControlEntry],
        env: DdEnvironment,
    ) -> None:
        super().__init__(base_dir, list(file_control), dict(env.paths()))
        appended = {name.text for name in env.appended()}
        self._appended_files = frozenset(
            e.file_name for e in file_control if e.assign_to in appended
        )

    def _opened_as(self, filename: str, mode: str) -> str:
        if mode == OpenMode.OUTPUT.value and filename in self._appended_files:
            return OpenMode.EXTEND.value
        return mode

    def _open_file(
        self,
        filename: str,
        mode: str,
        record_length: int,
        organization: str,
        key_offset: int,
        key_length: int,
    ) -> IOResult:
        return super()._open_file(
            filename,
            self._opened_as(filename, mode),
            record_length,
            organization,
            key_offset,
            key_length,
        )
