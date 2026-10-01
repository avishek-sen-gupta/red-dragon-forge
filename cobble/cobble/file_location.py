"""FileLocation — the source file a knowledge-graph node is defined in, or an
explicit marker for why it has none.

Carried on GraphNode itself and serialised as two complementary fields of a
graph file's node row: ``file_path`` when there is a file, ``file_path_reason``
when there is not. Exactly one of the two is ever set; see
cobble.knowledge_graph.graph_file.

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


@dataclass(frozen=True)
class NoFileLocation:
    reason: FileLocationReason


FileLocation = Path | NoFileLocation

# What a node built without a CorpusIndex carries. Shared rather than
# constructed per node: it is the same statement every time.
NOT_ATTEMPTED = NoFileLocation(FileLocationReason.NOT_ATTEMPTED)
