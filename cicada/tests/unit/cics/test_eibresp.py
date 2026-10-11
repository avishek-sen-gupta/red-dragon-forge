from interpreter.cobol.access_result import AccessCondition

from tests.covers import covers, NotLanguageFeature
from cics.vsam.eibresp import (
    RESP_DUPREC,
    RESP_ENDFILE,
    RESP_IOERR,
    RESP_NORMAL,
    RESP_NOTFND,
    to_eibresp,
)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_data_conditions_map_to_their_codes():
    assert to_eibresp(AccessCondition.OK) == RESP_NORMAL
    assert to_eibresp(AccessCondition.END_OF_FILE) == RESP_ENDFILE
    assert to_eibresp(AccessCondition.NOT_FOUND) == RESP_NOTFND
    assert to_eibresp(AccessCondition.DUPLICATE_KEY) == RESP_DUPREC


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_file_state_conditions_map_to_ioerr():
    # Decision A: a driver-level file-state condition on an FCT-enabled file is an
    # internal inconsistency (the adapter gates FCT/enable first), not a normal
    # program-visible CICS condition -> IOERR.
    for c in (
        AccessCondition.FILE_NOT_FOUND,
        AccessCondition.NOT_OPEN,
        AccessCondition.WRITE_NOT_PERMITTED,
        AccessCondition.ATTRIBUTE_CONFLICT,
    ):
        assert to_eibresp(c) == RESP_IOERR


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_mapping_is_exhaustive():
    # Every neutral condition must be mapped (fail loud on an unmapped one).
    for c in AccessCondition:
        assert isinstance(to_eibresp(c), int)
