"""Tests for IDCAMS control-language parser."""

from __future__ import annotations

import lark.exceptions
import pytest
from jackal.gdg import Empty, Scratch
from jackal.idcams.commands import (
    Cc,
    CcOp,
    Condition,
    DefineCluster,
    DefineGdg,
    Delete,
    If,
    Repro,
    SetCc,
)
from jackal.idcams.parser import parse_idcams
from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_delete_and_if():
    cmds = parse_idcams(
        "   DELETE A.B.KSDS -\n          CLUSTER\n"
        "   IF MAXCC LE 08 THEN SET MAXCC = 0\n"
    )
    assert cmds[0] == Delete(dsn="A.B.KSDS")
    assert cmds[1] == If(Condition(Cc.MAXCC, CcOp.LE, 8), (SetCc(Cc.MAXCC, 0),), ())


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_define_cluster():
    text = (
        "   DEFINE CLUSTER (NAME(A.B.KSDS) -\n"
        "          KEYS(11 0) -\n"
        "          RECORDSIZE(300 300) -\n"
        "          INDEXED -\n"
        "          ) -\n"
        "          DATA (NAME(A.B.KSDS.DATA)) -\n"
        "          INDEX (NAME(A.B.KSDS.INDEX))\n"
    )
    d = parse_idcams(text)[0]
    assert d == DefineCluster(
        name="A.B.KSDS", key_length=11, key_offset=0, record_size=300
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_repro():
    assert parse_idcams("   REPRO INFILE(ACCTDATA) OUTFILE(ACCTVSAM)\n")[0] == Repro(
        infile_dd="ACCTDATA", outfile_dd="ACCTVSAM"
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_unsupported_verb_raises():
    """Unsupported IDCAMS verbs must fail loud, not silently return empty."""
    with pytest.raises(lark.exceptions.LarkError):
        parse_idcams("   LISTCAT ENTRIES(A.B.C)\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_delete_without_cluster_trailer():
    """Real IDCAMS treats CLUSTER as optional (the default entry type) --
    e.g. DUSRSECJ.jcl / ESDSRRDS.jcl in the CardDemo corpus delete VSAM
    entries with no trailing type keyword at all."""
    cmds = parse_idcams("   DELETE AWS.M2.CARDDEMO.USRSEC.VSAM.ESDS\n")
    assert cmds[0] == Delete(dsn="AWS.M2.CARDDEMO.USRSEC.VSAM.ESDS")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_standalone_set_maxcc():
    """A bare SET MAXCC = n (not wrapped in IF...THEN) is a common
    idempotency idiom: DELETE x then unconditionally reset MAXCC so a
    missing dataset doesn't fail the step."""
    cmds = parse_idcams("   SET MAXCC = 0\n")
    assert cmds[0] == SetCc(Cc.MAXCC, 0)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_if_lastcc_bare_equals():
    """Real DEFGDGB.jcl idiom: IF LASTCC=n (bare '=', not the EQ keyword)
    tests the immediately-preceding command's own rc, not the running
    MAXCC."""
    cmds = parse_idcams("   IF LASTCC=12 THEN SET MAXCC=0\n")
    assert cmds[0] == If(Condition(Cc.LASTCC, CcOp.EQ, 12), (SetCc(Cc.MAXCC, 0),), ())


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_if_maxcc_defaults_test_field_to_maxcc():
    """Existing IF MAXCC form must still default test_field to MAXCC --
    backward compatible with every already-parsed real job."""
    cmds = parse_idcams("   IF MAXCC LE 08 THEN SET MAXCC = 0\n")
    assert cmds[0] == If(Condition(Cc.MAXCC, CcOp.LE, 8), (SetCc(Cc.MAXCC, 0),), ())


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_lastcc_line_with_trailing_whitespace():
    """A LASTCC line in the shape DEFGDGB.jcl uses (bare '=', trailing
    padding), pinned in isolation."""
    cmds = parse_idcams(
        "   IF LASTCC=12 THEN SET MAXCC=0                                            \n"
    )
    assert cmds[0] == If(Condition(Cc.LASTCC, CcOp.EQ, 12), (SetCc(Cc.MAXCC, 0),), ())


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_delete_cluster_purge_trailer():
    """Real CBEXPORT.jcl idiom: DELETE dsn CLUSTER PURGE -- forces deletion
    even if the entry's retention period (TO/FOR) hasn't expired."""
    cmds = parse_idcams("  DELETE AWS.M2.CARDDEMO.EXPORT.DATA CLUSTER PURGE\n")
    assert cmds[0] == Delete(dsn="AWS.M2.CARDDEMO.EXPORT.DATA", purge=True)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_delete_without_purge_defaults_false():
    cmds = parse_idcams("   DELETE A.B.KSDS CLUSTER\n")
    assert cmds[0] == Delete(dsn="A.B.KSDS", purge=False)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_real_carddemo_delete_set_idiom():
    """Exact opening of ESDSRRDS.jcl's IDCAMS SYSIN: bare DELETE followed
    by a standalone SET MAXCC -- two back-to-back top-level statements.
    (The real file's third statement, DEFINE CLUSTER with comma-separated
    RECORDSIZE(80,80)/KEYS args, is a separate, already-tracked grammar
    gap -- comma-separated DEFINE params aren't modeled yet -- and is out
    of scope for this fix.)"""
    text = (
        " DELETE                  AWS.M2.CARDDEMO.USRSEC.VSAM.ESDS\n"
        " SET       MAXCC = 0\n"
    )
    cmds = parse_idcams(text)
    assert cmds[0] == Delete(dsn="AWS.M2.CARDDEMO.USRSEC.VSAM.ESDS")
    assert cmds[1] == SetCc(Cc.MAXCC, 0)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_define_generation_data_group_in_full_and_abbreviated():
    """AMS ch. 15: DEFINE GENERATIONDATAGROUP, or DEF GDG with LIM/EMP/NSCR.
    NOEMPTY and NOSCRATCH are the defaults; OWNER, LIFO, PURGE and CATALOG
    are accepted and not modelled."""
    full = parse_idcams(
        "   DEFINE GENERATIONDATAGROUP -\n"
        "   (NAME(AWS.M2.CARDDEMO.TRANSACT.BKUP) -\n"
        "    LIMIT(5) -\n"
        "    SCRATCH -\n"
        "   )\n"
        "   IF LASTCC=12 THEN SET MAXCC=0\n"
    )
    short = parse_idcams(
        " DEF GDG (NAME(A.B.HIST) LIM(255) EMP NSCR OWNER(OPS) LIFO PURGE EXT)"
        " CAT(UCAT.ONE)\n"
    )
    assert full == (
        DefineGdg(
            name="AWS.M2.CARDDEMO.TRANSACT.BKUP",
            limit=5,
            empty=Empty.NOEMPTY,
            scratch=Scratch.SCRATCH,
            extended=False,
        ),
        If(Condition(Cc.LASTCC, CcOp.EQ, 12), (SetCc(Cc.MAXCC, 0),), ()),
    )
    assert short == (
        DefineGdg(
            name="A.B.HIST",
            limit=255,
            empty=Empty.EMPTY,
            scratch=Scratch.NOSCRATCH,
            extended=True,
        ),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_verify_and_modal_blocks_by_record():
    """AMS ch. 2 and 34: VFY/VERIFY FILE or DATASET; THEN DO ... END; a THEN or
    ELSE ending its record is null; each ELSE takes the nearest unmatched THEN;
    SET LASTCC; CANCEL."""
    from jackal.idcams.commands import (
        Cancel,
        Cc,
        CcOp,
        Condition,
        If,
        SetCc,
        Verify,
        VerifyDataset,
        VerifyFile,
    )

    cmds = parse_idcams(
        "  VFY FILE(ACCTKSDS)\n"
        "  IF LASTCC=12 THEN DO\n"
        "     SET MAXCC=0\n"
        "     VERIFY DATASET(A.B.KSDS) RECOVER\n"
        "  END\n"
        "  IF MAXCC > 4 -\n"
        "    THEN IF LASTCC < 12 -\n"
        "      THEN DELETE A.B\n"
        "      ELSE\n"
        "    ELSE SET LASTCC = 20\n"
        "  IF LASTCC = 0 THEN\n"
        "  ELSE CANCEL\n"
        "  IF MAXCC > 4 -\n"
        "    THEN IF LASTCC < 12 -\n"
        "      THEN DELETE C.D\n"
        "      ELSE DELETE E.F\n"
    )
    assert cmds == (
        Verify(VerifyFile("ACCTKSDS")),
        If(
            Condition(Cc.LASTCC, CcOp.EQ, 12),
            (SetCc(Cc.MAXCC, 0), Verify(VerifyDataset("A.B.KSDS"))),
            (),
        ),
        If(
            Condition(Cc.MAXCC, CcOp.GT, 4),
            (If(Condition(Cc.LASTCC, CcOp.LT, 12), (Delete("A.B"),), ()),),
            (SetCc(Cc.LASTCC, 20),),
        ),
        If(Condition(Cc.LASTCC, CcOp.EQ, 0), (), (Cancel(),)),
        If(
            Condition(Cc.MAXCC, CcOp.GT, 4),
            (
                If(
                    Condition(Cc.LASTCC, CcOp.LT, 12),
                    (Delete("C.D"),),
                    (Delete("E.F"),),
                ),
            ),
            (),
        ),
    )
