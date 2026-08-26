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
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Iterable, Iterator

from cobble.interpreter.project.graph_types import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)

logger = logging.getLogger(__name__)

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


def _language_for(kind: NodeKind) -> str | None:
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
    code = _read_file_text(Path(node.file_path)) if node.file_path else ""
    return {
        "id": _canonical_id(node.kind, node.id),
        "display_name": node.id,
        "type": node.kind.value,
        "code": code,
        "path": node.file_path or "",
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
    results = [canonical_node]
    if node.file_path:
        results.extend(fs.synthesize_for_node(canonical_node["id"], node.file_path))
    return results


def _stream_nodes(path: Path) -> Iterator[GraphNode]:
    with path.open() as f:
        for line in f:
            row = json.loads(line)
            yield GraphNode(
                id=row["id"],
                kind=NodeKind(row["kind"]),
                file_path=row.get("file_path"),
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


class FileSystemSynthesizer:
    """Thread-safe FILE/DIRECTORY node+edge synthesis, deduplicated across
    the whole export run. Bounded by unique file/directory count, not node
    count — see design spec's "Pipeline architecture" section."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen_node_ids: set[str] = set()
        self._edges: list[dict] = []

    def synthesize_for_node(self, canonical_node_id: str, file_path: str) -> list[dict]:
        parts = Path(file_path).parts
        new_nodes: list[dict] = []
        prefix = ""
        prev_id: str | None = None
        with self._lock:
            for i, part in enumerate(parts):
                prefix = f"{prefix}/{part}" if prefix else part
                is_file = i == len(parts) - 1
                node_type = "FILE" if is_file else "DIRECTORY"
                node_id = f"{node_type}::{prefix}"
                if node_id not in self._seen_node_ids:
                    self._seen_node_ids.add(node_id)
                    new_nodes.append(
                        {
                            "id": node_id,
                            "display_name": part,
                            "type": node_type,
                            "code": "",
                            "path": prefix,
                            "language": None,
                            "generator": GENERATOR,
                            "loc": 0,
                            "cyclomatic_complexity": 0,
                            "category": ["FILE_SYSTEM"],
                            "additional_properties": {},
                        }
                    )
                    if prev_id is not None:
                        self._edges.append(
                            {"from_id": prev_id, "to_id": node_id, "type": "MADE_OF"}
                        )
                prev_id = node_id
            # FILE -> owning node: always new (canonical_node_id is unique per node).
            self._edges.append(
                {"from_id": prev_id, "to_id": canonical_node_id, "type": "MADE_OF"}
            )
        return new_nodes

    def drain_edges(self) -> list[dict]:
        with self._lock:
            edges, self._edges = self._edges, []
        return edges


def _chunked(iterable: Iterable, size: int) -> Iterator[list]:
    chunk = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def write_manifest(
    nodes_path: Path,
    edges_path: Path,
    output_path: Path,
    project_name: str,
    *,
    chunk_size: int = 200,
    max_workers: int = 8,
) -> None:
    fs = FileSystemSynthesizer()
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")

    with tmp_path.open("w") as f:
        f.write(f'{{"version": "1.0", "generator": "{GENERATOR}", "nodes": [')
        first = True
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            process = partial(_process_node, project_name=project_name, fs=fs)
            for chunk in _chunked(_stream_nodes(nodes_path), chunk_size):
                for node_results in pool.map(process, chunk):
                    for node_dict in node_results:
                        if not first:
                            f.write(",")
                        f.write(json.dumps(node_dict))
                        first = False

        f.write('], "edges": [')
        first = True
        for edge_dict in fs.drain_edges():
            if not first:
                f.write(",")
            f.write(json.dumps(edge_dict))
            first = False
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            for chunk in _chunked(_stream_edges(edges_path), chunk_size):
                for edge_dict in pool.map(_transform_edge, chunk):
                    if not first:
                        f.write(",")
                    f.write(json.dumps(edge_dict))
                    first = False
        f.write("]}")

    tmp_path.rename(output_path)
