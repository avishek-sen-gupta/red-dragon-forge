"""flows.py — one statement, reduced to the names it reads and the names it writes.

This is the whole verb table of the coarse graph, and nothing here knows what a
graph is: a statement goes in, ``(verb, blocks)`` comes out, where a block is one
``(sources, targets)`` group. pass1 turns each block into a cross product of edges
and does the literal filtering, so a rule here is readable as a rule.

Most statements are one block. Two are not, and both for the same reason -- a
callee writes back through what it was handed:

    CALL 'PROGA' USING WS-LINK-REC   ->  (params -> PROGRAM:PROGA)
                                         (PROGRAM:PROGA -> REFERENCE params)
    EXEC CICS LINK PROGRAM('PROGB') COMMAREA(WS-COMM)
                                    ->  (WS-COMM -> PROGRAM:PROGB)
                                        (PROGRAM:PROGB -> WS-COMM)

ONE RULE DECIDES WHAT IS LEFT OUT: a selector is not provenance. Subscripts
(``WS-TBL(WS-IND)``), ``READ ... KEY``, ``START ... KEY`` and CICS ``RIDFLD`` all
choose WHICH value is moved, not where the value came from. The graph has one node
per name whatever the subscript, so those edges would say nothing -- and they would
make every loop counter and every key field a hub with hundreds of readers.

Verbs that carry data but yield nothing, deliberately:

    INITIALIZE      365 in a 120-program sample -- targets, no source, exactly
                    like MOVE ZERO TO X, which pass1 has always dropped
    DISPLAY         the sink is SYSOUT, which is not a node
    ACCEPT          the source is the clock or a device mnemonic
    EXEC SQL        the bridge keeps the block as opaque text; a real gap
    CICS RETRIEVE   its data came from another transaction's START FROM, and the
                    receiving transid is not in the statement
    CICS ASKTIME    ABSTIME is written by CICS, from nothing in the program
    CICS ASSIGN     same: USERID etc. come from the system
    CICS BIF DEEDIT FIELD(X) edits X in place, which is the self edge X -> X

EXTERNAL IDENTITIES BECOME NODES, prefixed so a dataset called like a variable
cannot merge with it: FILE:, MAP:, PROGRAM:, TSQ:, TRANSID:. This is the one place
a quoted literal becomes a node -- a dataset name is an identity, not a value --
and it is safe because the corpus writes them as literals almost always: of 452
CICS file/dataset operands sampled, 446 are literal, and 177 of 178 LINK PROGRAMs.

Statement kinds are matched by class NAME, as in graph.py: the bridge's class set
is not a stable import surface for cobble, and an exact match means a subclass
with different operand semantics is skipped loudly rather than mishandled quietly.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping, Sequence
from typing import Callable

# (sources, targets). pass1 emits every source -> target pair in a block.
Block = tuple[tuple[str, ...], tuple[str, ...]]

FILE_PREFIX = "FILE:"
MAP_PREFIX = "MAP:"
PROGRAM_PREFIX = "PROGRAM:"
QUEUE_PREFIX = "TSQ:"
TRANSID_PREFIX = "TRANSID:"

IDENTITY_PREFIXES = (
    FILE_PREFIX,
    MAP_PREFIX,
    PROGRAM_PREFIX,
    QUEUE_PREFIX,
    TRANSID_PREFIX,
)

# The names a value can arrive from or land in inside an expression. Everything
# else in the expression tree (BinOpNode, LiteralNode, FigurativeNode, DfhRespNode)
# either carries no name or carries one that is not a variable.
_EXPRESSION_NAME_NODES = frozenset({"FieldRefNode", "RefModNode", "LengthOfNode"})

# Not descended into, anywhere: see the selector rule in this module's docstring.
_SELECTOR_FIELDS = frozenset({"subscripts"})


# ── names off operands and expressions ───────────────────────────


def operand_name(operand: object) -> str:
    """One operand's name, upper-cased, whatever shape it arrived in.

    RefModOperand and ComputeTarget carry ``name``, CicsOperand carries ``text``,
    and several statements (MOVE CORRESPONDING, INITIALIZE, SET) carry plain
    strings. All four are one call here rather than four spellings at the call
    sites.
    """
    if operand is None:
        return ""
    if isinstance(operand, str):
        return operand.strip().upper()
    for attribute in ("name", "text"):
        value = getattr(operand, attribute, None)
        if isinstance(value, str):
            return value.strip().upper()
    return ""


def operand_names(operands: Iterable[object]) -> tuple[str, ...]:
    return tuple(name for name in map(operand_name, operands) if name)


def expression_names(node: object) -> tuple[str, ...]:
    """Every variable name read by an expression tree, subscripts excluded.

    Handles both shapes the ASG hands out: typed expression nodes (COMPUTE's
    ``expression``) and the raw dicts a FunctionCallOperand keeps its args as
    ({"kind": "ref", "name": "WS-X"}), so ``MOVE FUNCTION UPPER-CASE(WS-X) TO Y``
    still yields WS-X -> Y instead of nothing.
    """
    if isinstance(node, dict):
        found = (node["name"],) if isinstance(node.get("name"), str) else ()
        children = [v for k, v in node.items() if k not in _SELECTOR_FIELDS]
        return found + tuple(n for c in children for n in expression_names(c))
    if isinstance(node, (list, tuple)):
        return tuple(n for item in node for n in expression_names(item))
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        name = getattr(node, "name", "")
        found = (
            (name,)
            if type(node).__name__ in _EXPRESSION_NAME_NODES and isinstance(name, str)
            else ()
        )
        children = [
            getattr(node, f.name)
            for f in dataclasses.fields(node)
            if f.name not in _SELECTOR_FIELDS
        ]
        return found + tuple(n for c in children for n in expression_names(c))
    return ()


def _read_names(operand: object) -> tuple[str, ...]:
    """What an operand in a source position reads.

    A FunctionCallOperand reads its arguments and has no name of its own, so it is
    the expression walk; anything else is one name.
    """
    if type(operand).__name__ == "FunctionCallOperand":
        return tuple(n.upper() for n in expression_names(operand))
    name = operand_name(operand)
    return (name,) if name else ()


# ── the program's own vocabulary ─────────────────────────────────


@dataclasses.dataclass(frozen=True)
class ProgramContext:
    """What a rule needs to know about the program it is reading.

    record_of_file / file_of_record  the FD <-> record area pairing, which the ASG
                                    does not carry (see fd_record_pairing)
    declared                        every declared name, for resolving the record
                                    a SEND MAP / RECEIVE MAP implies
    """

    record_of_file: Mapping[str, str]
    file_of_record: Mapping[str, str]
    declared: frozenset[str]


def _record_names(fields: Iterable[object]) -> tuple[str, ...]:
    return tuple(operand_name(f) for f in fields)


def _all_declared(fields: Iterable[object]) -> tuple[str, ...]:
    out: list[str] = []
    for field in fields:
        out.append(operand_name(field))
        out.extend(_all_declared(getattr(field, "children", ()) or ()))
    return tuple(out)


def fd_record_pairing(file_names: Sequence[str], record_names: Sequence[str]) -> dict:
    """FD name -> its record area, matched by name, uniquely or not at all.

    Batch READ is 170/170 bare in a 120-program sample -- ``READ LAYOUT1`` with no
    INTO -- so without this pairing every batch read yields no edge at all and the
    whole batch half of the corpus starts from nowhere.

    The ASG cannot answer it: ``file_record_to_select`` is null in every cached
    program, and pairing file_control to file_fields BY INDEX is wrong -- one program
    pairs the wrong FD with the wrong record that way. Name matching is right and
    measurable: the FD name as a prefix of an 01, then the FD name minus its 3- or
    4-character site prefix. Over 477 FDs that is 357 unique, 8 ambiguous, 112
    unresolved -- the unresolved being files whose record lives in a foreign stub
    copybook, so the record is genuinely not in the program.

    Ambiguous is left unresolved rather than guessed at: two candidates means the
    edge would be a coin toss.
    """
    out: dict[str, str] = {}
    for file_name in file_names:
        for stem in (file_name, file_name[3:], file_name[4:]):
            if not stem:
                continue
            hits = [r for r in record_names if r.startswith(stem)]
            if len(hits) == 1:
                out[file_name] = hits[0]
                break
    return out


def program_context(asg) -> ProgramContext:
    records = _record_names(getattr(asg, "file_fields", ()) or ())
    files = tuple(
        operand_name(getattr(e, "file_name", ""))
        for e in getattr(asg, "file_control", ()) or ()
    )
    record_of_file = fd_record_pairing(files, records)
    declared = frozenset(
        name
        for group in ("data_fields", "linkage_fields", "local_storage_fields")
        for name in _all_declared(getattr(asg, group, ()) or ())
        if name
    ) | frozenset(records)
    return ProgramContext(
        record_of_file=record_of_file,
        file_of_record={rec: fd for fd, rec in record_of_file.items()},
        declared=declared,
    )


# ── one rule per COBOL statement ─────────────────────────────────


def _block(sources: Iterable[str], targets: Iterable[str]) -> tuple[Block, ...]:
    """One block, or none when either side is empty (no edge to build)."""
    src, dst = tuple(s for s in sources if s), tuple(t for t in targets if t)
    return ((src, dst),) if src and dst else ()


def _move(s, ctx: ProgramContext) -> tuple[Block, ...]:
    return _block(_read_names(s.source), operand_names(s.targets))


def _move_corresponding(s, ctx: ProgramContext) -> tuple[Block, ...]:
    return _block((operand_name(s.source),), operand_names(s.targets))


def _arithmetic(s, ctx: ProgramContext) -> tuple[Block, ...]:
    """ADD/SUBTRACT/MULTIPLY/DIVIDE, all four through op.

    ``target`` is in BOTH columns because that is what the verb does without
    GIVING: ADD A TO B reads A and B and writes B. The B -> B self edge pass1
    drops; A -> B is the edge that matters. With GIVING, ADD A TO B GIVING C is
    A -> C and B -> C, and B is no longer written.
    """
    sources = (operand_name(s.source), operand_name(s.target))
    given = operand_names(s.giving)
    remainder = (operand_name(s.remainder),) if s.remainder is not None else ()
    targets = (given or (operand_name(s.target),)) + remainder
    return _block(sources, targets)


def _arithmetic_corresponding(s, ctx: ProgramContext) -> tuple[Block, ...]:
    return _block((operand_name(s.source),), (operand_name(s.target),))


def _compute(s, ctx: ProgramContext) -> tuple[Block, ...]:
    return _block(expression_names(s.expression), operand_names(s.targets))


def _string(s, ctx: ProgramContext) -> tuple[Block, ...]:
    """STRING's sendings into its receiver, plus WITH POINTER.

    The pointer is written by the statement -- it ends up past the last character
    stored -- so it depends on the lengths of everything sent. 0 of 831 STRINGs in
    the sample use one; the rule is here because it costs a line, not because any
    corpus needs it. DELIMITED BY is not a source: it bounds the copy, it is not copied.
    """
    sources = tuple(
        name
        for sending in s.sendings
        for name in _read_names(getattr(sending, "function", None) or sending.value)
    )
    return _block(sources, (operand_name(s.into), operand_name(s.pointer)))


def _unstring(s, ctx: ProgramContext) -> tuple[Block, ...]:
    """One source split across many receivers; the tally and pointer derive from it."""
    targets = operand_names(s.into) + (
        operand_name(s.tallying_target),
        operand_name(s.pointer),
    )
    return _block((operand_name(s.source),), targets)


def _inspect(s, ctx: ProgramContext) -> tuple[Block, ...]:
    """TALLYING only. REPLACING and CONVERTING rewrite the source in place, which
    is the self edge, and their FROM/TO operands are figurative or literal in all
    five INSPECTs sampled."""
    tallied = tuple(operand_name(g.target) for g in s.tallying_groups)
    return _block((operand_name(s.source),), tallied)


def _set(s, ctx: ProgramContext) -> tuple[Block, ...]:
    """SET X TO Y. SET ... TO TRUE and SET ... TO 1 drop out as literals in pass1."""
    return _block(operand_names(s.values), operand_names(s.targets))


def _search(s, ctx: ProgramContext) -> tuple[Block, ...]:
    """SEARCH ... VARYING I: where the search stops depends on the table's contents.

    Without VARYING (38 of 38 sampled) the index is the table's own INDEXED BY,
    which is not a data name, so there is no node to point at.
    """
    return _block((operand_name(s.table),), (operand_name(s.varying),))


def _call(s, ctx: ProgramContext) -> tuple[Block, ...]:
    """Parameters into the callee, and the callee back into its BY REFERENCE ones.

    The reverse block is what makes CALL worth reading: a commarea record is passed in
    empty and comes back filled, and with a forward-only rule the graph would say
    the callee's answer came from nowhere. Which fields the callee actually writes
    is not knowable from the call site, so the program node carries the whole
    relation rather than being resolved into it.
    """
    program = PROGRAM_PREFIX + operand_name(s.program)
    params = tuple(
        operand_name(p) for p in s.using if not getattr(p, "is_literal", False)
    )
    by_reference = tuple(
        operand_name(p)
        for p in s.using
        if getattr(p, "param_type", "") == "REFERENCE"
        and not getattr(p, "is_literal", False)
    )
    giving = (operand_name(s.giving),) if s.giving else ()
    return _block(params, (program,) + giving) + _block((program,), by_reference)


def _read(s, ctx: ProgramContext) -> tuple[Block, ...]:
    """A record arrives from a dataset. KEY is a selector, so it is not a source."""
    file_name = operand_name(s.file_name)
    into = operand_name(s.into) or ctx.record_of_file.get(file_name, "")
    return _block((FILE_PREFIX + file_name if file_name else "",), (into,))


def _write(s, ctx: ProgramContext) -> tuple[Block, ...]:
    """WRITE and REWRITE: FROM into the record area, record area out to the dataset.

    Two blocks because both halves are real and both are sometimes all there is:
    671 of 758 WRITEs carry FROM, and all 13 REWRITEs sampled carry none -- their
    record area was filled by earlier MOVEs, and the dataset edge is the only thing
    that says where it went.
    """
    record = operand_name(s.record_name)
    source = operand_name(getattr(s, "from_field", ""))
    file_name = ctx.file_of_record.get(record, "")
    return _block((source,), (record,)) + _block(
        (record,), (FILE_PREFIX + file_name if file_name else "",)
    )


def _xml_generate(s, ctx: ProgramContext) -> tuple[Block, ...]:
    return _block(
        (operand_name(s.from_record),),
        (operand_name(s.xml_document), operand_name(s.count_in)),
    )


# ── one rule per EXEC CICS verb ──────────────────────────────────


def _option(options: Mapping, *keys: str) -> str:
    """The first of these options that is present, as a name."""
    for key in keys:
        if key in options:
            return operand_name(options[key])
    return ""


def _identity(prefix: str, options: Mapping, *keys: str) -> str:
    """An external object's name as a node id, quotes stripped.

    ``FILE('LAYOUT1')`` names a dataset, so the literal is an identity and gets a
    node; the same option written as a variable (6 of 452 sampled) holds a name
    chosen at run time, which is a selector and yields nothing.
    """
    for key in keys:
        operand = options.get(key)
        if operand is None:
            continue
        if not getattr(operand, "is_literal", False):
            return ""
        text = operand_name(operand).strip("'\"")
        return prefix + text if text else ""
    return ""


def _map_record(ctx: ProgramContext, map_name: str, suffix: str) -> str:
    """The symbolic map record a MAP option implies, if the program declares it.

    SEND MAP carries no FROM in any of 47 sampled and RECEIVE MAP no INTO in 47 of
    48: BMS defines the record for them, ``01 MAP1O`` and
    ``01 MAP1I REDEFINES MAP1O``, both real 01s in the generated symbolic
    maps. So this is a declaration lookup, not a naming guess -- a map whose
    copybook the program does not COPY resolves to nothing.
    """
    if not map_name:
        return ""
    candidate = map_name[len(MAP_PREFIX) :] + suffix
    return candidate if candidate in ctx.declared else ""


def _cics_read(s, ctx: ProgramContext) -> tuple[Block, ...]:
    """READ/READNEXT/READPREV INTO. RIDFLD is the key, so it is a selector."""
    return _block(
        (_identity(FILE_PREFIX, s.options, "FILE", "DATASET"),),
        (_option(s.options, "INTO"),),
    )


def _cics_write(s, ctx: ProgramContext) -> tuple[Block, ...]:
    return _block(
        (_option(s.options, "FROM"),),
        (_identity(FILE_PREFIX, s.options, "FILE", "DATASET"),),
    )


def _cics_transfer(s, ctx: ProgramContext) -> tuple[Block, ...]:
    """LINK/XCTL: the commarea goes out and comes back, same as CALL's parameters."""
    program = _identity(PROGRAM_PREFIX, s.options, "PROGRAM")
    commarea = _option(s.options, "COMMAREA")
    return _block((commarea,), (program,)) + _block((program,), (commarea,))


