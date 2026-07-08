"""Typed AST for IDCAMS modal commands (comprehensive grammar): IF/THEN/ELSE/
DO/END, SET, CANCEL.

Shapes transcribed verbatim from the design spec's "Modal Commands" section
(2026-07-08-idcams-comprehensive-grammar-design.md). Architecturally
different from every other command module in this plan: IF is genuinely
recursive control flow (a THEN or ELSE clause can itself be another IF, up
to 10 levels deep per the manual), not another flat parameter list.

`AmsCommand` is the union of every functional command dataclass built by
Tasks 2-10 plus this task's own SetCommand/CancelCommand -- the return type
for a single top-level IDCAMS control statement. `IfCommand` is kept
separate from AmsCommand (rather than folded into it) because `then`/`else_`
need to hold IfCommand instances too (nested IF), and a Union can't
self-reference its own name inside its own definition cleanly without the
string-literal forward-reference form used below.

Null-command semantics (directly testable against the IBM manual's own
worked examples -- see test_idcams_modal.py):
  - `then: tuple[...] = ()` -- an empty tuple means "THEN was written but
    with no command after it" (a null THEN, syntactically valid: bare
    "THEN" followed immediately by "ELSE" or end of statement).
  - `else_: tuple[...] | None = None` -- None means "no ELSE clause was
    written at all"; an empty tuple () means "an ELSE clause WAS written
    but it's null" (bare "ELSE" with nothing after it). These are two
    different things and must not be conflated.
  - A `DO ... END` block under THEN/ELSE holds 2+ commands in the tuple; a
    single (non-DO) command under THEN/ELSE holds exactly 1.

Depth cap: the manual caps IF nesting at 10 levels. This is enforced by the
transformer (jackal.idcams.parser_comprehensive) while building IfCommand
instances, not by the grammar -- Earley parses arbitrarily deep recursion
without complaint, so the cap is a semantic/business-rule check, not a
syntax-level one.

This module is deliberately unrelated to jackal.idcams.commands.py's
IfMaxcc/SetMaxcc (the older, minimal, execution-wired IDCAMS grammar's own
modal-command handling -- single combined "IF MAXCC op n THEN SET MAXCC=n"
form only, no nesting, no DO/END, no LASTCC). Do not touch commands.py/
executor.py/parser.py/the top-level grammar.lark from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Union

from jackal.idcams.ast_alter import Alter
from jackal.idcams.ast_bldindex import Bldindex
from jackal.idcams.ast_define_alternateindex import DefineAlternateIndex
from jackal.idcams.ast_define_cluster import DefineCluster
from jackal.idcams.ast_define_gdg import DefineGenerationDataGroup
from jackal.idcams.ast_define_nonvsam import DefineNonvsam
from jackal.idcams.ast_define_path import DefinePath
from jackal.idcams.ast_delete import Delete
from jackal.idcams.ast_export import Export
from jackal.idcams.ast_import import Import
from jackal.idcams.ast_listcat import Listcat
from jackal.idcams.ast_print import Print
from jackal.idcams.ast_repro import Repro
from jackal.idcams.ast_verify import Verify

__all__ = ["AmsCommand", "SetCommand", "CancelCommand", "IfCommand"]


@dataclass(frozen=True)
class SetCommand:
    field: Literal["MAXCC", "LASTCC"]
    value: int


@dataclass(frozen=True)
class CancelCommand:
    pass


AmsCommand = Union[
    DefineCluster,
    DefineAlternateIndex,
    DefineGenerationDataGroup,
    DefineNonvsam,
    DefinePath,
    Delete,
    Alter,
    Repro,
    Print,
    Listcat,
    Export,
    Import,
    Verify,
    Bldindex,
    SetCommand,
    CancelCommand,
]


@dataclass(frozen=True)
class IfCommand:
    field: Literal["MAXCC", "LASTCC"]
    op: Literal["EQ", "NE", "GT", "LT", "GE", "LE"]  # bare "=" normalizes to EQ
    value: int
    then: "tuple[AmsCommand | IfCommand, ...]" = ()  # empty tuple = null THEN
    # None = no ELSE clause was written at all; () = an ELSE clause was
    # written but it's null (bare ELSE with nothing after it).
    else_: "tuple[AmsCommand | IfCommand, ...] | None" = None
