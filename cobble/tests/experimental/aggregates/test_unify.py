"""Unification through COMMAREA byte-offset matching."""

from __future__ import annotations

from pathlib import Path

from cobble.experimental.aggregates.unify import unify_fields

DATA = Path(__file__).parent / "data"


def _classes() -> dict[str, list[str]]:
    uf = unify_fields(
        aliases_path=DATA / "aliases.jsonl",
        extents_path=DATA / "extents.jsonl",
    )
    return uf.classes()


def _canon() -> dict[str, str]:
    classes = _classes()
    canon = {}
    for rep, members in classes.items():
        for m in members:
            canon[m] = rep
    return canon


def test_fields_at_same_commarea_offsets_are_unified() -> None:
    canon = _canon()
    assert canon.get("WS-COMM-AMOUNT") == canon.get("REC-AMOUNT")
    assert canon.get("WS-COMM-AMOUNT") == canon.get("ITEM-AMT")
    assert canon.get("WS-COMM-DATE") == canon.get("REC-DATE")
    assert canon.get("WS-COMM-DATE") == canon.get("ITEM-DTE")
    assert canon.get("WS-COMM-STATUS") == canon.get("REC-STATUS")
    assert canon.get("WS-COMM-STATUS") == canon.get("ITEM-STAT")


def test_unrelated_fields_are_not_unified() -> None:
    canon = _canon()
    amount_rep = canon.get("WS-COMM-AMOUNT")
    assert amount_rep is not None
    assert canon.get("WS-FLAG", "WS-FLAG") != amount_rep
    assert canon.get("WS-TOTAL", "WS-TOTAL") != amount_rep


def test_equivalence_class_sizes() -> None:
    classes = _classes()
    multi = {k: v for k, v in classes.items() if len(v) > 1}
    size_3 = [v for v in multi.values() if len(v) == 3]
    assert len(size_3) == 3
