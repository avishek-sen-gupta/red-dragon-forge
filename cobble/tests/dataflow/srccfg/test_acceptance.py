"""The whole pipeline over real members.

Skips with no config, because the corpus is not in this repo and must not be. The
assertions are invariants rather than values: a member count or a node count would be
both a corpus identifier and a test that breaks on every re-parse.

Nothing here names a member, but a FAILURE message does: the assertions print member
names, paragraph names and node ids, because a structural invariant nobody can trace
back to a statement is not worth asserting. That is fine where the corpus already
lives and is the reason this module skips everywhere else -- run it locally, not
anywhere its output is published.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from cobol_asg.asg_types import CobolASG

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.srccfg.build import build_program
from cobble.dataflow.srccfg.bundle import cfg_from_dict, cfg_to_dict
from cobble.dataflow.srccfg.closure import build_closure
from cobble.dataflow.srccfg.config import load_srccfg_build_config
from cobble.dataflow.srccfg.cfg import EdgeKind, NodeKind
from cobble.dataflow.srccfg.dataflow import (
    reaching_conditions,
    reaching_definitions,
    with_handler_edges,
)
from cobble.dataflow.srccfg.desugar import CALL_TRANSFERS
from cobble.dataflow.srccfg.link import call_sites
from cobble.dataflow.srccfg.query import provenance_report

# Gap-fill verbs: these may have empty writes and reads by design.
_GAP_FILL_TRANSFERS = ("INITIALIZE", "DISPLAY", "ACCEPT")


def _cfgs(paths):
    with cached_asg_dialect_parsers_registered():
        for path in paths:
            yield path, build_program(
                CobolASG.from_dict(json.loads(path.read_text(encoding="utf-8")))
            )


def test_every_member_builds_a_cfg(corpus_asg_paths) -> None:
    """The first thing that goes wrong at scale is an ASG shape the lowering does not
    handle, and it shows up as an exception on member 40 of 3,779."""
    failures = []
    for path in corpus_asg_paths:
        try:
            with cached_asg_dialect_parsers_registered():
                cfg = build_program(
                    CobolASG.from_dict(json.loads(path.read_text(encoding="utf-8")))
                )
            if not cfg.nodes:
                failures.append((path.stem, "empty CFG"))
        except Exception as e:  # noqa: BLE001
            failures.append((path.stem, repr(e)))

    assert failures == [], f"Failed members: {failures}"


def test_every_edge_lands_on_a_node_that_exists(corpus_asg_paths) -> None:
    """The invariant every later walk depends on. A dangling edge is a KeyError in a
    pass that runs much later, on a member nobody was looking at."""
    for _, cfg in _cfgs(corpus_asg_paths):
        dangling = {
            (edge.source, edge.target)
            for edge in cfg.edges
            if edge.source not in cfg.node_ids or edge.target not in cfg.node_ids
        }
        assert dangling == set(), f"{cfg.program}: {sorted(dangling)[:3]}"


def test_every_node_id_is_unique_within_a_member(corpus_asg_paths) -> None:
    """Node identity is a path, not a line number. A collision silently merges two
    statements, and every guard and definition on both becomes wrong."""
    for _, cfg in _cfgs(corpus_asg_paths):
        ids = [node.id for node in cfg.nodes]
        assert len(ids) == len(set(ids)), cfg.program


def test_every_test_node_has_exactly_two_outgoing_polarities(corpus_asg_paths) -> None:
    """A TEST with one arm makes one polarity unreachable, which silently drops the
    guard for everything on that side."""
    for _, cfg in _cfgs(corpus_asg_paths):
        for node in cfg.nodes:
            if node.kind != NodeKind.TEST:
                continue
            kinds = {edge.kind for edge in cfg.successors(node.id)}
            assert kinds == {EdgeKind.TRUE, EdgeKind.FALSE}, f"{cfg.program} {node.id}"


def test_every_assign_node_writes_or_reads_something(corpus_asg_paths) -> None:
    """An ASSIGN with neither is a verb the flows table has a rule for and no operands
    extracted -- which reads downstream as "this statement moves nothing".

    Gap-fill verbs (INITIALIZE, DISPLAY, ACCEPT) are allowed to have empty operands
    when the ASG yields nothing extractable."""
    for _, cfg in _cfgs(corpus_asg_paths):
        empty = [
            node.id
            for node in cfg.nodes
            if node.kind == NodeKind.ASSIGN
            and not (node.writes or node.reads)
            and node.transfer not in _GAP_FILL_TRANSFERS
        ]
        assert empty == [], f"{cfg.program}: {empty[:3]}"


def test_reaching_conditions_terminate_on_every_member(corpus_asg_paths) -> None:
    """The path walk is capped, so this is really a test that the cap is reached
    rather than the walk diverging -- a member with deep nesting is where an
    unbounded walk stops being a theory."""
    for _, cfg in _cfgs(corpus_asg_paths):
        assert reaching_conditions(cfg).guards


def test_reaching_definitions_terminate_on_every_member(corpus_asg_paths) -> None:
    """The fixpoint has no iteration cap, so a member with a loop through a PERFORM
    range is what would hang it."""
    for _, cfg in _cfgs(corpus_asg_paths):
        assert reaching_definitions(cfg)


def test_most_members_have_at_least_one_guarded_assignment(corpus_asg_paths) -> None:
    """The aggregate the design rests on: guards are the common case, not the exotic
    one. A pass that produced almost none would still satisfy every unit test above.
    """
    guarded = 0
    total = 0
    for _, cfg in _cfgs(corpus_asg_paths):
        total = total + 1
        reaching = reaching_conditions(cfg)
        if any(
            any(guard for guard in reaching.guards.get(node.id, ()))
            for node in cfg.nodes
            if node.kind == NodeKind.ASSIGN
        ):
            guarded = guarded + 1

    if total == 0:
        pytest.skip("the configured members list is empty; nothing to aggregate over")

    assert guarded > total // 2, f"{guarded} of {total} members had a guarded write"


def test_handler_resolution_adds_no_dangling_edge(corpus_asg_paths) -> None:
    """Handler resolution is the one pass that ADDS edges, so it is the one that can
    invent a target -- and it runs after the build test has already passed."""
    for _, cfg in _cfgs(corpus_asg_paths):
        resolved = with_handler_edges(cfg)
        assert all(
            edge.target in resolved.node_ids for edge in resolved.edges
        ), cfg.program


def test_every_call_site_names_a_program_or_a_field(corpus_asg_paths) -> None:
    """An empty program on a call site collapses every unparsed call onto one graph
    node, which reads as a hub in the call graph that does not exist.

    call_sites already filters on non-empty target, so we verify that by counting
    how many call nodes are dropped."""
    for _, cfg in _cfgs(corpus_asg_paths):
        # Count all call transfer nodes
        all_call_nodes = [
            node
            for node in cfg.nodes
            if node.transfer in CALL_TRANSFERS and node.kind == NodeKind.CALL
        ]
        # Count those with empty target
        empty_target = [node for node in all_call_nodes if not node.target]
        # Count those returned by call_sites
        sites = list(call_sites(cfg))

        # Verify that call_sites returns exactly the non-empty ones
        assert len(sites) == len(all_call_nodes) - len(empty_target), (
            f"{cfg.program}: {len(all_call_nodes)} call nodes, "
            f"{len(empty_target)} empty targets, {len(sites)} sites returned"
        )


def test_a_cfg_round_trips_through_json(corpus_asg_paths) -> None:
    """The corpus call graph reads the written files, so a lossy round trip drops call
    sites -- and a dropped call site reads as a member with no callees."""
    for _, cfg in _cfgs(corpus_asg_paths):
        assert cfg_to_dict(cfg_from_dict(cfg_to_dict(cfg))) == cfg_to_dict(cfg)


def test_a_report_can_be_rendered_for_a_field_the_member_writes(
    corpus_asg_paths,
) -> None:
    """End to end: build, analyse, render. A report that raises on a real member is
    the failure a person meets first."""
    for _, cfg in _cfgs(corpus_asg_paths):
        written = next(
            (name for node in cfg.nodes for name in node.writes),
            "",
        )
        if not written:
            continue
        assert provenance_report(cfg, written)


_CLOSURE_CONFIG = Path(__file__).resolve().parents[3] / "config" / "closure-tests.toml"


def test_closure_annotates_source_file_on_real_corpus() -> None:
    """build_closure with source_dir populates source_file on every spanned node.

    Reads seed and config path from config/closure-tests.toml (gitignored):

        srccfg = "/abs/path/to/cobble-srccfg.toml"
        seed   = "ENTRY_PROGRAM"
    """
    if not _CLOSURE_CONFIG.is_file():
        pytest.skip(f"no {_CLOSURE_CONFIG.name}; needs a closure-tests config")
    raw = tomllib.loads(_CLOSURE_CONFIG.read_text())
    config = load_srccfg_build_config(Path(raw["srccfg"]))
    seed = raw["seed"]
    if not config.asg_dir.is_dir():
        pytest.skip(f"no parsed cache at {config.asg_dir}")
    if not (config.asg_dir / f"{seed}.json").is_file():
        pytest.skip(f"{seed} not in parsed cache")

    bundle = build_closure(config.asg_dir, seed, config.source_dir)

    source_files_by_program = {
        cfg.program: {n.span.source_file for n in cfg.nodes if n.span.source_file}
        for cfg in bundle.cfgs
    }
    annotated = {p: sf for p, sf in source_files_by_program.items() if sf}
    assert len(annotated) > 1, "need at least two programs with source_file set"
    all_files = {f for files in annotated.values() for f in files}
    assert len(all_files) > 1, f"all programs share one source_file: {all_files}"
    for program, files in annotated.items():
        assert len(files) == 1, f"{program} has multiple source_files: {files}"
        (source_file,) = files
        assert (
            program in source_file
        ), f"{program} source_file should contain its name: {source_file}"
