"""Union-find: find, union, classes, path compression."""

from __future__ import annotations

from cobble.experimental.aggregates.union_find import UnionFind


def test_find_creates_singleton() -> None:
    uf = UnionFind()
    assert uf.find("A") == "A"
    assert uf.find("B") == "B"


def test_union_merges_two_elements() -> None:
    uf = UnionFind()
    assert uf.union("A", "B") is True
    assert uf.find("A") == uf.find("B")


def test_union_returns_false_for_same_class() -> None:
    uf = UnionFind()
    uf.union("A", "B")
    assert uf.union("A", "B") is False


def test_transitive_union() -> None:
    uf = UnionFind()
    uf.union("A", "B")
    uf.union("B", "C")
    assert uf.find("A") == uf.find("C")


def test_classes_returns_groups() -> None:
    uf = UnionFind()
    uf.union("A", "B")
    uf.union("B", "C")
    uf.find("D")

    classes = uf.classes()
    merged = None
    for members in classes.values():
        if len(members) > 1:
            merged = members
    assert merged is not None
    assert set(merged) == {"A", "B", "C"}
    assert "D" in {m for members in classes.values() for m in members}


def test_path_compression() -> None:
    uf = UnionFind()
    for i in range(100):
        uf.union(f"N{i}", f"N{i + 1}")
    root = uf.find("N0")
    assert uf.find("N50") == root
    assert uf.find("N100") == root
