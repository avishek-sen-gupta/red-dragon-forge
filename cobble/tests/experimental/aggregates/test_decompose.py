"""NMF decomposition recovers planted block structure."""

from __future__ import annotations

import numpy as np
from scipy.sparse import csr_matrix

from cobble.experimental.aggregates.decompose import nmf_sweep


def test_nmf_recovers_two_planted_blocks() -> None:
    rng = np.random.default_rng(42)
    n = 10
    mat = np.zeros((n, n), dtype=np.float32)

    for i in range(5):
        for j in range(5):
            if i != j:
                mat[i, j] = 3.0 + rng.uniform(0, 0.5)

    for i in range(5, 10):
        for j in range(5, 10):
            if i != j:
                mat[i, j] = 3.0 + rng.uniform(0, 0.5)

    sparse_mat = csr_matrix(mat)
    fields = [f"FIELD-{i}" for i in range(n)]

    results = nmf_sweep(sparse_mat, fields, k_values=[2], max_iter=500, seed=42)
    assert len(results) == 1
    r = results[0]
    assert r["k"] == 2

    W = np.load(r["_W"]) if isinstance(r.get("_W"), str) else None

    factors = r["factors"]
    assert len(factors) == 2
    for fac in factors:
        top_field_ids = [int(f["field"].split("-")[1]) for f in fac["top_fields"][:5]]
        in_block_a = sum(1 for x in top_field_ids if x < 5)
        in_block_b = sum(1 for x in top_field_ids if x >= 5)
        assert in_block_a >= 4 or in_block_b >= 4, (
            f"factor should load on one block, got a={in_block_a} b={in_block_b}"
        )


def test_nmf_sweep_error_decreases_with_k() -> None:
    mat = csr_matrix(np.eye(5, dtype=np.float32) * 3.0)
    fields = [f"F{i}" for i in range(5)]
    results = nmf_sweep(mat, fields, k_values=[2, 3], max_iter=100, seed=0)
    assert len(results) == 2
    assert results[1]["reconstruction_error"] <= results[0]["reconstruction_error"]
