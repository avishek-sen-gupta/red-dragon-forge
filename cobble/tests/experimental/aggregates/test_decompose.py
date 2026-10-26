"""NMF rounds: the strict fields' factors, then factors of what they leave in the looser fields."""

from __future__ import annotations

import logging
import tracemalloc

import numpy as np
import pytest
from scipy.sparse import csr_matrix

from cobble.experimental.aggregates.decompose import rounds
from cobble.experimental.aggregates.factor import Factor
from cobble.experimental.aggregates.matrix import IncidenceMatrix
from cobble.experimental.aggregates.nmf_settings import NmfSettings
from cobble.experimental.aggregates.round_step import RoundStep

SETTINGS = NmfSettings(max_iter=500, seed=42)
BLOCKS = (
    (range(0, 5), range(0, 6)),
    (range(5, 10), range(6, 12)),
    (range(10, 14), range(12, 14)),
)


def _planted() -> IncidenceMatrix:
    mat = np.zeros((14, 14), dtype=np.float64)
    for fields, paragraphs in BLOCKS:
        mat[np.ix_(list(paragraphs), list(fields))] = 1.0
    return IncidenceMatrix(
        matrix=csr_matrix(mat),
        fields=tuple(f"FIELD-{i}" for i in range(14)),
        paragraphs=tuple(("P", f"PARA-{i}") for i in range(14)),
        occurrences=(*(6 for _ in range(10)), *(2 for _ in range(4))),
    )


def _block(factor: Factor) -> tuple[frozenset[int], frozenset[int]]:
    fields = frozenset(int(found.field.split("-")[1]) for found in factor.top_fields)
    paragraphs = frozenset(
        int(found.paragraph.split("-")[1]) for found in factor.top_paragraphs
    )
    return fields, paragraphs


def _planted_block(number: int) -> tuple[frozenset[int], frozenset[int]]:
    fields, paragraphs = BLOCKS[number]
    return frozenset(fields), frozenset(paragraphs)


def test_one_round_recovers_the_planted_blocks_of_the_strict_fields() -> None:
    (only,) = rounds(_planted(), (RoundStep(min_occurrences=4, k=2),), SETTINGS)

    assert (only.min_occurrences, only.explained_by_earlier, only.fit.k) == (4, 0.0, 2)
    assert {_block(factor) for factor in only.fit.factors} == {
        _planted_block(0),
        _planted_block(1),
    }
    assert {found.program for f in only.fit.factors for found in f.top_paragraphs} == {
        "P"
    }


def test_a_later_round_factors_what_the_strict_round_leaves_in_the_looser_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(
        logging.INFO, logger="cobble.experimental.aggregates.decompose"
    ):
        first, second = rounds(
            _planted(),
            (RoundStep(min_occurrences=4, k=2), RoundStep(min_occurrences=2, k=1)),
            SETTINGS,
        )

    (left,) = second.fit.factors
    assert (first.min_occurrences, second.min_occurrences) == (4, 2)
    assert _block(left) == _planted_block(2)
    assert second.explained_by_earlier == pytest.approx(60 / 68, abs=0.01)
    assert [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("decompose: round")
    ] == [
        "decompose: round 1 of 2: min-occurrences 4, 10 fields, k=2",
        "decompose: round 1 of 2: 0.0% of its matrix explained by earlier rounds",
        "decompose: round 2 of 2: min-occurrences 2, 14 fields, k=1",
        f"decompose: round 2 of 2: {second.explained_by_earlier:.1%} of its matrix explained by earlier rounds",
    ]


def test_rounds_hold_memory_for_the_matrix_non_zeros_not_its_every_cell() -> None:
    planted = _planted().matrix.tocoo()
    paragraphs, fields = 2000, 20000
    wide = IncidenceMatrix(
        matrix=csr_matrix(
            (planted.data, (planted.row, planted.col)), shape=(paragraphs, fields)
        ),
        fields=tuple(f"FIELD-{i}" for i in range(fields)),
        paragraphs=tuple(("P", f"PARA-{i}") for i in range(paragraphs)),
        occurrences=(*_planted().occurrences, *(0 for _ in range(fields - 14))),
    )

    tracemalloc.start()
    first, second = rounds(
        wide,
        (RoundStep(min_occurrences=4, k=2), RoundStep(min_occurrences=2, k=1)),
        SETTINGS,
    )
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert {_block(factor) for factor in first.fit.factors} == {
        _planted_block(0),
        _planted_block(1),
    }
    assert [_block(factor) for factor in second.fit.factors] == [_planted_block(2)]
    assert peak < paragraphs * fields * 8 // 10
