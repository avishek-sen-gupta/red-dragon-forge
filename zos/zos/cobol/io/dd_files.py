"""HLASM's file handler over catalogued datasets: each DDNAME opens as bound, admitted and labelled by the frame OPEN declared."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from catnip.dataset import Dataset, Relabeller
from cobol_asg.file_enums import OpenMode
from infrastructure.zos.access_methods.file_drivers import FileOrganizationDriver
from interpreter.record_io.file_frame import FileFrame
from zos.cobol.io.dataset_files import DatasetFileIOProvider
from zos.cobol.io.file_bindings import FileBindings
from zos.cobol.io.program_file import ProgramFile
from zos.cobol.io.record_format import FixedFormat, VariableFormat
from zos.cobol.io.record_key import RecordKey

_RDW = 4


def _format(frame: FileFrame) -> FixedFormat | VariableFormat:
    if frame.variable:
        return VariableFormat(frame.record_length + _RDW)
    return FixedFormat(frame.record_length)


class DdFileIOProvider(DatasetFileIOProvider):
    """One file per DDNAME, with no FDs: the declared frame's record format stands where a COBOL provider uses the FD, and picks the driver, so a record keeps its own length."""

    def __init__(
        self, base_dir: Path, bindings: FileBindings, relabeller: Relabeller
    ) -> None:
        super().__init__(base_dir, (), bindings, relabeller)

    def _appended(
        self, files: Sequence[ProgramFile], bindings: FileBindings
    ) -> frozenset[str]:
        return bindings.appended

    def _named(
        self, files: Sequence[ProgramFile], bindings: FileBindings
    ) -> tuple[tuple[str, Dataset], ...]:
        return tuple(bindings.datasets.items())

    def _admits(self, filename: str, mode: str, prime: RecordKey) -> bool:
        if not self._datasets.has(filename):
            return True
        return self._admits_sequential(filename, _format(self._frames[filename]), mode)

    def _driver_for(
        self, frame: FileFrame, path: Path, mode: OpenMode
    ) -> FileOrganizationDriver:
        return super(DatasetFileIOProvider, self)._driver_for(frame, path, mode)
