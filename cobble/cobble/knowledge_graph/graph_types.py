"""Shared node/edge schema for the COBOL/CICS/JCL knowledge graph.

Every source in the codebase (a COBOL program, a copybook, a CICS
transaction, a JCL job/step, a dataset, a BMS map) is a GraphNode; every
relationship between them (CALL, COPY, XCTL, JCL step sequencing, dataset
access, ...) is a GraphEdge. Node identity is (kind, id) — id is a logical
name (program-id, transaction-id, "JOBNAME.STEPNAME", ...), never a file
path, and is uppercased by every extractor at extraction time.

Consumers: interpreter.project.cobol_connections (this repo), cics.flow_map
(cicada), a new jackal JCL extractor, and red-dragon-forge's knowledge_graph
package, which merges all three into one graph. This module has no
knowledge of any of them — it is pure vocabulary, the same role
interpreter.project.coprocessor_compile plays for CoprocessorSpec.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import TypeAlias

from cobble.file_location import NOT_ATTEMPTED, FileLocation

# What an attribute may hold: whatever the nodes/edges JSONL can carry, spelled
# out rather than Any so a value that could never serialise is a type error here
# instead of a json.dumps failure at the end of a corpus run. Written as a quoted
# TypeAlias rather than a 3.12 `type` statement because the lint config still
# parses this package as 3.11.
AttrValue: TypeAlias = (
    "str | int | float | bool | Sequence[AttrValue] | Mapping[str, AttrValue]"
)


class NodeKind(Enum):
    PROGRAM = "PROGRAM"
    COPYBOOK = "COPYBOOK"
    TRANSACTION = "TRANSACTION"
    JOB = "JOB"
    STEP = "STEP"
    DATASET = "DATASET"
    BMS_MAP = "BMS_MAP"
    # The logical name a program's EXEC CICS ... FILE(...) references (a CSD
    # DEFINE FILE entry) — distinct from DATASET, its physical DSNAME, which
    # a CICS_FILE resolves to via a DEFINES_DATASET edge. Two nodes because a
    # program only ever knows the logical name; the physical dataset is a
    # separate identity JCL jobs can also independently reference.
    CICS_FILE = "CICS_FILE"
    # A JCL DD's literal inline content (DD *) — id is scoped by
    # JOB.STEP.DDNAME (never a bare dataset name, since instream data has
    # none). See EdgeKind.READS, source STEP -> target INSTREAM_DATA.
    INSTREAM_DATA = "INSTREAM_DATA"
    # A batch COBOL program's FILE-CONTROL SELECT ... ASSIGN TO ddname entry
    # — id is the ASSIGN TO name (the DD name its OPEN/READ/WRITE statements
    # reference), not the physical dataset. Mirrors CICS_FILE's split from
    # DATASET: a program only ever knows its DD name; the physical dataset
    # is a JCL-level identity a job's DD statement assigns independently.
    COBOL_FILE = "COBOL_FILE"
    # A COBOL data field, or a synthetic origin a field's bytes came from
    # (LITERAL, FILE:<name>, %CICS-STATE, %CALL:<target>). id is
    # "<program>.<field>" because a field name is only unique within a program
    # — two copybooks routinely give one piece of storage two names.
    FIELD = "FIELD"


class EdgeKind(Enum):
    CALL = "CALL"
    COPY = "COPY"
    XCTL = "XCTL"
    LINK = "LINK"
    RETURN_TRANSID = "RETURN_TRANSID"
    STARTS = "STARTS"
    # PROGRAM -> TRANSACTION, from EXEC CICS START TRANSID(...): asynchronous
    # dispatch, so it is neither STARTS (TRANSACTION -> PROGRAM, which says who
    # serves a transaction) nor RETURN_TRANSID (the current task ending).
    START_TRANSID = "START_TRANSID"
    SENDS_MAP = "SENDS_MAP"
    RECEIVES_MAP = "RECEIVES_MAP"
    JCL_STEP_RUNS = "JCL_STEP_RUNS"
    # STEP -> PROGRAM, from a RUN PROGRAM(...) subcommand in the SYSTSIN of a
    # step whose EXEC PGM= is the TSO terminal monitor. Distinct from
    # JCL_STEP_RUNS because both facts are true and neither substitutes for the
    # other: the step really does run IKJEFT01, and IKJEFT01 really does run
    # this program under DB2. Collapsing them into one kind would claim the JCL
    # names a program it never names. See jackal.tso.
    TSO_RUNS_PROGRAM = "TSO_RUNS_PROGRAM"
    READS = "READS"
    WRITES = "WRITES"
    UPDATES = "UPDATES"
    DELETES = "DELETES"
    ENDS_BROWSE = "ENDS_BROWSE"
    # CICS_FILE -> DATASET, from a CSD's DEFINE FILE(name) ... DSNAME(...).
    DEFINES_DATASET = "DEFINES_DATASET"
    # FIELD -> FIELD, from field-level byte dataflow: the source's bytes reach
    # the target's. attrs carry both extents and the CFG node id that wrote
    # them, but deliberately NOT the guard condition — a reader asks srccfg
    # for that node's guards on demand, which keeps conditions out of the
    # lattice they would otherwise multiply.
    FLOWS_TO = "FLOWS_TO"


ATTRS_ARE_IDENTITY: frozenset[EdgeKind] = frozenset({EdgeKind.FLOWS_TO})
"""The kinds whose attrs are part of the fact, not provenance about it.

For most kinds the endpoints are the whole claim: "this program COPYs that
copybook" is one fact however many lines assert it, and attrs record which one
was seen first. FLOWS_TO is not that shape -- "these bytes reach those bytes,
written here" names a different flow for every extent pair and defining
statement, so a sink deduping it on endpoints alone keeps one of N facts and
silently discards the rest.

A kind belongs here when two of its edges can share endpoints and still say
different things. Adding one grows the artefact by exactly the facts it was
losing.
"""


@dataclass(frozen=True)
class GraphNode:
    id: str
    kind: NodeKind
    location: FileLocation = NOT_ATTEMPTED
    """Where this node is defined, or an explicit statement of why it has no file.

    A ``str | None`` here for as long as there was one, which meant every
    producer called CorpusIndex, got back a reason, and threw it away at
    construction — the node could then only say "no file", not which of the
    several unrelated reasons applied. Keeping the FileLocation whole is what
    lets the reason reach nodes.jsonl; see cobble.file_location.

    Defaults to NOT_ATTEMPTED rather than "unresolved": a node built with no
    CorpusIndex in reach has not failed to resolve, it was never looked up.
    """
    attrs: dict[str, AttrValue] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphEdge:
    source: str
    source_kind: NodeKind
    target: str
    target_kind: NodeKind
    kind: EdgeKind
    attrs: dict[str, AttrValue] = field(default_factory=dict)
