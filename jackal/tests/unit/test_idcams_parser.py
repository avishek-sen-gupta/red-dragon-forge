"""Tests for IDCAMS control-language parser."""

from __future__ import annotations

import pytest
import lark.exceptions

from jackal.idcams.parser import parse_idcams
from jackal.idcams.commands import Delete, DefineCluster, Repro, IfMaxcc
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
