"""CLI: extract two-level sequence artifacts from cobble CFG.

Input:  <srccfg_dir>/cfg-<ENTRY>.jsonl  (cobble CFG, or a closure bundle of them)
Output: <out_dir>/sequences.json  (SequenceOutput)

Produces two artifacts in one pass:

  cross_program — flat ordered list of CICS LINK calls across programs,
                  derived by walking the full call tree from the entry program.

  per_program   — for each program, its intra-program PERFORM tree only;
                  CICS LINK calls appear as "link" leaf steps (no recursion
                  into the callee).
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import reduce
from pathlib import Path

from cobble.dataflow.srccfg.bundle import load_bundle
from cobble.dataflow.srccfg.cfg import Cfg, Edge, EdgeKind, Node, NodeKind
from cobble.path_utils import ensure_parent
from cobble.viz.models import (
    Arm,
    CrossProgramCall,
    CrossProgramSequence,
    ProgramSequence,
    SequenceOutput,
    SequenceStep,
)

_LOG = logging.getLogger(__name__)
_MAIN_PREFIXES = ("0000", "000", "MAIN", "CONTROL")
_MAX_DEPTH = 20

# ── CFG indexing ──────────────────────────────────────────────────────────────


def _entry_paragraph(cfg: Cfg) -> str:
    return next(
        (
            node.paragraph
            for node in cfg.nodes
            if node.kind is NodeKind.LABEL
            and any(node.paragraph.startswith(px) for px in _MAIN_PREFIXES)
        ),
        "",
    )


@dataclass(frozen=True)
class _Site:
    """One PERFORM statement: the CALL node issuing it and the paragraph it runs."""

    node: str
    target: str


PerformsAcc = Mapping[str, tuple[_Site, ...]]


def _perform_paras(edge: Edge, nodes_by_id: Mapping[str, Node]) -> tuple[str, str]:
    """Return (src_para, tgt_para) for a PERFORM edge; either may be ''."""
    if edge.kind is not EdgeKind.PERFORM:
        return "", ""
    src_para = nodes_by_id[edge.source].paragraph if edge.source in nodes_by_id else ""
    tgt_para = edge.target.replace("#label", "").replace("#end", "")
    return src_para, tgt_para


def _add_perform(
    acc: PerformsAcc, edge: Edge, nodes_by_id: Mapping[str, Node]
) -> PerformsAcc:
    src_para, tgt_para = _perform_paras(edge, nodes_by_id)
    if not src_para or not tgt_para or src_para == tgt_para:
        return acc
    site = _Site(node=edge.source, target=tgt_para)
    return {**acc, src_para: (*acc.get(src_para, ()), site)}


def _collect_performs(
    edges: Sequence[Edge],
    nodes_by_id: Mapping[str, Node],
) -> PerformsAcc:
    return reduce(lambda acc, e: _add_perform(acc, e, nodes_by_id), edges, {})


@dataclass(frozen=True)
class _LinksDecisions:
    para_link: dict[str, str]
    para_has_decision: dict[str, bool]


def _add_node_link_decision(acc: _LinksDecisions, node: Node) -> _LinksDecisions:
    if not node.paragraph:
        return acc
    has_decision = (
        {**acc.para_has_decision, node.paragraph: True}
        if node.kind is NodeKind.TEST
        else acc.para_has_decision
    )
    is_cics_call = node.kind is NodeKind.CALL and "CICS" in node.transfer
    para_link = (
        {**acc.para_link, node.paragraph: node.target}
        if is_cics_call and node.paragraph not in acc.para_link and node.target
        else acc.para_link
    )
    return _LinksDecisions(para_link=para_link, para_has_decision=has_decision)


_CALL_TYPE: Mapping[tuple[bool, bool], str] = {
    (True, True): "conditional_loop",
    (True, False): "loop",
    (False, True): "conditional",
    (False, False): "simple",
}


@dataclass(frozen=True)
class _Index:
    """What the tree walks read from one program's CFG."""

    performs: Mapping[str, tuple[_Site, ...]]  # paragraph -> PERFORM sites, in order
    links: Mapping[str, str]  # paragraph -> first CICS call target
    has_decision: Mapping[str, bool]  # paragraph -> has any TEST node
    node_ids: frozenset[str]
    tests: Mapping[str, str]  # TEST node id -> condition text


_ARM_SEGMENTS = frozenset({"then", "else", "when"})


