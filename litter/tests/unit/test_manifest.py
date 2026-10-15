"""The manifest is the one thing litter serialises; its JSON reads back to an equal manifest."""

from litter.cics_file import CicsFile
from litter.manifest import Manifest
from litter.transaction import Transaction


def test_manifest_round_trips_through_its_json() -> None:
    manifest = Manifest(
        programs=("MAINPGM", "MENUPGM"),
        coprocessors=("cics-conversational", "sql"),
        transactions=(Transaction("MAIN", "MAINPGM"), Transaction("MENU", "MENUPGM")),
        files=(CicsFile("ACCTFILE", "APP.ACCOUNT.KSDS"),),
        mapsets=("MAINSET",),
    )

    assert Manifest.model_validate_json(manifest.model_dump_json()) == manifest
