"""Typed AST for IDCAMS BLDINDEX (comprehensive grammar).

Field list transcribed verbatim from the design spec's `Bldindex` section
(2026-07-08-idcams-comprehensive-grammar-design.md).

Per the plan's ratified structural single-occurrence pattern (see
ast_export.py/ast_import.py/ast_repro.py for prior art), BLDINDEX has three
genuine "pick one" choice groups, each flat-grammar + transformer-enforced
(ams.lark's BLDINDEX section, ComprehensiveIdcamsTransformer.bldindex()):
  - INFILE/INDATASET (required, exactly one)
  - OUTFILE/OUTDATASET (required, exactly one -- note each of these itself
    accepts a LIST of 1+ ddnames/entrynames, e.g. OUTFILE(A B), to build
    multiple alternate indexes for the same base cluster in one invocation;
    modeled as outfiles/outdatasets tuple fields, not singular ones)
  - EXTERNALSORT/INTERNALSORT (optional, at most one -- which sort strategy)
  - SORTCALL/NOSORTCALL (optional, at most one -- which sort mechanism)

Per the manual, NOSORTCALL also disallows several other params
(SORTMESSAGELEVEL/SORTDEVICETYPE/SORTMESSAGEDD/SORTFILENUMBER) being
specified together with it -- that deeper cross-field interaction is NOT
modeled here; the design spec's Bldindex section does not call for it, so
only the SORTCALL/NOSORTCALL mutual exclusivity itself is enforced.

SORTDEVICETYPE, SORTFILENUMBER, SORTMESSAGEDD, SORTMESSAGELEVEL, WORKFILES,
and CATALOG are ordinary single-occurrence (or, for WORKFILES, plain list)
params -- no mutual-exclusivity machinery needed for any of these.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from jackal.idcams.ast_values import Name

__all__ = ["Bldindex"]


@dataclass(frozen=True)
class Bldindex:
    infile: str | None = None  # mutually exclusive with indataset
    indataset: Name | None = None
    outfiles: tuple[str, ...] = ()  # mutually exclusive with outdatasets
    outdatasets: tuple[Name, ...] = ()
    sort_kind: Literal["EXTERNALSORT", "INTERNALSORT"] | None = None
    sort_call: bool | None = None  # SORTCALL | NOSORTCALL, default True
    sort_device_type: str | None = None
    sort_file_number: int | None = None
    sort_message_dd: str | None = None
    sort_message_level: Literal["ALL", "CRITICAL", "NONE"] | None = None
    work_files: tuple[str, ...] = ()
    catalog: str | None = None
