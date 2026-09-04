"""Four queries over one member's CFG, printed for a person.

Names go to stdout and nowhere else: they are corpus identifiers, and the pattern the
copybook diagnostic settled on is that the machine channel carries the answer while
the log stays safe to tail.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from cobble.dataflow.srccfg.build_corpus import load_cfg
from cobble.dataflow.srccfg.cfg import Atom, Cfg
from cobble.dataflow.srccfg.coassign import Tier, caveats, co_assigned
from cobble.dataflow.srccfg.conditions import VALUE_OPS
from cobble.dataflow.srccfg.dataflow import (
    Reaching,
    guard_text,
    guards_of,
    reaching_conditions,
    writers_of,
)
from cobble.dataflow.srccfg.literals import is_literal
from cobble.dataflow.srccfg.synthetic import describe, is_synthetic

MAX_DEPTH = 6
UNCONDITIONAL = "unconditional"

CAP_NOTE = "(guard cap hit: this list is incomplete)"
SUBSET_NOTE = "(subset: paths upstream were also truncated)"


@dataclass(frozen=True)
class GuardLines:
    """One node's guard text, and the caveats that have to travel with it.

    ``notes`` is not decoration. R48/R52 make the walk name every node whose guard
    list the cap cut short, and a report that prints ``texts`` alone states those
    guards as the complete set of conditions -- which is a claim the walk did not
    establish. Producing the note here, beside the guards, is what stops the next
    report added from forgetting it: there is no route to the guard text that does
    not also hand over the caveat.
    """

    texts: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def writers_report(cfg: Cfg, field: str) -> tuple[str, ...]:
    """List every node that writes a field, with guards for each write.

    F6: Shows verbatim operands (including literals like SPACES) because a writers
    listing describes what the statement actually reads. The derivation report filters
    literals because it chases dependencies, and a literal is not a dependency."""
    nodes = writers_of(cfg, field)
    if not nodes:
        return (f"{field}: written nowhere in {cfg.program}",)
    reaching = reaching_conditions(cfg)
    return (
        f"{field}: {len(nodes)} writer(s) in {cfg.program}",
        *tuple(
            line for node_id in nodes for line in _writer_lines(cfg, reaching, node_id)
        ),
    )


def _writer_lines(cfg: Cfg, reaching: Reaching, node_id: str) -> tuple[str, ...]:
    node = cfg.node(node_id)
    head = f"  {node_id}  {node.transfer or 'ASSIGN'}  reads {', '.join(node.reads) or '(none)'}"
    guards = _guard_lines(cfg, reaching, node_id)
    return (
        head,
        *tuple(f"    when {text}" for text in guards.texts),
        *tuple(f"    {note}" for note in guards.notes),
    )


def _guard_lines(cfg: Cfg, reaching: Reaching, node_id: str) -> GuardLines:
    """Render the guards of a node, distinguishing dead code from abandoned walks.

    Per Reaching's contract (R7): no-guards splits three ways. A node in `abandoned`
    has no guards because the walk gave up, not because the program cannot reach it.
    Only zero guards AND not in abandoned may be reported as unreachable.

    The cap note rides along, on ``overflowed`` and not on ``truncated`` (R77):
    ``truncated`` is ``overflowed`` closed forward, so on branch-heavy code it holds
    nearly every node and a note on every line is a note nobody reads. ``overflowed``
    is the set that says the cap, rather than the program, rationed the answer."""
    return GuardLines(
        texts=_guard_texts(cfg, reaching, node_id),
        notes=(CAP_NOTE,) if node_id in reaching.overflowed else (),
    )


def _guard_texts(cfg: Cfg, reaching: Reaching, node_id: str) -> tuple[str, ...]:
    guards = guards_of(reaching, node_id)
    if guards:
        return tuple(
            " AND ".join(guard_text(cfg, guard)) or UNCONDITIONAL for guard in guards
        )
    if node_id in reaching.abandoned:
        return ("route not found by walk (overlapping PERFORM or similar)",)
    return (f"unreachable from {cfg.program} entry",)


def guards_report(cfg: Cfg, node_id: str) -> tuple[str, ...]:
    reaching = reaching_conditions(cfg)
    guards = _guard_lines(cfg, reaching, node_id)
    # R77: the subset warning belongs on the detailed report, paired with the cap note
    truncated_note = (f"  {SUBSET_NOTE}",) if node_id in reaching.truncated else ()
    return (
        f"{node_id}: {len(guards_of(reaching, node_id))} path(s)",
        *tuple(f"  path {n}: {text}" for n, text in enumerate(guards.texts)),
        *tuple(f"  {note}" for note in guards.notes),
        *truncated_note,
    )


def derivation_report(
    cfg: Cfg, field: str, max_depth: int = MAX_DEPTH
) -> tuple[str, ...]:
    reaching = reaching_conditions(cfg)
    return (
        f"{field} in {cfg.program}:",
        *_chain(cfg, reaching, field, 1, max_depth, frozenset()),
    )


def _chain(
    cfg: Cfg,
    reaching: Reaching,
    field: str,
    depth: int,
    max_depth: int,
    seen: frozenset[str],
) -> tuple[str, ...]:
    pad = "  " * depth
    if field in seen:
        return (f"{pad}{field} (already shown)",)
    if depth > max_depth:
        return (f"{pad}{field} (truncated at depth {max_depth})",)
    # F5: A name this pass invented is not a field the member failed to write
    synthetic = is_synthetic(field)
    if synthetic:
        return (f"{pad}{field} <- {describe(synthetic)}",)
    nodes = writers_of(cfg, field)
    if not nodes:
        return (f"{pad}{field} <- source (written nowhere in this member)",)
    # Show the field being derived, then the writers
    return (
        f"{pad}{field} <-",
        *tuple(
            line
            for node_id in nodes
            for line in _from_node(
                cfg, reaching, node_id, field, depth, max_depth, seen | {field}
            )
        ),
    )


def _from_node(
    cfg: Cfg,
    reaching: Reaching,
    node_id: str,
    field: str,
    depth: int,
    max_depth: int,
    seen: frozenset[str],
) -> tuple[str, ...]:
    """Chase the derivation back from one writer.

    F1 (R54): A field's dependencies are not just what the writer reads. If a field
    appears in a reaching condition for the write, it is a control dependency. Chase
    both node.reads (data dependencies) and the operands from TEST nodes in the guards
    (control dependencies)."""
    node = cfg.node(node_id)
    pad = "  " * depth
    guards = _guard_lines(cfg, reaching, node_id)
    head = f"{pad}{node_id} {node.transfer or 'ASSIGN'} when {'; '.join(guards.texts)}"
    notes = tuple(f"{pad}  {note}" for note in guards.notes)

    # Data dependencies: fields the node reads
    data_deps = [name for name in node.reads if not is_literal(name)]

    # Control dependencies (F1/R54): fields in the guards
    control_deps = _guard_operands(cfg, reaching, node_id)

    # Combine both, removing duplicates while preserving that data deps come first
    all_deps = list(dict.fromkeys(data_deps + control_deps))

    if not all_deps:
        return (
            head,
            *notes,
            f"{pad}  {field} <- source ({_terminus(cfg, reaching, node_id)})",
        )

    return (
        head,
        *notes,
        *tuple(
            line
            for name in all_deps
            for line in _chain(cfg, reaching, name, depth + 1, max_depth, seen)
        ),
    )


def _terminus(cfg: Cfg, reaching: Reaching, node_id: str) -> str:
    """Why the chain stopped here, which is not always what stopped it.

    F2 (Task 16) made a chain say why it ended; F-6 is that it said the wrong why.
    A write whose operands are all literals and a write guarded by a condition this
    pass could not decompose both leave nothing to follow, and reporting the second
    as "literal-only operands" contradicts the node line directly above it, which
    says UNRESOLVED. Two terminal states, two wordings."""
    if _unresolved_guard(cfg, reaching, node_id):
        return "unresolved condition, no operands to follow"
    return "literal-only operands"


def _unresolved_guard(cfg: Cfg, reaching: Reaching, node_id: str) -> bool:
    return any(
        not cfg.node(step_id).atom.resolved
        for guard in guards_of(reaching, node_id)
        for step_id, _kind in guard
    )


def _guard_operands(cfg: Cfg, reaching: Reaching, node_id: str) -> list[str]:
    """Extract field operands from TEST nodes in this node's guards.

    F1 (R54): Control dependencies. A field that appears only in a guard, never in a
    read, is still a dependency of the write. TEST nodes store operands in atom.left
    and atom.right, not in node.reads."""
    all_operands = (
        operand
        for guard in guards_of(reaching, node_id)
        for step_id, _kind in guard
        for operand in _operands(cfg.node(step_id).atom)
        if operand and not is_literal(operand)
    )
    # Remove duplicates while preserving order
    return list(dict.fromkeys(all_operands))


def _operands(atom: Atom) -> tuple[str, ...]:
    """The operands of one guard step, and only the operands.

    F5: ``atom.right`` is a second operand for a relation between two things and a
    VALUE for everything else -- a class name for IS NUMERIC, an 88's list of values
    for IN, the keyword RAISED for the handler test. Harvesting those printed
    ``NUMERIC`` and ``RAISED`` as fields written nowhere in the member, which spends
    the credibility of that line where it is genuinely true, as it is for a commarea
    or a file-read source.

    A synthetic left-hand side is the same case reached differently: the right of
    ``%HANDLER[ANY] RAISED`` or ``%IOSTATUS[F] == AT END`` is the state being tested
    for, not a field. The left IS kept -- the write does depend on it -- and the
    chain then labels it rather than claiming the member never wrote it."""
    if atom.op in VALUE_OPS or is_synthetic(atom.left):
        return (atom.left,)
    return (atom.left, atom.right)


def coassign_report(
    cfg: Cfg, field: str, min_tier: Tier = Tier.SAME_PARAGRAPH
) -> tuple[str, ...]:
    reaching = reaching_conditions(cfg)
    found = co_assigned(cfg, field, reaching, min_tier=min_tier)
    # F3: a comparison declined for want of guards must not read as "no candidate"
    notes = tuple(f"  ({c.node}: {c.reason})" for c in caveats(cfg, field, reaching))
    if not found:
        return (
            f"{field}: no co-assignment candidates at tier {min_tier.name} or stronger",
            *notes,
        )
    return (
        f"{field}: {len(found)} candidate(s)",
        *tuple(
            f"  {c.tier.name:<15} {c.field}"
            + (f"  shared {', '.join(c.shared)}" if c.shared else "")
            + f"  ({c.nodes[0]} / {c.nodes[1]})"
            for c in found
        ),
        *notes,
    )


_QUERIES = ("writers", "guards", "derivation", "coassign")


def main(argv: Sequence[str] = ()) -> int:
    parser = _parser()
    arguments = parser.parse_args(tuple(argv) or None)
    if not arguments.cfg.is_file():
        # F10: Use sys.stderr.write() instead of print() to avoid RUF100
        sys.stderr.write(f"No CFG at {arguments.cfg}\n")
        return 2
    for line in _lines(load_cfg(arguments.cfg), arguments):
        # F10: Use sys.stdout.write() instead of print()
        sys.stdout.write(f"{line}\n")
    return 0


def _parser() -> argparse.ArgumentParser:
    """R9: --min-tier takes tier NAMES, and Tier.UNRELATED must not be reachable."""
    parser = argparse.ArgumentParser(description="Query one member's source CFG.")
    parser.add_argument("query", choices=_QUERIES)
    parser.add_argument("subject", help="a field name, or a node id for `guards`")
    parser.add_argument("--cfg", required=True, type=Path)
    parser.add_argument(
        "--min-tier",
        choices=[t.name for t in Tier if t is not Tier.UNRELATED],
        default=Tier.SAME_PARAGRAPH.name,
    )
    parser.add_argument("--max-depth", type=int, default=MAX_DEPTH)
    return parser


def _lines(cfg: Cfg, arguments) -> tuple[str, ...]:
    if arguments.query == "guards":
        return guards_report(cfg, arguments.subject)
    if arguments.query == "derivation":
        return derivation_report(cfg, arguments.subject, max_depth=arguments.max_depth)
    if arguments.query == "coassign":
        return coassign_report(
            cfg, arguments.subject, min_tier=Tier[arguments.min_tier]
        )
    return writers_report(cfg, arguments.subject)
