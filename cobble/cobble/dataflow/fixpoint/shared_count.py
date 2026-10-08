"""A count every worker process advances, so a log numbers members in the order they finish."""

from __future__ import annotations

from multiprocessing.sharedctypes import Synchronized


class SharedCount:
    """Owned by the coordinator, handed to each worker; the next number goes to
    whichever process asks first."""

    def __init__(self, value: Synchronized[int]) -> None:
        self._value = value

    def next(self) -> int:
        with self._value.get_lock():
            self._value.value = self._value.value + 1
            return self._value.value
