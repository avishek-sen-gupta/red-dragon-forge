"""Run one member's fixpoint step by step and report where its work goes."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType

import networkx as nx
from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.fields.state import State
from cobble.dataflow.fixpoint.area_need_file import read_rows, table_of
from cobble.dataflow.fixpoint.fixpoint import stepwise
from cobble.dataflow.fixpoint.options import AnalysisOptions
from cobble.dataflow.fixpoint.scope import Scope
from cobble.dataflow.fixpoint.step_fact import StepFact
from cobble.dataflow.fixpoint.stepped import Stepped
from cobble.dataflow.srccfg.cfg import Cfg
from cobble.parsing.asg_cache import cached_first_program

USAGE = """\
Walks the member exactly as cobble-dataflow-fixpoint does, stopping after
--max-steps dequeues, and reports: the nodes dequeued most and how often a
dequeue grew a successor; the size of the cycle each hot node sits in; which
fields keep gaining entries or writers; the tallest writer sets at the end; and
reached nodes, entries and the largest state every --every steps.

Paragraph and field names print as they are. --anonymise replaces them with
stable aliases (PARA-001, FIELD-001) so the report can be shared.
"""

_EMPTY = State()


def _grown_fields(before: State, after: State) -> tuple[str, ...]:
    return tuple(
        extent.field_name
        for extent, held in after.sources.items()
        if before.sources.get(extent) != held
    )


def _grew(cfg: Cfg, step: Stepped) -> tuple[str, ...]:
    """Only a successor of the node taken can grow, so only those are compared."""
    return tuple(
        edge.target
        for edge in cfg.successors(step.node)
        if step.before.get(edge.target) is not step.after.get(edge.target)
    )


def _snapshot(dequeues: int, states: Mapping[str, State], queued: int) -> str:
    sizes = tuple(len(state.sources) for state in states.values())
    return (
        f"  {dequeues:8} {len(states):6} {queued:6} "
        f"{sum(sizes):10} {max(sizes, default=0):6}"
    )


def _fact(cfg: Cfg, step: Stepped, every: int, cap: int) -> StepFact:
    grew = _grew(cfg, step)
    last = step.queued == 0 or step.dequeues >= cap
    return StepFact(
        node=step.node,
        grew=grew,
        fields=tuple(
            name
            for node in grew
            for name in _grown_fields(step.before.get(node, _EMPTY), step.after[node])
        ),
        queued=step.queued,
        snapshot=(
            _snapshot(step.dequeues, step.after, step.queued)
            if last or not step.dequeues % every
            else ""
        ),
        final=step.after if last else MappingProxyType({}),
    )


def _cycle_sizes(cfg: Cfg) -> Mapping[str, int]:
    graph: nx.DiGraph[str] = nx.DiGraph()
    graph.add_nodes_from(node.id for node in cfg.nodes)
    graph.add_edges_from((edge.source, edge.target) for edge in cfg.edges)
    return MappingProxyType(
        {
            node: len(component)
            for component in nx.strongly_connected_components(graph)
            for node in component
        }
    )


def _namer(anonymise: bool, names: Sequence[str], prefix: str) -> Callable[[str], str]:
    if not anonymise:
        return lambda name: name
    table = {
        name: f"{prefix}-{position:03d}"
        for position, name in enumerate(sorted(set(names)), 1)
    }
    return lambda name: table.get(name, name)


def _label(cfg: Cfg, node: str, para: Callable[[str], str]) -> str:
    found = cfg.node(node)
    return f"{para(found.paragraph)} line {found.span.line_start} ({found.kind.value})"


def _summary(
    cfg: Cfg, final: Mapping[str, State], facts: Sequence[StepFact]
) -> tuple[str, ...]:
    growing = sum(1 for fact in facts if fact.grew)
    queued = facts[-1].queued
    state = "settled" if not queued else "not settled"
    return (
        f"nodes {len(cfg.nodes)}, reached {len(final)}, steps {len(facts)}, "
        f"queue left {queued} ({state})",
        f"steps that grew a successor: {growing} "
        f"({100 * growing // max(len(facts), 1)}%)",
        "",
    )


def _hot(
    cfg: Cfg, facts: Sequence[StepFact], para: Callable[[str], str]
) -> tuple[str, ...]:
    cycles = _cycle_sizes(cfg)
    taken = Counter(fact.node for fact in facts)
    grew = Counter(fact.node for fact in facts if fact.grew)
    paragraphs = Counter(cfg.node(fact.node).paragraph for fact in facts)
    return (
        "hottest nodes (dequeues, of which grew a successor, cycle size):",
        *(
            f"  {taken_:7} {grew[node]:7}  cycle {cycles.get(node, 1):5}  "
            f"{_label(cfg, node, para)}"
            for node, taken_ in taken.most_common(25)
        ),
        "",
        "hottest paragraphs (dequeues):",
        *(f"  {taken_:7}  {para(name)}" for name, taken_ in paragraphs.most_common(15)),
        "",
    )


def _growing(facts: Sequence[StepFact], field: Callable[[str], str]) -> tuple[str, ...]:
    grown = Counter(name for fact in facts for name in fact.fields)
    return (
        "fields gaining entries or writers most often (growth events):",
        *(f"  {events:8}  {field(name)}" for name, events in grown.most_common(25)),
        "",
    )


def _tallest(
    final: Mapping[str, State], field: Callable[[str], str]
) -> tuple[str, ...]:
    heights = Counter(
        {
            (extent.field_name, extent.start, extent.length): len(held)
            for state in final.values()
            for extent, held in state.sources.items()
        }
    )
    sizes = Counter(
        len(held) for state in final.values() for held in state.sources.values()
    )
    return (
        "tallest writer sets at the end (writers, field@start+length):",
        *(
            f"  {height:5}  {field(name)}@{start}+{length}"
            for (name, start, length), height in heights.most_common(20)
        ),
        "",
        "writer-set sizes over all entries (size: entries):",
        "  " + ", ".join(f"{size}: {n}" for size, n in sorted(sizes.items())),
        "",
    )


def report(
    asg_path: Path,
    options: AnalysisOptions,
    max_steps: int,
    every: int,
    anonymise: bool,
) -> str:
    """The diagnostic report for one member's walk, ``max_steps`` dequeues at most."""
    asg = cached_first_program(asg_path.parent, asg_path)
    cfg, walk = stepwise(asg, options, max_steps)
    facts = tuple(_fact(cfg, step, every, max_steps) for step in walk)
    if not facts:
        return "no steps taken: the entry paragraph is not in the CFG\n"
    final = facts[-1].final
    para = _namer(anonymise, tuple(node.paragraph for node in cfg.nodes), "PARA")
    field = _namer(
        anonymise,
        tuple(
            extent.field_name for state in final.values() for extent in state.sources
        ),
        "FIELD",
    )
    return "\n".join(
        (
            *_summary(cfg, final, facts),
            *_hot(cfg, facts, para),
            *_growing(facts, field),
            *_tallest(final, field),
            "timeline (dequeues, reached, queued, total entries, largest state):",
            *(fact.snapshot for fact in facts if fact.snapshot),
            "",
        )
    )


