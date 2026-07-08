# Comprehensive IDCAMS Grammar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a comprehensive, typed-AST Lark grammar for IDCAMS covering `DEFINE CLUSTER`/`ALTERNATEINDEX`/`GENERATIONDATAGROUP`/`NONVSAM`/`PATH`, `DELETE`, `ALTER`, `REPRO`, `PRINT`, `LISTCAT`, `EXPORT`, `IMPORT`, `VERIFY`, `BLDINDEX`, and modal `IF`/`THEN`/`ELSE`/`DO`/`END`/`SET`/`CANCEL` — parsing only, no execution semantics.

**Architecture:** One frozen dataclass and one Lark grammar rule per command, every field named after its real IBM parameter. Full spec: `jackal/docs/superpowers/specs/2026-07-08-idcams-comprehensive-grammar-design.md` — every task below references it for exact field lists; read the relevant section before implementing.

**Tech Stack:** Lark (`earley` parser), Python frozen dataclasses, pytest.

## Global Constraints

- No generic `Command(verb, params)` catch-all anywhere — every dataclass field is named after its real IBM parameter.
- `-` continuation and `+` continuation are behaviorally distinct: `-` is whitespace-equivalent; `+` force-joins a value across the line break with zero inserted characters.
- Semicolon terminator ends a command; everything after it on that physical line is a comment. Does not affect continuation behavior on other lines.
- `/* ... */` comments are ignorable anywhere between tokens.
- Quoted strings support embedded commas/semicolons/blanks/parens/slashes; `''` de-escapes to a literal `'`.
- Hex (`X'...'`) and binary (`B'...'`) literals are valid wherever a plain value is valid.
- Generic names: `*` replaces exactly one qualifier, never the leftmost, never more than once (`A.*`, `A.*.C` valid; `A.*.*`, `A.B*`, `*.B.C` invalid — must raise a parse error, not silently accept).
- A parenthesized list drops its parens when it has exactly one item; applies recursively to nested groups.
- Keyword abbreviations are out of scope — grammar rules use full keyword spellings only.
- None of this touches `jackal/jackal/idcams/commands.py`/`executor.py`/`parser.py` (the existing, execution-wired minimal grammar) — new files only, alongside the old ones.
- Every task's tests run via `JCL_BRIDGE_JAR=... uv run --no-sync python -m pytest jackal/tests/unit/test_idcams_<name>.py -v` from the repo root; no bridge JAR is needed for pure IDCAMS-grammar tests (IDCAMS parsing has no Java dependency — the JCL_BRIDGE_JAR requirement is JCL-level only, unaffected by this plan).
- `AmsCommand`/`Value` type aliases and all shared dataclasses live in `jackal/jackal/idcams/ast_values.py` (Task 1) — every later task imports from there, never redefines.

---

### Task 1: Value types, lexical infrastructure, shared shapes

**Files:**
- Create: `jackal/jackal/idcams/ast_values.py`
- Create: `jackal/jackal/idcams/grammar/ams.lark`
- Create: `jackal/jackal/idcams/preprocess.py`
- Test: `jackal/tests/unit/test_idcams_ast_values.py`
- Test: `jackal/tests/unit/test_idcams_preprocess.py`
- Test: `jackal/tests/unit/test_idcams_grammar_lexical.py`

**Interfaces:**
- Produces: `Name`, `QuotedString`, `HexLiteral`, `BinLiteral`, `Value` (union incl. `int`), `SpaceAllocation`, `Retention` dataclasses — every later task imports these.
- Produces: `join_plus_continuations(text: str) -> str` — preprocessing pass, called before Lark parses any IDCAMS text.
- Produces: `jackal/jackal/idcams/grammar/ams.lark`'s terminal definitions (`NAME`, `QUOTED_STRING`, `HEX_LITERAL`, `BIN_LITERAL`, `INT`) and `%ignore` rules — every later task's own `.lark` file assumes these terminals exist (via `%import ams.terminal_name` or by being textually appended into the same file — implementer's choice per the design spec's file-organization note).

- [ ] **Step 1: Write the failing tests for value dataclasses and generic-name validation**

```python
# jackal/tests/unit/test_idcams_ast_values.py
"""Tests for IDCAMS AST value types."""

from __future__ import annotations

import pytest

from jackal.idcams.ast_values import Name, Retention, SpaceAllocation
from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_plain_name_is_not_generic():
    n = Name(text="A.B.C")
    assert n.generic is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_valid_generic_name_single_trailing_wildcard():
    n = Name.parse("A.*")
    assert n.text == "A.*"
    assert n.generic is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_valid_generic_name_wildcard_mid_qualifier_list():
    n = Name.parse("A.*.C")
    assert n.generic is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_generic_name_rejects_leading_wildcard():
    with pytest.raises(ValueError):
        Name.parse("*.B.C")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_generic_name_rejects_multiple_wildcards():
    with pytest.raises(ValueError):
        Name.parse("A.*.*")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_generic_name_rejects_partial_qualifier_wildcard():
    with pytest.raises(ValueError):
        Name.parse("A.B*")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_space_allocation_holds_unit_primary_secondary():
    s = SpaceAllocation(unit="CYLINDERS", primary=10, secondary=5)
    assert s.unit == "CYLINDERS"
    assert s.secondary == 5


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_retention_to_date_and_for_days_are_independent_fields():
    r1 = Retention(to_date="99365")
    r2 = Retention(for_days=9999)
    assert r1.for_days is None
    assert r2.to_date is None
```

```python
# jackal/tests/unit/test_idcams_preprocess.py
"""Tests for the + (mid-token) continuation preprocessing pass."""

from __future__ import annotations

from jackal.idcams.preprocess import join_plus_continuations
from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_plus_continuation_joins_with_no_inserted_characters():
    text = "NAME(AWS.M2.CARDDEMO.VERYLONGDATASETNAME+\n   .REST)\n"
    result = join_plus_continuations(text)
    assert result == "NAME(AWS.M2.CARDDEMO.VERYLONGDATASETNAME.REST)\n"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_hyphen_continuation_is_untouched_by_plus_preprocessing():
    text = "DEFINE CLUSTER (NAME(A.B) -\n  KEYS(3 0))\n"
    result = join_plus_continuations(text)
    assert result == text
```

