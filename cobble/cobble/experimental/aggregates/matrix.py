"""A paragraph x field matrix: which graph fields each paragraph reads or writes."""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
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
from scipy.sparse import coo_matrix, csr_matrix, load_npz, save_npz

logger = logging.getLogger(__name__)

_Paragraph = tuple[str, str]


@dataclass(frozen=True)
class IncidenceMatrix:
    """A 1 where a paragraph touches a field, the paragraph each row and the field each column stands for, how many paragraphs each field is written in, and the fewest a field needed to be kept."""

    matrix: csr_matrix
    fields: tuple[str, ...]
    paragraphs: tuple[_Paragraph, ...]
    occurrences: tuple[int, ...]
    min_occurrences: int


def _paragraph(node: str) -> str:
    return node.split("/")[0]


def _touches(
    row: DefLine,
    index: LeafIndex,
    canonical: Mapping[str, str],
    excluded: Sequence[re.Pattern[str]],
) -> Iterable[tuple[_Paragraph, str]]:
    fields = {
        canonical.get(leaf.node, leaf.declared)
        for leaf in index.fields_in(byte_range(row.extent, row.program))
        if not any(pattern.search(leaf.declared) for pattern in excluded)
    }
    places = {_paragraph(node) for node in (row.node, *row.definers)}
    return (
        ((row.program, place), field)
        for place in sorted(places)
        for field in sorted(fields)
    )


def paragraph_fields(
    rows: Iterable[DefLine],
    index: LeafIndex,
    canonical: Mapping[str, str],
    excluded: Sequence[re.Pattern[str]],
) -> Mapping[_Paragraph, frozenset[str]]:
    touched = sorted(
        touch for row in rows for touch in _touches(row, index, canonical, excluded)
    )
    return {
        paragraph: frozenset(field for _, field in group)
        for paragraph, group in groupby(touched, itemgetter(0))
    }


def _incidence(kept: Sequence[frozenset[str]], place: Mapping[str, int]) -> csr_matrix:
    hits = tuple(
        (row, place[field])
        for row, fields in enumerate(kept)
        for field in fields
        if field in place
    )
    return csr_matrix(
        coo_matrix(
            (
                np.ones(len(hits), dtype=np.float32),
                (
                    np.array([hit[0] for hit in hits], dtype=np.int64),
                    np.array([hit[1] for hit in hits], dtype=np.int64),
                ),
            ),
            shape=(len(kept), len(place)),
        )
    )


def incidence_matrix(
    paragraphs: Mapping[_Paragraph, frozenset[str]], min_occurrences: int
) -> IncidenceMatrix:
    kept = sorted(paragraphs.items())
    freq = Counter(field for _, fields in kept for field in fields)
    fields = tuple(sorted(f for f, seen in freq.items() if seen >= min_occurrences))
    matrix = _incidence(
        [found for _, found in kept], {field: i for i, field in enumerate(fields)}
    )
    logger.info(
        "aggregate matrix: %d paragraphs, %d fields, %d non-zeros",
        len(kept),
        len(fields),
        matrix.nnz,
    )
    return IncidenceMatrix(
        matrix=matrix,
        fields=fields,
        paragraphs=tuple(paragraph for paragraph, _ in kept),
        occurrences=tuple(freq[field] for field in fields),
        min_occurrences=min_occurrences,
    )


def save_matrix(found: IncidenceMatrix, matrix_path: Path, meta_path: Path) -> None:
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


def load_matrix(matrix_path: Path, meta_path: Path) -> IncidenceMatrix:
    meta = MatrixMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))
    return IncidenceMatrix(
        matrix=csr_matrix(load_npz(matrix_path)),
        fields=meta.fields,
        paragraphs=tuple((ref.program, ref.paragraph) for ref in meta.paragraphs),
        occurrences=meta.occurrences,
        min_occurrences=meta.min_occurrences,
    )
