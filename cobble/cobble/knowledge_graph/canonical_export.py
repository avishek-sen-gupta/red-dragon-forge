"""canonical_export — convert cobble's own nodes.jsonl/edges.jsonl into
CodeConcise's canonical ingestion manifest JSON, alongside cobble's existing
nodes.jsonl/edges.jsonl/graph.html outputs.

Streaming and thread-pool-parallel throughout, with bounded memory — see
docs/superpowers/specs/2026-07-11-canonical-export-design.md for the full
design rationale, including the deliberate lack of schema validation.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from itertools import accumulate, chain, islice, pairwise
from pathlib import Path
from typing import TypeVar

from cobble.file_location import from_json, to_json_path
from cobble.knowledge_graph.graph_types import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)
from cobble.sink_state import Buffer, FirstSighting

logger = logging.getLogger(__name__)

# What goes into a chunked pool.map and what comes out: a graph node in and a
# list of manifest rows out, or an edge in and one row out.
_In = TypeVar("_In")
_Out = TypeVar("_Out")

GENERATOR = "cobble"

_CODE_CHUNK_KINDS = frozenset(
    {
        NodeKind.PROGRAM,
        NodeKind.COBOL_FILE,
        NodeKind.COPYBOOK,
        NodeKind.BMS_MAP,
        NodeKind.JOB,
        NodeKind.STEP,
        NodeKind.TRANSACTION,
        NodeKind.INSTREAM_DATA,
    }
)
_DATABASE_KINDS = frozenset({NodeKind.DATASET, NodeKind.CICS_FILE})

_LANGUAGE_FOR_KIND: dict[NodeKind, str] = {
    NodeKind.PROGRAM: "COBOL",
    NodeKind.COBOL_FILE: "COBOL",
    NodeKind.COPYBOOK: "COBOL",
    NodeKind.BMS_MAP: "COBOL",
    NodeKind.JOB: "JCL",
    NodeKind.STEP: "JCL",
    NodeKind.INSTREAM_DATA: "JCL",
}


def _canonical_id(kind: NodeKind, raw_id: str) -> str:
    return f"{kind.value}::{raw_id}"


def _category_for(kind: NodeKind) -> list[str]:
    if kind in _CODE_CHUNK_KINDS:
        return ["CODE_CHUNK"]
    if kind in _DATABASE_KINDS:
        return ["DATABASE"]
    raise ValueError(f"no category mapping for {kind!r}")


def _language_for(kind: NodeKind) -> object:
    """The canonical schema's ``language`` for a kind: a name, or JSON null.

    Typed to ``object`` rather than ``str | None`` for the same reason
    file_location.to_json_fields is — this is a value on its way to json.dumps,
    where "this kind has no language" is a null in the manifest and not a
    Python-side optional for a caller to unwrap.
    """
    return _LANGUAGE_FOR_KIND.get(kind)


def _read_file_text(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError as exc:
        logger.warning("canonical_export: could not read %s: %s", path, exc)
        return ""


def _loc(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def _transform_node(node: GraphNode, project_name: str) -> dict:
    # The canonical schema has one string field for a path and nowhere to say
    # why a node has none, so the reason stops here rather than at the wire.
    path = to_json_path(node.location)
    code = _read_file_text(Path(path)) if path else ""
    return {
        "id": _canonical_id(node.kind, node.id),
        "display_name": node.id,
        "type": node.kind.value,
        "code": code,
        "path": path or "",
        "language": _language_for(node.kind),
        "generator": GENERATOR,
        "loc": _loc(code),
        "cyclomatic_complexity": 0,
        "category": _category_for(node.kind),
        "additional_properties": {
            **node.attrs,
            "kind": node.kind.value,
            "project_name": project_name,
        },
    }


def _transform_edge(edge: GraphEdge) -> dict:
    return {
        "from_id": _canonical_id(edge.source_kind, edge.source),
        "to_id": _canonical_id(edge.target_kind, edge.target),
        "type": edge.kind.value,
    }


def _process_node(
    node: GraphNode, project_name: str, fs: FileSystemSynthesizer
) -> list[dict]:
    canonical_node = _transform_node(node, project_name)
    path = to_json_path(node.location)
    return [
        canonical_node,
        # A node with no file has no FILE/DIRECTORY chain to hang off — see
        # to_json_path on why the reason cannot reach this schema.
        *(fs.synthesize_for_node(canonical_node["id"], path) if path else ()),
    ]


def _stream_nodes(path: Path) -> Iterator[GraphNode]:
    with path.open() as f:
        for line in f:
            row = json.loads(line)
            yield GraphNode(
                id=row["id"],
                kind=NodeKind(row["kind"]),
                location=from_json(row),
                attrs=row.get("attrs", {}),
            )


def _stream_edges(path: Path) -> Iterator[GraphEdge]:
    with path.open() as f:
        for line in f:
            row = json.loads(line)
            yield GraphEdge(
                source=row["source"],
                source_kind=NodeKind(row["source_kind"]),
                target=row["target"],
                target_kind=NodeKind(row["target_kind"]),
                kind=EdgeKind(row["kind"]),
                attrs=row.get("attrs", {}),
            )


def _chain_ids(file_path: str) -> Sequence[str]:
    """The canonical ids of the FILE and DIRECTORY nodes along a path.

    ``a/b/PROGONE.cbl`` becomes DIRECTORY::a, DIRECTORY::a/b,
    FILE::a/b/PROGONE.cbl — outermost first, the last part the file and every
    earlier one a directory. accumulate() is what turns the parts into the
    cumulative prefixes each id is named by.
    """
    parts = Path(file_path).parts
    prefixes = accumulate(parts, lambda prefix, part: f"{prefix}/{part}")
    return [
        f"{'FILE' if i == len(parts) - 1 else 'DIRECTORY'}::{prefix}"
        for i, prefix in enumerate(prefixes)
    ]


def _file_system_node(node_id: str) -> dict:
    """The manifest row for one FILE or DIRECTORY node, read off its id.

    The id already carries both facts the row needs — its type and its path —
    so it is the argument rather than the two of them separately.
    """
    node_type, _, path = node_id.partition("::")
    return {
        "id": node_id,
        "display_name": Path(path).name,
        "type": node_type,
        "code": "",
        "path": path,
        "language": None,
        "generator": GENERATOR,
        "loc": 0,
        "cyclomatic_complexity": 0,
        "category": ["FILE_SYSTEM"],
        "additional_properties": {},
    }


def _made_of(from_id: str, to_id: str) -> dict:
    return {"from_id": from_id, "to_id": to_id, "type": "MADE_OF"}


class FileSystemSynthesizer:
    """Thread-safe FILE/DIRECTORY node+edge synthesis, deduplicated across
    the whole export run. Bounded by unique file/directory count, not node
    count — see design spec's "Pipeline architecture" section."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sighted = FirstSighting()
        self._edges: Buffer[dict] = Buffer()

    def synthesize_for_node(self, canonical_node_id: str, file_path: str) -> list[dict]:
        """The FILE/DIRECTORY nodes this path needs that no earlier call made.

        One lock around both pieces of state: which ids are new and which edges
        follow from them is a single decision, and two threads resolving the
        same directory must not both claim to have created it.

        The chain edges are emitted only alongside a newly created child, so a
        second node in an already-seen directory adds no duplicate MADE_OF —
        but the FILE -> owning-node edge is always new, since canonical_node_id
        is unique per graph node.
        """
        chain_ids = _chain_ids(file_path)
        with self._lock:
            new_ids = frozenset(
                node_id for node_id in chain_ids if self._sighted.first_time(node_id)
            )
            self._edges.add_all(
                chain(
                    (
                        _made_of(parent, child)
                        for parent, child in pairwise(chain_ids)
                        if child in new_ids
                    ),
                    (_made_of(chain_ids[-1], canonical_node_id),),
                )
            )
        return [
            _file_system_node(node_id) for node_id in chain_ids if node_id in new_ids
        ]

    def drain_edges(self) -> list[dict]:
        with self._lock:
            return self._edges.drain()


