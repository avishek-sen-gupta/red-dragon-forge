"""jackal's COBOL file handler for a linked image: each file call goes to the provider of the program that made it."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

from catnip.dataset import Relabeller
from interpreter.cobol.io_provider import CobolIOProvider, IOResult
from interpreter.data_value import DataRecord
from interpreter.vm.vm import Operators
from jackal.allocation import DdEnvironment
from jackal.cobol_files import AllocatedFileIOProvider, ProgramFile


class ProgramFilesIOProvider(CobolIOProvider):
    """Keeps one AllocatedFileIOProvider per program, holding that program's own declarations, so two programs' SELECTs never meet."""

    def __init__(
        self,
        base_dir: Path,
        programs: Collection[str],
        files: Sequence[ProgramFile],
        env: DdEnvironment,
        relabeller: Relabeller,
    ) -> None:
        self._providers: Mapping[str, AllocatedFileIOProvider] = {
            program: AllocatedFileIOProvider(
                base_dir,
                tuple(f for f in files if f.program == program),
                env,
                relabeller,
            )
            for program in programs
        }

    def _accept(self, from_device: str) -> Operators._Uncomputable:
        return Operators.UNCOMPUTABLE

    def _declare_file(self, frame: DataRecord, program: str) -> IOResult:
        return self._providers[program]._declare_file(frame, program)

    def _open_file(self, filename: str, mode: str, program: str) -> IOResult:
        return self._providers[program]._open_file(filename, mode, program)

    def _close_file(self, filename: str, program: str) -> IOResult:
        return self._providers[program]._close_file(filename, program)

    def _read_record(self, filename: str, key: str, program: str) -> IOResult:
        return self._providers[program]._read_record(filename, key, program)

    def _write_record(
        self, filename: str, data: str, key: str, program: str
    ) -> IOResult:
        return self._providers[program]._write_record(filename, data, key, program)

    def _rewrite_record(
        self, filename: str, data: str, key: str, program: str
    ) -> IOResult:
        return self._providers[program]._rewrite_record(filename, data, key, program)

    def _start_file(
        self, filename: str, key: str, relop: str, program: str
    ) -> IOResult:
        return self._providers[program]._start_file(filename, key, relop, program)

    def _delete_record(self, filename: str, key: str, program: str) -> IOResult:
        return self._providers[program]._delete_record(filename, key, program)

    def _key_of_reference(self, filename: str, number: int, program: str) -> IOResult:
        return self._providers[program]._key_of_reference(filename, number, program)
