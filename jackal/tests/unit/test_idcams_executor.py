"""Tests for the IDCAMS executor."""

from __future__ import annotations

from jackal.allocation import DdEnvironment
from jackal.gdg import Empty, GdgBase, Scratch
from jackal.idcams.commands import (
    DefineCluster,
    DefineGdg,
    Delete,
    IfMaxcc,
    Repro,
    SetMaxcc,
)
from jackal.system_catalog import NotCataloged
from jackal.labels import KsdsLabel, RecordFormat, SequentialLabel
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
        IfMaxcc(op="EQ", value=12, set_value=99, test_field="LASTCC"),
    )
    assert run_idcams(cmds, env, cat) == 99


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_existing_dsn_returns_0(tmp_path):
    from jackal.idcams.executor import run_idcams

    upload(tmp_path, "MY.DS", b"")
    cat = job_catalog(tmp_path)
    cmds = (Delete(dsn="MY.DS"),)
    rc = run_idcams(cmds, DdEnvironment(()), cat)
    assert rc == 0


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_missing_dsn_returns_8(tmp_path):
    from jackal.idcams.executor import run_idcams

    cat = job_catalog(tmp_path)
    cmds = (Delete(dsn="GHOST.DS"),)
    rc = run_idcams(cmds, DdEnvironment(()), cat)
    assert rc == 8


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
    # Delete missing → maxcc=8; IfMaxcc LE 8 → set maxcc=0
    cmds = (
        Delete(dsn="GHOST.DS"),
        IfMaxcc(op="LE", value=8, set_value=0),
    )
    rc = run_idcams(cmds, DdEnvironment(()), cat)
    assert rc == 0


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_maxcc_does_not_set_when_condition_not_met(tmp_path):
    from jackal.idcams.executor import run_idcams

    cat = job_catalog(tmp_path)
    # Delete missing → maxcc=8; IfMaxcc LT 8 → not met (8 < 8 is false)
    cmds = (
        Delete(dsn="GHOST.DS"),
        IfMaxcc(op="LT", value=8, set_value=0),
    )
    rc = run_idcams(cmds, DdEnvironment(()), cat)
    assert rc == 8


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_maxcc_all_operators(tmp_path):
    from jackal.idcams.executor import run_idcams

    cat = job_catalog(tmp_path)

    def after_rc_8(op: str, value: int) -> int:
        cmds = (Delete(dsn="GHOST.DS"), IfMaxcc(op=op, value=value, set_value=0))
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
        Delete(dsn="GHOST.DS"),
        SetMaxcc(value=0),
    )
    rc = run_idcams(cmds, DdEnvironment(()), cat)
    assert rc == 0


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_lastcc_tests_immediately_preceding_command_rc(tmp_path):
    from jackal.idcams.executor import run_idcams

    cat = job_catalog(tmp_path)
    cmds = (
        Delete(dsn="GHOST.DS"),  # missing -> rc 8, lastcc=8, maxcc=8
        IfMaxcc(op="EQ", value=8, set_value=0, test_field="LASTCC"),
    )
    rc = run_idcams(cmds, DdEnvironment(()), cat)
    assert rc == 0


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_lastcc_reflects_only_the_most_recent_command_not_running_maxcc(tmp_path):
    """LASTCC and MAXCC are genuinely distinct: a later, successful command
    resets LASTCC to 0 even though MAXCC still remembers an earlier
    failure. A test asserting against the wrong counter would give 8
    here instead of 99."""
    from jackal.idcams.executor import run_idcams

    cat = job_catalog(tmp_path)
    cmds = (
        Delete(dsn="GHOST.DS"),  # missing -> rc 8; lastcc=8, maxcc=8
        DefineCluster(
            name="MY.KSDS", key_length=5, key_offset=0, record_size=80
        ),  # succeeds -> rc 0; lastcc=0, maxcc stays 8 (max(8,0))
        IfMaxcc(op="EQ", value=0, set_value=99, test_field="LASTCC"),
    )
    rc = run_idcams(cmds, DdEnvironment(()), cat)
    assert rc == 99


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_set_maxcc_does_not_change_lastcc(tmp_path):
    """Per the manual: 'Setting MAXCC does not affect LASTCC.' A SET
    MAXCC=n between two functional commands must not corrupt the next
    IF LASTCC test."""
    from jackal.idcams.executor import run_idcams

    cat = job_catalog(tmp_path)
    cmds = (
        Delete(dsn="GHOST.DS"),  # missing -> rc 8; lastcc=8, maxcc=8
        SetMaxcc(value=0),  # maxcc forced to 0; lastcc still 8
        IfMaxcc(op="EQ", value=8, set_value=99, test_field="LASTCC"),
    )
    rc = run_idcams(cmds, DdEnvironment(()), cat)
    assert rc == 99


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_purge_flag_deletes_existing_dsn_same_as_without_purge(tmp_path):
    """No retention/expiration tracking exists in this simulated catalog
    today, so PURGE is currently a documented no-op: parsing/execution
    must not crash, and behavior matches an equivalent non-PURGE delete."""
    from jackal.idcams.executor import run_idcams

    upload(tmp_path, "MY.DS", b"")
    cat = job_catalog(tmp_path)
    cmds = (Delete(dsn="MY.DS", purge=True),)
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
    return DefineGdg(name, limit, Empty.NOEMPTY, Scratch.SCRATCH, extended)


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
        GdgBase("A.GDG", 5, Empty.NOEMPTY, Scratch.SCRATCH, ()),
        NotCataloged(),
    )
