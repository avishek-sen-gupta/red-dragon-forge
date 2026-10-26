"""CICS file control's RESP for each access-method condition."""

from cics.vsam.eibresp import to_eibresp
from infrastructure.zos.access_methods.access_result import AccessCondition
from interpreter.cobol.features import CobolFeature
from tests.covers import covers


@covers(CobolFeature.EXEC_CICS)
def test_more_duplicates_follow_is_resp_15():
    assert to_eibresp(AccessCondition.DUPLICATES_FOLLOW) == 15
