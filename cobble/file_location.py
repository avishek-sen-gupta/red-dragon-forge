"""FileLocation — the source file a knowledge-graph node is defined in, or an
explicit marker for why it has none.

Used internally by CorpusIndex (resolution) and the node-construction call
sites it feeds — never on the wire. GraphWriter collapses a FileLocation to
plain ``str | None`` when it writes a node to nodes.jsonl, so the JSONL
schema is unchanged; pattern-matching on FileLocation only matters while a
node is being built, e.g. to decide whether an UNRESOLVED result is worth a
log line.
"""

from __future__ import annotations

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


@dataclass(frozen=True)
class NoFileLocation:
    reason: FileLocationReason


FileLocation = Path | NoFileLocation


def to_json_value(location: FileLocation) -> str | None:
    """Collapse a FileLocation to the str | None nodes.jsonl serializes."""
    match location:
        case Path():
            return str(location)
        case NoFileLocation():
            return None
