"""@covers decorator for annotating test methods with the feature they verify.

This is a minimal stub used by the covers-guard pre-tool hook.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import TypeVar

_F = TypeVar("_F", bound=Callable[..., object])


class FeatureStatus(Enum):
    IMPLEMENTED = "implemented"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"


class NotLanguageFeature(Enum):
    INFRASTRUCTURE = (
        "tests infrastructure or cross-cutting concerns, not a language feature"
    )


def covers(
    *features: Enum, status: FeatureStatus = FeatureStatus.IMPLEMENTED
) -> Callable[[_F], _F]:
    def _decorator(func: _F) -> _F:
        func._covers = frozenset(features)  # type: ignore[attr-defined]
        func._covers_status = status  # type: ignore[attr-defined]
        return func

    return _decorator