```python
# jackal/tests/unit/test_idcams_grammar_lexical.py
"""Tests for shared lexical rules: continuation, terminator, comments, quoting, literals."""

from __future__ import annotations

from lark import Lark
from tests.covers import NotLanguageFeature, covers

_GRAMMAR_PATH = "jackal/jackal/idcams/grammar/ams.lark"


def _lex(text: str) -> list:
    parser = Lark.open(_GRAMMAR_PATH, start="value", parser="earley")
    return list(parser.parse(text).children)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_quoted_string_with_embedded_comma_and_paren():
    tree = Lark.open(_GRAMMAR_PATH, start="value", parser="earley").parse(
        "'A,(B)'\n"
    )
    assert tree.children[0].value == "'A,(B)'"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_quoted_string_embedded_doubled_quote_escapes():
    tree = Lark.open(_GRAMMAR_PATH, start="value", parser="earley").parse(
        "'IT''S'\n"
    )
    assert tree.children[0].value == "'IT''S'"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_hex_literal():
    tree = Lark.open(_GRAMMAR_PATH, start="value", parser="earley").parse(
        "X'C1C2C3'\n"
    )
    assert tree.children[0].value == "X'C1C2C3'"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_binary_literal():
    tree = Lark.open(_GRAMMAR_PATH, start="value", parser="earley").parse(
        "B'0101'\n"
    )
    assert tree.children[0].value == "B'0101'"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_semicolon_terminates_and_rest_of_line_is_comment():
    parser = Lark.open(_GROUP := _GRAMMAR_PATH, start="start", parser="earley")
    # SET MAXCC=0 followed by a semicolon-commented remainder, then a real
    # continued command on the next line -- both must parse.
    text = "SET MAXCC=0; ignored garbage $$$ !!!\nCANCEL\n"
    tree = parser.parse(text)
    assert len(tree.children) == 2


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_inline_comment_between_keyword_and_value():
    parser = Lark.open(_GRAMMAR_PATH, start="start", parser="earley")
    text = "SET /* comment */ MAXCC=0\n"
    tree = parser.parse(text)
    assert len(tree.children) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd jackal && uv run --no-sync python -m pytest tests/unit/test_idcams_ast_values.py tests/unit/test_idcams_preprocess.py tests/unit/test_idcams_grammar_lexical.py -v`
Expected: FAIL — `jackal.idcams.ast_values`, `jackal.idcams.preprocess`, and the grammar file don't exist yet.

- [ ] **Step 3: Implement `ast_values.py`**

```python
# jackal/jackal/idcams/ast_values.py
"""Shared AST value types and shapes for the comprehensive IDCAMS grammar.

Distinct from jackal.value_parts.Value (JCL's Literal/Symbol substitution
model) -- IDCAMS is a separate small language with its own value grammar
(plain names, quoted strings, hex/binary literals, integers), not JCL
symbol substitution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Union

_QUALIFIER = r"[A-Z#@$][A-Z0-9#@$]*"
_PLAIN_NAME = re.compile(rf"^{_QUALIFIER}(\.{_QUALIFIER})*$")
_GENERIC_NAME = re.compile(rf"^{_QUALIFIER}(\.{_QUALIFIER})*\.\*(\.{_QUALIFIER})?$")


@dataclass(frozen=True)
class Name:
    text: str
    generic: bool = False

    @staticmethod
    def parse(text: str) -> "Name":
        if _PLAIN_NAME.match(text):
            return Name(text=text, generic=False)
        if _GENERIC_NAME.match(text):
            return Name(text=text, generic=True)
        raise ValueError(f"Invalid entry/generic name: {text!r}")


@dataclass(frozen=True)
class QuotedString:
    text: str  # de-escaped ('' -> ')


@dataclass(frozen=True)
class HexLiteral:
    raw: str


@dataclass(frozen=True)
class BinLiteral:
    raw: str


Value = Union[Name, QuotedString, HexLiteral, BinLiteral, int]


@dataclass(frozen=True)
class SpaceAllocation:
    unit: Literal["CYLINDERS", "KILOBYTES", "MEGABYTES", "RECORDS", "TRACKS"]
    primary: int
    secondary: int | None = None


@dataclass(frozen=True)
class Retention:
    to_date: str | None = None
    for_days: int | None = None
```

- [ ] **Step 4: Implement `preprocess.py`**

```python
# jackal/jackal/idcams/preprocess.py
"""Preprocessing pass for the + (mid-token) continuation character.

IDCAMS's "+" continuation force-joins a value across a record boundary
with zero inserted characters -- this happens before the text ever
reaches the Lark parser, since it collapses two physical lines into one
logical token. "-" continuation (whitespace-equivalent) is handled
separately, at the grammar level, via %ignore.
"""

from __future__ import annotations

import re

_PLUS_CONTINUATION = re.compile(r"\+[ \t]*\r?\n[ \t]*")


def join_plus_continuations(text: str) -> str:
    return _PLUS_CONTINUATION.sub("", text)
```

- [ ] **Step 5: Implement `grammar/ams.lark` (shared terminals + lexical ignores + top-level skeleton)**

```lark
// jackal/jackal/idcams/grammar/ams.lark
// Shared terminals and lexical rules for the comprehensive IDCAMS grammar.
// Command-specific rules are added here by later tasks (Tasks 2-11), each
// contributing its own `command:` alternative and rule definitions.

start: command+

command: modal_command  // placeholder alternative until Task 2+ add real commands

?value: NAME | GENERIC_NAME | QUOTED_STRING | HEX_LITERAL | BIN_LITERAL | INT

modal_command: "CANCEL"   // minimal placeholder so start.lark is parseable
                          // standalone during Task 1; replaced/extended by
                          // Task 11's real modal_command rule.

NAME:          /[A-Z#@$][A-Z0-9#@$]*(\.[A-Z#@$][A-Z0-9#@$]*)*/
GENERIC_NAME:  /[A-Z#@$][A-Z0-9#@$]*(\.[A-Z#@$][A-Z0-9#@$]*)*\.\*(\.[A-Z#@$][A-Z0-9#@$]*)?/
QUOTED_STRING: /'([^']|'')*'/
HEX_LITERAL:   /X'[0-9A-Fa-f]+'/
BIN_LITERAL:   /B'[01]+'/
INT:           /[0-9]+/

// Whitespace, "-" continuation (whitespace-equivalent), semicolon
// terminator (rest of physical line becomes a comment), and /* */
// comments are all ignorable. "+" continuation is handled by
// preprocess.join_plus_continuations() *before* this grammar ever sees
// the text, not here.
%ignore /[ \t\r\n]+/
%ignore /-[ \t]*(?=\r?\n)/
%ignore /;[^\r\n]*/
%ignore /\/\*[^*]*\*+(?:[^\/*][^*]*\*+)*\//
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd jackal && uv run --no-sync python -m pytest tests/unit/test_idcams_ast_values.py tests/unit/test_idcams_preprocess.py tests/unit/test_idcams_grammar_lexical.py -v`
Expected: PASS (adjust the `start`/`command`/`modal_command` placeholder rules if the lexical tests need a different minimal top-level shape to parse standalone `value`/`start` trees — the important thing is the terminals and `%ignore` rules, not the placeholder command shape, which Task 11 replaces).

- [ ] **Step 7: Commit**

