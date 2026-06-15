"""
tests/unit/test_field_meta_validation.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
dclgen/data_layout category agreement (squall-aim): a host var carrying dclgen
field_meta must match ProLeap's parsed data_layout category, else fail loud.
"""

from __future__ import annotations

import pytest

from squall.binding import FieldMetaMismatch, validate_field_meta


def _scalar_layout() -> dict:
    return {
        "ACCT-ID": {"offset": 0, "length": 4, "category": "BINARY"},
        "ACCT-BAL": {"offset": 4, "length": 4, "category": "COMP3"},
        "ACCT-NAME": {"offset": 8, "length": 20, "category": "ALPHANUMERIC"},
    }


def _varchar_layout() -> dict:
    return {
        "EMP-NAME": {"offset": 0, "length": 11, "category": "ALPHANUMERIC"},
        "EMP-NAME-LEN": {"offset": 0, "length": 2, "category": "BINARY"},
        "EMP-NAME-TEXT": {"offset": 2, "length": 9, "category": "ALPHANUMERIC"},
    }


def test_scalar_categories_agree_does_not_raise():
    field_meta = {
        "ACCT-ID": {"category": "BINARY"},
        "ACCT-BAL": {"category": "COMP3"},
        "ACCT-NAME": {"category": "ALPHANUMERIC"},
    }
    validate_field_meta(_scalar_layout(), field_meta)  # no raise


def test_scalar_category_mismatch_raises():
    field_meta = {"ACCT-BAL": {"category": "BINARY"}}  # layout says COMP3
    with pytest.raises(FieldMetaMismatch):
        validate_field_meta(_scalar_layout(), field_meta)


def test_varchar_children_agree_does_not_raise():
    field_meta = {
        "EMP-NAME": {
            "category": "VARCHAR",
            "len_var": "EMP-NAME-LEN",
            "text_var": "EMP-NAME-TEXT",
        }
    }
    validate_field_meta(_varchar_layout(), field_meta)  # no raise


def test_varchar_len_child_not_binary_raises():
    layout = _varchar_layout()
    layout["EMP-NAME-LEN"]["category"] = "ALPHANUMERIC"  # should be BINARY
    field_meta = {
        "EMP-NAME": {
            "category": "VARCHAR",
            "len_var": "EMP-NAME-LEN",
            "text_var": "EMP-NAME-TEXT",
        }
    }
    with pytest.raises(FieldMetaMismatch):
        validate_field_meta(layout, field_meta)


def test_field_absent_from_layout_raises_keyerror():
    field_meta = {"GHOST": {"category": "BINARY"}}
    with pytest.raises(KeyError):
        validate_field_meta(_scalar_layout(), field_meta)


def test_empty_field_meta_is_noop():
    validate_field_meta(_scalar_layout(), {})  # no raise
