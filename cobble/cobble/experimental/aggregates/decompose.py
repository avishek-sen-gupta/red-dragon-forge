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
from cobble.experimental.aggregates.fitted_round import FittedRound
from cobble.experimental.aggregates.k_result import KResult
from cobble.experimental.aggregates.matrix import IncidenceMatrix
from cobble.experimental.aggregates.nmf_settings import NmfSettings
from cobble.experimental.aggregates.round_result import RoundResult
from cobble.experimental.aggregates.round_step import RoundStep
from numpy.typing import NDArray
from pydantic import TypeAdapter
from scipy.sparse import csr_matrix
from sklearn.decomposition import NMF

logger = logging.getLogger(__name__)

TOP_FIELDS = 20
TOP_PARAGRAPHS = 20
PREFIX_SEPARATOR = "-"

_Loadings = NDArray[np.float64]
_Names = tuple[Sequence[str], Sequence[tuple[str, str]]]
_Factors = tuple[_Loadings, _Loadings]
_Earlier = tuple[_Factors, NDArray[np.int64]]
_Entries = tuple[NDArray[np.int32], NDArray[np.int64]]
_ROUNDS: TypeAdapter[tuple[RoundResult, ...]] = TypeAdapter(tuple[RoundResult, ...])


def ranked(column: _Loadings, top: int) -> tuple[int, ...]:
    order = [int(i) for i in np.argsort(column, kind="stable")[::-1][:top]]
    return tuple(takewhile(lambda i: column[i] > 0, order))


def _top_fields(column: _Loadings, fields: Sequence[str]) -> tuple[FactorField, ...]:
    return tuple(
        FactorField(field=fields[i], loading=round(float(column[i]), 4))
        for i in ranked(column, TOP_FIELDS)
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
        for i in ranked(column, TOP_PARAGRAPHS)
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


def reconstruction_error(
    target: csr_matrix, used: _Loadings, made_of: _Loadings
) -> float:
    entries = target.tocoo()
    cross = sum(
        float((entries.data * used[entries.row, i] * made_of[i, entries.col]).sum())
        for i in range(used.shape[1])
    )
    rebuilt = float(np.sum((used.T @ used) * (made_of @ made_of.T)))
    return float(
        np.sqrt(max(0.0, float((entries.data**2).sum()) - 2 * cross + rebuilt))
    )


def factorised(
    target: csr_matrix, k: int, settings: NmfSettings
) -> tuple[_Factors, float, int]:
    model = NMF(init="nndsvda", max_iter=settings.max_iter, random_state=settings.seed)
    used: _Loadings = np.asarray(
        model.set_params(n_components=k).fit_transform(target), dtype=np.float64
    )
    made_of: _Loadings = np.asarray(model.components_, dtype=np.float64)
    error = reconstruction_error(target, used, made_of)
    return (used, made_of), error, int(model.n_iter_)


def _fit(
    target: csr_matrix, names: _Names, k: int, settings: NmfSettings
) -> tuple[KResult, _Factors]:
    (used, made_of), error, iterations = factorised(target, k, settings)
    logger.info("k=%d  error=%.2f  iters=%d", k, error, iterations)
    return (
        KResult(
            k=k,
            reconstruction_error=error,
            n_iterations=iterations,
            factors=tuple(_factor(i, used[:, i], made_of[i], names) for i in range(k)),
        ),
        (used, made_of),
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


def _rebuilt_at(earlier: _Earlier, entries: _Entries) -> _Loadings:
    (used, made_of), kept = earlier
    rows, columns = entries
    place = np.minimum(np.searchsorted(kept, columns), len(kept) - 1)
    hit = kept[place] == columns
    return hit * sum(
        (used[rows, i] * made_of[i, place] for i in range(used.shape[1])),
        np.zeros(len(rows)),
    )


def _explained_at(earlier: Sequence[_Earlier], entries: _Entries) -> _Loadings:
    return sum(
        (_rebuilt_at(found, entries) for found in earlier), np.zeros(len(entries[0]))
    )


def _residual(target: csr_matrix, before: _Loadings) -> csr_matrix:
    entries = target.tocoo()
    left = csr_matrix(
        (np.clip(entries.data - before, 0, None), (entries.row, entries.col)),
        shape=target.shape,
    )
    left.eliminate_zeros()
    return left


def _earlier(done: Sequence[FittedRound]) -> tuple[_Earlier, ...]:
    return tuple(((found.used, found.made_of), found.keep) for found in done)


def _round(
    done: tuple[FittedRound, ...],
    step: RoundStep,
    plan: tuple[IncidenceMatrix, NmfSettings, int],
) -> tuple[FittedRound, ...]:
    found, settings, total = plan
    keep = np.array(
        [i for i, n in enumerate(found.occurrences) if n >= step.min_occurrences],
        dtype=np.int64,
    )
    _opening(len(done) + 1, total, step, len(keep))
    target = csr_matrix(found.matrix[:, keep], dtype=np.float64)
    entries = target.tocoo()
    before = _explained_at(_earlier(done), (entries.row, keep[entries.col]))
    residual = _residual(target, before)
    fit, (used, made_of) = _fit(
        residual,
        ([found.fields[i] for i in keep], found.paragraphs),
        step.k,
        settings,
    )
    share = _share(float(np.minimum(entries.data, before).sum()), float(target.sum()))
    _closing(len(done) + 1, total, share)
    return (
        *done,
        FittedRound(
            step=step,
            keep=keep,
            residual=residual,
            used=used,
            made_of=made_of,
            result=RoundResult(
                min_occurrences=step.min_occurrences,
                explained_by_earlier=share,
                fit=fit,
            ),
        ),
    )


def fitted_rounds(
    found: IncidenceMatrix, steps: Sequence[RoundStep], settings: NmfSettings
) -> tuple[FittedRound, ...]:
    plan = (found, settings, len(steps))
    return reduce(lambda done, step: _round(done, step, plan), steps, ())


def rounds(
    found: IncidenceMatrix, steps: Sequence[RoundStep], settings: NmfSettings
) -> tuple[RoundResult, ...]:
    """Each step factors the fields written in at least its threshold of paragraphs, after subtracting what earlier rounds explain."""
    return tuple(done.result for done in fitted_rounds(found, steps, settings))


def write_rounds(out_dir: Path, found: Sequence[RoundResult]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "rounds.json"
    path.write_text(
        json.dumps(_ROUNDS.dump_python(tuple(found), mode="json"), indent=2),
        encoding="utf-8",
    )
    logger.info("decompose: %d rounds -> %s", len(found), path)
