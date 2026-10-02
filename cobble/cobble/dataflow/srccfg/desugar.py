"""One ASG statement to one Fragment.

What a statement MOVES is not decided here. ``depgraph.flows`` already holds the
verb table -- 30-odd statement kinds, the CICS verbs, the FD-to-record pairing --
and a second copy of it would drift from the first. This module asks flows what
the blocks are and turns them into nodes.

One gap has to be filled locally: flows has no INITIALIZE rule, because a
source-to-target edge needs a source. A definition with no source still kills the
definition before it, so reaching definitions needs the node even though the
dependency graph does not.

Identity is a path, because no ASG statement carries a line number. ``MAIN/3`` is
the fourth statement of MAIN; ``MAIN/3.else.1`` the second statement of its ELSE
arm. Suffixes distinguish the several nodes one statement can lower to:
``#test.0``, ``#join``, ``#end``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import reduce
from itertools import accumulate, pairwise, repeat, takewhile
from types import MappingProxyType

from cics.statements import CicsOperand
from cobble.dataflow.depgraph.flows import (
    ProgramContext,
    blocks_of,
    operand_names,
    verb_of,
)
from cobble.dataflow.srccfg.cfg import (
    EMPTY_FRAGMENT,
    NO_TARGET_OPERAND,
    Atom,
    Edge,
    EdgeKind,
    Exit,
    Fragment,
    Node,
    NodeKind,
    SourceSpan,
    seq,
)
from cobble.dataflow.srccfg.conditions import (
    ALWAYS,
    And,
    Cond,
    EightyEight,
    Not,
    Or,
    read_condition,
    read_when_condition,
    resolve_atom,
)
from cobble.dataflow.srccfg.synthetic import (
    HANDLER_ANY,
    IGNORED,
    RAISED,
    SYSTEM_DEFAULT,
    handler_field,
    io_status_field,
)
from cobble.dataflow.srccfg.varying import spec_text
from cobble.dataflow.srccfg.whenever import SQLCA_CONDITIONS, Governing
from cobol_asg.cobol_expression import expr_to_dict
from cobol_asg.ref_mod import RefModOperand
from squall.statements import Kind

GOTO_TRANSFER = "GO TO"
SQL_TRANSFER = "EXECSQL"
DISPATCH_TRANSFER = "GO TO DEPENDING"
PERFORM_TRANSFER = "PERFORM"
RANGE_SEPARATOR = "|"
TIMES_OP = "TIMES"

ARM_CLAUSES = (
    ("at_end", "not_at_end", "AT END"),
    ("invalid_key", "not_invalid_key", "INVALID KEY"),
    ("on_size_error", "not_on_size_error", "ON SIZE ERROR"),
)

ARMING_VERBS = ("HANDLE CONDITION", "IGNORE CONDITION", "HANDLE AID")
SUPPRESSING_OPTIONS = ("NOHANDLE", "RESP", "RESP2")
LEAVING_VERBS = ("XCTL", "RETURN")
ABENDING_VERB = "ABEND"
DISPATCH_TRANSFER_CICS = "HANDLE DISPATCH"

LINK_TRANSFER = "LINK"
XCTL_TRANSFER = "XCTL"
CALL_TRANSFER = "CALL"
CALL_TRANSFERS = {
    "CICS_LINK": LINK_TRANSFER,
    "CICS_XCTL": XCTL_TRANSFER,
    CALL_TRANSFER: CALL_TRANSFER,
}
NO_OPERAND = CicsOperand(text="", is_literal=False)
PROGRAM_OPTION = "PROGRAM"
COMMAREA_OPTION = "COMMAREA"

WRITES_ONLY_KINDS = ("InitializeStatement",)
# A verb whose sink is outside the program still reads its operands.
READS_ONLY_KINDS = ("DisplayStatement",)
# A verb whose source is outside the program still writes its target.
EXTERNAL_SOURCE_WRITES = ("AcceptStatement",)

# Kinds this module knows touch data items, and reads locally rather than through
# flows. A statement in this set is always ASSIGN even when extraction yields
# nothing: an ASSIGN with empty writes and reads is a parse gap made visible, not a
# no-op.
_GAP_FILL_KINDS = WRITES_ONLY_KINDS + READS_ONLY_KINDS + EXTERNAL_SOURCE_WRITES


@dataclass(frozen=True)
class Ctx:
    """What lowering needs about the program and the paragraph being lowered."""

    program: str
    paragraph: str
    flows: ProgramContext
    index: Mapping[str, EightyEight]
    source_file: str = ""
    # Which WHENEVER GO TOs govern each EXEC SQL node id. Computed once per
    # program in source order, because the directive is a precompiler one --
    # see srccfg/whenever.py.
    whenever: Mapping[str, Governing] = MappingProxyType({})


@dataclass(frozen=True)
class CondFragment:
    """A lowered condition: the tests, and the two sets of exits it leaves.

    A chain of ANDed atoms leaves one true exit and one false exit per atom; a
    chain of ORed atoms leaves the mirror image. NOT is applied by swapping the
    two sets, which is why no node is emitted for it and why the negation of a
    chain comes out as a set of paths rather than a formula.
    """

    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    entry: str
    true_exits: tuple[Exit, ...]
    false_exits: tuple[Exit, ...]


def node_id(ctx: Ctx, path: str, suffix: str = "") -> str:
    return f"{ctx.paragraph}/{path}{suffix}"


def lower_statements(statements: Sequence, ctx: Ctx, path: str) -> Fragment:
    prefix = f"{path}." if path else ""
    return seq(
        tuple(
            lower_statement(statement, ctx, f"{prefix}{position}")
            for position, statement in enumerate(statements)
        ),
        nop_id=node_id(ctx, f"{prefix}empty"),
    )


def lower_statement(statement, ctx: Ctx, path: str) -> Fragment:
    handler = _HANDLERS.get(type(statement).__name__)
    return handler(statement, ctx, path) if handler else _plain(statement, ctx, path)


def _span(statement, ctx: Ctx) -> SourceSpan:
    """Source location from the ASG statement's own ``span`` attribute."""
    match getattr(statement, "span", None):
        case None:
            return SourceSpan()
        case s:
            return SourceSpan(
                line_start=int(getattr(s, "line_start", 0) or 0),
                col_start=int(getattr(s, "col_start", 0) or 0),
                line_end=int(getattr(s, "line_end", 0) or 0),
                col_end=int(getattr(s, "col_end", 0) or 0),
                source_file=ctx.source_file,
            )


