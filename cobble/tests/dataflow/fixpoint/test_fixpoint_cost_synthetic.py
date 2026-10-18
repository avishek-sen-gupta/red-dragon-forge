"""The fixpoint's cost on three invented programs, against the costs recorded around the partial-overwrite split."""

from __future__ import annotations

from pathlib import Path

import pytest
from cobble.dataflow.fixpoint.fixpoint import analysed
from cobble.dataflow.fixpoint.options import AnalysisOptions
from cobble.dataflow.fixpoint.scope import Scope
from cobble.parsing.asg_cache import cached_first_program
from tests.dataflow.fixpoint.fixpoint_baseline import FixpointBaseline
from tests.dataflow.fixpoint.fixpoint_cost import FixpointCost
from tests.dataflow.fixpoint.fixpoint_scope_baseline import FixpointScopeBaseline

FORGE = Path(__file__).resolve().parents[4]
BRIDGE_GLOB = "vendor/red-dragon/proleap-bridge/target/proleap-bridge-*-shaded.jar"
PROGRAMS = Path(__file__).parent / "data" / "perf"

BASELINES = (
    FixpointBaseline(
        program="SYNPERFA",
        pre_split=FixpointCost(
            commit="c413b60",
            nodes=1016,
            dequeues=25_810,
            settled=True,
            source_extents=156_658,
            largest_state=207,
            value_extents=97_188,
            peak_rss_mb=257,
            seconds=3.6,
        ),
        split=FixpointCost(
            commit="df6d6a6",
            nodes=1016,
            dequeues=104_078,
            settled=True,
            source_extents=310_875,
            largest_state=506,
            value_extents=137_583,
            peak_rss_mb=434,
            seconds=42.8,
        ),
        atoms=FixpointCost(
            commit="df6d6a6 with atom cuts",
            nodes=1016,
            dequeues=36_146,
            settled=True,
            source_extents=467_182,
            largest_state=604,
            value_extents=137_583,
            peak_rss_mb=602,
            seconds=29.0,
        ),
        reverted=FixpointCost(
            commit="df6d6a6 with the split reverted",
            nodes=1016,
            dequeues=25_810,
            settled=True,
            source_extents=156_658,
            largest_state=207,
            value_extents=97_188,
            peak_rss_mb=257,
            seconds=3.6,
        ),
        coalesced=FixpointCost(
            commit="249193b with coalesced pieces",
            nodes=1016,
            dequeues=34_323,
            settled=True,
            source_extents=250_043,
            largest_state=348,
            value_extents=137_583,
            peak_rss_mb=408,
            seconds=13.7,
        ),
        round_robin=FixpointCost(
            commit="97fd4b6 with round-robin and additive reasons",
            nodes=1016,
            dequeues=8_221,
            settled=True,
            source_extents=250_043,
            largest_state=348,
            value_extents=137_583,
            peak_rss_mb=153,
            seconds=4.0,
        ),
    ),
    FixpointBaseline(
        program="SYNPERFB",
        pre_split=FixpointCost(
            commit="c413b60",
            nodes=1014,
            dequeues=49_670,
            settled=True,
            source_extents=176_327,
            largest_state=220,
            value_extents=122_415,
            peak_rss_mb=282,
            seconds=8.3,
        ),
        split=FixpointCost(
            commit="df6d6a6",
            nodes=1014,
            dequeues=152_100,
            settled=False,
            source_extents=349_410,
            largest_state=533,
            value_extents=186_722,
            peak_rss_mb=484,
            seconds=74.4,
        ),
        atoms=FixpointCost(
            commit="df6d6a6 with atom cuts",
            nodes=1014,
            dequeues=63_725,
            settled=True,
            source_extents=467_689,
            largest_state=608,
            value_extents=197_001,
            peak_rss_mb=674,
            seconds=52.4,
        ),
        reverted=FixpointCost(
            commit="df6d6a6 with the split reverted",
            nodes=1014,
            dequeues=49_670,
            settled=True,
            source_extents=176_327,
            largest_state=220,
            value_extents=122_415,
            peak_rss_mb=281,
            seconds=7.9,
        ),
        coalesced=FixpointCost(
            commit="249193b with coalesced pieces",
            nodes=1014,
            dequeues=61_234,
            settled=True,
            source_extents=280_037,
            largest_state=358,
            value_extents=197_001,
            peak_rss_mb=485,
            seconds=27.9,
        ),
        round_robin=FixpointCost(
            commit="97fd4b6 with round-robin and additive reasons",
            nodes=1014,
            dequeues=8_329,
            settled=True,
            source_extents=280_037,
            largest_state=358,
            value_extents=197_001,
            peak_rss_mb=160,
            seconds=5.4,
        ),
    ),
    FixpointBaseline(
        program="SYNPERFC",
        pre_split=FixpointCost(
            commit="c413b60",
            nodes=4778,
            dequeues=52_209,
            settled=True,
            source_extents=3_703_073,
            largest_state=942,
            value_extents=2_354_085,
            peak_rss_mb=1573,
            seconds=164.8,
        ),
        split=FixpointCost(
            commit="00e8aa7",
            nodes=4778,
            dequeues=60_949,
            settled=True,
            source_extents=6_643_830,
            largest_state=1779,
            value_extents=2_661_089,
            peak_rss_mb=2622,
            seconds=285.3,
        ),
        atoms=FixpointCost(
            commit="df6d6a6 with atom cuts",
            nodes=4778,
            dequeues=57_849,
            settled=True,
            source_extents=13_100_687,
            largest_state=3033,
            value_extents=2_661_089,
            peak_rss_mb=4412,
            seconds=342.6,
        ),
        reverted=FixpointCost(
            commit="df6d6a6 with the split reverted",
            nodes=4778,
            dequeues=49_026,
            settled=True,
            source_extents=3_703_073,
            largest_state=942,
            value_extents=2_354_085,
            peak_rss_mb=2086,
            seconds=72.8,
        ),
        coalesced=FixpointCost(
            commit="249193b with coalesced pieces",
            nodes=4778,
            dequeues=55_089,
            settled=True,
            source_extents=6_073_018,
            largest_state=1608,
            value_extents=2_661_089,
            peak_rss_mb=2633,
            seconds=125.2,
        ),
        round_robin=FixpointCost(
            commit="97fd4b6 with round-robin and additive reasons",
            nodes=4778,
            dequeues=30_712,
            settled=True,
            source_extents=6_073_018,
            largest_state=1608,
            value_extents=2_661_089,
            peak_rss_mb=544,
            seconds=94.5,
        ),
    ),
)


