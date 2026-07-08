"""Tests for IDCAMS REPRO parsing into the comprehensive AST, including its
nested ENCIPHER(...)/DECIPHER(...) cryptographic sub-blocks.

Covers every parameter listed in the design spec's Repro section
(2026-07-08-idcams-comprehensive-grammar-design.md): the two required
"pick one" groups (INFILE/INDATASET, OUTFILE/OUTDATASET), the six optional
"pick one" groups (ENTRIES/LEVEL, the 4-way RangeStart and RangeEnd, ENCIPHER/
DECIPHER, INSERTSHIFT/INSERTALL, SKIPDBCSCHECK/NODBCSCHECK), the two nested
"pick one" groups inside the cipher sub-blocks (CipherSpec's
EXTERNALKEYNAME/INTERNALKEYNAME/PRIVATEKEY, DecipherSpec's DATAKEYFILE/
DATAKEYVALUE/SYSTEMKEY), and the ordinary freely-repeatable parameters
(CIMODE/NOCIMODE, DBCS, ERRORLIMIT, FILE, MERGECAT/NOMERGECAT,
MESSAGELEVEL, REPLACE/NOREPLACE, REUSE/NOREUSE, VOLUMEENTRIES, RLSSOURCE,
RLSTARGET, and the CipherSpec/DecipherSpec sub-fields CIPHERUNIT,
DATAKEYFILE/DATAKEYVALUE, SHIPKEYNAMES, STOREDATAKEY/NOSTOREDATAKEY,
STOREKEYNAME, USERDATA, SYSTEMDATAKEY, SYSTEMKEYNAME).

Per ams.lark's REPRO section comment, the eight top-level "pick one" groups
are enforced via a fixed-relative-order chain of small two-state sequences
(not a 2^8-state cross-product DFA) -- tests below place multi-group
commands in that chain's order: source, target, ENTRIES/LEVEL, RangeStart,
RangeEnd, ENCIPHER/DECIPHER, INSERTSHIFT/INSERTALL, SKIPDBCSCHECK/
NODBCSCHECK.
"""

from __future__ import annotations

import pytest
from lark.exceptions import LarkError

from jackal.idcams.ast_repro import (
    CipherSpec,
    DecipherSpec,
    RangeEnd,
    RangeStart,
    Repro,
)
from jackal.idcams.ast_values import Name, QuotedString
from jackal.idcams.parser_comprehensive import parse_ams
from tests.covers import NotLanguageFeature, covers

# =========================================================================
# INFILE/OUTFILE (existing-shape-compatible case) and INDATASET/OUTDATASET
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_infile_outfile():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD)\n")
    assert cmds[0] == Repro(infile="INDD", outfile="OUTDD")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_indataset_outdataset():
    cmds = parse_ams("REPRO INDATASET(MY.IN) OUTDATASET(MY.OUT)\n")
    assert cmds[0] == Repro(
        indataset=Name.parse("MY.IN"), outdataset=Name.parse("MY.OUT")
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_infile_indataset_together_raises():
    """source is a genuine 'pick one' choice -- INFILE and INDATASET can't
    both be specified. Must be a structural LarkError."""
    with pytest.raises(LarkError):
        parse_ams("REPRO INFILE(INDD) INDATASET(MY.IN) OUTFILE(OUTDD)\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_outfile_outdataset_together_raises():
    with pytest.raises(LarkError):
        parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) OUTDATASET(MY.OUT)\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_missing_source_raises():
    with pytest.raises(LarkError):
        parse_ams("REPRO OUTFILE(OUTDD)\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_missing_target_raises():
    with pytest.raises(LarkError):
        parse_ams("REPRO INFILE(INDD)\n")


# =========================================================================
# ENTRIES/LEVEL (optional, at most one)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_entries():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) ENTRIES(A B)\n")
    assert cmds[0].entries == (Name.parse("A"), Name.parse("B"))
    assert cmds[0].level is None


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_level():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) LEVEL(PROD)\n")
    assert cmds[0].level == "PROD"
    assert cmds[0].entries == ()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_entries_level_together_raises():
    with pytest.raises(LarkError):
        parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) ENTRIES(A) LEVEL(PROD)\n")


