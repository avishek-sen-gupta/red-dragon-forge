"""NMF decomposition of a field PPMI matrix into domain aggregate candidates."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from sklearn.decomposition import NMF

logger = logging.getLogger(__name__)


def nmf_sweep(
    matrix: csr_matrix,
    field_list: list[str],
    k_values: list[int],
    max_iter: int = 500,
    seed: int = 42,
) -> list[dict]:
    """Run NMF at each *k* and return interpreted factors per *k*."""
    results = []
    for k in k_values:
        model = NMF(
            n_components=k, init="nndsvda", max_iter=max_iter, random_state=seed
        )
        W = model.fit_transform(matrix)
        err = float(model.reconstruction_err_)
        logger.info("k=%d  error=%.2f  iters=%d", k, err, model.n_iter_)

        factors = _interpret_factors(W, field_list, top_n=20)
        results.append(
            {
                "k": k,
                "reconstruction_error": err,
                "n_iterations": int(model.n_iter_),
                "factors": factors,
            }
        )
    return results


def _interpret_factors(
    W: np.ndarray, field_list: list[str], top_n: int = 20
) -> list[dict]:
    factors = []
    for f_idx in range(W.shape[1]):
        col = W[:, f_idx]
        top_indices = np.argsort(col)[::-1][:top_n]

        top_fields = []
        all_names: list[str] = []
        for idx in top_indices:
            if col[idx] <= 0:
                break
            name = field_list[idx]
            top_fields.append({"field": name, "loading": round(float(col[idx]), 4)})
            all_names.append(name)

        record_prefixes: set[str] = set()
        for name in all_names:
            parts = name.split("-")
            if parts:
                record_prefixes.add(parts[0])

        factors.append(
            {
                "factor_id": f_idx,
                "top_fields": top_fields,
                "n_record_prefixes": len(record_prefixes),
                "record_prefixes": sorted(record_prefixes),
            }
        )
    return factors


def select_k(results: list[dict]) -> int:
    """Pick the *k* that maximises cross-record factors; break ties by smaller *k*."""

    def score(r: dict) -> tuple[int, int]:
        cross = sum(
            1 for f in r["factors"] if f["n_record_prefixes"] >= 4
        )
        return (cross, -r["k"])

    return max(results, key=score)["k"]


def write_results(out_dir: Path, results: list[dict]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    sweep = [
        {"k": r["k"], "reconstruction_error": r["reconstruction_error"]}
        for r in results
    ]
    (out_dir / "sweep.json").write_text(json.dumps(sweep, indent=2), encoding="utf-8")

    for r in results:
        path = out_dir / f"factors_k{r['k']}.json"
        path.write_text(json.dumps(r["factors"], indent=2), encoding="utf-8")

    best_k = select_k(results)
    report = {"recommended_k": best_k, "sweep": sweep}
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    logger.info("decompose: results written to %s (recommended k=%d)", out_dir, best_k)