def _plain(statement, ctx: Ctx, path: str) -> Fragment:
    kind = type(statement).__name__
    writes, reads = _writes_reads(statement, ctx, kind)
    node = Node(
        id=node_id(ctx, path),
        kind=(
            NodeKind.ASSIGN
            if kind in _GAP_FILL_KINDS or writes or reads
            else NodeKind.NOP
        ),
        paragraph=ctx.paragraph,
        writes=writes,
        reads=reads,
        transfer=verb_of(statement) or _fallback_verb(kind),
        span=_span(statement, ctx),
    )
    return _with_arms(statement, ctx, path, _one(node))


def _writes_reads(statement, ctx: Ctx, kind: str) -> tuple[tuple[str, ...], ...]:
    if kind in _GAP_FILL_KINDS:
        return _local_roles(statement, kind)
    return _flow_roles(statement, ctx)


def _local_roles(statement, kind: str) -> tuple[tuple[str, ...], ...]:
    """The kinds flows has no rule for. What they touch is their own operand list --
    or, where the source is outside the program, their target -- rather than the
    source-to-target pairs every other verb is read as."""
    if kind in EXTERNAL_SOURCE_WRITES:
        return (_written_target(statement), ())
    names = operand_names(getattr(statement, "operands", ()))
    if kind in WRITES_ONLY_KINDS:
        return (names, ())
    return ((), names)


def _written_target(statement) -> tuple[str, ...]:
    target = getattr(statement, "target", "")
    return (target,) if target else ()


def _flow_roles(statement, ctx: Ctx) -> tuple[tuple[str, ...], ...]:
    blocks = blocks_of(statement, ctx.flows)
    return (
        _dedupe(target for _, targets in blocks for target in targets),
        _dedupe(source for sources, _ in blocks for source in sources),
    )


def _dedupe(names) -> tuple[str, ...]:
    return tuple(dict.fromkeys(name for name in names if name))


def _fallback_verb(kind: str) -> str:
    """A kind flows has no label for still shows something a reader recognises:
    ``DisplayStatement`` reads as DISPLAY."""
    return kind.removesuffix("Statement").upper()


def _one(node: Node) -> Fragment:
    return Fragment(
        nodes=(node,),
        edges=(),
        entry=node.id,
        exits=(Exit(node_id=node.id, kind=EdgeKind.FLOW),),
    )


def _terminator(statement, ctx: Ctx, path: str) -> Fragment:
    """STOP RUN, GOBACK, EXIT PROGRAM: the same node as any other, minus its exit.

    Dropping the exit is the whole model, because two things downstream are already
    driven by exits. ``seq`` gives each exit the next statement's entry, so a
    terminator leaves the rest of its paragraph with no route in; and ``build.py``
    gives a paragraph's exits its ``#end``, so a paragraph ending in one leaves that
    ``#end`` unreachable -- which severs the fall-through to the NEXT paragraph and
    the RETURN edge hanging off that same end together. Without this, control
    cascades off the entry paragraph's end through every later paragraph in
    declaration order, and no paragraph in a real member can be found dead.

    All three verbs alike. GOBACK and EXIT PROGRAM in a subprogram return to
    whatever CALLed the program, never to the PERFORM that reached the paragraph, so
    a PERFORM of a paragraph ending in one does not come back either.

    Plain EXIT is deliberately NOT here. It is the no-op sentinel conventionally
    written at the end of a PERFORM THRU range and it falls through like anything
    else; treating it as a terminator would cut most of a program in half.
    """
    return replace(_plain(statement, ctx, path), exits=())


def _with_arms(statement, ctx: Ctx, path: str, body: Fragment) -> Fragment:
    present = _present_arms(statement)
    if not present:
        return body
    return _chain_arms(statement, ctx, path, body, present, 0)


def _present_arms(statement) -> tuple:
    return tuple(
        clause
        for clause in ARM_CLAUSES
        if getattr(statement, clause[0], ()) or getattr(statement, clause[1], ())
    )


def _chain_arms(
    statement, ctx: Ctx, path: str, body: Fragment, present, pos: int
) -> Fragment:
    if pos >= len(present):
        return body
    true_attr, false_attr, label = present[pos]
    suffix = "#arm" if pos == 0 else f"#arm.{true_attr}"
    join_suffix = "#arm.join" if pos == 0 else f"#arm.{true_attr}.join"
    cond = _arm_test(statement, ctx, path, label, suffix)
    arms = _wire_arms(
        cond,
        lower_statements(getattr(statement, true_attr, ()), ctx, f"{path}.{true_attr}"),
        lower_statements(
            getattr(statement, false_attr, ()), ctx, f"{path}.{false_attr}"
        ),
    )
    wrapped = seq((body, arms), nop_id=node_id(ctx, path, join_suffix))
    return _chain_arms(statement, ctx, path, wrapped, present, pos + 1)


def _arm_test(
    statement, ctx: Ctx, path: str, label: str, suffix: str = "#arm"
) -> CondFragment:
    subject = _arm_subject(statement)
    resolved = bool(subject)
    node = Node(
        id=node_id(ctx, path, suffix),
        kind=NodeKind.TEST,
        paragraph=ctx.paragraph,
        atom=Atom(
            text=f"{label} {subject}",
            left=io_status_field(subject),
            op="==",
            right=label,
            resolved=resolved,
        ),
    )
    return _exits_of(node)


def _arm_subject(statement) -> str:
    """A file when there is one, otherwise the first target -- a size error is about
    the arithmetic, not about a file."""
    named = str(getattr(statement, "file_name", "") or "").upper()
    if named:
        return named
    targets = operand_names(
        (
            *getattr(statement, "targets", ()),
            *getattr(statement, "giving", ()),
            getattr(statement, "target", ""),
        )
    )
    return (
        targets[0]
        if targets
        else str(getattr(statement, "record_name", "") or "").upper()
    )


