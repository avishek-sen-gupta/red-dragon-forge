"""CICS file control's RESP for each access-method condition."""

from cics.vsam.eibresp import to_eibresp
from interpreter.cobol.features import CobolFeature
from interpreter.record_io.access_result import AccessCondition
from tests.covers import covers


@covers(CobolFeature.EXEC_CICS)
def test_more_duplicates_follow_is_resp_15():
    assert to_eibresp(AccessCondition.DUPLICATES_FOLLOW) == 15
