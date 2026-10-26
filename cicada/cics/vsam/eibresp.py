"""Map the engine's neutral access-method outcome to CICS EIBRESP codes.

The shared red-dragon access-method engine returns a neutral ``AccessCondition``
(language-agnostic). CICS file control speaks EIBRESP. This module is the CICS
adapter's translation table.

Decision A (file-state conditions): in CICS the program never opens/closes files
-- file state is an FCT/enable concern the adapter decides BEFORE calling a driver
(returning RESP_DISABLED itself). So a driver-level file-state condition
(FILE_NOT_FOUND / NOT_OPEN / WRITE_NOT_PERMITTED / ATTRIBUTE_CONFLICT / BOUNDARY_VIOLATION /
OPEN_MODE_NOT_SUPPORTED) means an internal inconsistency,
not a normal program-visible condition -> RESP_IOERR. Mapping a driver's internal
lifecycle state to a real CICS condition (NOTOPEN/INVREQ) would mislabel an adapter
bug as something the program would mishandle.
"""

from __future__ import annotations

from infrastructure.zos.access_methods.access_result import AccessCondition

RESP_NORMAL = 0
RESP_NOTFND = 13
RESP_DUPREC = 14
RESP_DUPKEY = 15
RESP_INVREQ = 16
RESP_IOERR = 17
RESP_ENDFILE = 20
RESP_DISABLED = 84

_EIBRESP: dict[AccessCondition, int] = {
    AccessCondition.OK: RESP_NORMAL,
    AccessCondition.DUPLICATES_FOLLOW: RESP_DUPKEY,
    AccessCondition.END_OF_FILE: RESP_ENDFILE,
    AccessCondition.NOT_FOUND: RESP_NOTFND,
    AccessCondition.DUPLICATE_KEY: RESP_DUPREC,
    AccessCondition.FILE_NOT_FOUND: RESP_IOERR,
    AccessCondition.NOT_OPEN: RESP_IOERR,
    AccessCondition.WRITE_NOT_PERMITTED: RESP_IOERR,
    AccessCondition.ATTRIBUTE_CONFLICT: RESP_IOERR,
    AccessCondition.BOUNDARY_VIOLATION: RESP_IOERR,
    AccessCondition.OPEN_MODE_NOT_SUPPORTED: RESP_IOERR,
}


def to_eibresp(condition: AccessCondition) -> int:
    """Translate a neutral access-method condition to a CICS EIBRESP code.

    Raises KeyError on an unmapped condition (fail loud — the table is exhaustive
    and a new AccessCondition must be added here deliberately).
    """
    return _EIBRESP[condition]
