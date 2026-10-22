"""Every cluster of a graph, as one value."""

from __future__ import annotations

from cobble.experimental.partition.cluster import Cluster
from pydantic import BaseModel, ConfigDict


class ClusterSet(BaseModel):
    """The clusters, and the fields in none."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    clusters: tuple[Cluster, ...]
    isolated: tuple[str, ...]
