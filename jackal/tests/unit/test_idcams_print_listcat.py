"""Tests for IDCAMS PRINT and LISTCAT parsing into the comprehensive AST.

Covers every parameter listed in the design spec's Print and Listcat
sections (2026-07-08-idcams-comprehensive-grammar-design.md).

PRINT reuses REPRO's RangeStart/RangeEnd dataclasses and grammar rules
(fromkey_param/.../count_param, insertshift_param/insertall_param,
skipdbcscheck_param/nodbcscheck_param, repro_cimode_param/repro_dbcs_param,
file_param, rlssource_param) verbatim -- see ast_print.py and ams.lark's
PRINT section comment. PRINT's own "pick one" groups (INFILE/INDATASET,
required; CHARACTER/DUMP/HEX, optional; the reused RangeStart/RangeEnd
4-ways; INSERTSHIFT/INSERTALL; SKIPDBCSCHECK/NODBCSCHECK) follow the same
flat-grammar/transformer-enforced pattern ratified in Task 7 (see
ComprehensiveIdcamsTransformer.repro()) -- order-independence for
INFILE/INDATASET is tested explicitly below to prove the pattern was
applied from the start, not bolted on after a review finding (as happened
in Task 7).

LISTCAT's ENTRIES/LEVEL is its sole mutual-exclusivity group (reusing
REPRO's entries_param/level_param rules); entry_types (ALIAS/CLUSTER/...)
is explicitly NOT a choice group -- multiple entry-type filters may combine
freely, per the manual.

CDILVL/NOCDILVL: the manual documents CDILVL as only meaningful alongside
LEVEL, but this grammar does not enforce that coupling -- it accepts
CDILVL/NOCDILVL standalone (deferring the "only valid alongside LEVEL"
semantic rule to a later execution/validation layer, consistent with this
module's parsing-only scope, same rationale as PRINT's format default and
Listcat's detail default above).
"""

from __future__ import annotations

import pytest

from jackal.idcams.ast_listcat import Listcat
from jackal.idcams.ast_print import Print
from jackal.idcams.ast_repro import RangeEnd, RangeStart
from jackal.idcams.ast_values import Name, QuotedString
from jackal.idcams.parser_comprehensive import parse_ams
from tests.covers import NotLanguageFeature, covers

