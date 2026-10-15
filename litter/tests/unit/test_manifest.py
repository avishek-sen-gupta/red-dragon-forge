"""The manifest is the one thing litter serialises; its JSON reads back to an equal manifest."""

import pytest
from litter.cics_file import CicsFile
from litter.manifest import Manifest
from litter.transaction import Transaction
from pydantic import ValidationError


def test_manifest_round_trips_through_its_json() -> None:
    manifest = Manifest(
        programs=("MAINPGM", "MENUPGM"),
        coprocessors=("cics-conversational", "sql"),
        transactions=(Transaction("MAIN", "MAINPGM"), Transaction("MENU", "MENUPGM")),
        files=(CicsFile("ACCTFILE", "APP.ACCOUNT.KSDS"),),
        mapsets=("MAINSET",),
    )

    assert Manifest.model_validate_json(manifest.model_dump_json()) == manifest


def test_manifest_refuses_names_that_are_not_member_names() -> None:
    text = (
        '{"programs": ["MAINPGM"], "coprocessors": [], "files": [],'
        ' "transactions": [{"transid": "MAIN", "program": "../MAINPGM"}],'
        ' "mapsets": ["maps/x"]}'
    )

    with pytest.raises(ValidationError) as refused:
        Manifest.model_validate_json(text)

    assert [detail["loc"] for detail in refused.value.errors()] == [
        ("transactions", 0, "program"),
        ("mapsets", 0),
    ]
