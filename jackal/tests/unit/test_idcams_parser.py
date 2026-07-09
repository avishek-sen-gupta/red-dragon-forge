"""Tests for IDCAMS control-language parser."""

from __future__ import annotations

import pytest
import lark.exceptions

from jackal.idcams.parser import parse_idcams
from jackal.idcams.commands import Delete, DefineCluster, Repro, IfMaxcc, SetMaxcc
from tests.covers import covers, NotLanguageFeature


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_delete_and_if():
    cmds = parse_idcams(
        "   DELETE A.B.KSDS -\n          CLUSTER\n"
        "   IF MAXCC LE 08 THEN SET MAXCC = 0\n"
    )
    assert cmds[0] == Delete(dsn="A.B.KSDS")
    assert cmds[1] == IfMaxcc(op="LE", value=8, set_value=0)


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
    assert cmds[0] == SetMaxcc(value=0)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_if_lastcc_bare_equals():
    """Real DEFGDGB.jcl idiom: IF LASTCC=n (bare '=', not the EQ keyword)
    tests the immediately-preceding command's own rc, not the running
    MAXCC."""
    cmds = parse_idcams("   IF LASTCC=12 THEN SET MAXCC=0\n")
    assert cmds[0] == IfMaxcc(op="EQ", value=12, set_value=0, test_field="LASTCC")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_if_maxcc_defaults_test_field_to_maxcc():
    """Existing IF MAXCC form must still default test_field to MAXCC --
    backward compatible with every already-parsed real job."""
    cmds = parse_idcams("   IF MAXCC LE 08 THEN SET MAXCC = 0\n")
    assert cmds[0] == IfMaxcc(op="LE", value=8, set_value=0, test_field="MAXCC")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_lastcc_line_with_trailing_whitespace():
    """A hand-written LASTCC line matching the shape DEFGDGB.jcl uses
    (bare '=', trailing padding). This is NOT a real-file test -- the
    surrounding DEFINE GENERATIONDATAGROUP verb in that real file isn't
    supported by this (minimal, execution-wired) grammar, so DEFGDGB's
    actual SYSIN block cannot be parsed end-to-end here at all. This only
    pins the isolated LASTCC-line grammar."""
    cmds = parse_idcams(
        "   IF LASTCC=12 THEN SET MAXCC=0                                            \n"
    )
    assert cmds[0] == IfMaxcc(op="EQ", value=12, set_value=0, test_field="LASTCC")


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
    assert cmds[1] == SetMaxcc(value=0)
