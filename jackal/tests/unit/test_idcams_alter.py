"""Tests for IDCAMS ALTER parsing into the comprehensive AST.

Covers the required positional `entry`, every parameter listed in the
design spec's Alter section (2026-07-08-idcams-comprehensive-grammar-
design.md, ~45 fields), the NULLIFY(...) sub-block's 9 sub-options, and
the one genuine structural mutual-exclusivity in this command: LOCK/UNLOCK
vs SUSPEND/RESUME (both operate on "catalog access state" per the manual
-- see the plan's ratified scoping decision, and ast_alter.py's module
docstring). Every other ON/OFF pair in ALTER is an ordinary freely-
repeatable last-wins parameter, per the same ratified scope.
"""

from __future__ import annotations

import pytest
from lark.exceptions import LarkError

from jackal.idcams.ast_alter import Alter, NullifySpec
from jackal.idcams.ast_values import Name, Retention
from jackal.idcams.parser_comprehensive import parse_ams
from tests.covers import NotLanguageFeature, covers

# =========================================================================
# Required positional entry
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_bare_entry():
    cmds = parse_ams("ALTER MY.DATASET.NAME\n")
    assert cmds[0] == Alter(entry=Name.parse("MY.DATASET.NAME"))


# =========================================================================
# NEWNAME (rename)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_newname():
    cmds = parse_ams("ALTER A NEWNAME(B)\n")
    assert cmds[0].new_name == Name.parse("B")


# =========================================================================
# ADDVOLUMES / REMOVEVOLUMES
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_addvolumes():
    cmds = parse_ams("ALTER A ADDVOLUMES(VOL001 VOL002)\n")
    assert cmds[0].add_volumes == ("VOL001", "VOL002")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_removevolumes():
    cmds = parse_ams("ALTER A REMOVEVOLUMES(VOL001)\n")
    assert cmds[0].remove_volumes == ("VOL001",)


# =========================================================================
# LOG / LOGSTREAMID / LOGREPLICATE -- independently settable
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_log():
    cmds = parse_ams("ALTER A LOG(ALL)\n")
    assert cmds[0].log == "ALL"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_log_redo():
    cmds = parse_ams("ALTER A LOG(REDO)\n")
    assert cmds[0].log == "REDO"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_logstreamid():
    cmds = parse_ams("ALTER A LOGSTREAMID(MY.LOGSTREAM)\n")
    assert cmds[0].log_stream_id == "MY.LOGSTREAM"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_logreplicate():
    cmds = parse_ams("ALTER A LOGREPLICATE\n")
    assert cmds[0].log_replicate is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_nologreplicate():
    cmds = parse_ams("ALTER A NOLOGREPLICATE\n")
    assert cmds[0].log_replicate is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_log_logstreamid_logreplicate_together():
    cmds = parse_ams("ALTER A LOG(UNDO) LOGSTREAMID(MY.LOGSTREAM) LOGREPLICATE\n")
    assert cmds[0].log == "UNDO"
    assert cmds[0].log_stream_id == "MY.LOGSTREAM"
    assert cmds[0].log_replicate is True


