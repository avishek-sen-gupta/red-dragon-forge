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

## #4 Non-UTF-8 members — FIXED

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

**Root cause: five strict decode sites, not three.** An earlier draft of this
entry listed three. Grepping every decode in `cobble/` while implementing found
two more, both reading corpus members:

| site | was | now |
|---|---|---|
| `cobol_parser.py:82` | `source.decode("utf-8")` before bridge stdin | `decode_source(source)` |
| `cobol_parser.py:104` | same, in `parse_to_file` | `decode_source(source)` |
| `build_graph.py:92` | `path.read_text()` — locale default, JCL | `decode_source(path.read_bytes())` |
| `corpus_index.py:95` | `parse_jcl(path.read_text())` | `decode_source(path.read_bytes())` |
| `build_graph.py:265` | `csd_file.read_text()` | `decode_source(csd_file.read_bytes())` |

The two extra sites fail differently from the first three, which is why they were
missed: both sit inside a per-file `try/except`, so they never aborted anything.
They dropped the member and logged a warning — `CorpusIndex: JCL <name> failed to
parse: 'utf-8' codec can't decode byte 0xa6` — leaving every job, step and dataset
in it unresolvable later. Silent degradation, not a crash.

**Fix.** One shared helper, `cobble/interpreter/cobol/source_text.py`:

```python
def decode_source(raw: bytes) -> str:
    return raw.decode("latin-1")
```

It lives under `interpreter` so `cobble.interpreter` stays a leaf that imports
nothing else in cobble (the `interpreter-is-leaf` contract), which it would have
lost had the helper gone top-level. `build_graph` and `corpus_index` reach in.
`lint-imports` is unchanged by this: 3 kept, 1 broken — the same pre-existing
`consumer-independence` break via `corpus_index`.

latin-1 is the byte-identity codec: defined for all 256 byte values, so it never
raises and never loses a character. One byte stays one character, so fixed-format
column positions hold and `PIC` lengths are unaffected.

**The wire to the bridge has to use the same codec, and for a while it did not.**
An earlier version of this paragraph said the bridge was safe because "Python's
`subprocess` encodes the `str` to UTF-8 for stdin and Java decodes it back with
`StandardCharsets.UTF_8`". That was true when it was written and stopped being
true when the bridge was resynced with red-dragon: `Main.SOURCE_CHARSET` is now
`ISO_8859_1`, `Main` no longer decodes stdin at all (`System.in.readAllBytes`
straight into the temp file), and ProLeap reads that temp file as ISO-8859-1. So
a UTF-8 wire turned one `0xA6` into `0xC2 0xA6`, ProLeap saw two characters where
the member had one, and every column right of it shifted:

```
member line: terminating period in column 72
as ProLeap read it: column 73 -- outside the code area, truncated away
```

The entry then never terminates and the next line's `FILLER` arrives as
`extraneous input 'FILLER'`, a syntax error hundreds of lines from anything
malformed. It cost the one member with code-area high bytes, and because
`AstStore.parse_all` re-raises out of `future.result()`, that one member aborted
the whole corpus run.

`RealSubprocessRunner` now names latin-1 as the subprocess `encoding` rather than
asking for text mode and letting the locale choose, so the wire is byte-identity
both ways, matching `decode_source` on this side and `SOURCE_CHARSET` on the
bridge's. The return path needed it just as
much: `Main` pins its stdout to `SOURCE_CHARSET`, so a high byte in a `VALUE`
literal comes back as a raw `0xA6`, which a locale-encoded read rejects outright.
The locale default round-tripped only by coincidence, on the days both ends
happened to be UTF-8.

**One site deliberately left strict.** `cobble/jackal/jcl/proc_expand.py:116`
(`parse_proc(proc_path.read_text())`) reads PROC members. Fixing it would cost
`cobble.jackal` its leaf status — it too imports nothing else in cobble today —
and the site is latent in both corpora: the production config declares no
`proclib_dirs` at all, so `expand_procs` is never called, and CardDemo's two PROC
members are pure ASCII. A corpus with a high byte in a PROC needs this fixed, and
then the placement question reopens. Until then the `UnicodeDecodeError` it raises
is at least caught: `CorpusIndex._expand` reports the member and carries on rather
than aborting the index build (see the index-failures section).

