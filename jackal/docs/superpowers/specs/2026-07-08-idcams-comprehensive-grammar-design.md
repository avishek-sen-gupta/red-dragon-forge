# IDCAMS Comprehensive Grammar Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:writing-plans to turn this spec into a task-by-task implementation plan, then superpowers:subagent-driven-development to execute it.

**Goal:** Replace jackal's minimal IDCAMS grammar/AST (currently: `DELETE`, `DEFINE CLUSTER`, `REPRO`, the combined `IF MAXCC...THEN SET MAXCC`, and the standalone `SET MAXCC` added this session) with a comprehensive Lark grammar and typed AST covering every command a real batch job plausibly uses, built against IBM's z/OS DFSMS Access Method Services Commands manual (`docs/idcams-ref.pdf`, SC23-6846-40). Parsing only — execution semantics (wiring new AST nodes into `executor.py`) are explicitly out of scope for this mission.

**Architecture:** One Lark grammar rule and one frozen Python dataclass per command, with every field named after its real IBM parameter — no generic `Command(verb, params)` catch-all. Full lexical fidelity to the manual's continuation-character rules (`-` vs `+` are genuinely different), terminator rules (semicolon), comment syntax (`/* */`), quoted-string escaping, and hex/binary literal forms.

**Tech Stack:** Lark (`earley` parser, matching the existing `jackal/jackal/idcams/parser.py` convention), Python frozen dataclasses.

## Global Constraints

