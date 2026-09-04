"""AT END, INVALID KEY, ON SIZE ERROR, and SEARCH.

These are guards written as clauses of another statement. An assignment in an AT END
arm runs only when the read failed; treating the arm as unconditional reports it as
a writer under no guard, which is the wrong answer to the question the whole pass
exists to answer.
"""

from __future__ import annotations

from cobble.dataflow.depgraph.flows import program_context

from cobble.dataflow.srccfg.cfg import Cfg, EdgeKind, NodeKind
from cobble.dataflow.srccfg.conditions import condition_index
from cobble.dataflow.srccfg.desugar import Ctx, lower_statements
from cobble.dataflow.srccfg.synthetic import io_status_field


def _ctx(asg) -> Ctx:
    return Ctx(
        program=asg.program_id,
        paragraph="MAIN",
        flows=program_context(asg),
        index=condition_index(asg),
    )


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


def _cfg(program_of, statements: list[dict], **extra) -> Cfg:
    asg = program_of(statements, **extra)
    fragment = lower_statements(asg.paragraphs[0].statements, _ctx(asg), "")
    return Cfg(program="PROGA", nodes=fragment.nodes, edges=fragment.edges)


_FILE_CONTROL = {"file_control": [{"file_name": "CUST-FILE", "assign_to": "CUSTDD"}]}


def test_an_at_end_arm_runs_under_a_test_on_the_files_status(program_of) -> None:
    """The predicate is not a field the program declares, so a synthetic one names
    the file it is about -- which is also what makes two files' AT END arms
    distinguishable."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "READ",
                "file_name": "CUST-FILE",
                "at_end": [_move("'Y'", "WS-EOF")],
            }
        ],
        **_FILE_CONTROL,
    )

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert test_node.atom.left == io_status_field("CUST-FILE")
    assert test_node.atom.right == "AT END"


def test_the_at_end_arm_is_on_the_true_edge_and_not_at_end_on_the_false(
    program_of,
) -> None:
    cfg = _cfg(
        program_of,
        [
            {
                "type": "READ",
                "file_name": "CUST-FILE",
                "at_end": [_move("'Y'", "WS-EOF")],
                "not_at_end": [_move("'N'", "WS-EOF")],
            }
        ],
        **_FILE_CONTROL,
    )

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert {(e.target, e.kind) for e in cfg.successors(test_node.id)} == {
        ("MAIN/0.at_end.0", EdgeKind.TRUE),
        ("MAIN/0.not_at_end.0", EdgeKind.FALSE),
    }


def test_the_read_itself_still_happens_before_the_test(program_of) -> None:
    """READ INTO is an assignment, and it happens whichever arm is taken -- so the
    ASSIGN node comes first and the test hangs off it."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "READ",
                "file_name": "CUST-FILE",
                "into": "WS-REC",
                "at_end": [_move("'Y'", "WS-EOF")],
            }
        ],
        **_FILE_CONTROL,
    )

    read = cfg.node("MAIN/0")
    assert read.writes == ("WS-REC",)
    assert [e.target for e in cfg.successors("MAIN/0")] == ["MAIN/0#arm"]


def test_an_invalid_key_arm_is_guarded_the_same_way(program_of) -> None:
    cfg = _cfg(
        program_of,
        [
            {
                "type": "WRITE",
                "record_name": "CUST-REC",
                "invalid_key": [_move("'E'", "WS-STATUS")],
            }
        ],
    )

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert test_node.atom.right == "INVALID KEY"


