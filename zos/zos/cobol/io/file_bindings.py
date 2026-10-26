"""What each ASSIGN name is bound to: its file's path, whether it opens for append, and its catalogued dataset."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from catnip.dataset import Dataset


@dataclass(frozen=True)
class FileBindings:
    paths: Mapping[str, Path]
    appended: frozenset[str]
    datasets: Mapping[str, Dataset]
