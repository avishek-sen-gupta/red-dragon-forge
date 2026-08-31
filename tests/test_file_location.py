"""FileLocation -> the two fields nodes.jsonl carries for it.

A node with no file used to serialise as ``file_path: null`` and nothing
else, which made every reason for having no file look identical on the wire:
a program the corpus was missing read the same as a dataset that never has a
file at all. These tests pin that the reason survives serialisation, so a
consumer no longer has to re-derive it from the node's kind.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobble.file_location import (
    FileLocationReason,
    NoFileLocation,
    from_json,
    to_json_fields,
    to_json_path,
)


def test_a_resolved_path_has_no_reason() -> None:
    """The two fields are complementary: exactly one of them is ever set."""
    assert to_json_fields(Path("cbl/PROGONE.cbl")) == {
        "file_path": "cbl/PROGONE.cbl",
        "file_path_reason": None,
    }


@pytest.mark.parametrize("reason", list(FileLocationReason))
def test_every_reason_reaches_the_wire_under_its_own_name(
    reason: FileLocationReason,
) -> None:
    """Parametrized over the enum rather than a hand-listed set, so a reason
    added later cannot be silently unserialisable."""
    assert to_json_fields(NoFileLocation(reason)) == {
        "file_path": None,
        "file_path_reason": reason.value,
    }


def test_the_reasons_are_distinguishable_from_one_another() -> None:
    """The whole point: these three used to be one null."""
    wire = {
        to_json_fields(NoFileLocation(reason))["file_path_reason"]
        for reason in (
            FileLocationReason.UNRESOLVED,
            FileLocationReason.NOT_FILE_BASED,
            FileLocationReason.NO_DEFINITION_SOURCE,
        )
    }

    assert len(wire) == 3


def test_a_kind_cobble_does_not_index_is_not_called_unresolved() -> None:
    """UNRESOLVED means "the corpus should have had this file and did not",
    which is a claim about the corpus. A kind cobble has no index for at all
    is a claim about cobble, and conflating them accuses a corpus of missing
    files it was never asked for."""
    assert FileLocationReason.NOT_INDEXED.value != FileLocationReason.UNRESOLVED.value


@pytest.mark.parametrize("reason", list(FileLocationReason))
def test_a_reason_survives_the_round_trip(reason: FileLocationReason) -> None:
    location = NoFileLocation(reason)

    assert from_json(to_json_fields(location)) == location


def test_a_path_survives_the_round_trip() -> None:
    location = Path("cbl/PROGONE.cbl")

    assert from_json(to_json_fields(location)) == location


def test_a_row_that_gives_neither_a_path_nor_a_reason_says_so() -> None:
    """Rows written before file_path_reason existed. NOT_STATED rather than any
    of the substantive reasons: the writer did not say, and guessing which it
    was is exactly the re-derivation this field exists to remove."""
    assert from_json({"id": "PROGONE", "kind": "PROGRAM"}) == NoFileLocation(
        FileLocationReason.NOT_STATED
    )


def test_a_row_whose_fields_are_not_strings_reads_as_saying_nothing() -> None:
    """A writer bug, not a corpus problem: a malformed row must not abort a run
    that has already spent an hour reading a corpus."""
    assert from_json({"file_path": 7, "file_path_reason": []}) == NoFileLocation(
        FileLocationReason.NOT_STATED
    )


def test_a_schema_with_only_one_path_field_gets_a_string_either_way() -> None:
    """canonical_export's schema has nowhere to say why a node has no file, so
    it reads the path as a plain string and "" is the whole of "no file"."""
    assert to_json_path(Path("cbl/PROGONE.cbl")) == "cbl/PROGONE.cbl"
    assert to_json_path(NoFileLocation(FileLocationReason.UNRESOLVED)) == ""


def test_a_node_built_without_a_corpus_index_says_so() -> None:
    """merge_graph builds endpoint nodes defensively, with no CorpusIndex in
    reach — that is neither a resolution failure nor a kind without files."""
    assert FileLocationReason.NOT_ATTEMPTED.value not in {
        FileLocationReason.UNRESOLVED.value,
        FileLocationReason.NOT_FILE_BASED.value,
    }
