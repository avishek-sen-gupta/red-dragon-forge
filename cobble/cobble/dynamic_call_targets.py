"""DynamicCallTargets -- the rows of the targets.jsonl cobble-dataflow-fixpoint wrote."""

from dataclasses import dataclass

from cobble.dataflow.fixpoint.rows import Row


@dataclass(frozen=True)
class DynamicCallTargets:
    rows: tuple[Row, ...]


NO_DYNAMIC_CALL_TARGETS = DynamicCallTargets(rows=())