# =========================================================================
# PRINT: INFILE/INDATASET (required, exactly one)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_infile():
    cmds = parse_ams("PRINT INFILE(INDD)\n")
    assert cmds[0] == Print(infile="INDD")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_indataset():
    cmds = parse_ams("PRINT INDATASET(MY.IN)\n")
    assert cmds[0] == Print(indataset=Name.parse("MY.IN"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_infile_indataset_together_raises():
    with pytest.raises(ValueError):
        parse_ams("PRINT INFILE(INDD) INDATASET(MY.IN)\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_missing_source_raises():
    with pytest.raises(ValueError):
        parse_ams("PRINT CHARACTER\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_outfile_before_infile_order_independent():
    """OUTFILE (an ordinary param) placed before INFILE (the required
    source choice) -- proves print_param is a flat, freely-repeatable list
    like REPRO's, not a fixed-order chain, from the start."""
    cmds = parse_ams("PRINT OUTFILE(OUTDD) INFILE(INDD)\n")
    assert cmds[0] == Print(infile="INDD", outfile="OUTDD")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_character_before_indataset_order_independent():
    """CHARACTER (an optional choice-group member) placed before INDATASET
    (the required source choice) -- another pure-reordering case."""
    cmds = parse_ams("PRINT CHARACTER INDATASET(MY.IN)\n")
    assert cmds[0] == Print(indataset=Name.parse("MY.IN"), format="CHARACTER")


# =========================================================================
# PRINT: CHARACTER/DUMP/HEX (optional 3-way, left None when absent)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_character():
    cmds = parse_ams("PRINT INFILE(INDD) CHARACTER\n")
    assert cmds[0].format == "CHARACTER"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_dump():
    cmds = parse_ams("PRINT INFILE(INDD) DUMP\n")
    assert cmds[0].format == "DUMP"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_hex():
    cmds = parse_ams("PRINT INFILE(INDD) HEX\n")
    assert cmds[0].format == "HEX"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_no_format_defaults_to_none():
    """Left None, not defaulted to DUMP -- this module is parsing-only; a
    future execution layer applies the manual's documented default."""
    cmds = parse_ams("PRINT INFILE(INDD)\n")
    assert cmds[0].format is None


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_character_dump_together_raises():
    with pytest.raises(ValueError):
        parse_ams("PRINT INFILE(INDD) CHARACTER DUMP\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_dump_hex_together_raises():
    with pytest.raises(ValueError):
        parse_ams("PRINT INFILE(INDD) DUMP HEX\n")


# =========================================================================
# PRINT: RangeStart/RangeEnd (reused from REPRO)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_fromkey_tokey():
    cmds = parse_ams("PRINT INFILE(INDD) FROMKEY('KEY001') TOKEY('KEY999')\n")
    assert cmds[0].range_start == RangeStart(
        kind="FROMKEY", value=QuotedString(text="KEY001")
    )
    assert cmds[0].range_end == RangeEnd(
        kind="TOKEY", value=QuotedString(text="KEY999")
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_fromnumber_count():
    cmds = parse_ams("PRINT INFILE(INDD) FROMNUMBER(5) COUNT(10)\n")
    assert cmds[0].range_start == RangeStart(kind="FROMNUMBER", value=5)
    assert cmds[0].range_end == RangeEnd(kind="COUNT", value=10)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_fromkey_fromaddress_together_raises():
    with pytest.raises(ValueError):
        parse_ams("PRINT INFILE(INDD) FROMKEY('K') FROMADDRESS(100)\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_tokey_toaddress_together_raises():
    with pytest.raises(ValueError):
        parse_ams("PRINT INFILE(INDD) TOKEY('K') TOADDRESS(100)\n")


# =========================================================================
# PRINT: DBCS + INSERTSHIFT/INSERTALL
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_dbcs():
    cmds = parse_ams("PRINT INFILE(INDD) DBCS\n")
    assert cmds[0].dbcs is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_insertshift():
    cmds = parse_ams("PRINT INFILE(INDD) INSERTSHIFT((10 2))\n")
    assert cmds[0].insert_shift == ((10, 2),)
    assert cmds[0].insert_all is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_insertall():
    cmds = parse_ams("PRINT INFILE(INDD) INSERTALL\n")
    assert cmds[0].insert_all is True
    assert cmds[0].insert_shift == ()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_insertshift_insertall_together_raises():
    with pytest.raises(ValueError):
        parse_ams("PRINT INFILE(INDD) INSERTSHIFT((10 2)) INSERTALL\n")


# =========================================================================
# Step 6: remaining PRINT parameters
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_cimode():
    cmds = parse_ams("PRINT INFILE(INDD) CIMODE\n")
    assert cmds[0].cimode is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_nocimode():
    cmds = parse_ams("PRINT INFILE(INDD) NOCIMODE\n")
    assert cmds[0].cimode is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_skipdbcscheck():
    cmds = parse_ams("PRINT INFILE(INDD) SKIPDBCSCHECK((5 1))\n")
    assert cmds[0].skip_dbcs_check == ((5, 1),)
    assert cmds[0].no_dbcs_check is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_nodbcscheck():
    cmds = parse_ams("PRINT INFILE(INDD) NODBCSCHECK\n")
    assert cmds[0].no_dbcs_check is True
    assert cmds[0].skip_dbcs_check == ()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_skipdbcscheck_nodbcscheck_together_raises():
    with pytest.raises(ValueError):
        parse_ams("PRINT INFILE(INDD) SKIPDBCSCHECK((5 1)) NODBCSCHECK\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_outfile():
    cmds = parse_ams("PRINT INFILE(INDD) OUTFILE(OUTDD)\n")
    assert cmds[0].outfile == "OUTDD"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_rlssource():
    cmds = parse_ams("PRINT INFILE(INDD) RLSSOURCE(YES)\n")
    assert cmds[0].rls_source == "YES"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_print_full():
    cmds = parse_ams(
        "PRINT INFILE(INDD) OUTFILE(OUTDD) -\n"
        "  DUMP CIMODE DBCS RLSSOURCE(QUIESCE) -\n"
        "  FROMNUMBER(5) TONUMBER(50) INSERTALL SKIPDBCSCHECK((5 1))\n"
    )
    assert cmds[0] == Print(
        infile="INDD",
        outfile="OUTDD",
        format="DUMP",
        cimode=True,
        dbcs=True,
        rls_source="QUIESCE",
        range_start=RangeStart(kind="FROMNUMBER", value=5),
        range_end=RangeEnd(kind="TONUMBER", value=50),
        insert_all=True,
        skip_dbcs_check=((5, 1),),
    )


# =========================================================================
# LISTCAT: no-operand case (all defaults)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_no_operands():
    cmds = parse_ams("LISTCAT\n")
    assert cmds[0] == Listcat()


# =========================================================================
# LISTCAT: entry_types -- NOT a mutual-exclusivity group
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_single_entry_type():
    cmds = parse_ams("LISTCAT CLUSTER\n")
    assert cmds[0].entry_types == ("CLUSTER",)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_multiple_entry_types_combine():
    """The manual allows combining multiple entry-type filters in one
    LISTCAT -- this must NOT raise, unlike REPRO/PRINT's genuine 'pick one'
    groups."""
    cmds = parse_ams("LISTCAT ALIAS CLUSTER\n")
    assert cmds[0].entry_types == ("ALIAS", "CLUSTER")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_all_entry_types():
    cmds = parse_ams(
        "LISTCAT ALIAS ALTERNATEINDEX CLUSTER DATA -\n"
        "  GENERATIONDATAGROUP INDEX NONVSAM PAGESPACE PATH USERCATALOG\n"
    )
    assert cmds[0].entry_types == (
        "ALIAS",
        "ALTERNATEINDEX",
        "CLUSTER",
        "DATA",
        "GENERATIONDATAGROUP",
        "INDEX",
        "NONVSAM",
        "PAGESPACE",
        "PATH",
        "USERCATALOG",
    )


# =========================================================================
# LISTCAT: ENTRIES/LEVEL mutual exclusivity
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_entries():
    cmds = parse_ams("LISTCAT ENTRIES(A B)\n")
    assert cmds[0].entries == (Name.parse("A"), Name.parse("B"))
    assert cmds[0].level is None


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_level():
    cmds = parse_ams("LISTCAT LEVEL(PROD)\n")
    assert cmds[0].level == "PROD"
    assert cmds[0].entries == ()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_entries_level_together_raises():
    with pytest.raises(ValueError):
        parse_ams("LISTCAT ENTRIES(A) LEVEL(PROD)\n")


# =========================================================================
# LISTCAT: detail level -- NAME/HISTORY/VOLUME/ALLOCATION/ALL
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_detail_name():
    cmds = parse_ams("LISTCAT NAME\n")
    assert cmds[0].detail == "NAME"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_detail_history():
    cmds = parse_ams("LISTCAT HISTORY\n")
    assert cmds[0].detail == "HISTORY"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_detail_volume():
    cmds = parse_ams("LISTCAT VOLUME\n")
    assert cmds[0].detail == "VOLUME"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_detail_allocation():
    cmds = parse_ams("LISTCAT ALLOCATION\n")
    assert cmds[0].detail == "ALLOCATION"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_detail_all():
    cmds = parse_ams("LISTCAT ALL\n")
    assert cmds[0].detail == "ALL"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_no_detail_defaults_to_none():
    """Left None, not defaulted to NAME -- see ast_listcat.py's module
    docstring for the rationale (consistency with Print.format)."""
    cmds = parse_ams("LISTCAT\n")
    assert cmds[0].detail is None


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_name_history_together_raises():
    with pytest.raises(ValueError):
        parse_ams("LISTCAT NAME HISTORY\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_volume_all_together_raises():
    with pytest.raises(ValueError):
        parse_ams("LISTCAT VOLUME ALL\n")


# =========================================================================
# LISTCAT: CDILVL/NOCDILVL (grammar does not enforce LEVEL coupling)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_cdilvl_with_level():
    cmds = parse_ams("LISTCAT LEVEL(PROD) CDILVL\n")
    assert cmds[0].cdilvl is True
    assert cmds[0].level == "PROD"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_nocdilvl_with_level():
    cmds = parse_ams("LISTCAT LEVEL(PROD) NOCDILVL\n")
    assert cmds[0].cdilvl is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_cdilvl_standalone_is_accepted_by_grammar():
    """Documented decision: the manual says CDILVL is only meaningful
    alongside LEVEL, but this parsing-only grammar does not enforce that
    coupling -- it's deferred to a later semantic/execution layer. This
    test pins down that the grammar accepts CDILVL standalone rather than
    silently changing behavior later."""
    cmds = parse_ams("LISTCAT CDILVL\n")
    assert cmds[0].cdilvl is True
    assert cmds[0].level is None


# =========================================================================
# Step 6: remaining LISTCAT parameters
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_libraryentries():
    cmds = parse_ams("LISTCAT LIBRARYENTRIES(MYLIB)\n")
    assert cmds[0].library_entries == "MYLIB"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_volumeentries():
    cmds = parse_ams("LISTCAT VOLUMEENTRIES(PROD)\n")
    assert cmds[0].volume_entries == "PROD"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_catalog():
    cmds = parse_ams("LISTCAT CATALOG(MYCAT)\n")
    assert cmds[0].catalog == "MYCAT"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_creation():
    cmds = parse_ams("LISTCAT CREATION(30)\n")
    assert cmds[0].creation_days == 30


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_expiration():
    cmds = parse_ams("LISTCAT EXPIRATION(90)\n")
    assert cmds[0].expiration_days == 90


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_prefix():
    cmds = parse_ams("LISTCAT PREFIX\n")
    assert cmds[0].prefix is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_noprefix():
    cmds = parse_ams("LISTCAT NOPREFIX\n")
    assert cmds[0].prefix is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_file():
    cmds = parse_ams("LISTCAT FILE(MYDD)\n")
    assert cmds[0].file == "MYDD"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_library():
    cmds = parse_ams("LISTCAT LIBRARY(MYLIB)\n")
    assert cmds[0].library == "MYLIB"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_outfile():
    cmds = parse_ams("LISTCAT OUTFILE(OUTDD)\n")
    assert cmds[0].outfile == "OUTDD"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_full():
    cmds = parse_ams(
        "LISTCAT ALIAS CLUSTER LIBRARYENTRIES(MYLIB) VOLUMEENTRIES(PROD) -\n"
        "  CATALOG(MYCAT) CREATION(30) EXPIRATION(90) LEVEL(PROD) -\n"
        "  NOCDILVL PREFIX ALL FILE(MYDD) LIBRARY(MYLIB2) OUTFILE(OUTDD)\n"
    )
    assert cmds[0] == Listcat(
        entry_types=("ALIAS", "CLUSTER"),
        library_entries="MYLIB",
        volume_entries="PROD",
        catalog="MYCAT",
        creation_days=30,
        expiration_days=90,
        level="PROD",
        cdilvl=False,
        prefix=True,
        detail="ALL",
        file="MYDD",
        library="MYLIB2",
        outfile="OUTDD",
    )


# =========================================================================
# LISTCAT: order independence
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_outfile_before_entrytype_order_independent():
    cmds = parse_ams("LISTCAT OUTFILE(OUTDD) CLUSTER\n")
    assert cmds[0] == Listcat(entry_types=("CLUSTER",), outfile="OUTDD")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_listcat_level_before_entrytype_order_independent():
    cmds = parse_ams("LISTCAT LEVEL(PROD) ALIAS\n")
    assert cmds[0] == Listcat(entry_types=("ALIAS",), level="PROD")
