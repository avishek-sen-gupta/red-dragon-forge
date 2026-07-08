"""Tests for DEFINE ALTERNATEINDEX parsing into the comprehensive AST.

Covers every parameter listed in the design spec's DefineAlternateIndex
section (2026-07-08-idcams-comprehensive-grammar-design.md) -- one test
per parameter (or logical group), plus the mutual-exclusivity groups
(space allocation choice, ALTKEYS/ALTKEYSU) and the AixDataComponent/
AixIndexComponent validity-boundary rule (UNIQUEKEY valid on DATA, not
on INDEX).
"""

from __future__ import annotations

import pytest
from lark.exceptions import LarkError

from jackal.idcams.ast_define_alternateindex import (
    AixDataComponent,
    AixIndexComponent,
    DefineAlternateIndex,
)
from jackal.idcams.ast_values import Name, Retention, SpaceAllocation
from jackal.idcams.parser_comprehensive import parse_ams
from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_minimal_required_fields():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B.AIX) -\n"
        "  RELATE(A.B.KSDS) -\n"
        "  CYLINDERS(1 5) -\n"
        "  VOLUMES(AWSHJ1))\n"
    )
    aix = cmds[0]
    assert aix == DefineAlternateIndex(
        name=Name.parse("A.B.AIX"),
        relate=Name.parse("A.B.KSDS"),
        space=SpaceAllocation(unit="CYLINDERS", primary=1, secondary=5),
        volumes=("AWSHJ1",),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_missing_relate_raises():
    with pytest.raises(TypeError):
        parse_ams("DEFINE ALTERNATEINDEX (NAME(A.B.AIX) CYLINDERS(1) VOLUMES(V1))\n")


# --- obsolete-but-must-parse parameters ---------------------------------


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_obsolete_imbed_parses_and_is_ignored():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) IMBED)\n"
    )
    assert cmds[0].imbed is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_obsolete_noimbed_parses_and_is_ignored():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) NOIMBED)\n"
    )
    assert cmds[0].imbed is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_obsolete_keyranges_parses_and_is_ignored():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) "
        "KEYRANGES(1 100))\n"
    )
    assert cmds[0].key_ranges_ignored is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_obsolete_ordered_parses_and_is_ignored():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) ORDERED)\n"
    )
    assert cmds[0].order_ignored is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_obsolete_unordered_parses_and_is_ignored():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) UNORDERED)\n"
    )
    assert cmds[0].order_ignored is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_obsolete_replicate_parses_and_is_ignored():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) REPLICATE)\n"
    )
    assert cmds[0].replicate_ignored is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_obsolete_noreplicate_parses_and_is_ignored():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) "
        "NOREPLICATE)\n"
    )
    assert cmds[0].replicate_ignored is True


# --- ALTKEYS / ALTKEYSU ---------------------------------------------------


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_altkeys():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) -\n"
        "  ALTKEYS(KEY1 A KEY2 D))\n"
    )
    assert cmds[0].alt_keys == (("KEY1", "A"), ("KEY2", "D"))
    assert cmds[0].alt_keys_utf8 is None


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_altkeysu():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) -\n"
        "  ALTKEYSU(KEY1 A))\n"
    )
    assert cmds[0].alt_keys_utf8 == (("KEY1", "A"),)
    assert cmds[0].alt_keys is None


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_rejects_altkeys_and_altkeysu_together():
    """ALTKEYS and ALTKEYSU are mutually exclusive -- at most one may
    appear on the same command."""
    with pytest.raises(LarkError):
        parse_ams(
            "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) -\n"
            "  ALTKEYS(KEY1 A) ALTKEYSU(KEY2 D))\n"
        )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_rejects_two_space_allocation_units():
    with pytest.raises(LarkError):
        parse_ams(
            "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) TRACKS(2) "
            "VOLUMES(V1))\n"
        )


# --- UNIQUEKEY / NONUNIQUEKEY, UPGRADE / NOUPGRADE -----------------------


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_uniquekey():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) UNIQUEKEY)\n"
    )
    assert cmds[0].unique_key is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_nonuniquekey():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) "
        "NONUNIQUEKEY)\n"
    )
    assert cmds[0].unique_key is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_upgrade():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) UPGRADE)\n"
    )
    assert cmds[0].upgrade is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_noupgrade():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) NOUPGRADE)\n"
    )
    assert cmds[0].upgrade is False


