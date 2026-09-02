"""CorpusIndex — resolves (NodeKind, id) -> FileLocation once per run.

Built before any extractor runs, so every node-construction call site
(across the JCL, CALL/COPY, CICS-flow and batch-file extractors, plus
GraphWriter's own defensive endpoint-stub synthesis) resolves a given node's
file_path identically no matter which extractor or what order constructs it
first. That determinism is what lets GraphWriter stream nodes the same way
it already streams edges, instead of buffering everything in memory to merge
whichever occurrence happened to carry the real file_path (see
knowledge_graph/graph_writer.py).

This module is the lookup only: finished mappings in, FileLocation out. Reading
the corpus to populate them lives in corpus_index_builder, which is imported by
build_graph and nothing else. The split is not cosmetic -- the reading needs the
JCL and CSD parsers, i.e. cobble.jcl and cobble.cics, and every consumer of
the index lives in one of those two packages. With both halves in one module
that was a genuine import cycle (jackal.jcl_graph -> corpus_index ->
jackal.jcl_graph), held apart only by the consumers' TYPE_CHECKING guards. The
lookup half imports leaves only, so the cycle is gone rather than deferred.

Node kinds fall into three groups:
  - Genuinely file-based (PROGRAM, COPYBOOK, JOB, STEP, INSTREAM_DATA,
    BMS_MAP): resolved by matching against the corpus's own naming
    conventions (filename stem == program-id, JCL step ownership, proclib
    .prc files, ...). A miss is UNRESOLVED — worth logging, since the corpus
    should have the file.
  - CSD-defined (TRANSACTION, CICS_FILE): resolved against config.csd_files
    when present; NO_DEFINITION_SOURCE when there's no CSD entry (or no CSD
    configured at all) for this corpus.
  - Structurally not file-based (DATASET, COBOL_FILE): always
    NOT_FILE_BASED. A DATASET's physical name is referenced from many DDs
    across possibly many JCL files; a COBOL_FILE's DD name is, per the
    (kind, id) identity model, shared by whichever programs happen to use
    the same ASSIGN TO name in their FILE-CONTROL — neither has a single
    file it is "defined" in.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from cobble.file_location import FileLocation, FileLocationReason, NoFileLocation
from cobble.knowledge_graph.graph_types import NodeKind

logger = logging.getLogger(__name__)

_NOT_FILE_BASED = NoFileLocation(FileLocationReason.NOT_FILE_BASED)
_NO_DEFINITION_SOURCE = NoFileLocation(FileLocationReason.NO_DEFINITION_SOURCE)
_UNRESOLVED = NoFileLocation(FileLocationReason.UNRESOLVED)
_NOT_INDEXED = NoFileLocation(FileLocationReason.NOT_INDEXED)

# Read-only and shared: a default of {} would be a mutable default, and every
# index that leaves a group unpopulated wants the same empty lookup anyway.
EMPTY: Mapping[str, Path] = MappingProxyType({})


class FileLocationResolver(Protocol):
    """The one question an extractor asks of the corpus index.

    Extractors take this rather than :class:`CorpusIndex` itself: resolving a
    node's location is all of what they use, so a stub that answers only that
    is a legitimate argument instead of an object pretending to be a whole
    index. Declared here, next to the implementation, because the consumers
    already import this module (under TYPE_CHECKING) for the concrete class.
    """

    def resolve_file_path(self, kind: NodeKind, node_id: str) -> FileLocation: ...


def _get_or_warn(
    mapping: Mapping[str, Path], kind: NodeKind, node_id: str
) -> FileLocation:
    """Look up a kind that the corpus should have a file for, warning on a miss."""
    if node_id in mapping:
        return mapping[node_id]
    logger.warning(
        "CorpusIndex: %s %r not found in corpus — UNRESOLVED", kind.value, node_id
    )
    return _UNRESOLVED


@dataclass(frozen=True)
class CorpusIndex:
    """Finished lookups, one per node kind that has one, plus what was skipped.

    Frozen and built in one shot by :func:`corpus_index_builder.build_corpus_index`
    so a resolution cannot depend on how much of the corpus had been read when it
    was asked -- that determinism is the whole point of resolving up front.
    """

    programs: Mapping[str, Path] = EMPTY
    copybooks: Mapping[str, Path] = EMPTY
    jobs: Mapping[str, Path] = EMPTY
    steps: Mapping[str, Path] = EMPTY
    instream: Mapping[str, Path] = EMPTY
    transactions: Mapping[str, Path] = EMPTY
    cics_files: Mapping[str, Path] = EMPTY
    failures: tuple[str, ...] = ()
    """Members the index skipped, one string each.

    A skipped member has to reach the caller: everything in it — its jobs,
    steps, instream data, transactions — is missing from the index, and every
    later reference to those resolves UNRESOLVED. This used to be a
    ``logger.warning`` and nothing else, so the run's end-of-run failure
    report claimed nothing had gone wrong while 259 members were absent.
    ``build_graph.main`` folds these into the run's own failure list.
    """

    def resolve_file_path(self, kind: NodeKind, node_id: str) -> FileLocation:
        return _RESOLVERS[kind](self, kind, node_id.upper())


# One resolver per node kind, in the three groups the module docstring
# describes. A table rather than a match statement so that adding a kind is a
# row, and so a kind that is missing from it fails loudly on a KeyError instead
# of falling through a chain of branches to whatever the last one returns.
_RESOLVERS: Mapping[NodeKind, Callable[[CorpusIndex, NodeKind, str], FileLocation]] = (
    MappingProxyType(
        {
            # File-based: the corpus should have the file, so a miss is worth
            # logging.
            NodeKind.PROGRAM: lambda index, kind, key: _get_or_warn(
                index.programs, kind, key
            ),
            NodeKind.COPYBOOK: lambda index, kind, key: _get_or_warn(
                index.copybooks, kind, key
            ),
            NodeKind.JOB: lambda index, kind, key: _get_or_warn(index.jobs, kind, key),
            NodeKind.STEP: lambda index, kind, key: _get_or_warn(
                index.steps, kind, key
            ),
            NodeKind.INSTREAM_DATA: lambda index, kind, key: _get_or_warn(
                index.instream, kind, key
            ),
            # BMS_MAP is file-based in principle but cobble keeps no index for
            # it (bms_dir isn't part of CorpusConfig today -- see the builder),
            # so no lookup is even attempted. NOT_INDEXED rather than
            # UNRESOLVED: the latter asserts the corpus was missing a file it
            # should have had, which would accuse every corpus of thousands of
            # absences that are cobble's gap, not theirs.
            NodeKind.BMS_MAP: lambda index, kind, key: _NOT_INDEXED,
            # CSD-defined: no entry means this corpus configured no CSD, or the
            # CSD does not define it. Corpus shape, not a missing file.
            NodeKind.TRANSACTION: lambda index, kind, key: index.transactions.get(
                key, _NO_DEFINITION_SOURCE
            ),
            NodeKind.CICS_FILE: lambda index, kind, key: index.cics_files.get(
                key, _NO_DEFINITION_SOURCE
            ),
            # DATASET: a physical dataset name referenced from many DDs across
            # possibly many JCL files. COBOL_FILE: a DD name from a program's
            # FILE-CONTROL -- per the (kind, id) identity model, the same DD
            # name from two different programs merges into one node, so there is
            # no single owning program's file to attribute it to either.
            NodeKind.DATASET: lambda index, kind, key: _NOT_FILE_BASED,
            NodeKind.COBOL_FILE: lambda index, kind, key: _NOT_FILE_BASED,
        }
    )
)
