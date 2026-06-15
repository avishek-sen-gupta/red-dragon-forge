# Richer SQL Model Types — Design

**Status:** approved (brainstorm) · **Bead:** squall-pzg · **Date:** 2026-06-15

## Problem

`squall.parser.parse.ParsedSql` is one flat frozen dataclass shared by ~37 statement
kinds, modelling kind-specific data as `X | None` Optionals — and the `str` fields are
really tiny closed sets:

```python
kind: str                         # actually one of ~37 grammar rule names
cursor: str | None
include_name: str | None
connect_variant: str | None       # only "TO" / "RESET"
connect_db: str | HostVar | None
whenever_condition: str | None     # only "SQLERROR" / "NOT FOUND" / "SQLWARNING"
whenever_action: str | None        # only "CONTINUE" / "GOTO"
whenever_target: str | None
```

Plus under-parameterized collections: `cursors: dict`, `_plans: list`,
`field_meta: Mapping[str, dict]`.

These types neither constrain values (any `str` passes) nor express which combinations
are valid, and they force `None`-handling throughout consumers.

## Goal

Eliminate `None` from the SQL model and give every field a precise type, **without
changing behaviour**. Keep a single `ParsedSql` dataclass (not a per-kind union); make
each field a non-optional value of a small sum type whose "absent" case is an explicit
**null object**, and make the dataless closed sets **proper enums**.

## Decisions (locked in brainstorm)

1. **One `ParsedSql` dataclass** — not a discriminated union of per-kind types. The
   sums live at the *field* level.
2. **No `None`.** Every previously-optional field becomes a non-optional sum whose
   "not applicable / absent" case is a named null object (`NoCursor`, `NoConnect`,
   `NoOpAction`, `WheneverCondition.NONE`, …).
3. **Types are pure data.** `sql_model.py` imports nothing from the interpreter or
   `squall.binding`. The `emit` (synthetic IF/GO TO lowering) and `resolve` (db-name
   from a host var) **behaviour lives in the consumers** (`strategy`, `binding`),
   which `match` on the sums.
4. **Proper `enum.Enum`, never `StrEnum`.** Dataless closed sets are plain `Enum` so
   there is no implicit `==` between an enum member and a `str`. The member *value*
   carries the grammar/source string only so the parser can construct the member
   (`Kind(stmt.data)`).
