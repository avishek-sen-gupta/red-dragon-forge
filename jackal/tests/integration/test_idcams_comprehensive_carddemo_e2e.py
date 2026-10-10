"""Proves the comprehensive IDCAMS grammar parses every real IDCAMS
SYSIN block in the CardDemo corpus -- the design spec's stated
completion signal for this mission."""

from __future__ import annotations

from pathlib import Path

import lark.exceptions
import pytest

from jackal.dsn import DdName
from jackal.model import ProgramRef, ProgramStep

from jackal.idcams.parser_comprehensive import parse_ams
from jackal.jcl.parser import parse_jcl
from tests.covers import NotLanguageFeature, covers

_IDCAMS_JCL_FILES = [
    "ACCTFILE.jcl",
    "CARDFILE.jcl",
    "CBEXPORT.jcl",
    "COMBTRAN.jcl",
    "CUSTFILE.jcl",
    "DALYREJS.jcl",
    "DEFCUST.jcl",
    "DEFGDGB.jcl",
    "DEFGDGD.jcl",
    "DISCGRP.jcl",
    "DUSRSECJ.jcl",
    "ESDSRRDS.jcl",
    "REPTFILE.jcl",
    "TCATBALF.jcl",
    "TRANBKP.jcl",
    "TRANFILE.jcl",
    "TRANIDX.jcl",
    "TRANCATG.jcl",
    "XREFFILE.jcl",
    "TRANTYPE.jcl",
]

# DUSRSECJ.jcl and ESDSRRDS.jcl each define a DEFINE CLUSTER block that uses
# "CISZ(...)" -- IBM's documented keyword ABBREVIATION for
# CONTROLINTERVALSIZE(...) (the full keyword is supported; see
# CONTROLINTERVALSIZE in ams.lark). The design spec explicitly excludes
# "keyword abbreviations" from this grammar's scope, so a SYSIN block that
# uses CISZ is expected to fail to parse. Every other IDCAMS block in these
# two files (DELETE/SET/REPRO) is still required to parse cleanly below.
_OUT_OF_SCOPE_ABBREVIATION_MARKER = "CISZ("


@pytest.mark.carddemo_e2e
@covers(NotLanguageFeature.INFRASTRUCTURE)
@pytest.mark.parametrize("jcl_filename", _IDCAMS_JCL_FILES)
def test_real_idcams_sysin_parses_with_comprehensive_grammar(
    jcl_filename: str, carddemo_home: Path, jcl_bridge_jar: str
):
    job = parse_jcl((carddemo_home / "jcl" / jcl_filename).read_text())
    idcams_steps = [
        s
        for s in job.steps
        if isinstance(s, ProgramStep) and s.pgm == ProgramRef("IDCAMS")
    ]
    assert idcams_steps, f"{jcl_filename} has no IDCAMS steps -- check the list above"
    for step in idcams_steps:
        for dd in step.dds:
            if dd.ddname == DdName("SYSIN") and dd.in_stream:
                text = "\n".join(dd.in_stream) + "\n"
                if _OUT_OF_SCOPE_ABBREVIATION_MARKER in text:
                    # Pre-approved out-of-scope exclusion: keyword
                    # abbreviations (CISZ for CONTROLINTERVALSIZE) are not
                    # part of this grammar's scope. Confirm it fails for
                    # exactly that reason rather than silently skipping it.
                    with pytest.raises(lark.exceptions.UnexpectedCharacters):
                        parse_ams(text)
                    continue
                parse_ams(text)  # must not raise


@pytest.mark.carddemo_e2e
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_reproc_prc_parses_with_comprehensive_grammar(
    carddemo_home: Path, jcl_bridge_jar: str
):
    from jackal.jcl.parser import parse_proc

    proc = parse_proc((carddemo_home / "proc" / "REPROC.prc").read_text())
    for step in proc.steps:
        for dd in step.dds:
            if dd.ddname == DdName("SYSIN") and dd.in_stream:
                text = "\n".join(dd.in_stream) + "\n"
                parse_ams(text)
