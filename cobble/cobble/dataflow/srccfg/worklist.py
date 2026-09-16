"""The forward gen/kill worklist over bitmask definition sets.

Kept apart from dataflow.py because the loop mutates in place by design: the out
mask of one node and the pending set are updated as the fixpoint converges. A
rebuild per step, or full sweeps, is the path this replaced -- 837s on the largest
member measured, against under a second here (9f3aad14).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from functools import reduce
from operator import or_

from cobble.dataflow.srccfg.cfg import Cfg

_log = logging.getLogger(__name__)


def out_masks(
    cfg: Cfg, gen_masks: Mapping[str, int], kill_masks: Mapping[str, int]
) -> Mapping[str, int]:
    """Each node's OUT set at the fixpoint: (IN & ~kill) | gen, IN the union of
    its predecessors' OUT."""
    masks = {node.id: gen_masks.get(node.id, 0) for node in cfg.nodes}
    worklist = set(cfg.node_ids)
    processed = 0
    while worklist:
        node_id = worklist.pop()
        processed += 1
        new_in = reduce(or_, (masks[e.source] for e in cfg.predecessors(node_id)), 0)
        new_out = (new_in & ~kill_masks.get(node_id, 0)) | gen_masks.get(node_id, 0)
        if new_out != masks[node_id]:
            masks[node_id] = new_out
            worklist.update(edge.target for edge in cfg.successors(node_id))
    _log.info("reaching_defs: %s  done  processed=%d", cfg.program, processed)
    return masks
