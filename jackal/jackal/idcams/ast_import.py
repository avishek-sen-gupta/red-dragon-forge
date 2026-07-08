"""Typed AST for IDCAMS IMPORT (comprehensive grammar).

Field list transcribed verbatim from the design spec's `Import` section
(2026-07-08-idcams-comprehensive-grammar-design.md).

Per the plan's ratified structural single-occurrence pattern, IMPORT has
two genuine required "pick one" choice groups, each flat-grammar +
transformer-enforced (ams.lark's IMPORT section,
ComprehensiveIdcamsTransformer.import_cmd()):
  - INFILE/INDATASET (required, exactly one)
  - OUTFILE/OUTDATASET (required, exactly one)

ALIAS/NOALIAS, ERASE/NOERASE, LOCK/UNLOCK, PURGE/NOPURGE, and
SAVRAC/NOSAVRAC are ordinary simple ON/OFF toggle pairs -- left as
freely-repeatable parameters per the plan's ratified scope for simple
booleans.

`OBJECTS(...)` is a REPEATABLE list of nested groups, not a mutual-
exclusivity choice -- each group carries its own required positional
`entry` plus independently-optional FILE/MANAGEMENTCLASS/NEWNAME/
STORAGECLASS/VOLUMES sub-fields (ImportObject).

Note on the module/dataclass name: `Import` is not a reserved Python
identifier (only the `import` *statement* keyword is reserved), so the
dataclass is safely named `Import`. The grammar rule and its transformer
callback are named `import_cmd`, not `import`, because a method literally
named `import` would be a Python syntax error.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from jackal.idcams.ast_values import Name

__all__ = ["ImportObject", "Import"]


@dataclass(frozen=True)
class ImportObject:
    entry: Name
    file: str | None = None
    management_class: str | None = None
    new_name: Name | None = None
    storage_class: str | None = None
    volumes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Import:
    infile: str | None = None  # mutually exclusive with indataset
    indataset: Name | None = None
    outfile: str | None = None  # mutually exclusive with outdataset
    outdataset: Name | None = None
    alias: bool | None = None
    erase: bool | None = None
    into_empty: bool = False
    lock: bool | None = None
    objects: tuple[ImportObject, ...] = ()
    purge: bool | None = None
    save_racf: bool | None = None  # SAVRAC | NOSAVRAC
    catalog: str | None = None
    rls_target: Literal["NO", "YES", "QUIESCE"] | None = None
