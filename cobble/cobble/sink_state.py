"""The mutable state the streaming graph sinks need, and nothing else.

This is the one file in cobble that mutates a collection, and fp.json excludes
it by name. That exclusion is the point of the file: the mutation is real and
unavoidable here, so it lives in one small tested class with its reasons
written down, rather than being scattered through the sinks or excused by
excluding a whole extractor.

Why it is unavoidable. The sinks are push-based — extractors call
sink.add_node() / sink.add_edge() one occurrence at a time (cicada's GraphSink
protocol, see cics/graph_sink.py), and a node reached from three extractors
must reach nodes.jsonl once. There is no stream the sink owns to fold over, so
"what have I seen" has to be state held between calls.

Why the functional form does not work here — at corpus scale, rather than in
principle. A recent run wrote 37,140 nodes and 112,629 edges, and
``seen = seen | {key}`` per item copies the whole set each time — O(n^2), so
roughly 690M and 6.3B element copies for one build. Python's stdlib has no
persistent (structure-sharing) set to insert into in O(log n); the HAMT behind
contextvars is not exposed. Sorting the stream to dedupe with groupby would
need every node buffered, which is exactly the bounded memory the streaming
design bought.

Not thread-safe. A caller sharing one across threads owns the lock.
"""

from __future__ import annotations

from collections.abc import Hashable


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
