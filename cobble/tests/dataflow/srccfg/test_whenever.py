from collections.abc import Sequence

from cobble.cics.asg_dialect_scope import asg_dialect_parsers_registered
from cobble.dataflow.srccfg.whenever import governing_directives
from cobol_asg.asg_types import CobolASG
from squall.statements import WheneverCondition

NOT_FOUND = WheneverCondition.NOT_FOUND
SQLERROR = WheneverCondition.SQLERROR


def _sql(text: str) -> dict:
    return {"type": "EXEC_SQL", "text": f"EXEC SQL {text} END-EXEC"}


def _asg(paragraphs: Sequence[dict]) -> CobolASG:
    with asg_dialect_parsers_registered():
        return CobolASG.from_dict(
            {"program_id": "P", "data_fields": [], "paragraphs": list(paragraphs)}
        )


def _para(name: str, statements: Sequence[dict]) -> dict:
    return {"name": name, "statements": list(statements)}


def test_a_directive_governs_what_follows_it_textually_and_nothing_before() -> None:
    """ "Must precede the first SQL statement it affects" -- a statement ahead of
    the directive is not governed, and the directive itself never appears."""
    asg = _asg(
        [
            _para(
                "MAIN",
                [
                    _sql("SELECT A INTO :B FROM T"),
                    _sql("WHENEVER NOT FOUND GO TO H"),
                    _sql("SELECT C INTO :D FROM U"),
                ],
            )
        ]
    )

    assert governing_directives(asg) == {
        "MAIN/0": (),
        "MAIN/2": ((NOT_FOUND, "H"),),
    }


def test_a_directive_a_branch_skips_still_governs_what_follows_it() -> None:
    """The precompiler applies WHENEVER in source order, so a directive nested in
    an IF body governs every later statement whether or not that branch runs.
    Reaching definitions over the CFG would answer "not armed" on the else path;
    Db2 says armed. This is why the scope pass is a source-order scan."""
    asg = _asg(
        [
            _para(
                "MAIN",
                [
                    {
                        "type": "IF",
                        "condition": {
                            "not": False,
                            "relation": {
                                "left": {"kind": "ref", "name": "X"},
                                "op": "=",
                                "right": {"kind": "lit", "value": "1"},
                            },
                        },
                        "children": [_sql("WHENEVER SQLERROR GO TO ERR")],
                    },
                    _sql("SELECT A INTO :B FROM T"),
                ],
            )
        ]
    )

    assert governing_directives(asg) == {"MAIN/1": ((SQLERROR, "ERR"),)}


def test_continue_clears_a_condition_a_later_statement_would_have_inherited() -> None:
    asg = _asg(
        [
            _para("A", [_sql("WHENEVER NOT FOUND GO TO H"), _sql("SELECT A FROM T")]),
            _para("B", [_sql("WHENEVER NOT FOUND CONTINUE"), _sql("SELECT C FROM U")]),
        ]
    )

    assert governing_directives(asg) == {
        "A/1": ((NOT_FOUND, "H"),),
        "B/1": (),
    }


def _cfg(paragraphs: Sequence[dict]):
    from cobble.dataflow.srccfg.build import build_program

    return build_program(_asg(paragraphs))


def test_a_governed_statement_branches_to_each_handler_and_the_directive_vanishes() -> (
    None
):
    """The directives contribute no node -- they emit no runtime code -- and the
    statement they govern gets one SQLCODE test per condition, the failing arm
    falling into the next and the last falling through."""
    cfg = _cfg(
        [
            _para(
                "MAIN",
                [
                    _sql("WHENEVER NOT FOUND GO TO NF"),
                    _sql("WHENEVER SQLERROR GO TO ERR"),
                    _sql("SELECT A INTO :B FROM T"),
                    {"type": "STOP_RUN"},
                ],
            ),
            _para("NF", [{"type": "STOP_RUN"}]),
            _para("ERR", [{"type": "STOP_RUN"}]),
        ]
    )
    ids = [n.id for n in cfg.nodes if n.id.startswith("MAIN/")]
    edges = {(e.source, e.target) for e in cfg.edges}

    assert ids == [
        "MAIN/2",
        "MAIN/2.sql0#test",
        "MAIN/2.sql0#whenever",
        "MAIN/2.sql1#test",
        "MAIN/2.sql1#whenever",
        "MAIN/3",
    ]
    assert ("MAIN/2.sql0#whenever", "NF#label") in edges
    assert ("MAIN/2.sql1#whenever", "ERR#label") in edges
    assert ("MAIN/2.sql0#test", "MAIN/2.sql1#test") in edges
    assert ("MAIN/2.sql1#test", "MAIN/3") in edges


def test_the_sqlcode_each_condition_tests_is_the_one_db2_defines() -> None:
    cfg = _cfg(
        [
            _para(
                "MAIN",
                [
                    _sql("WHENEVER NOT FOUND GO TO H"),
                    _sql("WHENEVER SQLERROR GO TO H"),
                    _sql("WHENEVER SQLWARNING GO TO H"),
                    _sql("SELECT A INTO :B FROM T"),
                ],
            ),
            _para("H", [{"type": "STOP_RUN"}]),
        ]
    )

    assert [n.atom.text for n in cfg.nodes if "#test" in n.id] == [
        "SQLCODE = 100",
        "SQLCODE < 0",
        "SQLWARN0 = 'W'",
        "SQLCODE > 0",
        "SQLCODE <> 100",
    ]


def test_each_exec_sql_node_is_labelled_with_its_own_verb() -> None:
    """Uniform EXECSQL told a reader nothing -- a directive, a cursor OPEN and a
    SELECT were indistinguishable. GENERIC keeps EXECSQL, because inventing a
    verb for text the parser could not classify would be worse than saying so."""
    cfg = _cfg(
        [
            _para(
                "MAIN",
                [
                    _sql("DECLARE C1 CURSOR FOR SELECT A FROM T"),
                    _sql("OPEN C1"),
                    _sql("FETCH C1 INTO :B"),
                    _sql("SELECT A INTO :B FROM T"),
                    _sql("UPDATE T SET A = 1"),
                    _sql("COMMIT"),
                    _sql("NOT ACTUALLY SQL"),
                ],
            )
        ]
    )

    assert [n.transfer for n in cfg.nodes if n.id.startswith("MAIN/")] == [
        "DECLARE CURSOR",
        "OPEN",
        "FETCH",
        "SELECT INTO",
        "UPDATE",
        "COMMIT",
        "EXECSQL",
    ]


def test_a_directive_db2_does_not_define_still_emits_no_node_and_no_edge() -> None:
    """The grammar admits conditions and actions Db2 does not define. None of
    them may reach the CFG as a jump: reading `DO HANDLER()` as a GO TO once
    produced an edge to a paragraph named ')'. They are directives all the same,
    so they contribute no node either."""
    cfg = _cfg(
        [
            _para(
                "MAIN",
                [
                    _sql("WHENEVER MYCOND GO TO H"),
                    _sql("WHENEVER SQLERROR DO HANDLER()"),
                    _sql("WHENEVER NOT FOUND STOP"),
                    _sql("SELECT A INTO :B FROM T"),
                ],
            ),
            _para("H", [{"type": "STOP_RUN"}]),
        ]
    )

    assert [n.id for n in cfg.nodes if n.id.startswith("MAIN/")] == ["MAIN/3"]
    assert [e.target for e in cfg.edges if "whenever" in e.source] == []
