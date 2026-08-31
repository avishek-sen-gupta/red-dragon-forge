"""The mutable state the streaming graph sinks need, and nothing else.

This is the one file in cobble that mutates a collection, and fp.json excludes
it by name. That exclusion is the point of the file: the mutation is real and
unavoidable here, so it lives in two small tested classes with their reasons
written down, rather than being scattered through the sinks or excused by
excluding a whole extractor.

Why it is unavoidable. The sinks are push-based — extractors call
sink.add_node() / sink.add_edge() one occurrence at a time (cicada's GraphSink
protocol, see cics/graph_sink.py), and a node reached from three extractors
must reach nodes.jsonl once. There is no stream the sink owns to fold over, so
"what have I seen" and "what have I set aside" have to be state held between
calls.

Why the functional forms do not work here — at corpus scale, rather than in
principle. A recent run wrote 37,140 nodes and 112,629 edges:

  * ``seen = seen | {key}`` per item copies the whole set each time — O(n^2),
    so roughly 690M and 6.3B element copies for one build.
  * ``rows = [*rows, row]`` per item is the same shape of cost for Buffer.
  * Python's stdlib has no persistent (structure-sharing) set or list to
    insert into in O(log n); the HAMT behind contextvars is not exposed.
  * Sorting the stream to dedupe with groupby would need every node buffered,
    which is exactly the bounded memory the streaming design bought.

Neither class is thread-safe. FileSystemSynthesizer holds its own lock around
both of them together, because which nodes are new and which edges follow from
them is one decision.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from typing import Generic, TypeVar

T = TypeVar("T")


class FirstSighting:
    """A set of keys already seen, answering only whether a key is new.

    Deliberately narrower than a set: callers cannot read the memo, remove from
    it, or iterate it, so the state cannot grow a second purpose later.
    """

    def __init__(self) -> None:
        self._seen: set[Hashable] = set()

    def first_time(self, key: Hashable) -> bool:
        """True the first time this key is offered, False every time after."""
        seen = key in self._seen
        self._seen.add(key)
        return not seen


class Buffer(Generic[T]):
    """Items set aside now for someone to take all of, once, later.

    canonical_export synthesizes FILE/DIRECTORY edges while streaming nodes but
    cannot write them until the manifest's edges section, which is after the
    last node. drain() is that handover: it returns the items and forgets them,
    so the same edge cannot be written twice.
    """

    def __init__(self) -> None:
        self._items: list[T] = []

    def add_all(self, items: Iterable[T]) -> None:
        self._items.extend(items)

    def drain(self) -> list[T]:
        """Everything buffered, in the order it arrived, leaving the buffer empty.

        A copy, not the internal list: the caller is about to iterate it while
        the sink may still be filling the buffer for a later drain.
        """
        items = list(self._items)
        self._items.clear()
        return items
