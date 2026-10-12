"""Tests for the IDCAMS parser over ams.lark: text -> the commands the executor runs."""

from __future__ import annotations

from jackal.gdg import Empty, GdgOrder, Scratch
from jackal.idcams.commands import (
    Cancel,
    Cc,
    CcOp,
    Condition,
    DefineCluster,
    DefineGdg,
    Delete,
    If,
    NotExecuted,
    Repro,
    SetCc,
    Verb,
    Verify,
    VerifyDataset,
    VerifyFile,
)
from jackal.idcams.parser import parse_idcams
from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_delete_in_its_forms():
    """AMS ch. 20: DELETE (or DEL) one entry or a parenthesised list, with an
    optional entry type (CLUSTER, CL, AIX, NONVSAM ...) and PURGE (PRG). A
    record ends the command unless a hyphen continues it."""
    cmds = parse_idcams(
        "   DELETE A.B.KSDS -\n"
        "          CLUSTER\n"
        " DELETE                  AWS.M2.CARDDEMO.USRSEC.VSAM.ESDS\n"
        "  DEL (A.ONE A.TWO) CL PRG\n"
        "  DELETE A.B.AIX ALTERNATEINDEX\n"
    )
    assert cmds == (
        Delete(("A.B.KSDS",), purge=False),
        Delete(("AWS.M2.CARDDEMO.USRSEC.VSAM.ESDS",), purge=False),
        Delete(("A.ONE", "A.TWO"), purge=True),
        Delete(("A.B.AIX",), purge=False),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_define_cluster_reads_its_key_and_record_size_and_drops_storage():
    """AMS ch. 14: NAME, KEYS and RECORDSIZE (RECSZ) define the KSDS, at the
    cluster level or in DATA(...); commas are separators (p. xxiv); space,
    VOLUMES, CISZ, FREESPACE, SHAREOPTIONS, REUSE and the like are storage
    attributes jackal drops."""
    cmds = parse_idcams(
        "   DEFINE CLUSTER (NAME(A.B.KSDS) -\n"
        "          KEYS(11 0) -\n"
        "          RECORDSIZE(300 300) -\n"
        "          INDEXED -\n"
        "          ) -\n"
        "          DATA (NAME(A.B.KSDS.DATA)) -\n"
        "          INDEX (NAME(A.B.KSDS.INDEX))\n"
        " DEF CL (NAME(A.USRSEC) KEYS(8,0) RECSZ(80,80) REUSE IXD -\n"
        "         TRK(45,15) FSPC(10,15) CISZ(8192) SHR(2 3) VOL(V1))\n"
        " DEFINE CLUSTER (NAME(A.TRXFL) INDEXED CYL(1 5)) -\n"
        "        DATA (NAME(A.TRXFL.DATA) KEYS(32 0) RECORDSIZE(350 350) -\n"
        "              CISZ(4096))\n"
    )
    assert cmds == (
        DefineCluster(name="A.B.KSDS", key_length=11, key_offset=0, record_size=300),
        DefineCluster(name="A.USRSEC", key_length=8, key_offset=0, record_size=80),
        DefineCluster(name="A.TRXFL", key_length=32, key_offset=0, record_size=350),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_command_jackal_does_not_run_parses_as_not_executed():
    """Record O5: a command jackal does not execute, or one coding a parameter
    that changes what it does and that jackal does not model, is NotExecuted
    rather than a parse failure or a silently partial run."""
    cmds = parse_idcams(
        "   LISTCAT ENTRIES(A.B.C)\n"
        "   DEFINE ALTERNATEINDEX (NAME(A.AIX) RELATE(A.KSDS) KEYS(8 0))\n"
        "   REPRO INFILE(IN) OUTFILE(OUT) COUNT(10)\n"
        "   DEFINE CLUSTER (NAME(A.ESDS) RECORDSIZE(80 80) NONINDEXED)\n"
        "   DEFINE CLUSTER (NAME(A.COPY) MODEL(A.KSDS))\n"
        "   DELETE A.B.HIST GENERATIONDATAGROUP\n"
    )
    assert cmds == (
        NotExecuted(Verb.LISTCAT),
        NotExecuted(Verb.DEFINE_ALTERNATEINDEX),
        NotExecuted(Verb.REPRO),
        NotExecuted(Verb.DEFINE_CLUSTER),
        NotExecuted(Verb.DEFINE_CLUSTER),
        NotExecuted(Verb.DELETE),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_repro_by_ddname():
    """AMS ch. 30: INFILE (IFILE) and OUTFILE (OFILE), in either order."""
    assert parse_idcams(
        "   REPRO INFILE(ACCTDATA) OUTFILE(ACCTVSAM)\n   REPRO OFILE(B) IFILE(A)\n"
    ) == (
        Repro(infile_dd="ACCTDATA", outfile_dd="ACCTVSAM"),
        Repro(infile_dd="A", outfile_dd="B"),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_separators_comments_and_continuations():
    """AMS pp. xxiv and xxvii: blanks, commas and /* */ comments separate; a
    semicolon ends the command and the rest of its record is a comment; a plus
    sign continues both the command and a value within it, the next record's
    first nonseparator character continuing the value."""
    assert parse_idcams(
        "   DELETE AWS.M2.CARD+\n"
        "       DEMO.KSDS\n"
        "   SET /* comment */ MAXCC=0; ignored garbage $$$ !!!\n"
        "   CANCEL\n"
    ) == (
        Delete(("AWS.M2.CARDDEMO.KSDS",), purge=False),
        SetCc(Cc.MAXCC, 0),
        Cancel(),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_define_generation_data_group_in_full_and_abbreviated():
    """AMS ch. 15: DEFINE GENERATIONDATAGROUP, or DEF GDG with LIM/EMP/NSCR.
    NOEMPTY, NOSCRATCH and LIFO are the defaults; OWNER, PURGE and CATALOG
    are accepted and not modelled."""
    full = parse_idcams(
        "   DEFINE GENERATIONDATAGROUP -\n"
        "   (NAME(AWS.M2.CARDDEMO.TRANSACT.BKUP) -\n"
        "    LIMIT(5) -\n"
        "    SCRATCH -\n"
        "   )\n"
        "   IF LASTCC=12 THEN SET MAXCC=0                                   \n"
    )
    short = parse_idcams(
        " DEF GDG (NAME(A.B.HIST) LIM(255) EMP NSCR OWNER(OPS) FIFO PURGE EXT)"
        " CAT(UCAT.ONE)\n"
    )
    assert full == (
        DefineGdg(
            name="AWS.M2.CARDDEMO.TRANSACT.BKUP",
            limit=5,
            empty=Empty.NOEMPTY,
            scratch=Scratch.SCRATCH,
            order=GdgOrder.LIFO,
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
            order=GdgOrder.FIFO,
            extended=True,
        ),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_verify_and_modal_blocks_by_record():
    """AMS ch. 2 and 34: VFY/VERIFY FILE or DATASET; IF LASTCC/MAXCC with each
    operator spelling; THEN DO ... END; a THEN or ELSE ending its record is
    null; each ELSE takes the nearest unmatched THEN; SET MAXCC/LASTCC with =
    or EQ; CANCEL."""
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
        "  IF MAXCC LE 08 THEN SET MAXCC EQ 0\n"
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
            (If(Condition(Cc.LASTCC, CcOp.LT, 12), (Delete(("A.B",), False),), ()),),
            (SetCc(Cc.LASTCC, 20),),
        ),
        If(Condition(Cc.LASTCC, CcOp.EQ, 0), (), (Cancel(),)),
        If(
            Condition(Cc.MAXCC, CcOp.GT, 4),
            (
                If(
                    Condition(Cc.LASTCC, CcOp.LT, 12),
                    (Delete(("C.D",), False),),
                    (Delete(("E.F",), False),),
                ),
            ),
            (),
        ),
        If(Condition(Cc.MAXCC, CcOp.LE, 8), (SetCc(Cc.MAXCC, 0),), ()),
    )