def test_an_on_size_error_arm_is_guarded_by_the_targets_own_status(program_of) -> None:
    """A size error is about the arithmetic, not about a file, so the synthetic
    field names the target being computed into."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "COMPUTE",
                "targets": [{"name": "WS-TOTAL"}],
                "expression": {"kind": "ref", "name": "WS-A"},
                "on_size_error": [_move("'E'", "WS-STATUS")],
            }
        ],
    )

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert test_node.atom.left == io_status_field("WS-TOTAL")


def test_a_statement_with_no_arms_gets_no_extra_node(program_of) -> None:
    """The overwhelming majority of statements. An unconditional MOVE must not grow
    a test node it does not need."""
    cfg = _cfg(program_of, [_move("'F'", "WS-RESULT")])

    assert len(cfg.nodes) == 1


def test_both_arms_and_the_fall_through_continue_into_the_next_statement(
    program_of,
) -> None:
    cfg = _cfg(
        program_of,
        [
            {
                "type": "READ",
                "file_name": "CUST-FILE",
                "at_end": [_move("'Y'", "WS-EOF")],
            },
            _move("WS-EOF", "WS-COPY"),
        ],
        **_FILE_CONTROL,
    )

    assert {e.source for e in cfg.predecessors("MAIN/1")} == {
        "MAIN/0.at_end.0",
        "MAIN/0#arm",
    }


def test_a_search_when_is_a_test_whose_predicate_is_unresolved(program_of) -> None:
    """The ASG gives a SEARCH WHEN condition as opaque text. The fork is real, so
    the node exists; the parts are unknown, and saying so is the requirement --
    inventing an atom from the text would be a guess a report could not qualify."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "SEARCH",
                "table": "WS-TABLE",
                "varying": "WS-IDX",
                "whens": [
                    {
                        "condition": "WS-TABLE-KEY (WS-IDX) = WS-WANTED",
                        "children": [_move("'F'", "WS-RESULT")],
                    }
                ],
            }
        ],
    )

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert test_node.atom.resolved is False
    assert test_node.atom.text == "WS-TABLE-KEY (WS-IDX) = WS-WANTED"


def test_a_search_body_is_reached_on_the_true_edge_of_its_when(program_of) -> None:
    cfg = _cfg(
        program_of,
        [
            {
                "type": "SEARCH",
                "table": "WS-TABLE",
                "whens": [
                    {"condition": "A = B", "children": [_move("'F'", "WS-RESULT")]}
                ],
            }
        ],
    )

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert [(e.target, e.kind) for e in cfg.successors(test_node.id)] == [
        ("MAIN/0.when.0.0", EdgeKind.TRUE)
    ]


def test_a_second_search_when_is_reached_on_the_firsts_false_edge(program_of) -> None:
    """Same chain as EVALUATE: a WHEN is tried only when the ones above it failed."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "SEARCH",
                "table": "WS-TABLE",
                "whens": [
                    {"condition": "A = B", "children": [_move("'F'", "WS-RESULT")]},
                    {"condition": "A = C", "children": [_move("'G'", "WS-RESULT")]},
                ],
            }
        ],
    )

    first, second = (n.id for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert [e.target for e in cfg.successors(first) if e.kind is EdgeKind.FALSE] == [
        second
    ]


def test_a_search_at_end_arm_is_the_last_false_arm(program_of) -> None:
    cfg = _cfg(
        program_of,
        [
            {
                "type": "SEARCH",
                "table": "WS-TABLE",
                "whens": [
                    {"condition": "A = B", "children": [_move("'F'", "WS-RESULT")]}
                ],
                "at_end": [_move("'Z'", "WS-RESULT")],
            }
        ],
    )

    assert [e.kind for e in cfg.predecessors("MAIN/0.at_end.0")] == [EdgeKind.FALSE]


def test_a_search_reads_the_table_and_its_index(program_of) -> None:
    """flows already has a SearchStatement rule; this asserts the reuse rather than
    a second reading of the same statement. The flows rule reports the index as a
    write target (SEARCH modifies it), so the assertion is on writes."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "SEARCH",
                "table": "WS-TABLE",
                "varying": "WS-IDX",
                "whens": [{"condition": "A = B", "children": []}],
            }
        ],
    )

    assert "WS-TABLE" in cfg.node("MAIN/0").reads
    assert "WS-IDX" in cfg.node("MAIN/0").writes


