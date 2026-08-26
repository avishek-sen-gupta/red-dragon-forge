# Corpus onboarding blockers

Working ledger for onboarding a large production corpus — 3779 COBOL members, 860
JCL members — into cobble. Member names, dataset names, transaction ids and paths
are deliberately absent from this document; where an example is needed it is
given with placeholder names that preserve the structure being described.

Each entry records what was **measured**, the root cause at `file:line` inside
cobble, and the chosen fix. Entries are updated in place as they are fixed — this
is not a dated snapshot.

Provenance matters here. A corpus this size makes "the parser chokes on X" easy
to assert and easy to get wrong: two entries below were carried in an earlier
ledger with the wrong root cause, and the correction came only from running the
parser rather than grepping the corpus. Every count in this document was produced
by a script over the actual corpus; where a claim is a hypothesis rather than a
measurement, it says so.

Status key: **OPEN** (analysed, not fixed) · **FIXED** (committed) · **ACCEPTED**
(understood, not fixable from the material available).

---

## #4 Non-UTF-8 members — OPEN

**Symptom.** `UnicodeDecodeError` before the source ever reaches a parser.

**Measured.** 110 members carry bytes ≥ `0x80` (52 of 3779 COBOL, 58 of 860 JCL).

| byte | count | cp1252 / latin-1 meaning |
|---|---|---|
| `0xA6` | 1323 | `¦` broken bar — box-drawing in report layouts |
| `0xF8` | 3 | `ø` |
| `0x9F` | 2 | cp1252 `Ÿ` vs latin-1 `U+009F` (the only disagreement) |
| 14 others | 1 each | scattered one-offs |

Two further measurements decide the fix:

- **Zero** members are valid UTF-8 with non-ASCII content. There is nothing to
  gain from attempting UTF-8 first — no member would succeed under it.
- **One** member has a byte in `0x80`–`0x9F`, the only range where cp1252 and
  latin-1 differ: a SAS member, twice, in a format-value list and a comparison,
  both annotated `/* CONTAINS HIGH-VALUES */`. An opaque sentinel byte — cp1252's
  `Ÿ` is no more correct than latin-1's `U+009F`, so cp1252 buys nothing anywhere
  in this corpus.

**Placement** (this corrects an earlier claim in the ledger that the high bytes
were "all comments or banner data, nothing load-bearing"):

- COBOL: comment-line 882, **code area 146**, sequence area 3
- JCL: `//*` comment 68, in-stream data 4

The 146 code-area bytes are all in one member, inside `VALUE` literals of a
report layout:

```cobol
05  FILLER  PIC X(1)   VALUE '\xa6'.
05  FILLER  PIC X(17)  VALUE '\xa6  <heading text>'.
```

So `errors="replace"` is not free — it would turn 146 load-bearing literal
characters into `U+FFFD`.

**Root cause.** Three strict decode sites:

| site | code |
|---|---|
| `cobble/interpreter/cobol/cobol_parser.py:81` | `source.decode("utf-8")` before bridge stdin |
| `cobble/interpreter/cobol/cobol_parser.py:103` | same, in `parse_to_file` |
| `cobble/build_graph.py:92` | `path.read_text()` — no encoding, locale default |

Two sites are already tolerant and need no change: `cobol_imports.py:99` and
`build_graph.py:184` both pass `errors="replace"`.

**Fix.** One shared helper, used at all three sites:

```python
def decode_source(raw: bytes) -> str:
    """Fixed-format mainframe members are 8-bit text, not UTF-8. latin-1 is the
    byte-identity codec — defined for all 256 bytes, so it never raises and never
    loses a character. Measured on the production corpus: no member is valid UTF-8
    with non-ASCII content, so trying UTF-8 first would buy nothing."""
    return raw.decode("latin-1")
```

One byte stays one character, so fixed-format column positions hold and `PIC`
lengths are unaffected. The bridge is safe too: Python's `subprocess` encodes the
`str` to UTF-8 for stdin and Java decodes it back with `StandardCharsets.UTF_8`,
so `U+00A6` round-trips as one Java `char`.

**Caveat to keep in mind.** This is a decode choice, not a codepage claim. A
genuinely EBCDIC member would come through as silent garbage instead of raising.
Measured: all 110 are ASCII with a handful of high bytes, hence ASCII-compatible
and not EBCDIC. A future EBCDIC corpus needs detection, not this helper.

---

## #5 `DISP=(,PASS)` — omitted positional subparameter — OPEN

**`DISP=(,PASS)` is correct JCL.** `DISP=(status,normal-disp,abnormal-disp)` is
positional; omitting the status defaults it to `NEW`, so `(,PASS)` means
`(NEW,PASS)`. `PASS` hands the dataset to a later step in the same job.

