"""A file call goes to its own program's declarations; a program that declares none for a SELECT takes the dataset as its label says."""

from pathlib import Path

from catnip.dataset import Dataset
from catnip.labels import Label, RecordFormat, SequentialLabel
from cobol_asg.cobol_statements import FileControlEntry
from interpreter.cobol.io_provider import IOResult
from jackal.allocation import DatasetAllocation, DdEnvironment, Positioning
from jackal.cobol_files import ProgramFile
from jackal.model import DdName, DispAbnormal, DispNormal, ResolvedDisp
from jackal.program_files_provider import ProgramFilesIOProvider
from jackal.record_format import FixedFormat
from tests.covers import NotLanguageFeature, covers

_RECORD = "R" * 120


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
        provider._open_file("INDD", "INPUT", 80, "SEQUENTIAL", 0, 0, "DECLARER"),
        provider._open_file("INDD", "INPUT", 120, "SEQUENTIAL", 0, 0, "BARE"),
        provider._read_record("INDD", "", "BARE"),
        provider._open_mode("INDD", "DECLARER"),
        provider._open_mode("INDD", "BARE"),
    ) == (
        IOResult("39", None),
        IOResult("00", None),
        IOResult("00", _RECORD),
        "",
        "INPUT",
    )