def _plain_without_arms(statement, ctx: Ctx, path: str) -> Fragment:
    kind = type(statement).__name__
    writes, reads = _writes_reads(statement, ctx, kind)
    return _one(
        Node(
            id=node_id(ctx, path),
            kind=(
                NodeKind.ASSIGN
                if kind in _GAP_FILL_KINDS or writes or reads
                else NodeKind.NOP
            ),
            paragraph=ctx.paragraph,
            writes=writes,
            reads=reads,
            transfer=verb_of(statement) or _fallback_verb(kind),
            span=_span(statement, ctx),
        )
    )


def lower_condition(cond, ctx: Ctx, path: str, slot: str = "") -> CondFragment:
    compound = _COMPOUNDS.get(type(cond))
    return compound(cond, ctx, path, slot) if compound else _test(cond, ctx, path, slot)


def _negated(cond, ctx: Ctx, path: str, slot: str) -> CondFragment:
    return _swap(lower_condition(cond.inner, ctx, path, slot))


def _chained(cond, ctx: Ctx, path: str, slot: str) -> CondFragment:
    """An AND/OR chain, lowered down its left side and joined back up.

    Each combination's left child takes its slot plus ``L`` and its right child
    plus ``R``, so the link ``depth`` levels down has slot ``slot + "L" * depth``.
    Walking the left side rather than recursing keeps a long ``A OR B OR ...``,
    which the bridge nests on the left, from costing a stack frame per operand.
    """
    spine = _left_spine(cond)
    innermost = lower_condition(spine[-1].left, ctx, path, slot + "L" * len(spine))

    def linked(left: CondFragment, numbered) -> CondFragment:
        depth, link = numbered
        right = lower_condition(link.right, ctx, path, f"{slot}{'L' * depth}R")
        return _joined(left, right, _THROUGH[type(link)])

    return reduce(linked, reversed(tuple(enumerate(spine))), innermost)


def _left_spine(cond) -> tuple:
    """The AND/OR links down the left side, outermost first."""
    lefts = accumulate(repeat(None), lambda link, _: link.left, initial=cond)
    return tuple(takewhile(lambda link: type(link) in _THROUGH, lefts))


def _test(atom, ctx: Ctx, path: str, slot: str) -> CondFragment:
    suffix = f"#test.{slot}" if slot else "#test"
    node = Node(
        id=node_id(ctx, path, suffix),
        kind=NodeKind.TEST,
        paragraph=ctx.paragraph,
        atom=resolve_atom(atom, ctx.index),
    )
    return _exits_of(node)


def _swap(inner: CondFragment) -> CondFragment:
    return CondFragment(
        nodes=inner.nodes,
        edges=inner.edges,
        entry=inner.entry,
        true_exits=inner.false_exits,
        false_exits=inner.true_exits,
    )


def _joined(left: CondFragment, right: CondFragment, through: EdgeKind) -> CondFragment:
    """Short-circuit: the right side is only reached along ``through`` from the
    left, and the other side's exits from BOTH halves escape the chain."""
    taken = left.true_exits if through is EdgeKind.TRUE else left.false_exits
    kept = left.false_exits if through is EdgeKind.TRUE else left.true_exits
    joined = CondFragment(
        nodes=(*left.nodes, *right.nodes),
        edges=(
            *left.edges,
            *right.edges,
            *(
                Edge(source=exit_.node_id, target=right.entry, kind=exit_.kind)
                for exit_ in taken
            ),
        ),
        entry=left.entry,
        true_exits=right.true_exits,
        false_exits=(*kept, *right.false_exits),
    )
    return joined if through is EdgeKind.TRUE else _or_exits(joined, kept, right)


def _or_exits(
    joined: CondFragment, kept: tuple[Exit, ...], right: CondFragment
) -> CondFragment:
    return CondFragment(
        nodes=joined.nodes,
        edges=joined.edges,
        entry=joined.entry,
        true_exits=(*kept, *right.true_exits),
        false_exits=right.false_exits,
    )


def as_fragment(cond: CondFragment) -> Fragment:
    return Fragment(
        nodes=cond.nodes,
        edges=cond.edges,
        entry=cond.entry,
        exits=(*cond.true_exits, *cond.false_exits),
    )


def _if(statement, ctx: Ctx, path: str) -> Fragment:
    cond = lower_condition(read_condition(_raw_condition(statement)), ctx, path)
    then_arm = lower_statements(getattr(statement, "children", ()), ctx, f"{path}.then")
    else_arm = lower_statements(
        getattr(statement, "else_children", ()), ctx, f"{path}.else"
    )
    return _wire_arms(cond, then_arm, else_arm)


def _wire_arms(cond: CondFragment, then_arm: Fragment, else_arm: Fragment) -> Fragment:
    """An empty arm leaves the guard's own exit dangling, which is right: the
    statement after END-IF is what that edge goes to."""
    into_then = _attach(cond.true_exits, then_arm)
    into_else = _attach(cond.false_exits, else_arm)
    return Fragment(
        nodes=(*cond.nodes, *then_arm.nodes, *else_arm.nodes),
        edges=(*cond.edges, *then_arm.edges, *else_arm.edges, *into_then, *into_else),
        entry=cond.entry,
        exits=(
            *(then_arm.exits if then_arm.nodes else cond.true_exits),
            *(else_arm.exits if else_arm.nodes else cond.false_exits),
        ),
    )


def _attach(exits: tuple[Exit, ...], arm: Fragment) -> tuple[Edge, ...]:
    if not arm.nodes:
        return ()
    return tuple(
        Edge(source=exit_.node_id, target=arm.entry, kind=exit_.kind) for exit_ in exits
    )


def _raw_condition(statement) -> Mapping:
    """The ASG hands conditions back as the same dicts it was built from, and the
    statement dataclasses keep them under ``condition``.

    Unparameterised, because the values are what nesting the reader walks: a
    sub-condition mapping, an operand mapping, a name, a flag. ``read_condition``
    owns that descent and is where the shapes are named."""
    raw = getattr(statement, "condition", {}) or {}
    return raw