# =========================================================================
# RangeStart: FROMKEY/FROMADDRESS/FROMNUMBER/SKIP (optional 4-way choice)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_fromkey():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) FROMKEY('KEY001')\n")
    assert cmds[0].range_start == RangeStart(
        kind="FROMKEY", value=QuotedString(text="KEY001")
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_fromaddress():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) FROMADDRESS(1000)\n")
    assert cmds[0].range_start == RangeStart(kind="FROMADDRESS", value=1000)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_fromnumber():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) FROMNUMBER(5)\n")
    assert cmds[0].range_start == RangeStart(kind="FROMNUMBER", value=5)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_skip():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) SKIP(3)\n")
    assert cmds[0].range_start == RangeStart(kind="SKIP", value=3)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_fromkey_fromaddress_together_raises():
    with pytest.raises(LarkError):
        parse_ams(
            "REPRO INFILE(INDD) OUTFILE(OUTDD) FROMKEY('KEY001') FROMADDRESS(1000)\n"
        )


# =========================================================================
# RangeEnd: TOKEY/TOADDRESS/TONUMBER/COUNT (optional 4-way choice)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_tokey():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) TOKEY('KEY999')\n")
    assert cmds[0].range_end == RangeEnd(
        kind="TOKEY", value=QuotedString(text="KEY999")
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_toaddress():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) TOADDRESS(2000)\n")
    assert cmds[0].range_end == RangeEnd(kind="TOADDRESS", value=2000)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_tonumber():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) TONUMBER(50)\n")
    assert cmds[0].range_end == RangeEnd(kind="TONUMBER", value=50)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_count():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) COUNT(100)\n")
    assert cmds[0].range_end == RangeEnd(kind="COUNT", value=100)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_tokey_toaddress_together_raises():
    with pytest.raises(LarkError):
        parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) TOKEY('KEY999') TOADDRESS(2000)\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_fromkey_and_tokey_type_matching_rejection():
    """The manual's start/end type-matching rule (FROMKEY pairs with TOKEY,
    not TOADDRESS) is a semantic convention, not grammar-enforced here --
    but a FROMKEY/TOADDRESS combination that's semantically mismatched must
    still parse structurally fine at the grammar level (each of RangeStart
    and RangeEnd is independently at-most-one). Document the explicit
    rejection scope: this test asserts the grammar does NOT reject
    mismatched kinds (RangeStart/RangeEnd type-compatibility is out of
    grammar scope, would require semantic validation beyond structural
    parsing)."""
    cmds = parse_ams(
        "REPRO INFILE(INDD) OUTFILE(OUTDD) FROMKEY('KEY001') TOADDRESS(2000)\n"
    )
    assert cmds[0].range_start == RangeStart(
        kind="FROMKEY", value=QuotedString(text="KEY001")
    )
    assert cmds[0].range_end == RangeEnd(kind="TOADDRESS", value=2000)


# =========================================================================
# MERGECAT/NOMERGECAT, REPLACE/NOREPLACE
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_mergecat():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) MERGECAT\n")
    assert cmds[0].merge_cat is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_nomergecat():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) NOMERGECAT\n")
    assert cmds[0].merge_cat is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_replace():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) REPLACE\n")
    assert cmds[0].replace is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_noreplace():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) NOREPLACE\n")
    assert cmds[0].replace is False


# =========================================================================
# ENCIPHER with EXTERNALKEYNAME / DECIPHER with SYSTEMKEY, mutual exclusion
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_encipher_externalkeyname():
    cmds = parse_ams(
        "REPRO INFILE(INDD) OUTFILE(OUTDD) ENCIPHER(EXTERNALKEYNAME(MYKEY))\n"
    )
    assert cmds[0].encipher == CipherSpec(
        key_source="EXTERNALKEYNAME", key_name="MYKEY"
    )
    assert cmds[0].decipher is None


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_decipher_systemkey():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) DECIPHER(SYSTEMKEY)\n")
    assert cmds[0].decipher == DecipherSpec(key_source="SYSTEMKEY")
    assert cmds[0].encipher is None


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_encipher_decipher_together_raises():
    """ENCIPHER/DECIPHER is a genuine 'pick one' choice -- a command can't
    both encipher and decipher. Must be a structural LarkError."""
    with pytest.raises(LarkError):
        parse_ams(
            "REPRO INFILE(INDD) OUTFILE(OUTDD) "
            "ENCIPHER(EXTERNALKEYNAME(MYKEY)) DECIPHER(SYSTEMKEY)\n"
        )


