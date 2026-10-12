"""A new dataset's label from its DD's DCB attributes over its model's label (JCL Ref, DCB parameter)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from jackal.labels import DatasetLabel, LabelPending, RecordFormat, SequentialLabel
from jackal.model import NullifiedValue
from jackal.value_parts import Value, resolve

T = TypeVar("T")

_BLOCKED = "B"
_FORMATS = frozenset({"F", "V"})


def _coded(value: Value | NullifiedValue) -> tuple[str, ...]:
    match value:
        case NullifiedValue() | ():
            return ()
        case _:
            return (resolve(value),)


def _record_format(text: str) -> tuple[RecordFormat, ...]:
    if text[:1] not in _FORMATS:
        return ()
    return (RecordFormat(text[:1] + (_BLOCKED if _BLOCKED in text[1:] else "")),)


def _record_length(text: str) -> tuple[int, ...]:
    return (int(text),) if text.isdigit() and int(text) > 0 else ()


def _chosen(
    coded: tuple[str, ...], parsed: Callable[[str], tuple[T, ...]], model: tuple[T, ...]
) -> tuple[T, ...]:
    return parsed(coded[0]) if coded else model


def _model_format(model: DatasetLabel) -> tuple[RecordFormat, ...]:
    match model:
        case SequentialLabel():
            return (model.recfm,)
        case _:
            return ()


def _model_length(model: DatasetLabel) -> tuple[int, ...]:
    match model:
        case SequentialLabel():
            return (model.lrecl,)
        case _:
            return ()


def coded_label(
    recfm: Value | NullifiedValue, lrecl: Value | NullifiedValue, model: DatasetLabel
) -> DatasetLabel:
    formats = _chosen(_coded(recfm), _record_format, _model_format(model))
    lengths = _chosen(_coded(lrecl), _record_length, _model_length(model))
    if not (formats and lengths):
        return LabelPending()
    return SequentialLabel(formats[0], lengths[0])