def _evaluate(statement, ctx: Ctx, path: str) -> Fragment:
    """A guard chain. Each branch is tried only when every earlier one failed, so
    branch N is reached along branch N-1's FALSE edges -- the same chaining OR
    uses, which is why the negation of the branches above is already on the path.
    """
    subjects = (
        str(getattr(statement, "subject", "") or ""),
        *getattr(statement, "also_subjects", ()),
    )
    branches = tuple(
        _branch(child, subjects, ctx, f"{path}.when.{position}")
        for position, child in enumerate(getattr(statement, "children", ()))
    )
    return _chain_branches(tuple(b for b in branches if b.nodes))


@dataclass(frozen=True)
class _Branch:
    """One WHEN: its guard chain (possibly none, for WHEN OTHER) and its body."""

    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    entry: str
    body_exits: tuple[Exit, ...]
    false_exits: tuple[Exit, ...]


def _branch(child, subjects: tuple[str, ...], ctx: Ctx, path: str) -> _Branch:
    body = lower_statements(getattr(child, "children", ()), ctx, path)
    if type(child).__name__ == "WhenOtherStatement":
        return _Branch(
            nodes=body.nodes,
            edges=body.edges,
            entry=body.entry,
            body_exits=body.exits,
            false_exits=(),
        )
    return _guarded_branch(child, subjects, ctx, path, body)


def _guarded_branch(
    child, subjects: tuple[str, ...], ctx: Ctx, path: str, body: Fragment
) -> _Branch:
    cond = _when_condition(child, subjects, ctx, path)
    into_body = _attach(cond.true_exits, body)
    return _Branch(
        nodes=(*cond.nodes, *body.nodes),
        edges=(*cond.edges, *body.edges, *into_body),
        entry=cond.entry,
        body_exits=body.exits if body.nodes else cond.true_exits,
        false_exits=cond.false_exits,
    )


def _when_condition(
    child, subjects: tuple[str, ...], ctx: Ctx, path: str
) -> CondFragment:
    """WHEN a ALSO b is a conjunction, so the ALSO conditions chain on TRUE. Each
    value answers the subject in the same ALSO position; a value with no subject
    to answer is read as a condition of its own."""
    thru = str(getattr(child, "condition_thru", "") or "")
    also_values = tuple(getattr(child, "also_conditions", ()))
    also_subjects = (*subjects[1:], *("",) * len(also_values))
    parts = (
        read_when_condition(getattr(child, "condition", ""), subjects[0], thru),
        *(
            read_when_condition(value, subject)
            for value, subject in zip(
                also_values, also_subjects[: len(also_values)], strict=True
            )
        ),
    )
    slotted = tuple(zip(_ALSO_SLOTS[: len(parts)], parts, strict=True))
    return _and_chain(_tested(slotted), ctx, path, 0)


def _tested(slotted: tuple[tuple[str, Cond], ...]) -> tuple[tuple[str, Cond], ...]:
    """The parts that test anything. ANY matches whatever its subject holds, so
    beside a real comparison it would only add a FALSE edge that never fires; a
    WHEN of nothing but ANY keeps one, so the branch still has a node."""
    tested = tuple(part for part in slotted if part[1] != ALWAYS)
    return tested if tested else slotted[:1]


def _and_chain(
    parts: tuple[tuple[str, Cond], ...], ctx: Ctx, path: str, position: int
) -> CondFragment:
    slot, cond = parts[position]
    head = lower_condition(cond, ctx, path, slot)
    if position + 1 >= len(parts):
        return head
    tail = _and_chain(parts, ctx, path, position + 1)
    return CondFragment(
        nodes=(*head.nodes, *tail.nodes),
        edges=(
            *head.edges,
            *tail.edges,
            *(
                Edge(source=e.node_id, target=tail.entry, kind=e.kind)
                for e in head.true_exits
            ),
        ),
        entry=head.entry,
        true_exits=tail.true_exits,
        false_exits=(*head.false_exits, *tail.false_exits),
    )


_ALSO_SLOTS = ("", "A1", "A2", "A3", "A4", "A5", "A6", "A7")


def _chain_branches(branches: tuple[_Branch, ...]) -> Fragment:
    if not branches:
        return EMPTY_FRAGMENT
    return Fragment(
        nodes=tuple(node for b in branches for node in b.nodes),
        edges=(
            *(edge for b in branches for edge in b.edges),
            *_between(branches),
        ),
        entry=branches[0].entry,
        exits=(
            *(e for b in branches for e in b.body_exits),
            *branches[-1].false_exits,
        ),
    )


def _between(branches: tuple[_Branch, ...]) -> tuple[Edge, ...]:
    return tuple(
        Edge(source=exit_.node_id, target=nxt.entry, kind=exit_.kind)
        for current, nxt in pairwise(branches)
        for exit_ in current.false_exits
    )


def _search(statement, ctx: Ctx, path: str) -> Fragment:
    """The whens chain like EVALUATE's branches, and AT END is the last FALSE arm.

    A WHEN's condition arrives structured or as text, depending on the cache, and
    _search_condition reads whichever it is. Only the text form stays UNRESOLVED:
    the fork is real and the node exists, but inventing parts from the text would
    be a guess no report could qualify.
    """
    head = _plain_without_arms(statement, ctx, path)
    whens = getattr(statement, "whens", ())
    at_end = lower_statements(getattr(statement, "at_end", ()), ctx, f"{path}.at_end")
    tail = _search_tail(whens, at_end, ctx, path)
    return seq((head, tail), nop_id=node_id(ctx, path, "#search"))


def _search_tail(whens, at_end: Fragment, ctx: Ctx, path: str) -> Fragment:
    if not whens and at_end.nodes:
        return _search_missing_when(at_end, ctx, path)
    branches = tuple(
        _search_branch(when, ctx, f"{path}.when.{position}")
        for position, when in enumerate(whens)
    )
    return _chain_branches((*branches, *_as_branch(at_end)))


