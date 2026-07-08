"""Tests for IDCAMS modal commands (comprehensive grammar): IF/THEN/ELSE/
DO/END, SET, CANCEL.

Architecturally different from every other command tested in this plan --
IF is genuine recursive control flow (THEN/ELSE can hold a single command,
nothing, or a DO...END block of commands, and a THEN/ELSE clause can itself
be another IF, up to 10 levels deep per the IBM manual), not another flat
parameter list.

Both nested-IF examples below are transcribed (with concrete commands
substituted for the manual's "REPRO...", "DELETE...", "PRINT..." elisions)
from the manual's own Chapter 2 modal-command examples -- not synthetic
toy cases.

Depth-cap test: the 11-level-deep IF construction below is asserted to
raise `ValueError` -- that is the exception type
`ComprehensiveIdcamsTransformer._build_if` raises when the computed
nesting depth of the IfCommand being built exceeds the manual's documented
maximum of 10 levels (jackal/jackal/idcams/parser_comprehensive.py's
_if_nesting_depth/_build_if). This is a semantic/business-rule check
performed in the transformer, not a grammar-level (LarkError) rejection --
Earley parses arbitrarily deep IF nesting without complaint, per
ast_modal.py's IfCommand docstring.
"""

from __future__ import annotations

import pytest

from jackal.idcams.ast_delete import Delete
from jackal.idcams.ast_modal import CancelCommand, IfCommand, SetCommand
from jackal.idcams.ast_print import Print
from jackal.idcams.ast_repro import Repro
from jackal.idcams.ast_values import Name
from jackal.idcams.parser_comprehensive import parse_ams
from tests.covers import NotLanguageFeature, covers

# =========================================================================
# SET
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_set_maxcc():
    cmds = parse_ams("SET MAXCC=8\n")
    assert cmds[0] == SetCommand(field="MAXCC", value=8)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_set_lastcc():
    cmds = parse_ams("SET LASTCC=16\n")
    assert cmds[0] == SetCommand(field="LASTCC", value=16)


# =========================================================================
# CANCEL
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cancel_bare():
    cmds = parse_ams("CANCEL\n")
    assert cmds[0] == CancelCommand()


