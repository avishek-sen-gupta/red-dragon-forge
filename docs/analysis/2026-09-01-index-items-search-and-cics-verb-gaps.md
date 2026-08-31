# Runtime gaps found by executing a production CICS program

*2026-09-01*

## Provenance

A production CICS/COBOL corpus (2,137 online programs) was brought up against
cicada + red-dragon. Every program in the target flow reached *compiles*, and one
of them was then **executed** for the first time: a two-turn pseudo-conversational
program, real BMS maps, real VSAM file control, terminating normally on
`DispatchKind.RETURN`.

It ran. It also produced an answer that its own source code says is impossible.

That single wrong answer decomposes into six defects, all in the same family:
**a component cannot do something, does not say so, and produces a plausible
result instead.** Compilation is not where these live and the test suite does not
reach them, so they are recorded here with self-contained reproductions — no
corpus, no client data, nothing to fetch.

Nothing in this document requires the original corpus. Every reproduction below is
a complete COBOL program you can paste into a probe script.

## Table of contents

| # | Defect | Severity | Where |
|---|---|---|---|
| A | `INDEXED BY` index items are never allocated | **wrong answer, silent** | bridge → layout → subscript |
| B | Unknown data-name lowered as a string literal | **wrong answer, silent** | `condition_lowering.py:952` |
| C | `SEARCH` ignores the table: no implicit index, no OCCURS bound, walks out of bounds | **wrong answer, silent** | `lower_search.py` |
| D | `SET target TO <data-item>` writes the item's *name* | **wrong answer, silent** | `lower_arithmetic.py:1772` |
| E | Unimplemented `EXEC CICS` verbs emit no IR and only warn | **missing behaviour, silent** | `cics/strategy.py:1064` |
| F | `HANDLE CONDITION` is a no-op and no condition is ever raised | **wrong control flow, silent** | `cics/strategy.py:60` |

Severity here means *what a consumer sees*, not how hard the fix is. All six are
"silent": nothing raises, nothing abends, and the run reports success.

---

## The observed failure

The executed program's error path is, in shape:

```cobol
      * A shared error-message table, laid out as fixed text then REDEFINEd
      * into an indexed table. This idiom is pervasive in the corpus.
       01  MSG-BYTES.
           02  FILLER  PIC X(78) VALUE
              'E401 FILE NOT OPEN, INFORM OPERATOR'.
           02  FILLER  PIC X(78) VALUE
              'E408 RECORD NOT FOUND IN MASTER'.
      *    ... 355 more ...
       01  MSG-TAB REDEFINES MSG-BYTES.
           05  MSG-ROW OCCURS 357 TIMES INDEXED BY MSG-IX.
               10  MSG-KEY   PIC X(4).
               10  MSG-TEXT  PIC X(74).
```

```cobol
           IF OUT-CODE NOT = LOW-VALUES AND SPACES
              SET MSG-IX TO 1
              SEARCH MSG-ROW
                  AT END  MOVE 'ERROR MSGE NOT FND' TO OUT-TEXT
                     WHEN MSG-KEY (MSG-IX) = OUT-CODE
                          MOVE MSG-TEXT (MSG-IX)   TO OUT-TEXT
              END-SEARCH
           END-IF.
```

Read the control flow: if `OUT-CODE` is set, `OUT-TEXT` **cannot** come out blank.
Either a `WHEN` matches and the message text lands there, or `AT END` fires and the
literal lands there.

The screen came back with `OUT-CODE` set and `OUT-TEXT` still `LOW-VALUES`.

The only diagnostic anywhere in the run was:

```
WARNING interpreter.cobol.lower_arithmetic: SET target MSG-IX not found in layout
```

which points at the `SET` — the one part of this that did no damage.

---

## Defect A — `INDEXED BY` index items are never allocated

### What COBOL says

`OCCURS n TIMES INDEXED BY IX` declares a data item. `IX` is an index: a
compiler-allocated binary item (4 bytes on IBM COBOL) holding an occurrence
*displacement*. It must not be declared by the programmer — there is deliberately
no `01 IX PIC ...` anywhere, because writing one is an error.