def test_an_add_with_size_error_names_the_arithmetic_target(program_of) -> None:
    """ArithmeticStatement has giving, not targets, so the fallback chain must
    handle both."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "ADD",
                "source": {"name": "WS-A"},
                "target": {"name": "WS-B"},
                "giving": [{"name": "WS-TOTAL"}],
                "on_size_error": [_move("'E'", "WS-STATUS")],
            }
        ],
    )

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert test_node.atom.left == io_status_field("WS-TOTAL")
    assert test_node.atom.resolved is True


def test_a_read_with_both_at_end_and_invalid_key_lowers_both_bodies(
    program_of,
) -> None:
    """When both arm families are present, chain them rather than dropping one."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "READ",
                "file_name": "CUST-FILE",
                "at_end": [_move("'Y'", "WS-EOF")],
                "invalid_key": [_move("'E'", "WS-STATUS")],
            }
        ],
        **_FILE_CONTROL,
    )

    at_end_node = cfg.node("MAIN/0.at_end.0")
    invalid_key_node = cfg.node("MAIN/0.invalid_key.0")
    assert at_end_node.writes == ("WS-EOF",)
    assert invalid_key_node.writes == ("WS-STATUS",)
    test_nodes = [n for n in cfg.nodes if n.kind == NodeKind.TEST]
    assert len(test_nodes) == 2
    assert test_nodes[0].id != test_nodes[1].id
    assert [
        (e.target, e.kind)
        for e in cfg.successors(test_nodes[0].id)
        if e.kind is EdgeKind.TRUE
    ] == [("MAIN/0.at_end.0", EdgeKind.TRUE)]
    assert [
        (e.target, e.kind)
        for e in cfg.successors(test_nodes[1].id)
        if e.kind is EdgeKind.TRUE
    ] == [("MAIN/0.invalid_key.0", EdgeKind.TRUE)]


def test_a_search_with_at_end_but_no_whens_emits_an_unresolved_test(
    program_of,
) -> None:
    """When WHENs are missing but AT END is present, the search outcome is unknown
    so the test is unresolved, AT END is on FALSE, and TRUE falls through."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "SEARCH",
                "table": "WS-TABLE",
                "at_end": [_move("'Z'", "WS-RESULT")],
            }
        ],
    )

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert test_node.atom.resolved is False
    assert [e.kind for e in cfg.predecessors("MAIN/0.at_end.0")] == [EdgeKind.FALSE]


def test_a_search_without_at_end_exits_through_the_last_whens_false_edge(
    program_of,
) -> None:
    """A search that finds nothing is the runtime-common case."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "SEARCH",
                "table": "WS-TABLE",
                "whens": [
                    {"condition": "A = B", "children": [_move("'F'", "WS-RESULT")]}
                ],
            },
            _move("'DONE'", "WS-RESULT"),
        ],
    )

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert [
        (e.target, e.kind)
        for e in cfg.successors(test_node.id)
        if e.kind is EdgeKind.FALSE
    ] == [("MAIN/1", EdgeKind.FALSE)]


def test_a_statement_with_only_not_at_end_still_builds_the_guard(program_of) -> None:
    """The corpus has exactly one such statement, so this is a real shape."""
    cfg = _cfg(
        program_of,
        [
            {
                "type": "READ",
                "file_name": "CUST-FILE",
                "not_at_end": [_move("'N'", "WS-EOF")],
            }
        ],
        **_FILE_CONTROL,
    )

    test_node = next(n for n in cfg.nodes if n.kind == NodeKind.TEST)
    assert test_node.atom.right == "AT END"
    assert [
        (e.target, e.kind)
        for e in cfg.successors(test_node.id)
        if e.kind is EdgeKind.FALSE
    ] == [("MAIN/0.not_at_end.0", EdgeKind.FALSE)]
