"""Each sequential or pending dataset is an HLASM DD with its label's RECFM and LRECL; any other is left unsupplied."""

from pathlib import Path

from catnip.dataset import Dataset
from catnip.labels import KsdsLabel, LabelPending, RecordFormat, SequentialLabel
from interpreter.hlasm_run_inputs.dd_definition import DdDefinition
from interpreter.hlasm_run_inputs.record_format import RecordFormat as DcbRecordFormat
from tests.covers import NotLanguageFeature, covers
from zos.cobol.io.dd_definitions import dd_definitions


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_sequential_and_pending_datasets_are_dds_by_their_labels(
    tmp_path: Path,
) -> None:
    pa, pb, pp, pk = (tmp_path / name for name in ("A", "B", "P", "K"))

    assert dd_definitions(
        {
            "A": Dataset("J.A", pa, SequentialLabel(RecordFormat.FB, 80)),
            "B": Dataset("J.B", pb, SequentialLabel(RecordFormat.VB, 104)),
            "P": Dataset("J.P", pp, LabelPending()),
            "K": Dataset("J.K", pk, KsdsLabel(80, 0, 8)),
        }
    ) == {
        "A": DdDefinition(pa, DcbRecordFormat.FB, 80),
        "B": DdDefinition(pb, DcbRecordFormat.VB, 104),
        "P": DdDefinition(pp),
    }
