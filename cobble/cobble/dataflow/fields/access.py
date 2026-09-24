"""Field-access rows: one per (site, extent) across every node in a CFG.

The CFG carries field names in ``node.reads`` (ASSIGN/CALL nodes) and in
``atom.left`` / ``atom.right`` (TEST nodes).  This module resolves those names
to byte extents via the per-program ASG and emits one ``AccessRow`` per hit,
deduped by (site, field name, start offset).

This is deliberately separate from the data-flow trace: the trace records
what data flows where through assignments; the access rows record what fields
are *examined* at each node, including conditional tests that produce no
assignment at all.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from cobble.dataflow.srccfg.build_corpus import cfg_dicts_of, load_document
from dataclasses import dataclass
from pathlib import Path

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.extent import CellIndex, cell_index, operand_extents
from cobble.dataflow.layout import UnsizeableFieldError, program_records
from cobol_asg.asg_types import CobolASG
from cobol_asg.ref_mod import RefModOperand
from cobol_memory.field_extent import FieldExtent

logger = logging.getLogger(__name__)

_JsonRow = Mapping[str, str | int | bool]


@dataclass(frozen=True)
class AccessRow:
    """One field-read event: the site that read it and the byte extent."""

    program: str
    site: str
    paragraph: str
    extent: FieldExtent


def _is_synthetic(name: str) -> bool:
    """True for names that denote no layout field."""
    return (
        not name
        or name.startswith("%")
        or ":" in name
        or name.startswith("'")
        or (len(name) > 0 and name[0].isdigit())
    )


def _real_names(names: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(n for n in names if not _is_synthetic(n)))


def _names_from_node(node: _JsonRow) -> tuple[str, ...]:
    """Field names read at this node, deduped, synthetics removed."""
    reads = _real_names(list(node.get("reads", [])))  # type: ignore[arg-type]
    atom = node.get("atom") or {}
    if node.get("kind") == "TEST":
        extra = _real_names([str(atom.get("left", "")), str(atom.get("right", ""))])
        return tuple(dict.fromkeys((*reads, *extra)))
    return reads


def _try_index(program: str, asg_dir: Path) -> tuple[CellIndex, ...]:
    """Return a one-tuple with the index, or empty on failure."""
    path = asg_dir / f"{program}.json"
    if not path.is_file():
        logger.warning("access: no ASG for %s, skipping", program)
        return ()
    with cached_asg_dialect_parsers_registered():
        asg = CobolASG.from_dict(json.loads(path.read_text(encoding="utf-8")))
    try:
        return (cell_index(program_records(asg)),)
    except UnsizeableFieldError as exc:
        logger.warning("access: cannot size %s: %s", program, exc)
        return ()


def _rows_for_node(
    program: str, node: _JsonRow, idx: CellIndex
) -> tuple[AccessRow, ...]:
    return tuple(
        AccessRow(
            program=program,
            site=f"{program}/{node['id']}",
            paragraph=str(node.get("paragraph", "")),
            extent=extent,
        )
        for name in _names_from_node(node)
        for extent in operand_extents(RefModOperand(name=name), idx).extents
    )


def _rows_for_program(entry: _JsonRow, asg_dir: Path) -> tuple[AccessRow, ...]:
    program = str(entry["program"])
    logger.info("access: %s", program)
    indices = _try_index(program, asg_dir)
    if not indices:
        return ()
    idx = indices[0]
    rows = tuple(
        row
        for node in entry["nodes"]  # type: ignore[union-attr]
        for row in _rows_for_node(program, node, idx)
    )
    logger.info("access: %s — %d rows", program, len(rows))
    return rows


def accesses(cfg_path: Path, asg_dir: Path) -> tuple[AccessRow, ...]:
    """All access rows across every program in ``cfg_path``."""
    all_rows = tuple(
        row for entry in cfg_dicts_of(load_document(cfg_path)) for row in _rows_for_program(entry, asg_dir)
    )
    keyed = {
        (row.site, row.extent.field_name, row.extent.start): row for row in all_rows
    }
    return tuple(keyed.values())