def _chunked(items: Iterable[_In], size: int) -> Iterator[tuple[_In, ...]]:
    """`items` in tuples of at most `size`, lazily.

    itertools.batched is exactly this, but it landed in 3.12 and this package
    supports 3.11. iter(callable, sentinel) is the stdlib idiom: each call takes
    the next `size` items off the shared iterator, and the empty tuple ends it.
    """
    iterator = iter(items)
    return iter(lambda: tuple(islice(iterator, size)), ())


def _mapped_in_chunks(
    pool: ThreadPoolExecutor,
    transform: Callable[[_In], _Out],
    items: Iterable[_In],
    chunk_size: int,
) -> Iterator[_Out]:
    """`transform` over `items` on `pool`, in order, `chunk_size` at a time.

    Chunked rather than one pool.map over the whole stream because pool.map
    submits everything it is given at once: on a 37,000-node corpus that would
    pull every node into memory before the first result came back, which is the
    bounded memory the streaming design exists for.
    """
    return chain.from_iterable(
        pool.map(transform, chunk) for chunk in _chunked(items, chunk_size)
    )


def _json_array_items(items: Iterable[str]) -> Iterator[str]:
    """Already-serialised values with the commas of a JSON array between them.

    A generator over strings rather than ",".join of a list: the manifest is
    written a piece at a time precisely so a whole corpus need not be held in
    memory to serialise it.
    """
    return (item if i == 0 else f",{item}" for i, item in enumerate(items))