def _cics_send_map(s, ctx: ProgramContext) -> tuple[Block, ...]:
    map_node = _identity(MAP_PREFIX, s.options, "MAP", "MAPNAME")
    source = _option(s.options, "FROM") or _map_record(ctx, map_node, "O")
    return _block((source,), (map_node,))


def _cics_receive_map(s, ctx: ProgramContext) -> tuple[Block, ...]:
    map_node = _identity(MAP_PREFIX, s.options, "MAP", "MAPNAME")
    target = _option(s.options, "INTO") or _map_record(ctx, map_node, "I")
    return _block((map_node,), (target,))


def _cics_writeq_ts(s, ctx: ProgramContext) -> tuple[Block, ...]:
    return _block(
        (_option(s.options, "FROM"),),
        (_identity(QUEUE_PREFIX, s.options, "QUEUE", "QNAME"),),
    )


def _cics_readq_ts(s, ctx: ProgramContext) -> tuple[Block, ...]:
    return _block(
        (_identity(QUEUE_PREFIX, s.options, "QUEUE", "QNAME"),),
        (_option(s.options, "INTO"),),
    )


def _cics_start(s, ctx: ProgramContext) -> tuple[Block, ...]:
    """START TRANSID('T') FROM(X): X is queued for whichever program runs T.

    The matching RETRIEVE has no rule of its own, so this edge stops at the
    transaction node -- which is exactly as far as the statement says.
    """
    return _block(
        (_option(s.options, "FROM"),),
        (_identity(TRANSID_PREFIX, s.options, "TRANSID"),),
    )


