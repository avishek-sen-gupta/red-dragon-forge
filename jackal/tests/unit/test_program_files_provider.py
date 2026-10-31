"""A file call goes to its own program's declarations, an HLASM call to the DD provider; a program that declares none for a SELECT takes the dataset as its label says."""

from functools import partial
from pathlib import Path

from catnip.dataset import Dataset, Relabeller
from catnip.labels import Label, RecordFormat, SequentialLabel
from cobol_asg.cobol_statements import FileControlEntry
from cobol_asg.file_enums import FileOrganization
from infrastructure.zos.access_methods.access_result import AccessCondition
from infrastructure.zos.access_methods.prime_key import PrimeKey
from interpreter.cobol.io_provider import IOResult
from interpreter.data_value import DataRecord
from interpreter.record_io.file_frame import FileFrame
from jackal.allocation import DatasetAllocation, DdEnvironment, Positioning
from jackal.cobol_files import AllocatedFileIOProvider, bindings_of
from jackal.model import DdName, DispAbnormal, DispNormal, ResolvedDisp
from tests.covers import NotLanguageFeature, covers
from zos.cobol.io.dd_files import DdFileIOProvider
from zos.cobol.io.program_file import ProgramFile
from zos.cobol.io.program_files import ProgramFilesIOProvider
from zos.cobol.io.record_format import FixedFormat
from zos.cobol.io.system_input import unsupplied

_RECORD = "R" * 120


def _frame(record_length: int) -> DataRecord:
    return FileFrame(
        "INDD", FileOrganization.SEQUENTIAL, PrimeKey(), False, record_length
    ).data()


class _Unrelabelled(Relabeller):
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
        ("DECLARER", "BARE"),
        partial(AllocatedFileIOProvider, tmp_path, env=env, relabeller=_Unrelabelled()),
        (declared,),
        DdFileIOProvider(tmp_path, bindings_of(env), _Unrelabelled()),
        unsupplied,
    )

    assert (
        provider._declare_file(_frame(80), "DECLARER"),
        provider._declare_file(_frame(120), "BARE"),
        provider._open_file("INDD", "INPUT", "DECLARER"),
        provider._open_file("INDD", "INPUT", "BARE"),
        provider._read_record("INDD", "", "BARE"),
        provider._key_of_reference("INDD", 1, "BARE"),
        provider._close_file("INDD", "DECLARER"),
        provider._close_file("INDD", "BARE"),
        provider._declare_file(_frame(120), ""),
        provider._open_file("INDD", "INPUT", ""),
        provider._read_record("INDD", "", ""),
        provider._close_file("INDD", ""),
    ) == (
        IOResult(AccessCondition.OK, None),
        IOResult(AccessCondition.OK, None),
        IOResult(AccessCondition.ATTRIBUTE_CONFLICT, None),
        IOResult(AccessCondition.OK, None),
        IOResult(AccessCondition.OK, _RECORD),
        IOResult(AccessCondition.OK, None),
        IOResult(AccessCondition.NOT_OPEN, None),
        IOResult(AccessCondition.OK, None),
        IOResult(AccessCondition.OK, None),
        IOResult(AccessCondition.OK, None),
        IOResult(AccessCondition.OK, _RECORD),
        IOResult(AccessCondition.OK, None),
    )
