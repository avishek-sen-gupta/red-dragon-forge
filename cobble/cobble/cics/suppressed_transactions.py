"""SuppressedTransactions — the one counter the placeholder-transaction filter
keeps, because there is no stream for it to fold over.

`knowledge_graph/graph_writer.py`'s ``GraphWriter`` is push-based -- an
extractor calls ``add_node``/``add_edge`` once per occurrence, so "how many
placeholders did the filter remove" has to be state held between calls and
read back by the same object later, the same shape ``cics/cell.py`` and
``cics/strategy_stores.py`` are gated for elsewhere in this workspace. A
rebuilt copy on every call would go unseen by the caller holding the original
reference.
"""

from __future__ import annotations


class SuppressedTransactions:
    """What a placeholder-transaction filter removed, so the stage can say so.

    A filter that drops a thousand transactions in silence reads, in the log,
    exactly like one that found none: every other count a stage prints
    describes its inputs. Transactions are counted by id because the sink
    sees each placeholder more than once -- as a node, and again as an edge
    endpoint; edges are counted as seen, since each is emitted once.
    """

    def __init__(self) -> None:
        self._transactions: frozenset[str] = frozenset()
        self._edges = 0

    def transaction(self, node_id: str) -> None:
        self._transactions = self._transactions | {node_id}

    def edge(self) -> None:
        self._edges = self._edges + 1

    @property
    def transactions(self) -> frozenset[str]:
        return self._transactions

    @property
    def edges(self) -> int:
        return self._edges