`IX` is then usable in exactly three places: `SET`, a subscript, and `SEARCH`.

### What happens

The name never leaves the Java bridge. `DataFieldSerializer.java` extracts
`occurs`, `occurs_min` and `occurs_depending_on` from the `OccursClause` and
nothing else:

```java
int occursCount = extractOccurs(group);
if (occursCount > 0) {
    obj.addProperty("occurs", occursCount);
}
```

`OccursClause.getIndexNames()` is never called — `grep -rn "IndexName" proleap-bridge/src/main/java/`
returns nothing. So `asg_types.py:81-90` has `occurs`, `occurs_min`,
`occurs_depending_on` and no index names, `data_layout.py` has nothing to allocate,
and `MaterialisedSectionedLayout.has_field("MSG-IX")` is `False` forever.

Note `DataFieldSerializer.java:482` does map `USAGE INDEX` (`case "INDEX" -> "INDEX"`).
So an *explicitly declared* `USAGE INDEX` item works; only the `INDEXED BY`
compiler-allocated form is missing. The fix is symmetric with something already
present.

### The two consequences

**`SET MSG-IX TO 1`** — loud, harmless. `lower_arithmetic.py:1774-1776` and
`:1786-1788` warn and `continue`, so the statement produces no IR. Bad, but
visible.

**Every subscript `MSG-KEY (MSG-IX)`** — silent, poisonous. See defect B for the
mechanism. No warning at all.

### Fix shape

1. Extract index names in `DataFieldSerializer.java` alongside `occurs`
   (`OccursClause.getIndexNames()`), as e.g. `"indexed_by": ["MSG-IX"]`.
2. Carry them on the ASG group in `asg_types.py` (`from_dict`/`to_dict` both).
3. Allocate one 4-byte binary item per index name in `data_layout.py`, in the
   same section as the table. Occurrence displacement vs occurrence number is a
   real semantic choice: IBM stores a displacement, but nothing here reads the
   raw bytes, so an occurrence *number* is simpler and the difference is
   unobservable unless a program `REDEFINES` an index (illegal) or writes one via
   a group MOVE (also illegal). Pick occurrence number, and say so in a comment.
4. Associate index → table so `SEARCH` can find the table's implicit index
   (defect C) and so subscripting can bounds-check.

### Blast radius

In the corpus: **122 programs and 53 copybooks** declare `INDEXED BY`. Because the
declaration is usually in a shared copybook while the `SEARCH` is in the program,
the affected-program count is far higher than 122 — see defect C.

---

## Defect B — an unknown data-name is lowered as a string literal

This is the mechanism behind defect A's silent half, and it is a general defect
independent of indexes.

There are two expression lowerers in `interpreter/cobol/condition_lowering.py`,
and they disagree about what to do with a name that is not in the layout.

**The dict-based lowerer, `_lower_expr_dict` (`:758-775`) — loud, correct:**

```python
        # The bridge sometimes tags a numeric literal as a ref (e.g. an
        # abbreviated-condition operand "1"); parse it as the literal it is.
        parsed = ctx.parse_literal(name)
        if isinstance(parsed, (int, float)):
            return ctx.const_to_reg(parsed)
        # A genuinely unresolvable data-name: emit an obviously-wrong sentinel
        # (rather than silently coercing the name to a string literal) so the
        # failure is visible in logs and in the IR.
        logger.warning("unresolvable field reference %r — emitting sentinel", name)
        return ctx.const_to_reg(f"UNRESOLVABLE__{name}")
```

**The node-based lowerer, `lower_expr_node` (`:948-952`) — silent, wrong:**

```python
    if isinstance(node, FieldRefNode):
        if ctx.has_field(node.name, materialised):
            ref, rr = ctx.resolve_field_ref(
                node.name, materialised, subscripts=node.subscripts
            )
            return ctx.emit_decode_field(rr, ref.fl, ref.offset_reg)
        return ctx.const_to_reg(ctx.parse_literal(node.name))
```

The last line does precisely the thing the other lowerer's comment says it stopped
doing. The sentinel fix was applied to one of the two paths.

