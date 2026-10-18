"""
squall.dclgen_meta
~~~~~~~~~~~~~~~~~~~
Derives DCLGEN VARCHAR host-var metadata directly from the raw ProLeap bridge
JSON — the same ``data_fields`` tree (``name`` / ``level`` / ``pic`` / ``usage``
/ ``children``) the bridge emits for every program.

Why this exists: ``squall.binding``'s level-49 VARCHAR codec is only reached
when ``field_meta[name]["category"] == "VARCHAR"``, and this is the one source
of that metadata. Recognising the DCLGEN VARCHAR *shape* — a group whose two
children are both level 49: a ``PIC S9(4) USAGE COMP`` length prefix
immediately followed by a ``PIC X(n)`` text field — works for squall-generated
and hand-written IBM DCLGEN copybooks alike, with no dependence on a live DB
connection or any DCLGEN naming convention.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from cobol_asg.usage_synonyms import canonical_usage
from squall.parser.sql_model import FieldMeta

# A level-49 VARCHAR length prefix is always signed 4-digit binary: PIC S9(4)
# COMP. The digit count is fixed by DB2's own VARCHAR length-prefix format, so
# this pattern (rather than a generic S9(n) COMP match) is deliberately exact.
_LEN_PIC = re.compile(r"^S9\(4\)$")
_TEXT_PIC = re.compile(r"^X\((\d+)\)$")

# One node of the raw bridge JSON's data_fields tree: {"name", "level", "pic",
# "usage", "children": [...]}, plus other keys (offset, line/col spans, ...)
# this module never reads. `Any` is the JSON boundary itself, not a lazy
# stand-in for a type this module could otherwise state precisely.
_Field = Mapping[str, Any]


def _is_varchar_len_child(field: _Field) -> bool:
    """True for a level-49 ``PIC S9(4) USAGE COMP`` binary length prefix."""
    usage = canonical_usage(str(field.get("usage", "")))
    match field.get("level"), usage, field.get("pic"):
        case 49, "COMP", str(pic) if _LEN_PIC.match(pic):
            return True
        case _:
            return False


def _text_lengths(field: _Field) -> tuple[int, ...]:
    """The declared character length of a level-49 ``PIC X(n)`` text field, as
    a 0-or-1-element tuple — empty when *field* isn't one."""
    match field.get("level"), field.get("pic"):
        case 49, str(pic):
            return tuple(int(n) for n in _TEXT_PIC.findall(pic))
        case _:
            return ()


def _varchar_field_metas(group: _Field) -> tuple[FieldMeta, ...]:
    """0-or-1 ``FieldMeta`` for *group*, present iff its children are exactly
    the DCLGEN VARCHAR pair — [level-49 LEN, level-49 TEXT], in that order.
    A plain group, a group with any other number of children, or one whose
    two children aren't this exact LEN/TEXT pair yields none."""
    match tuple(group.get("children") or ()):
        case (len_child, text_child) if _is_varchar_len_child(len_child):
            return tuple(
                FieldMeta(
                    category="VARCHAR",
                    length=length,
                    len_var=len_child["name"],
                    text_var=text_child["name"],
                )
                for length in _text_lengths(text_child)
            )
        case _:
            return ()


def _walk(fields: Sequence[_Field]) -> Iterator[tuple[str, FieldMeta]]:
    """Depth-first walk of a ``data_fields`` tree, yielding ``(name, meta)``
    for every DCLGEN VARCHAR group found at any depth."""
    here = (
        (field["name"], meta)
        for field in fields
        for meta in _varchar_field_metas(field)
    )
    deeper = (
        pair for field in fields for pair in _walk(tuple(field.get("children") or ()))
    )
    return itertools.chain(here, deeper)


def derive_field_meta(program: _Field) -> Mapping[str, FieldMeta]:
    """Recognise every DCLGEN VARCHAR (level-49) group in *program*'s
    ``data_fields`` tree and return ``{group_name: FieldMeta}`` for them.

    *program* is the raw bridge JSON dict ``SqlLoweringStrategy.
    preprocess_program_dict`` receives — before ProLeap's dict is turned into
    a ``CobolASG`` — so this depends on nothing but shape: no live
    DB connection, no DCLGEN naming convention. A program with no VARCHAR
    groups (or no ``data_fields`` at all) yields ``{}``.
    """
    return dict(_walk(tuple(program.get("data_fields") or ())))
