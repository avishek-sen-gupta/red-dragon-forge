"""Scores each decompose round on held-out accuracy and the other axes of its factors' quality."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from itertools import groupby
from operator import itemgetter

import numpy as np
from cobble.experimental.aggregates.class_share import class_shares
from cobble.experimental.aggregates.decompose import (
    TOP_FIELDS,
    TOP_PARAGRAPHS,
    factorised,
    fitted_rounds,
    ranked,
)
from cobble.experimental.aggregates.fitted_round import FittedRound
from cobble.experimental.aggregates.matrix import IncidenceMatrix
from cobble.experimental.aggregates.nmf_settings import NmfSettings
from cobble.experimental.aggregates.program_columns import ProgramColumns
from cobble.experimental.aggregates.round_score import RoundScore
from cobble.experimental.aggregates.round_step import RoundStep
from numpy.typing import NDArray
from scipy.optimize import linear_sum_assignment
from scipy.sparse import csr_matrix
from sklearn.metrics import roc_auc_score

HELD_OUT = 0.1
SEEDS = 5
SUBSAMPLE = 0.9
PROGRAM_SEPARATOR = ":"
DRAWS = 8

_Loadings = NDArray[np.float64]
_Tops = tuple[tuple[int, ...], ...]


def _scored(
    used: _Loadings,
    made_of: _Loadings,
    rows: NDArray[np.int64],
    columns: NDArray[np.int64],
) -> _Loadings:
    return np.asarray(
        (used[rows] * made_of[:, columns].T).sum(axis=1), dtype=np.float64
    )


def program_columns(
    paragraphs: Sequence[tuple[str, str]],
    names: Sequence[str],
    programs: Mapping[str, frozenset[str]],
) -> ProgramColumns:
    owned = sorted(
        (program, column)
        for column, name in enumerate(names)
        for program in programs.get(name, frozenset({_program(name)}))
    )
    order = {program: i for i, program in enumerate(sorted({p for p, _ in owned}))}
    counts = np.bincount(
        np.array([order[p] for p, _ in owned], dtype=np.int64), minlength=len(order)
    ).astype(np.int64)
    return ProgramColumns(
        rows=np.array([order.get(p, -1) for p, _ in paragraphs], dtype=np.int64),
        starts=(np.cumsum(counts) - counts).astype(np.int64),
        counts=counts,
        columns=np.array([c for _, c in owned], dtype=np.int64),
    )


def same_program_negatives(
    residual: csr_matrix,
    rows: NDArray[np.int64],
    owned: ProgramColumns,
    rng: np.random.Generator,
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    entries = residual.tocoo()
    width = residual.get_shape()[1]
    usable = rows[owned.rows[rows] >= 0]
    program = owned.rows[usable]
    picks = rng.integers(0, owned.counts[program][:, None], size=(len(usable), DRAWS))
    columns = owned.columns[owned.starts[program][:, None] + picks]
    occupied = entries.row.astype(np.int64) * width + entries.col
    free = ~np.isin(usable[:, None] * width + columns, occupied)
    found = free.any(axis=1)
    return usable[found], columns[found, free.argmax(axis=1)[found]]


def _auc(fitted: FittedRound, settings: NmfSettings, owned: ProgramColumns) -> float:
    rng = np.random.default_rng(settings.seed)
    entries = fitted.residual.tocoo()
    count = max(1, round(entries.nnz * HELD_OUT))
    hidden = np.isin(
        np.arange(entries.nnz), rng.choice(entries.nnz, count, replace=False)
    )
    train = csr_matrix(
        (entries.data[~hidden], (entries.row[~hidden], entries.col[~hidden])),
        shape=fitted.residual.shape,
    )
    used, made_of = factorised(train, fitted.step.k, settings)[0]
    rows, columns = same_program_negatives(
        fitted.residual, entries.row[hidden].astype(np.int64), owned, rng
    )
    if not len(rows):
        return float("nan")
    positive = _scored(used, made_of, entries.row[hidden], entries.col[hidden])
    negative = _scored(used, made_of, rows, columns)
    labels = np.concatenate((np.ones(len(positive)), np.zeros(len(negative))))
    return float(roc_auc_score(labels, np.concatenate((positive, negative))))


def _unit(loadings: _Loadings) -> _Loadings:
    norms = np.linalg.norm(loadings, axis=1, keepdims=True)
    return loadings / np.maximum(norms, np.finfo(np.float64).tiny)


def _matched(reference: _Loadings, other: _Loadings) -> float:
    similar = _unit(reference) @ _unit(other).T
    rows, columns = linear_sum_assignment(-similar)
    return float(similar[rows, columns].mean())


def _refit(residual: csr_matrix, k: int, settings: NmfSettings, seed: int) -> _Loadings:
    kept = np.random.default_rng(seed).random(residual.get_shape()[0]) < SUBSAMPLE
    return factorised(residual[kept], k, replace(settings, seed=seed))[0][1]


def _stability(fitted: FittedRound, settings: NmfSettings) -> float:
    return float(
        np.mean(
            [
                _matched(
                    fitted.made_of,
                    _refit(fitted.residual, fitted.step.k, settings, settings.seed + s),
                )
                for s in range(1, SEEDS)
            ]
        )
    )


def _distinctness(made_of: _Loadings) -> float:
    if made_of.shape[0] < 2:
        return 0.0
    similar = _unit(made_of) @ _unit(made_of).T
    return float((similar - np.eye(made_of.shape[0]) * 2).max())


def _coverage(residual: csr_matrix, fields: _Tops, paragraphs: _Tops) -> float:
    entries = residual.tocoo()
    if not entries.nnz:
        return 0.0
    return float(
        np.logical_or.reduce(
            [
                np.isin(entries.col, columns) & np.isin(entries.row, rows)
                for columns, rows in zip(fields, paragraphs, strict=True)
            ]
        ).mean()
    )


def _held(row: _Loadings, top: tuple[int, ...]) -> float:
    total = float(row.sum())
    return float(row[list(top)].sum()) / total if total else 0.0


def _focus(made_of: _Loadings, fields: _Tops) -> float:
    return float(np.median([_held(made_of[f], top) for f, top in enumerate(fields)]))


def _program(field: str) -> str:
    return field.split(PROGRAM_SEPARATOR)[0]


def _spans(
    tops: _Tops, names: Sequence[str], programs: Mapping[str, frozenset[str]]
) -> tuple[int, ...]:
    return tuple(
        len(
            frozenset().union(
                *(programs.get(names[j], frozenset({_program(names[j])})) for j in top)
            )
        )
        for top in tops
    )


def _class_programs(unified: Mapping[str, str]) -> Mapping[str, frozenset[str]]:
    pairs = sorted((rep, _program(member)) for member, rep in unified.items())
    return {
        rep: frozenset(program for _, program in group)
        for rep, group in groupby(pairs, itemgetter(0))
    }


def _score(
    fitted: FittedRound,
    found: IncidenceMatrix,
    settings: NmfSettings,
    unified: Mapping[str, str],
) -> RoundScore:
    names = tuple(found.fields[i] for i in fitted.keep)
    fields = tuple(ranked(row, TOP_FIELDS) for row in fitted.made_of)
    paragraphs = tuple(ranked(column, TOP_PARAGRAPHS) for column in fitted.used.T)
    programs = _class_programs(unified)
    spans = _spans(fields, names, programs)
    mass = float(np.sqrt((fitted.residual.data**2).sum()))
    (share,) = class_shares(
        found, frozenset(unified.values()), (fitted.step.min_occurrences,)
    )
    return RoundScore(
        min_occurrences=fitted.step.min_occurrences,
        k=fitted.step.k,
        auc=_auc(fitted, settings, program_columns(found.paragraphs, names, programs)),
        fidelity=fitted.result.fit.reconstruction_error / mass if mass else 0.0,
        coverage=_coverage(fitted.residual, fields, paragraphs),
        stability=_stability(fitted, settings),
        distinctness=_distinctness(fitted.made_of),
        focus=_focus(fitted.made_of, fields),
        reach=sum(1 for span in spans if span > 1) / len(spans),
        programs=float(np.median(spans)),
        class_share=share.share,
    )


def round_scores(
    found: IncidenceMatrix,
    steps: Sequence[RoundStep],
    settings: NmfSettings,
    unified: Mapping[str, str],
) -> tuple[RoundScore, ...]:
    return tuple(
        _score(fitted, found, settings, unified)
        for fitted in fitted_rounds(found, steps, settings)
    )
