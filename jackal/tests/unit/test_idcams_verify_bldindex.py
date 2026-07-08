"""Tests for IDCAMS VERIFY and BLDINDEX parsing into the comprehensive AST.

Covers every parameter listed in the design spec's Verify and Bldindex
sections (2026-07-08-idcams-comprehensive-grammar-design.md).

VERIFY's FILE/DATASET (required) is a genuine mutual-exclusivity choice
group, flat-grammar/transformer-enforced per the plan's ratified pattern
(see ComprehensiveIdcamsTransformer.verify()). RECOVER is an ordinary bare
flag. This is the lightest command in the comprehensive-grammar plan.

BLDINDEX's INFILE/INDATASET (required), OUTFILE/OUTDATASET (required --
each itself a LIST of 1+ ddnames/entrynames), EXTERNALSORT/INTERNALSORT
(optional "which sort strategy"), and SORTCALL/NOSORTCALL (optional "which
sort mechanism") get the same flat-grammar/transformer-enforced treatment.
SORTDEVICETYPE, SORTFILENUMBER, SORTMESSAGEDD, SORTMESSAGELEVEL, WORKFILES,
and CATALOG are ordinary single-occurrence (or plain list) params -- no
mutual-exclusivity machinery.
"""

from __future__ import annotations

import pytest

from jackal.idcams.ast_bldindex import Bldindex
from jackal.idcams.ast_values import Name
from jackal.idcams.ast_verify import Verify
from jackal.idcams.parser_comprehensive import parse_ams
from tests.covers import NotLanguageFeature, covers

