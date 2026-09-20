"""The SQL lowering strategy's writes into state it does not own.

Each store changes an object in place because its owner reads that same
object back afterwards: the VM looks builtins up in the process-global
``Builtins.TABLE``; the ``__exec_sql`` builtin closes over the plan-pool list
lowering appends to; and the ``field_meta`` store is the very dict the
``__exec_sql`` builtin's immutable ``MappingProxyType`` view already wraps,
handed to it at construction time (before the bridge JSON that
``preprocess_program_dict`` derives more metadata from is even available —
see ``squall.strategy``). A rebuilt copy of any of the three would go unseen
by its reader. Only those stores live here; every lowering decision stays
gated in strategy.py.
"""

from __future__ import annotations

import logging
from collections.abc import Container, Mapping, MutableSequence
from dataclasses import dataclass, field
from typing import TypeVar

from squall.parser.sql_model import FieldMeta, ParsedSql

T = TypeVar("T")


class Absent:
    """The explicit-absence type for a caller-supplied mutable store.

    ``None`` says "no value" without saying what kind of nothing; the
    project's standing ruling treats an ``X | None = None`` default plus an
    ``is None`` check as an admission of that ambiguity, not a fix for it.
    ``Absent`` names the one thing both ``SqlLoweringStrategy.stores`` and
    ``make_exec_sql_builtin``'s ``cursors`` actually mean by "not given":
    build a private, freshly-constructed store instead of sharing one. A
    single module-level default instance (unlike ``None``) can be reused
    safely across every call precisely because the two call sites never read
    ``ABSENT`` itself -- they only test identity and then construct their own
    store, the same way ``_NO_CONNECTOR`` is safely shared because
    ``NullDbConnector`` carries no per-caller state.
    """


ABSENT: Absent = Absent()


@dataclass(frozen=True)
class SharedSqlStores:
    """The three stores every program a single ``build_sql_spec`` serves must
    share, because only ONE ``__exec_sql`` builtin can exist at a time.

    ``register`` writes into the process-global ``Builtins.TABLE``, so the
    last ``SqlLoweringStrategy`` built wins -- and ``compile_program`` builds
    one strategy per program. Give each program its own stores and the
    surviving builtin closes over only the LAST program's: an earlier
    program's plan index then addresses a different statement in a shorter
    pool (IndexError, or silently the wrong SQL), its ``OPEN`` finds no
    cursor, and its VARCHAR host vars lose their DCLGEN metadata. Sharing one
    set across the spec makes plan indices globally unique and every
    program's cursors and field metadata reachable from the one surviving
    builtin -- the same spec-level sharing ``build_cics_spec`` already
    applies to ``context_holder``/``result_holder``/``program_cache``
    (forge-2xy).
    """

    plans: list[ParsedSql] = field(default_factory=list)
    field_meta: dict[str, FieldMeta] = field(default_factory=dict)
    cursors: dict[str, ParsedSql] = field(default_factory=dict)
    # Names ever written as an explicit sidecar declaration (constructor
    # ``field_meta`` or ``absorb_field_meta``), as opposed to a bridge-JSON
    # inference (``merge_field_meta``'s *derived*). Lets ``merge_field_meta``
    # tell the two apart in a store now shared region-wide: an explicit
    # declaration still outranks any inference, from any program, but two
    # inferences never compete on "whoever ran first" -- see
    # ``merge_field_meta``.
    sidecar_field_names: set[str] = field(default_factory=set)


# The overwrite warning is the strategy's own diagnostic; keep it on its logger.
logger = logging.getLogger("squall.strategy")

_OVERWRITING = "Builtins.TABLE already contains %s — overwriting."


def register(name: str, builtin: object) -> None:
    """Insert *builtin* into the process-global ``Builtins.TABLE`` under
    ``FuncName(name)``."""
    # Deferred import to avoid violating project-no-vm-internals import contract.
    from interpreter.func_name import FuncName
    from interpreter.vm.builtins import Builtins

    func_name = FuncName(name)
    if func_name in Builtins.TABLE:
        logger.warning(_OVERWRITING, func_name)
    Builtins.TABLE[func_name] = builtin


