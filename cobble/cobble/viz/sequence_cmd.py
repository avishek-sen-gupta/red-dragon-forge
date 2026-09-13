"""CLI: extract two-level sequence artifacts from cobble CFG.

Input:  <srccfg_dir>/cfg-<ENTRY>.json  (cobble CFG, list of program CFGs)
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
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import reduce
from pathlib import Path

from cobble.viz.models import (
    CrossProgramCall,
    CrossProgramSequence,
    ProgramSequence,
    SequenceOutput,
    SequenceStep,
)

_LOG = logging.getLogger(__name__)
_MAIN_PREFIXES = ("0000", "000", "MAIN", "CONTROL")
_MAX_DEPTH = 20

# Type aliases for CFG dicts (JSON-decoded, values are JSON scalars or lists/dicts)
CfgNode = Mapping[str, str]
CfgEdge = Mapping[str, str]
CfgDict = Mapping[str, object]


# ── CFG indexing ──────────────────────────────────────────────────────────────


def _entry_paragraph(cfg: CfgDict) -> str:
    return next(
        (
            n["paragraph"]
            for n in cfg.get("nodes", [])
            if n.get("kind") == "LABEL"
            and any(n["paragraph"].startswith(px) for px in _MAIN_PREFIXES)
        ),
        "",
    )


PerformsAcc = Mapping[str, tuple[str, ...]]


def _perform_paras(
    edge: CfgEdge, nodes_by_id: Mapping[str, CfgNode]
) -> tuple[str, str]:
    """Return (src_para, tgt_para) for a PERFORM edge; either may be ''."""
    if edge.get("kind") != "PERFORM":
        return "", ""
    src_para = nodes_by_id.get(edge.get("source", ""), {}).get("paragraph", "")
    tgt_para = (edge.get("target") or "").replace("#label", "").replace("#end", "")
    return src_para, tgt_para


def _add_perform(
    acc: PerformsAcc, edge: CfgEdge, nodes_by_id: Mapping[str, CfgNode]
) -> PerformsAcc:
    src_para, tgt_para = _perform_paras(edge, nodes_by_id)
    if not src_para or not tgt_para or src_para == tgt_para:
        return acc
    existing = acc.get(src_para, ())
    if tgt_para in existing:
        return acc
    return {**acc, src_para: (*existing, tgt_para)}


def _collect_performs(
    edges: Sequence[CfgEdge],
    nodes_by_id: Mapping[str, CfgNode],
) -> dict[str, tuple[str, ...]]:
    return reduce(lambda acc, e: _add_perform(acc, e, nodes_by_id), edges, {})


@dataclass(frozen=True)
class _LinksDecisions:
    para_link: dict[str, str]
    para_has_decision: dict[str, bool]


def _add_node_link_decision(acc: _LinksDecisions, node: CfgNode) -> _LinksDecisions:
    para = node.get("paragraph", "")
    if not para:
        return acc
    has_decision = (
        {**acc.para_has_decision, para: True}
        if node.get("kind") == "TEST"
        else acc.para_has_decision
    )
    target = node.get("target", "")
    is_cics_call = node.get("kind") == "CALL" and "CICS" in node.get("transfer", "")
    para_link = (
        {**acc.para_link, para: target}
        if is_cics_call and para not in acc.para_link and target
        else acc.para_link
    )
    return _LinksDecisions(para_link=para_link, para_has_decision=has_decision)


_CALL_TYPE: Mapping[tuple[bool, bool], str] = {
    (True, True): "conditional_loop",
    (True, False): "loop",
    (False, True): "conditional",
    (False, False): "simple",
}


def _determine_call_type(src_id: str, all_node_ids: frozenset[str]) -> str:
    is_loop = (src_id + "#loop#test") in all_node_ids or (
        src_id + "#loop#test.L"
    ) in all_node_ids
    is_cond = ".then." in src_id or ".else." in src_id
    return _CALL_TYPE[(is_loop, is_cond)]


def _collect_call_types(
    edges: Sequence[CfgEdge],
    nodes_by_id: Mapping[str, CfgNode],
) -> Mapping[str, str]:
    """Map tgt_paragraph -> call_type based on the PERFORM CALL node context."""
    all_ids = frozenset(nodes_by_id)
    return {
        tgt_para: _determine_call_type(src_id, all_ids)
        for edge in edges
        if edge.get("kind") == "PERFORM"
        for src_id in (nodes_by_id.get(edge.get("source", ""), {}).get("id", ""),)
        for tgt_para in (
            (edge.get("target") or "").replace("#label", "").replace("#end", ""),
        )
        if tgt_para
    }


def _index_cfg(
    cfg: CfgDict,
) -> tuple[
    dict[str, tuple[str, ...]],  # para -> ordered PERFORM targets
    dict[str, str],  # para -> callee program (first CICS LINK)
    dict[str, bool],  # para -> has any TEST node
    Mapping[str, str],  # para -> call_type
]:
    nodes = cfg.get("nodes", [])
    nodes_by_id: dict[str, CfgNode] = {n["id"]: n for n in nodes}
    para_performs = _collect_performs(cfg.get("edges", []), nodes_by_id)
    ld = reduce(_add_node_link_decision, nodes, _LinksDecisions({}, {}))
    call_types = _collect_call_types(cfg.get("edges", []), nodes_by_id)
    return para_performs, ld.para_link, ld.para_has_decision, call_types


# ── Per-program intra-program tree ───────────────────────────────────────────


def _walk_intra(
    para: str,
    para_performs: Mapping[str, tuple[str, ...]],
    para_link: Mapping[str, str],
    para_has_decision: Mapping[str, bool],
    call_types: Mapping[str, str],
    visited: frozenset[str],
    depth: int,
) -> tuple[SequenceStep, ...]:
    """Recursively build the PERFORM tree for a single program.
    CICS LINK calls become leaf "link" steps — no cross-program recursion.
    """
    if depth > _MAX_DEPTH or para in visited:
        return ()
    callee = para_link.get(para, "")
    children = tuple(
        step
        for child_para in para_performs.get(para, ())
        for step in _walk_intra(
            child_para,
            para_performs,
            para_link,
            para_has_decision,
            call_types,
            visited | {para},
            depth + 1,
        )
    )
    return (
        SequenceStep(
            type="link" if callee else "perform",
            paragraph=para,
            callee_program=callee,
            has_decision=para_has_decision.get(para, False),
            call_type=call_types.get(para, "simple"),
            children=children,
        ),
    )


def extract_per_program(cfg: CfgDict) -> ProgramSequence:
    program = str(cfg["program"])
    entry = _entry_paragraph(cfg)
    if not entry:
        return ProgramSequence(program=program, entry_paragraph="", steps=())
    para_performs, para_link, para_has_decision, call_types = _index_cfg(cfg)
    steps = tuple(
        step
        for child_para in para_performs.get(entry, ())
        for step in _walk_intra(
            child_para,
            para_performs,
            para_link,
            para_has_decision,
            call_types,
            frozenset({entry}),
            depth=1,
        )
    )
    return ProgramSequence(program=program, entry_paragraph=entry, steps=steps)


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
    cfg_by_prog: Mapping[str, CfgDict],
    cfg_indices: Mapping[str, tuple],
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
    cfg_by_prog: Mapping[str, CfgDict],
    cfg_indices: Mapping[str, tuple],
    target_programs: frozenset[str],
    state: _CrossState,
    depth: int,
) -> _CrossState:
    """Walk the full call tree; return updated state (calls, visited)."""
    if depth > _MAX_DEPTH or f"{program}/{para}" in state.visited:
        return state
    after_mark = _CrossState(state.calls, state.visited | {f"{program}/{para}"})
    para_performs, para_link, _, _call_types = cfg_indices[program]
    after_children = reduce(
        lambda st, child_para: _walk_cross(
            program,
            child_para,
            cfg_by_prog,
            cfg_indices,
            target_programs,
            st,
            depth + 1,
        ),
        para_performs.get(para, ()),
        after_mark,
    )
    return _emit_callee(
        after_children,
        para_link.get(para, ""),
        para,
        program,
        cfg_by_prog,
        cfg_indices,
        target_programs,
        depth,
    )


def extract_cross_program(
    entry_program: str,
    cfg_by_prog: Mapping[str, CfgDict],
    target_programs: frozenset[str],
    cfg_indices: Mapping[str, tuple],
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
    output = SequenceOutput(cross_program=cross, per_program=per_program)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(output.model_dump_json(indent=2))
    _LOG.info(
        "sequences.json: %d cross-program calls, %d programs with intra-program trees",
        len(cross.calls),
        len(per_program),
    )


def _run(args: argparse.Namespace) -> None:
    cfgs_raw: list[dict] = json.loads(args.cfg.read_text())
    cfg_by_prog: dict[str, CfgDict] = {c["program"]: c for c in cfgs_raw}
    targets = frozenset(cfg_by_prog.keys())
    entry = args.entry or next(iter(sorted(targets)))
    cfg_indices = {prog: _index_cfg(cfg) for prog, cfg in cfg_by_prog.items()}
    per_program = {
        prog: extract_per_program(cfg_by_prog[prog])
        for prog in sorted(targets)
        if prog in cfg_by_prog
    }
    _write_output(
        args,
        extract_cross_program(entry, cfg_by_prog, targets, cfg_indices),
        per_program,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cfg", required=True, type=Path, help="cobble cfg-<ENTRY>.json")
    ap.add_argument("--entry", default="", help="entry program (default: first in CFG)")
    ap.add_argument("--out", required=True, type=Path, help="output sequences.json")
    _run(ap.parse_args())
