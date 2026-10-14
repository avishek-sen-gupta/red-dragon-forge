"""Tests for the IDCAMS executor."""

from __future__ import annotations

from catnip.gdg import Empty, GdgBase, GdgOrder, Scratch
from catnip.labels import KsdsLabel, RecordFormat, SequentialLabel
from catnip.system_catalog import NotCataloged
from jackal.allocation import DdEnvironment
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
from jackal.model import (
    DD,
    DdName,
    DirectDSN,
    Disp,
    DispNormal,
    DispStatus,
    ProgramRef,
    ProgramStep,
    StepName,
)
from jackal.value_parts import literal
from tests.covers import NotLanguageFeature, covers
from tests.model_build import allocated
from tests.system_build import job_catalog, upload


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_reads_its_input_at_the_input_label_and_writes_at_the_output_label(
    tmp_path,
):
    from jackal.idcams.executor import run_idcams

    upload(tmp_path, "IN.PS", b"AAA1BBB2", SequentialLabel(RecordFormat.FB, 4))
    cat = job_catalog(tmp_path)
    dds = (
        DD(
            DdName("INF"),
            DirectDSN(literal("IN.PS")),
            Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP),
        ),
        DD(
            DdName("OUT"),
            DirectDSN(literal("OUT.KSDS")),
            Disp(DispStatus.OLD, DispNormal.KEEP, DispNormal.KEEP),
        ),
    )
    define = (
        DefineCluster(name="OUT.KSDS", key_length=3, key_offset=0, record_size=9),
    )
    defined = run_idcams(define, DdEnvironment(()), cat)
    env = allocated(ProgramStep(StepName("S2"), ProgramRef("IDCAMS"), dds), cat)
    copied = run_idcams((Repro(infile_dd="INF", outfile_dd="OUT"),), env, cat)
    assert (defined, copied) == (0, 0)
    from cobol_asg.file_enums import OpenMode
    from interpreter.cobol.file_drivers import IndexedDriver

    drv = IndexedDriver()
    drv.open(cat.resolve("OUT.KSDS").path, OpenMode.INPUT, 9, 0, 3)
    loaded = (drv.read_key(b"AAA").data, drv.read_key(b"BBB").data)
    drv.close()
    assert (loaded[0][:4], loaded[1][:4]) == (b"AAA1", b"BBB2")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_from_an_unlabelled_input_ends_with_12_and_idcams_goes_on(tmp_path):
    from jackal.idcams.executor import run_idcams

    cat = job_catalog(tmp_path)
    dds = (
        DD(
            DdName("INF"),
            DirectDSN(literal("NEW.PS")),
            Disp(DispStatus.NEW, DispNormal.CATLG, DispNormal.DELETE),
        ),
        DD(
            DdName("OUT"),
            DirectDSN(literal("OUT.PS")),
            Disp(DispStatus.NEW, DispNormal.CATLG, DispNormal.DELETE),
        ),
    )
    env = allocated(ProgramStep(StepName("S1"), ProgramRef("IDCAMS"), dds), cat)
    cmds = (
        Repro(infile_dd="INF", outfile_dd="OUT"),
        If(Condition(Cc.LASTCC, CcOp.EQ, 12), (SetCc(Cc.MAXCC, 5),), ()),
    )
    assert run_idcams(cmds, env, cat) == 5


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_ends_with_the_highest_code_of_its_entries(tmp_path):
    """AMS p. 22: 8 when an entry to be deleted could not be found. A DELETE of
    several entries deletes each it finds and ends with the highest code."""
    from jackal.idcams.executor import run_idcams

    for name in ("ONE.DS", "TWO.DS", "THREE.DS"):
        upload(tmp_path, name, b"")
    cat = job_catalog(tmp_path)
    rcs = tuple(
        run_idcams((Delete(entries, purge=False),), DdEnvironment(()), cat)
        for entries in (("ONE.DS",), ("GHOST.DS",), ("TWO.DS", "GHOST.DS", "THREE.DS"))
    )
    assert rcs == (0, 8, 8)
    assert (
        tuple(cat.resolve(n) for n in ("ONE.DS", "TWO.DS", "THREE.DS"))
        == (NotCataloged(),) * 3
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_command_not_executed_ends_with_12_and_the_stream_goes_on(tmp_path):
    """Record O6: a command jackal parsed but does not run ends with condition
    code 12, which LASTCC sees, and the next command runs."""
    from jackal.idcams.commands import Cc, CcOp, Condition, If, NotExecuted, SetCc, Verb
    from jackal.idcams.executor import run_idcams

    cat = job_catalog(tmp_path)
    cmds = (
        NotExecuted(Verb.LISTCAT),
        If(Condition(Cc.LASTCC, CcOp.EQ, 12), (SetCc(Cc.MAXCC, 3),), ()),
    )
    assert run_idcams(cmds, DdEnvironment(()), cat) == 3


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_registers_in_catalog(tmp_path):
    from jackal.idcams.executor import run_idcams

    cat = job_catalog(tmp_path)
    cmds = (DefineCluster(name="MY.KSDS", key_length=5, key_offset=0, record_size=80),)
    rc = run_idcams(cmds, DdEnvironment(()), cat)
    assert rc == 0
    assert cat.resolve("MY.KSDS").label == KsdsLabel(80, 0, 5)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_maxcc_sets_value_when_condition_met(tmp_path):
    from jackal.idcams.executor import run_idcams

    cat = job_catalog(tmp_path)
    # Delete missing → maxcc=8; IF MAXCC LE 8 → SET MAXCC=0
    cmds = (
        Delete(("GHOST.DS",), purge=False),
        If(Condition(Cc.MAXCC, CcOp.LE, 8), (SetCc(Cc.MAXCC, 0),), ()),
    )
    rc = run_idcams(cmds, DdEnvironment(()), cat)
    assert rc == 0


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_maxcc_does_not_set_when_condition_not_met(tmp_path):
    from jackal.idcams.executor import run_idcams

    cat = job_catalog(tmp_path)
    # Delete missing → maxcc=8; IF MAXCC LT 8 → not met (8 < 8 is false)
    cmds = (
        Delete(("GHOST.DS",), purge=False),
        If(Condition(Cc.MAXCC, CcOp.LT, 8), (SetCc(Cc.MAXCC, 0),), ()),
    )
    rc = run_idcams(cmds, DdEnvironment(()), cat)
    assert rc == 8


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_maxcc_all_operators(tmp_path):
    from jackal.idcams.executor import run_idcams

    cat = job_catalog(tmp_path)

    def after_rc_8(op: str, value: int) -> int:
        cmds = (
            Delete(("GHOST.DS",), purge=False),
            If(Condition(Cc.MAXCC, CcOp(op), value), (SetCc(Cc.MAXCC, 0),), ()),
        )
        return run_idcams(cmds, DdEnvironment(()), cat)

    assert [
        after_rc_8("GE", 8),
        after_rc_8("GT", 4),
        after_rc_8("EQ", 8),
        after_rc_8("NE", 0),
        after_rc_8("GT", 8),
        after_rc_8("EQ", 4),
    ] == [0, 0, 0, 0, 8, 8]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_set_maxcc_overrides_accumulated_rc(tmp_path):
    from jackal.idcams.executor import run_idcams

    cat = job_catalog(tmp_path)
    # Delete missing -> maxcc=8; a bare SET MAXCC=0 forcibly overrides it,
    # same idempotency idiom real CardDemo JCL uses so a missing dataset
    # doesn't fail a step that's about to (re)DEFINE it anyway.
    cmds = (
        Delete(("GHOST.DS",), purge=False),
        SetCc(Cc.MAXCC, 0),
    )
    rc = run_idcams(cmds, DdEnvironment(()), cat)
    assert rc == 0


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_lastcc_tests_immediately_preceding_command_rc(tmp_path):
    from jackal.idcams.executor import run_idcams

    cat = job_catalog(tmp_path)
    cmds = (
        Delete(("GHOST.DS",), purge=False),  # missing -> rc 8, lastcc=8, maxcc=8
        If(Condition(Cc.LASTCC, CcOp.EQ, 8), (SetCc(Cc.MAXCC, 0),), ()),
    )
    rc = run_idcams(cmds, DdEnvironment(()), cat)
    assert rc == 0


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_lastcc_reflects_only_the_most_recent_command_not_running_maxcc(tmp_path):
    """LASTCC and MAXCC are genuinely distinct: a later, successful command
    resets LASTCC to 0 even though MAXCC still remembers an earlier
    failure. A test asserting against the wrong counter would give 8
    here instead of 5."""
    from jackal.idcams.executor import run_idcams

    cat = job_catalog(tmp_path)
    cmds = (
        Delete(("GHOST.DS",), purge=False),  # missing -> rc 8; lastcc=8, maxcc=8
        DefineCluster(
            name="MY.KSDS", key_length=5, key_offset=0, record_size=80
        ),  # succeeds -> rc 0; lastcc=0, maxcc stays 8 (max(8,0))
        If(Condition(Cc.LASTCC, CcOp.EQ, 0), (SetCc(Cc.MAXCC, 5),), ()),
    )
    rc = run_idcams(cmds, DdEnvironment(()), cat)
    assert rc == 5


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_set_maxcc_does_not_change_lastcc(tmp_path):
    """Per the manual: 'Setting MAXCC does not affect LASTCC.' A SET
    MAXCC=n between two functional commands must not corrupt the next
    IF LASTCC test."""
    from jackal.idcams.executor import run_idcams

    cat = job_catalog(tmp_path)
    cmds = (
        Delete(("GHOST.DS",), purge=False),  # missing -> rc 8; lastcc=8, maxcc=8
        SetCc(Cc.MAXCC, 0),  # maxcc forced to 0; lastcc still 8
        If(Condition(Cc.LASTCC, CcOp.EQ, 8), (SetCc(Cc.MAXCC, 5),), ()),
    )
    rc = run_idcams(cmds, DdEnvironment(()), cat)
    assert rc == 5


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_purge_flag_deletes_existing_dsn_same_as_without_purge(tmp_path):
    """No retention/expiration tracking exists in this simulated catalog
    today, so PURGE is currently a documented no-op: parsing/execution
    must not crash, and behavior matches an equivalent non-PURGE delete."""
    from jackal.idcams.executor import run_idcams

    upload(tmp_path, "MY.DS", b"")
    cat = job_catalog(tmp_path)
    cmds = (Delete(("MY.DS",), purge=True),)
    rc = run_idcams(cmds, DdEnvironment(()), cat)
    assert rc == 0


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_purge_set_define_sequence_executes(tmp_path):
    """A representative (hand-written) multi-statement block in the shape
    CBEXPORT.jcl's STEP01 uses: DELETE...CLUSTER PURGE, standalone
    SET MAXCC=0, then DEFINE CLUSTER with DATA/INDEX trailers and several
    ignored SMS-style params. This is a fast unit test with NO real-file
    read -- the genuine end-to-end test that reads the real CBEXPORT.jcl
    bytes through the jcl-bridge lives in
    tests/integration/test_idcams_execution_carddemo_e2e.py."""
    from jackal.idcams.executor import run_idcams
    from jackal.idcams.parser import parse_idcams

    text = (
        "  DELETE AWS.M2.CARDDEMO.EXPORT.DATA CLUSTER PURGE\n"
        "  SET MAXCC = 0\n"
        "  DEFINE CLUSTER (NAME(AWS.M2.CARDDEMO.EXPORT.DATA) -\n"
        "                  INDEXED -\n"
        "                  KEYS(4 28) -\n"
        "                  RECORDSIZE(500 500) -\n"
        "                  CYLINDERS(10 5) -\n"
        "                  FREESPACE(10 10) -\n"
        "                  SHAREOPTIONS(2 3)) -\n"
        "         DATA (NAME(AWS.M2.CARDDEMO.EXPORT.DATA.DATA)) -\n"
        "         INDEX (NAME(AWS.M2.CARDDEMO.EXPORT.DATA.INDEX))\n"
    )
    cmds = parse_idcams(text)
    cat = job_catalog(tmp_path)
    rc = run_idcams(cmds, DdEnvironment(()), cat)
    assert rc == 0
    assert cat.resolve("AWS.M2.CARDDEMO.EXPORT.DATA").label == KsdsLabel(500, 28, 4)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_duplicate_dsn_returns_12(tmp_path):
    from jackal.idcams.executor import run_idcams

    cat = job_catalog(tmp_path)
    cmds = (
        DefineCluster(name="MY.KSDS", key_length=5, key_offset=0, record_size=80),
        DefineCluster(name="MY.KSDS", key_length=5, key_offset=0, record_size=80),
    )
    rc = run_idcams(cmds, DdEnvironment(()), cat)
    assert rc == 12


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_reads_a_variable_input_record_by_record_at_each_record_length(
    tmp_path,
):
    from cobol_asg.file_enums import OpenMode
    from interpreter.cobol.file_drivers import IndexedDriver
    from jackal.idcams.executor import run_idcams

    upload(
        tmp_path,
        "IN.V",
        b"\x00\x08\x00\x00AAA1\x00\x0b\x00\x00BBB2xyz",
        SequentialLabel(RecordFormat.VB, 104),
    )
    cat = job_catalog(tmp_path)
    run_idcams(
        (DefineCluster(name="OUT.KSDS", key_length=3, key_offset=0, record_size=9),),
        DdEnvironment(()),
        cat,
    )
    dds = (
        DD(
            DdName("INF"),
            DirectDSN(literal("IN.V")),
            Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP),
        ),
        DD(
            DdName("OUT"),
            DirectDSN(literal("OUT.KSDS")),
            Disp(DispStatus.OLD, DispNormal.KEEP, DispNormal.KEEP),
        ),
    )
    env = allocated(ProgramStep(StepName("S1"), ProgramRef("IDCAMS"), dds), cat)
    copied = run_idcams((Repro(infile_dd="INF", outfile_dd="OUT"),), env, cat)
    drv = IndexedDriver()
    drv.open(cat.resolve("OUT.KSDS").path, OpenMode.INPUT, 9, 0, 3)
    loaded = (drv.read_key(b"AAA").data, drv.read_key(b"BBB").data)
    drv.close()
    assert (copied, loaded[0][:4], loaded[1][:7]) == (0, b"AAA1", b"BBB2xyz")


