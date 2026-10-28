"""Statements with no control effect, and the node identity every artifact keys on.

The verb table is not reimplemented here: flows.blocks_of already knows what each
statement moves, and this slice only turns its answer into nodes.
"""

from __future__ import annotations

from cobble.dataflow.depgraph.flows import program_context
from cobble.dataflow.srccfg.cfg import EdgeKind, NodeKind
from cobble.dataflow.srccfg.conditions import condition_index
from cobble.dataflow.srccfg.desugar import Ctx, lower_statement, lower_statements


def _ctx(asg, paragraph: str = "MAIN") -> Ctx:
    return Ctx(
        program=asg.program_id,
        paragraph=paragraph,
        flows=program_context(asg),
        index=condition_index(asg),
    )


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


def _only(program_of, statement: dict):
    asg = program_of([statement])
    return lower_statement(asg.paragraphs[0].statements[0], _ctx(asg), "0")


def test_a_move_becomes_one_assign_node_naming_what_it_reads_and_writes(
    program_of,
) -> None:
    fragment = _only(program_of, _move("WS-FLAG-A", "WS-FLAG-B"))

    node = fragment.nodes[0]
    assert (node.kind, node.writes, node.reads, node.transfer) == (
        NodeKind.ASSIGN,
        ("WS-FLAG-B",),
        ("WS-FLAG-A",),
        "MOVE",
    )


def test_the_node_id_is_the_paragraph_and_the_statement_path(program_of) -> None:
    """No ASG statement carries a line number, so identity has to come from
    position. A path is stable across reruns of the same source, which is what a
    stored artifact and a report need to agree on."""
    fragment = _only(program_of, _move("WS-FLAG-A", "WS-FLAG-B"))

    assert fragment.nodes[0].id == "MAIN/0"
    assert fragment.nodes[0].paragraph == "MAIN"


def test_a_fragment_leaves_one_flow_exit_for_the_next_statement(program_of) -> None:
    fragment = _only(program_of, _move("WS-FLAG-A", "WS-FLAG-B"))

    assert fragment.entry == "MAIN/0"
    assert [(e.node_id, e.kind) for e in fragment.exits] == [("MAIN/0", EdgeKind.FLOW)]


def test_a_move_to_two_targets_writes_both_from_one_node(program_of) -> None:
    """One statement, so one node: the co-assignment tier that means "same
    statement" is exactly this, and splitting it into two nodes would lose it."""
    fragment = _only(
        program_of,
        {
            "type": "MOVE",
            "operands": [{"name": "WS-FLAG-A"}, {"name": "WS-B"}, {"name": "WS-C"}],
        },
    )

    assert len(fragment.nodes) == 1
    assert fragment.nodes[0].writes == ("WS-B", "WS-C")


def test_a_literal_source_is_kept_as_a_read(program_of) -> None:
    """MOVE 'F' TO X is the assignment a dictionary rule is usually about, so the
    literal has to survive as the node's source rather than be filtered out."""
    fragment = _only(program_of, _move("'F'", "WS-FLAG-B"))

    assert fragment.nodes[0].reads == ("'F'",)


def test_a_compute_reads_every_name_in_its_expression(program_of) -> None:
    """flows.expression_names already walks the expression tree; this asserts the
    reuse, not a reimplementation."""
    fragment = _only(
        program_of,
        {
            "type": "COMPUTE",
            "targets": [{"name": "WS-TOTAL"}],
            "expression": {
                "kind": "binop",
                "op": "+",
                "left": {"kind": "ref", "name": "WS-A"},
                "right": {"kind": "ref", "name": "WS-B"},
            },
        },
    )

    node = fragment.nodes[0]
    assert node.writes == ("WS-TOTAL",)
    assert set(node.reads) == {"WS-A", "WS-B"}
    assert node.transfer == "COMPUTE"


