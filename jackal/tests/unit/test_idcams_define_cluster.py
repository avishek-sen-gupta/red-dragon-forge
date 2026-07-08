"""Tests for DEFINE CLUSTER parsing into the comprehensive AST.

Covers every parameter listed in the design spec's DefineCluster
section (2026-07-08-idcams-comprehensive-grammar-design.md) -- one test
per parameter (or logical group), plus the DATA/INDEX validity-boundary
rule that is the main thing under scrutiny for this command.
"""

from __future__ import annotations

import pytest
from lark.exceptions import LarkError

from jackal.idcams.ast_define_cluster import (
    DatabaseSpec,
    DataComponent,
    DefineCluster,
    IndexComponent,
)
from jackal.idcams.ast_values import Name, Retention, SpaceAllocation
from jackal.idcams.parser_comprehensive import parse_ams
from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_minimal_required_fields():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B.KSDS) -\n"
        "  CYLINDERS(1 5) -\n"
        "  VOLUMES(AWSHJ1))\n"
    )
    dc = cmds[0]
    assert dc == DefineCluster(
        name=Name.parse("A.B.KSDS"),
        space=SpaceAllocation(unit="CYLINDERS", primary=1, secondary=5),
        volumes=("AWSHJ1",),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_organization_choice_defaults_to_indexed():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1))\n")
    assert cmds[0].organization == "INDEXED"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_linear_organization():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) LINEAR CYLINDERS(1) VOLUMES(V1))\n")
    assert cmds[0].organization == "LINEAR"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_nonindexed_organization():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) NONINDEXED CYLINDERS(1) VOLUMES(V1))\n")
    assert cmds[0].organization == "NONINDEXED"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_numbered_organization():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) NUMBERED CYLINDERS(1) VOLUMES(V1))\n")
    assert cmds[0].organization == "NUMBERED"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_zfs_organization():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) ZFS CYLINDERS(1) VOLUMES(V1))\n")
    assert cmds[0].organization == "ZFS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_retention_to_date():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) TO(99365))\n")
    assert cmds[0].retention == Retention(to_date="99365")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_retention_for_days():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) FOR(9999))\n")
    assert cmds[0].retention == Retention(for_days=9999)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_share_options_both_values():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) SHAREOPTIONS(2 3))\n"
    )
    assert cmds[0].share_options == (2, 3)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_share_options_single_value():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) SHAREOPTIONS(1))\n"
    )
    assert cmds[0].share_options == (1, None)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_with_data_and_index_trailers():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B.KSDS) -\n"
        "  CYLINDERS(1 5) -\n"
        "  VOLUMES(AWSHJ1) -\n"
        "  KEYS(16 0) -\n"
        "  RECORDSIZE(150 150) -\n"
        "  INDEXED) -\n"
        "  DATA (NAME(A.B.KSDS.DATA) SPANNED) -\n"
        "  INDEX (NAME(A.B.KSDS.INDEX))\n"
    )
    dc = cmds[0]
    assert dc.data == DataComponent(name=Name.parse("A.B.KSDS.DATA"), spanned=True)
    assert dc.index == IndexComponent(name=Name.parse("A.B.KSDS.INDEX"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_index_component_rejects_spanned():
    """SPANNED is a DATA-only parameter per the manual -- INDEX(...) must
    not accept it."""
    with pytest.raises(LarkError):
        parse_ams(
            "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1)) -\n"
            "  INDEX (NAME(A.B.INDEX) SPANNED)\n"
        )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_index_component_rejects_erase():
    with pytest.raises(LarkError):
        parse_ams(
            "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1)) -\n"
            "  INDEX (NAME(A.B.INDEX) ERASE)\n"
        )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_index_component_rejects_bufferspace():
    with pytest.raises(LarkError):
        parse_ams(
            "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1)) -\n"
            "  INDEX (NAME(A.B.INDEX) BUFFERSPACE(4096))\n"
        )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_index_component_rejects_freespace():
    with pytest.raises(LarkError):
        parse_ams(
            "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1)) -\n"
            "  INDEX (NAME(A.B.INDEX) FREESPACE(10 20))\n"
        )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_index_component_rejects_keys():
    with pytest.raises(LarkError):
        parse_ams(
            "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1)) -\n"
            "  INDEX (NAME(A.B.INDEX) KEYS(16 0))\n"
        )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_index_component_rejects_recordsize():
    with pytest.raises(LarkError):
        parse_ams(
            "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1)) -\n"
            "  INDEX (NAME(A.B.INDEX) RECORDSIZE(150 150))\n"
        )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_index_component_rejects_speed():
    with pytest.raises(LarkError):
        parse_ams(
            "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1)) -\n"
            "  INDEX (NAME(A.B.INDEX) SPEED)\n"
        )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_database_spec():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) -\n"
        "  DATABASE(JSON) KEYNAME(MYKEY))\n"
    )
    assert cmds[0].database.format == "JSON"
    assert cmds[0].database.key_name == "MYKEY"
    assert cmds[0].database.key_name_is_utf8 is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_database_spec_bson_keynameu():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) -\n"
        "  DATABASE(BSON) KEYNAMEU(MYKEY))\n"
    )
    assert cmds[0].database.format == "BSON"
    assert cmds[0].database.key_name == "MYKEY"
    assert cmds[0].database.key_name_is_utf8 is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_space_allocation_kilobytes():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) KILOBYTES(100 50) VOLUMES(V1))\n")
    assert cmds[0].space == SpaceAllocation(unit="KILOBYTES", primary=100, secondary=50)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_space_allocation_megabytes():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) MEGABYTES(10) VOLUMES(V1))\n")
    assert cmds[0].space == SpaceAllocation(
        unit="MEGABYTES", primary=10, secondary=None
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_space_allocation_records():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) RECORDS(1000 100) VOLUMES(V1))\n")
    assert cmds[0].space == SpaceAllocation(unit="RECORDS", primary=1000, secondary=100)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_space_allocation_tracks():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) TRACKS(5) VOLUMES(V1))\n")
    assert cmds[0].space == SpaceAllocation(unit="TRACKS", primary=5, secondary=None)