`EmitContext.resolve_field_ref` lowers subscripts through the **node**-based one
(`emit_context.py:302`, `idx_reg = lower_expr_node(self, subscripts[0], materialised)`),
which is why an unresolvable subscript is invisible.

### How that becomes a false match

`MSG-IX` lowers to the string `"MSG-IX"`. The single-subscript fast path
(`emit_context.py:300-302`) then computes `(idx - 1) * stride + base`, i.e.
`("MSG-IX" - 1) * 78`. String arithmetic in the VM yields a `SymbolicValue`. The
region load gets a symbolic offset and returns a `SymbolicValue`. A `SymbolicValue`
compares equal to anything, so:

* the `WHEN` matches on the first iteration regardless of table contents;
* the `MOVE MSG-TEXT (MSG-IX) TO OUT-TEXT` that follows writes nothing;
* `AT END` is never reached.

Success path, empty result, no diagnostic. That is the whole observed failure.

### Reproduction

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SRCHPROBE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  MSG-BYTES.
           02  FILLER        PIC X(14)   VALUE 'E401MSG-FOR-401'.
           02  FILLER        PIC X(14)   VALUE 'E408MSG-FOR-408'.
           02  FILLER        PIC X(14)   VALUE 'E409MSG-FOR-409'.
       01  MSG-TAB REDEFINES MSG-BYTES.
           05  MSG-ROW OCCURS 3 TIMES INDEXED BY MSG-IX.
               10  MSG-KEY   PIC X(4).
               10  MSG-TEXT  PIC X(10).
       01  IN-CODE      PIC X(4)  VALUE 'E408'.
       01  OUT-TEXT     PIC X(10) VALUE SPACES.
       PROCEDURE DIVISION.
           DISPLAY 'A-GUARD-BEFORE'.
           IF IN-CODE NOT = LOW-VALUES AND SPACES
              DISPLAY 'A-GUARD-TRUE'
           ELSE
              DISPLAY 'A-GUARD-FALSE'
           END-IF.
           SET MSG-IX TO 1.
           SEARCH MSG-ROW
               AT END  DISPLAY 'B-AT-END'
                  WHEN MSG-KEY (MSG-IX) = IN-CODE
                       DISPLAY 'B-WHEN-HIT'
                       MOVE MSG-TEXT (MSG-IX) TO OUT-TEXT
           END-SEARCH.
           DISPLAY 'B-OUT-TEXT=' OUT-TEXT.
      * Controls: a literal subscript resolves; an index-name subscript does not.
           DISPLAY 'C-LIT2-KEY=' MSG-KEY (2).
           DISPLAY 'C-LIT2-TEXT=' MSG-TEXT (2).
           DISPLAY 'C-IDX-KEY=' MSG-KEY (MSG-IX).
           STOP RUN.
```

Observed:

```
WARNING interpreter.cobol.lower_arithmetic: SET target MSG-IX not found in layout
'A-GUARD-BEFORE''A-GUARD-TRUE''B-SEARCH-BEFORE''B-WHEN-HIT''B-OUT-TEXT='
'C-LIT2-KEY='E408'C-LIT2-TEXT='MSG-FOR-40
'C-IDX-KEY='SymbolicValue(name='sym_24', type_hint='__string_concat_pair(...)')
```

Read it bottom-up:

* `C-LIT2-*` — a **literal** subscript is correct. `MSG-KEY (2)` is `E408`,
  `MSG-TEXT (2)` is `MSG-FOR-40`. So `FILLER ... VALUE` initialisation, the
  `REDEFINES`, and the `OCCURS` stride all work. The table machinery is sound.
* `C-IDX-KEY` — an **index-name** subscript is a `SymbolicValue`. The defect, in
  one line of output.
* `B-WHEN-HIT` with an empty `B-OUT-TEXT=` — the lie. It claims a hit on entry 1
  (`E401`) while searching for `E408`.
* `A-GUARD-TRUE` clears a suspect that looked likelier at first: the abbreviated
  combined relation `IF IN-CODE NOT = LOW-VALUES AND SPACES` evaluates **true**.
  That condition form is not implicated. Worth knowing so nobody re-investigates it.

### Fix shape

Make `lower_expr_node`'s `FieldRefNode` fallback match `_lower_expr_dict`: try a
numeric literal, then warn and emit `UNRESOLVABLE__<name>`. Better still, extract
the shared policy into one helper both call, so the next fix cannot land on only
one path — the divergence is the actual root cause here, not either branch.

Consider making it a hard error behind a strictness flag. An undeclared identifier
in a COBOL expression is a compile error on every real compiler; degrading it to
data is never right. A sentinel is a big improvement on silence, but it is still a
value that flows.

---

## Defect C — `SEARCH` ignores the table it was given

`interpreter/cobol/lower_search.py` is 134 lines. `stmt.table` is **never
referenced** — `grep -n "stmt\." lower_search.py` returns only `stmt.whens`,
`stmt.at_end`, and `stmt.varying`. Three consequences.

### C1 — no implicit index, so a plain `SEARCH` never advances

```python
    if stmt.varying and ctx.has_field(stmt.varying, materialised):
        # ... increment the varying field ...
