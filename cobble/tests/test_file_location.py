"""FileLocationReason -- why a node has no file, as distinct reasons.

A node with no file used to serialise as ``file_path: null`` and nothing
else, which made every reason for having no file look identical on the wire:
a program the corpus was missing read the same as a dataset that never has a
file at all. These tests pin that the reasons stay distinct; that each one
survives the graph file is pinned in tests/knowledge_graph/test_graph_file.py.
"""

from __future__ import annotations

from cobble.file_location import FileLocationReason


def test_the_reasons_are_distinguishable_from_one_another() -> None:
    """The whole point: these used to be one null."""
    assert len({reason.value for reason in FileLocationReason}) == len(
        FileLocationReason
    )


def test_a_kind_cobble_does_not_index_is_not_called_unresolved() -> None:
    """UNRESOLVED means "the corpus should have had this file and did not",
    which is a claim about the corpus. A kind cobble has no index for at all
    is a claim about cobble, and conflating them accuses a corpus of missing
    files it was never asked for."""
    assert FileLocationReason.NOT_INDEXED.value != FileLocationReason.UNRESOLVED.value


def test_a_node_built_without_a_corpus_index_says_so() -> None:
    """merge_graph builds endpoint nodes defensively, with no CorpusIndex in
    reach — that is neither a resolution failure nor a kind without files."""
    assert FileLocationReason.NOT_ATTEMPTED.value not in {
        FileLocationReason.UNRESOLVED.value,
        FileLocationReason.NOT_FILE_BASED.value,
    }