```bash
git add jackal/jackal/idcams/ast_values.py jackal/jackal/idcams/preprocess.py jackal/jackal/idcams/grammar/ams.lark jackal/tests/unit/test_idcams_ast_values.py jackal/tests/unit/test_idcams_preprocess.py jackal/tests/unit/test_idcams_grammar_lexical.py
git commit -m "feat(idcams): value types, +/- continuation, terminator, comment lexing for the comprehensive grammar"
```

---

### Task 2: DEFINE CLUSTER

**Files:**
- Create: `jackal/jackal/idcams/ast_define_cluster.py`
- Modify: `jackal/jackal/idcams/grammar/ams.lark` (add `define_cluster` rule + append to `command:` alternatives)
- Test: `jackal/tests/unit/test_idcams_define_cluster.py`

**Interfaces:**
- Consumes: `Name`, `SpaceAllocation`, `Retention` from `jackal.idcams.ast_values` (Task 1).
- Produces: `DefineCluster`, `DataComponent`, `IndexComponent`, `DatabaseSpec` dataclasses — exact field lists in the design spec's "`DefineCluster`" section. Transcribe every field listed there; this is the largest single command (~50 parameters across CLUSTER/DATA/INDEX levels) — do not abbreviate the field list.

- [ ] **Step 1: Write failing tests covering the required fields, one representative optional field per logical group, and the DATA/INDEX validity-boundary rule**

```python
# jackal/tests/unit/test_idcams_define_cluster.py
"""Tests for DEFINE CLUSTER parsing into the comprehensive AST.

Covers every parameter listed in the design spec's DefineCluster
section (2026-07-08-idcams-comprehensive-grammar-design.md) -- this
file shows the required pattern; extend it with one test per remaining
optional parameter (BWO, CCSID... wait CCSID belongs to ALTER;
DATACLASS, EATTR, FRLOG, KEYLABEL, LOG, LOGREPLICATE, LOGSTREAMID,
MANAGEMENTCLASS, OWNER, RECATALOG, STORAGECLASS, WRITECHECK, etc.)
following the same shape as the examples below.
"""

from __future__ import annotations

from jackal.idcams.ast_define_cluster import (
    DataComponent,
    DefineCluster,
    IndexComponent,
)
from jackal.idcams.ast_values import Name, Retention, SpaceAllocation
from jackal.idcams.parser_comprehensive import parse_ams
from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_minimal_required_fields():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B.KSDS) -\n"
        "  CYLINDERS(1 5) -\n"
        "  VOLUMES(AWSHJ1))\n"
    )
    dc = cmds[0]
    assert dc == DefineCluster(
        name=Name.parse("A.B.KSDS"),
        space=SpaceAllocation(unit="CYLINDERS", primary=1, secondary=5),
        volumes=("AWSHJ1",),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_organization_choice_defaults_to_indexed():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1))\n"
    )
    assert cmds[0].organization == "INDEXED"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_linear_organization():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) LINEAR CYLINDERS(1) VOLUMES(V1))\n"
    )
    assert cmds[0].organization == "LINEAR"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_retention_to_date():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) TO(99365))\n"
    )
    assert cmds[0].retention == Retention(to_date="99365")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_retention_for_days():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) FOR(9999))\n"
    )
    assert cmds[0].retention == Retention(for_days=9999)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_share_options_both_values():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) SHAREOPTIONS(2 3))\n"
    )
    assert cmds[0].share_options == (2, 3)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_with_data_and_index_trailers():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B.KSDS) -\n"
        "  CYLINDERS(1 5) -\n"
        "  VOLUMES(AWSHJ1) -\n"
        "  KEYS(16 0) -\n"
        "  RECORDSIZE(150 150) -\n"
        "  INDEXED) -\n"
        "  DATA (NAME(A.B.KSDS.DATA) SPANNED) -\n"
        "  INDEX (NAME(A.B.KSDS.INDEX))\n"
    )
    dc = cmds[0]
    assert dc.data == DataComponent(name=Name.parse("A.B.KSDS.DATA"), spanned=True)
    assert dc.index == IndexComponent(name=Name.parse("A.B.KSDS.INDEX"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_index_component_rejects_spanned():
    """SPANNED is a DATA-only parameter per the manual -- INDEX(...) must
    not accept it."""
    import pytest
    from lark.exceptions import LarkError

    with pytest.raises(LarkError):
        parse_ams(
            "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1)) -\n"
            "  INDEX (NAME(A.B.INDEX) SPANNED)\n"
        )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_define_cluster_database_spec():
    cmds = parse_ams(
        "DEFINE CLUSTER (NAME(A.B) CYLINDERS(1) VOLUMES(V1) -\n"
        "  DATABASE(JSON) KEYNAME(MYKEY))\n"
    )
    assert cmds[0].database.format == "JSON"
    assert cmds[0].database.key_name == "MYKEY"
    assert cmds[0].database.key_name_is_utf8 is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd jackal && uv run --no-sync python -m pytest tests/unit/test_idcams_define_cluster.py -v`
Expected: FAIL — `ast_define_cluster.py` and `parser_comprehensive.py` don't exist yet.

- [ ] **Step 3: Implement `ast_define_cluster.py`**

Transcribe the full `DataComponent`, `IndexComponent`, `DefineCluster`, `DatabaseSpec` dataclasses verbatim from the design spec's "`DefineCluster`" section (every field listed there — space allocation, volumes, account, buffer_space, bwo, catalog, control_interval_size, database, data_class, eattr, erase, exception_exit, file, freespace, frlog, organization, key_label, keys, log, log_replicate, log_stream_id, management_class, model, owner, recatalog, record_size, reuse, rls_mode, share_options, spanned, speed, storage_class, retention, write_check, data, index — do not drop any).

- [ ] **Step 4: Implement `define_cluster` grammar rule, appended to `ams.lark`**

