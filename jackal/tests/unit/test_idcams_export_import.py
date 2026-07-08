"""Tests for IDCAMS EXPORT and IMPORT parsing into the comprehensive AST.

Covers every parameter listed in the design spec's Export and Import
sections (2026-07-08-idcams-comprehensive-grammar-design.md).

EXPORT's OUTFILE/OUTDATASET (required), CIMODE/RECORDMODE (optional "which
processing mode"), and TEMPORARY/PERMANENT (optional "which export kind")
are genuine mutual-exclusivity choice groups, flat-grammar/transformer-
enforced per the plan's ratified pattern (see
ComprehensiveIdcamsTransformer.export()). ERASE/NOERASE,
INHIBITSOURCE/NOINHIBITSOURCE, INHIBITTARGET/NOINHIBITTARGET, and
PURGE/NOPURGE are ordinary simple ON/OFF toggle pairs (no mutual-exclusivity
machinery, last-wins-in-a-repeatable-list semantics).

IMPORT's INFILE/INDATASET and OUTFILE/OUTDATASET (both required) get the
same flat-grammar/transformer-enforced treatment. ALIAS/NOALIAS,
ERASE/NOERASE, LOCK/UNLOCK, PURGE/NOPURGE, and SAVRAC/NOSAVRAC are ordinary
simple ON/OFF toggle pairs. OBJECTS(...) is a repeatable list of nested
groups (ImportObject), not a mutual-exclusivity choice -- covered with its
own dedicated multi-object test below.
"""

from __future__ import annotations

import pytest

from jackal.idcams.ast_export import Export
from jackal.idcams.ast_import import Import, ImportObject
from jackal.idcams.ast_values import Name
from jackal.idcams.parser_comprehensive import parse_ams
from tests.covers import NotLanguageFeature, covers

