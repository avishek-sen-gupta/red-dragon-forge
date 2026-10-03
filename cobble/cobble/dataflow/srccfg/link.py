"""Calls out of a member, and the storage a commarea shares.

Whole-record aliasing only: a commarea maps the caller's field onto the callee's
DFHCOMMAREA, and matching individual fields inside it needs byte-offset-accurate
layouts, which are out of scope here. Saying record-to-record is the honest answer;
a field-level claim from a name match would be wrong wherever the two sides declare
the area differently, which on a real corpus is most places.

XCTL does not return, so control does not flow back to the caller. Only a failed
XCTL continues: to the armed handler, or, under RESP or NOHANDLE, to the next
statement. ``desugar.py`` gives the node that shape, and the link adds no flow.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import chain

from cobble.dataflow.srccfg.cfg import Cfg, Node
from cobble.dataflow.srccfg.desugar import CALL_TRANSFER, CALL_TRANSFERS, commarea_field
from cobble.dataflow.srccfg.dynamic_targets import NO_DYNAMIC_TARGETS, DynamicTargets
from cobble.dataflow.srccfg.synthetic import using_field

COMMAREA_RECORD = "DFHCOMMAREA"


@dataclass(frozen=True)
class CallSite:
    caller: str
    node: str
    transfer: str
    program: str
    resolved: bool = True
    commarea: str = ""


@dataclass(frozen=True)
class Alias:
    caller: str
    caller_field: str
    callee: str
    callee_field: str


@dataclass(frozen=True)
class CallGraph:
    sites: tuple[CallSite, ...] = ()
    aliases: tuple[Alias, ...] = ()


def call_sites(cfg: Cfg) -> tuple[CallSite, ...]:
    return tuple(
        CallSite(
            caller=cfg.program,
            node=node.id,
            transfer=CALL_TRANSFERS[node.transfer],
            program=node.target,
            resolved=node.target_resolved,
            commarea=commarea_field(node),
        )
        for node in cfg.nodes
        if node.transfer in CALL_TRANSFERS and node.target
    )


def aliases(cfg: Cfg) -> tuple[Alias, ...]:
    return tuple(
        chain.from_iterable(
            _aliases_of(cfg, site, node) for site, node in _resolved(cfg)
        )
    )


def _sites(cfg: Cfg) -> tuple[tuple[CallSite, Node], ...]:
    return tuple((site, cfg.node(site.node)) for site in call_sites(cfg))


def _resolved(cfg: Cfg) -> tuple[tuple[CallSite, Node], ...]:
    return tuple((site, node) for site, node in _sites(cfg) if site.resolved)


def _aliases_of(cfg: Cfg, site: CallSite, node: Node) -> tuple[Alias, ...]:
    if site.transfer == CALL_TRANSFER:
        return tuple(
            Alias(
                caller=cfg.program,
                caller_field=argument.name,
                callee=site.program,
                callee_field=using_field(position),
            )
            for position, argument in enumerate(node.using)
            if argument.name
        )
    if not site.commarea:
        return ()
    return (
        Alias(
            caller=cfg.program,
            caller_field=site.commarea,
            callee=site.program,
            callee_field=COMMAREA_RECORD,
        ),
    )


def call_graph(cfgs: Iterable[Cfg]) -> CallGraph:
    built = tuple(cfgs)
    return CallGraph(
        sites=tuple(chain.from_iterable(call_sites(cfg) for cfg in built)),
        aliases=tuple(chain.from_iterable(aliases(cfg) for cfg in built)),
    )


@dataclass(frozen=True)
class BundleCall:
    """A call site and the node in the callee it lands on: the one edge no CFG holds.

    ``entry`` is empty when the callee is not in the bundle -- its ASG was never in
    the cache -- and that is the whole difference between this and a ``CallSite``: a
    reader with the entry can cross to the callee without re-deriving the join.

    ``transfer`` is the node's own spelling, CICS_LINK and not CallSite's normalised
    LINK, because the entry is a fact about two nodes and a reader joining this back
    to the node it names finds the same word on it.
    """

    caller: str
    node: str
    transfer: str
    program: str
    entry: str = ""
    resolved: bool = True
    commarea: str = ""
    expression: str = ""
    reasons: tuple[str, ...] = ()
    certain: bool = True


def entry_nodes(cfgs: Sequence[Cfg]) -> Mapping[str, str]:
    """Each program's first node, which is the paragraph label the build starts at.

    A program with no nodes is absent rather than mapped to nothing: there is no
    entry to point an edge at.
    """
    return {cfg.program: cfg.nodes[0].id for cfg in cfgs if cfg.nodes}


def bundle_calls(
    cfgs: Sequence[Cfg], targets: DynamicTargets = NO_DYNAMIC_TARGETS
) -> tuple[BundleCall, ...]:
    """Every call out of the bundle's programs, joined to the callee's entry.

    Unresolved sites and calls out of the bundle are kept and carry an empty entry,
    because "this program calls something we did not build" is the answer a reader
    of the closure most often wants and deriving it back from nothing is not possible.

    A dynamic site ``targets`` answers is one call per candidate, each joined to that
    candidate's entry; ``certain`` is the three-way rule's proven case, one candidate
    and no reasons. A dynamic site with no candidates stays one call naming the field.
    """
    entries = entry_nodes(cfgs)
    return tuple(
        call
        for cfg in cfgs
        for site, node in _sites(cfg)
        for call in _calls_at(site, node, entries, targets)
    )


def _calls_at(
    site: CallSite, node: Node, entries: Mapping[str, str], targets: DynamicTargets
) -> tuple[BundleCall, ...]:
    if site.resolved:
        return (_call_to(site, node, site.program, entries),)
    answer = targets.at(site.caller, node.id)
    if not answer.candidates:
        unanswered = _dynamic_call(
            site, node, site.program, entries, answer.reasons, False
        )
        return (replace(unanswered, entry=""),)
    return tuple(
        _dynamic_call(site, node, candidate, entries, answer.reasons, answer.proven)
        for candidate in answer.candidates
    )


def _dynamic_call(
    site: CallSite,
    node: Node,
    program: str,
    entries: Mapping[str, str],
    reasons: tuple[str, ...],
    certain: bool,
) -> BundleCall:
    return replace(
        _call_to(site, node, program, entries),
        expression=site.program,
        reasons=reasons,
        certain=certain,
    )


def _call_to(
    site: CallSite, node: Node, program: str, entries: Mapping[str, str]
) -> BundleCall:
    return BundleCall(
        caller=site.caller,
        node=node.id,
        transfer=node.transfer,
        program=program,
        entry=entries.get(program, ""),
        resolved=site.resolved,
        commarea=site.commarea,
    )


def dynamic_callees(cfg: Cfg, targets: DynamicTargets) -> tuple[str, ...]:
    """Every candidate of every dynamic site in ``cfg`` that ``targets`` answers."""
    return tuple(
        sorted(
            {
                candidate
                for site in call_sites(cfg)
                if not site.resolved
                for candidate in targets.at(site.caller, site.node).candidates
            }
        )
    )


def callees_of(graph: CallGraph, program: str) -> tuple[str, ...]:
    return tuple(
        sorted({s.program for s in graph.sites if s.caller == program and s.resolved})
    )


def callers_of(graph: CallGraph, program: str) -> tuple[str, ...]:
    return tuple(
        sorted({s.caller for s in graph.sites if s.program == program and s.resolved})
    )


def unresolved_sites(graph: CallGraph) -> tuple[CallSite, ...]:
    return tuple(site for site in graph.sites if not site.resolved)