```

`lower_search.py:94`. The increment is emitted **only** for an explicit `VARYING`
operand that resolves in the layout. Format 1 `SEARCH tbl` with no `VARYING` uses
the table's first `INDEXED BY` index implicitly, and that is the overwhelmingly
common form. Nothing advances; the loop re-tests the same occurrence until the
bound.

The bridge is not at fault: `StatementSerializer.serializeSearch` (`:1341`)
correctly emits `table`, `varying` (when a `VARYING` phrase exists), `whens` with
structured conditions, and `at_end`. The information needed to find the implicit
index is present in `table` — it is simply unused.

Note the ordering dependency: **fixing C1 requires defect A first.** Until index
items exist in the layout, there is no implicit index to advance.

### C2 — a hard-coded 256 bound instead of the OCCURS count

```python
    max_iterations = 256
```

`lower_search.py:37`. Real `SEARCH` terminates when the index exceeds the table's
occurrence count, and only then runs `AT END`.

For a table **larger** than 256, occurrences 257..n are never examined and `AT END`
fires as though the table were exhausted — a false "not found". The corpus has
**45 `OCCURS` clauses above 256**, including the 357-entry error-message table at
the centre of the observed failure. So even after A and C1 are fixed, that table
still cannot be searched correctly.

### C3 — a short table is walked far past its end

For a table **smaller** than 256, the loop keeps subscripting past the last
occurrence, reading adjacent storage, until it hits the artificial cap. There is no
bounds check. A `WHEN` that matches whatever happens to follow the table in memory
returns a false hit from outside the table.

### Reproduction for C1–C3, and the working workaround

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IDXPROBE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  TBL-BYTES.
           05  FILLER  PIC X(6) VALUE 'K01V01'.
           05  FILLER  PIC X(6) VALUE 'K02V02'.
           05  FILLER  PIC X(6) VALUE 'K03V03'.
       01  TBL REDEFINES TBL-BYTES.
           05  TBL-ROW OCCURS 3 TIMES INDEXED BY TBL-IX.
               10  TBL-KEY   PIC X(3).
               10  TBL-VAL   PIC X(3).
       01  WS-SUB       PIC 9(4) VALUE 1.
       01  WS-HIT       PIC X(6) VALUE SPACES.
       01  BIG-BYTES    PIC X(1500).
       01  BIG REDEFINES BIG-BYTES.
           05  BIG-ROW OCCURS 300 TIMES INDEXED BY BIG-IX.
               10  BIG-CELL  PIC X(5).
       01  WS-N         PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
      * D: a plain numeric field as the VARYING subscript, over a real table.
           MOVE 1 TO WS-SUB.
           SEARCH TBL-ROW VARYING WS-SUB
               AT END  DISPLAY 'D-AT-END'
                  WHEN TBL-KEY (WS-SUB) = 'K03'
                       DISPLAY 'D-HIT-SUB=' WS-SUB
                       MOVE TBL-VAL (WS-SUB) TO WS-HIT
           END-SEARCH.
           DISPLAY 'D-VAL=' WS-HIT.
      * G: does SEARCH walk past the end of a SHORT table?
           MOVE 1 TO WS-SUB.
           SEARCH TBL-ROW VARYING WS-SUB
               AT END  DISPLAY 'G-AT-END-AT-SUB=' WS-SUB
                  WHEN TBL-KEY (WS-SUB) = 'ZZZ'
                       DISPLAY 'G-IMPOSSIBLE'
           END-SEARCH.
      * F: does SEARCH reach occurrence 300 of a 300-entry table?
           MOVE 1 TO WS-N.
           SEARCH BIG-ROW VARYING WS-N
               AT END  DISPLAY 'F-AT-END-AT-N=' WS-N
                  WHEN BIG-CELL (WS-N) = 'NEVER'
                       DISPLAY 'F-IMPOSSIBLE'
           END-SEARCH.
           STOP RUN.
```

