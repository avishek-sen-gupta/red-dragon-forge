"""Coverage, one pinned derivation, and a bound on the worst member.

A termination assertion is not an acceptance test: the 3ao post-mortem found a
suite passing while its walk reached 18% of nodes, because nothing measured
reach. Every assertion here is about how much of the program the analysis
actually explained.

Skips with no config, because the corpus is not in this repo and must not be.
Nothing here names a member, but a FAILURE message does -- a coverage shortfall
nobody can trace back to a statement class is not worth asserting. Run this
where the corpus already lives, nowhere its output is published.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from cobble.corpus_index import CorpusIndex
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.emit import ProgramRecords, graph_records
from cobble.dataflow.fields.side_tables import defs_row, extent_row
from cobble.dataflow.fixpoint.fixpoint import analysed
from cobble.dataflow.fixpoint.query import FieldStore, Side, store_of
from cobol_asg.asg_types import CobolASG

COVERAGE_FLOOR = 0.85


def _rows(pairs) -> tuple[dict, ...]:
    """The side tables as they reach disk: the writer's own row producers."""
    return tuple(json.loads(row) for _, row in pairs)


def _store(records: ProgramRecords) -> FieldStore:
    return store_of(
        _rows(map(extent_row, records.extents)),
        tuple(_edge_row(edge) for edge in records.edges),
        _rows(map(defs_row, records.defs)),
    )


def _edge_row(edge) -> dict:
    return {
        "source": edge.source,
        "target": edge.target,
        "kind": edge.kind.value,
        "attrs": dict(edge.attrs),
    }


def _asg(cache: Path, member: str) -> CobolASG:
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict(
            json.loads((cache / f"{member}.json").read_text(encoding="utf-8"))
        )


def _analysed(cache: Path, member: str):
    return analysed(_asg(cache, member))


def test_most_resolvable_writes_produce_at_least_one_edge(corpus_config):
    """The measurement 3ao's post-mortem demands: reach, not termination."""
    cache = Path(corpus_config["cache_dir"])
    flows = [_analysed(cache, member)[0] for member in corpus_config["members"]]
    writes = sum(flow.writes for flow in flows)
    covered = sum(flow.covered for flow in flows)
    unhandled = sum(flow.unhandled for flow in flows)

    assert writes > 0
    assert covered / writes >= COVERAGE_FLOOR, (
        f"{covered}/{writes} writes covered, floor {COVERAGE_FLOOR}; "
        f"{unhandled} statements unhandled. Read the unhandled reasons and name "
        f"the missing statement class -- do not lower the floor."
    )


def test_no_analysed_member_is_silently_skipped(corpus_config):
    cache = Path(corpus_config["cache_dir"])
    skipped = {
        member: _analysed(cache, member)[0].skipped
        for member in corpus_config["members"]
    }
    assert not [member for member, reason in skipped.items() if reason], skipped


def test_the_pinned_derivation_holds_end_to_end(corpus_config):
    """A ratio says how much was explained; this says the explanation is right.

    Resolved by byte overlap, not by endpoint name. The pinned flow writes a
    group and the field it is pinned on is one of that group's children, so the
    edge names the group -- matching on ids finds nothing, which is the whole
    reason the queries intersect ranges instead.
    """
    oracle = corpus_config["oracle"]
    flow, index = _analysed(Path(corpus_config["cache_dir"]), oracle["member"])
    store = _store(graph_records(flow, index, CorpusIndex()))
    (source,) = store.field(oracle["source_field"])
    (target,) = store.field(oracle["target_field"])

    carried = [
        one
        for one in store.touching(target.ranges, Side.TARGET)
        if any(one.source_range.overlaps(part) for part in source.ranges)
    ]

    assert {one.node for one in carried} == set(oracle["cfg_nodes"]), sorted(
        one.node for one in carried
    )


def test_the_worst_member_completes_within_its_bound(corpus_config):
    """710.58s under recursive PERFORM inlining; the node-keyed worklist is what
    this asserts away."""
    performance = corpus_config.get("performance")
    if not performance:
        pytest.skip("no [performance] in fields-tests.toml")
    cache = Path(corpus_config["cache_dir"])

    started = time.monotonic()
    flow, _ = _analysed(cache, performance["member"])
    elapsed = time.monotonic() - started

    assert not flow.skipped
    assert elapsed < performance["seconds"], f"{elapsed:.1f}s"