Write the Lark rule so that: (a) `CYLINDERS|KILOBYTES|MEGABYTES|RECORDS|TRACKS` is a genuine mutually-exclusive alternation (not five independent optional rules that could all match at once), (b) `INDEXED|LINEAR|NONINDEXED|NUMBERED|ZFS` is likewise mutually exclusive with `INDEXED` as the transformer-applied default when absent, (c) the `DATA(...)` and `INDEX(...)` trailers are **separate rules** with **different parameter alternatives** (INDEX's rule must not include `SPANNED`/`NONSPANNED`, `ERASE`/`NOERASE`, `BUFFERSPACE`, `FREESPACE`, `KEYS`, `RECORDSIZE`, `SPEED`/`RECOVERY` — the design spec's `IndexComponent` field list is authoritative for what's absent), (d) the transformer builds `DefineCluster`/`DataComponent`/`IndexComponent`/`DatabaseSpec` instances matching Step 3's dataclasses exactly.

Create `jackal/jackal/idcams/parser_comprehensive.py` with a `parse_ams(text: str) -> tuple[AmsCommand, ...]` entry point (mirrors `jackal/jackal/idcams/parser.py`'s `parse_idcams` shape: apply `join_plus_continuations` first, then `Lark.open("grammar/ams.lark", start="start", parser="earley").parse(...)`, then a `Transformer` producing the typed dataclasses).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd jackal && uv run --no-sync python -m pytest tests/unit/test_idcams_define_cluster.py -v`
Expected: PASS.

- [ ] **Step 6: Extend test coverage to every remaining `DefineCluster`/`DataComponent`/`IndexComponent` parameter**

Following the pattern shown in Step 1, add one test per remaining optional parameter listed in the design spec (at minimum: `ACCOUNT`, `BUFFERSPACE`, `BWO`, `CATALOG`, `CONTROLINTERVALSIZE`, `DATACLASS`, `EATTR`, `ERASE`/`NOERASE`, `EXCEPTIONEXIT`, `FILE`, `FREESPACE`, `FRLOG`, `KEYLABEL`, `KEYS`, `LOG`, `LOGREPLICATE`/`NOLOGREPLICATE`, `LOGSTREAMID`, `MANAGEMENTCLASS`, `MODEL`, `OWNER`, `RECATALOG`/`NORECATALOG`, `RECORDSIZE`, `REUSE`/`NOREUSE`, `RLSQUIESCE`/`RLSENABLE`, `SPEED`/`RECOVERY`, `STORAGECLASS`, `WRITECHECK`/`NOWRITECHECK`, and the `IMBED`/`KEYRANGES`/`ORDERED`/`REPLICATE` obsolete-but-must-parse-and-be-ignored parameters the manual explicitly calls out).

- [ ] **Step 7: Run full test file, verify all pass**

Run: `cd jackal && uv run --no-sync python -m pytest tests/unit/test_idcams_define_cluster.py -v`
Expected: PASS, all parameters covered.

- [ ] **Step 8: Commit**

```bash
git add jackal/jackal/idcams/ast_define_cluster.py jackal/jackal/idcams/parser_comprehensive.py jackal/jackal/idcams/grammar/ams.lark jackal/tests/unit/test_idcams_define_cluster.py
git commit -m "feat(idcams): comprehensive DEFINE CLUSTER grammar and typed AST"
```

---

### Task 3: DEFINE ALTERNATEINDEX

**Files:**
- Create: `jackal/jackal/idcams/ast_define_alternateindex.py`
- Modify: `jackal/jackal/idcams/grammar/ams.lark`
- Test: `jackal/tests/unit/test_idcams_define_alternateindex.py`

**Interfaces:**
- Consumes: `Name`, `SpaceAllocation`, `Retention` from Task 1.
- Produces: `DefineAlternateIndex`, `AixDataComponent`, `AixIndexComponent` — exact field lists in the design spec's "`DefineAlternateIndex`" section.

- [ ] **Step 1: Write failing tests** for: required `NAME`+`RELATE`, the four now-ignored-but-must-parse obsolete parameters (`IMBED`, `KEYRANGES`, `ORDERED`/`UNORDERED`, `REPLICATE`/`NOREPLICATE`), `ALTKEYS`/`ALTKEYSU` (mutually exclusive, each a list of `(keyname, A|D)` pairs), `UNIQUEKEY`/`NONUNIQUEKEY`, `UPGRADE`/`NOUPGRADE`, and one `AixDataComponent`/`AixIndexComponent` test confirming `AixDataComponent` accepts `UNIQUEKEY` but `AixIndexComponent` does not (per the spec's noted DATA/INDEX asymmetry, mirroring Task 2's Step 1's validity-boundary pattern).

- [ ] **Step 2: Run tests to verify they fail.**

Run: `cd jackal && uv run --no-sync python -m pytest tests/unit/test_idcams_define_alternateindex.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `ast_define_alternateindex.py`** — transcribe the full field list from the design spec's "`DefineAlternateIndex`" section verbatim (including `AixDataComponent`/`AixIndexComponent`).

- [ ] **Step 4: Implement `define_alternateindex` grammar rule**, appended to `ams.lark`, following Task 2's established pattern for mutual exclusivity and DATA/INDEX validity differences.

- [ ] **Step 5: Run tests to verify they pass.**

Run: `cd jackal && uv run --no-sync python -m pytest tests/unit/test_idcams_define_alternateindex.py -v`
Expected: PASS.

- [ ] **Step 6: Extend test coverage to every remaining parameter** in the design spec's `DefineAlternateIndex` section (`BUFFERSPACE`, `CATALOG`, `CONTROLINTERVALSIZE`, `DATACLASS`, `ERASE`/`NOERASE`, `EXCEPTIONEXIT`, `FILE`, `FREESPACE`, `KEYS`, `MODEL`, `OWNER`, `RECATALOG`/`NORECATALOG`, `RECORDSIZE`, `REUSE`/`NOREUSE`, `SHAREOPTIONS`, `SPEED`/`RECOVERY`, `TO`/`FOR`, `WRITECHECK`/`NOWRITECHECK`).

- [ ] **Step 7: Run full test file, verify all pass.**

- [ ] **Step 8: Commit**

```bash
git add jackal/jackal/idcams/ast_define_alternateindex.py jackal/jackal/idcams/grammar/ams.lark jackal/tests/unit/test_idcams_define_alternateindex.py
git commit -m "feat(idcams): comprehensive DEFINE ALTERNATEINDEX grammar and typed AST"
```

---

### Task 4: DEFINE GENERATIONDATAGROUP, DEFINE NONVSAM, DEFINE PATH

**Files:**
- Create: `jackal/jackal/idcams/ast_define_gdg.py`
- Create: `jackal/jackal/idcams/ast_define_nonvsam.py`
- Create: `jackal/jackal/idcams/ast_define_path.py`
- Modify: `jackal/jackal/idcams/grammar/ams.lark`
- Test: `jackal/tests/unit/test_idcams_define_gdg_nonvsam_path.py`

**Interfaces:**
- Consumes: `Name`, `Retention` from Task 1.
- Produces: `DefineGenerationDataGroup`, `DefineNonvsam`, `DefinePath` — exact field lists in the design spec's respective sections. These three are grouped into one task because each is small (≤10 fields) relative to Tasks 2-3.

- [ ] **Step 1: Write failing tests** — at minimum: `DEFINE GENERATIONDATAGROUP` with `NAME`+`LIMIT` required and `EMPTY`/`NOEMPTY`, `EXTENDED`/`NOEXTENDED`, `FIFO`/`LIFO`, `PURGE`/`NOPURGE`, `SCRATCH`/`NOSCRATCH` covered; `DEFINE NONVSAM` with `NAME`+`DEVICETYPES`+`VOLUMES` required, including the special `DEVICETYPES(0000)` and `VOLUMES(******)`/`VOLUMES(&SYSR2)` indirect forms explicitly tested; `DEFINE PATH` with `NAME`+`PATHENTRY` required and `UPDATE`/`NOUPDATE` covered (this is a real CardDemo-relevant case — `TRANREPT.jcl` uses `JCLLIB`, not `DEFINE PATH`, but the alternate-index toolchain work referenced in `jackal-1o2.6` will need `DEFINE PATH` next).

- [ ] **Step 2: Run tests to verify they fail.**

- [ ] **Step 3: Implement all three `ast_define_*.py` files** — transcribe field lists verbatim from the design spec.

- [ ] **Step 4: Implement all three grammar rules**, appended to `ams.lark`.

- [ ] **Step 5: Run tests to verify they pass.**

- [ ] **Step 6: Extend test coverage to every remaining parameter** in each of the three design-spec sections.

- [ ] **Step 7: Run full test file, verify all pass.**

- [ ] **Step 8: Commit**

```bash
git add jackal/jackal/idcams/ast_define_gdg.py jackal/jackal/idcams/ast_define_nonvsam.py jackal/jackal/idcams/ast_define_path.py jackal/jackal/idcams/grammar/ams.lark jackal/tests/unit/test_idcams_define_gdg_nonvsam_path.py
git commit -m "feat(idcams): comprehensive DEFINE GENERATIONDATAGROUP/NONVSAM/PATH grammar and typed AST"
```

---

### Task 5: DELETE

**Files:**
- Create: `jackal/jackal/idcams/ast_delete.py`
- Modify: `jackal/jackal/idcams/grammar/ams.lark`
- Test: `jackal/tests/unit/test_idcams_delete_comprehensive.py`

**Interfaces:**
- Consumes: `Name` from Task 1.
- Produces: `Delete`, `EntryType` — exact field list and the 13-member `EntryType` literal in the design spec's "`Delete`" section. This is a new, separate module from the existing `jackal/jackal/idcams/commands.py::Delete` (execution-wired, untouched) — name collision is fine since they live in different modules; do not import one from the other.

- [ ] **Step 1: Write failing tests** covering: multi-entry positional list (`DELETE (A B C)`), single-entry elision (`DELETE A`), each of the 13 `EntryType` values, `MASK` with a real filter-key pattern (`**`, `%`), `FORCE`/`NOFORCE`, `PURGE`/`NOPURGE`, `RECOVERY`/`NORECOVERY`, `SCRATCH`/`NOSCRATCH`, `NODISCONNECT`, and the real corpus's bare `DELETE dsname` (no type keyword — this is a *new*, separate grammar from `forge-c53`/this session's earlier minimal-grammar fix; this task's grammar must independently support the bare form too, per its own dataclass's `entry_type: EntryType | None = None`).

- [ ] **Step 2: Run tests to verify they fail.**

- [ ] **Step 3: Implement `ast_delete.py`.**

- [ ] **Step 4: Implement `delete` grammar rule**, appended to `ams.lark`. Max 100 entries in the positional list is a semantic constraint, not necessarily a grammar one — check via the transformer, raising `ValueError` if exceeded (do not silently truncate).

- [ ] **Step 5: Run tests to verify they pass.**

- [ ] **Step 6: Extend test coverage to every remaining parameter** (`CATALOG`, `ERASE`/`NOERASE`, `FILE`).

- [ ] **Step 7: Run full test file, verify all pass.**

- [ ] **Step 8: Commit**

```bash
git add jackal/jackal/idcams/ast_delete.py jackal/jackal/idcams/grammar/ams.lark jackal/tests/unit/test_idcams_delete_comprehensive.py
git commit -m "feat(idcams): comprehensive DELETE grammar and typed AST"
```

---

### Task 6: ALTER

**Files:**
- Create: `jackal/jackal/idcams/ast_alter.py`
- Modify: `jackal/jackal/idcams/grammar/ams.lark`
- Test: `jackal/tests/unit/test_idcams_alter.py`

**Interfaces:**
- Consumes: `Name`, `Retention` from Task 1.
- Produces: `Alter`, `NullifySpec` — exact field list (~45 optional fields) in the design spec's "`Alter`" section. **Does not include a `stage` field** — the design spec explicitly defers `STAGE` (definition not recoverable from the manual excerpt read for the spec); if this task's implementer independently finds `STAGE`'s definition while reading the `ALTER` chapter directly, add it and note the addition in the task report, but do not block the task on it.

- [ ] **Step 1: Write failing tests** covering: required positional `entry`, `NEWNAME` (rename), `ADDVOLUMES`/`REMOVEVOLUMES`, `LOG`/`LOGSTREAMID`/`LOGREPLICATE` interaction (all three independently settable), the full `NULLIFY(...)` sub-block with at least 3 of its 9 sub-options, `LOCK`/`UNLOCK` vs `SUSPEND`/`RESUME` (both mutually-exclusive-with-each-other pairs, per the manual's note), `TYPE(LINEAR)`, `ROLLIN`.

- [ ] **Step 2: Run tests to verify they fail.**

- [ ] **Step 3: Implement `ast_alter.py`.**

- [ ] **Step 4: Implement `alter` grammar rule**, appended to `ams.lark`.

- [ ] **Step 5: Run tests to verify they pass.**

- [ ] **Step 6: Extend test coverage to every remaining parameter** listed in the design spec's `Alter` section (all ~45 — `ACCOUNT`, `BUFFERSPACE`, `BUFND`, `BUFNI`, `BWO`, `CATALOG`, `CCSID`, `ECSHARING`/`NOECSHARING`, `EMPTY`/`NOEMPTY`, `ERASE`/`NOERASE`, `EXCEPTIONEXIT`, `EXTENDEDADDRESSABLE`, `FIFO`/`LIFO`, `FILE`, `FILEDATA`, `FREESPACE`, `FRLOG`, `INHIBIT`/`UNINHIBIT`, `KEYS`, `LIMIT`, `MANAGEMENTCLASS`, `OWNER`, `PURGE`/`NOPURGE`, `RECLAIMCA`/`NORECLAIMCA`, `RECORDSIZE`, `REUSE`/`NOREUSE`, `RLSQUIESCE`/`RLSENABLE`, `SCRATCH`/`NOSCRATCH`, `SHAREOPTIONS`, `STORAGECLASS`, `STRNO`, `TO`/`FOR`, `UNIQUEKEY`/`NONUNIQUEKEY`, `UPDATE`/`NOUPDATE`, `UPGRADE`/`NOUPGRADE`, `WRITECHECK`/`NOWRITECHECK`, and all 9 `NULLIFY` sub-options).

- [ ] **Step 7: Run full test file, verify all pass.**

- [ ] **Step 8: Commit**

```bash
git add jackal/jackal/idcams/ast_alter.py jackal/jackal/idcams/grammar/ams.lark jackal/tests/unit/test_idcams_alter.py
git commit -m "feat(idcams): comprehensive ALTER grammar and typed AST"
```

---

### Task 7: REPRO (including ENCIPHER/DECIPHER)

**Files:**
- Create: `jackal/jackal/idcams/ast_repro.py`
- Modify: `jackal/jackal/idcams/grammar/ams.lark`
- Test: `jackal/tests/unit/test_idcams_repro_comprehensive.py`

**Interfaces:**
- Consumes: `Name` from Task 1.
- Produces: `Repro`, `CipherSpec`, `DecipherSpec`, `RangeStart`, `RangeEnd` — exact field list in the design spec's "`Repro`" section. This is a *new*, separate module from the existing execution-wired `jackal/jackal/idcams/commands.py::Repro` — different shape (this one is comprehensive; the old one is `infile_dd`/`outfile_dd` only), untouched.

- [ ] **Step 1: Write failing tests** covering: `INFILE`/`OUTFILE` (existing-shape-compatible case), `INDATASET`/`OUTDATASET`, each of the four `RangeStart` kinds and four `RangeEnd` kinds (mutually exclusive within each group, and the manual's start/end type-matching rule — e.g. `FROMKEY` pairs with `TOKEY`, not `TOADDRESS` — as at least one explicit rejection test), `MERGECAT`/`NOMERGECAT`, `REPLACE`/`NOREPLACE`, one `ENCIPHER` test with `EXTERNALKEYNAME`, one `DECIPHER` test with `SYSTEMKEY`, and a test confirming `ENCIPHER`/`DECIPHER` are mutually exclusive on one `REPRO` command.

- [ ] **Step 2: Run tests to verify they fail.**

- [ ] **Step 3: Implement `ast_repro.py`.**

- [ ] **Step 4: Implement `repro` grammar rule**, appended to `ams.lark`, including the nested `ENCIPHER(...)`/`DECIPHER(...)` sub-grammars.

- [ ] **Step 5: Run tests to verify they pass.**

- [ ] **Step 6: Extend test coverage to every remaining parameter** in the design spec's `Repro` section (`CIMODE`/`NOCIMODE`, `DBCS`, `ENTRIES`/`LEVEL`, `ERRORLIMIT`, `FILE`, `INSERTSHIFT`/`INSERTALL`, `MESSAGELEVEL`, `REUSE`/`NOREUSE`, `SKIPDBCSCHECK`/`NODBCSCHECK`, `VOLUMEENTRIES`, `RLSSOURCE`, `RLSTARGET`, and every `CipherSpec`/`DecipherSpec` sub-field: `CIPHERUNIT`, `DATAKEYFILE`/`DATAKEYVALUE`, `SHIPKEYNAMES`, `STOREDATAKEY`/`NOSTOREDATAKEY`, `STOREKEYNAME`, `USERDATA`, `SYSTEMDATAKEY`, `SYSTEMKEYNAME`).

- [ ] **Step 7: Run full test file, verify all pass.**

- [ ] **Step 8: Commit**

```bash
git add jackal/jackal/idcams/ast_repro.py jackal/jackal/idcams/grammar/ams.lark jackal/tests/unit/test_idcams_repro_comprehensive.py
git commit -m "feat(idcams): comprehensive REPRO grammar and typed AST, incl. ENCIPHER/DECIPHER"
```

---

### Task 8: PRINT, LISTCAT

**Files:**
- Create: `jackal/jackal/idcams/ast_print.py`
- Create: `jackal/jackal/idcams/ast_listcat.py`
- Modify: `jackal/jackal/idcams/grammar/ams.lark`
- Test: `jackal/tests/unit/test_idcams_print_listcat.py`

**Interfaces:**
- Consumes: `Name` from Task 1, `RangeStart`/`RangeEnd` from Task 7 (reused verbatim — `PRINT` has the identical four-kind start/end range shape as `REPRO`; import from `jackal.idcams.ast_repro`, do not redefine).
- Produces: `Print`, `Listcat` — exact field lists in the design spec's respective sections.

- [ ] **Step 1: Write failing tests** — `PRINT`: `INFILE`/`INDATASET` required, `CHARACTER`/`DUMP`/`HEX` (default `DUMP`), one `RangeStart`/`RangeEnd` pair, `DBCS` + `INSERTSHIFT`. `LISTCAT`: no-operand case (all defaults), multiple simultaneous entry-type filters (`ALIAS`+`CLUSTER` together — the manual allows combining), `ENTRIES`/`LEVEL` mutual exclusivity, each of the five detail levels (`NAME`/`HISTORY`/`VOLUME`/`ALLOCATION`/`ALL`, default `NAME`), `CDILVL`/`NOCDILVL` only valid alongside `LEVEL` (test that it's accepted when paired, and decide — document the decision in the test — whether the grammar rejects it standalone or defers that to a later semantic pass).

- [ ] **Step 2: Run tests to verify they fail.**

- [ ] **Step 3: Implement `ast_print.py` and `ast_listcat.py`.**

- [ ] **Step 4: Implement `print` and `listcat` grammar rules**, appended to `ams.lark`.

- [ ] **Step 5: Run tests to verify they pass.**

- [ ] **Step 6: Extend test coverage to every remaining parameter** in both design-spec sections (`PRINT`: `CIMODE`/`NOCIMODE`, `SKIPDBCSCHECK`/`NODBCSCHECK`, `OUTFILE`, `RLSSOURCE`. `LISTCAT`: `LIBRARYENTRIES`, `VOLUMEENTRIES`, `CATALOG`, `CREATION`, `EXPIRATION`, `PREFIX`/`NOPREFIX`, `FILE`, `LIBRARY`, `OUTFILE`).

- [ ] **Step 7: Run full test file, verify all pass.**

- [ ] **Step 8: Commit**

```bash
git add jackal/jackal/idcams/ast_print.py jackal/jackal/idcams/ast_listcat.py jackal/jackal/idcams/grammar/ams.lark jackal/tests/unit/test_idcams_print_listcat.py
git commit -m "feat(idcams): comprehensive PRINT and LISTCAT grammar and typed AST"
```

---

### Task 9: EXPORT, IMPORT

**Files:**
- Create: `jackal/jackal/idcams/ast_export.py`
- Create: `jackal/jackal/idcams/ast_import.py`
- Modify: `jackal/jackal/idcams/grammar/ams.lark`
- Test: `jackal/tests/unit/test_idcams_export_import.py`

**Interfaces:**
- Consumes: `Name` from Task 1.
- Produces: `Export`, `Import`, `ImportObject` — exact field lists in the design spec's respective sections.

- [ ] **Step 1: Write failing tests** — `EXPORT`: required positional entry + one of `OUTFILE`/`OUTDATASET`, `TEMPORARY`/`PERMANENT`, `INHIBITSOURCE`/`INHIBITTARGET` independence, `RLSSOURCE`. `IMPORT`: one of `INFILE`/`INDATASET` + one of `OUTFILE`/`OUTDATASET` required, `ALIAS`/`NOALIAS`, `LOCK`/`UNLOCK`, `INTOEMPTY`, and a real `OBJECTS(...)` list with 2+ entries each carrying `NEWNAME`+`VOLUMES` — this is the trickiest sub-structure (repeatable nested groups), give it its own dedicated test with 2 objects to confirm the list, not just a single-object shape, parses correctly.

- [ ] **Step 2: Run tests to verify they fail.**

- [ ] **Step 3: Implement `ast_export.py` and `ast_import.py`.**

- [ ] **Step 4: Implement `export` and `import` grammar rules**, appended to `ams.lark`. Note: `IMPORT` is a Python-safe attribute/module name but is also a Python keyword-adjacent builtin concept — name the dataclass module `ast_import.py` and the dataclass `Import` (not a reserved word, safe), but double-check no shadowing issues arise from the module name itself (it does not, since `import` the statement and `ast_import` the module name don't collide).

- [ ] **Step 5: Run tests to verify they pass.**

- [ ] **Step 6: Extend test coverage to every remaining parameter** (`EXPORT`: `CIMODE`/`RECORDMODE`, `ERASE`/`NOERASE`, `INFILE`, `PURGE`/`NOPURGE`. `IMPORT`: `ERASE`/`NOERASE`, `PURGE`/`NOPURGE`, `SAVRAC`/`NOSAVRAC`, `CATALOG`, `RLSTARGET`, and every `ImportObject` sub-field: `FILE`, `MANAGEMENTCLASS`, `STORAGECLASS`).

- [ ] **Step 7: Run full test file, verify all pass.**

- [ ] **Step 8: Commit**

```bash
git add jackal/jackal/idcams/ast_export.py jackal/jackal/idcams/ast_import.py jackal/jackal/idcams/grammar/ams.lark jackal/tests/unit/test_idcams_export_import.py
git commit -m "feat(idcams): comprehensive EXPORT and IMPORT grammar and typed AST"
```

---

### Task 10: VERIFY, BLDINDEX

**Files:**
- Create: `jackal/jackal/idcams/ast_verify.py`
- Create: `jackal/jackal/idcams/ast_bldindex.py`
- Modify: `jackal/jackal/idcams/grammar/ams.lark`
- Test: `jackal/tests/unit/test_idcams_verify_bldindex.py`

**Interfaces:**
- Consumes: `Name` from Task 1.
- Produces: `Verify`, `Bldindex` — exact field lists in the design spec's respective sections. `Verify` is small (`FILE`/`DATASET`, `RECOVER`) — this task is the lightest in the plan.

- [ ] **Step 1: Write failing tests** — `VERIFY`: `FILE(ddname)` form, `DATASET(entryname)` form, `RECOVER`. `BLDINDEX`: `INFILE`/`INDATASET` + `OUTFILE`/`OUTDATASET` (note `OUTFILE`/`OUTDATASET` each accept a *list* of 1+ ddnames/entrynames per the manual — test with 2 to confirm the list form, not just a single value), `EXTERNALSORT`/`INTERNALSORT`, `SORTCALL`/`NOSORTCALL`, `WORKFILES` with 2 ddnames.

- [ ] **Step 2: Run tests to verify they fail.**

- [ ] **Step 3: Implement `ast_verify.py` and `ast_bldindex.py`.**

- [ ] **Step 4: Implement `verify` and `bldindex` grammar rules**, appended to `ams.lark`.

- [ ] **Step 5: Run tests to verify they pass.**

- [ ] **Step 6: Extend test coverage to every remaining parameter** (`BLDINDEX`: `SORTDEVICETYPE`, `SORTFILENUMBER`, `SORTMESSAGEDD`, `SORTMESSAGELEVEL`, `CATALOG`).

- [ ] **Step 7: Run full test file, verify all pass.**

- [ ] **Step 8: Commit**

```bash
git add jackal/jackal/idcams/ast_verify.py jackal/jackal/idcams/ast_bldindex.py jackal/jackal/idcams/grammar/ams.lark jackal/tests/unit/test_idcams_verify_bldindex.py
git commit -m "feat(idcams): comprehensive VERIFY and BLDINDEX grammar and typed AST"
```

---

### Task 11: Modal commands — IF/THEN/ELSE/DO/END, SET, CANCEL

**Files:**
- Create: `jackal/jackal/idcams/ast_modal.py`
- Modify: `jackal/jackal/idcams/grammar/ams.lark` (replace Task 1's placeholder `modal_command` rule with the real one; wire `command:` to alternate across every command rule added by Tasks 2-10 plus this task's modal rule — this is also where `parser_comprehensive.py`'s `parse_ams` becomes able to parse a real mixed job stream, since only now does every command type exist)
- Test: `jackal/tests/unit/test_idcams_modal.py`

**Interfaces:**
- Consumes: every `*Command` dataclass from Tasks 2-10 (for the `AmsCommand` union type).
- Produces: `AmsCommand` (union type alias), `SetCommand`, `CancelCommand`, `IfCommand` — exact shapes in the design spec's "Modal Commands" section.

- [ ] **Step 1: Write failing tests** covering: `SET MAXCC=n` and `SET LASTCC=n`, bare `CANCEL`, a simple `IF LASTCC = 0 THEN <command> ELSE <command>` (both branches single-command, no `DO`/`END`), the manual's own two worked nested-`IF` examples transcribed verbatim (both from the design spec's modal-commands section / this session's earlier read of the manual's Chapter 2 — reproduce both `IF LASTCC > 4 THEN IF MAXCC < 12 THEN REPRO... ELSE DELETE... ELSE IF LASTCC = 4 THEN ELSE PRINT...` examples exactly), a `DO`/`END` block containing 2+ commands under one `THEN`, a null `THEN` (bare `THEN` followed by nothing, i.e. no action), a null `ELSE`, and an 11-level-deep nested `IF` that must be **rejected** (depth cap enforcement — write this test to assert a `ValueError` or `LarkError`, whichever the implementer's depth-check mechanism raises; document the choice in the test's docstring).

- [ ] **Step 2: Run tests to verify they fail.**

- [ ] **Step 3: Implement `ast_modal.py`** — transcribe `AmsCommand`, `SetCommand`, `CancelCommand`, `IfCommand` from the design spec's "Modal Commands" section verbatim, importing every command dataclass from Tasks 2-10's modules for the `AmsCommand` union.

- [ ] **Step 4: Implement the modal-command grammar rules**, replacing Task 1's placeholder in `ams.lark`. The `=` bare operator normalizes to `"EQ"` in the transformer (per the manual: `=` and `EQ` are the same operator, just two spellings). Enforce the depth-10 cap in the transformer (count nesting depth while building `IfCommand` instances; raise if exceeded — do not rely on the grammar itself to reject deep nesting, since Earley will happily parse arbitrarily deep recursion).

- [ ] **Step 5: Run tests to verify they pass.**

- [ ] **Step 6: Decide on `PARM`** — attempt a straightforward `PARM(TEST(...)|GRAPHICS(...)|MARGINS(...))` grammar rule following the same pattern as the other commands. If it's genuinely quick (reuses existing generic-value-list machinery with no new lexical needs), add it with a couple of tests and note it in the task report. If it turns out to need meaningfully new grammar machinery, stop, do **not** spend further budget on it, and report to the controller that `PARM` is being deferred — per the design spec's explicit call that this is the one place "comprehensive" yields to "not worth a dedicated task."

- [ ] **Step 7: Run full test file, verify all pass.**

- [ ] **Step 8: Commit**

```bash
git add jackal/jackal/idcams/ast_modal.py jackal/jackal/idcams/grammar/ams.lark jackal/tests/unit/test_idcams_modal.py
git commit -m "feat(idcams): comprehensive modal command grammar (IF/THEN/ELSE/DO/END, SET, CANCEL) and typed AST"
```

---

### Task 12: Real-corpus validation and completeness sign-off

**Files:**
- Create: `jackal/tests/integration/test_idcams_comprehensive_carddemo_e2e.py`
- Modify: none (verification-only task, plus the one bead close below)

**Interfaces:**
- Consumes: `parse_ams` from `jackal.idcams.parser_comprehensive` (Task 2+), real CardDemo JCL via the existing `carddemo_home`/`jcl_bridge_jar` fixtures (`jackal/tests/conftest.py`).

- [ ] **Step 1: Write the completeness test**

```python
# jackal/tests/integration/test_idcams_comprehensive_carddemo_e2e.py
"""Proves the comprehensive IDCAMS grammar parses every real IDCAMS
SYSIN block in the CardDemo corpus -- the design spec's stated
completion signal for this mission."""

from __future__ import annotations

from pathlib import Path

import pytest

from jackal.idcams.parser_comprehensive import parse_ams
from jackal.jcl.parser import parse_jcl
from tests.covers import NotLanguageFeature, covers

_IDCAMS_JCL_FILES = [
    "ACCTFILE.jcl", "CARDFILE.jcl", "CBEXPORT.jcl", "COMBTRAN.jcl",
    "CUSTFILE.jcl", "DALYREJS.jcl", "DEFCUST.jcl", "DEFGDGB.jcl",
    "DEFGDGD.jcl", "DISCGRP.jcl", "DUSRSECJ.jcl", "ESDSRRDS.jcl",
    "REPTFILE.jcl", "TCATBALF.jcl", "TRANBKP.jcl", "TRANFILE.jcl",
    "TRANIDX.jcl", "TRANCATG.jcl", "XREFFILE.jcl", "TRANTYPE.jcl",
]


@pytest.mark.carddemo_e2e
@covers(NotLanguageFeature.INFRASTRUCTURE)
@pytest.mark.parametrize("jcl_filename", _IDCAMS_JCL_FILES)
def test_real_idcams_sysin_parses_with_comprehensive_grammar(
    jcl_filename: str, carddemo_home: Path, jcl_bridge_jar: str
):
    job = parse_jcl((carddemo_home / "jcl" / jcl_filename).read_text())
    idcams_steps = [s for s in job.steps if s.pgm == "IDCAMS"]
    assert idcams_steps, f"{jcl_filename} has no IDCAMS steps -- check the list above"
    for step in idcams_steps:
        for dd in step.dds:
            if dd.ddname == "SYSIN" and dd.in_stream:
                text = "\n".join(dd.in_stream) + "\n"
                parse_ams(text)  # must not raise


@pytest.mark.carddemo_e2e
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_reproc_prc_parses_with_comprehensive_grammar(
    carddemo_home: Path, jcl_bridge_jar: str
):
    from jackal.jcl.parser import parse_proc

    proc = parse_proc((carddemo_home / "proc" / "REPROC.prc").read_text())
    for step in proc.steps:
        for dd in step.dds:
            if dd.ddname == "SYSIN" and dd.in_stream:
                text = "\n".join(dd.in_stream) + "\n"
                parse_ams(text)
```

- [ ] **Step 2: Run the test**

Run: `cd jackal && JCL_BRIDGE_JAR=$(pwd)/../jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar CARDDEMO_HOME=$(pwd)/../vendor/carddemo/app uv run --no-sync python -m pytest tests/integration/test_idcams_comprehensive_carddemo_e2e.py -v`
Expected: PASS for all 20 files + `REPROC.prc`. If any real block fails to parse, that is a genuine grammar gap — fix the specific command's grammar rule (in its own Task 2-11 module, not by adding a workaround here) and re-run; do not skip or xfail a failing real-corpus case.

- [ ] **Step 3: Confirm `forge-2zs` is subsumed and close it**

The comma-separated `RECORDSIZE(80,80)`/`KEYS(8,0)` gap filed as `forge-2zs` should now parse correctly as a side effect of this grammar being genuinely comprehensive (the manual's own syntax allows comma or space as the subparameter separator within a parenthesized list — confirm this was handled naturally by however Task 2 modeled `SpaceAllocation`/`keys`/`record_size` tuples, not as a special case). Verify directly:

```bash
cd jackal && uv run --no-sync python -c "
from jackal.idcams.parser_comprehensive import parse_ams
cmds = parse_ams('DEFINE CLUSTER (NAME(A.B) RECORDSIZE(80,80) KEYS(8,0) CYLINDERS(1) VOLUMES(V1))\n')
print(cmds[0].record_size, cmds[0].keys)
"
```
Expected output: `(80, 80) (8, 0)`. If this fails, fix Task 2's grammar rule for `RECORDSIZE`/`KEYS` to accept a comma as an alternate separator to whitespace before closing out this task.

```bash
bd close forge-2zs --reason="Subsumed by the comprehensive IDCAMS grammar (jackal/docs/superpowers/plans/2026-07-08-idcams-comprehensive-grammar.md) -- RECORDSIZE()/KEYS() now accept comma-separated args as part of full parameter fidelity, verified against real DUSRSECJ.jcl/ESDSRRDS.jcl text."
bd export -o beads/issues.jsonl
```

- [ ] **Step 4: Commit**

```bash
git add jackal/tests/integration/test_idcams_comprehensive_carddemo_e2e.py beads/issues.jsonl
git commit -m "test(idcams): prove the comprehensive grammar parses every real CardDemo IDCAMS SYSIN block; close forge-2zs"
```

---

## Post-Plan Note

This plan produces parsing only. A follow-up mission (not part of this plan) decides whether/how to wire the new `AmsCommand` AST into `jackal/jackal/idcams/executor.py` for real execution — until then, `jackal/jackal/jcl/utilities.py::idcams()` continues to use the existing minimal `parse_idcams`/`run_idcams` path unchanged.
