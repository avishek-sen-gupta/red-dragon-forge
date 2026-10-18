"""A file call goes to its own program's declarations; a program that declares none for a SELECT takes the dataset as its label says."""

from pathlib import Path

from catnip.dataset import Dataset
from catnip.labels import Label, RecordFormat, SequentialLabel
from cobol_asg.cobol_statements import FileControlEntry
from cobol_asg.file_enums import FileOrganization
from interpreter.cobol.access_result import AccessCondition
from interpreter.cobol.file_frame import FileFrame
from interpreter.cobol.io_provider import IOResult
from interpreter.cobol.prime_key import PrimeKey
from interpreter.data_value import DataRecord
from jackal.allocation import DatasetAllocation, DdEnvironment, Positioning
from jackal.cobol_files import ProgramFile
from jackal.model import DdName, DispAbnormal, DispNormal, ResolvedDisp
from jackal.program_files_provider import ProgramFilesIOProvider
from jackal.record_format import FixedFormat
from tests.covers import NotLanguageFeature, covers

_RECORD = "R" * 120


def _frame(record_length: int) -> DataRecord:
    return FileFrame(
        "INDD", FileOrganization.SEQUENTIAL, PrimeKey(), False, record_length
    ).data()


class _Unrelabelled:
    def relabel(self, dataset: Dataset, label: Label) -> None:
        raise AssertionError(f"{dataset.dsn} relabelled to {label}")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_an_undeclared_select_takes_the_dataset_its_dd_names_as_labelled(
    tmp_path: Path,
) -> None:
    path = tmp_path / "J.IN"
    path.write_bytes(_RECORD.encode("latin-1"))
    dataset = Dataset("J.IN", path, SequentialLabel(RecordFormat.F, 120))
    env = DdEnvironment(
        (
            (
                DdName("INDD"),
                DatasetAllocation(
                    dataset,
                    Positioning.START,
                    True,
                    ResolvedDisp(DispNormal.KEEP, DispAbnormal.KEEP),
                ),
            ),
        )
    )
    declared = ProgramFile(
        "DECLARER", FileControlEntry("INDD", "INDD"), FixedFormat(80)
    )
    provider = ProgramFilesIOProvider(
        tmp_path, ("DECLARER", "BARE"), (declared,), env, _Unrelabelled()
    )

    assert (
        provider._declare_file(_frame(80), "DECLARER"),
        provider._declare_file(_frame(120), "BARE"),
        provider._open_file("INDD", "INPUT", "DECLARER"),
        provider._open_file("INDD", "INPUT", "BARE"),
        provider._read_record("INDD", "", "BARE"),
        provider._close_file("INDD", "DECLARER"),
        provider._close_file("INDD", "BARE"),
    ) == (
        IOResult(AccessCondition.OK, None),
        IOResult(AccessCondition.OK, None),
        IOResult(AccessCondition.ATTRIBUTE_CONFLICT, None),
        IOResult(AccessCondition.OK, None),
        IOResult(AccessCondition.OK, _RECORD),
        IOResult(AccessCondition.NOT_OPEN, None),
        IOResult(AccessCondition.OK, None),
    )