SCOPE_BASELINES = (
    FixpointScopeBaseline(
        program="SYNPERFD",
        whole=FixpointCost(
            commit="97fd4b6 with round-robin and additive reasons",
            nodes=1056,
            dequeues=8_551,
            settled=True,
            source_extents=261_726,
            largest_state=349,
            value_extents=143_397,
            peak_rss_mb=154,
            seconds=4.1,
        ),
        call_targets=FixpointCost(
            commit="97fd4b6 with round-robin and additive reasons",
            nodes=1056,
            dequeues=8_144,
            settled=True,
            source_extents=214_621,
            largest_state=321,
            value_extents=121_208,
            peak_rss_mb=154,
            seconds=4.3,
        ),
    ),
)


def _bridge_jar() -> Path:
    found = sorted(FORGE.glob(BRIDGE_GLOB))
    if not found:
        pytest.skip(f"no bridge JAR at {BRIDGE_GLOB}; run `make jar`")
    return found[-1]


@pytest.fixture(scope="module")
def parsed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from cobble.parsing.parse_corpus import Job, parse_one

    cache = tmp_path_factory.mktemp("perf")
    jar = str(_bridge_jar())
    results = tuple(
        parse_one(
            Job(PROGRAMS / f"{one.program}.cbl", cache / f"{one.program}.json"),
            jar,
            (),
            ("cpy",),
        )
        for one in (*BASELINES, *SCOPE_BASELINES)
    )
    assert [result.error for result in results] == [
        "" for _ in (*BASELINES, *SCOPE_BASELINES)
    ]
    return cache


@pytest.mark.parametrize("baseline", BASELINES, ids=lambda one: one.program)
def test_the_fixpoint_settles_at_the_recorded_round_robin_cost(
    parsed: Path, baseline: FixpointBaseline
) -> None:
    flow, _ = analysed(
        cached_first_program(parsed, PROGRAMS / f"{baseline.program}.cbl")
    )

    assert (flow.nodes, flow.dequeues, flow.settled) == (
        baseline.round_robin.nodes,
        baseline.round_robin.dequeues,
        baseline.round_robin.settled,
    )


@pytest.mark.parametrize("baseline", SCOPE_BASELINES, ids=lambda one: one.program)
def test_each_scope_settles_at_its_recorded_cost(
    parsed: Path, baseline: FixpointScopeBaseline
) -> None:
    asg = cached_first_program(parsed, PROGRAMS / f"{baseline.program}.cbl")
    whole, _ = analysed(asg, AnalysisOptions(scope=Scope.WHOLE))
    restricted, _ = analysed(asg, AnalysisOptions(scope=Scope.CALL_TARGETS))

    assert (whole.nodes, whole.dequeues, whole.settled) == (
        baseline.whole.nodes,
        baseline.whole.dequeues,
        baseline.whole.settled,
    )
    assert (restricted.nodes, restricted.dequeues, restricted.settled) == (
        baseline.call_targets.nodes,
        baseline.call_targets.dequeues,
        baseline.call_targets.settled,
    )
    assert restricted.targets == whole.targets
