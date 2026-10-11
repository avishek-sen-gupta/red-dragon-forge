"""A dataset: its name, the file holding its bytes, and its label."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cobol_asg.file_enums import FileOrganization, OpenMode
from interpreter.cobol.file_drivers import FileOrganizationDriver, open_driver
from jackal.labels import DatasetLabel, KsdsLabel, LabelPending, SequentialLabel


@dataclass(frozen=True)
class Dataset:
    dsn: str
    path: Path
    label: DatasetLabel

    def record_size(self) -> int:
        match self.label:
            case SequentialLabel() | KsdsLabel():
                return self.label.lrecl
            case LabelPending():
                return 0

    def opened(self, mode: OpenMode, record_size: int) -> FileOrganizationDriver:
        match self.label:
            case KsdsLabel():
                return open_driver(
                    FileOrganization.INDEXED,
                    self.path,
                    mode,
                    record_size,
                    self.label.key_offset,
                    self.label.key_length,
                )
            case SequentialLabel() | LabelPending():
                return open_driver(
                    FileOrganization.SEQUENTIAL, self.path, mode, record_size, 0, 0
                )
