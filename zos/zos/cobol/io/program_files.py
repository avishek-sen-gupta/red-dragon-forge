"""COBOL's file handler for a linked image: each file call goes to the provider of the program that made it."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence

from interpreter.cobol.io_provider import CobolIOProvider, IOResult
from interpreter.data_value import DataRecord
from interpreter.vm.vm import Operators
from zos.cobol.io.program_file import ProgramFile


class ProgramFilesIOProvider(CobolIOProvider):
    """Keeps one provider per program, holding that program's own declarations, so two programs' SELECTs never meet."""

    def __init__(
        self,
        programs: Collection[str],
        provider_for: Callable[[Sequence[ProgramFile]], CobolIOProvider],
        files: Sequence[ProgramFile],
    ) -> None:
        self._providers: Mapping[str, CobolIOProvider] = {
            program: provider_for(tuple(f for f in files if f.program == program))
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

    def _read_record(self, filename: str, locator: str, program: str) -> IOResult:
        return self._providers[program]._read_record(filename, locator, program)

    def _write_record(
        self, filename: str, data: str, locator: str, program: str
    ) -> IOResult:
        return self._providers[program]._write_record(filename, data, locator, program)

    def _rewrite_record(
        self, filename: str, data: str, locator: str, program: str
    ) -> IOResult:
        return self._providers[program]._rewrite_record(
            filename, data, locator, program
        )

    def _start_file(
        self, filename: str, locator: str, relop: str, program: str
    ) -> IOResult:
        return self._providers[program]._start_file(filename, locator, relop, program)

    def _delete_record(self, filename: str, locator: str, program: str) -> IOResult:
        return self._providers[program]._delete_record(filename, locator, program)

    def _key_of_reference(self, filename: str, number: int, program: str) -> IOResult:
        return self._providers[program]._key_of_reference(filename, number, program)
