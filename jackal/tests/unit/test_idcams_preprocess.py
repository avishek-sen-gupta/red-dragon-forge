"""Tests for the + (mid-token) continuation preprocessing pass."""

from __future__ import annotations

from jackal.idcams.preprocess import join_plus_continuations
from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_plus_continuation_joins_with_no_inserted_characters():
    text = "NAME(AWS.M2.CARDDEMO.VERYLONGDATASETNAME+\n   .REST)\n"
    result = join_plus_continuations(text)
    assert result == "NAME(AWS.M2.CARDDEMO.VERYLONGDATASETNAME.REST)\n"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_hyphen_continuation_is_untouched_by_plus_preprocessing():
    text = "DEFINE CLUSTER (NAME(A.B) -\n  KEYS(3 0))\n"
    result = join_plus_continuations(text)
    assert result == text