Observed:

```
'D-HIT-SUB='3'D-VAL='V03   'G-AT-END-AT-SUB='257'F-AT-END-AT-N='257
```

* **D passes.** `SEARCH tbl VARYING <plain numeric field>`, with the `WHEN`
  subscripted by that same field, is fully correct — it found occurrence 3 and
  moved `V03`. This is important twice over: it confirms the table, stride and
  subscript machinery are sound, and it gives a **workaround** for anyone who needs
  a corpus program to run before these fixes land (rewrite `SET ix TO 1` /
  `SEARCH tbl` as `MOVE 1 TO sub` / `SEARCH tbl VARYING sub`).
* **G**: a 3-occurrence table ran to iteration 257 — **254 iterations past the end
  of the table**, subscripting out of bounds, silently. C3 confirmed.
* **F**: a 300-occurrence table stopped at 257. Occurrences 257–300 unreachable,
  and `AT END` reported not-found. C2 confirmed.

### C4 — `SEARCH ALL` is indistinguishable from `SEARCH`

`serializeSearch` calls `newStatement("SEARCH")` with no flag for the `ALL` form,
and `SearchStatement` (`cobol_statements.py:957-963`) has no field for it. So
`SEARCH ALL` lowers to a linear scan. `CobolFeature.SEARCH_BINARY` exists in
`features.py:91` and is claimed by no test — correctly, since it is unimplemented.

Severity: low, and **not** a blocker. For an equality `WHEN` over a sorted table a
linear scan returns the same answer, just slower, and `AT END` semantics coincide.
The corpus contains **zero** `SEARCH ALL`. Recorded for completeness; do not
sequence work behind it.

### Fix shape

1. Resolve `stmt.table` to its layout group. Derive the occurrence count from
   `occurs_count` and use it as the loop bound instead of `256`.
2. When `stmt.varying` is absent, advance the table's first `INDEXED BY` index
   (requires defect A).
3. Keep a large hard cap as a runaway guard only, and log if it is ever the
   terminating condition — that way a future bound bug is loud instead of silent.
4. Honour `SEARCH ALL` when convenient, or reject it explicitly. Silently
   downgrading it is acceptable only while it stays documented.

### Blast radius

Of 2,137 online programs: **489 contain an explicit `END-SEARCH`** (620
occurrences), and 1,337 lines parse as a `SEARCH` statement head — the difference
is period-terminated `SEARCH`es. **845 lines** are `WHEN` clauses subscripted by an
index-shaped name. Conservatively: **≥620 `SEARCH` statements across ≥489
programs**, every one of them currently capable of a false match.

The shared error-message table means essentially **every program's error path** is
affected. Error messages are exactly where a silently-blank result is least likely
to be noticed and most likely to be believed.

### Why the test suite did not catch this

Both `SEARCH` integration tests (`tests/integration/test_cobol_programs.py:1772`
and `:1797`) are:

```cobol
"77 WS-IDX PIC 9(4) VALUE 1.",
...
"    SEARCH WS-IDX VARYING WS-IDX",
"        AT END MOVE 99 TO WS-FOUND",
"        WHEN WS-IDX = 3",
"            MOVE 1 TO WS-FOUND.",
```

