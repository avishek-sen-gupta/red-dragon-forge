"""How much of the matrix the unified classes' columns hold, per decompose threshold."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest
from scipy.sparse import csr_matrix

from cobble.experimental.aggregates import class_share_cli
from cobble.experimental.aggregates.matrix import IncidenceMatrix, save_matrix
from cobble.experimental.aggregates.unify import write_unified


def test_each_threshold_reports_its_columns_class_columns_and_their_share_of_entries(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    save_matrix(
        IncidenceMatrix(
            matrix=csr_matrix(
                np.array([[1, 1, 0, 0], [1, 1, 1, 0], [0, 0, 0, 1]], dtype=np.float32)
            ),
            fields=("A:R.X", "A:R.Y", "B:R.Z", "C:Q.W"),
            paragraphs=(("A", "P0"), ("A", "P1"), ("C", "P2")),
            occurrences=(2, 2, 1, 1),
        ),
        tmp_path / "matrix.npz",
        tmp_path / "meta.json",
    )
    write_unified(tmp_path / "unified.jsonl", (("A:R.X", "B:R.X"), ("B:R.Z", "D:R.Z")))

    with caplog.at_level(logging.INFO):
        assert (
            class_share_cli.main(
                [
                    "--matrix",
                    str(tmp_path / "matrix.npz"),
                    "--meta",
                    str(tmp_path / "meta.json"),
                    "--unified",
                    str(tmp_path / "unified.jsonl"),
                    "--min-occurrences",
                    "2",
                    "1",
                ]
            )
            == 0
        )

    assert [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("aggregate class share: min-occurrences")
    ] == [
        "aggregate class share: min-occurrences 2: 2 columns, 1 class columns, "
        "50.0% of their entries in class columns",
        "aggregate class share: min-occurrences 1: 4 columns, 2 class columns, "
        "50.0% of their entries in class columns",
    ]