# =========================================================================
# NULLIFY(...) sub-block
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_nullify_three_options():
    cmds = parse_ams("ALTER A NULLIFY(BWO CODE OWNER)\n")
    assert cmds[0].nullify == NullifySpec(bwo=True, code=True, owner=True)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_nullify_authorization_module():
    cmds = parse_ams("ALTER A NULLIFY(AUTHORIZATION(MODULE))\n")
    assert cmds[0].nullify == NullifySpec(authorization="MODULE")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_nullify_authorization_string():
    cmds = parse_ams("ALTER A NULLIFY(AUTHORIZATION(STRING))\n")
    assert cmds[0].nullify == NullifySpec(authorization="STRING")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_nullify_all_nine_options():
    cmds = parse_ams(
        "ALTER A NULLIFY(AUTHORIZATION(MODULE) BWO CODE EXCEPTIONEXIT LOG -\n"
        "  LOGSTREAMID MANAGEMENTCLASS OWNER RETENTION)\n"
    )
    assert cmds[0].nullify == NullifySpec(
        authorization="MODULE",
        bwo=True,
        code=True,
        exception_exit=True,
        log=True,
        log_stream_id=True,
        management_class=True,
        owner=True,
        retention=True,
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_no_nullify_defaults_none():
    cmds = parse_ams("ALTER A\n")
    assert cmds[0].nullify is None


# =========================================================================
# LOCK/UNLOCK vs SUSPEND/RESUME (structural mutual exclusivity)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_lock():
    cmds = parse_ams("ALTER A LOCK\n")
    assert cmds[0].lock is True
    assert cmds[0].suspend is None


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_unlock():
    cmds = parse_ams("ALTER A UNLOCK\n")
    assert cmds[0].lock is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_suspend():
    cmds = parse_ams("ALTER A SUSPEND\n")
    assert cmds[0].suspend is True
    assert cmds[0].lock is None


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_resume():
    cmds = parse_ams("ALTER A RESUME\n")
    assert cmds[0].suspend is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_lock_and_suspend_together_raises():
    """LOCK/UNLOCK is mutually exclusive with SUSPEND/RESUME per the
    manual -- both operate on catalog access state, so a single ALTER
    can't do both. Must be a structural LarkError, not silent last-wins."""
    with pytest.raises(LarkError):
        parse_ams("ALTER A LOCK SUSPEND\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_lock_twice_raises():
    with pytest.raises(LarkError):
        parse_ams("ALTER A LOCK UNLOCK\n")


# =========================================================================
# TYPE(LINEAR)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_type_linear():
    cmds = parse_ams("ALTER A TYPE(LINEAR)\n")
    assert cmds[0].to_linear is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_no_type_linear_defaults_false():
    cmds = parse_ams("ALTER A\n")
    assert cmds[0].to_linear is False


# =========================================================================
# ROLLIN
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_rollin():
    cmds = parse_ams("ALTER A ROLLIN\n")
    assert cmds[0].roll_in is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_no_rollin_defaults_false():
    cmds = parse_ams("ALTER A\n")
    assert cmds[0].roll_in is False


# =========================================================================
# Remaining ~45-field checklist (Step 6)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_account():
    cmds = parse_ams("ALTER A ACCOUNT(ACCTINFO)\n")
    assert cmds[0].account == "ACCTINFO"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_bufferspace():
    cmds = parse_ams("ALTER A BUFFERSPACE(4096)\n")
    assert cmds[0].buffer_space == 4096


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_bufnd():
    cmds = parse_ams("ALTER A BUFND(10)\n")
    assert cmds[0].bufnd == 10


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_bufni():
    cmds = parse_ams("ALTER A BUFNI(5)\n")
    assert cmds[0].bufni == 5


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_bwo():
    cmds = parse_ams("ALTER A BWO(TYPECICS)\n")
    assert cmds[0].bwo == "TYPECICS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_catalog():
    cmds = parse_ams("ALTER A CATALOG(MYCAT)\n")
    assert cmds[0].catalog == "MYCAT"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_ccsid():
    cmds = parse_ams("ALTER A CCSID(1047)\n")
    assert cmds[0].ccsid == 1047


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_ecsharing():
    cmds = parse_ams("ALTER A ECSHARING\n")
    assert cmds[0].ec_sharing is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_noecsharing():
    cmds = parse_ams("ALTER A NOECSHARING\n")
    assert cmds[0].ec_sharing is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_empty():
    cmds = parse_ams("ALTER A EMPTY\n")
    assert cmds[0].empty is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_noempty():
    cmds = parse_ams("ALTER A NOEMPTY\n")
    assert cmds[0].empty is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_erase():
    cmds = parse_ams("ALTER A ERASE\n")
    assert cmds[0].erase is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_noerase():
    cmds = parse_ams("ALTER A NOERASE\n")
    assert cmds[0].erase is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_exceptionexit():
    cmds = parse_ams("ALTER A EXCEPTIONEXIT(MYEXIT)\n")
    assert cmds[0].exception_exit == "MYEXIT"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_extendedaddressable():
    cmds = parse_ams("ALTER A EXTENDEDADDRESSABLE\n")
    assert cmds[0].extended_addressable is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_no_extendedaddressable_defaults_false():
    cmds = parse_ams("ALTER A\n")
    assert cmds[0].extended_addressable is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_fifo():
    cmds = parse_ams("ALTER A FIFO\n")
    assert cmds[0].order == "FIFO"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_lifo():
    cmds = parse_ams("ALTER A LIFO\n")
    assert cmds[0].order == "LIFO"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_file():
    cmds = parse_ams("ALTER A FILE(MYDD)\n")
    assert cmds[0].file == "MYDD"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_filedata_text():
    cmds = parse_ams("ALTER A FILEDATA(TEXT)\n")
    assert cmds[0].file_data == "TEXT"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_filedata_binary():
    cmds = parse_ams("ALTER A FILEDATA(BINARY)\n")
    assert cmds[0].file_data == "BINARY"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_freespace():
    cmds = parse_ams("ALTER A FREESPACE(20 10)\n")
    assert cmds[0].freespace == (20, 10)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_frlog_none():
    cmds = parse_ams("ALTER A FRLOG(NONE)\n")
    assert cmds[0].frlog == "NONE"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_frlog_redo():
    cmds = parse_ams("ALTER A FRLOG(REDO)\n")
    assert cmds[0].frlog == "REDO"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_inhibit():
    cmds = parse_ams("ALTER A INHIBIT\n")
    assert cmds[0].inhibit is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_uninhibit():
    cmds = parse_ams("ALTER A UNINHIBIT\n")
    assert cmds[0].inhibit is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_keys():
    cmds = parse_ams("ALTER A KEYS(5 0)\n")
    assert cmds[0].keys == (5, 0)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_limit():
    cmds = parse_ams("ALTER A LIMIT(255)\n")
    assert cmds[0].limit == 255


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_managementclass():
    cmds = parse_ams("ALTER A MANAGEMENTCLASS(MYMGMT)\n")
    assert cmds[0].management_class == "MYMGMT"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_owner():
    cmds = parse_ams("ALTER A OWNER(MYOWNER)\n")
    assert cmds[0].owner == "MYOWNER"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_purge():
    cmds = parse_ams("ALTER A PURGE\n")
    assert cmds[0].purge is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_nopurge():
    cmds = parse_ams("ALTER A NOPURGE\n")
    assert cmds[0].purge is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_reclaimca():
    cmds = parse_ams("ALTER A RECLAIMCA\n")
    assert cmds[0].reclaim_ca is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_noreclaimca():
    cmds = parse_ams("ALTER A NORECLAIMCA\n")
    assert cmds[0].reclaim_ca is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_recordsize():
    cmds = parse_ams("ALTER A RECORDSIZE(80 80)\n")
    assert cmds[0].record_size == (80, 80)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_reuse():
    cmds = parse_ams("ALTER A REUSE\n")
    assert cmds[0].reuse is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_noreuse():
    cmds = parse_ams("ALTER A NOREUSE\n")
    assert cmds[0].reuse is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_rlsquiesce():
    cmds = parse_ams("ALTER A RLSQUIESCE\n")
    assert cmds[0].rls_mode == "QUIESCE"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_rlsenable():
    cmds = parse_ams("ALTER A RLSENABLE\n")
    assert cmds[0].rls_mode == "ENABLE"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_scratch():
    cmds = parse_ams("ALTER A SCRATCH\n")
    assert cmds[0].scratch is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_noscratch():
    cmds = parse_ams("ALTER A NOSCRATCH\n")
    assert cmds[0].scratch is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_shareoptions():
    cmds = parse_ams("ALTER A SHAREOPTIONS(2 3)\n")
    assert cmds[0].share_options == (2, 3)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_storageclass():
    cmds = parse_ams("ALTER A STORAGECLASS(MYSTOR)\n")
    assert cmds[0].storage_class == "MYSTOR"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_strno():
    cmds = parse_ams("ALTER A STRNO(3)\n")
    assert cmds[0].strno == 3


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_to_retention():
    cmds = parse_ams("ALTER A TO(2027001)\n")
    assert cmds[0].retention == Retention(to_date="2027001")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_for_retention():
    cmds = parse_ams("ALTER A FOR(30)\n")
    assert cmds[0].retention == Retention(for_days=30)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_uniquekey():
    cmds = parse_ams("ALTER A UNIQUEKEY\n")
    assert cmds[0].unique_key is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_nonuniquekey():
    cmds = parse_ams("ALTER A NONUNIQUEKEY\n")
    assert cmds[0].unique_key is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_update():
    cmds = parse_ams("ALTER A UPDATE\n")
    assert cmds[0].update is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_noupdate():
    cmds = parse_ams("ALTER A NOUPDATE\n")
    assert cmds[0].update is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_upgrade():
    cmds = parse_ams("ALTER A UPGRADE\n")
    assert cmds[0].upgrade is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_noupgrade():
    cmds = parse_ams("ALTER A NOUPGRADE\n")
    assert cmds[0].upgrade is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_writecheck():
    cmds = parse_ams("ALTER A WRITECHECK\n")
    assert cmds[0].write_check is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_nowritecheck():
    cmds = parse_ams("ALTER A NOWRITECHECK\n")
    assert cmds[0].write_check is False


# =========================================================================
# Full command, a representative broad set of parameters together
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_alter_full():
    cmds = parse_ams(
        "ALTER A.B.C NEWNAME(A.B.D) -\n"
        "  ACCOUNT(ACCTINFO) ADDVOLUMES(VOL001) BUFFERSPACE(4096) -\n"
        "  BUFND(10) BUFNI(5) BWO(TYPECICS) CATALOG(MYCAT) CCSID(1047) -\n"
        "  ECSHARING EMPTY ERASE EXCEPTIONEXIT(MYEXIT) -\n"
        "  EXTENDEDADDRESSABLE FIFO FILE(MYDD) FILEDATA(TEXT) -\n"
        "  FREESPACE(20 10) FRLOG(REDO) INHIBIT KEYS(5 0) LIMIT(255) -\n"
        "  LOG(ALL) LOGREPLICATE LOGSTREAMID(MY.LOGSTREAM) -\n"
        "  MANAGEMENTCLASS(MYMGMT) NULLIFY(BWO CODE) OWNER(MYOWNER) -\n"
        "  PURGE RECLAIMCA RECORDSIZE(80 80) REMOVEVOLUMES(VOL002) -\n"
        "  REUSE RLSQUIESCE ROLLIN SCRATCH SHAREOPTIONS(2 3) -\n"
        "  STORAGECLASS(MYSTOR) STRNO(3) SUSPEND TO(2027001) -\n"
        "  TYPE(LINEAR) UNIQUEKEY UPDATE UPGRADE WRITECHECK\n"
    )
    assert cmds[0] == Alter(
        entry=Name.parse("A.B.C"),
        new_name=Name.parse("A.B.D"),
        account="ACCTINFO",
        add_volumes=("VOL001",),
        buffer_space=4096,
        bufnd=10,
        bufni=5,
        bwo="TYPECICS",
        catalog="MYCAT",
        ccsid=1047,
        ec_sharing=True,
        empty=True,
        erase=True,
        exception_exit="MYEXIT",
        extended_addressable=True,
        order="FIFO",
        file="MYDD",
        file_data="TEXT",
        freespace=(20, 10),
        frlog="REDO",
        inhibit=True,
        keys=(5, 0),
        limit=255,
        log="ALL",
        log_replicate=True,
        log_stream_id="MY.LOGSTREAM",
        management_class="MYMGMT",
        nullify=NullifySpec(bwo=True, code=True),
        owner="MYOWNER",
        purge=True,
        reclaim_ca=True,
        record_size=(80, 80),
        remove_volumes=("VOL002",),
        reuse=True,
        rls_mode="QUIESCE",
        roll_in=True,
        scratch=True,
        share_options=(2, 3),
        storage_class="MYSTOR",
        strno=3,
        suspend=True,
        retention=Retention(to_date="2027001"),
        to_linear=True,
        unique_key=True,
        update=True,
        upgrade=True,
        write_check=True,
    )
