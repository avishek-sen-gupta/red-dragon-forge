"""Tests for DEFINE GENERATIONDATAGROUP / DEFINE NONVSAM / DEFINE PATH
parsing into the comprehensive AST.

Covers every parameter listed in the design spec's DefineGenerationDataGroup,
DefineNonvsam, and DefinePath sections
(2026-07-08-idcams-comprehensive-grammar-design.md) -- one test per
parameter (or logical group), plus DEFINE NONVSAM's special indirect
VOLUMES forms (`******`, `&SYSR2`) and the DEVICETYPES(0000) placeholder.
"""

from __future__ import annotations

import pytest
from lark.exceptions import LarkError

from jackal.idcams.ast_define_gdg import DefineGenerationDataGroup
from jackal.idcams.ast_define_nonvsam import DefineNonvsam
from jackal.idcams.ast_define_path import DefinePath
from jackal.idcams.ast_values import Name, Retention
from jackal.idcams.parser_comprehensive import parse_ams
from tests.covers import NotLanguageFeature, covers

# =========================================================================
# DEFINE GENERATIONDATAGROUP
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_gdg_minimal_required_fields():
    cmds = parse_ams("DEFINE GENERATIONDATAGROUP (NAME(A.B.GDG) LIMIT(10))\n")
    gdg = cmds[0]
    assert gdg == DefineGenerationDataGroup(name=Name.parse("A.B.GDG"), limit=10)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_gdg_missing_limit_raises():
    with pytest.raises(TypeError):
        parse_ams("DEFINE GENERATIONDATAGROUP (NAME(A.B.GDG))\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_gdg_empty():
    cmds = parse_ams("DEFINE GENERATIONDATAGROUP (NAME(A.B) LIMIT(5) EMPTY)\n")
    assert cmds[0].empty is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_gdg_noempty():
    cmds = parse_ams("DEFINE GENERATIONDATAGROUP (NAME(A.B) LIMIT(5) NOEMPTY)\n")
    assert cmds[0].empty is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_gdg_extended():
    cmds = parse_ams("DEFINE GENERATIONDATAGROUP (NAME(A.B) LIMIT(5) EXTENDED)\n")
    assert cmds[0].extended is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_gdg_noextended():
    cmds = parse_ams("DEFINE GENERATIONDATAGROUP (NAME(A.B) LIMIT(5) NOEXTENDED)\n")
    assert cmds[0].extended is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_gdg_fifo():
    cmds = parse_ams("DEFINE GENERATIONDATAGROUP (NAME(A.B) LIMIT(5) FIFO)\n")
    assert cmds[0].order == "FIFO"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_gdg_lifo():
    cmds = parse_ams("DEFINE GENERATIONDATAGROUP (NAME(A.B) LIMIT(5) LIFO)\n")
    assert cmds[0].order == "LIFO"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_gdg_purge():
    cmds = parse_ams("DEFINE GENERATIONDATAGROUP (NAME(A.B) LIMIT(5) PURGE)\n")
    assert cmds[0].purge is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_gdg_nopurge():
    cmds = parse_ams("DEFINE GENERATIONDATAGROUP (NAME(A.B) LIMIT(5) NOPURGE)\n")
    assert cmds[0].purge is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_gdg_scratch():
    cmds = parse_ams("DEFINE GENERATIONDATAGROUP (NAME(A.B) LIMIT(5) SCRATCH)\n")
    assert cmds[0].scratch is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_gdg_noscratch():
    cmds = parse_ams("DEFINE GENERATIONDATAGROUP (NAME(A.B) LIMIT(5) NOSCRATCH)\n")
    assert cmds[0].scratch is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_gdg_catalog():
    cmds = parse_ams("DEFINE GENERATIONDATAGROUP (NAME(A.B) LIMIT(5) CATALOG(MYCAT))\n")
    assert cmds[0].catalog == "MYCAT"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_gdg_owner():
    cmds = parse_ams("DEFINE GENERATIONDATAGROUP (NAME(A.B) LIMIT(5) OWNER(MYOWNER))\n")
    assert cmds[0].owner == "MYOWNER"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_gdg_full():
    cmds = parse_ams(
        "DEFINE GENERATIONDATAGROUP (NAME(A.B.GDG) LIMIT(255) -\n"
        "  CATALOG(MYCAT) EMPTY EXTENDED FIFO OWNER(MYOWNER) PURGE SCRATCH)\n"
    )
    assert cmds[0] == DefineGenerationDataGroup(
        name=Name.parse("A.B.GDG"),
        limit=255,
        catalog="MYCAT",
        empty=True,
        extended=True,
        order="FIFO",
        owner="MYOWNER",
        purge=True,
        scratch=True,
    )


# =========================================================================
# DEFINE NONVSAM
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_nonvsam_minimal_required_fields():
    cmds = parse_ams(
        "DEFINE NONVSAM (NAME(A.B.SEQ) DEVICETYPES(3390) VOLUMES(VOL001))\n"
    )
    assert cmds[0] == DefineNonvsam(
        name=Name.parse("A.B.SEQ"),
        device_types=("3390",),
        volumes=("VOL001",),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_nonvsam_missing_devicetypes_raises():
    with pytest.raises(TypeError):
        parse_ams("DEFINE NONVSAM (NAME(A.B.SEQ) VOLUMES(VOL001))\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_nonvsam_missing_volumes_raises():
    with pytest.raises(TypeError):
        parse_ams("DEFINE NONVSAM (NAME(A.B.SEQ) DEVICETYPES(3390))\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_nonvsam_devicetypes_all_zeros_placeholder():
    """DEVICETYPES(0000) means "resolve device type at LOCATE/DELETE time"."""
    cmds = parse_ams(
        "DEFINE NONVSAM (NAME(A.B.SEQ) DEVICETYPES(0000) VOLUMES(VOL001))\n"
    )
    assert cmds[0].device_types == ("0000",)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_nonvsam_devicetypes_multiple():
    cmds = parse_ams(
        "DEFINE NONVSAM (NAME(A.B.SEQ) DEVICETYPES(3390 3380) VOLUMES(VOL001))\n"
    )
    assert cmds[0].device_types == ("3390", "3380")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_nonvsam_volumes_indirect_asterisks():
    """VOLUMES(******) -- six literal asterisks -- is an indirect
    (unresolved) volume placeholder."""
    cmds = parse_ams(
        "DEFINE NONVSAM (NAME(A.B.SEQ) DEVICETYPES(3390) VOLUMES(******))\n"
    )
    assert cmds[0].volumes == ("******",)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_nonvsam_volumes_indirect_symbolic():
    """VOLUMES(&SYSR2) -- '&' + up to 5 more chars -- is a symbolic
    indirect volume reference."""
    cmds = parse_ams(
        "DEFINE NONVSAM (NAME(A.B.SEQ) DEVICETYPES(3390) VOLUMES(&SYSR2))\n"
    )
    assert cmds[0].volumes == ("&SYSR2",)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_nonvsam_volumes_multiple_mixed():
    cmds = parse_ams(
        "DEFINE NONVSAM (NAME(A.B.SEQ) DEVICETYPES(3390) -\n"
        "  VOLUMES(VOL001 VOL002))\n"
    )
    assert cmds[0].volumes == ("VOL001", "VOL002")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_nonvsam_catalog():
    cmds = parse_ams(
        "DEFINE NONVSAM (NAME(A.B.SEQ) DEVICETYPES(3390) VOLUMES(VOL001) "
        "CATALOG(MYCAT))\n"
    )
    assert cmds[0].catalog == "MYCAT"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_nonvsam_collection():
    """COLLECTION is obsolete but must still parse (accepted for
    RECATALOG compatibility only)."""
    cmds = parse_ams(
        "DEFINE NONVSAM (NAME(A.B.SEQ) DEVICETYPES(3390) VOLUMES(VOL001) "
        "COLLECTION)\n"
    )
    assert cmds[0].collection is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_nonvsam_collection_defaults_false():
    cmds = parse_ams(
        "DEFINE NONVSAM (NAME(A.B.SEQ) DEVICETYPES(3390) VOLUMES(VOL001))\n"
    )
    assert cmds[0].collection is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_nonvsam_filesequencenumbers():
    cmds = parse_ams(
        "DEFINE NONVSAM (NAME(A.B.SEQ) DEVICETYPES(3390) VOLUMES(VOL001) "
        "FILESEQUENCENUMBERS(1 2 3))\n"
    )
    assert cmds[0].file_sequence_numbers == (1, 2, 3)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_nonvsam_owner():
    cmds = parse_ams(
        "DEFINE NONVSAM (NAME(A.B.SEQ) DEVICETYPES(3390) VOLUMES(VOL001) "
        "OWNER(MYOWNER))\n"
    )
    assert cmds[0].owner == "MYOWNER"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_nonvsam_recatalog():
    cmds = parse_ams(
        "DEFINE NONVSAM (NAME(A.B.SEQ) DEVICETYPES(3390) VOLUMES(VOL001) "
        "RECATALOG)\n"
    )
    assert cmds[0].recatalog is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_nonvsam_norecatalog():
    cmds = parse_ams(
        "DEFINE NONVSAM (NAME(A.B.SEQ) DEVICETYPES(3390) VOLUMES(VOL001) "
        "NORECATALOG)\n"
    )
    assert cmds[0].recatalog is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_nonvsam_retention_to_date():
    cmds = parse_ams(
        "DEFINE NONVSAM (NAME(A.B.SEQ) DEVICETYPES(3390) VOLUMES(VOL001) "
        "TO(99365))\n"
    )
    assert cmds[0].retention == Retention(to_date="99365")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_nonvsam_retention_for_days():
    cmds = parse_ams(
        "DEFINE NONVSAM (NAME(A.B.SEQ) DEVICETYPES(3390) VOLUMES(VOL001) "
        "FOR(9999))\n"
    )
    assert cmds[0].retention == Retention(for_days=9999)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_nonvsam_full():
    cmds = parse_ams(
        "DEFINE NONVSAM (NAME(A.B.SEQ) DEVICETYPES(3390) VOLUMES(VOL001 VOL002) -\n"
        "  CATALOG(MYCAT) COLLECTION FILESEQUENCENUMBERS(1 2) OWNER(MYOWNER) -\n"
        "  RECATALOG FOR(9999))\n"
    )
    assert cmds[0] == DefineNonvsam(
        name=Name.parse("A.B.SEQ"),
        device_types=("3390",),
        volumes=("VOL001", "VOL002"),
        catalog="MYCAT",
        collection=True,
        file_sequence_numbers=(1, 2),
        owner="MYOWNER",
        recatalog=True,
        retention=Retention(for_days=9999),
    )


# =========================================================================
# DEFINE PATH
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_path_minimal_required_fields():
    cmds = parse_ams("DEFINE PATH (NAME(A.B.PATH) PATHENTRY(A.B.AIX))\n")
    assert cmds[0] == DefinePath(
        name=Name.parse("A.B.PATH"), path_entry=Name.parse("A.B.AIX")
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_path_missing_pathentry_raises():
    with pytest.raises(TypeError):
        parse_ams("DEFINE PATH (NAME(A.B.PATH))\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_path_update():
    cmds = parse_ams("DEFINE PATH (NAME(A.B) PATHENTRY(A.C) UPDATE)\n")
    assert cmds[0].update is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_path_noupdate():
    cmds = parse_ams("DEFINE PATH (NAME(A.B) PATHENTRY(A.C) NOUPDATE)\n")
    assert cmds[0].update is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_path_catalog():
    cmds = parse_ams("DEFINE PATH (NAME(A.B) PATHENTRY(A.C) CATALOG(MYCAT))\n")
    assert cmds[0].catalog == "MYCAT"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_path_model_without_catalog():
    cmds = parse_ams("DEFINE PATH (NAME(A.B) PATHENTRY(A.C) MODEL(A.MODELDS))\n")
    assert cmds[0].model == (Name.parse("A.MODELDS"), None)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_path_model_with_catalog():
    cmds = parse_ams("DEFINE PATH (NAME(A.B) PATHENTRY(A.C) MODEL(A.MODELDS A.CAT))\n")
    assert cmds[0].model == (Name.parse("A.MODELDS"), Name.parse("A.CAT"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_path_owner():
    cmds = parse_ams("DEFINE PATH (NAME(A.B) PATHENTRY(A.C) OWNER(MYOWNER))\n")
    assert cmds[0].owner == "MYOWNER"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_path_recatalog():
    cmds = parse_ams("DEFINE PATH (NAME(A.B) PATHENTRY(A.C) RECATALOG)\n")
    assert cmds[0].recatalog is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_path_norecatalog():
    cmds = parse_ams("DEFINE PATH (NAME(A.B) PATHENTRY(A.C) NORECATALOG)\n")
    assert cmds[0].recatalog is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_path_retention_to_date():
    cmds = parse_ams("DEFINE PATH (NAME(A.B) PATHENTRY(A.C) TO(99365))\n")
    assert cmds[0].retention == Retention(to_date="99365")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_path_retention_for_days():
    cmds = parse_ams("DEFINE PATH (NAME(A.B) PATHENTRY(A.C) FOR(9999))\n")
    assert cmds[0].retention == Retention(for_days=9999)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_path_full():
    cmds = parse_ams(
        "DEFINE PATH (NAME(A.B.PATH) PATHENTRY(A.B.AIX) -\n"
        "  CATALOG(MYCAT) MODEL(A.MODELDS A.CAT) OWNER(MYOWNER) -\n"
        "  RECATALOG TO(99365) UPDATE)\n"
    )
    assert cmds[0] == DefinePath(
        name=Name.parse("A.B.PATH"),
        path_entry=Name.parse("A.B.AIX"),
        catalog="MYCAT",
        model=(Name.parse("A.MODELDS"), Name.parse("A.CAT")),
        owner="MYOWNER",
        recatalog=True,
        retention=Retention(to_date="99365"),
        update=True,
    )