5. **Sum-with-data → frozen-dataclass union** (can't be a plain enum). Null objects in
   those unions are empty frozen dataclasses.
6. **Parameterize the loose collections.**

## The model — `squall/parser/sql_model.py` (new, pure-data module)

`HostVar` and `ParsedSql` move here from `parse.py`; `parse.py` becomes the builder.

### Enums (dataless closed sets)

```python
import enum

class Kind(enum.Enum):
    # one member per grammar `?stmt` alternative; value == the Lark rule name.
    SELECT_INTO = "select_into"
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
    DECLARE_CURSOR = "declare_cursor"
    DECLARE_TABLE = "declare_table"
    DECLARE_STATEMENT = "declare_statement"
    DECLARE_VARIABLE = "declare_variable"
    FETCH = "fetch"
    OPEN = "open_"
    CLOSE = "close"
    COMMIT = "commit"
    ROLLBACK = "rollback"
    SAVEPOINT = "savepoint"
    RELEASE = "release"
    CONNECT = "connect"
    SET_CONNECTION = "set_connection"
    DISCONNECT = "disconnect"
    INCLUDE = "include"
    WHENEVER = "whenever"
    ALLOCATE_CURSOR = "allocate_cursor"
    MERGE = "merge"
    VALUES_INTO = "values_into"
    PREPARE = "prepare"
    EXECUTE = "execute_"
    DESCRIBE = "describe"
    GET_DIAGNOSTICS = "get_diagnostics"
    SIGNAL = "signal"
    BEGIN_DECLARE = "begin_declare"
    END_DECLARE = "end_declare"
    FREE_LOCATOR = "free_locator"
    HOLD_LOCATOR = "hold_locator"
    ASSOCIATE = "associate"
    CALL = "call"
    SET = "set"
    LOCK = "lock"
    GENERIC = "generic"

class WheneverCondition(enum.Enum):
    SQLERROR = "SQLERROR"
    NOT_FOUND = "NOT FOUND"
    SQLWARNING = "SQLWARNING"
    NONE = "none"          # null object: statement carries no WHENEVER condition
```

`Kind(stmt.data)` constructs from the grammar rule name; `WheneverCondition(text)`
constructs from the normalised condition string the parser already builds. No member is
`==` to a bare string.

### Frozen-dataclass unions (sums carrying data; null objects are empty dataclasses)

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class HostVar:
    name: str
    indicator: str | None      # genuine optional of a host var; unchanged

# ── cursor reference ──────────────────────────────────────────────
@dataclass(frozen=True)
class NamedCursor:
    name: str
@dataclass(frozen=True)
class NoCursor:
    pass
CursorRef = NamedCursor | NoCursor

# ── INCLUDE target ────────────────────────────────────────────────
@dataclass(frozen=True)
class IncludeName:
    name: str
@dataclass(frozen=True)
class NoInclude:
    pass
IncludeRef = IncludeName | NoInclude

# ── connection directive ──────────────────────────────────────────
@dataclass(frozen=True)
class LiteralDb:
    name: str                  # upper-cased literal db name
@dataclass(frozen=True)
class HostVarDb:
    var: HostVar               # resolved at run time by the consumer
DbName = LiteralDb | HostVarDb

@dataclass(frozen=True)
class ConnectTo:
    db: DbName
@dataclass(frozen=True)
class ConnectReset:
    pass
@dataclass(frozen=True)
class NoConnect:
    pass
ConnectSpec = ConnectTo | ConnectReset | NoConnect

# ── WHENEVER action ───────────────────────────────────────────────
@dataclass(frozen=True)
class GoTo:
    target: str
@dataclass(frozen=True)
class Continue:
    pass
@dataclass(frozen=True)
class NoOpAction:
    pass
WheneverAction = GoTo | Continue | NoOpAction
```

### `ParsedSql` after

```python
@dataclass(frozen=True)
class ParsedSql:
    kind: Kind
    in_vars: tuple[HostVar, ...]
    out_vars: tuple[HostVar, ...]
    cursor: CursorRef
    query: str
    include: IncludeRef
    connect: ConnectSpec
    whenever_condition: WheneverCondition
    whenever_action: WheneverAction
```

No `None`, no defaults that mean "absent". For e.g. a `SELECT … INTO`:
`kind=Kind.SELECT_INTO, cursor=NoCursor(), include=NoInclude(), connect=NoConnect(),
whenever_condition=WheneverCondition.NONE, whenever_action=NoOpAction()`.

(`connect_variant` + `connect_db` collapse into the single `connect: ConnectSpec`;
`include_name` → `include`; `whenever_target` is absorbed into `GoTo.target`.)

### Collections (parameterized)

```python
from typing import TypedDict

class FieldMeta(TypedDict, total=False):
    category: str          # ZONED_DECIMAL | ALPHANUMERIC | COMP3 | BINARY | VARCHAR
    offset: int
    length: int
    total_digits: int
    decimal_digits: int
    signed: bool
    len_var: str           # VARCHAR group only
    text_var: str          # VARCHAR group only
```

- `SqlLoweringStrategy._plans: list[ParsedSql]`
- `_Ctx.cursors: dict[str, ParsedSql]`  (cursor name → its DECLARE plan)
- `_Ctx.field_meta: Mapping[str, FieldMeta]`; `make_exec_sql_builtin(field_meta=…)`,
  `apply_sql_prepass`/`PrepassResult`, `SqlLoweringStrategy` all retyped to
  `Mapping[str, FieldMeta]`.

## Behaviour stays in consumers (via `match`)

### `parse.py` (builder)
The `_*` helpers return the typed objects instead of `None`/tuples:
`_cursor_ref(stmt, kind) -> CursorRef`, `_include_ref(...) -> IncludeRef`,
`_connect_spec(...) -> ConnectSpec`, `_whenever_condition(...) -> WheneverCondition`,
`_whenever_action(...) -> WheneverAction`. `kind = Kind(stmt.data)`.

### `squall/strategy.py` (WHENEVER emit)
Keeps the condition→relation table, now keyed by the enum (no `None`, membership-tested):

```python
_WHENEVER_RELATION: dict[WheneverCondition, tuple[str, str]] = {
    WheneverCondition.SQLERROR: ("<", "0"),
    WheneverCondition.NOT_FOUND: ("=", "100"),
}
# state: dict[WheneverCondition, WheneverAction]
for condition, action in self._whenever.items():
    match action:
        case GoTo(target):
            if condition in _WHENEVER_RELATION:
                self._emit_if_goto(ctx, materialised, condition, target)
        case _:            # Continue, NoOpAction
            pass
```
The whenever directive branch updates state from `plan.whenever_condition` /
`plan.whenever_action`; a `Continue` overwrites the stored action so its branch stops
emitting (no `del`, no `None`).

### `squall/builtins/exec_sql.py` + `squall/binding.py` (connection)
`_resolve_db_name` is replaced by a `match` in the connect handler / binding:

```python
match spec:
    case ConnectTo(LiteralDb(name)):  db = name
    case ConnectTo(HostVarDb(var)):   db = str(read_params(vm, (var.name,), field_meta)[0]).strip().upper()
    case ConnectReset():              # disconnect
    # NoConnect() never reaches a connect handler
```
`_h_*` dispatch table becomes `dict[Kind, Handler]`; `plan.kind == "whenever"`-style
comparisons become `plan.kind is Kind.WHENEVER` etc.

## Testing

Pure type refactor, **zero behaviour change** — the existing **267** tests (unit + DB2
e2e) are the regression net. Add focused unit tests:
- parser builders return the right sum member for each form (`NoCursor` vs
  `NamedCursor`, `ConnectReset` vs `ConnectTo(LiteralDb/HostVarDb)`, `WheneverCondition`
  members, `GoTo`/`Continue`).
- strategy `match`: `GoTo` under an active relation emits a branch; `Continue`/`NoOpAction`
  emit nothing.
- binding/builtin `match`: `LiteralDb`/`HostVarDb` resolve correctly; `ConnectReset`
  disconnects.

`python_fp_lint` + `pyright` clean on the touched modules; the `Mapping`/`list`/`dict`
parameterization should *remove* pyright noise, not add it.

## Scope / non-goals

- **In scope:** `sql_model.py` (new), `parse.py`, `strategy.py`, `exec_sql.py`,
  `binding.py`, `preprocess.py` (the `PrepassResult.field_meta` type), and the tests.
- **Not a per-kind union** — explicitly rejected; one `ParsedSql`.
- **`FieldMeta.category` stays `str`** this pass. Its values are a closed set, but they
  originate in external dclgen JSON sidecars and are compared as strings across
  `binding.py`; promoting it to an enum is a separate binding-layer change, out of scope
  here.
- **Runtime execution dispatch stays kind-based** (`dict[Kind, Handler]`), not
  polymorphic — consistent with the single-dataclass decision.
- **No behaviour change**; no new SQL features.

## Risk

Mechanical breadth (six modules) is the main risk, contained by the 267-test net and a
TDD, per-module plan. `connect_variant`+`connect_db` → `connect` and `include_name` →
`include` are renames that ripple to every constructor/reader of those fields.