The "table" is a scalar `77` item. There is no `OCCURS`, no `INDEXED BY`, no
subscript in the `WHEN`, and `VARYING` is explicit. Every ingredient that fails in
practice — a real table, a compiler-allocated index, a subscripted comparison, an
implicit advance, the occurrence bound — is absent. The tests exercise the one
shape that works.

Any fix should land with a test built on a real `OCCURS ... INDEXED BY` table:
assert the matching occurrence's *data* (not just that some branch ran), assert
`AT END` on a genuine miss, and assert the bound at both `n < 256` and `n > 256`.

---

## Defect D — `SET target TO <data-item>` writes the item's name

Separate from indexes, found while investigating them, and it will bite
immediately after defect A is fixed.

`lower_arithmetic.py:1770-1783`:

```python
    if stmt.set_type == "TO":
        value_str = stmt.values[0] if stmt.values else "0"
        for target_name in stmt.targets:
            ...
            target_ref, target_rr = ctx.resolve_field_ref(target_name, materialised)
            value_str_reg = ctx.const_to_reg(str(value_str))
```

`stmt.values[0]` is raw operand text — `serializeSet` (`StatementSerializer.java:1091`)
fills it with `extractValueStmtText(val.getValueStmt())`. It is never tested for
being a data-name. So `SET A TO B` writes the two characters `"B"`.

Observed, with `WS-B` holding 7:

```
'E-FROM-FIELD-WS-A='0        <- SET WS-A TO WS-B   (expected 7)
'E-FROM-LITERAL-WS-A='7      <- SET WS-A TO 7      (correct)
```

Note how it hides: writing a *name* into a numeric field encodes as zeros, so the
symptom is a plausible `0` rather than anything that looks like a bug.

`SET idx-a TO idx-b` and `SET idx TO some-field` are both legal COBOL and both
take this path. Today they are masked, because index targets fail the
`has_field` check first and are dropped with a warning. Fix defect A without
fixing this and every `SET` from a data item starts silently writing a name.

Fix shape: in both the `TO` and `BY` branches, test the source with `has_field`
and, when it resolves, decode it as a field (`emit_decode_field`) instead of
`const_to_reg`. `SET ... UP/DOWN BY` at `:1793` has the same shape with
`step_val` — check both.

---

## Defect E — unimplemented `EXEC CICS` verbs emit no IR and only warn

`cics/strategy.py:1064`:

```python
        logger.warning(
            "CicsLoweringStrategy: unimplemented verb %r — no IR emitted", verb
        )
```

The statement disappears. The program runs on as though it had executed.

This is well-signposted in the code, and for a single missing verb in a test it is
a reasonable stance. At corpus scale it is not: a program can log four such
warnings, terminate on a normal `RETURN`, and look like a clean run while having
skipped its entire downstream flow. That is what the first execution did.

### What is implemented

From `strategy.py`: `RETURN`, `RETURN TRANSID`, `XCTL`, `ABEND`, `ASSIGN`,
`ASKTIME`, `FORMATTIME`, `INQUIRE`, `HANDLE ABEND`, `HANDLE CONDITION` (no-op, see
defect F), `HANDLE AID` (no-op), `SEND MAP`, `RECEIVE MAP`, `SEND TEXT`, `READ`,
`WRITE`, `REWRITE`, `DELETE`, `STARTBR`, `READNEXT`, `READPREV`, `ENDBR`,
`WRITEQ TD`, `LINK`.

### What the corpus needs and does not have

Occurrence counts across 2,137 online programs:

| Verb | Occurrences | Notes |
|---|---|---|
| `START` | 3,021 | flow control between transactions — blocks composition |
| `BIF DEEDIT` | 992 | numeric de-editing of screen input |
| `RETRIEVE` | 920 | receives `START ... FROM` data |
| `IGNORE CONDITION` | 820 | pairs with `HANDLE CONDITION` |
| `UNLOCK` | 457 | releases VSAM update position |
| `DELETEQ TS` | 144 | temporary storage |
| `READQ TS` | 98 | temporary storage |
| `WRITEQ TS` | 88 | temporary storage (`WRITEQ TD` *is* implemented) |
| `SPOOLOPEN/WRITE/CLOSE` | 116 | report spooling |
| `ROUTE` | 25 | BMS routing |
| `DELAY` | 25 | |
| `SYNCPOINT` | 20 | |
| `RESETBR` | 8 | browse repositioning — the browse family is otherwise complete |
| `GETMAIN` | 7 | |
| `ENQ` / `DEQ` | 3 / 3 | |

