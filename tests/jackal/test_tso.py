"""Reading a TSO monitor step's SYSTSIN for the program it actually runs."""

from __future__ import annotations

from cobble.jackal.tso import TsoRun, is_tso_monitor, tso_runs


def test_the_dsn_run_subcommand_names_the_program_and_its_plan() -> None:
    assert tso_runs(
        (
            "  DSN SYSTEM(DSN)",
            "  RUN PROGRAM(PAYROLL) PLAN(PAYPLAN)",
            "  END",
        )
    ) == (TsoRun(program="PAYROLL", plan="PAYPLAN"),)


def test_a_run_without_a_plan_is_still_a_run() -> None:
    """PLAN is optional -- DB2 takes the plan from the program name. An absent
    plan is "" rather than a refusal to read the program."""
    assert tso_runs(("  RUN PROGRAM(PAYROLL)",)) == (
        TsoRun(program="PAYROLL", plan=""),
    )


def test_the_lines_arrive_blank_padded_to_the_card() -> None:
    """In-stream data comes through with the card's trailing blanks intact, so
    the continuation character is not the last character of the raw line."""
    assert tso_runs(
        (
            "  RUN PROGRAM(PAYROLL) PLAN(PAYPLAN) -" + " " * 30,
            "      LIB('BATCH.LOADLIB')" + " " * 40,
        )
    ) == (TsoRun(program="PAYROLL", plan="PAYPLAN"),)


def test_a_hyphen_continuation_splitting_the_subcommand_still_reads() -> None:
    """The operand text is contiguous across the join, so RUN and its PROGRAM
    keyword may sit on different cards."""
    assert tso_runs(
        (
            "  RUN -",
            "     PROGRAM(PAYROLL) -",
            "     PLAN(PAYPLAN)",
        )
    ) == (TsoRun(program="PAYROLL", plan="PAYPLAN"),)


def test_a_plus_continuation_removes_the_next_cards_leading_blanks() -> None:
    """Which is the whole difference between + and -, and it matters here only
    in that the joined text has to stay one token where TSO makes it one."""
    assert tso_runs(
        (
            "  RUN PROGRAM(PAY+",
            "                 ROLL)",
        )
    ) == (TsoRun(program="PAYROLL", plan=""),)


def test_the_program_keyword_abbreviates_to_prog() -> None:
    assert tso_runs(("  RUN PROG(PAYROLL) PLAN(PAYPLAN)",)) == (
        TsoRun(program="PAYROLL", plan="PAYPLAN"),
    )


def test_tso_reads_commands_without_regard_to_case() -> None:
    """Lower case is legal in SYSTSIN. The names it yields are uppercased,
    because node identity in the graph is uppercase everywhere."""
    assert tso_runs(("  run program(payroll) plan(payplan)",)) == (
        TsoRun(program="PAYROLL", plan="PAYPLAN"),
    )


def test_every_run_in_one_stream_is_read_in_order() -> None:
    """One SYSTSIN may drive several programs in sequence."""
    assert tso_runs(
        (
            "  DSN SYSTEM(DSN)",
            "  RUN PROGRAM(EXTRACT) PLAN(EXTPLAN)",
            "  RUN PROGRAM(REPORT) PLAN(RPTPLAN)",
            "  END",
        )
    ) == (
        TsoRun(program="EXTRACT", plan="EXTPLAN"),
        TsoRun(program="REPORT", plan="RPTPLAN"),
    )


def test_a_repeated_program_is_repeated_here() -> None:
    """Collapsing repeats is the graph's decision, not this function's."""
    assert tso_runs(
        (
            "  RUN PROGRAM(PAYROLL) PLAN(PLANA)",
            "  RUN PROGRAM(PAYROLL) PLAN(PLANB)",
        )
    ) == (
        TsoRun(program="PAYROLL", plan="PLANA"),
        TsoRun(program="PAYROLL", plan="PLANB"),
    )


def test_a_stream_that_runs_nothing_yields_nothing() -> None:
    """Most SYSTSIN streams are not DSN at all -- DELETE, ALLOC, a REXX exec."""
    assert (
        tso_runs(
            (
                "  DELETE 'BATCH.WORK.FILE'",
                "  ALLOC FI(REPORT) DA('BATCH.REPORT') SHR",
            )
        )
        == ()
    )


def test_an_empty_stream_yields_nothing() -> None:
    assert tso_runs(()) == ()


def test_blank_cards_do_not_confuse_the_fold() -> None:
    assert tso_runs(
        (
            "",
            "  RUN PROGRAM(PAYROLL) PLAN(PAYPLAN)",
            "   ",
        )
    ) == (TsoRun(program="PAYROLL", plan="PAYPLAN"),)


def test_run_naming_something_other_than_a_program_is_not_a_run() -> None:
    """DSN's RUN takes PROGRAM or PROC. A RUN PROC(...) runs a stored
    procedure, which is no load module and no node this graph has."""
    assert tso_runs(("  RUN PROC(SOMEPROC) PLAN(APLAN)",)) == ()


def test_each_monitor_entry_point_is_a_monitor() -> None:
    """One monitor, three entry points differing only in what they pass back
    to the step -- the SYSTSIN they read is the same."""
    assert [is_tso_monitor(pgm) for pgm in ("IKJEFT01", "IKJEFT1A", "IKJEFT1B")] == [
        True,
        True,
        True,
    ]


def test_a_program_that_is_not_the_monitor_is_not_the_monitor() -> None:
    assert [is_tso_monitor(pgm) for pgm in ("IEFBR14", "IDCAMS", "PAYROLL")] == [
        False,
        False,
        False,
    ]


def test_an_exec_proc_step_carries_no_program_and_is_not_the_monitor() -> None:
    """A step written EXEC PROC= has an empty pgm, and asking about it must be
    a plain no rather than an AttributeError halfway through a corpus run."""
    assert is_tso_monitor("") is False