def test_initialize_writes_with_no_source(program_of) -> None:
    """flows has no rule for INITIALIZE, because a source-to-target edge needs a
    source. Here it matters anyway: a definition with no source still kills the
    previous definition, and a reaching-definitions pass that cannot see the kill
    reports a stale writer."""
    fragment = _only(program_of, {"type": "INITIALIZE", "operands": ["WS-REC"]})

    node = fragment.nodes[0]
    assert (node.kind, node.writes, node.reads, node.transfer) == (
        NodeKind.ASSIGN,
        ("WS-REC",),
        (),
        "INITIALIZE",
    )


def test_display_reads_its_operands_even_though_the_sink_is_outside(program_of) -> None:
    """A verb whose sink is outside the program is a pure use site. DISPLAY writes
    to SYSOUT, not a field, so flows has no rule for it -- but it genuinely reads
    its operands, and losing that would make a field that only DISPLAY reads look
    unused to every downstream pass."""
    fragment = _only(program_of, {"type": "DISPLAY", "operands": [{"name": "WS-A"}]})

    node = fragment.nodes[0]
    assert (node.kind, node.writes, node.reads, node.transfer) == (
        NodeKind.ASSIGN,
        (),
        ("WS-A",),
        "DISPLAY",
    )


def test_accept_writes_its_target_even_though_the_source_is_outside(program_of) -> None:
    """A verb whose source is outside the program still writes its target. ACCEPT
    reads from console or clock, not a field, so flows has no rule for it -- but it
    genuinely writes its target, and losing that would make a field that only ACCEPT
    writes look uninitialized to every downstream pass."""
    fragment = _only(program_of, {"type": "ACCEPT", "target": {"name": "WS-FLAG-A"}})

    node = fragment.nodes[0]
    assert (node.kind, node.writes, node.reads, node.transfer) == (
        NodeKind.ASSIGN,
        ("WS-FLAG-A",),
        (),
        "ACCEPT",
    )


def test_a_gap_fill_kind_with_no_names_is_assign_not_nop(program_of) -> None:
    """A statement kind this module knows touches data is always ASSIGN, whether or
    not extraction produced names. An ASSIGN with empty writes and reads is a parse
    gap made visible -- greppable and countable -- not a no-op."""
    fragment = _only(program_of, {"type": "INITIALIZE"})

    node = fragment.nodes[0]
    assert (node.kind, node.writes, node.reads, node.transfer) == (
        NodeKind.ASSIGN,
        (),
        (),
        "INITIALIZE",
    )


def test_a_verb_with_no_blocks_becomes_a_nop_that_preserves_flow(program_of) -> None:
    """CONTINUE carries no data and has no rule, so blocks_of yields nothing. The
    node is still plumbing that preserves flow -- dropping it would make the
    statements either side look adjacent."""
    fragment = _only(program_of, {"type": "CONTINUE"})

    node = fragment.nodes[0]
    assert (node.kind, node.writes, node.reads, node.transfer) == (
        NodeKind.NOP,
        (),
        (),
        "CONTINUE",
    )


def test_consecutive_statements_are_chained_in_order(program_of) -> None:
    asg = program_of([_move("WS-A", "WS-B"), _move("WS-B", "WS-C")])

    fragment = lower_statements(asg.paragraphs[0].statements, _ctx(asg), "")

    assert [node.id for node in fragment.nodes] == ["MAIN/0", "MAIN/1"]
    assert [(e.source, e.target, e.kind) for e in fragment.edges] == [
        ("MAIN/0", "MAIN/1", EdgeKind.FLOW)
    ]


def test_a_nested_path_is_prefixed_by_its_parent(program_of) -> None:
    """Paths compose, so a statement inside an arm inside a loop still has one id
    and it says where it is."""
    asg = program_of([_move("WS-A", "WS-B")])

    fragment = lower_statements(asg.paragraphs[0].statements, _ctx(asg), "3.else")

    assert fragment.nodes[0].id == "MAIN/3.else.0"


def test_a_paragraph_with_no_statements_lowers_to_nothing(program_of) -> None:
    asg = program_of([])

    assert lower_statements(asg.paragraphs[0].statements, _ctx(asg), "").nodes == ()


