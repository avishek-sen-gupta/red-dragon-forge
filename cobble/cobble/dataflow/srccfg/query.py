"""Three queries over one member's CFG, printed for a person.

Names go to stdout and nowhere else: they are corpus identifiers, and the pattern the
copybook diagnostic settled on is that the machine channel carries the answer while
the log stays safe to tail.

``provenance`` is the field query and the other two answer around it: ``guards`` takes
a node id rather than a field, and ``coassign`` asks which OTHER fields move with this
one. What ``provenance`` reports is one field's two directions in the same walk --
what its value is derived from, and where that value goes on to -- because a review
that has only the backward half cannot tell whether a field being wrong matters.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from cobble.dataflow.srccfg.build_corpus import load_cfgs
from cobble.dataflow.srccfg.cfg import Cfg, Node, NodeKind
from cobble.dataflow.srccfg.coassign import Tier, caveats, co_assigned
from cobble.dataflow.srccfg.dataflow import (
    MAX_PATHS,
    Reaching,
    condition_operands,
    guard_text,
    guards_of,
    reaching_conditions,
    readers_of,
    writers_of,
)
from cobble.dataflow.srccfg.literals import is_literal
from cobble.dataflow.srccfg.synthetic import describe, is_synthetic

MAX_DEPTH = 6
UNCONDITIONAL = "unconditional"

CAP_NOTE = "(guard cap hit: this list is incomplete)"
SUBSET_NOTE = "(subset: paths upstream were also truncated)"
RESUMED_NOTE = "(resumed past a PERFORM whose return the walk never reached)"

BACKWARD_HEADING = "backward -- what its value is derived from:"
FORWARD_HEADING = "forward -- what its value reaches:"


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


def _guard_lines(cfg: Cfg, reaching: Reaching, node_id: str) -> GuardLines:
    """Render the guards of a node, distinguishing dead code from abandoned walks.

    Per Reaching's contract (R7): no-guards splits three ways. A node in `abandoned`
    has no guards because the walk gave up, not because the program cannot reach it.
    Only zero guards AND not in abandoned may be reported as unreachable.

    The cap note rides along, on ``overflowed`` and not on ``truncated`` (R77):
    ``truncated`` is ``overflowed`` closed forward, so on branch-heavy code it holds
    nearly every node and a note on every line is a note nobody reads. ``overflowed``
    is the set that says the cap, rather than the program, rationed the answer.

    ``resumed`` earns its own note because it is the one caveat that points the other
    way. Every other note here says the list may be short; this one says this node's
    guard is present only because the walk assumed a PERFORM came back, which is right
    for a paragraph that returns and a guess for one that never does."""
    return GuardLines(
        texts=_guard_texts(cfg, reaching, node_id),
        notes=(
            *((CAP_NOTE,) if node_id in reaching.overflowed else ()),
            *((RESUMED_NOTE,) if node_id in reaching.resumed else ()),
        ),
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


def guards_report(cfg: Cfg, node_id: str, max_paths: int = MAX_PATHS) -> tuple[str, ...]:
    reaching = reaching_conditions(cfg, max_paths=max_paths)
    guards = _guard_lines(cfg, reaching, node_id)
    truncated_note = (f"  {SUBSET_NOTE}",) if node_id in reaching.truncated else ()
    return (
        f"{node_id}: {len(guards_of(reaching, node_id))} path(s)",
        *tuple(f"  path {n}: {text}" for n, text in enumerate(guards.texts)),
        *tuple(f"  {note}" for note in guards.notes),
        *truncated_note,
    )


def provenance_report(
    cfg: Cfg, field: str, max_depth: int = MAX_DEPTH
) -> tuple[str, ...]:
    """One field's two directions, walked from the same reaching conditions.

    Both halves are guarded, and that is the point of pairing them: a field derived
    under one condition and consumed under an incompatible one is not the flow the
    two halves separately appear to describe. Reading them from one ``Reaching`` is
    what lets a reader compare the guard text on a backward line against a forward
    one, rather than against a second walk's numbering.
    """
    reaching = reaching_conditions(cfg)
    return (
        f"{field} in {cfg.program}:",
        BACKWARD_HEADING,
        *_chain(cfg, reaching, field, 1, max_depth, frozenset()),
        FORWARD_HEADING,
        *_uses(cfg, reaching, field, 1, max_depth, frozenset()),
    )


def _halt(
    field: str, depth: int, max_depth: int, seen: frozenset[str], arrow: str
) -> str:
    """The line that ends the walk at this field, or "" to keep walking.

    Three ways a chase stops before it reaches a node, in this order because a field
    already shown is not also a depth truncation, and a name this pass invented (F5)
    has no writers to look for -- it is not a field the member failed to write. Both
    directions read their wordings from here so the arrow is the only difference
    between them; the guards themselves are the same guards either way round.
    """
    pad = "  " * depth
    synthetic = is_synthetic(field)
    reasons = (
        (field in seen, f"{pad}{field} (already shown)"),
        (depth > max_depth, f"{pad}{field} (truncated at depth {max_depth})"),
        (
            bool(synthetic),
            f"{pad}{field} {arrow} {describe(synthetic) if synthetic else ''}",
        ),
    )
    return next((line for applies, line in reasons if applies), "")


def _chain(
    cfg: Cfg,
    reaching: Reaching,
    field: str,
    depth: int,
    max_depth: int,
    seen: frozenset[str],
) -> tuple[str, ...]:
    pad = "  " * depth
    halt = _halt(field, depth, max_depth, seen, "<-")
    if halt:
        return (halt,)
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
    head = f"{pad}{node_id} {_verb(node)} when {'; '.join(guards.texts)}"
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


def _uses(
    cfg: Cfg,
    reaching: Reaching,
    field: str,
    depth: int,
    max_depth: int,
    seen: frozenset[str],
) -> tuple[str, ...]:
    """The forward half: every reader of the field, then what those readers write.

    Symmetric to ``_chain`` in every control it needs -- the same cycle cut, the same
    depth cap, the same synthetic label -- because the shapes that make a backward
    chase diverge are the same shapes forward. ``COMPUTE WS-A = WS-A + 1`` reads and
    writes one field, and ``seen`` is what stops it either way round -- see ``_halt``,
    which both directions share.
    """
    pad = "  " * depth
    halt = _halt(field, depth, max_depth, seen, "->")
    if halt:
        return (halt,)
    nodes = readers_of(cfg, field)
    if not nodes:
        return (f"{pad}{field} -> sink (read nowhere in this member)",)
    return (
        f"{pad}{field} ->",
        *tuple(
            line
            for node_id in nodes
            for line in _into_node(
                cfg, reaching, node_id, field, depth, max_depth, seen | {field}
            )
        ),
    )


def _into_node(
    cfg: Cfg,
    reaching: Reaching,
    node_id: str,
    field: str,
    depth: int,
    max_depth: int,
    seen: frozenset[str],
) -> tuple[str, ...]:
    """Chase the flow onward through one reader.

    A value that reached a node leaves it one of two ways: written on into the node's
    targets, or -- at a TEST -- spent deciding which arm runs, with no target field to
    follow. Both are places the value matters, so a reader with no writes is a terminus
    that says which of the two it is rather than a line the report omits.
    """
    node = cfg.node(node_id)
    pad = "  " * depth
    guards = _guard_lines(cfg, reaching, node_id)
    head = f"{pad}{node_id} {_verb(node)} when {'; '.join(guards.texts)}"
    notes = tuple(f"{pad}  {note}" for note in guards.notes)

    if not node.writes:
        return (head, *notes, f"{pad}  {field} -> {_sink(node)}")

    return (
        head,
        *notes,
        *tuple(
            line
            for name in node.writes
            for line in _uses(cfg, reaching, name, depth + 1, max_depth, seen)
        ),
    )


def _verb(node: Node) -> str:
    """The verb that moved the data, or the node's kind where there is no verb.

    The forward walk reaches TEST nodes, which the backward one never does -- a TEST
    writes nothing, so ``writers_of`` cannot return it. Printing those as ASSIGN would
    say a predicate assigned something.
    """
    return node.transfer or node.kind.value


def _sink(node: Node) -> str:
    """Why the forward chain stopped at this reader.

    Two terminal states, two wordings, for the same reason ``_terminus`` has two: a
    TEST consuming the value is not the same finding as a statement that reads it and
    writes nothing, and one wording for both would make the reader check the source to
    tell which they were looking at.
    """
    if node.kind is NodeKind.TEST:
        return "decides this branch (no target field)"
    return "read here, written on to nothing"


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
    and atom.right, not in node.reads -- ``condition_operands`` is the same rule
    ``readers_of`` applies, so a field reported here as a control dependency is one
    the forward walk will also find reaching this test."""
    all_operands = (
        operand
        for guard in guards_of(reaching, node_id)
        for step_id, _kind in guard
        for operand in condition_operands(cfg.node(step_id).atom)
        if operand and not is_literal(operand)
    )
    # Remove duplicates while preserving order
    return list(dict.fromkeys(all_operands))


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


