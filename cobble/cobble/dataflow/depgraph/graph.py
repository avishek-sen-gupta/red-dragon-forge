"""graph.py — the coarse variable dependency graph, two passes.

PASS 1 -- literal connectivity. Every data-carrying statement becomes one edge per
(source, target) pair, tagged with the verb that made it and with the index of the
statement it came from. Which statements those are, and which of their operands
count as source and target, is flows.py -- one rule per verb, nothing here.
Nothing is interpreted: no last-writer tracking, no pass-through, no control flow.
The same pair of names can appear many times at many indices and all of them are
kept, because the whole point of pass 2 is to ask how close together two edges are.

PASS 2 -- transform. A -> B -> C collapses to A -> C when B is in the
pass-through list AND the two edges are adjacent in the statement stream. That
adjacency is what stops the collapse from inventing pairings: PROGA uses
WS-NUMERIAL nine separate times, and without it the collapse would claim
unrelated fields are connected.

The index counts DATA-CARRYING statements only -- every statement flows.py has a
rule for, whether or not it yielded an edge -- not statements in general and not
source lines:

  * Not statements in general, because what sits between a conduit's write and its
    read is usually part of the conduit, and counting an IF or a PERFORM as
    distance would need window=2 to see a pair that is written adjacent.
  * Not source lines, because the bridge JSON carries none ({"type": "MOVE",
    "operands": [...]} and nothing else) and this repo does not modify the bridge.
    Index is the better measure regardless -- one program's pair sits three source
    lines apart with an IF in between, one statement apart.

Widening the index from MOVEs to all data-carrying statements is what makes a
conduit written by one verb and read by another adjacent, which is the common case
now that EXEC CICS BIF DEEDIT and COMPUTE are in the stream rather than skipped.

REDEFINES is coarse. Two names over one piece of storage are two overlapping
byte ranges in the flat space layout.py builds, so a write to either is recorded
against both. Containment (a group and its leaves) is deliberately NOT aliased:
DFHCOMMAREA PIC X(10000) contains every field under it, and folding that in
drowns every other signal.

Statement kinds are matched by class NAME rather than by importing the ASG
statement classes. The match has to be exact -- a subclass of MoveStatement that
carried different operand semantics would be silently treated as a MOVE by
isinstance -- and the bridge's class set is not a stable import surface for
cobble.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence

from cobble.dataflow.depgraph.flows import (
    IDENTITY_PREFIXES,
    blocks_of,
    carries_data,
    program_context,
    verb_of,
)
from cobble.dataflow.layout import program_records

# One edge: (source name, target name, statement ordinal, verb label).
Edge = tuple[str, str, int, str]

_FIGURATIVE = frozenset(
    """SPACE SPACES ZERO ZEROS ZEROES LOW-VALUE LOW-VALUES HIGH-VALUE HIGH-VALUES
    QUOTE QUOTES NULL NULLS ALL""".split()
)


def is_literal(name: str) -> bool:
    """Not a node in the graph: a literal, or unnamed storage.

    FILLER is unnamed by definition and can never answer "what depends on what",
    but the bridge synthesises a distinct name per occurrence (FILLER_253) which
    looks like a real node. BMS symbolic maps are mostly FILLER -- the attribute
    byte before each screen field -- so leaving them in put 32 FILLERs beside the
    one real target on every screen-field write.
    """
    if not name:
        return True
    if name.upper() == "FILLER" or name.upper().startswith("FILLER_"):
        return True
    if name[0] in "'\"":
        return True
    if name.upper() in _FIGURATIVE:
        return True
    try:
        float(name.replace("+", "").replace("-", "") or "x")
        return True
    except ValueError:
        return False


def is_node(name: str) -> bool:
    """Whether this name is something the graph can carry.

    An identity node (FILE:LAYOUT1, PROGRAM:PROGA) is exempt from the literal
    test on purpose: it was BUILT from a quoted literal, because a dataset name is
    an identity rather than a value. See flows.py.
    """
    return name.startswith(IDENTITY_PREFIXES) or not is_literal(name)


# ── the pass-through set under judgment ──────────────────────────


class Passthrough:
    """The names a collapse is allowed to route through: explicit, plus regexes.

    A membership test and nothing else, so the set can be handed to pass2 without
    pass2 knowing whether it came from a file, a literal or a test.
    """

    def __init__(self, names: Iterable[str], patterns: Iterable[str]) -> None:
        self.names = frozenset(n.upper() for n in names)
        self.patterns = tuple(re.compile(p) for p in patterns)

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        return name in self.names or any(p.match(name) for p in self.patterns)

    def __len__(self) -> int:
        return len(self.names)


# ── pass 1 ───────────────────────────────────────────────────────


def statement_stream(asg) -> list:
    """Every statement in source order, flattened, nested bodies inline.

    COBOL falls through one paragraph into the next, so declaration order is the
    order statements are written in -- which is all pass 1 needs. PERFORM is not
    followed: a paragraph appears once, where it is declared, not once per call
    site. That is the whole "no traversal" saving.
    """
    out: list = []

    def walk(stmts: Sequence) -> None:
        for s in stmts:
            out.append(s)
            for attr in ("children", "else_children"):
                walk(getattr(s, attr, ()) or ())
            for w in list(getattr(s, "whens", ()) or ()) + list(
                getattr(s, "when_other", ()) or ()
            ):
                walk(getattr(w, "children", ()) or ())

    walk(list(asg.statements))
    for sec in asg.sections:
        walk(list(sec.statements))
        for p in sec.paragraphs:
            walk(list(p.statements))
    for p in asg.paragraphs:
        walk(list(p.statements))
    return out


def aliases(asg) -> Mapping[str, frozenset[str]]:
    """name -> other names sharing its bytes, via REDEFINES only.

    A decl's extent is the span of all its cells, so an OCCURS table is one
    interval covering every row. Coarse by construction, which is what was asked
    for. Only decls in a REDEFINES relationship are compared, so a group is not
    aliased to its own leaves.
    """
    out: dict[str, set[str]] = defaultdict(set)
    for rec in program_records(asg):
        extent: dict[object, tuple[int, int]] = {}
        redefiner: set[object] = set()
        for c in rec.cells:
            lo, hi = extent.get(c.decl, (c.start, c.end))
            extent[c.decl] = (min(lo, c.start), max(hi, c.end))
            if c.redefines:
                redefiner.add(c.decl)
        name_of = {c.decl: c.name.upper() for c in rec.cells}
        for d in redefiner:
            dlo, dhi = extent[d]
            for e, (elo, ehi) in extent.items():
                if e == d or not (elo < dhi and dlo < ehi):
                    continue
                # Intersecting is not aliasing. Every decl inside a redefining
                # group intersects it, and so does every ancestor above it, so
                # the raw test made WS-MSG-TAB [0:14586] an alias of FILLER_33
                # [0:78] and FILLER_221 [14:15] an alias of the whole 924-byte
                # map. Measured over one sample program: 244 pairs share a range,
                # 2720 are one containing the other, 0 partially overlap.
                contained = (dlo <= elo and ehi <= dhi) or (elo <= dlo and dhi <= ehi)
                if not contained or (dlo, dhi) == (elo, ehi):
                    out[name_of[d]].add(name_of[e])
                    out[name_of[e]].add(name_of[d])
    return {k: frozenset(v - {k}) for k, v in out.items()}


def pass1(asg) -> tuple[list[Edge], Counter]:
    """Literal edges: (source, target, statement ordinal, verb), plus a tally.

    Multi-edges are kept. Nine MOVEs into WS-NUMERIAL are nine edges at nine
    indices, and collapsing them here would destroy exactly the information
    pass 2 runs on.

    The tally is the coverage report for the verb table: stmt_<VERB> counts the
    statements a rule ran on, empty_<VERB> the ones whose rule yielded nothing
    (INITIALIZE, a bare REWRITE, a dynamic FILE name), and skip_<ClassName> the
    kinds with no rule at all. Reading those three together is how you tell a verb
    that carries no data from one that is missing a rule.
    """
    alias = aliases(asg)
    ctx = program_context(asg)
    edges: list[Edge] = []
    tally: Counter = Counter()
    idx = -1

    for s in statement_stream(asg):
        if not carries_data(s):
            tally[f"skip_{type(s).__name__}"] += 1
            continue
        idx += 1
        verb = verb_of(s)
        tally[f"stmt_{verb}"] += 1
        blocks = blocks_of(s, ctx)
        if not blocks:
            tally[f"empty_{verb}"] += 1
            continue
        for sources, targets in blocks:
            for src in sources:
                if not is_node(src):
                    tally["dropped_literal_source"] += 1
                    continue
                for dst in targets:
                    if not is_node(dst):
                        tally["dropped_literal_target"] += 1
                        continue
                    fanout = [d for d in alias.get(dst, ()) if is_node(d)]
                    for d in (dst, *fanout):
                        if d == src:
                            # ADD A TO B reads and writes B; SEND MAP from the
                            # record it also names. Neither says anything.
                            tally["dropped_self"] += 1
                            continue
                        edges.append((src, d, idx, verb))
                        tally["edge_alias" if d != dst else "edge"] += 1
    return edges, tally


# ── pass 2 ───────────────────────────────────────────────────────


def pass2(
    edges: Sequence[Edge], passthrough: Passthrough, window: int = 1
) -> tuple[list[Edge], Counter]:
    """Collapse A -> B -> C to A -> C where B is pass-through and the two edges
    are within *window* data-carrying statements of each other.

    Iterated to a fixpoint so a chain of two conduits collapses fully. An edge
    whose target is pass-through but which finds no partner is dropped, not kept:
    it terminates in a variable that is by definition not an answer.

    The surviving edge keeps the ordinal AND the verb of the second hop, the one
    that reached C: that is the statement the value arrives at C by, and it is what
    an ordinal has to point at for a third hop to measure adjacency against.
    """
    tally: Counter = Counter()
    cur = list(edges)

    for round_no in range(1, 11):
        out_of: dict[str, list[Edge]] = defaultdict(list)  # name -> edges LEAVING it
        for e in cur:
            out_of[e[0]].append(e)
        out: list[Edge] = []
        changed = False
        for a, b, i, verb in cur:
            if b not in passthrough:
                out.append((a, b, i, verb))
                continue
            # b is a conduit: find every B -> C written just after this A -> B
            nxt = [(c, j, v) for _, c, j, v in out_of.get(b, ()) if 0 < j - i <= window]
            if not nxt:
                tally["dropped_no_partner"] += 1
                continue
            for c, j, v in nxt:
                out.append((a, c, j, v))
                tally["collapsed"] += 1
            changed = True
        cur = out
        if not changed:
            tally["rounds"] = round_no
            break
    else:
        tally["hit_round_cap"] = 1
    return cur, tally


def declarations(asg) -> Mapping[str, tuple[str, str]]:
    """name -> (declaring section, root record). Context for judging a hub.

    Whether a name is a screen field, a VSAM record field or program-local
    scratch is the first thing anyone asks of a node, and it is not recoverable
    from the name.
    """
    out: dict[str, tuple[str, str]] = {}
    for rec in program_records(asg):
        for c in rec.cells:
            out.setdefault(c.name.upper(), (rec.origin, rec.name))
    return out
