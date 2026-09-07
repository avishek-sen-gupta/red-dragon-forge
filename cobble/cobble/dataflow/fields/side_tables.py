"""The tables beside the graph, and the one sink that streams any of them.

None of them is a graph fact, so none of them is in the graph.

``extents.jsonl`` says where every *declared* field is, whether a value ever
moved through it or not, plus the level and usage it was declared with. Level is
there because ranges alone cannot resolve containment: a group with a single
child owns exactly its child's bytes, and so does a record's REDEFINES view, and
only the declared level says which of the pair holds the other. Usage is there
because a partial overlap of a COMP or COMP-3 field is not a partial read of its
value -- a consumer that slices one is reading half a packed number. With both,
the whole record tree and the byte correspondence of a group move are derivable
from this table plus the two ranges an edge carries, which is why no edge
carries either.

``defs.jsonl`` says which statements could have last written one byte range by
the time one CFG node runs. Its own table because the relation is keyed by
(node, range) and not by the flow: one source range at one node had a hundred
reaching definers on the member measured, and 862 of its 5261 (node, source,
target) triples had more than one. Pinned onto the edge, each of those became one
edge per definer, all stating the same flow. Here it is one row, and an edge that
wants the definers joins on the pair it already names.

``aliases.jsonl`` says which bytes a call site shares between two programs. Its
own table because a row belongs to neither program's flow graph -- it is the
relation between them.

Same temp-and-rename discipline as GraphWriter, so a crashed run leaves no
truncated file, and the same keep-first dedupe: two members declaring one
program_id is normal on a real corpus, and the first one analysed is the one
whose layout the ids in the graph were named from.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from cobble.sink_state import FirstSighting


@dataclass(frozen=True)
class FieldExtents:
    """One declared name, how it was declared, and every byte range it owns.

    A list of ranges because a name owns more than one whenever OCCURS gives it
    an occurrence per subscript, or two records declare it independently. Not the
    span from the first range to the last: between two occurrences of an element
    lie its siblings' bytes, and a single spanning range would report this field
    as covered by a write that only ever touched them.
    """

    id: str
    level: int
    usage: str
    extents: tuple[str, ...]


@dataclass(frozen=True)
class ReachingDefs:
    """Which statements could have written ``extent`` by the time ``node`` runs.

    Plural, and irreducibly so: two arms of a branch both reach the node, and
    nothing short of a path-sensitive walk says which one ran.
    """

    node: str
    extent: str
    definers: tuple[str, ...]


@dataclass(frozen=True)
class CommareaAlias:
    """One call site's shared commarea window, or a named reason there is none.

    ``caller``/``node``/``transfer`` are always present, so a site that could not
    be aliased is a row a consumer can read rather than an absence it has to
    interpret. ``returns`` is false for XCTL, which never comes back.
    """

    caller: str
    node: str
    transfer: str
    callee: str = ""
    caller_extent: str = ""
    callee_extent: str = ""
    returns: bool = False
    reason: str = ""


_Row = tuple[str, str]


def extent_row(field: FieldExtents) -> _Row:
    """One declared field's row, keyed by its id."""
    return (
        field.id,
        json.dumps(
            {
                "id": field.id,
                "level": field.level,
                "usage": field.usage,
                "extents": list(field.extents),
            }
        ),
    )


def defs_row(defs: ReachingDefs) -> _Row:
    """One reaching-definition row, keyed by the pair a flow joins on."""
    return (
        f"{defs.node}\x00{defs.extent}",
        json.dumps(
            {
                "node": defs.node,
                "extent": defs.extent,
                "definers": list(defs.definers),
            }
        ),
    )


def alias_row(alias: CommareaAlias) -> _Row:
    """One alias, keyed by the site and the caller window it shares.

    One commarea name can resolve to more than one caller cell -- not because a
    group is several cells, it is one, but because the same name can be declared in
    more than one record. The window is in the key so those cells stay apart where
    they land on different bytes, and collapse where they do not. Two cells that
    report one window produce a byte-identical row, which the keep-first dedupe
    drops, rightly: there is one window there to report and not two.
    """
    return (
        f"{alias.caller}\x00{alias.node}\x00{alias.caller_extent}",
        json.dumps(
            {
                "caller": alias.caller,
                "node": alias.node,
                "transfer": alias.transfer,
                "callee": alias.callee,
                "caller_extent": alias.caller_extent,
                "callee_extent": alias.callee_extent,
                "returns": alias.returns,
                "reason": alias.reason,
            }
        ),
    )


class JsonlWriter:
    """One JSON object per line, deduped keep-first on a caller-chosen key.

    Rows arrive already serialised because the tables have unrelated shapes and a
    signature wide enough for all of them would be a blob with extra steps.

    Opened and closed through ``jsonl_writer`` rather than by implementing the
    context-manager protocol itself: ``__exit__`` takes an exception type, an
    exception and a traceback, each of which may be absent, and the repo's lint
    rules admit neither ``object`` nor a ``| None`` union to say so.
    """

    def __init__(self, path: Path) -> None:
        self._written = FirstSighting()
        self._tmp = path.with_suffix(path.suffix + ".tmp")
        self._path = path
        self._file = self._tmp.open("w")

    def add_row(self, key: str, row: str) -> None:
        if not self._written.first_time(key):
            return
        self._file.write(row + "\n")

    def add_rows(self, rows: Iterable[_Row]) -> None:
        for key, row in rows:
            self.add_row(key, row)

    def close(self) -> None:
        self._file.close()
        self._tmp.rename(self._path)


@contextmanager
def jsonl_writer(path: Path) -> Iterator[JsonlWriter]:
    """The ``with`` form of ``JsonlWriter``, closing it however the block ends.

    ``knowledge_graph/graph_writer.py``'s ``GraphWriter`` implements the protocol
    directly, with the ``*exc: object`` annotation the same lint rules reject; it
    passes only because the blocking hook lints staged files and nothing has staged
    it since. Whoever does needs this seam, and this is the precedent.
    """
    writer = JsonlWriter(path)
    try:
        yield writer
    finally:
        writer.close()