# =========================================================================
# IF: simple single-command THEN/ELSE, both branches present
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_simple_then_else_single_commands():
    cmds = parse_ams("IF LASTCC = 0 THEN CANCEL ELSE SET MAXCC=4\n")
    assert cmds[0] == IfCommand(
        field="LASTCC",
        op="EQ",
        value=0,
        then=(CancelCommand(),),
        else_=(SetCommand(field="MAXCC", value=4),),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_operator_spellings_normalize():
    """Every one of the six documented operator spellings (bare "=" and its
    "EQ" alias; "GT"; "LT"; "GE"; "LE"; and "NE") normalizes to one of the
    six canonical two-letter forms in IfCommand.op."""
    assert parse_ams("IF LASTCC = 4 THEN CANCEL\n")[0].op == "EQ"
    assert parse_ams("IF LASTCC EQ 4 THEN CANCEL\n")[0].op == "EQ"
    assert parse_ams("IF LASTCC NE 4 THEN CANCEL\n")[0].op == "NE"
    assert parse_ams("IF LASTCC GT 4 THEN CANCEL\n")[0].op == "GT"
    assert parse_ams("IF LASTCC LT 4 THEN CANCEL\n")[0].op == "LT"
    assert parse_ams("IF LASTCC GE 4 THEN CANCEL\n")[0].op == "GE"
    assert parse_ams("IF LASTCC LE 4 THEN CANCEL\n")[0].op == "LE"
    assert parse_ams("IF LASTCC > 4 THEN CANCEL\n")[0].op == "GT"
    assert parse_ams("IF LASTCC < 4 THEN CANCEL\n")[0].op == "LT"
    assert parse_ams("IF LASTCC >= 4 THEN CANCEL\n")[0].op == "GE"
    assert parse_ams("IF LASTCC <= 4 THEN CANCEL\n")[0].op == "LE"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_not_equal_symbol_spelling():
    """The IBM manual's own "not equal" symbol is the logical-NOT character
    (¬=), distinct from the ASCII-safe "NE" spelling most real JCL uses --
    both must normalize to the same canonical "NE"."""
    cmds = parse_ams("IF LASTCC ¬= 4 THEN CANCEL\n")
    assert cmds[0].op == "NE"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_maxcc_field():
    cmds = parse_ams("IF MAXCC = 0 THEN CANCEL\n")
    assert cmds[0].field == "MAXCC"


# =========================================================================
# IF: null THEN / null ELSE
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_null_then():
    """Bare THEN followed immediately by ELSE -- a syntactically valid
    "no action" clause, per the manual's own worked examples."""
    cmds = parse_ams("IF LASTCC = 4 THEN ELSE CANCEL\n")
    assert cmds[0] == IfCommand(
        field="LASTCC", op="EQ", value=4, then=(), else_=(CancelCommand(),)
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_null_else():
    """Bare ELSE followed by nothing -- an ELSE clause WAS written, but
    it's null. Distinct from omitting ELSE entirely (see
    test_if_no_else_clause_at_all below): then=(), else_=() here, not
    else_=None."""
    cmds = parse_ams("IF LASTCC = 4 THEN CANCEL ELSE\n")
    assert cmds[0] == IfCommand(
        field="LASTCC", op="EQ", value=4, then=(CancelCommand(),), else_=()
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_no_else_clause_at_all():
    """No ELSE keyword at all -- else_ must be None, not an empty tuple.
    This is the load-bearing distinction the design spec calls out
    explicitly: None means "no ELSE clause was written"; () means "an
    ELSE clause was written but it's null"."""
    cmds = parse_ams("IF LASTCC = 4 THEN CANCEL\n")
    assert cmds[0] == IfCommand(
        field="LASTCC", op="EQ", value=4, then=(CancelCommand(),), else_=None
    )


# =========================================================================
# IF: DO/END block with 2+ commands under one THEN
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_do_end_block_multiple_commands():
    cmds = parse_ams("IF LASTCC = 0 THEN DO CANCEL SET MAXCC=4 SET LASTCC=8 END\n")
    assert cmds[0] == IfCommand(
        field="LASTCC",
        op="EQ",
        value=0,
        then=(
            CancelCommand(),
            SetCommand(field="MAXCC", value=4),
            SetCommand(field="LASTCC", value=8),
        ),
    )


# =========================================================================
# IF: manual's own worked nested-IF examples, transcribed verbatim
# (concrete commands substituted for "REPRO...", "DELETE...", "PRINT...")
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_manual_example_one_nested_if_with_null_then():
    """
    IF LASTCC > 4  -
      THEN IF MAXCC < 12  -
        THEN REPRO...
        ELSE DELETE...
      ELSE IF LASTCC = 4  -
        THEN
        ELSE PRINT...

    The inner "THEN" right before "ELSE IF LASTCC = 4" is a null THEN --
    no command follows it before the ELSE.
    """
    text = (
        "IF LASTCC > 4 -\n"
        "  THEN IF MAXCC < 12 -\n"
        "    THEN REPRO INFILE(INDD) OUTFILE(OUTDD) -\n"
        "    ELSE DELETE (MY.CLUSTER) -\n"
        "  ELSE IF LASTCC = 4 -\n"
        "    THEN -\n"
        "    ELSE PRINT INFILE(PRDD)\n"
    )
    cmds = parse_ams(text)
    assert cmds[0] == IfCommand(
        field="LASTCC",
        op="GT",
        value=4,
        then=(
            IfCommand(
                field="MAXCC",
                op="LT",
                value=12,
                then=(Repro(infile="INDD", outfile="OUTDD"),),
                else_=(Delete(entries=(Name.parse("MY.CLUSTER"),)),),
            ),
        ),
        else_=(
            IfCommand(
                field="LASTCC",
                op="EQ",
                value=4,
                then=(),
                else_=(Print(infile="PRDD"),),
            ),
        ),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_manual_example_two_nested_if_with_null_else_and_no_outer_else():
    """
    IF LASTCC > 4  -
      THEN IF MAXCC < 12  -
        THEN REPRO ...
        ELSE
      ELSE IF LASTCC = 4  -
        THEN PRINT ...

    This example has a null ELSE after "MAXCC < 12"'s THEN (else_=()), and
    the OUTER IF has no ELSE clause at all (else_=None on the inner
    "LASTCC = 4" IfCommand) -- the load-bearing None-vs-() distinction.
    """
    text = (
        "IF LASTCC > 4 -\n"
        "  THEN IF MAXCC < 12 -\n"
        "    THEN REPRO INFILE(INDD) OUTFILE(OUTDD) -\n"
        "    ELSE -\n"
        "  ELSE IF LASTCC = 4 -\n"
        "    THEN PRINT INFILE(PRDD)\n"
    )
    cmds = parse_ams(text)
    assert cmds[0] == IfCommand(
        field="LASTCC",
        op="GT",
        value=4,
        then=(
            IfCommand(
                field="MAXCC",
                op="LT",
                value=12,
                then=(Repro(infile="INDD", outfile="OUTDD"),),
                else_=(),
            ),
        ),
        else_=(
            IfCommand(
                field="LASTCC",
                op="EQ",
                value=4,
                then=(Print(infile="PRDD"),),
                else_=None,
            ),
        ),
    )


# =========================================================================
# IF: nesting depth cap (max 10 levels per the manual)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_nesting_exactly_ten_levels_allowed():
    text = "IF LASTCC = 0 THEN " * 10 + "CANCEL\n"
    cmds = parse_ams(text)
    depth = 0
    node = cmds[0]
    while isinstance(node, IfCommand):
        depth += 1
        node = node.then[0]
    assert depth == 10


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_nesting_eleven_levels_rejected():
    """11 levels of nested IF exceeds the manual's documented maximum of
    10 -- rejected with a ValueError raised by the transformer's depth
    check (parser_comprehensive.py's _build_if), not a LarkError from the
    grammar itself (see this file's module docstring)."""
    text = "IF LASTCC = 0 THEN " * 11 + "CANCEL\n"
    with pytest.raises(ValueError):
        parse_ams(text)