def _gdg(name: str, limit: int, extended: bool = False) -> DefineGdg:
    return DefineGdg(
        name, limit, Empty.NOEMPTY, Scratch.SCRATCH, GdgOrder.LIFO, extended
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_gdg_catalogs_an_empty_base_once_within_its_limit(tmp_path):
    """AMS ch. 15: the base is cataloged with no generations and survives the job;
    a duplicate name (as GDG or cluster) or a LIMIT outside 1-255 (1-999 with
    EXTENDED) ends the command with condition code 12."""
    from jackal.idcams.executor import run_idcams

    cat = job_catalog(tmp_path)
    rcs = tuple(
        run_idcams((cmd,), DdEnvironment(()), cat)
        for cmd in (
            _gdg("A.GDG", 5),
            _gdg("A.GDG", 5),
            DefineCluster(name="A.GDG", key_length=1, key_offset=0, record_size=8),
            _gdg("B.GDG", 0),
            _gdg("B.GDG", 256),
            _gdg("B.GDG", 999, extended=True),
            _gdg("C.GDG", 1000, extended=True),
        )
    )
    assert rcs == (0, 12, 12, 12, 12, 0, 12)
    later = job_catalog(tmp_path)
    assert (later.gdg("A.GDG"), later.gdg("C.GDG")) == (
        GdgBase("A.GDG", 5, Empty.NOEMPTY, Scratch.SCRATCH, GdgOrder.LIFO, ()),
        NotCataloged(),
    )


def _verify_env(tmp_path):
    from jackal.idcams.executor import run_idcams

    upload(tmp_path, "SEQ.PS", b"", SequentialLabel(RecordFormat.FB, 4))
    cat = job_catalog(tmp_path)
    run_idcams(
        (DefineCluster(name="A.KSDS", key_length=3, key_offset=0, record_size=9),),
        DdEnvironment(()),
        cat,
    )
    dds = (
        DD(
            DdName("KSDS"),
            DirectDSN(literal("A.KSDS")),
            Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP),
        ),
    )
    env = allocated(ProgramStep(StepName("S1"), ProgramRef("IDCAMS"), dds), cat)
    return env, cat


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_verify_succeeds_on_a_vsam_object_and_ends_12_otherwise(tmp_path):
    """Record V6: a KSDS by DD or by name verifies with 0; a non-VSAM dataset,
    an uncataloged name or a missing DD ends the command with 12."""
    from jackal.idcams.executor import run_idcams
    from jackal.idcams.parser import parse_idcams

    env, cat = _verify_env(tmp_path)
    rcs = tuple(
        run_idcams(parse_idcams(text), env, cat)
        for text in (
            " VFY FILE(KSDS)\n",
            " VERIFY DATASET(A.KSDS) RECOVER\n",
            " VFY DS(SEQ.PS)\n",
            " VFY DS(NO.SUCH)\n",
            " VFY FILE(NODD)\n",
        )
    )
    assert rcs == (0, 0, 12, 12, 12)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_modal_commands_follow_the_condition_codes(tmp_path):
    """Records V3-V5: the retry idiom recovers; a branch not taken changes
    nothing; ELSE runs when the test fails; SET caps at 16, a LASTCC above
    MAXCC raises it, and 16 ends the stream; CANCEL ends it with MAXCC."""
    from jackal.idcams.executor import run_idcams
    from jackal.idcams.parser import parse_idcams

    env, cat = _verify_env(tmp_path)

    def rc(text: str) -> int:
        return run_idcams(parse_idcams(text), env, cat)

    retry = (
        " VFY FILE(NODD)\n"
        " IF LASTCC=12 THEN DO\n"
        "    SET MAXCC=0\n"
        "    VFY FILE(KSDS)\n"
        " END\n"
    )
    untaken = " DELETE GHOST.DS\n VFY FILE(KSDS)\n IF LASTCC=12 THEN SET MAXCC=0\n"
    otherwise = " VFY FILE(KSDS)\n IF LASTCC=12 THEN SET MAXCC=5\n ELSE SET MAXCC=7\n"
    capped = " SET LASTCC=4\n SET LASTCC=20\n DELETE SEQ.PS\n"
    cancelled = " DELETE GHOST.DS\n CANCEL\n DELETE SEQ.PS\n"
    assert (rc(retry), rc(untaken), rc(otherwise), rc(capped), rc(cancelled)) == (
        0,
        8,
        7,
        16,
        8,
    )
    assert cat.resolve("SEQ.PS").dsn == "SEQ.PS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_from_dummy_empties_its_output_and_into_dummy_keeps_its_input(tmp_path):
    """vqa item 5: DUMMY reads as an immediate end of file, so REPRO from it
    leaves a sequential output empty; REPRO into DUMMY discards every record."""
    from jackal.idcams.executor import run_idcams
    from jackal.model import DummyDSN, NotCoded

    upload(tmp_path, "FULL.PS", b"AAAABBBB", SequentialLabel(RecordFormat.FB, 4))
    upload(tmp_path, "KEEP.PS", b"CCCCDDDD", SequentialLabel(RecordFormat.FB, 4))
    cat = job_catalog(tmp_path)
    old = Disp(DispStatus.OLD, DispNormal.KEEP, DispNormal.KEEP)
    dds = (
        DD(DdName("NOTHING"), DummyDSN(), NotCoded()),
        DD(DdName("FULL"), DirectDSN(literal("FULL.PS")), old),
        DD(DdName("KEEP"), DirectDSN(literal("KEEP.PS")), old),
        DD(DdName("DISCARD"), DummyDSN(), NotCoded()),
    )
    env = allocated(ProgramStep(StepName("S1"), ProgramRef("IDCAMS"), dds), cat)
    rcs = (
        run_idcams((Repro(infile_dd="NOTHING", outfile_dd="FULL"),), env, cat),
        run_idcams((Repro(infile_dd="KEEP", outfile_dd="DISCARD"),), env, cat),
    )
    assert rcs == (0, 0)
    assert (
        cat.resolve("FULL.PS").path.read_bytes(),
        cat.resolve("KEEP.PS").path.read_bytes(),
    ) == (b"", b"CCCCDDDD")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_repro_reads_a_concatenated_input_member_after_member(tmp_path):
    """AMS p. 314: REPRO's input can be a sequential concatenation, each member
    read at its own label; the output cannot be one of its members. A member whose
    label is pending ends the command with 12, as a single input's does."""
    from catnip.labels import LabelPending
    from jackal.idcams.executor import run_idcams
    from jackal.model import ConcatMember

    fb4 = SequentialLabel(RecordFormat.FB, 4)
    upload(tmp_path, "ONE.PS", b"AAAABBBB", fb4)
    upload(tmp_path, "TWO.PS", b"CCCC", fb4)
    upload(tmp_path, "PEND.PS", b"", LabelPending())
    upload(tmp_path, "OUT.PS", b"", fb4)
    cat = job_catalog(tmp_path)
    old = Disp(DispStatus.OLD, DispNormal.KEEP, DispNormal.KEEP)

    def named(ddname: str, dsn: str, *more: str) -> DD:
        members = tuple(ConcatMember(DirectDSN(literal(m)), old) for m in more)
        return DD(DdName(ddname), DirectDSN(literal(dsn)), old, concatenated=members)

    dds = (
        named("IN", "ONE.PS", "TWO.PS"),
        named("HALF", "ONE.PS", "PEND.PS"),
        named("OUT", "OUT.PS"),
        named("AGAIN", "TWO.PS"),
    )
    env = allocated(ProgramStep(StepName("S1"), ProgramRef("IDCAMS"), dds), cat)
    rcs = tuple(
        run_idcams((Repro(infile_dd=i, outfile_dd=o),), env, cat)
        for i, o in (("IN", "OUT"), ("HALF", "AGAIN"), ("IN", "AGAIN"))
    )
    assert rcs == (0, 12, 12)
    assert (
        cat.resolve("OUT.PS").path.read_bytes(),
        cat.resolve("TWO.PS").path.read_bytes(),
    ) == (b"AAAABBBBCCCC", b"CCCC")
