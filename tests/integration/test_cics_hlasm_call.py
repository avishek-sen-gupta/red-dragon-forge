"""A CICS COBOL transaction in a forge package calls an HLASM subprogram that waits on the host clock."""

from __future__ import annotations

from pathlib import Path

from catnip.system_catalog import SystemCatalog
from cics.coprocessor import build_cics_spec
from cics.screen.driver import Ended, Returned
from cics.screen.payload import SendTextPayload
from cics.tn3270.region import CICS_COPYBOOKS, assemble_region
from interpreter.frontends import get_hlasm_parser
from litter.build import build
from litter.hlasm_sources import HlasmSources
from litter.open import open_package
from litter.transaction import Transaction

from red_dragon_forge.cics_command import region_builtins
from tests.integration.forge_cobol_helpers import make_parser

_FIXTURES = Path(__file__).parent / "fixtures" / "cics_hlasm"
_CARDDEMO = Path(__file__).parents[2] / "vendor" / "carddemo" / "app"


def test_a_cics_transaction_calls_mvswait_and_waits(
    tmp_path: Path, bridge_jar: str
) -> None:
    package = build(
        name="waits",
        programs=("WAITCICS", "MVSWAIT"),
        link=("WAITCICS", "MVSWAIT"),
        sources={"WAITCICS": _FIXTURES / "WAITCICS.cbl"},
        hlasm=HlasmSources(
            {"MVSWAIT": _CARDDEMO / "asm" / "MVSWAIT.asm"},
            get_hlasm_parser((_CARDDEMO / "maclib",)),
        ),
        parser=make_parser(bridge_jar),
        specs=(build_cics_spec(),),
        copybook_dirs=(CICS_COPYBOOKS,),
        work_dir=tmp_path / "work",
        out_dir=tmp_path / "out",
        transactions=(Transaction("WAIT", "WAITCICS"),),
        files=(),
        mapsets={},
        tolerant=False,
    )
    served = assemble_region(
        open_package(package),
        SystemCatalog(tmp_path / "system"),
        permit_unresolved_call_targets=False,
        other_builtins=region_builtins({}),
    )

    assert served.driver.start("WAIT") == Ended(
        (SendTextPayload("WAITED".ljust(12)),), Returned()
    )
