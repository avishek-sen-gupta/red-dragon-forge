"""One cluster, as one line of the clusters file."""

from __future__ import annotations

from cobble.experimental.partition.cluster import Cluster
from pydantic import BaseModel, ConfigDict


class ClusterLine(BaseModel):
    """A clusters file line holding a cluster."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cluster: Cluster
