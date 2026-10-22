"""PPMI matrix construction from defs + unification."""

from __future__ import annotations

from pathlib import Path

from cobble.experimental.aggregates.matrix import build_ppmi_matrix
from cobble.experimental.aggregates.unify import unify_fields, read_unified, write_unified

DATA = Path(__file__).parent / "data"


def _unified_canon() -> dict[str, str]:
    uf = unify_fields(
        aliases_path=DATA / "aliases.jsonl",
        extents_path=DATA / "extents.jsonl",
    )
    canon: dict[str, str] = {}
    for rep, members in uf.classes().items():
        for m in members:
            canon[m] = rep
    return canon


def test_matrix_is_square_and_symmetric() -> None:
    mat, field_list, para_list, stats = build_ppmi_matrix(
        defs_path=DATA / "defs.jsonl",
        canonical_map=_unified_canon(),
        min_fields_per_para=2,
        min_occurrences=2,
        min_cooccurrences=2,
    )
    assert mat.shape[0] == mat.shape[1]
    diff = abs(mat - mat.T)
    assert diff.max() < 1e-6


def test_cooccurring_fields_have_positive_ppmi() -> None:
    canon = _unified_canon()
    mat, field_list, para_list, stats = build_ppmi_matrix(
        defs_path=DATA / "defs.jsonl",
        canonical_map=canon,
        min_fields_per_para=1,
        min_occurrences=1,
        min_cooccurrences=1,
    )
    field_idx = {f: i for i, f in enumerate(field_list)}
    amount_rep = canon.get("WS-COMM-AMOUNT", "WS-COMM-AMOUNT")
    date_rep = canon.get("WS-COMM-DATE", "WS-COMM-DATE")

    assert amount_rep in field_idx, f"{amount_rep} not in field list"
    assert date_rep in field_idx, f"{date_rep} not in field list"
    i = field_idx[amount_rep]
    j = field_idx[date_rep]
    assert mat[i, j] > 0, "amount and date should have positive PPMI"


def test_matrix_has_no_negative_entries() -> None:
    mat, field_list, para_list, stats = build_ppmi_matrix(
        defs_path=DATA / "defs.jsonl",
        canonical_map=_unified_canon(),
        min_fields_per_para=2,
        min_occurrences=2,
        min_cooccurrences=2,
    )
    assert mat.min() >= 0