**It is not a grammar failure.** An earlier ledger attributed this to the JCL
grammar. Measured with the real jar:

```
DISP=(,PASS)      FAIL 'PASS' is not a valid DispStatus — output: '{"name":"TESTJOB","steps":[{...
DISP=(NEW,PASS)   OK
```

The ANTLR parse succeeds and the emitted JSON is well-formed. The failure is on
the Python side, after the bridge.

**Measured shapes** across 21,133 `DISP=(...)` occurrences in the 860 members:

```
10535  DISP=(X,X)
 1574  DISP=(_,X)        <- breaks
  687  DISP=(X,X,X)
   37  DISP=(_,X,X)      <- breaks
    0  DISP=(_,_,X)
```

1611 broken occurrences across **328 of 860** members. Note the zero: no member
omits two leading slots, which is exactly the case a Python-side heuristic would
silently mis-slot.

**Root cause.** Positional structure is discarded at the JSON boundary:

- `jcl-bridge/src/main/java/org/jackal/jcl/JclSerializer.java:644` — `extractWords`
  recursively collects `keywordOrSymbolic` nodes and skips empty text, so
  `DISP=(,PASS)` serialises as `["PASS"]`, indistinguishable from `DISP=PASS`.
- `cobble/jackal/jcl/bridge_parser.py:44` — `DispStatus(words[0])` is
  index-positional with no notion of an omitted slot.
- `cobble/jackal/model.py:12` — `DispStatus` is `NEW|OLD|SHR|MOD`, correctly
  excluding `PASS` (a `DispNormal`), so the enum raises.

`extractWords` has exactly **one** caller, the DISP fold at `JclSerializer.java:597`,
so changing it cannot disturb any other DD parameter.

**Chosen fix.** Keep positional knowledge in the serializer, where the parse tree
still has it, rather than inferring it back in Python.

*Change 1 — `JclSerializer.java:644`.* Walk the `singleOrMultipleValue` node's
direct children and emit one array entry per positional slot: `LPAREN` opens the
list, `COMMA` closes the current slot (empty or not) and opens the next, a
`keywordOrSymbolic` child appends its text to the current slot, `RPAREN` closes
the last. No `LPAREN` at depth 0 (`DISP=SHR`) means a single slot, as today.

```
DISP=(,PASS)            -> ["", "PASS"]
DISP=(,PASS,DELETE)     -> ["", "PASS", "DELETE"]
DISP=(NEW,CATLG,DELETE) -> ["NEW", "CATLG", "DELETE"]
DISP=SHR                -> ["SHR"]
```

*Change 2 — `bridge_parser.py:43`.* Treat `""` as omitted and apply the z/OS
positional defaults — status → `NEW`, normal → `KEEP`, abnormal → the normal
disposition:

```python
def _disp_from_words(words: tuple[str, ...]) -> Disp:
    """DISP=(status,normal,abnormal). An omitted positional subparameter arrives
    as "" (see JclSerializer.extractWords) — omitted status defaults to NEW,
    omitted normal to KEEP, omitted abnormal to the normal disposition. The
    production corpus has 1611 such DDs across 328 members, nearly all
    DISP=(,PASS)."""
    status = DispStatus(words[0]) if words[0] else DispStatus.NEW
    normal = DispNormal(words[1]) if len(words) > 1 and words[1] else DispNormal.KEEP
    abnormal = DispNormal(words[2]) if len(words) > 2 and words[2] else normal
    return Disp(status, normal, abnormal)
```

The caller's `if words else _DEFAULT_DISP` guard stays, so a DD with no `DISP` at
all is untouched.

*Tests — `tests/jackal/test_bridge_parser.py` (new).* Pure Python, no JVM:
`("", "PASS")` → `Disp(NEW, PASS, PASS)`; `("", "PASS", "DELETE")` →
`Disp(NEW, PASS, DELETE)`; `("SHR",)` → `Disp(SHR, KEEP, KEEP)` as a regression
guard on the 11,222 shapes that already work; `("NEW", "")` →
`Disp(NEW, KEEP, KEEP)` for a trailing empty slot.

No Java test is committed: `jcl-bridge/src/test` does not exist (the repo has no
Java test infrastructure) and `make test` does not export `JCL_BRIDGE_JAR`, so a
JVM-dependent test would break `uv run pytest` on a fresh clone. The Java half is
verified by running the 328 affected members before and after.

**Graph payoff.** Omitted status resolves to `NEW`, which
`jcl_graph.py:_DISP_TO_EDGE_KIND` maps to `WRITES`. Those 1611 DDs go from
killing their member outright to emitting real `WRITES` edges.

