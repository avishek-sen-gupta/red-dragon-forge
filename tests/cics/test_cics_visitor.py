"""EXEC CICS command text parsing: verb plus the options each command allows."""

from cobble.cics.cics_visitor import parse_exec_cics_text


def test_link_dpl_form() -> None:
    verb, opts = parse_exec_cics_text(
        "EXEC CICS LINK PROGRAM(WS-PROG) COMMAREA(WS-AREA) LENGTH(WS-LEN) END-EXEC"
    )
    assert verb == "LINK"
    assert opts["PROGRAM"].text == "WS-PROG"
    assert opts["COMMAREA"].text == "WS-AREA"


def test_link_exci_form_with_applid_and_retcode() -> None:
    """The external CICS interface form, issued from a program outside CICS.

    APPLID names the region to link into and RETCODE receives the interface's
    own return code; both are options of LINK that only the EXCI form uses.
    """
    verb, opts = parse_exec_cics_text(
        "EXEC CICS LINK PROGRAM(TARGET-PROGRAM) TRANSID(TARGET-TRANSID) "
        "APPLID(TARGET-SYSTEM) COMMAREA(WS-AREA) LENGTH(WS-LEN) "
        "RETCODE(WS-RETCODE) SYNCONRETURN END-EXEC"
    )
    assert verb == "LINK"
    assert opts["PROGRAM"].text == "TARGET-PROGRAM"
    assert opts["APPLID"].text == "TARGET-SYSTEM"
    assert opts["RETCODE"].text == "WS-RETCODE"
    assert opts["TRANSID"].text == "TARGET-TRANSID"
    assert "SYNCONRETURN" in opts
