"""NMF decomposition of a field PPMI matrix into domain aggregate candidates."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from functools import reduce
from itertools import takewhile
from pathlib import Path

import numpy as np
from cobble.experimental.aggregates.factor import Factor
from cobble.experimental.aggregates.factor_field import FactorField
from cobble.experimental.aggregates.k_result import KResult
from cobble.experimental.aggregates.matrix import PpmiMatrix
from cobble.experimental.aggregates.nmf_settings import NmfSettings
from cobble.experimental.aggregates.round_result import RoundResult
from cobble.experimental.aggregates.round_step import RoundStep
from numpy.typing import NDArray
from pydantic import TypeAdapter
from scipy.sparse import coo_matrix, csr_matrix
from sklearn.decomposition import NMF

logger = logging.getLogger(__name__)

TOP_FIELDS = 20
PREFIX_SEPARATOR = "-"

_Loadings = NDArray[np.float64]
_ROUNDS: TypeAdapter[tuple[RoundResult, ...]] = TypeAdapter(tuple[RoundResult, ...])


def _top_fields(column: _Loadings, fields: Sequence[str]) -> tuple[FactorField, ...]:
    ranked = [int(i) for i in np.argsort(column)[::-1][:TOP_FIELDS]]
    return tuple(
        FactorField(field=fields[i], loading=round(float(column[i]), 4))
        for i in takewhile(lambda i: column[i] > 0, ranked)
    )


def _factor(index: int, column: _Loadings, fields: Sequence[str]) -> Factor:
    top = _top_fields(column, fields)
    prefixes = tuple(sorted({found.field.split(PREFIX_SEPARATOR)[0] for found in top}))
    return Factor(
        factor_id=index,
        top_fields=top,
        n_record_prefixes=len(prefixes),
        record_prefixes=prefixes,
    )


def _fit(
    target: _Loadings, fields: Sequence[str], k: int, settings: NmfSettings
) -> tuple[KResult, _Loadings]:
    model = NMF(init="nndsvda", max_iter=settings.max_iter, random_state=settings.seed)
    loadings: _Loadings = np.asarray(
        model.set_params(n_components=k).fit_transform(csr_matrix(target)),
        dtype=np.float64,
    )
    error = float(model.reconstruction_err_)
    logger.info("k=%d  error=%.2f  iters=%d", k, error, model.n_iter_)
    rebuilt = loadings @ np.asarray(model.components_, dtype=np.float64)
    return (
        KResult(
            k=k,
            reconstruction_error=error,
            n_iterations=int(model.n_iter_),
            factors=tuple(
                _factor(i, loadings[:, i], fields) for i in range(loadings.shape[1])
            ),
        ),
        rebuilt,
    )


def _lifted(rebuilt: _Loadings, keep: NDArray[np.int64], size: int) -> _Loadings:
    rows = np.repeat(keep, len(keep))
    columns = np.tile(keep, len(keep))
    return np.asarray(
        coo_matrix((rebuilt.ravel(), (rows, columns)), shape=(size, size)).toarray(),
        dtype=np.float64,
    )


def _round(
    state: tuple[tuple[RoundResult, ...], _Loadings],
    step: RoundStep,
    plan: tuple[_Loadings, PpmiMatrix, NmfSettings],
) -> tuple[tuple[RoundResult, ...], _Loadings]:
    done, explained = state
    whole, found, settings = plan
    keep = np.array(
        [i for i, n in enumerate(found.occurrences) if n >= step.min_occurrences]
    )
    block = np.ix_(keep, keep)
    target = whole[block]
    covered = float(np.minimum(target, explained[block]).sum())
    fit, rebuilt = _fit(
        np.clip(target - explained[block], 0, None),
        [found.fields[i] for i in keep],
        step.k,
        settings,
    )
    grown = explained + _lifted(rebuilt, keep, explained.shape[0])
    mass = float(target.sum())
    return (
        (
            *done,
            RoundResult(
                min_occurrences=step.min_occurrences,
                explained_by_earlier=covered / mass if mass else 0.0,
                fit=fit,
            ),
        ),
        grown,
    )


def rounds(
    found: PpmiMatrix, steps: Sequence[RoundStep], settings: NmfSettings
) -> tuple[RoundResult, ...]:
    """Each step factors the fields written in at least its threshold of paragraphs, after subtracting what earlier rounds explain."""
    whole: _Loadings = np.asarray(found.matrix.toarray(), dtype=np.float64)
    plan = (whole, found, settings)
    done, _ = reduce(
        lambda state, step: _round(state, step, plan),
        steps,
        ((), np.zeros_like(whole)),
    )
    return done


def write_rounds(out_dir: Path, found: Sequence[RoundResult]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "rounds.json"
    path.write_text(
        json.dumps(_ROUNDS.dump_python(tuple(found), mode="json"), indent=2),
        encoding="utf-8",
    )
    logger.info("decompose: %d rounds -> %s", len(found), path)