For comparison, the implemented verbs by volume: `READ` 9,534, `RETURN` 5,607,
`LINK` 4,050, `FORMATTIME` 2,814, `HANDLE` 2,810, `ASKTIME` 2,714,
`READNEXT` 2,434, `STARTBR` 2,414, `ENDBR` 2,233, `REWRITE` 1,806, `ASSIGN` 1,387,
`WRITE` 1,372, `SEND` 1,372, `RECEIVE` 1,046, `DELETE` 605, `READPREV` 425,
`XCTL` 5, `INQUIRE` 4.

`START` alone outranks every implemented verb except the top three.

### The parser is not the problem

`cics_visitor.py` uses the full ANTLR `CICSzParser` grammar and extracts options
generically (`_extract_options` at `:371`, `_extract_from_option` at `:381`), then
maps the rule-context class name to a verb string via `_CONTEXT_TO_VERB`. That
table already contains `"Start": "START"` (`:280`) and `"Retrieve": "RETRIEVE"`
(`:244`).

So `START`'s `TRANSID`, `TERMID`, `FROM`, `LENGTH`, `INTERVAL`, `REQID` and
`RETRIEVE`'s `INTO`, `LENGTH` **already arrive fully parsed in `opts`**. The work
is entirely in `strategy.py` lowering plus runtime plumbing. That is a much smaller
job than it looks.

### `START` / `RETRIEVE` design notes

`DispatchKind` (`cics/types.py:18-22`) has `RETURN`, `RETURN_TRANSID`, `XCTL`,
`ABEND`. There is no `START`.

Every `START` in the surveyed programs sits at a flow exit, immediately followed by
`EXEC CICS RETURN`, so the minimum viable shape is:

1. Add `DispatchKind.START` plus `transid`, `termid` and start-data fields to
   `DispatchResult`.
2. Route it in `_advance_routing` (`cics/dispatcher.py:95-107`) the same way
   `RETURN_TRANSID` is routed, carrying start data instead of a COMMAREA.
3. Add a per-terminal start-data store the runtime can hold between tasks.
4. Implement `RETRIEVE` as a read of that store into the `INTO` operand, with the
   usual `EIBRESP` writeback via `emit_resp_writeback` (`strategy.py:277`).

Two caveats worth building for rather than discovering later. First, `START` in real
CICS is *asynchronous* — it queues a task and the issuing task continues to its
`RETURN`. Modelling it as a terminal dispatch is only sound while every `START`
precedes a `RETURN`, which held for every program surveyed but is not guaranteed;
assert it and abend loudly if a `START` is followed by more work. Second, a program
may issue several `START`s on different branches; the store must be keyed by
`TERMID`, not global.

`RETRIEVE` is separately avoidable for bring-up: every program surveyed guards it
behind `IF EIBCALEN = 0`, so entering with a non-empty COMMAREA skips it. Useful for
getting a flow running, not a substitute for the verb.

### Fix shape for the policy itself

Make the fallthrough loud. Options, roughly in order of preference:

* An `unsupported_verbs` strictness setting: raise at lowering time by default,
  warn only when a caller opts in.
* Failing that, emit IR that abends at runtime with the verb name, so the failure
  lands where the program actually depended on it rather than vanishing.
* At minimum, surface the accumulated set of skipped verbs on the compile result
  so a caller can assert on it. A `logger.warning` on a shared logger is not
  something a harness can reliably check.

The same argument applies to `lower_search`'s silent non-advance and
`lower_expr_node`'s literal coercion. **A component that cannot do something should
say so in its return value, not only in a log line.** All six defects here share
that shape, and it is the one fix that would have prevented all of them.

---

## Defect F — `HANDLE CONDITION` is a no-op, and no condition is ever raised

Two halves that compound.