**Sites left tolerant-but-lossy**, unchanged on purpose to keep the diff about
this blocker: `cobol_imports.py:99`, `build_graph.py:187` and `cics/csd_parse.py`
(twice) all pass `errors="replace"`. They never raise, so no member is lost; they
would corrupt a high byte to `U+FFFD`, which does not affect what any of them
extracts (COPY/CALL names, `DEFINE` statements).

**Tests.** `tests/interpreter/cobol/test_source_text.py` pins the codec: all 256
bytes round-trip, `0xA6` → `¦`, one byte stays one character at the same index,
and `b"\xa6\xa6"` — the sequence that raised — decodes. `test_cobol_parser.py`
covers both bridge sites through the existing `RecordingRunner`, asserting the
runner receives `U+00A6`. `test_corpus_index.py` covers the silent-drop site: a
JCL member with `0xA6` in a `//*` comment now reaches `parse_jcl` and its job
resolves. `build_graph.py`'s two sites are pure one-line substitutions with no
branching; that module has no test harness at all, and building one is separate
work, so their correctness rides on `decode_source`'s own tests.

**Measured payoff.** JCL, all 58 high-byte members through cobble's own path:

```
48  OK  (270 steps recovered)
10  blocker #6 — mismatched input 'EXEC'/'DD', statement group closed early
```