def _node_texts(
    nodes_path: Path,
    project_name: str,
    fs: FileSystemSynthesizer,
    chunk_size: int,
    max_workers: int,
) -> Iterator[str]:
    """Every manifest node row, serialised: one graph node may yield several,
    since a file-backed node also brings its FILE/DIRECTORY chain."""
    process = partial(_process_node, project_name=project_name, fs=fs)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        batches = _mapped_in_chunks(
            pool, process, _stream_nodes(nodes_path), chunk_size
        )
        yield from (json.dumps(row) for row in chain.from_iterable(batches))


def _synthesized_edge_texts(fs: FileSystemSynthesizer) -> Iterator[str]:
    """The synthesizer's buffered MADE_OF edges, serialised.

    A generator so the drain happens when this section of the manifest is
    reached — after every node has been processed and had its chain
    synthesised. Draining any earlier would lose the edges of later nodes.
    """
    yield from (json.dumps(row) for row in fs.drain_edges())


def _extractor_edge_texts(
    edges_path: Path, chunk_size: int, max_workers: int
) -> Iterator[str]:
    """Every edge cobble's own extractors found, serialised."""
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        rows = _mapped_in_chunks(
            pool, _transform_edge, _stream_edges(edges_path), chunk_size
        )
        yield from (json.dumps(row) for row in rows)


def write_manifest(
    nodes_path: Path,
    edges_path: Path,
    output_path: Path,
    project_name: str,
    *,
    chunk_size: int = 200,
    max_workers: int = 8,
) -> None:
    """Write the canonical manifest, streaming, via a temp path and a rename.

    One lazy chain of strings handed to writelines, in manifest order: the
    sections must be consumed in this order, since the synthesized edges are
    only complete once the last node has passed through _node_texts.
    """
    fs = FileSystemSynthesizer()
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    with tmp_path.open("w") as f:
        f.writelines(
            chain(
                (f'{{"version": "1.0", "generator": "{GENERATOR}", "nodes": [',),
                _json_array_items(
                    _node_texts(nodes_path, project_name, fs, chunk_size, max_workers)
                ),
                ('], "edges": [',),
                _json_array_items(
                    chain(
                        _synthesized_edge_texts(fs),
                        _extractor_edge_texts(edges_path, chunk_size, max_workers),
                    )
                ),
                ("]}",),
            )
        )
    tmp_path.rename(output_path)