**Registration is discarded.** `strategy.py:56-61`:

```python
    # HANDLE CONDITION / HANDLE AID are explicit no-ops for now — the real
    # runtime-dispatch machinery is a deferred follow-up
    # (docs/superpowers/plans/2026-06-07-cics-handle-condition-machinery.md).
    "HANDLE CONDITION": "__cics_handle_condition",
    "HANDLE AID": "__cics_handle_aid",
```

`cics/builtins/system.py:188-197` logs at INFO and drops the condition→label pairs.

> The referenced plan file does not exist in this repository —
> `find . -name "*handle-condition*"` returns nothing. Either it was never
> committed or it lived somewhere that did not survive the monorepo migration.
> Whoever picks this up will need to rewrite it; do not go looking.

**Nothing raises a condition in the first place.** `emit_resp_writeback`
(`strategy.py:277-293`) writes the response code into `EIBRESP` and the `RESP(name)`
field, and that is all. No branch, no abend, no signal. `NOHANDLE` appears nowhere
in `strategy.py` — which is at least self-consistent, since every verb already
behaves as if `NOHANDLE` were coded.

Real CICS, on a non-`NORMAL` condition with no `RESP`/`NOHANDLE`, transfers control
to the registered `HANDLE CONDITION` label, or abends the task if none is
registered. Here, execution continues to the next statement with whatever was in
the target area before the failed operation.

So a program whose entire error strategy is `HANDLE CONDITION MAPFAIL(...)`
proceeds *through* the failure, on stale data, silently. The corpus's error paths
are written this way throughout.

### Blast radius

**2,679 `HANDLE CONDITION` occurrences across 1,599 of 2,137 programs — 75%.**
Plus `IGNORE CONDITION` at 820 occurrences, which is unimplemented (defect E) and
whose *actual* semantics — "revert to no handler for this condition" — are
currently the universal behaviour anyway. `HANDLE AID` adds 10 more.

This is the largest-radius defect in the document. It is listed last only because
it needs the most design: condition raising, a per-task handler table, and
label-targeted control transfer out of a builtin, which the IR must be able to
express.

Sequencing note: implementing raising **before** handler dispatch will convert a
large number of currently-silent wrong answers into abends. That is an improvement
in truthfulness, but it will look like a regression in any pass/fail count. Land
both together, or expect the noise and say so up front.

---

## Also known, not re-verified here

* **`AlternateKeyDriver` is read-only.** `vendor/red-dragon/interpreter/cobol/file_drivers.py`
  raises `NotImplementedError("alternate-key datasets are read-only point lookups")`
  on every write verb. Whether it bites depends on which programs write through an
  alternate-index path; not measured.
* **No CSD.** `run_carddemo_region` (`cics/bootstrap.py:61`) requires exactly one of
  `transid_to_program=` or `csd_path=`. A corpus arriving without a CSD needs the
  mapping synthesised. Only matters at composition time; a single-program region
  can pass the dict directly.

## Suggested order

Dependencies first, then radius.

1. **B** — unify the two lowerers' unknown-name policy. Smallest change, and it
   makes A and C visible instead of silent. Do this first even though it fixes no
   program: it converts everything below from a wrong answer into a diagnosable
   one.
2. **A** — allocate index items. Bridge → ASG → layout. Unblocks C1.
3. **D** — `SET ... TO <data-item>`. Must land with or before A, or A turns a
   masked defect into an active one.
4. **C2/C3** — real `OCCURS` bound and bounds checking. Independent of A; fixes
   the false-hit-past-end and the >256 blind spot on their own.
5. **C1** — implicit index advance. Needs A.
6. **E, `START` + `RETRIEVE`** — the flow-control blocker. Options are already
   parsed; the work is `DispatchKind`, routing, and a start-data store.
7. **E, policy** — make unimplemented verbs loud, ideally in the return value.
8. **F** — condition raising and `HANDLE CONDITION` dispatch. Largest radius,
   largest design, and it needs a plan document rewritten from scratch.

Steps 1–5 are all in `vendor/red-dragon`; 6–8 are all in `cicada`. They can proceed
in parallel by two people without touching the same files.