_QUERIES = ("provenance", "guards", "coassign")


def main(argv: Sequence[str] = ()) -> int:
    """No arguments means take the command line, which is what the console script does.

    argparse spells that as ``parse_args()`` against ``parse_args(argv)``, so the two
    are separate calls: passing an empty sequence through would ask it to parse nothing
    and fail on the required arguments.
    """
    parser = _parser()
    if argv:
        return _run(parser.parse_args(tuple(argv)))
    return _run(parser.parse_args())


def _run(arguments: argparse.Namespace) -> int:
    if not arguments.cfg.is_file():
        # F10: Use sys.stderr.write() instead of print() to avoid RUF100
        sys.stderr.write(f"No CFG at {arguments.cfg}\n")
        return 2
    for line in _all_lines(load_cfgs(arguments.cfg), arguments):
        # F10: Use sys.stdout.write() instead of print()
        sys.stdout.write(f"{line}\n")
    return 0


def _all_lines(cfgs: Sequence[Cfg], arguments) -> tuple[str, ...]:
    """Every program in the file, reported on in turn.

    A file may hold one program or a whole call closure, and a query that read only
    the first would answer about the seed while looking like it had searched all of
    them. No heading is added: each report already names its own program, so the
    single-program case reads exactly as it did before.
    """
    return tuple(line for cfg in cfgs for line in _lines(cfg, arguments))


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
    parser.add_argument(
        "--max-depth",
        type=int,
        default=MAX_DEPTH,
        help="how far `provenance` chases each direction",
    )
    parser.add_argument(
        "--max-paths",
        type=int,
        default=MAX_PATHS,
        help="path cap for reaching conditions (default: %(default)s)",
    )
    return parser


def _lines(cfg: Cfg, arguments) -> tuple[str, ...]:
    if arguments.query == "guards":
        return guards_report(cfg, arguments.subject, max_paths=arguments.max_paths)
    if arguments.query == "coassign":
        return coassign_report(
            cfg, arguments.subject, min_tier=Tier[arguments.min_tier]
        )
    return provenance_report(cfg, arguments.subject, max_depth=arguments.max_depth)