# =========================================================================
# CipherSpec's own EXTERNALKEYNAME/INTERNALKEYNAME/PRIVATEKEY 3-way choice
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_encipher_internalkeyname():
    cmds = parse_ams(
        "REPRO INFILE(INDD) OUTFILE(OUTDD) ENCIPHER(INTERNALKEYNAME(MYKEY2))\n"
    )
    assert cmds[0].encipher == CipherSpec(
        key_source="INTERNALKEYNAME", key_name="MYKEY2"
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_encipher_privatekey():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) ENCIPHER(PRIVATEKEY)\n")
    assert cmds[0].encipher == CipherSpec(key_source="PRIVATEKEY", key_name=None)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_encipher_externalkeyname_internalkeyname_together_raises():
    with pytest.raises(LarkError):
        parse_ams(
            "REPRO INFILE(INDD) OUTFILE(OUTDD) "
            "ENCIPHER(EXTERNALKEYNAME(A) INTERNALKEYNAME(B))\n"
        )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_encipher_cipher_subfields():
    cmds = parse_ams(
        "REPRO INFILE(INDD) OUTFILE(OUTDD) -\n"
        "  ENCIPHER(PRIVATEKEY CIPHERUNIT(2) DATAKEYFILE(KEYDD) -\n"
        "    SHIPKEYNAMES(K1 K2) STOREDATAKEY STOREKEYNAME(STOREDD) -\n"
        "    USERDATA('EXTRA'))\n"
    )
    assert cmds[0].encipher == CipherSpec(
        key_source="PRIVATEKEY",
        key_name=None,
        cipher_unit=2,
        data_key_file="KEYDD",
        ship_key_names=("K1", "K2"),
        store_data_key=True,
        store_key_name="STOREDD",
        user_data="EXTRA",
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_encipher_datakeyvalue_nostoredatakey():
    cmds = parse_ams(
        "REPRO INFILE(INDD) OUTFILE(OUTDD) "
        "ENCIPHER(PRIVATEKEY DATAKEYVALUE('ABCDEFGH') NOSTOREDATAKEY)\n"
    )
    assert cmds[0].encipher == CipherSpec(
        key_source="PRIVATEKEY",
        data_key_value="ABCDEFGH",
        store_data_key=False,
    )


# =========================================================================
# DecipherSpec's own DATAKEYFILE/DATAKEYVALUE/SYSTEMKEY 3-way choice
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_decipher_datakeyfile():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) DECIPHER(DATAKEYFILE(KEYDD))\n")
    assert cmds[0].decipher == DecipherSpec(
        key_source="DATAKEYFILE", data_key_file="KEYDD"
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_decipher_datakeyvalue():
    cmds = parse_ams(
        "REPRO INFILE(INDD) OUTFILE(OUTDD) DECIPHER(DATAKEYVALUE('ABCDEFGH'))\n"
    )
    assert cmds[0].decipher == DecipherSpec(
        key_source="DATAKEYVALUE", data_key_value="ABCDEFGH"
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_decipher_datakeyfile_datakeyvalue_together_raises():
    with pytest.raises(LarkError):
        parse_ams(
            "REPRO INFILE(INDD) OUTFILE(OUTDD) "
            "DECIPHER(DATAKEYFILE(A) DATAKEYVALUE('B'))\n"
        )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_decipher_systemkey_subfields():
    cmds = parse_ams(
        "REPRO INFILE(INDD) OUTFILE(OUTDD) -\n"
        "  DECIPHER(SYSTEMKEY SYSTEMDATAKEY('SYSKEYVAL') SYSTEMKEYNAME(SYSKEYNM))\n"
    )
    assert cmds[0].decipher == DecipherSpec(
        key_source="SYSTEMKEY",
        system_data_key="SYSKEYVAL",
        system_key_name="SYSKEYNM",
    )


# =========================================================================
# Step 6: remaining parameters
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_cimode():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) CIMODE\n")
    assert cmds[0].cimode is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_nocimode():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) NOCIMODE\n")
    assert cmds[0].cimode is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_dbcs():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) DBCS\n")
    assert cmds[0].dbcs is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_no_dbcs_defaults_false():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD)\n")
    assert cmds[0].dbcs is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_errorlimit():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) ERRORLIMIT(10)\n")
    assert cmds[0].error_limit == 10


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_file():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) FILE(MYDD)\n")
    assert cmds[0].file == "MYDD"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_insertshift():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) INSERTSHIFT((10 2) (20 4))\n")
    assert cmds[0].insert_shift == ((10, 2), (20, 4))
    assert cmds[0].insert_all is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_insertall():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) INSERTALL\n")
    assert cmds[0].insert_all is True
    assert cmds[0].insert_shift == ()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_insertshift_insertall_together_raises():
    with pytest.raises(LarkError):
        parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) INSERTSHIFT((10 2)) INSERTALL\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_messagelevel_all():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) MESSAGELEVEL(ALL)\n")
    assert cmds[0].message_level == "ALL"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_messagelevel_short():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) MESSAGELEVEL(SHORT)\n")
    assert cmds[0].message_level == "SHORT"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_reuse():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) REUSE\n")
    assert cmds[0].reuse is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_noreuse():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) NOREUSE\n")
    assert cmds[0].reuse is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_skipdbcscheck():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) SKIPDBCSCHECK((5 1))\n")
    assert cmds[0].skip_dbcs_check == ((5, 1),)
    assert cmds[0].no_dbcs_check is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_nodbcscheck():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) NODBCSCHECK\n")
    assert cmds[0].no_dbcs_check is True
    assert cmds[0].skip_dbcs_check == ()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_skipdbcscheck_nodbcscheck_together_raises():
    with pytest.raises(LarkError):
        parse_ams(
            "REPRO INFILE(INDD) OUTFILE(OUTDD) SKIPDBCSCHECK((5 1)) NODBCSCHECK\n"
        )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_volumeentries():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) VOLUMEENTRIES(PROD)\n")
    assert cmds[0].volume_entries == "PROD"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_rlssource():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) RLSSOURCE(YES)\n")
    assert cmds[0].rls_source == "YES"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_rlstarget():
    cmds = parse_ams("REPRO INFILE(INDD) OUTFILE(OUTDD) RLSTARGET(QUIESCE)\n")
    assert cmds[0].rls_target == "QUIESCE"


