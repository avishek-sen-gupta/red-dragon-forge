from __future__ import annotations

import pytest

from red_dragon_forge.coprocessor import CoprocessorSpec


def test_default_source_prepass_is_identity():
    spec = CoprocessorSpec(name="noop", make_strategy=lambda: object())
    assert spec.source_prepass("       IDENTIFICATION DIVISION.") == (
        "       IDENTIFICATION DIVISION."
    )


def test_defaults_are_non_execution_owning_with_no_cics_text_parser():
    spec = CoprocessorSpec(name="noop", make_strategy=lambda: object())
    assert spec.owns_execution is False
    assert spec.cics_text_parser is None


def test_spec_is_frozen():
    import dataclasses

    spec = CoprocessorSpec(name="noop", make_strategy=lambda: object())
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.name = "renamed"