- **No generic AST nodes.** Every command gets its own dataclass with real parameter names as fields. A reviewer finding a `Param(name, args)`-shaped bag standing in for a command's actual parameters is a spec violation, not a style nitpick.
- **Both continuation characters are modeled per spec, not simplified.** `-` continues the command (record boundary is just whitespace). `+` continues the command *and* forces a value to join across the record boundary with **no inserted whitespace** — this must be a real lexer/grammar behavior, not silently treated the same as `-`.
- **Semicolon terminator** ends a command; everything after it on the same physical line is a comment (not lexed as command content) and does not prevent the *next* line from being genuinely new syntax (verified in the manual's own worked example: a `-`-continued record after a semicolon-terminated one still continues correctly).
- **`/* ... */` comments** are ignorable anywhere between tokens (distinct from JCL's own `//*` line comments, which the bridge already strips before this text ever reaches the IDCAMS parser).
- **Quoted strings** (`'...'`) may contain commas, semicolons, blanks, parentheses, and slashes; an embedded quote is written as two consecutive quotes (`''` → literal `'`).
- **Hex (`X'...'`) and binary (`B'...'`) literal forms** are valid wherever a plain value is valid.
- **Generic/wildcard names** (`A.*`, `A.*.C`) follow the manual's restricted pattern (asterisk replaces exactly one qualifier; never the leftmost qualifier; never more than one occurrence; `A.*.*`, `A.B*`, `*.B.C` are explicitly invalid and must be rejected, not silently accepted).
- **List/single elision**: a parenthesized list drops its enclosing parens when it contains exactly one item (`DELETE(entryname)` ≡ `DELETE entryname` where the manual allows it); this applies recursively to nested parameter groups, not just the top-level entry list.
- **Positional parameters precede keyword parameters** and are never optional, per the manual's own general command structure (`COMMAND parameters ... [terminator]`).
- **Keyword abbreviations are an explicit non-goal.** Every abbreviation IBM documents (e.g. `DATASET` → `DA`/`DSN`/`DSNAME`) is out of scope — real CardDemo JCL never abbreviates, and building abbreviation-resolution tables for every parameter across every command is a large, low-value undertaking for zero real corpus benefit. Grammar rules use only the full keyword spelling.
- **Existing execution-wired path is untouched.** `Delete`, `DefineCluster`, `Repro`, `IfMaxcc`, `SetMaxcc` in `jackal/jackal/idcams/commands.py`/`executor.py`/`parser.py` (the current, minimal, already-shipped grammar) are not modified or removed by this work. The new comprehensive grammar/AST lives in new files alongside them. A later, separate mission decides how (or whether) to connect the new AST to execution.
- **Nested `IF` depth is capped at 10**, per the manual's stated maximum, not left to recurse unbounded.

---

## In-Scope Commands

Full dataclass + grammar rule, built to real IBM parameter fidelity:

**`DEFINE`** — `CLUSTER`, `ALTERNATEINDEX`, `PATH`, `GENERATIONDATAGROUP`, `NONVSAM` (five distinct object-type dataclasses, sharing no code beyond common value types)
**`DELETE`** — single dataclass with an entry-type enum (see below)
**`ALTER`** — single dataclass (large — ~45 optional fields)
**`REPRO`** — single dataclass, including the `ENCIPHER`/`DECIPHER` cryptographic sub-blocks as nested dataclasses (they're part of REPRO's real syntax, not a separate command)
**`PRINT`**, **`LISTCAT`**, **`EXPORT`**, **`IMPORT`**, **`VERIFY`**, **`BLDINDEX`** — one dataclass each
**Modal commands**: `IF`/`THEN`/`ELSE`/`DO`/`END` (one recursive dataclass), `SET`, `CANCEL`, `PARM` (diagnostic-only but syntactically simple — modeled for completeness)

## Explicitly Out of Scope

No dataclass, no grammar rule, no tests — these are storage-administrator/tape-library/diagnostic tools, never invoked by application batch JCL like CardDemo: `ALLOCATE`, `ALTER LIBRARYENTRY`, `ALTER VOLUMEENTRY`, `CREATE LIBRARYENTRY`, `CREATE VOLUMEENTRY`, `DCOLLECT`, `DIAGNOSE`, `EXAMINE`, `SETCACHE`, `SHCDS`, `LISTDATA`, `DEFINE ALIAS`, `DEFINE USERCATALOG`, `DEFINE PAGESPACE`, `EXPORT DISCONNECT`, `IMPORT CONNECT`. If a later mission needs any of these, it gets its own spec addendum — do not build them speculatively now.

**Deferred within `ALTER`:** `STAGE` — its prose definition wasn't recoverable from the manual excerpt read for this spec (only its table row is confirmed to exist). Filed as a follow-up rather than guessed at; the `Alter` dataclass ships without a `stage` field, and the grammar does not accept the keyword. `READPW`/`UPDATEPW` are deliberately omitted — the manual states passwords are no longer honored and will be ignored if specified, so they carry no semantic weight.

---

## Value Representation

IDCAMS values are one of: a plain name/qualified-name token, a quoted string, a hex literal, a binary literal, or a decimal integer. New to this module (distinct from JCL's `jackal.value_parts.Value` — IDCAMS is a separate small language with its own value grammar, not JCL symbol substitution):

```python
# jackal/jackal/idcams/ast_values.py
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Name:
    """A plain or qualified name, e.g. A.B.C, or a generic name (A.*, A.*.C)."""
    text: str
    generic: bool = False  # True if this name contains a validated wildcard qualifier

@dataclass(frozen=True)
class QuotedString:
    text: str  # already de-escaped ('' -> ')

@dataclass(frozen=True)
class HexLiteral:
    raw: str  # hex digits between X'...'

@dataclass(frozen=True)
class BinLiteral:
    raw: str  # binary digits between B'...'

Value = Name | QuotedString | HexLiteral | BinLiteral | int
```

Grammar-level generic-name validation (asterisk rules above) happens in the transformer, not deferred to a later semantic pass — an invalid generic name is a parse error.

---

## Continuation & Terminator Lexing

The existing grammar's `%ignore /[ \t\r\n]+/` and `%ignore /-[ \t]*(?=\r?\n)/` patterns are the starting point but are insufficient. New lexer behavior required:

1. **`-` continuation**: unchanged from today — a trailing hyphen (optionally followed by blanks) before a newline is stripped, and the next record's leading blanks are also insignificant (normal token/whitespace boundary).
2. **`+` continuation**: a trailing plus sign (optionally followed by blanks) before a newline means the *value token straddling the line break* must be reassembled with the two fragments concatenated **directly**, no whitespace inserted — e.g. a long quoted string or name broken mid-token across two records. This cannot be a blanket `%ignore` regex the way `-` is, because it must not insert a token boundary; it requires either a lexer callback/contextual rule that joins the two physical-line fragments into one logical token before the value-parsing rule sees it, or a dedicated `PLUS_CONTINUED_VALUE` terminal that spans the newline and is post-processed in the transformer to strip the `+`/newline/leading-blanks in the middle and concatenate the two sides. Pick whichever approach the Task 1 implementer finds cleanest in Lark's terminal-priority system; the requirement is behavioral (two-record value reassembles correctly with zero inserted characters), not architectural.
3. **Semicolon terminator**: `;` ends the current command; everything from `;` to end-of-physical-line is a comment (ignorable), matching `%ignore /;[^\r\n]*/`. Critically, per the manual's own worked example, a `-`-continuation on a *later* line is unaffected by an earlier semicolon-terminated command — semicolon scoping is per-line, not per-parse.
4. **`/* ... */` comments**: ignorable anywhere between tokens, `%ignore /\/\*[^*]*\*+(?:[^\/*][^*]*\*+)*\//` (standard non-nesting C-style comment regex) or Lark's equivalent construct.

## Nested Test Fixtures for the Above

Every one of the four lexical behaviors above needs its own dedicated test independent of any specific command — e.g. parse a synthetic two-record `DEFINE`-shaped value using `+`-continuation and assert the reassembled value has no inserted whitespace; parse a semicolon-terminated command followed by a `-`-continued one and assert both commands are recovered correctly; parse a command with an inline `/* comment */` between keyword and value and assert it round-trips to the same AST as without the comment.

---

## Per-Command Dataclasses

Field lists below are drawn directly from the manual (verified via full-chapter reads of `docs/idcams-ref.pdf`, this session). Each becomes a Lark grammar rule producing exactly this dataclass shape — `Optional[...]` fields are grammar-optional; non-`Optional` fields are grammar-required. Mutually-exclusive parameter groups (e.g. `CYLINDERS|KILOBYTES|MEGABYTES|RECORDS|TRACKS`) become a nested union dataclass or enum, never a flat "pick one of these strings" field, so invalid combinations are unrepresentable in the AST.

### `DefineCluster` (`jackal/jackal/idcams/ast_define_cluster.py`)

```python
@dataclass(frozen=True)
class SpaceAllocation:
    unit: Literal["CYLINDERS", "KILOBYTES", "MEGABYTES", "RECORDS", "TRACKS"]
    primary: int
    secondary: int | None = None

@dataclass(frozen=True)
class DataComponent:
    name: Name | None = None
    space: SpaceAllocation | None = None
    volumes: tuple[str, ...] = ()
    buffer_space: int | None = None
    control_interval_size: int | None = None
    erase: bool | None = None            # ERASE | NOERASE
    exception_exit: str | None = None
    file: str | None = None
    freespace: tuple[int, int] | None = None
    keys: tuple[int, int] | None = None  # length, offset
    model: tuple[Name, Name | None] | None = None
    owner: str | None = None
    record_size: tuple[int, int] | None = None  # average, maximum
    reuse: bool | None = None
    share_options: tuple[int, int | None] | None = None
    spanned: bool | None = None          # SPANNED | NONSPANNED
    speed: bool | None = None            # SPEED (True) | RECOVERY (False)
    write_check: bool | None = None

@dataclass(frozen=True)
class IndexComponent:
    name: Name | None = None
    space: SpaceAllocation | None = None
    volumes: tuple[str, ...] = ()
    control_interval_size: int | None = None
    exception_exit: str | None = None
    file: str | None = None
    model: tuple[Name, Name | None] | None = None
    owner: str | None = None
    reuse: bool | None = None
    share_options: tuple[int, int | None] | None = None
    write_check: bool | None = None

@dataclass(frozen=True)
class DefineCluster:
    name: Name
    space: SpaceAllocation | None = None       # required unless MODEL or SMS-managed
    volumes: tuple[str, ...] = ()               # required unless MODEL or SMS-managed
    account: str | None = None
    buffer_space: int | None = None
    bwo: Literal["TYPECICS", "TYPEIMS", "NO"] | None = None
    catalog: str | None = None
    control_interval_size: int | None = None
    database: "DatabaseSpec | None" = None       # DATABASE(BSON|JSON) KEYNAME|KEYNAMEU(...)
    data_class: str | None = None
    eattr: Literal["NO", "OPT"] | None = None
    erase: bool | None = None
    exception_exit: str | None = None
    file: str | None = None
    freespace: tuple[int, int] | None = None
    frlog: Literal["ALL", "NONE", "REDO", "UNDO"] | None = None
    organization: Literal["INDEXED", "LINEAR", "NONINDEXED", "NUMBERED", "ZFS"] = "INDEXED"
    key_label: str | None = None
    keys: tuple[int, int] | None = None
    log: Literal["NONE", "UNDO", "ALL"] | None = None
    log_replicate: bool | None = None
    log_stream_id: str | None = None
    management_class: str | None = None
    model: tuple[Name, Name | None] | None = None
    owner: str | None = None
    recatalog: bool | None = None
    record_size: tuple[int, int] | None = None
    reuse: bool | None = None
    rls_mode: Literal["QUIESCE", "ENABLE"] | None = None
    share_options: tuple[int, int | None] | None = None
    spanned: bool | None = None
    speed: bool | None = None
    storage_class: str | None = None
    retention: "Retention | None" = None          # TO(date) | FOR(days)
    write_check: bool | None = None
    data: DataComponent | None = None
    index: IndexComponent | None = None

@dataclass(frozen=True)
class DatabaseSpec:
    format: Literal["BSON", "JSON"]
    key_name: str
    key_name_is_utf8: bool  # KEYNAME (False) vs KEYNAMEU (True)

@dataclass(frozen=True)
class Retention:
    to_date: str | None = None   # yyyyddd form, mutually exclusive with for_days
    for_days: int | None = None
```

*(`Retention` is reused verbatim by `DefineAlternateIndex`, `DefineNonvsam`, `DefinePath`, `Alter` — every command with `TO(date)|FOR(days)` semantics.)*

### `DefineAlternateIndex`

```python
@dataclass(frozen=True)
class DefineAlternateIndex:
    name: Name
    relate: Name
    space: SpaceAllocation | None = None
    volumes: tuple[str, ...] = ()
    buffer_space: int | None = None
    catalog: str | None = None
    control_interval_size: int | None = None
    data_class: str | None = None
    erase: bool | None = None
    exception_exit: str | None = None
    file: str | None = None
    freespace: tuple[int, int] | None = None
    imbed: bool | None = None            # accepted, ignored (obsolete per manual)
    key_ranges_ignored: bool = False     # KEYRANGES: accepted, ignored (obsolete)
    keys: tuple[int, int] | None = None
    alt_keys: tuple[tuple[str, Literal["A", "D"]], ...] | None = None    # ALTKEYS
    alt_keys_utf8: tuple[tuple[str, Literal["A", "D"]], ...] | None = None  # ALTKEYSU
    model: tuple[Name, Name | None] | None = None
    order_ignored: bool = False          # ORDERED|UNORDERED: accepted, ignored (obsolete)
    owner: str | None = None
    recatalog: bool | None = None
    record_size: tuple[int, int] | None = None
    replicate_ignored: bool = False      # REPLICATE|NOREPLICATE: accepted, ignored (obsolete)
    reuse: bool | None = None
    share_options: tuple[int, int | None] | None = None
    speed: bool | None = None
    retention: Retention | None = None
    unique_key: bool | None = None       # UNIQUEKEY | NONUNIQUEKEY
    upgrade: bool | None = None          # UPGRADE | NOUPGRADE
    write_check: bool | None = None
    data: "AixDataComponent | None" = None
    index: "AixIndexComponent | None" = None

@dataclass(frozen=True)
class AixDataComponent:
    # Same shape as DataComponent minus SPANNED/NONSPANNED (not valid for AIX per manual)
    name: Name | None = None
    space: SpaceAllocation | None = None
    volumes: tuple[str, ...] = ()
    attempts: int | None = None
    authorization: tuple[str, str | None] | None = None
    buffer_space: int | None = None
    code: str | None = None
    control_interval_size: int | None = None
    erase: bool | None = None
    exception_exit: str | None = None
    file: str | None = None
    freespace: tuple[int, int] | None = None
    keys: tuple[int, int] | None = None
    model: tuple[Name, Name | None] | None = None
    owner: str | None = None
    record_size: tuple[int, int] | None = None
    reuse: bool | None = None
    share_options: tuple[int, int | None] | None = None
    speed: bool | None = None
    unique_key: bool | None = None
    write_check: bool | None = None

@dataclass(frozen=True)
class AixIndexComponent:
    name: Name | None = None
    space: SpaceAllocation | None = None
    volumes: tuple[str, ...] = ()
    attempts: int | None = None
    authorization: tuple[str, str | None] | None = None
    code: str | None = None
    control_interval_size: int | None = None
    exception_exit: str | None = None
    file: str | None = None
    model: tuple[Name, Name | None] | None = None
    owner: str | None = None
    reuse: bool | None = None
    share_options: tuple[int, int | None] | None = None
    write_check: bool | None = None
```

### `DefineGenerationDataGroup`

```python
@dataclass(frozen=True)
class DefineGenerationDataGroup:
    name: Name
    limit: int
    catalog: str | None = None
    empty: bool | None = None       # EMPTY | NOEMPTY
    extended: bool | None = None    # EXTENDED | NOEXTENDED
    order: Literal["FIFO", "LIFO"] | None = None
    owner: str | None = None
    purge: bool | None = None       # PURGE | NOPURGE
    scratch: bool | None = None     # SCRATCH | NOSCRATCH
```

### `DefineNonvsam`

```python
@dataclass(frozen=True)
class DefineNonvsam:
    name: Name
    device_types: tuple[str, ...]
    volumes: tuple[str, ...]
    catalog: str | None = None
    collection: bool = False        # obsolete, accepted for RECATALOG compatibility only
    file_sequence_numbers: tuple[int, ...] = ()
    owner: str | None = None
    recatalog: bool | None = None
    retention: Retention | None = None
```

### `DefinePath`

```python
@dataclass(frozen=True)
class DefinePath:
    name: Name
    path_entry: Name
    catalog: str | None = None
    model: tuple[Name, Name | None] | None = None
    owner: str | None = None
    recatalog: bool | None = None
    retention: Retention | None = None
    update: bool | None = None      # UPDATE | NOUPDATE
```

### `Delete`

```python
EntryType = Literal[
    "ALIAS", "ALTERNATEINDEX", "CLUSTER", "GENERATIONDATAGROUP",
    "LIBRARYENTRY", "NONVSAM", "NVR", "PAGESPACE", "PATH", "TRUENAME",
    "USERCATALOG", "VOLUMEENTRY", "VVR",
]

@dataclass(frozen=True)
class Delete:
    entries: tuple[Name, ...]         # 1..100 entries
    entry_type: EntryType | None = None
    catalog: str | None = None
    erase: bool | None = None
    file: str | None = None
    force: bool | None = None
    mask: bool | None = None
    no_disconnect: bool = False
    purge: bool | None = None
    recovery: bool | None = None
    scratch: bool | None = None
```

### `Alter`

```python
@dataclass(frozen=True)
class NullifySpec:
    authorization: Literal["MODULE", "STRING"] | None = None
    bwo: bool = False
    code: bool = False
    exception_exit: bool = False
    log: bool = False
    log_stream_id: bool = False
    management_class: bool = False
    owner: bool = False
    retention: bool = False

@dataclass(frozen=True)
class Alter:
    entry: Name
    account: str | None = None
    add_volumes: tuple[str, ...] = ()
    buffer_space: int | None = None
    bufnd: int | None = None
    bufni: int | None = None
    bwo: Literal["TYPECICS", "TYPEIMS", "NO"] | None = None
    catalog: str | None = None
    ccsid: int | None = None
    ec_sharing: bool | None = None
    empty: bool | None = None
    erase: bool | None = None
    exception_exit: str | None = None
    extended_addressable: bool = False
    order: Literal["FIFO", "LIFO"] | None = None
    file: str | None = None
    file_data: Literal["TEXT", "BINARY"] | None = None
    freespace: tuple[int, int] | None = None
    frlog: Literal["NONE", "REDO"] | None = None
    inhibit: bool | None = None         # INHIBIT | UNINHIBIT
    keys: tuple[int, int] | None = None
    limit: int | None = None
    lock: bool | None = None            # LOCK | UNLOCK (mutually exclusive with suspend)
    log: Literal["NONE", "UNDO", "ALL", "REDO"] | None = None
    log_replicate: bool | None = None
    log_stream_id: str | None = None
    management_class: str | None = None
    new_name: Name | None = None
    nullify: NullifySpec | None = None
    owner: str | None = None
    purge: bool | None = None
    reclaim_ca: bool | None = None
    record_size: tuple[int, int] | None = None
    remove_volumes: tuple[str, ...] = ()
    reuse: bool | None = None
    rls_mode: Literal["QUIESCE", "ENABLE"] | None = None
    roll_in: bool = False
    scratch: bool | None = None
    share_options: tuple[int, int | None] | None = None
    storage_class: str | None = None
    strno: int | None = None
    suspend: bool | None = None         # SUSPEND | RESUME
    retention: Retention | None = None
    to_linear: bool = False             # TYPE(LINEAR)
    unique_key: bool | None = None
    update: bool | None = None
    upgrade: bool | None = None
    write_check: bool | None = None
```

### `Repro`

```python
@dataclass(frozen=True)
class CipherSpec:
    key_source: Literal["EXTERNALKEYNAME", "INTERNALKEYNAME", "PRIVATEKEY"]
    key_name: str | None = None          # present unless PRIVATEKEY
    cipher_unit: int = 1
    data_key_file: str | None = None
    data_key_value: str | None = None
    ship_key_names: tuple[str, ...] = ()
    store_data_key: bool | None = None
    store_key_name: str | None = None
    user_data: str | None = None

@dataclass(frozen=True)
class DecipherSpec:
    key_source: Literal["DATAKEYFILE", "DATAKEYVALUE", "SYSTEMKEY"]
    data_key_file: str | None = None
    data_key_value: str | None = None
    system_data_key: str | None = None
    system_key_name: str | None = None

@dataclass(frozen=True)
class RangeStart:
    kind: Literal["FROMKEY", "FROMADDRESS", "FROMNUMBER", "SKIP"]
    value: Value

@dataclass(frozen=True)
class RangeEnd:
    kind: Literal["TOKEY", "TOADDRESS", "TONUMBER", "COUNT"]
    value: Value

@dataclass(frozen=True)
class Repro:
    infile: str | None = None            # mutually exclusive with indataset
    indataset: Name | None = None
    outfile: str | None = None           # mutually exclusive with outdataset
    outdataset: Name | None = None
    cimode: bool | None = None
    dbcs: bool = False
    entries: tuple[Name, ...] = ()       # mutually exclusive with level
    level: str | None = None
    error_limit: int | None = None
    file: str | None = None
    range_start: RangeStart | None = None
    range_end: RangeEnd | None = None
    insert_shift: tuple[tuple[int, int], ...] = ()
    insert_all: bool = False
    merge_cat: bool | None = None
    message_level: Literal["ALL", "SHORT"] | None = None
    replace: bool | None = None
    reuse: bool | None = None
    skip_dbcs_check: tuple[tuple[int, int], ...] = ()
    no_dbcs_check: bool = False
    volume_entries: str | None = None
    encipher: CipherSpec | None = None
    decipher: DecipherSpec | None = None
    rls_source: Literal["NO", "YES", "QUIESCE"] | None = None
    rls_target: Literal["NO", "YES", "QUIESCE"] | None = None
```

### `Print`

```python
@dataclass(frozen=True)
class Print:
    infile: str | None = None
    indataset: Name | None = None
    format: Literal["CHARACTER", "DUMP", "HEX"] | None = None   # default DUMP
    cimode: bool | None = None
    dbcs: bool = False
    range_start: RangeStart | None = None
    range_end: RangeEnd | None = None
    insert_shift: tuple[tuple[int, int], ...] = ()
    insert_all: bool = False
    skip_dbcs_check: tuple[tuple[int, int], ...] = ()
    no_dbcs_check: bool = False
    outfile: str | None = None
    rls_source: Literal["NO", "YES", "QUIESCE"] | None = None
```

### `Listcat`

```python
@dataclass(frozen=True)
class Listcat:
    entry_types: tuple[Literal[
        "ALIAS", "ALTERNATEINDEX", "CLUSTER", "DATA",
        "GENERATIONDATAGROUP", "INDEX", "NONVSAM", "PAGESPACE",
        "PATH", "USERCATALOG",
    ], ...] = ()
    library_entries: str | None = None
    volume_entries: str | None = None
    catalog: str | None = None
    creation_days: int | None = None
    expiration_days: int | None = None
    entries: tuple[Name, ...] = ()       # mutually exclusive with level
    level: str | None = None
    cdilvl: bool | None = None
    prefix: bool | None = None
    detail: Literal["NAME", "HISTORY", "VOLUME", "ALLOCATION", "ALL"] = "NAME"
    file: str | None = None
    library: str | None = None
    outfile: str | None = None
```

### `Export`

```python
@dataclass(frozen=True)
class Export:
    entry: Name
    outfile: str | None = None           # mutually exclusive with outdataset
    outdataset: Name | None = None
    mode: Literal["CIMODE", "RECORDMODE"] | None = None
    erase: bool | None = None
    infile: str | None = None
    inhibit_source: bool | None = None
    inhibit_target: bool | None = None
    purge: bool | None = None
    temporary: bool | None = None        # TEMPORARY | PERMANENT
    rls_source: Literal["NO", "YES", "QUIESCE"] | None = None
```

### `Import`

```python
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
    infile: str | None = None
    indataset: Name | None = None
    outfile: str | None = None
    outdataset: Name | None = None
    alias: bool | None = None
    erase: bool | None = None
    into_empty: bool = False
    lock: bool | None = None
    objects: tuple[ImportObject, ...] = ()
    purge: bool | None = None
    save_racf: bool | None = None        # SAVRAC | NOSAVRAC
    catalog: str | None = None
    rls_target: Literal["NO", "YES", "QUIESCE"] | None = None
```

### `Verify`

```python
@dataclass(frozen=True)
class Verify:
    file: str | None = None              # mutually exclusive with dataset
    dataset: Name | None = None
    recover: bool = False
```

### `Bldindex`

```python
@dataclass(frozen=True)
class Bldindex:
    infile: str | None = None            # mutually exclusive with indataset
    indataset: Name | None = None
    outfiles: tuple[str, ...] = ()       # mutually exclusive with outdatasets
    outdatasets: tuple[Name, ...] = ()
    sort_kind: Literal["EXTERNALSORT", "INTERNALSORT"] | None = None
    sort_call: bool | None = None        # SORTCALL | NOSORTCALL, default True
    sort_device_type: str | None = None
    sort_file_number: int | None = None
    sort_message_dd: str | None = None
    sort_message_level: Literal["ALL", "CRITICAL", "NONE"] | None = None
    work_files: tuple[str, ...] = ()
    catalog: str | None = None
```

---

## Modal Commands

```python
# jackal/jackal/idcams/ast_modal.py

AmsCommand = Union[
    DefineCluster, DefineAlternateIndex, DefineGenerationDataGroup,
    DefineNonvsam, DefinePath, Delete, Alter, Repro, Print, Listcat,
    Export, Import, Verify, Bldindex, "SetCommand", "CancelCommand",
]

@dataclass(frozen=True)
class SetCommand:
    field: Literal["MAXCC", "LASTCC"]
    value: int

@dataclass(frozen=True)
class CancelCommand:
    pass

@dataclass(frozen=True)
class IfCommand:
    field: Literal["MAXCC", "LASTCC"]
    op: Literal["EQ", "NE", "GT", "LT", "GE", "LE"]   # bare "=" normalizes to EQ
    value: int
    then: tuple["AmsCommand | IfCommand", ...] = ()    # empty = null THEN
    else_: "tuple[AmsCommand | IfCommand, ...] | None" = None  # None = no ELSE; () = null ELSE
```

Note: replaces this session's `IfMaxcc`/`SetMaxcc` (in the *new* comprehensive module) with a version that supports full nesting/`DO`-`END` blocks — but again, does not modify or remove the existing `jackal/jackal/idcams/commands.py::IfMaxcc`/`SetMaxcc`, which stay wired to the real executor unchanged.

`PARM` is syntactically simple (`TEST(...)`/`GRAPHICS(...)`/`MARGINS(...)`) but is a pure diagnostic aid with zero real-corpus usage — model it if the Task N implementer finds it genuinely free to add alongside the modal-command grammar work; do not spend a dedicated task budget on it if it turns out non-trivial. This is the one place in this spec where "comprehensive" yields to "not worth a dedicated task" — flag it to the user if it needs its own task rather than silently dropping it.

---

## Grammar File Organization

One `.lark` grammar file per command family, imported into a top-level `ams.lark` via Lark's `%import`, mirroring how a large real grammar is usually decomposed:

```
jackal/jackal/idcams/grammar/
  ams.lark              # top-level: command alternation, common terminals (NAME, INT, quoted string, hex/bin literals, continuation/comment ignores)
  define_cluster.lark
  define_alternateindex.lark
  define_gdg.lark
  define_nonvsam.lark
  define_path.lark
  delete.lark
  alter.lark
  repro.lark
  print.lark
  listcat.lark
  export.lark
  import.lark
  verify.lark
  bldindex.lark
  modal.lark             # IF/THEN/ELSE/DO/END, SET, CANCEL, PARM
```

This is a strong recommendation, not a hard requirement — if the Task 1 (infrastructure) implementer finds Lark's `%import` mechanics awkward for this many files, a single `ams.lark` with clearly delimited `// ==== DEFINE CLUSTER ====` sections is an acceptable fallback, as long as each command's rules stay textually grouped and independently readable.

---

## Testing Strategy

1. **Per-command synthetic tests** covering every parameter documented above — not just a happy-path example, but the documented mutual-exclusivity groups (assert the grammar rejects e.g. both `CYLINDERS` and `TRACKS` on the same `DEFINE CLUSTER`), the documented defaults (assert an omitted `SHAREOPTIONS` round-trips as `None`, not a guessed default value — defaults are an *execution* concern, not a parse concern, so the AST should carry `None` and let a future executor apply IBM's default), and the DATA/INDEX component validity differences (assert `SPANNED` is accepted inside `DATA(...)` but rejected inside `INDEX(...)`).
2. **Real-corpus tests**: every one of the 21 real CardDemo `SYSIN` blocks (`jackal/third-party/carddemo/app/jcl/*.jcl` IDCAMS steps) must parse successfully through this new grammar — this is the primary "are we actually comprehensive" signal, more valuable than any synthetic coverage number. Include the `RECORDSIZE(80,80)`-style comma-separated params real files use (this grammar subsumes `forge-2zs`'s fix as a side effect of being comprehensive — confirm and close that bead when this lands).
3. **Lexical-rule tests** (continuation, terminator, comments, quoting, hex/binary, generic names) as their own dedicated test file, independent of any specific command, per the "Nested Test Fixtures" section above.
4. **Nested `IF` tests**: at least one test exercising real nesting (the manual's own two worked examples — nested nested `IF`/`THEN`/`ELSE` nested inside another `THEN`) parsed verbatim, plus a test confirming an 11-level-deep `IF` is rejected (depth cap enforcement).
5. **"Iterate until complete" stopping condition**: this mission is done when (a) every command listed under "In-Scope Commands" has a dataclass, a grammar rule, and passing tests for every parameter in its section above, and (b) all 21 real CardDemo IDCAMS `SYSIN` blocks parse without error. Track this as a literal checklist in the implementation plan, not a vibe.

---

## Non-Goals (Restated)

- No execution semantics. This spec produces an AST; nothing in `executor.py` changes.
- No storage-admin/tape-library/diagnostic commands (`ALLOCATE`, `*LIBRARYENTRY`, `*VOLUMEENTRY`, `DCOLLECT`, `DIAGNOSE`, `EXAMINE`, `SETCACHE`, `SHCDS`, `LISTDATA`).
- No `DEFINE ALIAS`, `DEFINE USERCATALOG`, `DEFINE PAGESPACE`, `EXPORT DISCONNECT`, `IMPORT CONNECT`.
- No keyword abbreviation support.
- No `ALTER STAGE` (definition not recoverable from the read excerpt — flagged as a follow-up, not guessed at).
