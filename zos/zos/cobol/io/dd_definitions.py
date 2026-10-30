"""HLASM's DD definitions from catalogued datasets: a sequential or pending dataset is a DD, its label giving RECFM and LRECL."""

from __future__ import annotations

from collections.abc import Mapping

from catnip.dataset import Dataset
from catnip.labels import DatasetLabel, LabelPending, RecordFormat, SequentialLabel
from interpreter.hlasm_run_inputs.dd_definition import DdDefinition
from interpreter.hlasm_run_inputs.record_format import RecordFormat as DcbRecordFormat

_DCB_RECFM: Mapping[RecordFormat, DcbRecordFormat] = {
    RecordFormat.F: DcbRecordFormat.F,
    RecordFormat.FB: DcbRecordFormat.FB,
    RecordFormat.V: DcbRecordFormat.V,
    RecordFormat.VB: DcbRecordFormat.VB,
}


def _supplied(label: DatasetLabel) -> bool:
    return isinstance(label, (SequentialLabel, LabelPending))


def _dd(dataset: Dataset) -> DdDefinition:
    match dataset.label:
        case SequentialLabel(recfm=recfm, lrecl=lrecl):
            return DdDefinition(dataset.path, _DCB_RECFM[recfm], lrecl)
        case _:
            return DdDefinition(dataset.path)


def dd_definitions(datasets: Mapping[str, Dataset]) -> Mapping[str, DdDefinition]:
    return {
        name: _dd(dataset)
        for name, dataset in datasets.items()
        if _supplied(dataset.label)
    }