def _cics_formattime(s, ctx: ProgramContext) -> tuple[Block, ...]:
    """ABSTIME in, every other named operand out.

    FORMATTIME's output options are open-ended (DDMMYYYY, YYYYMMDD, TIME,
    DAYOFWEEK, ...) and all of them are receiving fields, so listing them would be
    a list to maintain: anything that is not the input and is a data name is an
    output. DATESEP('/') and friends are literals and drop out.
    """
    source = _option(s.options, "ABSTIME")
    targets = tuple(
        operand_name(operand)
        for key, operand in s.options.items()
        if key != "ABSTIME"
        and operand is not None
        and not getattr(operand, "is_literal", False)
    )
    return _block((source,), targets)


_CICS_RULES: Mapping[str, Callable[..., tuple[Block, ...]]] = {
    "READ": _cics_read,
    "READNEXT": _cics_read,
    "READPREV": _cics_read,
    "WRITE": _cics_write,
    "REWRITE": _cics_write,
    "LINK": _cics_transfer,
    "XCTL": _cics_transfer,
    "SEND MAP": _cics_send_map,
    "RECEIVE MAP": _cics_receive_map,
    "WRITEQ TS": _cics_writeq_ts,
    "READQ TS": _cics_readq_ts,
    "START": _cics_start,
    "FORMATTIME": _cics_formattime,
}


