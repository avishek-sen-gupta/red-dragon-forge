from bms_copybook_gen.models import BmsField, BmsMap, BmsMapSet
from bms_copybook_gen.generator import generate_copybook
from tests.covers import covers, NotLanguageFeature


def _mapset(maps, mode="INOUT", tioapfx=True):
    return BmsMapSet(label="MYSET", lang="COBOL", mode=mode, tioapfx=tioapfx, maps=maps)


def _map(label, fields):
    return BmsMap(label=label, elements=tuple(fields))


def _field(label, length, picout="", picin="", attrb=None, grpname="", occurs=0):
    return BmsField(
        label=label,
        length=length,
        attrb=tuple(attrb) if attrb else (),
        picout=picout,
        picin=picin,
        grpname=grpname,
        occurs=occurs,
    )


# ── output map (O suffix) ────────────────────────────────────────────────────


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_output_map_01_level():
    lines = generate_copybook(_mapset([_map("ORDERMAP", [])]))
    assert "       01  ORDERMAPO." in lines


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_tioapfx_yes_adds_filler_header():
    lines = generate_copybook(_mapset([_map("ORDERMAP", [])], tioapfx=True))
    assert "           02  FILLER                          PIC X(12)." in lines


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_tioapfx_no_omits_filler_header():
    lines = generate_copybook(_mapset([_map("ORDERMAP", [])], tioapfx=False))
    assert not any("PIC X(12)" in l for l in lines)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_field_length_subfield():
    lines = generate_copybook(_mapset([_map("M", [_field("ORDNO", 8)])]))
    assert "           02  ORDNOL                          PIC S9(4) COMP." in lines


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_field_attribute_byte():
    lines = generate_copybook(_mapset([_map("M", [_field("ORDNO", 8)])]))
    assert "           02  ORDNOA                          PIC X." in lines


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_field_flag_redefines():
    lines = generate_copybook(_mapset([_map("M", [_field("ORDNO", 8)])]))
    assert "           02  FILLER REDEFINES ORDNOA." in lines
    assert "               03  ORDNOF                      PIC X." in lines


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_field_output_pic_x_default():
    lines = generate_copybook(_mapset([_map("M", [_field("ORDNO", 8)])]))
    assert "           02  ORDNOO                          PIC X(8)." in lines


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_field_output_picout_overrides():
    lines = generate_copybook(
        _mapset([_map("M", [_field("ORDNO", 8, picout="99999999")])])
    )
    assert "           02  ORDNOO                          PIC 99999999." in lines


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_two_fields_in_sequence():
    fields = [_field("ORDNO", 8), _field("CUSTNAM", 30)]
    lines = generate_copybook(_mapset([_map("M", fields)]))
    ordno_idx = next(i for i, l in enumerate(lines) if "ORDNOO" in l)
    custnam_idx = next(i for i, l in enumerate(lines) if "CUSTNAMO" in l)
    assert ordno_idx < custnam_idx


# ── input map (I suffix) ─────────────────────────────────────────────────────


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_input_map_redefines_output():
    lines = generate_copybook(_mapset([_map("ORDERMAP", [])]))
    assert "       01  ORDERMAPI REDEFINES ORDERMAPO." in lines


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_input_map_field_uses_filler_for_length_and_attr():
    fields = [_field("ORDNO", 8)]
    lines = generate_copybook(_mapset([_map("M", fields)]))
    # In input map, length and attr are FILLER
    input_start = next(i for i, l in enumerate(lines) if "MI REDEFINES" in l)
    input_section = lines[input_start:]
    fillers = [l for l in input_section if "FILLER" in l and "PIC S9(4) COMP" in l]
    assert len(fillers) >= 1


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_input_field_pic_x_default():
    lines = generate_copybook(_mapset([_map("M", [_field("ORDNO", 8)])]))
    assert "           02  ORDNOI                          PIC X(8)." in lines


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_input_field_picin_overrides():
    lines = generate_copybook(
        _mapset([_map("M", [_field("ORDNO", 8, picin="99999999")])])
    )
    assert "           02  ORDNOI                          PIC 99999999." in lines


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_mode_out_omits_input_map():
    lines = generate_copybook(_mapset([_map("ORDERMAP", [])], mode="OUT"))
    assert not any("REDEFINES ORDERMAPO" in l for l in lines)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_mode_in_omits_output_data_field():
    lines = generate_copybook(_mapset([_map("M", [_field("ORDNO", 8)])], mode="IN"))
    assert not any("ORDNOO" in l for l in lines)


# ── OCCURS / GRPNAME ─────────────────────────────────────────────────────────


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_occurs_group_wraps_fields():
    f = _field("ITEMCD", 10, grpname="LINEITEM", occurs=10)
    lines = generate_copybook(_mapset([_map("M", [f])]))
    assert any("LINEITEM" in l and "OCCURS 10 TIMES" in l for l in lines)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_occurs_field_indented_under_group():
    f = _field("ITEMCD", 10, grpname="LINEITEM", occurs=10)
    lines = generate_copybook(_mapset([_map("M", [f])]))
    grp_idx = next(i for i, l in enumerate(lines) if "LINEITEM" in l and "OCCURS" in l)
    data_idx = next(i for i, l in enumerate(lines) if "ITEMCDO" in l)
    assert data_idx > grp_idx


# ── multiple maps ────────────────────────────────────────────────────────────


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_multiple_maps_each_get_own_01():
    maps = [_map("MAP1", [_field("F1", 5)]), _map("MAP2", [_field("F2", 10)])]
    lines = generate_copybook(_mapset(maps))
    assert any("MAP1O" in l and "01" in l for l in lines)
    assert any("MAP2O" in l and "01" in l for l in lines)


# ── input map no longer emits invalid "FILLER REDEFINES FILLER" ───────────────


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_input_map_has_no_filler_redefines_filler():
    # REDEFINES requires a data-name, not FILLER — the input map must not emit it.
    lines = generate_copybook(_mapset([_map("MYMAP", [_field("FLD", 8)])]))
    assert not any("FILLER REDEFINES FILLER" in l for l in lines)


# ── extended attributes (per-map: DFHMSD EXTATT=YES or DFHMDI DSATTS/MAPATTS) ──


def _map_extatt(label, fields):
    return BmsMap(label=label, extatt=True, elements=tuple(fields))


def _mapset_extatt(maps, mode="INOUT", tioapfx=True):
    return BmsMapSet(
        label="MYSET", lang="COBOL", mode=mode, tioapfx=tioapfx, extatt=True, maps=maps
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_extatt_output_emits_color_ps_highlight_validation_subfields():
    lines = generate_copybook(
        _mapset_extatt([_map_extatt("MYMAP", [_field("FLD", 8)])])
    )
    for suffix in ("C", "P", "H", "V"):
        assert any(f"02  FLD{suffix} " in l for l in lines), suffix
    # data field still present and after the attribute bytes
    assert any("02  FLDO " in l for l in lines)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_extatt_input_adds_four_filler_bytes_for_attributes():
    lines = generate_copybook(
        _mapset_extatt([_map_extatt("MYMAP", [_field("FLD", 8)])])
    )
    input_start = next(i for i, l in enumerate(lines) if "REDEFINES MYMAPO" in l)
    input_section = lines[input_start:]
    # the 4 extended-attribute bytes appear as a single FILLER X(4) in the input map
    assert any("02  FILLER" in l and "PIC X(4)." in l for l in input_section)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_no_extatt_omits_color_subfields():
    lines = generate_copybook(_mapset([_map("MYMAP", [_field("FLD", 8)])]))
    assert not any("02  FLDC " in l for l in lines)
