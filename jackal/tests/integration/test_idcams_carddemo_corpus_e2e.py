"""Every IDCAMS SYSIN in the CardDemo corpus parses, and only the commands jackal does not yet run are left unexecuted."""

from __future__ import annotations

from pathlib import Path

import pytest
from jackal.idcams.commands import NotExecuted, Verb
from jackal.jcl.parser import parse_jcl
from jackal.model import DdName, ProgramRef, ProgramStep
from jackal.utilities import sysin_commands
from tests.covers import NotLanguageFeature, covers

_AIX_TOOLCHAIN = (Verb.DEFINE_ALTERNATEINDEX, Verb.DEFINE_PATH, Verb.BLDINDEX)


def _sysins(jcl: Path) -> tuple[tuple[str, ...], ...]:
    return tuple(
        dd.in_stream
        for step in parse_jcl(jcl.read_text(errors="replace")).steps
        if isinstance(step, ProgramStep) and step.pgm == ProgramRef("IDCAMS")
        for dd in step.dds
        if dd.ddname == DdName("SYSIN") and dd.in_stream
    )


@pytest.mark.carddemo_e2e
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_every_carddemo_idcams_sysin_parses_leaving_only_unmodelled_commands(
    carddemo_home: Path, jcl_bridge_jar: str
):
    """Record O1: of the 61 IDCAMS SYSINs, the narrow grammar parsed 39. All 61
    parse; the commands left NotExecuted are the alternate-index toolchain and
    the ESDS and RRDS clusters, which jackal does not yet run."""
    parsed = {
        jcl.name: tuple(sysin_commands(records) for records in _sysins(jcl))
        for jcl in sorted((carddemo_home / "jcl").iterdir())
    }
    not_executed = {
        name: verbs
        for name, steps in parsed.items()
        if (
            verbs := tuple(
                c.verb for cmds in steps for c in cmds if isinstance(c, NotExecuted)
            )
        )
    }
    assert sum(map(len, parsed.values())) == 61
    assert not_executed == {
        "CARDFILE.jcl": _AIX_TOOLCHAIN,
        "ESDSRRDS.jcl": (Verb.DEFINE_CLUSTER, Verb.DEFINE_CLUSTER),
        "TRANFILE.jcl": _AIX_TOOLCHAIN,
        "TRANIDX.jcl": _AIX_TOOLCHAIN,
        "XREFFILE.jcl": _AIX_TOOLCHAIN,
    }