def _arms(site: str, tests: Mapping[str, str]) -> tuple[Arm, ...]:
    """The arms enclosing a site, outermost first, read off its statement path.

    srccfg names a node by its route from its paragraph: ``9.when.2.1.else.0`` is
    statement 0 of the ELSE of statement 1, inside WHEN 2 of statement 9.
    """
    paragraph, _, path = site.partition("#")[0].partition("/")
    segments = tuple(path.split("."))
    return tuple(
        _arm(f"{paragraph}/{'.'.join(segments[:at])}", segments, at, tests)
        for at, segment in enumerate(segments)
        if segment in _ARM_SEGMENTS and at + (segment == "when") < len(segments)
    )


def _arm(
    decision: str, segments: tuple[str, ...], at: int, tests: Mapping[str, str]
) -> Arm:
    if segments[at] == "when":
        branch = f"when.{segments[at + 1]}"
        text = _test_text(f"{decision}.{branch}", tests)
        return Arm(decision=decision, arm=branch, label=f"WHEN {text or 'OTHER'}")
    prefix = "IF" if segments[at] == "then" else "NOT"
    return Arm(
        decision=decision,
        arm=segments[at],
        label=f"{prefix} {_test_text(decision, tests)}",
    )


def _test_text(statement: str, tests: Mapping[str, str]) -> str:
    """The condition tested for ``statement``: its one TEST node, or a compound
    condition's halves (``#test.L``, ``#test.R``) side by side."""
    whole = tests.get(f"{statement}#test", "")
    if whole:
        return whole
    halves = sorted(
        (node, text)
        for node, text in tests.items()
        if node.startswith(f"{statement}#test.")
    )
    return " / ".join(text for _, text in halves)


def _call_type(site: str, arms: tuple[Arm, ...], index: _Index) -> str:
    is_loop = (
        f"{site}#loop#test" in index.node_ids or f"{site}#loop#test.L" in index.node_ids
    )
    return _CALL_TYPE[(is_loop, bool(arms))]


def _index_cfg(cfg: Cfg) -> _Index:
    nodes_by_id = {node.id: node for node in cfg.nodes}
    ld = reduce(_add_node_link_decision, cfg.nodes, _LinksDecisions({}, {}))
    return _Index(
        performs=_collect_performs(cfg.edges, nodes_by_id),
        links=ld.para_link,
        has_decision=ld.para_has_decision,
        node_ids=frozenset(nodes_by_id),
        tests={
            node.id: node.atom.text for node in cfg.nodes if node.kind is NodeKind.TEST
        },
    )


# ── Per-program intra-program tree ───────────────────────────────────────────


def _walk_intra(
    site: _Site,
    index: _Index,
    visited: frozenset[str],
    depth: int,
) -> tuple[SequenceStep, ...]:
    """One step for one PERFORM site, with the sites its target performs beneath it.

    A step per site rather than per target paragraph: a paragraph PERFORMed from
    three arms is three calls, each with its own arms and call type.
    CICS LINK calls become leaf "link" steps — no cross-program recursion.
    """
    para = site.target
    if depth > _MAX_DEPTH or para in visited:
        return ()
    callee = index.links.get(para, "")
    arms = _arms(site.node, index.tests)
    return (
        SequenceStep(
            type="link" if callee else "perform",
            paragraph=para,
            callee_program=callee,
            has_decision=index.has_decision.get(para, False),
            call_type=_call_type(site.node, arms, index),
            arms=arms,
            children=_steps_of(para, index, visited | {para}, depth + 1),
        ),
    )


def _steps_of(
    para: str, index: _Index, visited: frozenset[str], depth: int
) -> tuple[SequenceStep, ...]:
    return tuple(
        step
        for site in index.performs.get(para, ())
        for step in _walk_intra(site, index, visited, depth)
    )


def extract_per_program(cfg: Cfg) -> ProgramSequence:
    entry = _entry_paragraph(cfg)
    if not entry:
        return ProgramSequence(program=cfg.program, entry_paragraph="", steps=())
    steps = _steps_of(entry, _index_cfg(cfg), frozenset({entry}), depth=1)
    return ProgramSequence(program=cfg.program, entry_paragraph=entry, steps=steps)


# ── Cross-program ordered call list ──────────────────────────────────────────