def _parsed(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cobble-dataflow-fixpoint-diagnose",
        description=__doc__,
        epilog=USAGE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--asg-dir", type=Path, required=True)
    parser.add_argument("--member", required=True)
    parser.add_argument("--max-steps", type=int, default=50000)
    parser.add_argument("--every", type=int, default=5000)
    parser.add_argument("--call-targets-only", action="store_true")
    parser.add_argument(
        "--narrow-areas",
        default="",
        metavar="FILE",
        help="with --call-targets-only: walk as cobble-dataflow-fixpoint"
        " --narrow-areas FILE does, tracking only the handed-over bytes the"
        " area-need file says some program needs",
    )
    parser.add_argument("--anonymise", action="store_true")
    return parser.parse_args(argv)


def _refusal(arguments: argparse.Namespace, path: Path) -> str:
    if not path.is_file():
        return f"fields: !! no cached ASG at {path}\n"
    if arguments.narrow_areas and not arguments.call_targets_only:
        return "fields: !! --narrow-areas needs --call-targets-only\n"
    return ""


def _options(arguments: argparse.Namespace) -> AnalysisOptions:
    """The options cobble-dataflow-fixpoint walks this member with, for the same flags."""
    if arguments.narrow_areas:
        table = table_of(read_rows(Path(arguments.narrow_areas)))
        return AnalysisOptions(
            scope=Scope.NARROW_CALL_TARGETS, areas=table.seen_from(arguments.member)
        )
    scope = Scope.CALL_TARGETS if arguments.call_targets_only else Scope.WHOLE
    return AnalysisOptions(scope=scope)


def cli(argv: Sequence[str]) -> int:
    arguments = _parsed(argv)
    path = arguments.asg_dir / f"{arguments.member}.json"
    refusal = _refusal(arguments, path)
    if refusal:
        sys.stderr.write(refusal)
        return 2
    sys.stdout.write(
        report(
            path,
            _options(arguments),
            arguments.max_steps,
            arguments.every,
            arguments.anonymise,
        )
    )
    return 0


def main() -> int:
    configure_cli_logging()
    return cli(sys.argv[1:])
