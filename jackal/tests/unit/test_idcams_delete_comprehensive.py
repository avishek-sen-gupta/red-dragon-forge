"""Tests for IDCAMS DELETE parsing into the comprehensive AST.

Covers every parameter listed in the design spec's Delete section
(2026-07-08-idcams-comprehensive-grammar-design.md): the positional
entries list (multi-entry parenthesized form and single-entry elision),
each of the 13 EntryType values (kept as a single-occurrence choice per
the plan's ratified scoping decision -- entry_type is the one genuine
"pick one kind" choice in DELETE), MASK filter-key patterns, and the six
documented ON/OFF toggle pairs (ERASE/NOERASE, FORCE/NOFORCE, MASK/NOMASK,
PURGE/NOPURGE, RECOVERY/NORECOVERY, SCRATCH/NOSCRATCH) plus NODISCONNECT,
CATALOG, and FILE.
"""

from __future__ import annotations

import pytest
from lark.exceptions import LarkError

from jackal.idcams.ast_delete import Delete
from jackal.idcams.ast_values import Name
from jackal.idcams.parser_comprehensive import parse_ams
from tests.covers import NotLanguageFeature, covers

# =========================================================================
# Positional entries list
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_multi_entry_list():
    cmds = parse_ams("DELETE (A B C)\n")
    assert cmds[0] == Delete(
        entries=(Name.parse("A"), Name.parse("B"), Name.parse("C")),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_single_entry_elision():
    cmds = parse_ams("DELETE A\n")
    assert cmds[0] == Delete(entries=(Name.parse("A"),))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_bare_dsname_no_type_keyword():
    """Real-corpus form: DELETE dsname with no trailing type keyword at
    all (not even CLUSTER) -- this comprehensive grammar must support the
    bare form independently of the older minimal grammar's own fix."""
    cmds = parse_ams("DELETE MY.DATASET.NAME\n")
    assert cmds[0] == Delete(entries=(Name.parse("MY.DATASET.NAME"),))
    assert cmds[0].entry_type is None


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_entries_qualified_names():
    cmds = parse_ams("DELETE (A.B.C A.B.D)\n")
    assert cmds[0].entries == (Name.parse("A.B.C"), Name.parse("A.B.D"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_entries_over_100_raises():
    names = " ".join(f"ENTRY{i}" for i in range(101))
    with pytest.raises(ValueError, match="100"):
        parse_ams(f"DELETE ({names})\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_entries_exactly_100_ok():
    names = " ".join(f"ENTRY{i}" for i in range(100))
    cmds = parse_ams(f"DELETE ({names})\n")
    assert len(cmds[0].entries) == 100


# =========================================================================
# EntryType (single-occurrence choice)
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_entry_type_alias():
    cmds = parse_ams("DELETE A ALIAS\n")
    assert cmds[0].entry_type == "ALIAS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_entry_type_alternateindex():
    cmds = parse_ams("DELETE A ALTERNATEINDEX\n")
    assert cmds[0].entry_type == "ALTERNATEINDEX"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_entry_type_cluster():
    cmds = parse_ams("DELETE A CLUSTER\n")
    assert cmds[0].entry_type == "CLUSTER"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_entry_type_generationdatagroup():
    cmds = parse_ams("DELETE A GENERATIONDATAGROUP\n")
    assert cmds[0].entry_type == "GENERATIONDATAGROUP"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_entry_type_libraryentry():
    cmds = parse_ams("DELETE A LIBRARYENTRY\n")
    assert cmds[0].entry_type == "LIBRARYENTRY"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_entry_type_nonvsam():
    cmds = parse_ams("DELETE A NONVSAM\n")
    assert cmds[0].entry_type == "NONVSAM"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_entry_type_nvr():
    cmds = parse_ams("DELETE A NVR\n")
    assert cmds[0].entry_type == "NVR"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_entry_type_pagespace():
    cmds = parse_ams("DELETE A PAGESPACE\n")
    assert cmds[0].entry_type == "PAGESPACE"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_entry_type_path():
    cmds = parse_ams("DELETE A PATH\n")
    assert cmds[0].entry_type == "PATH"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_entry_type_truename():
    cmds = parse_ams("DELETE A TRUENAME\n")
    assert cmds[0].entry_type == "TRUENAME"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_entry_type_usercatalog():
    cmds = parse_ams("DELETE A USERCATALOG\n")
    assert cmds[0].entry_type == "USERCATALOG"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_entry_type_volumeentry():
    cmds = parse_ams("DELETE A VOLUMEENTRY\n")
    assert cmds[0].entry_type == "VOLUMEENTRY"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_entry_type_vvr():
    cmds = parse_ams("DELETE A VVR\n")
    assert cmds[0].entry_type == "VVR"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_entry_type_twice_raises():
    """entry_type is a genuine 'pick one kind' choice (an entry can't be
    both CLUSTER and PATH at once) -- must be structurally at-most-once,
    per the plan's ratified scoping decision."""
    with pytest.raises(LarkError):
        parse_ams("DELETE A CLUSTER PATH\n")


# =========================================================================
# MASK filter-key patterns
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_mask_double_star_pattern():
    cmds = parse_ams("DELETE (PROD.**.DATA) MASK\n")
    assert cmds[0].entries == (Name(text="PROD.**.DATA", generic=True),)
    assert cmds[0].mask is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_mask_percent_pattern():
    cmds = parse_ams("DELETE (PROD.%YYY.DATA) MASK\n")
    assert cmds[0].entries == (Name(text="PROD.%YYY.DATA", generic=True),)
    assert cmds[0].mask is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_nomask():
    cmds = parse_ams("DELETE A NOMASK\n")
    assert cmds[0].mask is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_mask_defaults_none():
    cmds = parse_ams("DELETE A\n")
    assert cmds[0].mask is None


# =========================================================================
# ON/OFF toggle pairs
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_force():
    cmds = parse_ams("DELETE A FORCE\n")
    assert cmds[0].force is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_noforce():
    cmds = parse_ams("DELETE A NOFORCE\n")
    assert cmds[0].force is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_purge():
    cmds = parse_ams("DELETE A PURGE\n")
    assert cmds[0].purge is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_nopurge():
    cmds = parse_ams("DELETE A NOPURGE\n")
    assert cmds[0].purge is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_recovery():
    cmds = parse_ams("DELETE A RECOVERY\n")
    assert cmds[0].recovery is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_norecovery():
    cmds = parse_ams("DELETE A NORECOVERY\n")
    assert cmds[0].recovery is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_scratch():
    cmds = parse_ams("DELETE A SCRATCH\n")
    assert cmds[0].scratch is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_noscratch():
    cmds = parse_ams("DELETE A NOSCRATCH\n")
    assert cmds[0].scratch is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_erase():
    cmds = parse_ams("DELETE A ERASE\n")
    assert cmds[0].erase is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_noerase():
    cmds = parse_ams("DELETE A NOERASE\n")
    assert cmds[0].erase is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_nodisconnect():
    cmds = parse_ams("DELETE A NODISCONNECT\n")
    assert cmds[0].no_disconnect is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_nodisconnect_defaults_false():
    cmds = parse_ams("DELETE A\n")
    assert cmds[0].no_disconnect is False


# =========================================================================
# CATALOG / FILE
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_catalog():
    cmds = parse_ams("DELETE A CATALOG(MYCAT)\n")
    assert cmds[0].catalog == "MYCAT"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_file():
    cmds = parse_ams("DELETE A FILE(MYDD)\n")
    assert cmds[0].file == "MYDD"


# =========================================================================
# Full command, every parameter together
# =========================================================================


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_full():
    cmds = parse_ams(
        "DELETE (A.B.C A.B.D) CLUSTER -\n"
        "  CATALOG(MYCAT) ERASE FILE(MYDD) FORCE MASK -\n"
        "  NODISCONNECT PURGE RECOVERY SCRATCH\n"
    )
    assert cmds[0] == Delete(
        entries=(Name.parse("A.B.C"), Name.parse("A.B.D")),
        entry_type="CLUSTER",
        catalog="MYCAT",
        erase=True,
        file="MYDD",
        force=True,
        mask=True,
        no_disconnect=True,
        purge=True,
        recovery=True,
        scratch=True,
    )