# --- Step 6: remaining optional parameters -----------------------------


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_account():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) ACCOUNT(ACCTINFO))\n"
    )
    assert cmds[0].account == "ACCTINFO"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_bufferspace():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) BUFFERSPACE(4096))\n"
    )
    assert cmds[0].buffer_space == 4096


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_bwo_typecics():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) BWO(TYPECICS))\n"
    )
    assert cmds[0].bwo == "TYPECICS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_bwo_typeims():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) BWO(TYPEIMS))\n"
    )
    assert cmds[0].bwo == "TYPEIMS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_bwo_no():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) BWO(NO))\n")
    assert cmds[0].bwo == "NO"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_catalog():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) CATALOG(MYCAT))\n"
    )
    assert cmds[0].catalog == "MYCAT"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_controlintervalsize():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) CONTROLINTERVALSIZE(4096))\n"
    )
    assert cmds[0].control_interval_size == 4096


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_dataclass():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) DATACLASS(MYDCLAS))\n"
    )
    assert cmds[0].data_class == "MYDCLAS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_eattr_no():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) EATTR(NO))\n")
    assert cmds[0].eattr == "NO"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_eattr_opt():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) EATTR(OPT))\n")
    assert cmds[0].eattr == "OPT"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_erase():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) ERASE)\n")
    assert cmds[0].erase is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_noerase():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) NOERASE)\n")
    assert cmds[0].erase is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_exceptionexit():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) EXCEPTIONEXIT(MYEXIT))\n"
    )
    assert cmds[0].exception_exit == "MYEXIT"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_file():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) FILE(MYDD))\n")
    assert cmds[0].file == "MYDD"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_freespace():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) FREESPACE(10 20))\n"
    )
    assert cmds[0].freespace == (10, 20)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_frlog():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) FRLOG(REDO))\n"
    )
    assert cmds[0].frlog == "REDO"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_keylabel():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) KEYLABEL(MYLABEL))\n"
    )
    assert cmds[0].key_label == "MYLABEL"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_keys():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) KEYS(16 0))\n")
    assert cmds[0].keys == (16, 0)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_log():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) LOG(ALL))\n")
    assert cmds[0].log == "ALL"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_logreplicate():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) LOGREPLICATE)\n"
    )
    assert cmds[0].log_replicate is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_nologreplicate():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) NOLOGREPLICATE)\n"
    )
    assert cmds[0].log_replicate is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_logstreamid():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) LOGSTREAMID(MYLOGID))\n"
    )
    assert cmds[0].log_stream_id == "MYLOGID"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_managementclass():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) MANAGEMENTCLASS(MYMCLAS))\n"
    )
    assert cmds[0].management_class == "MYMCLAS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_model_without_catalog():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) MODEL(A.MODELDS))\n"
    )
    assert cmds[0].model == (Name.parse("A.MODELDS"), None)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_model_with_catalog():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) MODEL(A.MODELDS A.CAT))\n"
    )
    assert cmds[0].model == (Name.parse("A.MODELDS"), Name.parse("A.CAT"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_owner():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) OWNER(MYOWNER))\n"
    )
    assert cmds[0].owner == "MYOWNER"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_recatalog():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) RECATALOG)\n")
    assert cmds[0].recatalog is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_norecatalog():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) NORECATALOG)\n"
    )
    assert cmds[0].recatalog is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_recordsize():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) RECORDSIZE(150 150))\n"
    )
    assert cmds[0].record_size == (150, 150)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_reuse():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) REUSE)\n")
    assert cmds[0].reuse is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_noreuse():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) NOREUSE)\n")
    assert cmds[0].reuse is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_rlsquiesce():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) RLSQUIESCE)\n")
    assert cmds[0].rls_mode == "QUIESCE"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_rlsenable():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) RLSENABLE)\n")
    assert cmds[0].rls_mode == "ENABLE"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_spanned():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) SPANNED)\n")
    assert cmds[0].spanned is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_nonspanned():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) NONSPANNED)\n")
    assert cmds[0].spanned is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_speed():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) SPEED)\n")
    assert cmds[0].speed is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_recovery():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) RECOVERY)\n")
    assert cmds[0].speed is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_storageclass():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) STORAGECLASS(MYSCLAS))\n"
    )
    assert cmds[0].storage_class == "MYSCLAS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_writecheck():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) WRITECHECK)\n")
    assert cmds[0].write_check is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_nowritecheck():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) NOWRITECHECK)\n"
    )
    assert cmds[0].write_check is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_obsolete_imbed_parses_and_is_ignored():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) IMBED)\n")
    assert cmds[0].name == Name.parse("A.B")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_obsolete_noimbed_parses_and_is_ignored():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) NOIMBED)\n")
    assert cmds[0].name == Name.parse("A.B")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_obsolete_keyranges_parses_and_is_ignored():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) KEYRANGES(1 100))\n"
    )
    assert cmds[0].name == Name.parse("A.B")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_obsolete_ordered_parses_and_is_ignored():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) ORDERED)\n")
    assert cmds[0].name == Name.parse("A.B")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_obsolete_unordered_parses_and_is_ignored():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) UNORDERED)\n")
    assert cmds[0].name == Name.parse("A.B")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_obsolete_replicate_parses_and_is_ignored():
    cmds = parse_ams("DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) REPLICATE)\n")
    assert cmds[0].name == Name.parse("A.B")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_obsolete_noreplicate_parses_and_is_ignored():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) NOREPLICATE)\n"
    )
    assert cmds[0].name == Name.parse("A.B")