Previously all 58 were lost. (The 601/860 baseline under #6 came from a standalone
harness that decoded permissively, so it already counted these members — the loss
was cobble's, not the grammar's. The #6 fix has since cleared those 10 too.)

COBOL, all 52 high-byte members: the decode wall is gone, and what they hit next
is not this blocker. Before the fix, a single one of them inside
`_build_batch_file_graph` aborted the entire 3779-member run — the
`UnicodeDecodeError` was raised in a worker thread and re-raised by `fut.result()`
inside `parse_all` (blocker #3). Probed individually with the batch parser now:
5 parse, 44 raise `Copybook not found` (they need `make sym` first — a separate
open item), 3 raise `Unknown COBOL statement type: 'EXEC_CICS'` because the probe
handed CICS members to the batch parser, which is a harness artifact rather than a
cobble defect.

CardDemo is unaffected: `make compare` is still an empty diff at 449 nodes / 803
edges.

**Caveat to keep in mind.** This is a decode choice, not a codepage claim. A
genuinely EBCDIC member would come through as silent garbage instead of raising.
Measured: all 110 are ASCII with a handful of high bytes, hence ASCII-compatible
and not EBCDIC. A future EBCDIC corpus needs detection, not this helper.

---

## #5 `DISP=(,PASS)` — omitted positional subparameter — FIXED

**`DISP=(,PASS)` is correct JCL.** `DISP=(status,normal-disp,abnormal-disp)` is
positional; omitting the status defaults it to `NEW`, so `(,PASS)` means
`(NEW,PASS)`. `PASS` hands the dataset to a later step in the same job.

**It was never a grammar failure.** An earlier ledger entry attributed this to
the JCL grammar. Measured with the real jar:

```
DISP=(,PASS)      FAIL 'PASS' is not a valid DispStatus — output: '{"name":"TESTJOB","steps":[{...
DISP=(NEW,PASS)   OK
```

The ANTLR parse succeeds and the emitted JSON is well-formed. The failure was on
the Python side, after the bridge.

**Measured shapes** across the 12,833 parenthesised `DISP=(...)` occurrences in
the 860 members:

```
10535  DISP=(X,X)     in 657 members
 1574  DISP=(_,X)     in 327 members   <- raised
  687  DISP=(X,X,X)   in  88 members
   37  DISP=(_,X,X)   in  11 members   <- raised
    0  DISP=(_,_,X)
    0  DISP=(X,_,X)
```

1611 raising occurrences across **328 of 860** members. Note the two zeros: no
member omits two leading slots, and none omits an inner slot — so this corpus
never exercised the mis-slotting the old serializer would have done silently.

**Root cause.** Positional structure was discarded at the JSON boundary. The
serializer collected `keywordOrSymbolic` nodes recursively and dropped empty
text, so an omitted slot left no trace:

```
DISP=(,PASS)            -> ["PASS"]           indistinguishable from DISP=PASS
DISP=(NEW,,DELETE)      -> ["NEW","DELETE"]   silently read as (NEW,DELETE)
```

The first raised `'PASS' is not a valid DispStatus`. The second is worse and the
earlier analysis missed it: it does not raise, it shifts, so the abnormal
disposition is read as the normal one. Zero occurrences in this corpus, but it
was wrong for any corpus that has them.

**Fix, three parts.**

*`JclSerializer.extractWords`.* Now splits the `singleOrMultipleValue` node's
terminals on `COMMA`, skipping `LPAREN`/`RPAREN`, and emits one array entry per
positional slot — empty or not. The comma tokens are the only record of position,
so they are what gets read; a `keywordOrSymbolic` collection cannot express a gap.
Flattening to terminals rather than walking direct children also makes it
independent of which `singleOrMultipleValue` alternative the parser chose:
`(,PASS)` matches the `parenList` alternative and `(NEW,,DELETE)` does not, and
the two put their keywords at different depths.

```
DISP=(,PASS)            -> ["", "PASS"]
DISP=(NEW,,DELETE)      -> ["NEW", "", "DELETE"]
DISP=(NEW,CATLG,DELETE) -> ["NEW", "CATLG", "DELETE"]
DISP=SHR                -> ["SHR"]
DISP=(SHR)              -> ["SHR"]
no DISP=                -> []
```

DISP is `extractWords`'s only caller, so this cannot disturb any other DD
parameter. A value with nested parentheses or an embedded equality (the `PARM=`
shapes) would have its inner commas counted as separators; DISP cannot contain
either.

*`bridge_parser._disp_from_words`.* Treats `""` as omitted and applies the z/OS
positional defaults. **The defaults are chained, not a fixed triple** — an
earlier draft of this fix had the normal disposition defaulting to a flat `KEEP`,
which is wrong. It defaults to `DELETE` for a data set the step creates and
`KEEP` for one that already existed, and the abnormal disposition defaults to
whichever normal disposition resolved.

`MOD` is read as already-existing. It can be either — `MOD` creates the data set
when absent and appends when present — and JCL alone cannot say which. Only
`status` reaches the graph, so the choice affects the model's fidelity and no
edge.

*The `_DEFAULT_DISP` constant is gone.* It held `Disp(SHR, KEEP, KEEP)` for a DD
with no `DISP=` at all, where z/OS says `(NEW,DELETE,DELETE)`. With the chained
defaults that case needs no special handling: no words → status `NEW` → normal
`DELETE` → abnormal `DELETE`, by the same rule. One rule replaced a rule plus a
contradicting constant.

**Tests.** `tests/jackal/test_bridge_parser.py` covers the seven default
combinations in pure Python. `jcl-bridge/src/test/java/org/jackal/jcl/JclSerializerTest.java`
is new, and so is jcl-bridge's junit dependency — the module had no test
infrastructure at all. `JclSerializer.serialize(String)` was extracted out of
`main` so a test can state a JCL snippet and read the JSON the Python side would
receive, exercising the real grammar rather than a hand-built parse tree. It runs
under `mvn test`, not `make test`, which stays JVM-free.

**Graph payoff, measured.**

- The 1611 `(_,X)` / `(_,X,X)` DDs across 328 members went from killing their
  member outright to resolving as `NEW`, which `jcl_graph._DISP_TO_EDGE_KIND`
  maps to `WRITES`.
- The `_DEFAULT_DISP` correction moves 1016 DDs across 133 members from `READS`
  to `WRITES` — those are DDs with a `DSN=` and no `DISP=` at all. CardDemo has
  zero such DDs, which is why the 449/803 identity diff stayed empty.

---

## Silently skipped index members — FIXED

Found while fixing #4, and it is the reason that entry undercounted its own decode
sites. `CorpusIndex._index_jcl_file` and `_index_csd_file` each wrapped their parse
in `except Exception`, logged a warning and returned. Two separate defects:

- **`except Exception` filed cobble's own bugs as corpus shape.** An
  `AttributeError` in the indexing code was indistinguishable from a member that
  genuinely does not parse, and both produced "skipped, carried on".
- **The skip never reached the report anyone reads.** `logging.basicConfig(level=
  WARNING)` does put the line on stderr, but `CorpusIndex` had no access to the
  `failures` list, so the run ended with `N failure(s)` counting only
  graph-building failures. A member missing from the index takes its jobs, steps,
  instream data and transactions with it, and every later reference to those
  resolves `UNRESOLVED` — with nothing in the summary to say why.

**The strongest evidence is an accident.** A new test that indexed a real JCL file
failed with `KeyError: 'JCL_BRIDGE_JAR'`. That env var is set by the Makefile, so
running cobble any other way made *every* member "fail to parse" — 860 corpus-shape
failures reported for one unset variable, and a run that still claimed success.
The old handler could not tell the two apart. This one could not have been found by
reading the code; it fell out of narrowing the catch.

**Fix.** Both handlers narrow to the corpus-shaped failures only —
`(JclParseError, OSError)` and `(CsdParseError, OSError)` — so anything else
propagates. `CorpusIndex.failures` exposes the skips as a tuple of strings, and
`build_graph.main` folds them into the run's own `failures` list right after the
index is built, so they appear in the same end-of-run report.

`CsdParseError` is new in `cobble/cics/csd_parse.py`: `parse_csd` and
`parse_csd_files` now wrap lark's `UnexpectedInput`, which is what a malformed CSD
actually raises. Without it there was no type to narrow to, and a consumer would
have had to import lark to catch it. This mirrors `pic_parser.py:119`, which
already converts `UnexpectedInput` into a domain error.

**Deleting the handlers outright was considered and rejected on the measurement.**
259 of 860 members failed JCL parse on #6 at the time, so an unguarded index would
abort before any graph work and the production run would produce no output at all
(#6 has since landed and cut that count sharply). Skip-and-report also matches
what `build_graph` already does per member; the defect was never that it skipped,
it was that it skipped quietly and lumped bugs in with corpus shape.

**Two gaps closed afterwards.** `expand_procs` ran *after* the guarded block, so
one unbound symbol, one circular PROC reference or one `.prc` file that is not
valid UTF-8 aborted the whole index — and every member after it was never indexed.
It is now `CorpusIndex._expand`, guarded on
`(ProcExpansionError, JclParseError, UnicodeDecodeError, OSError)`. The outer job
parsed, so on failure its own steps stay indexed *unexpanded*: those are exactly
what the JCL states, and the PROC's inner steps are lost from the graph too since
the JCL extractor expands through the same function.

`build_graph._load_transid_to_program` had the same shape — `parse_csd` unguarded,
called before the writer opens, so a malformed CSD killed the run outright while
`CorpusIndex._index_csd_file` guarded that very same file two calls later. Now
guarded per file, reporting into the same list.

**The report is loud.** It was a quiet `print` on stdout after `Wrote …`, trivially
scrolled past on a corpus where 62 members are missing from a graph whose printed
counts look finished. `_report_failures` now writes a ruled block to **stderr**
saying `N FAILURE(S) -- THIS GRAPH IS INCOMPLETE`, then a tally by category, then
the lines. The tally is the part a reader acts on: 62 detail lines hide the shape,
`54 index JCL` does not. Exit code stays 0 — the run did what it could, and a
non-zero exit would break callers that legitimately tolerate a partial corpus.

**Measured.** Indexing the production corpus reported 259 skipped members at the
time — the same failures as #6, every one of them a `mismatched input ... expecting JOB`
signature, with no `OSError` and no `CsdParseError` among them. That number was
previously absent from the run's summary entirely. CardDemo is unaffected:
`make compare` is an empty diff at 449 nodes / 803 edges, and its report still
shows the one pre-existing `CICS program COCRDSEC: not found` failure.

---

## #6 Bare `/*` delimiter line — FIXED

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
both beat the 2-character `SA`, so the token is produced correctly. Those are two
different `/*`: one that really terminates in-stream data is consumed in
`DATA_MODE` and reaches the parser as `DATA_MODE_TERMINATOR3` *inside* the DD it
belongs to, never as a `delimiterStatement`. Only an **orphan** `/*` — lexed in
`DEFAULT_MODE`, terminating nothing — becomes a `DELIMITER_STATEMENT` token.

### Root cause — the group is written twice, not looped

The earlier reading of this entry blamed tail-position placement and left the
mechanism labelled a hypothesis. The mechanism is now proven, and it is one level
more general. `JCLParser.g4:26-81` reduces to:

```
execJCL : jesExecutionControlStatements ( jobCard SEG ( SEG ) )+ EOF?
   where SEG = prologue* statements* nullStatement* jes2CntlStatement* delimiterStatement*
```

`delimiterStatement` appears only at the end of `SEG`, and `SEG` is **spelled out
twice rather than starred**. Two segments per job means two tails, so one job
tolerates exactly **one** interior delimiter boundary. The second one closes the
job, and the enclosing `( … )+` restarts wanting a fresh JOB card — reported at
the next statement as `mismatched input 'EXEC' expecting JOB`. Nothing in the
message mentions `/*`.

**Six lines reproduce it**, against the unpatched grammar:

```
0 interior /*   OK
1 interior /*   OK
2 interior /*   FAIL  line 6:10 mismatched input 'EXEC' expecting JOB
3 interior /*   FAIL
```

That is why every earlier synthetic parsed cleanly: each had at most one interior
boundary. The break has nothing to do with long token streams or ANTLR's adaptive
prediction — that theory is withdrawn.

**Confirmed at corpus scale.** A line-level model of the lexer's modes, counting
maximal runs of orphan `/*` that still have a step after them, predicts the
failure over all 860 members at tp=246 fp=12 fn=12 tn=579. The 24 misses are the
model's continuation and `DLM=` handling, not the mechanism.

### The signature count was wrong

This entry used to claim "one signature, no others" and put the failure count at
259. That came from a sweep printing only its six commonest signatures. The full
tally over 860 members is **260** failures: 252 carry the `expecting JOB`
signature, 7 carry other signatures, and 1 member never returns (see below).

### Fix

`| delimiterStatement` added to the mid-job statement alternation in both copies
of `SEG` (`JCLParser.g4:49-53`, `:75-79`). Four lines. The rule and the token both
already existed; the grammar simply now lists the rule in one of the two positions
z/OS permits.

```
baseline: 601 members parse, 5253 steps
patched:  789 members parse, 10075 steps
transitions: 601 stay OK, 188 newly parse, 0 regress
```

Both jars ran over every member in the same pass, 6 at a time with a 150s cap.
That cap is why 789 understates the fix: uncapped and serial it is 798 — see
*What is left* below.

+188 members, and the corpus's step count nearly doubles. `DelimiterStatementTest`
covers the ladder plus the in-stream case; that last test passes unfixed, which is
the point — it pins the boundary between the two kinds of `/*`.

Preprocessing was rejected on the merits, not on taste: when `/*` genuinely
terminates in-stream data the lexer consumes it as `DATA_MODE_TERMINATOR3` and the
parser never sees a token, so a text-level stripper would have to re-implement
`dlmVals` and `DATA_MODE` tracking to know which lines are safe to delete — and a
custom `DLM=` means the delimiter is not `/*` at all.

### The same defect for `nullStatement` and `jes2CntlStatement` — measured, left alone

`nullStatement` and `jes2CntlStatement` sit in the same tail and inherit the same
one-per-job allowance. Two mid-job `//` null statements fail; two mid-job
`/*ROUTE` statements fail; both with the identical message. So the defect is real
and general.

Adding all three to the alternation measured **worse** than adding only
`delimiterStatement`: 787 members and 9916 steps instead of 789 and 10075, one
member that previously parsed now exceeding a 150s parse budget, and not one of
the 54 residual failures below fixed. `nullStatement : SS` puts the token that
begins *every* JCL statement into a loop alternation, and ANTLR's prediction cost
for that outweighs what it recovers. Real defect, latent in this corpus — not
worth the grammar change until a corpus shows it.

### What was left: 62 members, five causes — four fixed, one is not our bug

The 789-of-860 figure above comes from the comparison sweep, which capped each
bridge at 150s while running 6 at a time and so charged its own contention to 11
members. Serial and uncapped, the honest number after the delimiter fix is
**798 of 860 parse, 62 fail**, and the index completes.

Every one of the 62 was pinned the same way: bisect the member by truncation to
the smallest failing `1..N` line prefix, then rebuild that prefix as a minimal
repro. Bisection was not optional. ANTLR reports all of these against the
position where `jclStep` *started* — the step's EXEC line, often dozens of lines
earlier — so the printed position says nothing about which parameter broke.

| cause | members | shape | verdict |
|---|---|---|---|
| B | 54 | bare `/*` between two DDs of **one step** | valid JCL — FIXED |
| D | 4 | omitted trailing positional: `SPACE=(CYL,(2,2,),RLSE)`, `UNIT=(SYSDA,3,)` | tolerated in practice — FIXED |
| A | 1 | `DCB=*.ddname` followed by a continuation card | valid JCL — FIXED |
| E | 1 | `PROC` with no parameters and a cols 73-80 sequence number | valid JCL — FIXED |
| C | 2 | empty keyword subparameter: `DCB=(RECFM=FB,BLKSIZE=)` | z/OS verdict unconfirmed — FIXED anyway |

**B — `/*` inside a step's DD list.** The #6 fix put `delimiterStatement` in the
mid-job alternation, which handles a delimiter *between steps*. `jclStep` listed
none at all, so a delimiter among a step's DDs ended the step's DD list, ended
the job with it, and `execJCL+` restarted wanting a fresh JOB card — surfacing at
the *next* DD as `mismatched input 'DD' expecting JOB`. One added alternative.
Only `delimiterStatement` is listed there, deliberately: `SS` is the token every
statement in that loop starts with, so a `nullStatement : SS` alternative would
compete with all of them, while `DELIMITER_STATEMENT` starts nothing else and so
decides the alternative on one token.

**D — omitted trailing positional.** `parenList` already allowed a positional to
be omitted at the front (`DISP=(,PASS)`) and in the middle
(`SPACE=(CYL,(2,,2),RLSE)`) but required a value after the last comma. One
trailing `COMMA*`. Unlike A, B and E this one is a tolerance rather than a
correction: IBM's documented way to omit a *trailing* positional omits its comma
too, so `(2,2,)` is what real systems accept rather than what the manual states.

**A — `DCB=*.ddname` then a continuation.** `DCB=` puts the lexer in
`DCB_MODE`. A *keyword* subparameter there (`DCB=(RECFM=FB,…)`) switches to
`KYWD_VAL_MODE`, which carries both continuation rules and so always worked. A
*bare* value — a backward reference `*.ddname`, or a model dataset name — is
consumed by `DCB_KEYWORD_VALUE` without leaving the mode, so the following comma
reached `DCB_COMMA : COMMA_DFLT ->more,popMode`: that folds the comma into the
next token and pops to `DD_PARM_MODE`, where what remains of the line matched an
end-of-statement rule and the continuation card became a new statement.
`DCB_MODE` now has the same `,\n` and `,`-then-blanks rules `KYWD_VAL_MODE` has.

The second of those is the one that mattered, and a first attempt shipped only
the first. Production cards are blank-padded to 80 columns, so the continuing
comma is followed by blanks and never reaches the newline — a `,\n` rule alone
fixed the synthetic repro and moved the member not at all. The repro had to be
rebuilt with padded cards before it reproduced what the corpus does.

**E — `PROC` with no parameters and a sequence number.** Columns 73-80 are the
identification/sequence field; the system ignores them and card-era members keep
a line number there. `PROC_MODE`'s `PROC_WS` assumed a parameter field always
follows the whitespace and went to `PROC_PARM_MODE`, where the digits hit
`ERROR_CHAR_PROC_PARM`: `mismatched input '0' expecting {COMMENT_FLAG, SS}`. A
`PROC` *with* parameters escaped this only incidentally — its `=` pushes
`PROC_PARM_VALUE_MODE`, which absorbs the trailing field already.

The fix keys on the column, not on absorbing whatever trails the statement, and
that distinction is load-bearing: a comment field is permitted only on a
statement that *has* a parameter field, so `//NAME PROC` with nothing after it
cannot be carrying one. A predicated rule recognises whitespace that runs to
column 73 and switches to a mode that swallows the rest of the card. mapa has no
sequence-field handling anywhere in its 104 lexer modes; every other member gets
away with it because its sequence number lands somewhere a value or comment is
already being absorbed.

**C — empty keyword subparameter value. FIXED.**

```
DCB=(RECFM=FB,LRECL=2000,BLKSIZE=)     both members, 3 cards
DCB=(BLKSIZE=,LRECL=80)                same shape, constructed
```

This entry previously read **"invalid JCL — WON'T FIX"**, on two arguments. The
first is unproven and the second is wrong.

*Is the form legal?* Unconfirmed. The IBM z/OS JCL Reference could not be
reached to settle it, and no secondary source consulted addresses a null value on
a keyword *sub*parameter. It is worth being explicit that the earlier verdict was
an inference stated as a fact. What is settled is that this is not the one null
form that is unambiguously legal — symbolic parameter nullification (`//P PROC
BLK=`, `// EXEC P,BLK=`) — because the raw cards put it inside a DD's `DCB=(...)`.

The typo reading still looks right, and is now measured: **3 occurrences against
2193 `BLKSIZE=0` and 2566 numeric `BLKSIZE=` corpus-wide**, in two members that
write `BLKSIZE=0` themselves 4 and 6 times. One has
`DCB=(BLKSIZE=0,LRECL=3300,RECFM=FB)` a few cards above the card that failed.
A dropped `0`.

*Does that justify rejecting the member?* No, and this is what overturned it.
The old reason was that cobble "would have to invent a block size, a claim about
the data set the JCL does not make." cobble records no block size at all:
`BLKSIZE` appears nowhere in the Python, and `JclSerializer` emits no `DCB`. The
whole DCB subtree is parsed and discarded. So accepting a null value invents
nothing and discards nothing extra — the justification described a risk that does
not exist. Rejecting the members cost **37 steps / 168 DDs and 19 steps / 73
DDs** of real graph content to enforce a rule about a field that is thrown away.
cobble is an analysis tool, not a JCL validator; a typo in a discarded field is
not a reason to lose the job.

The lexer already permitted this deliberately — `KYWD_VAL_MODE` carries
`KYWD_VAL_COMMA` and `KYWD_VAL_RPAREN` so that `DATACLAS=` and `COPIES=,` lex,
and its comment says exactly that. Only the parser rule disagreed, so the fix is
the grammar's own idiom for a nullable keyword applied to one more rule:

```
ddParmBLKSIZE : BLKSIZE EQUAL keywordOrSymbolic? ;
```

`keywordOrSymbolic` itself is **not** loosened, and neither is any rule whose
value cobble uses. A null `DSN=` would be a real loss of information, since
dataset edges are built out of it.

### Where the corpus ended up

Five grammar commits, each measured over all 860 members with the *only*
difference being the jar, and each requiring not just more members parsing but
**zero regressions and zero changes to any member that already parsed** — no
member's step count, DD count or program list moved:

| | parsed | failed | steps | DDs |
|---|---|---|---|---|
| after #6 (delimiter between steps) | 798 | 62 | 11114 | 59320 |
| + B (delimiter inside a step) | 852 | 8 | 11587 | 61378 |
| + D (omitted trailing positional) | 856 | 4 | 11695 | 61910 |
| + A and E (DCB continuation, PROC sequence field) | 858 | 2 | 11701 | 61940 |
| + C (null keyword subparameter value) | **860** | **0** | **11757** | **62181** |

The corpus parses whole. The last row's step and DD deltas — 56 and 241 — are
exactly the two recovered members' own counts (37 + 19, 168 + 73), which is the
zero-regression check for that row: nothing that already parsed moved. Every fix
is one or two lines and all five are upstreamable to mapa.

CardDemo is unaffected throughout: `make compare` is an empty diff at 449 nodes /
803 edges. 39 jcl-bridge Java tests and 241 pytest tests pass.

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
- **`clean` does not remove per-corpus output directories.** `make clean` names
  `out cache sym` literally, so a corpus configured with `out_dir: out-<name>` or
  `sym_dir: sym-<name>` leaves both behind. `.gitignore` half of this is done —
  it now carries `out-*/` and `sym-*/`, so per-corpus output cannot be committed
  by accident — but the `clean` target still only knows the defaults.
- **The online members need `make sym CONFIG=<corpus>` first**, otherwise every
  one of them fails with `Copybook not found`.
- **Empty-copybook synthesis** to get past `Copybook not found` for copybooks
  absent from the corpus entirely. Deferred by decision, not by oversight.

---

## Bridge parse time blew up on large members — FIXED

Screening all 860 JCL members with 8 bridges at once, 114 exceeded 20s — but most
of that was the screen's own CPU contention. Re-run **one at a time**, 113 of the
114 completed: mostly tens of seconds, slowest 599s. One member (3317 lines) was
still running at 900s. Cost was steeply superlinear in line count and not
monotonic in it — 2843 lines in 105s while 2537 lines took 599s — so member size
was a correlate, not the cause.

**Root cause: full-context LL prediction on the top-level alternative.**
`jcl : (execJCL+ SS?) | (procJCL SS?)` is decidable only from deep inside the
member, and under ANTLR's default `LL` prediction the cost of carrying that
decision grows at roughly O(n^1.8) in input size.

**Fix: the two-stage parse from ANTLR's own `TestPerformance`.** SLL prediction
with `BailErrorStrategy` first, full LL only if SLL bails. SLL decides the same
alternatives without the full-context work whenever the input is unambiguous,
which is every member that is valid JCL. The LL stage is configured exactly as
the single-stage parse was, so a member SLL cannot decide gets the same tree and
the same error text as before.

**Measured, same jar except for this change:**

| member | before | after |
|---|---|---|
| median, 10 KB | 2.04s | 0.54s |
| p90, 46 KB | 25.66s | 0.71s |
| largest, 262 KB | never completed | 2.19s |

Nine members never returned from the bridge at all; all nine return now. This is
a speed change only, and the sweep proves it: 798 members parsed before and 798
after, with no member's output altered.

**What the remaining wall-clock is, now that parsing is not it.** A full 860-member
sweep is ~150s, of which the actual parse work is ~1.0s per member. Two costs
dominate what is left, and neither is in the parser:

- **301s of CPU (26%) is JVM startup** — 860 process launches at ~0.35s each.
- **Each member is parsed twice per run** — once building the corpus index, once
  building the graph. Roughly a 2× on everything.

The 4-way parallelism configured for `build_graph`'s JCL passes is not actually
used, which is a third. All three are open items; none of them is a grammar or
prediction problem.

One consequence of the original blocker stands unfixed: cobble never times the
bridge subprocess out, so a member that does hang makes a run look stuck with no
diagnostic. Any timeout added has to be a *reported* skip (see the index-failures
entry), not a silent one.

---

## Fixed

Fixes are named by what they changed rather than by commit SHA: this history has
been rewritten, so any SHA recorded here would be stale. `git log --grep` on the
description finds the commit.

- **#1, #2** — earlier sessions.
- **`ALTERNATE KEY` grammar** — added to the ProLeap fork's
  `alternateRecordKeyClause`; cobble tracks it through the submodule pin.
- **`PIC X(8)B(3)`** — `pic_parser` now accepts a `B` (blank-insertion)
  character in a PICTURE string.
- **Bare `/*` closed the job early (#6)** — `delimiterStatement` reached only the
  tail of a statement group that `execJCL` spells out twice instead of looping, so
  a job allowed exactly one interior `/*`. Added to the mid-job alternation:
  601 -> 798 of 860 members parse, 5253 -> 10075 steps, no regressions.
- **Bare `/*` inside a step's DD list** — `jclStep` listed no
  `delimiterStatement` at all, so a delimiter among a step's DDs ended the step,
  the job, and the parse: 798 -> 852 of 860. The commonest single defect in the
  corpus, 54 members.
- **Omitted trailing positional subparameter** — `parenList` required a value
  after its last comma while already allowing leading and middle omissions:
  852 -> 856 of 860.
- **`DCB=*.ddname` lost its continuation card** — `DCB_MODE` had neither of the
  two comma-continuation rules `KYWD_VAL_MODE` has, so a bare DCB value ended the
  statement instead of continuing it.
- **`PROC` with no parameters and a cols 73-80 sequence number** — `PROC_MODE`
  assumed whitespace is always followed by a parameter field; the sequence digits
  became a parameter name with no value. With the DCB fix, 856 -> 858 of 860.
- **Null keyword subparameter value** — `ddParmBLKSIZE` required a value the
  lexer already allowed to be absent, and that cobble never records. 858 -> 860
  of 860.
- **Bridge parse time superlinear in member size** — SLL-then-LL two-stage parse
  in `JclSerializer`. p90 member 25.66s -> 0.71s, largest member never completed
  -> 2.19s, nine members that never returned now all return, output identical.
- **`EXEC SQL` aborts the program** — `parse_statement` raised
  `Unknown COBOL statement type: 'EXEC_SQL'` with only Cicada's dialect parser
  registered; `cobble/sql/` now ports Squall's parse-time `DialectParser` and
  `verb_source_asg.asg_dialect_parsers()` registers both.
