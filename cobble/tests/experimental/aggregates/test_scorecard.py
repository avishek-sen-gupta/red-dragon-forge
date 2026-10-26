"""The scorecard: per round, held-out accuracy and the axes of quality of its factors."""

from __future__ import annotations

import logging
from dataclasses import astuple
from pathlib import Path

import numpy as np
import pytest
from scipy.sparse import csr_matrix

from cobble.experimental.aggregates import scorecard_cli
from cobble.experimental.aggregates.matrix import (
    IncidenceMatrix,
    load_matrix,
    save_matrix,
)
from cobble.experimental.aggregates.nmf_settings import NmfSettings
from cobble.experimental.aggregates.round_step import RoundStep
from cobble.experimental.aggregates.scorecard import round_scores
from cobble.experimental.aggregates.unify import read_unified, write_unified

FIELDS = (
    *(f"A:R.F{i}" for i in range(5)),
    *(f"B:R.F{i}" for i in range(5, 10)),
    *(f"C:R.F{i}" for i in range(10, 14)),
)
BLOCKS = (
    (range(0, 5), range(0, 6)),
    (range(5, 10), range(6, 12)),
    (range(10, 14), range(12, 14)),
)


def _planted(tmp_path: Path) -> None:
    cells = np.zeros((14, 14), dtype=np.float32)
    for fields, paragraphs in BLOCKS:
        cells[np.ix_(list(paragraphs), list(fields))] = 1.0
    save_matrix(
        IncidenceMatrix(
            matrix=csr_matrix(cells),
            fields=FIELDS,
            paragraphs=tuple(("P", f"PARA-{i}") for i in range(14)),
            occurrences=(*(6 for _ in range(10)), *(2 for _ in range(4))),
        ),
        tmp_path / "matrix.npz",
        tmp_path / "meta.json",
    )
    write_unified(tmp_path / "unified.jsonl", (("A:R.F0", "Z:R.F0"),))


def test_planted_blocks_score_as_accurate_complete_stable_distinct_focused_factors(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _planted(tmp_path)

    with caplog.at_level(logging.INFO):
        assert (
            scorecard_cli.main(
                [
                    "--matrix",
                    str(tmp_path / "matrix.npz"),
                    "--meta",
                    str(tmp_path / "meta.json"),
                    "--unified",
                    str(tmp_path / "unified.jsonl"),
                    "--min-occurrences",
                    "4",
                    "--k",
                    "2",
                ]
            )
            == 0
        )

    (score,) = round_scores(
        load_matrix(tmp_path / "matrix.npz", tmp_path / "meta.json"),
        (RoundStep(min_occurrences=4, k=2),),
        NmfSettings(max_iter=500, seed=42),
        read_unified(tmp_path / "unified.jsonl"),
    )
    assert astuple(score) == pytest.approx(
        (4, 2, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.5, 1.5, 0.1), abs=0.01
    )
    assert [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("aggregate scorecard: round")
    ] == [
        "aggregate scorecard: round 1 (min-occurrences 4, k=2): held-out AUC 1.000",
        "aggregate scorecard: round 1: fidelity 0.000 relative error, coverage 100.0%, "
        "stability 1.000, distinctness 0.000, focus 1.000, "
        "reach 50.0% of factors across programs (median 1.5 programs), "
        "class share 10.0%",
    ]