**Adjacent, deliberately out of scope.** `bridge_parser.py:30` has
`_DEFAULT_DISP = Disp(SHR, KEEP, KEEP)` for a DD with no `DISP` at all, but the
z/OS default is `(NEW,DELETE,DELETE)`. Correcting it would flip those DDs from
`READS` to `WRITES` — a real graph change that deserves its own decision.

---

## #6 Bare `/*` delimiter line — OPEN

**Bare `/*` is correct JCL.** It is the JES2 *delimiter statement*, terminating
in-stream data (`DD *` / `DD DATA`). `//*` is the comment; `/*` is not.

**The lexer already models it.** In
`jcl-bridge/src/main/antlr4/org/jackal/jcl/JCLLexer.g4`:

```antlr
SA : SLASH ASTERISK { getCharPositionInLine() == 2 }? -> mode(JES2_CNTL_MODE) ;
DELIMITER_STATEMENT_1 : SA [ ]+ { myMode = DEFAULT_MODE; } -> type(DELIMITER_STATEMENT), mode(CM_MODE) ;
DELIMITER_STATEMENT_2 : SA NEWLINE -> type(DELIMITER_STATEMENT) ;
```

plus `DATA_MODE_TERMINATOR3` inside `mode DATA_MODE`, guarded on
`dlmVals.contains("/*")`. ANTLR's longest-match means `/*`+spaces and `/*`+newline
both beat the 2-character `SA`, so the token is produced correctly.

**The parser is where it breaks.** `JCLParser.g4:1003` defines
`delimiterStatement : DELIMITER_STATEMENT ;`, and it is referenced at exactly two
places — lines 53 and 79 — both as `delimiterStatement*` at the **tail** of a
job's statement group, after all `jclStep`s. It is absent from the mid-job
alternation. So a `/*` between steps closes the group, and the enclosing `( … )+`
restarts wanting a fresh JOB card.

