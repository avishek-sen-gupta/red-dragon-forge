"""What the runner does with a DD the catalog cannot allocate: fail the step, or stand in an empty dataset."""

from __future__ import annotations

import logging
from typing import Protocol

from catnip.dataset import Dataset
from jackal.catalog import DatasetCatalog, Unallocated
from jackal.model import QualifiedStep
from jackal.results import AllocationFailed

logger = logging.getLogger(__name__)


class MissingDataStrategy(Protocol):
    def settle(
        self,
        qualified: QualifiedStep,
        unallocated: Unallocated,
        catalog: DatasetCatalog,
    ) -> Dataset | AllocationFailed: ...


class StrictAllocation(MissingDataStrategy):
    """Fails the step before its program runs, as z/OS does."""

    def settle(
        self,
        qualified: QualifiedStep,
        unallocated: Unallocated,
        catalog: DatasetCatalog,
    ) -> Dataset | AllocationFailed:
        return AllocationFailed(unallocated.dd.ddname, unallocated.error)


class LenientAllocation(MissingDataStrategy):
    """Allocates an empty dataset in place of the one that could not be, and warns."""

    def settle(
        self,
        qualified: QualifiedStep,
        unallocated: Unallocated,
        catalog: DatasetCatalog,
    ) -> Dataset | AllocationFailed:
        logger.warning(
            "%s DD %s: %s; allocated an empty dataset in its place",
            qualified.rendered(),
            unallocated.dd.ddname.text,
            unallocated.error.value,
        )
        return catalog.created_empty(unallocated.dd)