def test_a_statement_writes_its_targets_though_nothing_named_feeds_them(
    program_of,
) -> None:
    """A FUNCTION with no arguments, a FILE or PROGRAM chosen at run time, CICS
    filling a field from its own state -- RESP and RESP2 among them -- and INSPECT
    rewriting its subject in place: none names a source the graph has a node for,
    and each still writes."""
    var = {"is_literal": False}
    cfg_nodes = lower_statements(
        program_of(
            [
                {
                    "type": "MOVE",
                    "operands": [
                        {"kind": "function", "name": "CURRENT-DATE", "args": []},
                        {"name": "WS-DATE"},
                    ],
                },
                {
                    "type": "EXEC_CICS",
                    "verb": "READ",
                    "options": {
                        "FILE": {"text": "WS-FILE", **var},
                        "INTO": {"text": "WS-REC", **var},
                        "RESP": {"text": "WS-RESP", **var},
                        "RESP2": {"text": "WS-RESP2", **var},
                    },
                },
                {
                    "type": "EXEC_CICS",
                    "verb": "XCTL",
                    "options": {
                        "PROGRAM": {"text": "WS-PGM", **var},
                        "COMMAREA": {"text": "WS-COMM", **var},
                    },
                },
                {
                    "type": "INSPECT",
                    "inspect_type": "CONVERTING",
                    "source": {"name": "WS-TEXT"},
                    "converting_from": {"name": "'abc'"},
                    "converting_to": {"name": "'ABC'"},
                },
                {
                    "type": "INSPECT",
                    "inspect_type": "REPLACING",
                    "source": {"name": "WS-NAME"},
                    "replacings": [
                        {"mode": "ALL", "from": {"name": "' '"}, "to": {"name": "'-'"}}
                    ],
                },
                {
                    "type": "EXEC_CICS",
                    "verb": "ASKTIME",
                    "options": {"ABSTIME": {"text": "WS-ABS", **var}},
                },
                {
                    "type": "EXEC_CICS",
                    "verb": "ASSIGN",
                    "options": {
                        "APPLID": {"text": "WS-APPLID", **var},
                        "SYSID": {"text": "WS-SYSID", **var},
                    },
                },
            ]
        )
        .paragraphs[0]
        .statements,
        _ctx(program_of([])),
        "",
    ).nodes

    assert [
        (node.kind, node.writes, node.reads) for node in cfg_nodes if "#" not in node.id
    ] == [
        (NodeKind.ASSIGN, ("WS-DATE",), ()),
        (NodeKind.ASSIGN, ("WS-REC", "WS-RESP", "WS-RESP2"), ()),
        (NodeKind.CALL, ("WS-COMM",), ("WS-COMM",)),
        (NodeKind.ASSIGN, ("WS-TEXT",), ("WS-TEXT", "'ABC'")),
        (NodeKind.ASSIGN, ("WS-NAME",), ("WS-NAME", "' '", "'-'")),
        (NodeKind.ASSIGN, ("WS-ABS",), ()),
        (NodeKind.ASSIGN, ("WS-APPLID", "WS-SYSID"), ()),
    ]