# --- AixDataComponent / AixIndexComponent asymmetry: UNIQUEKEY ----------


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_data_component_accepts_uniquekey():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1)) -\n"
        "  DATA (NAME(A.B.DATA) UNIQUEKEY)\n"
    )
    assert cmds[0].data == AixDataComponent(
        name=Name.parse("A.B.DATA"), unique_key=True
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_index_component_rejects_uniquekey():
    """UNIQUEKEY is a DATA-only parameter -- INDEX(...) must not accept
    it."""
    with pytest.raises(LarkError):
        parse_ams(
            "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1)) -\n"
            "  INDEX (NAME(A.B.INDEX) UNIQUEKEY)\n"
        )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_index_component_rejects_spanned():
    """SPANNED/NONSPANNED are not valid for an AIX component at all."""
    with pytest.raises(LarkError):
        parse_ams(
            "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1)) -\n"
            "  INDEX (NAME(A.B.INDEX) SPANNED)\n"
        )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_data_component_rejects_spanned():
    with pytest.raises(LarkError):
        parse_ams(
            "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1)) -\n"
            "  DATA (NAME(A.B.DATA) SPANNED)\n"
        )


# --- Step 6: remaining optional parameters -------------------------------


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_bufferspace():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) "
        "BUFFERSPACE(4096))\n"
    )
    assert cmds[0].buffer_space == 4096


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_catalog():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) "
        "CATALOG(MYCAT))\n"
    )
    assert cmds[0].catalog == "MYCAT"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_controlintervalsize():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) "
        "CONTROLINTERVALSIZE(4096))\n"
    )
    assert cmds[0].control_interval_size == 4096


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_dataclass():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) "
        "DATACLASS(MYDCLAS))\n"
    )
    assert cmds[0].data_class == "MYDCLAS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_erase():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) ERASE)\n"
    )
    assert cmds[0].erase is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_noerase():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) NOERASE)\n"
    )
    assert cmds[0].erase is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_exceptionexit():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) "
        "EXCEPTIONEXIT(MYEXIT))\n"
    )
    assert cmds[0].exception_exit == "MYEXIT"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_file():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) FILE(MYDD))\n"
    )
    assert cmds[0].file == "MYDD"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_freespace():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) "
        "FREESPACE(10 20))\n"
    )
    assert cmds[0].freespace == (10, 20)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_keys():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) "
        "KEYS(16 0))\n"
    )
    assert cmds[0].keys == (16, 0)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_model_without_catalog():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) "
        "MODEL(A.MODELDS))\n"
    )
    assert cmds[0].model == (Name.parse("A.MODELDS"), None)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_model_with_catalog():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) "
        "MODEL(A.MODELDS A.CAT))\n"
    )
    assert cmds[0].model == (Name.parse("A.MODELDS"), Name.parse("A.CAT"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_owner():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) "
        "OWNER(MYOWNER))\n"
    )
    assert cmds[0].owner == "MYOWNER"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_recatalog():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) RECATALOG)\n"
    )
    assert cmds[0].recatalog is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_norecatalog():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) "
        "NORECATALOG)\n"
    )
    assert cmds[0].recatalog is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_recordsize():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) "
        "RECORDSIZE(150 150))\n"
    )
    assert cmds[0].record_size == (150, 150)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_reuse():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) REUSE)\n"
    )
    assert cmds[0].reuse is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_noreuse():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) NOREUSE)\n"
    )
    assert cmds[0].reuse is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_shareoptions_both_values():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) "
        "SHAREOPTIONS(2 3))\n"
    )
    assert cmds[0].share_options == (2, 3)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_shareoptions_single_value():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) "
        "SHAREOPTIONS(1))\n"
    )
    assert cmds[0].share_options == (1, None)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_speed():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) SPEED)\n"
    )
    assert cmds[0].speed is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_recovery():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) RECOVERY)\n"
    )
    assert cmds[0].speed is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_retention_to_date():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) TO(99365))\n"
    )
    assert cmds[0].retention == Retention(to_date="99365")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_retention_for_days():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) FOR(9999))\n"
    )
    assert cmds[0].retention == Retention(for_days=9999)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_writecheck():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) WRITECHECK)\n"
    )
    assert cmds[0].write_check is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_nowritecheck():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1) "
        "NOWRITECHECK)\n"
    )
    assert cmds[0].write_check is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_multiple_volumes():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) "
        "VOLUMES(VOL001 VOL002 VOL003))\n"
    )
    assert cmds[0].volumes == ("VOL001", "VOL002", "VOL003")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_space_allocation_kilobytes():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) KILOBYTES(100 50) VOLUMES(V1))\n"
    )
    assert cmds[0].space == SpaceAllocation(unit="KILOBYTES", primary=100, secondary=50)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_space_allocation_megabytes():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) MEGABYTES(10) VOLUMES(V1))\n"
    )
    assert cmds[0].space == SpaceAllocation(
        unit="MEGABYTES", primary=10, secondary=None
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_space_allocation_records():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) RECORDS(1000 100) VOLUMES(V1))\n"
    )
    assert cmds[0].space == SpaceAllocation(unit="RECORDS", primary=1000, secondary=100)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_space_allocation_tracks():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) TRACKS(5) VOLUMES(V1))\n"
    )
    assert cmds[0].space == SpaceAllocation(unit="TRACKS", primary=5, secondary=None)


