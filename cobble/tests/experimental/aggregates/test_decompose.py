"""NMF rounds: the strict fields' factors, then factors of what they leave in the looser fields."""

from __future__ import annotations

from dataclasses import replace
import logging
from pathlib import Path

import numpy as np
import pytest
from scipy.sparse import csr_matrix

from cobble.experimental.aggregates import decompose_cli
from cobble.experimental.aggregates.decompose import rounds
from cobble.experimental.aggregates.factor import Factor
from cobble.experimental.aggregates.matrix import IncidenceMatrix, save_matrix
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
        min_occurrences=2,
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


def test_a_round_below_the_matrix_s_own_threshold_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    built = replace(_planted(), min_occurrences=4)
    save_matrix(built, tmp_path / "m.npz", tmp_path / "meta.json")

    with pytest.raises(SystemExit) as refused:
        decompose_cli.main(
            [
                "--matrix",
                str(tmp_path / "m.npz"),
                "--meta",
                str(tmp_path / "meta.json"),
                "--min-occurrences",
                "4",
                "2",
                "--k",
                "2",
                "1",
                "--out-dir",
                str(tmp_path / "out"),
            ]
        )

    assert refused.value.code == 2
    assert capsys.readouterr().err.splitlines()[-1] == (
        "cobble-experimental-aggregate-decompose: error: the matrix was built at "
        "--min-occurrences 4, so a round at 2 sees no more fields; rebuild it at 2"
    )
