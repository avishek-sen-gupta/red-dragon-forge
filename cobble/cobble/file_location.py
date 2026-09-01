"""FileLocation — the source file a knowledge-graph node is defined in, or an
explicit marker for why it has none.

Carried on GraphNode itself and serialised as two complementary fields of
nodes.jsonl: ``file_path`` when there is a file, ``file_path_reason`` when
there is not. Exactly one of the two is ever set.

The reason used to stop here, inside the build: every NoFileLocation
collapsed to ``file_path: null`` and nothing else, so a program the corpus
was missing looked exactly like a dataset that never has a file. A consumer
could still recover the reason, but only by re-deriving it from the node's
kind against CorpusIndex's resolver table -- knowledge that lives in
cobble's source, not in cobble's output, and that goes stale the moment a
resolver changes. Stating it per node moves that table from the reader to
the writer, which is where it can be kept true.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class FileLocationReason(Enum):
    # e.g. DATASET — a physical dataset name is referenced from many DDs
    # across possibly many JCL files; there is no single file it is
    # "defined" in.
    NOT_FILE_BASED = "not_file_based"
    # e.g. a TRANSACTION or CICS_FILE with no CSD configured/matching for
    # this corpus — legitimately undefined, not a resolution failure.
    NO_DEFINITION_SOURCE = "no_definition_source"
    # This kind is normally file-based and CorpusIndex expected to find one,
    # but couldn't (e.g. a COPY target not present in any copybook_dir, or a
    # CALL target program not present in the corpus). Worth logging.
    UNRESOLVED = "unresolved"
    # e.g. BMS_MAP — file-based in principle, but cobble keeps no index for
    # the kind, so no lookup was even possible. Distinct from UNRESOLVED,
    # which asserts the corpus was missing a file it should have had: this
    # says nothing about the corpus, only about cobble.
    NOT_INDEXED = "not_indexed"
    # A node built with no CorpusIndex in reach — merge_graph's defensive
    # endpoint nodes, and hand-built fixtures. Neither a resolution failure
    # nor a kind without files: simply never asked.
    NOT_ATTEMPTED = "not_attempted"
    # Read back from a nodes.jsonl written before this field existed, where a
    # missing file was a bare ``file_path: null``. The reason was known when
    # that file was built and thrown away, so it cannot be recovered here —
    # saying which one it was would be the guess this field exists to avoid.
    NOT_STATED = "not_stated"


@dataclass(frozen=True)
class NoFileLocation:
    reason: FileLocationReason


FileLocation = Path | NoFileLocation

# What a node built without a CorpusIndex carries. Shared rather than
# constructed per node: it is the same statement every time.
NOT_ATTEMPTED = NoFileLocation(FileLocationReason.NOT_ATTEMPTED)


def to_json_fields(location: FileLocation) -> Mapping[str, object]:
    """The two nodes.jsonl fields a location writes: the path, and why not.

    Both keys are always present -- one of them null -- so every node row has
    the same shape and a consumer can read ``file_path_reason`` without first
    checking whether this writer emitted it. Typed to ``object`` rather than
    ``str | None`` because these are JSON values on their way to json.dumps,
    where the absent one is a null and not a Python-side optional to unwrap.
    """
    match location:
        case Path():
            return {"file_path": str(location), "file_path_reason": None}
        case NoFileLocation(reason=reason):
            return {"file_path": None, "file_path_reason": reason.value}


def to_json_path(location: FileLocation) -> str:
    """The path as a string, empty when there is none.

    For a consumer whose own schema has a single path field and nowhere to put
    a reason -- canonical_export's, today. Empty string rather than None so the
    caller has one type to handle: no file and an unnamed file are the same
    thing to a schema that cannot say why.
    """
    match location:
        case Path():
            return str(location)
        case NoFileLocation():
            return ""


def from_json(row: Mapping[str, object]) -> FileLocation:
    """A location read back from a nodes.jsonl row.

    Takes the whole row rather than its two fields so that "the file did not
    say" is one case here instead of an optional at every call site. A row
    written before ``file_path_reason`` existed is NOT_STATED rather than an
    error: those rows are the entire installed base until a corpus is rebuilt.
    A non-string in either field would be a writer bug and reads as absent,
    which keeps a malformed row from aborting a whole corpus run.
    """
    match (row.get("file_path"), row.get("file_path_reason")):
        case (str() as path, _):
            return Path(path)
        case (_, str() as reason):
            return NoFileLocation(FileLocationReason(reason))
        case _:
            return NoFileLocation(FileLocationReason.NOT_STATED)
