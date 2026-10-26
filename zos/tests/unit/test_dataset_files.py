"""A catalogued dataset opens by its ASSIGN name, and an FD its label contradicts fails with status 39."""

from pathlib import Path

from catnip.dataset import Dataset
from catnip.labels import Label, RecordFormat, SequentialLabel
from cobol_asg.cobol_statements import FileControlEntry
from cobol_asg.file_enums import FileOrganization
from infrastructure.zos.access_methods.prime_key import PrimeKey
from interpreter.cobol.outcome_status import OUTCOME_STATUS
from interpreter.record_io.file_frame import FileFrame
from tests.covers import NotLanguageFeature, covers
from zos.cobol.io.dataset_files import DatasetFileIOProvider
from zos.cobol.io.file_bindings import FileBindings
from zos.cobol.io.program_file import ProgramFile
from zos.cobol.io.record_format import FixedFormat

_RECORD = "R" * 80


class _Unrelabelled:
    def relabel(self, dataset: Dataset, label: Label) -> None:
        raise AssertionError(f"{dataset.dsn} relabelled to {label}")


def _status(base_dir: Path, bindings: FileBindings, lrecl: int) -> str:
    provider = DatasetFileIOProvider(
        base_dir,
        (
            ProgramFile(
                "READER", FileControlEntry("INFILE", "INDD"), FixedFormat(lrecl)
            ),
        ),
        bindings,
        _Unrelabelled(),
    )
    provider._declare_file(
        FileFrame(
            "INFILE", FileOrganization.SEQUENTIAL, PrimeKey(), False, lrecl
        ).data(),
        "READER",
    )
    return OUTCOME_STATUS[
        provider._open_file("INFILE", "INPUT", "READER").condition.position()
    ]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_catalogued_dataset_opens_by_its_assign_name_and_a_contradicting_fd_fails_39(
    tmp_path: Path,
) -> None:
    path = tmp_path / "Z.IN"
    path.write_bytes(_RECORD.encode("latin-1"))
    bindings = FileBindings(
        paths={"INDD": path},
        appended=frozenset(),
        datasets={"INDD": Dataset("Z.IN", path, SequentialLabel(RecordFormat.F, 80))},
    )

    assert (_status(tmp_path, bindings, 80), _status(tmp_path, bindings, 79)) == (
        "00",
        "39",
    )