def _search_branch(when, ctx: Ctx, path: str) -> _Branch:
    body = lower_statements(getattr(when, "children", ()), ctx, path)
    cond = _search_condition(when, ctx, path)
    return _Branch(
        nodes=(*cond.nodes, *body.nodes),
        edges=(*cond.edges, *body.edges, *_attach(cond.true_exits, body)),
        entry=cond.entry,
        body_exits=body.exits if body.nodes else cond.true_exits,
        false_exits=cond.false_exits,
    )


def _search_condition(when, ctx: Ctx, path: str) -> CondFragment:
    """A WHEN's condition, decomposed wherever the cache holds its parts.

    Some caches give the condition as text with the subject already folded in, and
    there is nothing to take apart; that form still yields one UNRESOLVED test,
    because the fork is real either way. Where the parts are present, reading them
    is what puts the fields the guard depends on into a dependency report -- and
    what keeps a Python dict repr out of the predicate a person reads.
    """
    raw = getattr(when, "condition", "")
    if isinstance(raw, str):
        return _exits_of(_opaque_test(ctx, path, raw))
    return lower_condition(read_condition(raw), ctx, path)


def _opaque_test(ctx: Ctx, path: str, text: str) -> Node:
    return Node(
        id=node_id(ctx, path, "#test"),
        kind=NodeKind.TEST,
        paragraph=ctx.paragraph,
        atom=Atom(text=text, resolved=False),
    )


def _search_missing_when(at_end: Fragment, ctx: Ctx, path: str) -> Fragment:
    """When WHENs are missing but AT END is present, emit an unresolved test.

    The search outcome is unknown, so the test is unresolved. AT END is on the
    FALSE edge, and the TRUE edge falls through to the next statement.
    """
    node = Node(
        id=node_id(ctx, path, "#test"),
        kind=NodeKind.TEST,
        paragraph=ctx.paragraph,
        atom=Atom(text="SEARCH outcome unknown", resolved=False),
    )
    cond = _exits_of(node)
    return Fragment(
        nodes=(node, *at_end.nodes),
        edges=(*at_end.edges, *_attach(cond.false_exits, at_end)),
        entry=node.id,
        exits=(*cond.true_exits, *at_end.exits),
    )


def _as_branch(arm: Fragment) -> tuple[_Branch, ...]:
    if not arm.nodes:
        return ()
    return (
        _Branch(
            nodes=arm.nodes,
            edges=arm.edges,
            entry=arm.entry,
            body_exits=arm.exits,
            false_exits=(),
        ),
    )


def _goto(statement, ctx: Ctx, path: str) -> Fragment:
    form = getattr(statement, "form", "")
    targets = getattr(form, "targets", ())
    if targets:
        return _computed_goto(form, targets, ctx, path)
    return _transfer(ctx, path, "", _target_name(getattr(form, "target", "")))


def _transfer(ctx: Ctx, path: str, suffix: str, target: str) -> Fragment:
    """A node control leaves from: no exits, and a target build.py resolves."""
    node = Node(
        id=node_id(ctx, path, suffix),
        kind=NodeKind.CALL,
        paragraph=ctx.paragraph,
        transfer=GOTO_TRANSFER,
        target=target,
    )
    return Fragment(nodes=(node,), edges=(), entry=node.id, exits=())


def _computed_goto(form, targets, ctx: Ctx, path: str) -> Fragment:
    """One dispatch node reading the index, one branch node per target.

    The dispatch keeps a FLOW exit: an index outside 1..N is not an error in COBOL,
    control simply continues with the next statement.
    """
    dispatch = Node(
        id=node_id(ctx, path),
        kind=NodeKind.CALL,
        paragraph=ctx.paragraph,
        reads=operand_names((getattr(form, "index", ""),)),
        transfer=DISPATCH_TRANSFER,
    )
    branches = tuple(
        _transfer(ctx, path, f"#goto.{position}", _target_name(ref)).nodes[0]
        for position, ref in enumerate(targets)
    )
    return Fragment(
        nodes=(dispatch, *branches),
        edges=tuple(
            Edge(source=dispatch.id, target=branch.id, kind=EdgeKind.FLOW)
            for branch in branches
        ),
        entry=dispatch.id,
        exits=(Exit(node_id=dispatch.id, kind=EdgeKind.FLOW),),
    )


def _target_name(ref) -> str:
    return str(getattr(ref, "paragraph", "") or "").upper()


def _perform(statement, ctx: Ctx, path: str) -> Fragment:
    """A call, a block, or either of those wrapped in a loop."""
    inner = _perform_body(statement, ctx, path)
    return _loop(getattr(statement, "spec", ""), inner, ctx, path)


def _perform_body(statement, ctx: Ctx, path: str) -> Fragment:
    target = str(getattr(statement, "target", "") or "").upper()
    if not target:
        return lower_statements(getattr(statement, "children", ()), ctx, f"{path}.body")
    return _call(ctx, path, _range_target(target, getattr(statement, "thru", "")))


def _range_target(target: str, thru: str) -> str:
    last = str(thru or "").upper()
    return f"{target}{RANGE_SEPARATOR}{last}" if last else target


def _call(ctx: Ctx, path: str, target: str) -> Fragment:
    node = Node(
        id=node_id(ctx, path),
        kind=NodeKind.CALL,
        paragraph=ctx.paragraph,
        transfer=PERFORM_TRANSFER,
        target=target,
    )
    return Fragment(
        nodes=(node,),
        edges=(),
        entry=node.id,
        exits=(Exit(node_id=node.id, kind=EdgeKind.FLOW),),
    )


def _loop(spec, body: Fragment, ctx: Ctx, path: str) -> Fragment:
    """A spec no form is known for leaves the body unwrapped: an inline PERFORM runs
    its body once."""
    form = _LOOP_FORMS.get(type(spec).__name__)
    return form(spec, body, ctx, path) if form else body


def _times_loop(spec, body: Fragment, ctx: Ctx, path: str) -> Fragment:
    return _tested_loop(_times_test(spec, ctx, path), body, before=True)