# =========================================================================
# VERIFY: FILE/DATASET (required, exactly one)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_verify_file():
    cmds = parse_ams("VERIFY FILE(MYDD)\n")
    assert cmds[0] == Verify(file="MYDD")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_verify_dataset():
    cmds = parse_ams("VERIFY DATASET(MY.CLUSTER)\n")
    assert cmds[0] == Verify(dataset=Name.parse("MY.CLUSTER"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_verify_file_dataset_together_raises():
    with pytest.raises(ValueError):
        parse_ams("VERIFY FILE(MYDD) DATASET(MY.CLUSTER)\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_verify_missing_target_raises():
    with pytest.raises(ValueError):
        parse_ams("VERIFY RECOVER\n")


# =========================================================================
# VERIFY: RECOVER
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_verify_recover():
    cmds = parse_ams("VERIFY FILE(MYDD) RECOVER\n")
    assert cmds[0] == Verify(file="MYDD", recover=True)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_verify_recover_before_dataset_order_independent():
    """RECOVER (an ordinary optional flag) placed before DATASET (the
    required choice member) -- proves verify_param is a flat,
    freely-repeatable list, not a fixed-order chain."""
    cmds = parse_ams("VERIFY RECOVER DATASET(MY.CLUSTER)\n")
    assert cmds[0] == Verify(dataset=Name.parse("MY.CLUSTER"), recover=True)


# =========================================================================
# BLDINDEX: INFILE/INDATASET (required, exactly one)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bldindex_infile():
    cmds = parse_ams("BLDINDEX INFILE(INDD) OUTFILE(OUTDD)\n")
    assert cmds[0] == Bldindex(infile="INDD", outfiles=("OUTDD",))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bldindex_indataset():
    cmds = parse_ams("BLDINDEX INDATASET(MY.IN) OUTFILE(OUTDD)\n")
    assert cmds[0] == Bldindex(indataset=Name.parse("MY.IN"), outfiles=("OUTDD",))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bldindex_infile_indataset_together_raises():
    with pytest.raises(ValueError):
        parse_ams("BLDINDEX INFILE(INDD) INDATASET(MY.IN) OUTFILE(OUTDD)\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bldindex_missing_source_raises():
    with pytest.raises(ValueError):
        parse_ams("BLDINDEX OUTFILE(OUTDD)\n")


# =========================================================================
# BLDINDEX: OUTFILE/OUTDATASET (required, exactly one -- each a LIST)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bldindex_outfile_list():
    cmds = parse_ams("BLDINDEX INFILE(INDD) OUTFILE(OUTDD1 OUTDD2)\n")
    assert cmds[0] == Bldindex(infile="INDD", outfiles=("OUTDD1", "OUTDD2"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bldindex_outdataset_list():
    cmds = parse_ams("BLDINDEX INFILE(INDD) OUTDATASET(MY.OUT1 MY.OUT2)\n")
    assert cmds[0] == Bldindex(
        infile="INDD",
        outdatasets=(Name.parse("MY.OUT1"), Name.parse("MY.OUT2")),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bldindex_outfile_outdataset_together_raises():
    with pytest.raises(ValueError):
        parse_ams("BLDINDEX INFILE(INDD) OUTFILE(OUTDD) OUTDATASET(MY.OUT)\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bldindex_missing_target_raises():
    with pytest.raises(ValueError):
        parse_ams("BLDINDEX INFILE(INDD)\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bldindex_outfile_before_infile_order_independent():
    """OUTFILE placed before INFILE -- proves bldindex_param is a flat,
    freely-repeatable list like EXPORT's/IMPORT's, not a fixed-order
    chain."""
    cmds = parse_ams("BLDINDEX OUTFILE(OUTDD) INFILE(INDD)\n")
    assert cmds[0] == Bldindex(infile="INDD", outfiles=("OUTDD",))


# =========================================================================
# BLDINDEX: EXTERNALSORT/INTERNALSORT (optional, at most one)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bldindex_externalsort():
    cmds = parse_ams("BLDINDEX INFILE(INDD) OUTFILE(OUTDD) EXTERNALSORT\n")
    assert cmds[0] == Bldindex(
        infile="INDD", outfiles=("OUTDD",), sort_kind="EXTERNALSORT"
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bldindex_internalsort():
    cmds = parse_ams("BLDINDEX INFILE(INDD) OUTFILE(OUTDD) INTERNALSORT\n")
    assert cmds[0] == Bldindex(
        infile="INDD", outfiles=("OUTDD",), sort_kind="INTERNALSORT"
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bldindex_externalsort_internalsort_together_raises():
    with pytest.raises(ValueError):
        parse_ams("BLDINDEX INFILE(INDD) OUTFILE(OUTDD) EXTERNALSORT INTERNALSORT\n")


# =========================================================================
# BLDINDEX: SORTCALL/NOSORTCALL (optional, at most one)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bldindex_sortcall():
    cmds = parse_ams("BLDINDEX INFILE(INDD) OUTFILE(OUTDD) SORTCALL\n")
    assert cmds[0] == Bldindex(infile="INDD", outfiles=("OUTDD",), sort_call=True)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bldindex_nosortcall():
    cmds = parse_ams("BLDINDEX INFILE(INDD) OUTFILE(OUTDD) NOSORTCALL\n")
    assert cmds[0] == Bldindex(infile="INDD", outfiles=("OUTDD",), sort_call=False)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bldindex_sortcall_nosortcall_together_raises():
    with pytest.raises(ValueError):
        parse_ams("BLDINDEX INFILE(INDD) OUTFILE(OUTDD) SORTCALL NOSORTCALL\n")


# =========================================================================
# BLDINDEX: WORKFILES (2 ddnames)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bldindex_workfiles_two_ddnames():
    cmds = parse_ams("BLDINDEX INFILE(INDD) OUTFILE(OUTDD) WORKFILES(WORK1 WORK2)\n")
    assert cmds[0] == Bldindex(
        infile="INDD",
        outfiles=("OUTDD",),
        work_files=("WORK1", "WORK2"),
    )


# =========================================================================
# BLDINDEX: remaining parameters (Step 6 coverage) -- SORTDEVICETYPE,
# SORTFILENUMBER, SORTMESSAGEDD, SORTMESSAGELEVEL, CATALOG
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bldindex_sortdevicetype():
    cmds = parse_ams("BLDINDEX INFILE(INDD) OUTFILE(OUTDD) SORTDEVICETYPE(3390)\n")
    assert cmds[0] == Bldindex(
        infile="INDD", outfiles=("OUTDD",), sort_device_type="3390"
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bldindex_sortfilenumber():
    cmds = parse_ams("BLDINDEX INFILE(INDD) OUTFILE(OUTDD) SORTFILENUMBER(4)\n")
    assert cmds[0] == Bldindex(infile="INDD", outfiles=("OUTDD",), sort_file_number=4)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bldindex_sortmessagedd():
    cmds = parse_ams("BLDINDEX INFILE(INDD) OUTFILE(OUTDD) SORTMESSAGEDD(SORTMSG)\n")
    assert cmds[0] == Bldindex(
        infile="INDD", outfiles=("OUTDD",), sort_message_dd="SORTMSG"
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bldindex_sortmessagelevel_all():
    cmds = parse_ams("BLDINDEX INFILE(INDD) OUTFILE(OUTDD) SORTMESSAGELEVEL(ALL)\n")
    assert cmds[0] == Bldindex(
        infile="INDD", outfiles=("OUTDD",), sort_message_level="ALL"
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bldindex_sortmessagelevel_critical():
    cmds = parse_ams(
        "BLDINDEX INFILE(INDD) OUTFILE(OUTDD) SORTMESSAGELEVEL(CRITICAL)\n"
    )
    assert cmds[0] == Bldindex(
        infile="INDD", outfiles=("OUTDD",), sort_message_level="CRITICAL"
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bldindex_sortmessagelevel_none():
    cmds = parse_ams("BLDINDEX INFILE(INDD) OUTFILE(OUTDD) SORTMESSAGELEVEL(NONE)\n")
    assert cmds[0] == Bldindex(
        infile="INDD", outfiles=("OUTDD",), sort_message_level="NONE"
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bldindex_catalog():
    cmds = parse_ams("BLDINDEX INFILE(INDD) OUTFILE(OUTDD) CATALOG(MY.CAT)\n")
    assert cmds[0] == Bldindex(infile="INDD", outfiles=("OUTDD",), catalog="MY.CAT")