def test_a_statement_reads_what_it_hands_out_of_the_program(program_of) -> None:
    """RETURN hands its COMMAREA to the transaction it names, SEND and WRITEQ TD send
    FROM, and INSPECT's patterns choose what lands in its subject. The length is a
    constant and the queue a name, so neither is read."""
    var = {"is_literal": False}
    asg = program_of(
        [
            {
                "type": "EXEC_CICS",
                "verb": "RETURN",
                "options": {
                    "TRANSID": {"text": "'T001'", "is_literal": True},
                    "COMMAREA": {"text": "WS-COMM", **var},
                    "LENGTH": {"text": "LENGTH OF WS-COMM", **var},
                },
            },
            {
                "type": "EXEC_CICS",
                "verb": "SEND TEXT",
                "options": {"FROM": {"text": "WS-MSG", **var}, "ERASE": None},
            },
            {
                "type": "EXEC_CICS",
                "verb": "SEND",
                "options": {"FROM": {"text": "WS-DATA", **var}, "NOHANDLE": None},
            },
            {
                "type": "EXEC_CICS",
                "verb": "WRITEQ TD",
                "options": {
                    "QUEUE": {"text": "WS-QUEUE", **var},
                    "FROM": {"text": "WS-LINE", **var},
                },
            },
            {
                "type": "INSPECT",
                "inspect_type": "CONVERTING",
                "source": {"name": "WS-TEXT"},
                "converting_from": {"name": "WS-LOWER"},
                "converting_to": {"name": "WS-UPPER"},
            },
            {
                "type": "INSPECT",
                "inspect_type": "TALLYING",
                "source": {"name": "WS-NAME"},
                "tallying_groups": [
                    {
                        "target": {"name": "WS-COUNT"},
                        "patterns": [{"mode": "ALL", "pattern": {"name": "WS-CHAR"}}],
                    }
                ],
            },
        ]
    )
    nodes = lower_statements(asg.paragraphs[0].statements, _ctx(asg), "").nodes

    assert [(node.writes, node.reads) for node in nodes if "#" not in node.id] == [
        (("TRANSID:T001",), ("WS-COMM",)),
        ((), ("WS-MSG",)),
        ((), ("WS-DATA",)),
        ((), ("WS-LINE",)),
        (("WS-TEXT",), ("WS-TEXT", "WS-LOWER", "WS-UPPER")),
        (("WS-COUNT",), ("WS-NAME", "WS-CHAR")),
    ]


def test_a_file_statement_names_the_record_its_fd_declares(program_of) -> None:
    """The parser pairs each 01 with its FD, so a READ fills that record and a
    WRITE sends it to that file, however differently the two are named."""
    asg = program_of(
        [
            {"type": "READ", "file_name": "CARD-INPUT"},
            {"type": "READ", "file_name": "CARD-INPUT", "into": "WS-COPY"},
            {"type": "WRITE", "record_name": "OUT-REC"},
        ],
        file_control=[{"file_name": "CARD-INPUT"}, {"file_name": "CARD-OUTPUT"}],
        file_fields=[
            {
                "level": 1,
                "name": "FD-CARD-REC",
                "pic": "X(16)",
                "fd_name": "CARD-INPUT",
            },
            {"level": 1, "name": "OUT-REC", "pic": "X(16)", "fd_name": "CARD-OUTPUT"},
        ],
    )
    nodes = lower_statements(asg.paragraphs[0].statements, _ctx(asg), "").nodes

    assert [(node.writes, node.reads) for node in nodes if "#" not in node.id] == [
        (("FD-CARD-REC",), ("FILE:CARD-INPUT",)),
        (("WS-COPY", "FD-CARD-REC"), ("FILE:CARD-INPUT",)),
        (("FILE:CARD-OUTPUT",), ("OUT-REC",)),
    ]


def test_a_set_reads_the_field_it_copies_and_no_literal(program_of) -> None:
    """SET X TO Y reads Y; the TRUE of a condition and a number name no field."""

    def _set(target: str, value: dict) -> dict:
        return {
            "type": "SET",
            "set_type": "TO",
            "targets": [{"kind": "ref", "name": target}],
            "values": [value],
        }

    asg = program_of(
        [
            _set("WS-IX", {"kind": "ref", "name": "WS-N"}),
            _set("WS-DONE", {"kind": "lit", "value": "TRUE"}),
            _set("WS-IX", {"kind": "lit", "value": "1"}),
        ]
    )
    nodes = lower_statements(asg.paragraphs[0].statements, _ctx(asg), "").nodes

    assert [(node.writes, node.reads) for node in nodes] == [
        (("WS-IX",), ("WS-N",)),
        (("WS-DONE",), ()),
        (("WS-IX",), ()),
    ]
