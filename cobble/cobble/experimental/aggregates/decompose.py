"""NMF decomposition of a paragraph x field matrix into domain aggregate candidates."""

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
from cobble.experimental.aggregates.factor_paragraph import FactorParagraph
from cobble.experimental.aggregates.k_result import KResult
from cobble.experimental.aggregates.matrix import IncidenceMatrix
from cobble.experimental.aggregates.nmf_settings import NmfSettings
from cobble.experimental.aggregates.round_result import RoundResult
from cobble.experimental.aggregates.round_step import RoundStep
from numpy.typing import NDArray
from pydantic import TypeAdapter
from scipy.sparse import coo_matrix, csr_matrix
from sklearn.decomposition import NMF

logger = logging.getLogger(__name__)

TOP_FIELDS = 20
TOP_PARAGRAPHS = 20
PREFIX_SEPARATOR = "-"

_Loadings = NDArray[np.float64]
_Names = tuple[Sequence[str], Sequence[tuple[str, str]]]
_ROUNDS: TypeAdapter[tuple[RoundResult, ...]] = TypeAdapter(tuple[RoundResult, ...])


def _ranked(column: _Loadings, top: int) -> tuple[int, ...]:
    ranked = [int(i) for i in np.argsort(column, kind="stable")[::-1][:top]]
    return tuple(takewhile(lambda i: column[i] > 0, ranked))


def _top_fields(column: _Loadings, fields: Sequence[str]) -> tuple[FactorField, ...]:
    return tuple(
        FactorField(field=fields[i], loading=round(float(column[i]), 4))
        for i in _ranked(column, TOP_FIELDS)
    )


def _top_paragraphs(
    column: _Loadings, paragraphs: Sequence[tuple[str, str]]
) -> tuple[FactorParagraph, ...]:
    return tuple(
        FactorParagraph(
            program=paragraphs[i][0],
            paragraph=paragraphs[i][1],
            loading=round(float(column[i]), 4),
        )
        for i in _ranked(column, TOP_PARAGRAPHS)
    )


def _factor(index: int, used: _Loadings, made_of: _Loadings, names: _Names) -> Factor:
    fields, paragraphs = names
    top = _top_fields(made_of, fields)
    prefixes = tuple(sorted({found.field.split(PREFIX_SEPARATOR)[0] for found in top}))
    return Factor(
        factor_id=index,
        top_fields=top,
        n_record_prefixes=len(prefixes),
        record_prefixes=prefixes,
        top_paragraphs=_top_paragraphs(used, paragraphs),
    )


def _fit(
    target: _Loadings, names: _Names, k: int, settings: NmfSettings
) -> tuple[KResult, _Loadings]:
    model = NMF(init="nndsvda", max_iter=settings.max_iter, random_state=settings.seed)
    used: _Loadings = np.asarray(
        model.set_params(n_components=k).fit_transform(csr_matrix(target)),
        dtype=np.float64,
    )
    made_of: _Loadings = np.asarray(model.components_, dtype=np.float64)
    error = float(model.reconstruction_err_)
    logger.info("k=%d  error=%.2f  iters=%d", k, error, model.n_iter_)
    return (
        KResult(
            k=k,
            reconstruction_error=error,
            n_iterations=int(model.n_iter_),
            factors=tuple(_factor(i, used[:, i], made_of[i], names) for i in range(k)),
        ),
        used @ made_of,
    )


def _lifted(
    rebuilt: _Loadings, keep: NDArray[np.int64], shape: tuple[int, int]
) -> _Loadings:
    rows = np.repeat(np.arange(shape[0]), len(keep))
    columns = np.tile(keep, shape[0])
    return np.asarray(
        coo_matrix((rebuilt.ravel(), (rows, columns)), shape=shape).toarray(),
        dtype=np.float64,
    )


def _opening(number: int, total: int, step: RoundStep, fields: int) -> None:
    logger.info(
        "decompose: round %d of %d: min-occurrences %d, %d fields, k=%d",
        number,
        total,
        step.min_occurrences,
        fields,
        step.k,
    )


def _share(covered: float, mass: float) -> float:
    return covered / mass if mass else 0.0


def _closing(number: int, total: int, share: float) -> None:
    logger.info(
        "decompose: round %d of %d: %.1f%% of its matrix explained by earlier rounds",
        number,
        total,
        100 * share,
    )


def _sliced(matrix: _Loadings, keep: NDArray[np.int64]) -> _Loadings:
    return matrix[:, keep]


def _round(
    state: tuple[tuple[RoundResult, ...], _Loadings],
    step: RoundStep,
    plan: tuple[_Loadings, IncidenceMatrix, NmfSettings, int],
) -> tuple[tuple[RoundResult, ...], _Loadings]:
    done, explained = state
    whole, found, settings, total = plan
    keep = np.array(
        [i for i, n in enumerate(found.occurrences) if n >= step.min_occurrences]
    )
    _opening(len(done) + 1, total, step, len(keep))
    target, before = _sliced(whole, keep), _sliced(explained, keep)
    fit, rebuilt = _fit(
        np.clip(target - before, 0, None),
        ([found.fields[i] for i in keep], found.paragraphs),
        step.k,
        settings,
    )
    share = _share(float(np.minimum(target, before).sum()), float(target.sum()))
    _closing(len(done) + 1, total, share)
    return (
        (
            *done,
            RoundResult(
                min_occurrences=step.min_occurrences,
                explained_by_earlier=share,
                fit=fit,
            ),
        ),
        explained + _lifted(rebuilt, keep, (explained.shape[0], explained.shape[1])),
    )


def rounds(
    found: IncidenceMatrix, steps: Sequence[RoundStep], settings: NmfSettings
) -> tuple[RoundResult, ...]:
    """Each step factors the fields written in at least its threshold of paragraphs, after subtracting what earlier rounds explain."""
    whole: _Loadings = np.asarray(found.matrix.toarray(), dtype=np.float64)
    plan = (whole, found, settings, len(steps))
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
