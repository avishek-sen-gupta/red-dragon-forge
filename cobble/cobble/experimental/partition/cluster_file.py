"""The clusters file: one cluster per line, then one line per isolated field."""

from __future__ import annotations

from pathlib import Path

from cobble.experimental.partition.cluster_line import ClusterLine
from cobble.experimental.partition.cluster_set import ClusterSet
from cobble.experimental.partition.isolated_line import IsolatedLine
from pydantic import TypeAdapter

_LINE: TypeAdapter[ClusterLine | IsolatedLine] = TypeAdapter(ClusterLine | IsolatedLine)


def write_clusters(path: Path, clusters: ClusterSet) -> None:
    with path.open("w", encoding="utf-8") as out:
        out.writelines(
            f"{ClusterLine(cluster=cluster).model_dump_json()}\n"
            for cluster in clusters.clusters
        )
        out.writelines(
            f"{IsolatedLine(isolated=field).model_dump_json()}\n"
            for field in clusters.isolated
        )


def read_clusters(path: Path) -> ClusterSet:
    with path.open(encoding="utf-8") as lines:
        parsed = tuple(_LINE.validate_json(line) for line in lines if line.strip())
    return ClusterSet(
        clusters=tuple(
            line.cluster for line in parsed if isinstance(line, ClusterLine)
        ),
        isolated=tuple(
            line.isolated for line in parsed if isinstance(line, IsolatedLine)
        ),
    )
