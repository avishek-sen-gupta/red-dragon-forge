"""Typed AST for IDCAMS DEFINE NONVSAM (comprehensive grammar).

DEFINE NONVSAM catalogs a non-VSAM (e.g. sequential, PDS) data set. Like
DEFINE GENERATIONDATAGROUP it has no DATA(...)/INDEX(...) trailers and no
mutually-exclusive-choice groups. Two of its parameters need dedicated
grammar handling rather than reuse of DEFINE CLUSTER's rules:

- VOLUMES accepts the ordinary volser-list form, but ALSO two "indirect"
  forms: the literal six-asterisk placeholder `VOLUMES(******)` and a
  symbolic `VOLUMES(&SYSR2)`-style form (`&` + up to 5 more characters).
  Neither is expressible by DEFINE CLUSTER's plain `NAME+` volumes_param,
  since `*` and `&` aren't valid NAME-start characters.
- DEVICETYPES accepts device-type names that are conventionally all-numeric
  (e.g. `3390`) including the special all-zeros placeholder `DEVICETYPES
  (0000)` meaning "resolve at LOCATE/DELETE time" -- NAME's terminal
  requires an alphabetic/special leading character, so a numeric-leading
  device-type token needs its own terminal.

Field list transcribed verbatim from the design spec's `DefineNonvsam`
section (2026-07-08-idcams-comprehensive-grammar-design.md).
"""

from __future__ import annotations

from dataclasses import dataclass

from jackal.idcams.ast_values import Name, Retention

__all__ = ["DefineNonvsam"]


@dataclass(frozen=True)
class DefineNonvsam:
    name: Name
    device_types: tuple[str, ...]
    volumes: tuple[str, ...]
    catalog: str | None = None
    collection: bool = False  # obsolete, accepted for RECATALOG compatibility only
    file_sequence_numbers: tuple[int, ...] = ()
    owner: str | None = None
    recatalog: bool | None = None
    retention: Retention | None = None