def append(items: MutableSequence[T], item: T) -> int:
    """Append *item* to *items* — the ``__exec_sql`` builtin's closed-over
    plan pool — and return the index it now lives at."""
    index = len(items)
    items.append(item)
    return index


def merge_cursors(
    store: dict[str, ParsedSql], derived: Mapping[str, ParsedSql]
) -> None:
    """Merge *derived* — ``DECLARE CURSOR`` plans recovered from outside
    PROCEDURE DIVISION (``squall.data_division_exec_sql``) — into *store* in
    place.

    *store* is ``SqlLoweringStrategy._cursors_store``, the exact dict object
    ``make_exec_sql_builtin`` holds as ``ctx.cursors``. Unlike
    ``merge_field_meta`` there is no sidecar-vs-inference precedence to
    settle — a cursor name reaches here from exactly one source — but the
    write must still land on this same object, never a rebuild, or a later
    OPEN would keep reading the old (pre-merge) dict forever.
    """
    store.update(derived)


def absorb_field_meta(
    store: dict[str, FieldMeta],
    sidecar: Mapping[str, FieldMeta],
    sidecar_field_names: set[str] | None = None,
) -> None:
    """Add one program's SIDECAR-declared field metadata to the spec's shared
    store, in place.

    Called once per program compiled from a single ``build_sql_spec``, from
    that spec's source-text stage. *sidecar* wins over what is there, the
    same precedence ``merge_field_meta`` applies in the other direction: an
    explicit sidecar declaration beats metadata a previous program's bridge
    JSON was only shape-recognised into. The write must land on this object,
    never a rebuild -- it is the dict the ``__exec_sql`` builtin's
    ``MappingProxyType`` view already wraps.

    *sidecar_field_names*, when given, records *sidecar*'s keys as
    sidecar-declared (see ``SharedSqlStores.sidecar_field_names``) so a later
    ``merge_field_meta`` call for any program can still tell an explicit
    declaration apart from an inference, even once *store* is shared
    region-wide.
    """
    store.update(sidecar)
    if sidecar_field_names is not None:
        sidecar_field_names.update(sidecar.keys())


def merge_field_meta(
    store: dict[str, FieldMeta],
    derived: Mapping[str, FieldMeta],
    sidecar_field_names: Container[str] = frozenset(),
) -> None:
    """Merge *derived* -- the CURRENT program's own bridge-JSON inference --
    into *store* in place.

    An explicit sidecar declaration (name present in *sidecar_field_names*)
    still outranks an inference, from any program: it is a positive
    statement, and shape recognition is only a guess. But between two
    inferences there is no such asymmetry, so *derived* wins over whatever is
    already in *store* for a name *not* in *sidecar_field_names*. Getting
    this backwards -- *store* winning outright, as a flat ``{**derived,
    **store}`` -- was fine when every strategy held a private store (each
    program's own metadata, nothing else, so "store wins" and "mine wins"
    were the same thing); now that ``SharedSqlStores.field_meta`` is one dict
    across the whole spec, unqualified "store wins" instead means "whichever
    program compiled first wins", silently handing program B's own host
    variable program A's leftover metadata whenever the bare COBOL names
    collide (see ``SharedSqlStores`` and the docstring on
    ``sidecar_field_names``).

    *store* is the live dict the ``__exec_sql`` builtin's ``MappingProxyType``
    view already wraps, so this replaces its *contents* (clear + update)
    rather than rebinding the name — a rebind would leave that view, and the
    builtin holding it, pointed at the old (pre-merge) mapping forever.
    """
    merged = dict(store)
    for name, meta in derived.items():
        if name not in sidecar_field_names:
            merged[name] = meta
    store.clear()
    store.update(merged)
