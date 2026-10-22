"""Every cluster of a graph, as one value and as the file the clusters stage writes."""

from __future__ import annotations

from cobble.experimental.partition.cluster import Cluster
from pydantic import BaseModel, ConfigDict


class ClusterSet(BaseModel):
    """The clusters, the fields in none, and the barrier the graph was built with."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    barrier: str
    clusters: tuple[Cluster, ...]
    isolated: tuple[str, ...]