**Measured.** 568 of 860 members contain a bare `/*` line; 350 of those do not
also contain `DISP=(,` (so #5 does not confound). Parsing 60 of those 350:

```
32  OK
28  jcl-bridge failed (exit 1): line N:9 mismatched input 'EXEC' expecting JOB
```

Not one error mentions `/*`. The `expecting JOB` symptom is the group having
closed early — exactly the tail-position placement above.

**Decisive test** on one affected member:

```
wholefile_asis:          FAIL line 70:9 mismatched input 'EXEC' expecting JOB
wholefile_no_slashstar:  OK steps=8
```

Removing only its 4 bare `/*` lines takes the member from zero steps to eight.
The relevant region — note the `/*` with no preceding `DD *`, so it is not
terminating in-stream data at all:

```jcl
//SYSIN    DD DSN=<library>(<member>),DISP=SHR
/*
//*--------------------------------------------------------------------
//<step>   EXEC    PGM=IEBGENER          <- reported error position
```

**Fix: grammar, not preprocessing.** Add `delimiterStatement` to the mid-job
statement alternation in `JCLParser.g4`. The token and the rule both already
exist; the grammar simply lists the rule in one of the two positions z/OS
permits. This grammar has been patched in-tree before (see the cobble-authored
comment on `DATA_MODE_TERMINATORX`).

Preprocessing is rejected on the merits, not on taste: when `/*` genuinely
terminates in-stream data the lexer consumes it as `DATA_MODE_TERMINATOR3` and
the parser never sees a token, so a text-level stripper would have to
re-implement `dlmVals` and `DATA_MODE` tracking to know which lines are safe to
delete — and a custom `DLM=` means the delimiter is not `/*` at all.

**Open risk — the mechanism is unproven.** Every minimal synthetic parses
cleanly: `/*` bare, `/*` followed by 78 spaces, `/*` before and after `//*`
comment lines, `/*` after a real `DD *` block, `/*` under a continued JOB card,
`/*` after a PROC-form `EXEC`. The break only fires in long real token streams,
which points at ANTLR's adaptive prediction choosing the tail-position reduction
only once enough statements precede it. If that is the mechanism, the alternation
edit may fix it or may relocate the ambiguity. Confirming requires `make jars`
and a re-sweep of the 568 members.

---

## #7 No CSD — ACCEPTED (but partly recoverable)

**What a CSD is.** The CICS System Definition file: a VSAM dataset holding CICS
resource definitions — the runtime's own registry of what exists. Populated by
the `DFHCSDUP` batch utility from `DEFINE` statements:

```
DEFINE TRANSACTION(T001) GROUP(GRP) PROGRAM(PGM001)
DEFINE PROGRAM(PGM001)   GROUP(GRP) LANGUAGE(COBOL)
DEFINE MAPSET(MAP001)    GROUP(GRP)
DEFINE FILE(FILE001)     GROUP(GRP) DSNAME(<dataset>)
```

cobble reads it in `cobble/cics/csd_parse.py` for one thing: the **transaction-id
→ program** map. Nothing in the COBOL source states which transid starts which
program — `EXEC CICS RETURN TRANSID('T001')` names a transid whose target only
the CSD knows.

**Measured: the CSD content is genuinely absent from this corpus.**

| pattern | files |
|---|---|
| `DFHCSDUP` | 0 |
| `DEFINE PROGRAM` | 0 |
| `DFHPCT`, `DFHPPT`, `TYPE=ENTRY`, `DFHSIT`, `DFHRPL` | 0 each |
| `DEFINE TRANSACTION` | 1 — false positive |
| `CEDA` | 4 — false positives |

The `DEFINE TRANSACTION` hit is a `//*` comment about an IDCAMS VSAM cluster. The
`CEDA` hits are all a COBOL field name ending in those four letters. Recorded in
the corpus config as `csd_files: []`.

**Cost as things stand.** No `TRANSACTION` nodes; `RETURN TRANSID` and
`START TRANSID` edges have no resolvable target.

**Measured: the mapping is recoverable from a naming convention.** In the online
program directory, comment lines stripped and code area only: 2944 literal
`RETURN TRANSID`, 2687 literal `START TRANSID`, and only 3 literal
`XCTL PROGRAM`. Of the distinct literal transids:

- 1054 distinct (whole-line grep) / 1052 (code area only, `RETURN`/`START` — the
  two extra come from continuation or comment context)
- 1024 of 1054 share a single leading character
- **1008 of 1052** have an existing program at a fixed prefix plus the transid's
  last three characters

The convention is a consistent triple, shown here with placeholder prefixes:

```
transid  T<nnn>  ->  program  <pgm-prefix><nnn>  ->  mapset  <map-prefix><nnn>
```

Suffix matching alone is ambiguous — a given three-character suffix also matches
members in the batch, VSAM-definition and mapset families — but only one prefix
is the online program family, and the corpus config's `bms_globs` already encodes
the mapset leg of the same convention.

**Proposed shape, not yet designed.** A **config-declared pattern**, following
`copybook_extensions`: the corpus owns the guess, the derived edges stay
attributable to it, and the public sample corpus (which has a real CSD) is
unaffected. A convention is not a definition — a transid deliberately aimed at a
different program is invisible to it, and 44 transids do not resolve — so this
must never be hardcoded in the extractor.

---

## Other open blockers (not yet analysed to this depth)

- **#3 One bad parse aborts the whole run.** `cobble/interpreter/cobol/ast_store.py:81`
  — `fut.result()` re-raises the first failure inside `parse_all`. The per-program
  `try/except` at `build_graph.py:292` is *downstream* of the `parse_all` call at
  `:291`, so it never helps. One unparseable member kills all 3779. **This is the
  entry that makes every other one survivable** and should probably go first.
- **`PROGRAM-ID` ≠ filename** — 16 of 3779 members; none is missing a
  `PROGRAM-ID`. The pairs are recorded outside the repo.
- **Absent copybook directory crashes the bridge.** A configured `copybook_dirs`
  entry that does not exist on disk is passed straight to Java, whose
  `listFiles()` returns null: `NullPointerException: Cannot read the array length
  because "<local4>" is null` in `org.reddragon.bridge.Main.resolveInputFile`.
  cobble should reject or drop nonexistent directories before invoking the bridge.
- **Generated-symbolic output is untracked by the cleanup targets.** `.gitignore`
  and the `clean` target both name only the default `sym/` directory, not a
  per-corpus one.
- **The online members need `make sym CONFIG=<corpus>` first**, otherwise every
  one of them fails with `Copybook not found`.
- **Empty-copybook synthesis** to get past `Copybook not found` for copybooks
  absent from the corpus entirely. Deferred by decision, not by oversight.

## Fixed

Fixes are named by what they changed rather than by commit SHA: this history has
been rewritten, so any SHA recorded here would be stale. `git log --grep` on the
description finds the commit.

- **#1, #2** — earlier sessions.
- **`ALTERNATE KEY` grammar** — added to the ProLeap fork's
  `alternateRecordKeyClause`; cobble tracks it through the submodule pin.
- **`PIC X(8)B(3)`** — `pic_parser` now accepts a `B` (blank-insertion)
  character in a PICTURE string.
- **`EXEC SQL` aborts the program** — `parse_statement` raised
  `Unknown COBOL statement type: 'EXEC_SQL'` with only Cicada's dialect parser
  registered; `cobble/sql/` now ports Squall's parse-time `DialectParser` and
  `verb_source_asg.asg_dialect_parsers()` registers both.