@dataclass(frozen=True)
class _CrossState:
    calls: tuple[CrossProgramCall, ...]
    visited: frozenset[str]


def _emit_callee(
    after_children: _CrossState,
    callee: str,
    para: str,
    program: str,
    cfg_by_prog: Mapping[str, Cfg],
    cfg_indices: Mapping[str, _Index],
    target_programs: frozenset[str],
    depth: int,
) -> _CrossState:
    if not callee or callee not in target_programs or callee not in cfg_by_prog:
        return after_children
    link_call = CrossProgramCall(
        from_program=program, to_program=callee, via_paragraph=para
    )
    after_link = _CrossState((*after_children.calls, link_call), after_children.visited)
    callee_entry = _entry_paragraph(cfg_by_prog[callee])
    if not callee_entry:
        return after_link
    return _walk_cross(
        callee,
        callee_entry,
        cfg_by_prog,
        cfg_indices,
        target_programs,
        after_link,
        depth + 1,
    )


def _walk_cross(
    program: str,
    para: str,
    cfg_by_prog: Mapping[str, Cfg],
    cfg_indices: Mapping[str, _Index],
    target_programs: frozenset[str],
    state: _CrossState,
    depth: int,
) -> _CrossState:
    """Walk the full call tree; return updated state (calls, visited)."""
    if depth > _MAX_DEPTH or f"{program}/{para}" in state.visited:
        return state
    after_mark = _CrossState(state.calls, state.visited | {f"{program}/{para}"})
    index = cfg_indices[program]
    after_children = reduce(
        lambda st, site: _walk_cross(
            program,
            site.target,
            cfg_by_prog,
            cfg_indices,
            target_programs,
            st,
            depth + 1,
        ),
        index.performs.get(para, ()),
        after_mark,
    )
    return _emit_callee(
        after_children,
        index.links.get(para, ""),
        para,
        program,
        cfg_by_prog,
        cfg_indices,
        target_programs,
        depth,
    )


def extract_cross_program(
    entry_program: str,
    cfg_by_prog: Mapping[str, Cfg],
    target_programs: frozenset[str],
    cfg_indices: Mapping[str, _Index],
) -> CrossProgramSequence:
    entry_cfg = cfg_by_prog.get(entry_program)
    if not entry_cfg:
        return CrossProgramSequence(entry=entry_program, calls=())
    entry_para = _entry_paragraph(entry_cfg)
    if not entry_para:
        return CrossProgramSequence(entry=entry_program, calls=())
    final = _walk_cross(
        entry_program,
        entry_para,
        cfg_by_prog,
        cfg_indices,
        target_programs,
        _CrossState((), frozenset()),
        depth=0,
    )
    return CrossProgramSequence(entry=entry_program, calls=final.calls)


# ── CLI ───────────────────────────────────────────────────────────────────────


def _write_output(
    args: argparse.Namespace,
    cross: CrossProgramSequence,
    per_program: Mapping[str, ProgramSequence],
) -> None:
    output = SequenceOutput(cross_program=cross, per_program=dict(per_program))
    ensure_parent(args.out).write_text(output.model_dump_json(indent=2))
    _LOG.info(
        "sequences.json: %d cross-program calls, %d programs with intra-program trees",
        len(cross.calls),
        len(per_program),
    )


def _run(args: argparse.Namespace) -> int:
    cfg_by_prog = {cfg.program: cfg for cfg in load_bundle(args.cfg).cfgs}
    targets = frozenset(cfg_by_prog)
    if args.entry and args.entry not in targets:
        _LOG.error(
            "error: entry program %s is not in %s; it holds %s",
            args.entry,
            args.cfg,
            ", ".join(sorted(targets)),
        )
        return 1
    entry = args.entry or next(iter(sorted(targets)))
    cfg_indices = {prog: _index_cfg(cfg) for prog, cfg in cfg_by_prog.items()}
    per_program = {
        prog: extract_per_program(cfg_by_prog[prog]) for prog in sorted(targets)
    }
    _write_output(
        args,
        extract_cross_program(entry, cfg_by_prog, targets, cfg_indices),
        per_program,
    )
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cfg", required=True, type=Path, help="cobble cfg-<ENTRY>.jsonl")
    ap.add_argument("--entry", default="", help="entry program (default: first in CFG)")
    ap.add_argument("--out", required=True, type=Path, help="output sequences.json")
    return _run(ap.parse_args())
