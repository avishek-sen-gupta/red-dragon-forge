"""One coprocessor a build may name: the compile spec it lowers with and the programs every image built with it must link."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from interpreter.project.coprocessor_compile import CoprocessorSpec

from red_dragon_forge.coprocessor_name import CoprocessorName


@dataclass(frozen=True)
class Coprocessor:
    name: CoprocessorName
    spec: Callable[[], CoprocessorSpec]
    required: tuple[str, ...]