def _until_loop(spec, body: Fragment, ctx: Ctx, path: str) -> Fragment:
    return _tested_loop(_until_test(spec, ctx, path), body, before=_before(spec))


def _before(spec) -> bool:
    return bool(getattr(spec, "test_before", True))


def _times_test(spec, ctx: Ctx, path: str) -> CondFragment:
    """The count is a field as often as a literal; when it is a field the loop
    depends on it, so it is a read on the test."""
    times = str(getattr(spec, "times", "") or "").upper()
    node = Node(
        id=node_id(ctx, path, "#loop"),
        kind=NodeKind.TEST,
        paragraph=ctx.paragraph,
        atom=Atom(text=f"{times} TIMES", left=times, op=TIMES_OP),
        reads=_dedupe((times,)),
    )
    return _exits_of(node)


def _until_test(spec, ctx: Ctx, path: str) -> CondFragment:
    return lower_condition(
        read_condition(getattr(spec, "condition", {})), ctx, f"{path}#loop"
    )


def _exits_of(node: Node) -> CondFragment:
    return CondFragment(
        nodes=(node,),
        edges=(),
        entry=node.id,
        true_exits=(Exit(node_id=node.id, kind=EdgeKind.TRUE),),
        false_exits=(Exit(node_id=node.id, kind=EdgeKind.FALSE),),
    )


def _tested_loop(test: CondFragment, body: Fragment, before: bool) -> Fragment:
    """UNTIL and TIMES both leave the loop on TRUE and enter the body on FALSE.

    TEST BEFORE makes the body's execution conditional, which is what a query about
    an assignment inside the body must see; TEST AFTER makes the first pass
    unconditional, so the entry is the body.
    """
    back = tuple(
        Edge(source=exit_.node_id, target=test.entry, kind=exit_.kind)
        for exit_ in body.exits
    )
    into_body = _attach(test.false_exits, body)
    return Fragment(
        nodes=(*test.nodes, *body.nodes),
        edges=(*test.edges, *body.edges, *into_body, *back),
        entry=test.entry if before or not body.nodes else body.entry,
        exits=test.true_exits,
    )


def _varying_loop(spec, body: Fragment, ctx: Ctx, path: str) -> Fragment:
    """FROM and BY are assignments to the loop variable, and both are definitions a
    query for its writers has to find.

    AFTER specs are nested loops whose innermost varies fastest, built inside-out.
    """
    inner_body = _nest_after_specs(getattr(spec, "after_specs", ()), body, ctx, path)
    variable = str(getattr(spec, "varying_var", "") or "").upper()
    init = _step_node(
        ctx, path, "#init", variable, (spec_text(getattr(spec, "varying_from", "")),)
    )
    step = _step_node(
        ctx,
        path,
        "#step",
        variable,
        (variable, spec_text(getattr(spec, "varying_by", ""))),
    )
    loop = _tested_loop(
        _until_test(spec, ctx, path),
        _with_step(inner_body, step, ctx, path),
        before=_before(spec),
    )
    return Fragment(
        nodes=(init, *loop.nodes),
        edges=(
            *loop.edges,
            Edge(source=init.id, target=loop.entry, kind=EdgeKind.FLOW),
        ),
        entry=init.id,
        exits=loop.exits,
    )


def _nest_after_specs(
    after_specs: tuple, body: Fragment, ctx: Ctx, path: str
) -> Fragment:
    """Build nested AFTER loops from innermost to outermost."""
    if not after_specs:
        return body
    return _one_after_loop(after_specs, 0, body, ctx, path)


def _one_after_loop(
    specs: tuple, position: int, body: Fragment, ctx: Ctx, path: str
) -> Fragment:
    if position >= len(specs):
        return body
    inner = _one_after_loop(specs, position + 1, body, ctx, path)
    spec = specs[position]
    suffix = f".after.{position}"
    variable = str(getattr(spec, "varying_var", "") or "").upper()
    init = _step_node(
        ctx,
        path,
        f"{suffix}#init",
        variable,
        (spec_text(getattr(spec, "varying_from", "")),),
    )
    step = _step_node(
        ctx,
        path,
        f"{suffix}#step",
        variable,
        (variable, spec_text(getattr(spec, "varying_by", ""))),
    )
    loop = _tested_loop(
        lower_condition(
            read_condition(getattr(spec, "condition", {})), ctx, f"{path}{suffix}#loop"
        ),
        _with_step(inner, step, ctx, f"{path}{suffix}"),
        before=_before(spec),
    )
    return Fragment(
        nodes=(init, *loop.nodes),
        edges=(
            *loop.edges,
            Edge(source=init.id, target=loop.entry, kind=EdgeKind.FLOW),
        ),
        entry=init.id,
        exits=loop.exits,
    )


def _with_step(body: Fragment, step: Node, ctx: Ctx, path: str) -> Fragment:
    stepped = Fragment(
        nodes=(step,),
        edges=(),
        entry=step.id,
        exits=(Exit(node_id=step.id, kind=EdgeKind.FLOW),),
    )
    return (
        seq((body, stepped), nop_id=node_id(ctx, path, "#empty"))
        if body.nodes
        else stepped
    )


def _step_node(
    ctx: Ctx, path: str, suffix: str, variable: str, reads: tuple[str, ...]
) -> Node:
    return Node(
        id=node_id(ctx, path, suffix),
        kind=NodeKind.ASSIGN,
        paragraph=ctx.paragraph,
        writes=_dedupe((variable,)),
        reads=_dedupe(reads),
        transfer="SET",
    )


def _exec_sql(statement, ctx: Ctx, path: str) -> Fragment:
    """An EXEC SQL block, and the branches any active WHENEVER gives it.

    A WHENEVER contributes NO node: it is a precompiler directive that emits no
    runtime code, so a node for it would imply an execution step that never
    happens. Every other EXEC SQL is followed by one guard per governing
    condition, mirroring what squall.strategy lowers -- IF SQLCODE <op> <val>
    GO TO target -- so the CFG says what the runtime does.
    """
    if statement.kind is Kind.WHENEVER:
        return EMPTY_FRAGMENT
    body = _labelled(_plain(statement, ctx, path), _sql_transfer(statement.kind))
    governing = ctx.whenever.get(node_id(ctx, path), ())
    return seq(
        (body, _whenever_guards(ctx, path, governing, 0)),
        nop_id=node_id(ctx, path, "#sql.join"),
    )