# =========================================================================
# EXPORT: entryname (required positional) + OUTFILE/OUTDATASET (required)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_export_outfile():
    cmds = parse_ams("EXPORT MY.CLUSTER OUTFILE(OUTDD)\n")
    assert cmds[0] == Export(entry=Name.parse("MY.CLUSTER"), outfile="OUTDD")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_export_outdataset():
    cmds = parse_ams("EXPORT MY.CLUSTER OUTDATASET(MY.OUT)\n")
    assert cmds[0] == Export(
        entry=Name.parse("MY.CLUSTER"), outdataset=Name.parse("MY.OUT")
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_export_outfile_outdataset_together_raises():
    with pytest.raises(ValueError):
        parse_ams("EXPORT MY.CLUSTER OUTFILE(OUTDD) OUTDATASET(MY.OUT)\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_export_missing_target_raises():
    with pytest.raises(ValueError):
        parse_ams("EXPORT MY.CLUSTER TEMPORARY\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_export_temporary_before_outdataset_order_independent():
    """TEMPORARY (an ordinary optional param) placed before OUTDATASET (the
    required choice member) -- proves export_param is a flat,
    freely-repeatable list, not a fixed-order chain. (The entryname itself
    is a fixed positional slot right after EXPORT, per the grammar -- only
    the *_param members are order-independent.)"""
    cmds = parse_ams("EXPORT MY.CLUSTER TEMPORARY OUTDATASET(MY.OUT)\n")
    assert cmds[0] == Export(
        entry=Name.parse("MY.CLUSTER"),
        outdataset=Name.parse("MY.OUT"),
        temporary=True,
    )


# =========================================================================
# EXPORT: CIMODE/RECORDMODE (optional, at most one)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_export_cimode():
    cmds = parse_ams("EXPORT MY.CLUSTER OUTFILE(OUTDD) CIMODE\n")
    assert cmds[0] == Export(
        entry=Name.parse("MY.CLUSTER"), outfile="OUTDD", mode="CIMODE"
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_export_recordmode():
    cmds = parse_ams("EXPORT MY.CLUSTER OUTFILE(OUTDD) RECORDMODE\n")
    assert cmds[0] == Export(
        entry=Name.parse("MY.CLUSTER"), outfile="OUTDD", mode="RECORDMODE"
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_export_cimode_recordmode_together_raises():
    with pytest.raises(ValueError):
        parse_ams("EXPORT MY.CLUSTER OUTFILE(OUTDD) CIMODE RECORDMODE\n")


# =========================================================================
# EXPORT: TEMPORARY/PERMANENT (optional, at most one)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_export_temporary():
    cmds = parse_ams("EXPORT MY.CLUSTER OUTFILE(OUTDD) TEMPORARY\n")
    assert cmds[0] == Export(
        entry=Name.parse("MY.CLUSTER"), outfile="OUTDD", temporary=True
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_export_permanent():
    cmds = parse_ams("EXPORT MY.CLUSTER OUTFILE(OUTDD) PERMANENT\n")
    assert cmds[0] == Export(
        entry=Name.parse("MY.CLUSTER"), outfile="OUTDD", temporary=False
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_export_temporary_permanent_together_raises():
    with pytest.raises(ValueError):
        parse_ams("EXPORT MY.CLUSTER OUTFILE(OUTDD) TEMPORARY PERMANENT\n")


# =========================================================================
# EXPORT: INHIBITSOURCE/INHIBITTARGET independence (both simple toggles,
# not a mutually-exclusive pair with each other)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_export_inhibitsource_and_inhibittarget_together():
    cmds = parse_ams("EXPORT MY.CLUSTER OUTFILE(OUTDD) INHIBITSOURCE INHIBITTARGET\n")
    assert cmds[0] == Export(
        entry=Name.parse("MY.CLUSTER"),
        outfile="OUTDD",
        inhibit_source=True,
        inhibit_target=True,
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_export_noinhibitsource():
    cmds = parse_ams("EXPORT MY.CLUSTER OUTFILE(OUTDD) NOINHIBITSOURCE\n")
    assert cmds[0] == Export(
        entry=Name.parse("MY.CLUSTER"), outfile="OUTDD", inhibit_source=False
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_export_noinhibittarget():
    cmds = parse_ams("EXPORT MY.CLUSTER OUTFILE(OUTDD) NOINHIBITTARGET\n")
    assert cmds[0] == Export(
        entry=Name.parse("MY.CLUSTER"), outfile="OUTDD", inhibit_target=False
    )


# =========================================================================
# EXPORT: RLSSOURCE
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_export_rlssource():
    cmds = parse_ams("EXPORT MY.CLUSTER OUTFILE(OUTDD) RLSSOURCE(YES)\n")
    assert cmds[0] == Export(
        entry=Name.parse("MY.CLUSTER"), outfile="OUTDD", rls_source="YES"
    )


# =========================================================================
# EXPORT: remaining parameters (Step 6 coverage) -- CIMODE/RECORDMODE
# already covered above; ERASE/NOERASE, INFILE, PURGE/NOPURGE remain.
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_export_erase():
    cmds = parse_ams("EXPORT MY.CLUSTER OUTFILE(OUTDD) ERASE\n")
    assert cmds[0] == Export(
        entry=Name.parse("MY.CLUSTER"), outfile="OUTDD", erase=True
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_export_noerase():
    cmds = parse_ams("EXPORT MY.CLUSTER OUTFILE(OUTDD) NOERASE\n")
    assert cmds[0] == Export(
        entry=Name.parse("MY.CLUSTER"), outfile="OUTDD", erase=False
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_export_infile():
    cmds = parse_ams("EXPORT MY.CLUSTER OUTFILE(OUTDD) INFILE(INDD)\n")
    assert cmds[0] == Export(
        entry=Name.parse("MY.CLUSTER"), outfile="OUTDD", infile="INDD"
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_export_purge():
    cmds = parse_ams("EXPORT MY.CLUSTER OUTFILE(OUTDD) PURGE\n")
    assert cmds[0] == Export(
        entry=Name.parse("MY.CLUSTER"), outfile="OUTDD", purge=True
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_export_nopurge():
    cmds = parse_ams("EXPORT MY.CLUSTER OUTFILE(OUTDD) NOPURGE\n")
    assert cmds[0] == Export(
        entry=Name.parse("MY.CLUSTER"), outfile="OUTDD", purge=False
    )


# =========================================================================
# IMPORT: INFILE/INDATASET (required, exactly one)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_infile():
    cmds = parse_ams("IMPORT INFILE(INDD) OUTFILE(OUTDD)\n")
    assert cmds[0] == Import(infile="INDD", outfile="OUTDD")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_indataset():
    cmds = parse_ams("IMPORT INDATASET(MY.IN) OUTFILE(OUTDD)\n")
    assert cmds[0] == Import(indataset=Name.parse("MY.IN"), outfile="OUTDD")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_infile_indataset_together_raises():
    with pytest.raises(ValueError):
        parse_ams("IMPORT INFILE(INDD) INDATASET(MY.IN) OUTFILE(OUTDD)\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_missing_source_raises():
    with pytest.raises(ValueError):
        parse_ams("IMPORT OUTFILE(OUTDD)\n")


# =========================================================================
# IMPORT: OUTFILE/OUTDATASET (required, exactly one)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_outfile():
    cmds = parse_ams("IMPORT INFILE(INDD) OUTFILE(OUTDD)\n")
    assert cmds[0] == Import(infile="INDD", outfile="OUTDD")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_outdataset():
    cmds = parse_ams("IMPORT INFILE(INDD) OUTDATASET(MY.OUT)\n")
    assert cmds[0] == Import(infile="INDD", outdataset=Name.parse("MY.OUT"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_outfile_outdataset_together_raises():
    with pytest.raises(ValueError):
        parse_ams("IMPORT INFILE(INDD) OUTFILE(OUTDD) OUTDATASET(MY.OUT)\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_missing_target_raises():
    with pytest.raises(ValueError):
        parse_ams("IMPORT INFILE(INDD)\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_outfile_before_infile_order_independent():
    """OUTFILE placed before INFILE -- proves import_param is a flat,
    freely-repeatable list like REPRO's/PRINT's, not a fixed-order chain."""
    cmds = parse_ams("IMPORT OUTFILE(OUTDD) INFILE(INDD)\n")
    assert cmds[0] == Import(infile="INDD", outfile="OUTDD")


# =========================================================================
# IMPORT: ALIAS/NOALIAS, LOCK/UNLOCK, INTOEMPTY
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_alias():
    cmds = parse_ams("IMPORT INFILE(INDD) OUTFILE(OUTDD) ALIAS\n")
    assert cmds[0] == Import(infile="INDD", outfile="OUTDD", alias=True)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_noalias():
    cmds = parse_ams("IMPORT INFILE(INDD) OUTFILE(OUTDD) NOALIAS\n")
    assert cmds[0] == Import(infile="INDD", outfile="OUTDD", alias=False)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_lock():
    cmds = parse_ams("IMPORT INFILE(INDD) OUTFILE(OUTDD) LOCK\n")
    assert cmds[0] == Import(infile="INDD", outfile="OUTDD", lock=True)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_unlock():
    cmds = parse_ams("IMPORT INFILE(INDD) OUTFILE(OUTDD) UNLOCK\n")
    assert cmds[0] == Import(infile="INDD", outfile="OUTDD", lock=False)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_intoempty():
    cmds = parse_ams("IMPORT INFILE(INDD) OUTFILE(OUTDD) INTOEMPTY\n")
    assert cmds[0] == Import(infile="INDD", outfile="OUTDD", into_empty=True)


# =========================================================================
# IMPORT: OBJECTS(...) -- repeatable list of nested groups (the trickiest
# sub-structure in this task). Dedicated 2-object test below to confirm the
# list shape parses correctly, not just a single-object shape.
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_objects_two_entries_with_newname_and_volumes():
    cmds = parse_ams(
        "IMPORT INFILE(INDD) OUTFILE(OUTDD) "
        "OBJECTS("
        "(FIRST.ENTRY NEWNAME(FIRST.NEW) VOLUMES(VOL001 VOL002)) "
        "(SECOND.ENTRY NEWNAME(SECOND.NEW) VOLUMES(VOL003))"
        ")\n"
    )
    assert cmds[0] == Import(
        infile="INDD",
        outfile="OUTDD",
        objects=(
            ImportObject(
                entry=Name.parse("FIRST.ENTRY"),
                new_name=Name.parse("FIRST.NEW"),
                volumes=("VOL001", "VOL002"),
            ),
            ImportObject(
                entry=Name.parse("SECOND.ENTRY"),
                new_name=Name.parse("SECOND.NEW"),
                volumes=("VOL003",),
            ),
        ),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_objects_single_entry():
    cmds = parse_ams("IMPORT INFILE(INDD) OUTFILE(OUTDD) OBJECTS((ONLY.ENTRY))\n")
    assert cmds[0] == Import(
        infile="INDD",
        outfile="OUTDD",
        objects=(ImportObject(entry=Name.parse("ONLY.ENTRY")),),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_objects_file_managementclass_storageclass():
    cmds = parse_ams(
        "IMPORT INFILE(INDD) OUTFILE(OUTDD) "
        "OBJECTS((MY.ENTRY FILE(MYFILE) MANAGEMENTCLASS(MCLASS) "
        "STORAGECLASS(SCLASS)))\n"
    )
    assert cmds[0] == Import(
        infile="INDD",
        outfile="OUTDD",
        objects=(
            ImportObject(
                entry=Name.parse("MY.ENTRY"),
                file="MYFILE",
                management_class="MCLASS",
                storage_class="SCLASS",
            ),
        ),
    )


# =========================================================================
# IMPORT: remaining parameters (Step 6 coverage) -- ERASE/NOERASE,
# PURGE/NOPURGE, SAVRAC/NOSAVRAC, CATALOG, RLSTARGET
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_erase():
    cmds = parse_ams("IMPORT INFILE(INDD) OUTFILE(OUTDD) ERASE\n")
    assert cmds[0] == Import(infile="INDD", outfile="OUTDD", erase=True)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_noerase():
    cmds = parse_ams("IMPORT INFILE(INDD) OUTFILE(OUTDD) NOERASE\n")
    assert cmds[0] == Import(infile="INDD", outfile="OUTDD", erase=False)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_purge():
    cmds = parse_ams("IMPORT INFILE(INDD) OUTFILE(OUTDD) PURGE\n")
    assert cmds[0] == Import(infile="INDD", outfile="OUTDD", purge=True)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_nopurge():
    cmds = parse_ams("IMPORT INFILE(INDD) OUTFILE(OUTDD) NOPURGE\n")
    assert cmds[0] == Import(infile="INDD", outfile="OUTDD", purge=False)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_savrac():
    cmds = parse_ams("IMPORT INFILE(INDD) OUTFILE(OUTDD) SAVRAC\n")
    assert cmds[0] == Import(infile="INDD", outfile="OUTDD", save_racf=True)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_nosavrac():
    cmds = parse_ams("IMPORT INFILE(INDD) OUTFILE(OUTDD) NOSAVRAC\n")
    assert cmds[0] == Import(infile="INDD", outfile="OUTDD", save_racf=False)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_catalog():
    cmds = parse_ams("IMPORT INFILE(INDD) OUTFILE(OUTDD) CATALOG(MY.CAT)\n")
    assert cmds[0] == Import(infile="INDD", outfile="OUTDD", catalog="MY.CAT")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_import_rlstarget():
    cmds = parse_ams("IMPORT INFILE(INDD) OUTFILE(OUTDD) RLSTARGET(QUIESCE)\n")
    assert cmds[0] == Import(infile="INDD", outfile="OUTDD", rls_target="QUIESCE")