# =========================================================================
# Full command, a representative broad set of parameters together
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_full():
    cmds = parse_ams(
        "REPRO INFILE(INDD) OUTFILE(OUTDD) -\n"
        "  CIMODE ERRORLIMIT(10) FILE(MYDD) MERGECAT MESSAGELEVEL(ALL) -\n"
        "  REPLACE REUSE VOLUMEENTRIES(PROD) RLSSOURCE(YES) RLSTARGET(NO) -\n"
        "  ENTRIES(A B) FROMNUMBER(5) TONUMBER(50) -\n"
        "  ENCIPHER(EXTERNALKEYNAME(MYKEY) CIPHERUNIT(2)) -\n"
        "  INSERTSHIFT((10 2)) SKIPDBCSCHECK((5 1))\n"
    )
    assert cmds[0] == Repro(
        infile="INDD",
        outfile="OUTDD",
        cimode=True,
        error_limit=10,
        file="MYDD",
        merge_cat=True,
        message_level="ALL",
        replace=True,
        reuse=True,
        volume_entries="PROD",
        rls_source="YES",
        rls_target="NO",
        entries=(Name.parse("A"), Name.parse("B")),
        range_start=RangeStart(kind="FROMNUMBER", value=5),
        range_end=RangeEnd(kind="TONUMBER", value=50),
        encipher=CipherSpec(
            key_source="EXTERNALKEYNAME", key_name="MYKEY", cipher_unit=2
        ),
        insert_shift=((10, 2),),
        skip_dbcs_check=((5, 1),),
    )