def _exec_cics(s, ctx: ProgramContext) -> tuple[Block, ...]:
    rule = _CICS_RULES.get(s.verb.upper())
    return rule(s, ctx) if rule else ()


def _exec_cics_verb(s) -> str:
    """The verb label an EXEC CICS edge is tagged with, e.g. CICS_SEND_MAP."""
    return "CICS_" + s.verb.upper().replace(" ", "_") if s.verb else "CICS_"


_RULES: Mapping[str, Callable[..., tuple[Block, ...]]] = {
    "MoveStatement": _move,
    "MoveCorrespondingStatement": _move_corresponding,
    "ArithmeticStatement": _arithmetic,
    "ArithmeticCorrespondingStatement": _arithmetic_corresponding,
    "ComputeStatement": _compute,
    "StringStatement": _string,
    "UnstringStatement": _unstring,
    "InspectStatement": _inspect,
    "SetStatement": _set,
    "SearchStatement": _search,
    "CallStatement": _call,
    "ReadStatement": _read,
    "WriteStatement": _write,
    "RewriteStatement": _write,
    "XmlGenerateStatement": _xml_generate,
    "ExecCicsStatement": _exec_cics,
}

# The verb label per statement class. ArithmeticStatement carries its own in op
# (ADD/SUBTRACT/MULTIPLY/DIVIDE) and EXEC CICS in verb, so both are computed.
_VERB_LABELS: Mapping[str, str] = {
    "MoveStatement": "MOVE",
    "MoveCorrespondingStatement": "MOVE_CORRESPONDING",
    "ArithmeticCorrespondingStatement": "ADD_CORRESPONDING",
    "ComputeStatement": "COMPUTE",
    "StringStatement": "STRING",
    "UnstringStatement": "UNSTRING",
    "InspectStatement": "INSPECT",
    "SetStatement": "SET",
    "SearchStatement": "SEARCH",
    "CallStatement": "CALL",
    "ReadStatement": "READ",
    "WriteStatement": "WRITE",
    "RewriteStatement": "REWRITE",
    "XmlGenerateStatement": "XML_GENERATE",
}

