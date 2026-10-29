"""Every relation a run gives, read whole before anything is written."""

from collections.abc import Callable
from pathlib import Path

from cobble.experimental.datalog.access_facts import access_facts
from cobble.experimental.datalog.cfg_facts import cfg_facts
from cobble.experimental.datalog.cluster_facts import cluster_facts
from cobble.experimental.datalog.counts_facts import counts_facts
from cobble.experimental.datalog.defs_facts import defs_facts
from cobble.experimental.datalog.dep_facts import dep_facts
from cobble.experimental.datalog.extent_facts import extent_facts
from cobble.experimental.datalog.facts import Facts
from cobble.experimental.datalog.flow_facts import flow_facts
from cobble.experimental.datalog.jump_facts import jump_facts
from cobble.experimental.datalog.knowledge_facts import knowledge_facts
from cobble.experimental.datalog.link_facts import link_facts
from cobble.experimental.datalog.sink_facts import sink_facts
from cobble.experimental.datalog.slot_facts import slot_facts
from cobble.experimental.datalog.target_facts import target_facts

FAMILIES: tuple[Callable[[Path], tuple[Facts, ...]], ...] = (
    knowledge_facts,
    extent_facts,
    cfg_facts,
    access_facts,
    counts_facts,
    defs_facts,
    sink_facts,
    flow_facts,
    link_facts,
    target_facts,
    jump_facts,
    slot_facts,
    dep_facts,
    cluster_facts,
)


def run_facts(run: Path) -> tuple[Facts, ...]:
    return tuple(facts for family in FAMILIES for facts in family(run))