# --- DataComponent / IndexComponent optional parameters -----------------


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_data_component_full():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1)) -\n"
        "  DATA (NAME(A.B.DATA) CYLINDERS(2 1) VOLUMES(V2) -\n"
        "    BUFFERSPACE(4096) CONTROLINTERVALSIZE(4096) ERASE -\n"
        "    EXCEPTIONEXIT(MYEXIT) FILE(MYDD) FREESPACE(10 20) -\n"
        "    KEYS(16 0) MODEL(A.MODELDS A.CAT) OWNER(MYOWNER) -\n"
        "    RECORDSIZE(150 150) REUSE SHAREOPTIONS(2 3) SPANNED -\n"
        "    SPEED WRITECHECK)\n"
    )
    dc = cmds[0].data
    assert dc == DataComponent(
        name=Name.parse("A.B.DATA"),
        space=SpaceAllocation(unit="CYLINDERS", primary=2, secondary=1),
        volumes=("V2",),
        buffer_space=4096,
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
        spanned=True,
        speed=True,
        write_check=True,
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_index_component_full():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1)) -\n"
        "  INDEX (NAME(A.B.INDEX) CYLINDERS(1) VOLUMES(V3) -\n"
        "    CONTROLINTERVALSIZE(512) EXCEPTIONEXIT(MYEXIT) -\n"
        "    FILE(MYDD) MODEL(A.MODELDS A.CAT) OWNER(MYOWNER) -\n"
        "    REUSE SHAREOPTIONS(2 3) WRITECHECK)\n"
    )
    ic = cmds[0].index
    assert ic == IndexComponent(
        name=Name.parse("A.B.INDEX"),
        space=SpaceAllocation(unit="CYLINDERS", primary=1, secondary=None),
        volumes=("V3",),
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
def test_define_cluster_multiple_volumes():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(VOL001 VOL002 VOL003))\n"
    )
    assert cmds[0].volumes == ("VOL001", "VOL002", "VOL003")
