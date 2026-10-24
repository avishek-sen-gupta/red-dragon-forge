"""A field x field positive PMI matrix over the paragraphs each graph field is read or written in."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import groupby
from operator import itemgetter
from pathlib import Path

import numpy as np
from cobble.dataflow.fields.extent_text import byte_range
from cobble.experimental.aggregates.def_line import DefLine
from cobble.experimental.aggregates.matrix_meta import MatrixMeta
from cobble.experimental.aggregates.paragraph_ref import ParagraphRef
from cobble.experimental.partition.leaf_index import LeafIndex
from scipy.sparse import coo_matrix, csr_matrix, load_npz, save_npz, triu

logger = logging.getLogger(__name__)

_Paragraph = tuple[str, str]


@dataclass(frozen=True)
class MatrixLimits:
    """The fewest fields a paragraph keeps, paragraphs a field appears in, and paragraphs a pair shares."""

    fields_per_paragraph: int
    occurrences: int
    cooccurrences: int


@dataclass(frozen=True)
class PpmiMatrix:
    """The symmetric matrix, the field each row stands for, the paragraphs it was counted over, how many of them each field is written in, and the fewest a field needed to be kept."""

    matrix: csr_matrix
    fields: tuple[str, ...]
    paragraphs: tuple[_Paragraph, ...]
    occurrences: tuple[int, ...]
    min_occurrences: int


def _paragraph(node: str) -> str:
    return node.split("/")[0]


def _touches(
    row: DefLine, index: LeafIndex, canonical: Mapping[str, str]
) -> Iterable[tuple[_Paragraph, str]]:
    fields = {
        canonical.get(leaf.node, leaf.declared)
        for leaf in index.fields_in(byte_range(row.extent, row.program))
    }
    places = {_paragraph(node) for node in (row.node, *row.definers)}
    return (
        ((row.program, place), field)
        for place in sorted(places)
        for field in sorted(fields)
    )


def paragraph_fields(
    rows: Iterable[DefLine], index: LeafIndex, canonical: Mapping[str, str]
) -> Mapping[_Paragraph, frozenset[str]]:
    touched = sorted(touch for row in rows for touch in _touches(row, index, canonical))
    return {
        paragraph: frozenset(field for _, field in group)
        for paragraph, group in groupby(touched, itemgetter(0))
    }


def _incidence(
    kept: Mapping[_Paragraph, frozenset[str]], place: Mapping[str, int]
) -> csr_matrix:
    hits = tuple(
        (row, place[field])
        for row, fields in enumerate(kept.values())
        for field in fields
        if field in place
    )
    return csr_matrix(
        coo_matrix(
            (
                np.ones(len(hits), dtype=np.int64),
                (
                    np.array([hit[0] for hit in hits], dtype=np.int64),
                    np.array([hit[1] for hit in hits], dtype=np.int64),
                ),
            ),
            shape=(len(kept), len(place)),
        )
    )


def _cells(
    kept: Mapping[_Paragraph, frozenset[str]],
    place: Mapping[str, int],
    limits: MatrixLimits,
) -> coo_matrix:
    incidence = _incidence(kept, place)
    freq = np.asarray(incidence.sum(axis=0), dtype=np.float64).ravel()
    pairs = coo_matrix(triu(incidence.T @ incidence, k=1))
    shared = pairs.data >= limits.cooccurrences
    first, second = pairs.row[shared], pairs.col[shared]
    weights = np.log2(
        pairs.data[shared] * float(len(kept)) / (freq[first] * freq[second])
    )
    positive = weights > 0
    rows, cols = first[positive], second[positive]
    return coo_matrix(
        (
            np.concatenate((weights[positive], weights[positive])).astype(np.float32),
            (np.concatenate((rows, cols)), np.concatenate((cols, rows))),
        ),
        shape=(len(place), len(place)),
    )


def ppmi_matrix(
    paragraphs: Mapping[_Paragraph, frozenset[str]], limits: MatrixLimits
) -> PpmiMatrix:
    kept = {
        paragraph: fields
        for paragraph, fields in paragraphs.items()
        if len(fields) >= limits.fields_per_paragraph
    }
    freq = Counter(field for fields in kept.values() for field in fields)
    fields = tuple(sorted(f for f, seen in freq.items() if seen >= limits.occurrences))
    place = {field: i for i, field in enumerate(fields)}
    matrix = csr_matrix(_cells(kept, place, limits))
    logger.info(
        "aggregate matrix: %d paragraphs, %d fields, %d non-zeros",
        len(kept),
        len(fields),
        matrix.nnz,
    )
    return PpmiMatrix(
        matrix=matrix,
        fields=fields,
        paragraphs=tuple(sorted(kept)),
        occurrences=tuple(freq[field] for field in fields),
        min_occurrences=limits.occurrences,
    )


def save_matrix(found: PpmiMatrix, matrix_path: Path, meta_path: Path) -> None:
    save_npz(matrix_path, found.matrix)
    meta = MatrixMeta(
        fields=found.fields,
        occurrences=found.occurrences,
        min_occurrences=found.min_occurrences,
        paragraphs=tuple(
            ParagraphRef(program=program, paragraph=paragraph)
            for program, paragraph in found.paragraphs
        ),
    )
    meta_path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")


def load_matrix(matrix_path: Path, meta_path: Path) -> PpmiMatrix:
    meta = MatrixMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))
    return PpmiMatrix(
        matrix=csr_matrix(load_npz(matrix_path)),
        fields=meta.fields,
        paragraphs=tuple((ref.program, ref.paragraph) for ref in meta.paragraphs),
        occurrences=meta.occurrences,
        min_occurrences=meta.min_occurrences,
    )