# Every verb label an edge can be tagged with, for anything that colours or counts
# by verb. CICS labels are listed from the rule table so the two cannot drift. No
# REDEFINES label: an edge reached through an alias is the same write seen through
# a second name, so it keeps the verb of the statement that wrote it.
VERB_LABELS: frozenset[str] = (
    frozenset(_VERB_LABELS.values())
    | frozenset({"ADD", "SUBTRACT", "MULTIPLY", "DIVIDE"})
    | frozenset("CICS_" + v.replace(" ", "_") for v in _CICS_RULES)
)


def carries_data(statement) -> bool:
    """True if this statement kind has a rule, whether or not it yields an edge.

    What the statement ordinal counts (see graph.pass1): a statement with a rule
    that produced nothing this time -- MOVE ZERO TO X, a bare REWRITE -- still
    happened, and skipping it would make two statements look adjacent across it.
    """
    return type(statement).__name__ in _RULES


def verb_of(statement) -> str:
    """The verb label for this statement, or "" if no rule covers its kind."""
    kind = type(statement).__name__
    if kind == "ArithmeticStatement":
        return statement.op.upper()
    if kind == "ExecCicsStatement":
        return _exec_cics_verb(statement)
    return _VERB_LABELS.get(kind, "")


def blocks_of(statement, ctx: ProgramContext) -> tuple[Block, ...]:
    """The (sources, targets) blocks this statement contributes, possibly none."""
    rule = _RULES.get(type(statement).__name__)
    return rule(statement, ctx) if rule else ()