def _sql_transfer(kind: Kind) -> str:
    """The statement's own SQL verb, rather than a uniform EXECSQL for all of
    them. Kind's values are the grammar's rule names, so OPEN is ``open_`` and a
    SELECT ... INTO is ``select_into``; GENERIC is what the parser returns for a
    block it could not classify, which keeps the label it always had."""
    if kind is Kind.GENERIC:
        return SQL_TRANSFER
    return kind.value.rstrip("_").replace("_", " ").upper()


def _labelled(fragment: Fragment, transfer: str) -> Fragment:
    return Fragment(
        nodes=tuple(
            replace(node, transfer=transfer) if node.id == fragment.entry else node
            for node in fragment.nodes
        ),
        edges=fragment.edges,
        entry=fragment.entry,
        exits=fragment.exits,
    )


def _whenever_guards(
    ctx: Ctx, path: str, governing: Governing, position: int
) -> Fragment:
    """Each condition's guard in turn, the failing arm falling into the next and
    the last falling through to the statement after."""
    if position >= len(governing):
        return EMPTY_FRAGMENT
    condition, target = governing[position]
    slot = f"{path}.sql{position}"
    cond = lower_condition(read_condition(SQLCA_CONDITIONS[condition]), ctx, slot)
    taken = _transfer(ctx, slot, "#whenever", target)
    return _wire_arms(cond, taken, _whenever_guards(ctx, path, governing, position + 1))


def _exec_cics(statement, ctx: Ctx, path: str) -> Fragment:
    verb = str(getattr(statement, "verb", "") or "").upper()
    if verb in ARMING_VERBS:
        return _arm(statement, ctx, path, verb)
    if verb == ABENDING_VERB:
        return replace(_plain_without_arms(statement, ctx, path), exits=())
    return _command(statement, ctx, path, verb)


def _command(statement, ctx: Ctx, path: str, verb: str) -> Fragment:
    plain = _plain_without_arms(statement, ctx, path)
    annotated = _called(statement, plain, verb) if verb in ("LINK", "XCTL") else plain
    body = _with_arms(statement, ctx, path, annotated)
    if _suppressed(statement):
        return body
    return _unless_leaving(_raisable(body, ctx, path), verb)


def _unless_leaving(raised: Fragment, verb: str) -> Fragment:
    """A successful XCTL or RETURN never comes back, so the nothing-raised arm has
    nowhere to go. Under RESP or NOHANDLE the command's one exit is its failure,
    which does continue, so only the raising form loses it."""
    return replace(raised, exits=()) if verb in LEAVING_VERBS else raised


def _arm(statement, ctx: Ctx, path: str, verb: str) -> Fragment:
    options = _handler_options(statement)
    return _one(
        Node(
            id=node_id(ctx, path),
            kind=NodeKind.ASSIGN,
            paragraph=ctx.paragraph,
            writes=tuple(handler_field(name) for name, _ in options),
            reads=_dedupe(_armed_value(value, verb) for _, value in options),
            transfer=verb,
        )
    )


def _handler_options(statement) -> tuple[tuple[str, str], ...]:
    """Each non-suppressing option as its name and its text.

    The text is taken here rather than carried onwards, because an option written
    without a value is None in the parse and an absent operand and an empty one mean
    the same thing to lowering. getattr with a default keeps the whole of that at
    this one boundary, and stands in for the banned ``is None`` check.
    """
    return tuple(
        (name.upper(), str(getattr(value, "text", "") or ""))
        for name, value in getattr(statement, "options", {}).items()
        if name.upper() not in SUPPRESSING_OPTIONS
    )


def _armed_value(text: str, verb: str) -> str:
    """A paragraph name when one is given; otherwise the marker for what the
    command means -- IGNORE CONDITION keeps control, a bare HANDLE CONDITION hands
    the condition back to CICS."""
    if text:
        return text.upper()
    return IGNORED if verb == "IGNORE CONDITION" else SYSTEM_DEFAULT


def _suppressed(statement) -> bool:
    names = tuple(name.upper() for name in getattr(statement, "options", {}))
    return any(name in SUPPRESSING_OPTIONS for name in names)


def commarea_field(node: Node) -> str:
    """The caller field a call site shares with its callee, or "" for none.

    Stored in `transfer_operand` rather than inferred from `reads`, because a LINK
    reads its map name and its length too and picking the commarea back out of that
    list is guesswork.
    """
    return node.transfer_operand


def _ref_mod_operand(operand: CicsOperand) -> RefModOperand:
    return RefModOperand(
        name=operand.text,
        ref_mod_start=operand.ref_mod_start,
        ref_mod_length=operand.ref_mod_length,
        subscripts=operand.subscripts,
    )


def _with_call(statement, node: Node, verb: str) -> Node:
    from cobble.dataflow.depgraph.graph import is_literal

    transfer_map = {"LINK": LINK_TRANSFER, "XCTL": XCTL_TRANSFER}
    transfer = transfer_map.get(verb, "")
    program = _callee(statement)
    if not (transfer and program):
        return node
    resolved = _option_is_literal(statement, PROGRAM_OPTION)
    return Node(
        id=node.id,
        kind=NodeKind.CALL,
        paragraph=node.paragraph,
        writes=node.writes,
        reads=node.reads,
        transfer=f"CICS_{transfer}",
        target=program.strip("'\"") if is_literal(program) else program,
        target_resolved=resolved,
        target_operand=(
            NO_TARGET_OPERAND
            if resolved
            else _ref_mod_operand(_option_operand(statement, PROGRAM_OPTION))
        ),
        transfer_operand=_option_text(statement, COMMAREA_OPTION),
    )


