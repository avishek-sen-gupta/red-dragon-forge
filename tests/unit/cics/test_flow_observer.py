from dataclasses import FrozenInstanceError
import pytest
from tests.covers import covers, NotLanguageFeature
from cics.flow_observer import CicsVerb, NullCicsFlowObserver


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cics_verb_is_frozen():
    v = CicsVerb(
        verb="SEND_MAP",
        program="PROG1",
        map_name="MAP1",
        mapset_name="SET1",
        xctl_target=None,
        transid=None,
    )
    with pytest.raises((FrozenInstanceError, AttributeError)):
        v.verb = "OTHER"  # type: ignore[misc]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cics_verb_optional_fields_default_none():
    v = CicsVerb(
        verb="XCTL",
        program="PROG1",
        map_name=None,
        mapset_name=None,
        xctl_target="PROG2",
        transid=None,
    )
    assert v.map_name is None
    assert v.transid is None
    assert v.xctl_target == "PROG2"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_null_observer_on_verb_is_noop():
    observer = NullCicsFlowObserver()
    v = CicsVerb(
        verb="SEND_MAP",
        program="PROG1",
        map_name="MAP1",
        mapset_name="SET1",
        xctl_target=None,
        transid=None,
    )
    assert observer.on_verb(v) is None