# --- AixDataComponent / AixIndexComponent full coverage ------------------


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_data_component_full():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1)) -\n"
        "  DATA (NAME(A.B.DATA) CYLINDERS(2 1) VOLUMES(V2) -\n"
        "    ATTEMPTS(3) AUTHORIZATION(MYMOD 'PARM') BUFFERSPACE(4096) -\n"
        "    CODE(MYCODE) CONTROLINTERVALSIZE(4096) ERASE -\n"
        "    EXCEPTIONEXIT(MYEXIT) FILE(MYDD) FREESPACE(10 20) -\n"
        "    KEYS(16 0) MODEL(A.MODELDS A.CAT) OWNER(MYOWNER) -\n"
        "    RECORDSIZE(150 150) REUSE SHAREOPTIONS(2 3) -\n"
        "    SPEED UNIQUEKEY WRITECHECK)\n"
    )
    dc = cmds[0].data
    assert dc == AixDataComponent(
        name=Name.parse("A.B.DATA"),
        space=SpaceAllocation(unit="CYLINDERS", primary=2, secondary=1),
        volumes=("V2",),
        attempts=3,
        authorization=("MYMOD", "PARM"),
        buffer_space=4096,
        code="MYCODE",
        control_interval_size=4096,
        erase=True,
        exception_exit="MYEXIT",
        file="MYDD",
        freespace=(10, 20),
        keys=(16, 0),
        model=(Name.parse("A.MODELDS"), Name.parse("A.CAT")),
        owner="MYOWNER",
        record_size=(150, 150),
        reuse=True,
        share_options=(2, 3),
        speed=True,
        unique_key=True,
        write_check=True,
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_index_component_full():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1)) -\n"
        "  INDEX (NAME(A.B.INDEX) CYLINDERS(1) VOLUMES(V3) -\n"
        "    ATTEMPTS(2) AUTHORIZATION(MYMOD) CODE(MYCODE) -\n"
        "    CONTROLINTERVALSIZE(512) EXCEPTIONEXIT(MYEXIT) -\n"
        "    FILE(MYDD) MODEL(A.MODELDS A.CAT) OWNER(MYOWNER) -\n"
        "    REUSE SHAREOPTIONS(2 3) WRITECHECK)\n"
    )
    ic = cmds[0].index
    assert ic == AixIndexComponent(
        name=Name.parse("A.B.INDEX"),
        space=SpaceAllocation(unit="CYLINDERS", primary=1, secondary=None),
        volumes=("V3",),
        attempts=2,
        authorization=("MYMOD", None),
        code="MYCODE",
        control_interval_size=512,
        exception_exit="MYEXIT",
        file="MYDD",
        model=(Name.parse("A.MODELDS"), Name.parse("A.CAT")),
        owner="MYOWNER",
        reuse=True,
        share_options=(2, 3),
        write_check=True,
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_data_component_space_allocation():
    cmds = parse_ams(
        "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1)) -\n"
        "  DATA (NAME(A.B.DATA) TRACKS(5))\n"
    )
    assert cmds[0].data.space == SpaceAllocation(
        unit="TRACKS", primary=5, secondary=None
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_alternateindex_data_component_rejects_two_space_allocation_units():
    with pytest.raises(LarkError):
        parse_ams(
            "DEFINE ALTERNATEINDEX (NAME(A.B) RELATE(A.C) CYLINDERS(1) VOLUMES(V1)) -\n"
            "  DATA (NAME(A.B.DATA) CYLINDERS(1) TRACKS(2))\n"
        )