def _callee(statement) -> str:
    """The PROGRAM operand as the source spells it, subscript and all.

    A subscripted callee stays unresolved -- which occurrence of the table runs is
    a runtime choice -- but it must not be recorded as the bare name, which claims
    a scalar the program never declared and resolves against no cell at all.
    """
    operand = _option_operand(statement, PROGRAM_OPTION)
    if not operand.subscripts:
        return operand.text
    indices = ", ".join(_index_text(node) for node in operand.subscripts)
    return f"{operand.text}({indices})"


def _index_text(node) -> str:
    """A CICS subscript is a bare data-name or an integer; cicada rejects the rest."""
    written = expr_to_dict(node)
    return str(written.get("name") or written.get("value") or "")


def _option_operand(statement, name: str) -> CicsOperand:
    """The named option's operand, or the empty one when it carries none.

    An option written without a value and an option absent altogether mean the same
    thing to lowering, and both spell as ``NO_OPERAND`` rather than as a None the
    caller has to remember to test.
    """
    options = getattr(statement, "options", {})
    upper_name = name.upper()
    matches = (
        value
        for option, value in options.items()
        if option.upper() == upper_name and isinstance(value, CicsOperand)
    )
    return next(matches, NO_OPERAND)


def _option_text(statement, name: str) -> str:
    options = getattr(statement, "options", {})
    upper_name = name.upper()
    matches = (
        str(getattr(value, "text", "") or "")
        for key, value in options.items()
        if key.upper() == upper_name
    )
    return next(matches, "")


def _option_is_literal(statement, name: str) -> bool:
    options = getattr(statement, "options", {})
    upper_name = name.upper()
    matches = (
        bool(getattr(value, "is_literal", False))
        for key, value in options.items()
        if key.upper() == upper_name
    )
    return next(matches, False)


def _called(statement, fragment: Fragment, verb: str) -> Fragment:
    return Fragment(
        nodes=tuple(
            _with_call(statement, node, verb) if node.id == fragment.entry else node
            for node in fragment.nodes
        ),
        edges=fragment.edges,
        entry=fragment.entry,
        exits=fragment.exits,
    )


def _dispatch_fragment(ctx: Ctx, path: str) -> Fragment:
    """The raise arm's destination: a dispatch node, joined to the handlers armed
    there by ``with_handler_edges`` once the whole program is lowered."""
    dispatch = Node(
        id=node_id(ctx, path, "#dispatch"),
        kind=NodeKind.CALL,
        paragraph=ctx.paragraph,
        reads=(HANDLER_ANY,),
        transfer=DISPATCH_TRANSFER_CICS,
    )
    return Fragment(nodes=(dispatch,), edges=(), entry=dispatch.id, exits=())


def _raisable(body: Fragment, ctx: Ctx, path: str) -> Fragment:
    """A command with no NOHANDLE and no RESP can transfer control to whichever
    handler is armed. When error handlers are known from a pre-scan, the raise
    arm targets each of them directly; otherwise a dead stub stands in.
    """
    cond = _exits_of(
        Node(
            id=node_id(ctx, path, "#raise"),
            kind=NodeKind.TEST,
            paragraph=ctx.paragraph,
            atom=Atom(
                text=f"{HANDLER_ANY} {RAISED}", left=HANDLER_ANY, op="==", right=RAISED
            ),
        )
    )
    arms = _wire_arms(cond, _dispatch_fragment(ctx, path), EMPTY_FRAGMENT)
    return seq((body, arms), nop_id=node_id(ctx, path, "#raise.join"))


def _callee_name(target) -> str:
    """What a CALL site records as its callee, on both arms of ``CallTarget``.

    A literal loses its quotes because the call graph joins on program id and
    ``'PROGB'`` never equals ``PROGB``. A data item keeps its own name and the site
    is marked unresolved: that name is what "which programs can this reach" is a
    reaching-definitions query over, exactly as for a dynamic CICS LINK.
    """
    match target.identifier:
        case None:
            return target.literal.strip().strip("'\"")
        case identifier:
            return identifier.name.strip().upper()


def _identifier_operand(callee) -> RefModOperand:
    """The structured callee, for the data-item arm of a CALL's target.

    Mirrors ``_callee_name``'s own match on the same two arms, rather than
    testing ``callee.identifier`` for None.
    """
    match callee.identifier:
        case None:
            return NO_TARGET_OPERAND
        case operand:
            return operand


def _cobol_call(statement, ctx: Ctx, path: str) -> Fragment:
    """CALL 'PROGB' USING A B. The parameters are the alias list, so they are kept in
    order -- OMITTED included, since a parameter's position is its identity."""
    writes, reads = _writes_reads(statement, ctx, "CallStatement")
    callee = statement.target
    node = Node(
        id=node_id(ctx, path),
        kind=NodeKind.CALL,
        paragraph=ctx.paragraph,
        writes=writes,
        reads=reads,
        transfer=CALL_TRANSFER,
        target=_callee_name(callee),
        target_resolved=not callee.resolved_at_runtime,
        target_operand=_identifier_operand(callee),
        using=tuple(
            (
                ""
                if getattr(param, "omitted", False)
                or getattr(param, "is_literal", False)
                else getattr(param, "name", "")
            )
            for param in getattr(statement, "using", ())
        ),
    )
    return _with_arms(statement, ctx, path, _one(node))


_THROUGH = {And: EdgeKind.TRUE, Or: EdgeKind.FALSE}

_COMPOUNDS = {Not: _negated, And: _chained, Or: _chained}

_LOOP_FORMS = {
    "PerformTimesSpec": _times_loop,
    "PerformUntilSpec": _until_loop,
    "PerformVaryingSpec": _varying_loop,
}

_HANDLERS = {
    "IfStatement": _if,
    "EvaluateStatement": _evaluate,
    "GotoStatement": _goto,
    "PerformStatement": _perform,
    "SearchStatement": _search,
    "ExecCicsStatement": _exec_cics,
    "ExecSqlStatement": _exec_sql,
    "CallStatement": _cobol_call,
    "StopRunStatement": _terminator,
    "GobackStatement": _terminator,
    "ExitProgramStatement": _terminator,
}
