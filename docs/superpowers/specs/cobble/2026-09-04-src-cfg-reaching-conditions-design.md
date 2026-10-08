# Source CFG with reaching conditions and primitive data dependencies

*2026-09-04 — design for NO-TICKET*

## Why

`cobble` already has a dependency graph over a parsed corpus: `cobble-depgraph`,
146,525 nodes and 588,398 edges, built from `MOVE`-family data movement. It answers
one question — which statement copies which field into which — and field-provenance
work needs two more that it cannot answer at all.

**Under what conditions.** Control dependence is not an edge in that pass, so a
field appearing only in a guard is absent from the graph. Measured on one target
field: of the 128 nodes whose names mention a field that supplies half of a
two-clause guard on that target, **zero** appear in the target's backward closure.
The dependency is real, sits three lines away in the source, and the graph does not
have it.

The same omission makes closures unusable. A backward closure over one target field
reaches 24,459 nodes across 28 depths — 17% of the whole graph — because the field
is a hub and no edge carries a condition to prune with. Conditions are not decoration
on a dependency graph; they are the only thing that makes a closure small enough to
read.

**Across programs.** Every dependency stops at a `LINK`, `XCTL` or `CALL`. In a CICS
corpus that is most of them: 4,084 `LINK`/`XCTL` sites and 1,231 COBOL `CALL` sites
over 3,779 members, with the fields that decide a program's behaviour routinely
arriving in its commarea from a caller.

The construct at issue is ordinary, and shows both gaps in six lines:

```cobol
IF  WS-RESULT-CODE = SPACES OR LOW-VALUES
    IF  WS-FLAG-A = 'Y' AND WS-TYPE-B = 'G'
        MOVE 'F'        TO WS-RESULT-CODE
    ELSE
        MOVE WS-TYPE-B  TO WS-RESULT-CODE
    END-IF
END-IF.
```

`cobble-depgraph` records the two `MOVE`s and nothing else. What a reader wants is
the whole sentence: this literal is written *here*, when these three comparisons
hold, and each of `WS-FLAG-A` and `WS-TYPE-B` arrives from somewhere. The literals
matter as much as the field names — an artifact carrying guard *literals* can be
checked against an independently stated rule, and disagree with it, while one
carrying only field names cannot be checked at all.

So: a source-level CFG, with reaching conditions, primitive data dependencies, and
recursive expansion across program boundaries.

## What this builds

A per-program control-flow graph constructed by walking the cached ASG, carrying:

* **reaching conditions** — for any node, the guards that must hold to arrive
  there, with their literals;
* **primitive data dependencies** — flow-sensitive def-use edges, each tagged
  with the guards live at the definition and at the use;
* **cross-program expansion** — recursive through `EXEC CICS LINK`/`XCTL` and
  COBOL `CALL`, seeded at one CICS program.

## Decisions

### Nothing is compiled; the input is the existing ASG cache

`out-<corpus>-parsed/` holds 3,779 ASG JSON files, 557 MB, written by
`cobble-parse-corpus`. It needs no JVM to read and no corpus source. This pass
reads it and nothing else.

The alternative was lowering each program through
`cics.bootstrap.compile_cics_program` and taking its `merged_cfg`, which for one
172-paragraph CICS program is 1,646 real basic blocks. It was rejected on evidence.
Parsing that program succeeds in about 12 seconds with every copybook it references
present or stubbed; **lowering** then dies with

```
KeyError: "Field '<name redacted>' not found in any DATA DIVISION section"
```

at `interpreter/cobol/sectioned_layout.py:93`, because three of its 21 copybooks
are generated empty stubs. Corpus-wide, 318 of 3,043 distinct `COPY` names are
stubs, and 1,987 members reference at least one — roughly half. The stubs are
almost all foreign, belonging to neighbouring applications: the five largest
families contribute 40, 26, 22, 20 and 19 respectively, and only **three** stubs
belong to the application under analysis. The single most-referenced stub blocks
777 members on its own.

Filling them with placeholder layouts does make the program compile — 116,905 IR
instructions, 1,646 CFG blocks, 0 unresolved imports — but the placeholders invent
PIC widths, and invented widths are wrong in exactly the places static analysis
would consume them: `RIDFLD` and `KEYLENGTH` operands, `REDEFINES` aliasing, group
moves, and reference modification.

Parsing needs none of that. A stub costs only the *declarations* of a foreign
record, and reaching conditions do not need declarations.

Coverage is therefore total. The source tree holds 4,074 members and the cache
holds 3,779 ASGs; the 295 without one were checked individually and **none has a
`PROGRAM-ID` or a `PROCEDURE DIVISION`** — they are JCL and compile-proc members.
Every COBOL program in the corpus parses. The whole price of not compiling is not
knowing byte offsets, and "Crossing programs" is why that price is affordable.

### The ancestor walk was measured first, and it is not enough

Before designing a graph, the cheapest possible version of this analysis was built
and thrown away: one pass over the ASG cache accumulating the enclosing
`IF`/`EVALUATE`/`WHEN` chain as a guard stack, with no CFG at all. It produced
**779,712 guarded assignment records** across the 3,779 members, 65% of them
carrying a local guard, median 1 atom and p90 5, with zero unhandled statement
types. `PERFORM`-inherited guards, added by walking callers transitively through
range-expanded `PERFORM … THRU`, cost almost nothing: median 1 path per assignment,
p90 6, and 6 of 1,950 sampled hitting a 200-path cap. 528 of those 1,950
assignments carry no local guard but do inherit one, so inheritance is not optional.

Cheap as it is, it answered real provenance questions the `MOVE`-only graph could
not — which is an argument for building this design rather than for skipping it,
because it is wrong in four ways the CFG fixes by construction:

1. **`OR` collapses into the conjunction.** `= SPACES OR LOW-VALUES` comes out as
   both atoms joined by `AND`. Short-circuit `TEST` chains split it into two paths.
2. **The `ELSE` arm negates wrongly.** The else of `A AND B` is recorded as
   `NOT A AND NOT B` rather than `NOT A OR NOT B`. Same cause: no per-path split.
3. **`GO TO` is invisible.** A guard can be escaped by a `GO TO` out of an `IF`, so
   the recorded guard is both too strong and too weak, and paragraphs entered only
   by `GO TO` inherit no context at all.
4. **Nothing crosses a program.** Guards on commarea fields dead-end at the
   boundary, which in this corpus is where the deciding fields usually come from.

So the graph buys soundness and the `GO TO` tail rather than the basic capability.
Stating it that way sets the bar for v1: reproduce what the ancestor walk already
found, then be right about the four cases above.

### Two node kinds carry meaning; everything else is plumbing

| kind | payload | out-edges |
| --- | --- | --- |
| `TEST` | exactly **one atomic** predicate | exactly two: `true`, `false` |
| `ASSIGN` | `writes[]`, `reads[]`, `transfer` | one |
| `LABEL` | paragraph name | one |
| `CALL` | callee plus operand binding; its data effect is an attached `ASSIGN` | one, plus `link` |
| `NOP` | — | one or more (`CONTINUE`, `EXIT`, `JOIN`, program `ENTRY`/`EXIT`) |

All semantics live in `TEST` and `ASSIGN`. Every conditional construct in the
corpus desugars into `TEST` chains; every data-moving construct into `ASSIGN`.
The plumbing kinds hold no semantics and exist so branch targets and call
boundaries have somewhere to attach.

### `AND`/`OR` become short-circuit chains, so the CFG *is* the condition language

The ASG delivers conditions as a recursive tree, not text:

```
cond := {not, relation:{left:{kind,name,subscripts?}, op, right:{kind,value}}}
      | {not?, op:"AND"|"OR", left:cond, right:cond}
      | {not, class:"NUMERIC"|..., operand}
      | {not, condition:cond}
      | {not, condition_name:"WS-SOME-88-LEVEL"}
```

A compound condition is **not** flattened into one `TEST`. `AND` becomes
`TEST(left)` whose true-edge is `TEST(right)` and whose false-edge joins the else
branch; `OR` is the mirror. Every `TEST` therefore holds one atomic relation, and
the reaching condition of any node is *by construction* the list of
`(TEST, edge-polarity)` pairs along the path to it.

This removes the need for a separate predicate representation, a normal form, or
a solver. There was an open question about how to represent reaching conditions —
conjunction lists, a predicate tree with a simplifier, or Z3 — and canonicalising
to single-atom `TEST` nodes dissolves it. The condition language is the graph.

Short-circuiting is semantics-preserving here because COBOL relation conditions
have no side effects, and the corpus uses no `FUNCTION` intrinsics.

Contradiction detection (`WS-X = 'A' AND WS-X = 'B'` is unreachable) is deliberately
**not** in scope. It becomes a filter over an existing path, addable later
without touching the graph.

### Every conditional variant desugars; the corpus was surveyed to be sure

Counts are full-corpus over all 3,779 ASG files, not sampled.

| source construct | desugaring | count |
| --- | --- | --- |
| `IF c THEN a ELSE b` | `TEST(c)`: true to `a`, false to `b`, both to `JOIN` | 193,160 `IF`, 39.9% with `else_children` |
| `{op:"AND", left, right}` | `TEST(left)` true to `TEST(right)`, both false-edges to else | — |
| `{op:"OR", left, right}` | `TEST(left)` true to then, false to `TEST(right)` | — |
| `{condition: c}` (parenthesised) | transparent; recurse | — |
| `{class:"NUMERIC", operand}` | `TEST` with atom `CLASS(operand, NUMERIC)` | — |
| `{condition_name: X}` | resolve the 88-level from `data_fields`; a multi-`VALUE` 88 is an `OR` chain. Stub-owned owner leaves atom `COND-NAME(X)` tagged `UNRESOLVED` | — |
| `EVALUATE s / WHEN v1 / v2 / OTHER` | `TEST(s == v1)` false to `TEST(s == v2)` …; final false to `WHEN OTHER`, or `JOIN` if absent | 25,921 `EVALUATE`, 88,953 `WHEN`, 22,883 `WHEN OTHER` |
| `EVALUATE TRUE / WHEN c` | `TEST(c)` directly | 685 |
| `WHEN {kind:"dfhresp", condition:"NORMAL"}` | atom `EIBRESP == DFHRESP(NORMAL)`; the `EVALUATE` subject supplies the left side | — |
| `WHEN` bare string `"00"` | atom `subject == '00'` | — |
| `also_subjects` / `also_conditions` | `AND` chain within the one `WHEN` | — |
| `GOTO` simple | unconditional edge to `LABEL` | 32,262 |
| `GOTO` computed (`GO TO … DEPENDING ON`) | `TEST(idx == 1)` true to target 1, false to `TEST(idx == 2)` …; **final false-edge falls through to the next statement** | 14 |
| `PERFORM … THRU` | one conditioned `perform` edge per paragraph in range; see below | 153,948 |
| `PERFORM` paragraph, no `THRU` | one `perform` edge | 2,219 |
| `PERFORM … UNTIL c` | `TEST(c)` at loop head, false to body, true to exit, back-edge body to `TEST` | 6,986 |
| `PERFORM … VARYING v FROM a BY b` | `ASSIGN(v <- a)` before, `ASSIGN(v <- v + b)` at tail, plus the `UNTIL` `TEST` | 8,428 |
| `PERFORM n TIMES` | `ASSIGN(%times.k <- 0)`, `TEST(%times.k == n)` at head, `ASSIGN(%times.k <- %times.k + 1)` at tail | 13 |
| `PERFORM` inline (`children`) | same loop shapes; body is the inline block | 6,989 |
| `PERFORM … AFTER` | nested loops, same shapes | 4 |
| `READ … AT END / NOT AT END`, `INVALID KEY`, `NOT INVALID KEY` | the I/O `ASSIGN`, then `TEST(FILE-STATUS(f) == AT-END)` | 2,775 `READ.at_end`, 359 `not_at_end`, 39 `invalid_key`, 7 `not_invalid_key`; 42 `START.invalid_key`, 12 `REWRITE`, 2 `WRITE`, 2 `DELETE` |
| `SEARCH … WHEN … AT END` | loop plus `TEST` chain | 1,364 `SEARCH`, 1,338 with `at_end` |
| `GOBACK` / `STOP RUN` | edge to program `EXIT` | 2,379 / 1,698 |
| `CONTINUE`, `EXIT` | `NOP` | 20,109 / 77,172 |

Two cases are worth calling out because they are rare enough to be missed and
wrong enough to matter.

`GO TO … DEPENDING ON` (14 occurrences, ASG `{form:"computed", index, targets}`)
has a **fall-through** semantics that is easy to model as an error: an index of
zero or greater than the number of targets branches nowhere and execution
continues at the following statement. The final false-edge of the chain must go
there.

All 6,986 `PERFORM … UNTIL` are `test_before`, with zero `test_before: false`, so
the loop `TEST` sits at the head uniformly and no `TEST AFTER` variant is needed.

Absent from the corpus, so unhandled by construction rather than by omission:
`ALTER` (0), `NEXT SENTENCE` (0), `SORT`/`MERGE` (0), `EXEC CICS PUSH HANDLE` /
`POP HANDLE` (0).

### `HANDLE CONDITION` folds into the same two kinds

`EXEC CICS HANDLE CONDITION` (2,794) and `IGNORE CONDITION` (835) are non-local:
they arm a handler that fires from a later CICS call, possibly in another
paragraph.

`HANDLE CONDITION ERROR(ERR-EXIT)` becomes
`ASSIGN(%HANDLER[ERROR] <- 'ERR-EXIT')`. Every CICS node not carrying `NOHANDLE`
then gets a `TEST(EIBRESP != NORMAL)` whose true-edge targets the label read from
`%HANDLER[…]`. Which handler is live at a given call is answered by reaching
definitions over the synthetic field — the same machinery this pass already
builds for real fields. So `HANDLE` is an `ASSIGN`, dispatch is a `TEST`, and no
third construct appears.

`NOHANDLE` is present on 18,634 of 49,855 CICS calls, so more than a third get no
exceptional edge at all. `PUSH`/`POP HANDLE` being absent means `%HANDLER[…]`
needs no stack discipline, which makes the treatment exact rather than an
approximation; if one ever appears it is an `ASSIGN` to and from a shadow copy,
still within the two kinds.

The related idiom needs no special handling: of 25,921 `EVALUATE`s the subject is
`EIBRESP` in 17,000, an ordinary field in 8,236, and `TRUE`/`FALSE` in 685. Only
39 CICS calls carry an explicit `RESP` option, so `EXEC CICS READ … NOHANDLE`
followed by `EVALUATE EIBRESP` is overwhelmingly the corpus idiom — a CICS
`ASSIGN` writing `EIBRESP` and an ordinary `TEST` chain reading it.

### Paragraphs are shared nodes and `PERFORM` edges carry the condition

`PERFORM A THRU C` emits one `perform` edge to *each* paragraph in the range, and
every one of those edges is labelled with the reaching condition at the `PERFORM`
site. Paragraphs are not cloned: there is one node set per paragraph, with as
many conditioned in-edges as it has callers.

The alternative was cloning a paragraph per call path, k-limited. With 153,948
range-performs, the eager clone is a cost paid on every member to answer
questions asked of a few. Conditioned edges on shared nodes defer the same
precision to query time: a backward walk accumulates the edge labels along the
path it actually took, which is context-sensitive for the path being reported and
costs nothing for the paths nobody asks about.

Fall-through and return are separate, tagged edge kinds — `fallthru` from a
paragraph to its textual successor, `return` from a range end to the `PERFORM`
site's successor — so a walk inside an active range prefers `return` while one
that entered by `GOTO` can still fall through. Per-paragraph `perform` edges
over-approximate when a `GO TO` inside the range skips a paragraph; the
over-approximation is deliberate, since the failure to avoid is a lost edge.

### Crossing programs needs no byte offsets

At a `CALL` node the caller's `COMMAREA(X)` is aliased to the callee's
`DFHCOMMAREA` as one group-level edge. Flow then continues by ordinary `ASSIGN`:
the corpus idiom is for a called program to open with
`MOVE DFHCOMMAREA TO WS-COMM-AREA`, and from there every field arrives through
`MOVE`s the pass already tracks. No offsets are consulted.

Per-field positional joins matter only when caller and callee name the same bytes
with different layouts. Those edges are emitted tagged `APPROX`. They are never
dropped, because a silently missing edge is exactly how the guard-only field went
missing from the graph this pass replaces.

Foreign commareas are stubs — the most-referenced one appears in 409 members — so
cross-application hops resolve to a boundary and stop, which is the right answer:
the program on the other side is not in the corpus.

### Recursion is unbounded in principle and shallow in fact

Expansion follows `link` edges with a visited set. The call graph was measured
from the ASG cache before choosing this: 4,084 `LINK`/`XCTL` sites (4,079 `LINK`,
5 `XCTL`) plus 1,231 COBOL `CALL` sites over 163 distinct operands. Only 38
`PROGRAM` operands are variables, across 9 distinct names. Together they yield
4,145 literal-target edges to 426 distinct targets, 331 present in the corpus and
95 foreign.

Reachable-set size over all 3,779 seeds: **maximum 35 programs, p90 of 4, median
of 1**, with the deepest seeds reaching 29 programs at a maximum depth of 2. So
there is no fixpoint to compute and no scaling risk; a visited set is the whole
story.

The 38 dynamic `PROGRAM(WS-x)` operands are out of scope for v1. They are
recoverable later from a `VALUE` clause or a literal `MOVE` — several are named
after their target — and until then each is a boundary, reported as
`UNRESOLVED-TARGET` rather than a missing edge.

### Statement identity is a path, not a line number

No ASG statement carries a line number; this was verified across the cache and
the answer is `NONE` for every statement type. A node is therefore identified by
`(program, paragraph, child-index-path)`, and a finding reads

```
<program> / 6200-UPDATE-MASTER / [3].then[0]
```

rather than `<program>:2887`.

The alternatives were emitting line numbers from `proleap-bridge` — correct, and
permanent for every downstream consumer, but it modifies `vendor/red-dragon` and
costs a full reparse of 3,779 members — or re-matching statements to source text
in Python, which is fragile across continuation lines, duplicated statements and
`REPLACING`-expanded copybooks. Neither is needed to prove the graph produces the
right rules, so v1 ships without provenance and the bridge change stays available
as a follow-up.

### Unresolved is a value, never a silence

Three known holes emit explicit markers rather than absence:

* 88-level `condition_name` whose owning record is a stub — `UNRESOLVED`;
* dynamic `PROGRAM(WS-x)` call targets — `UNRESOLVED-TARGET`;
* per-field commarea joins between differently-named layouts — `APPROX`.

The pass that this one replaces failed by omission, and an omission looks exactly
like a fact.

## Data dependencies

Read and write sets per verb, then reaching definitions over the CFG. Each
def-use edge carries the guard path live at the definition and at the use.

| verb | reads | writes |
| --- | --- | --- |
| `MOVE` | `operands[0]` | `operands[1:]` |
| `MOVE_CORRESPONDING` | `source` | `targets` |
| `COMPUTE` | `expression` | `targets` |
| `ADD`, `SUBTRACT`, `MULTIPLY`, `DIVIDE` | `operands` | `giving` when present, else last operand; `remainder` |
| `STRING` | `sendings` | `into` |
| `UNSTRING` | `source`, `delimiters` | `into` |
| `INITIALIZE` | — | `operands` |
| `SET` | `values` | `targets` |
| `INSPECT` | `source` | `tallying_groups`, `replacings` |
| `SEARCH` | `table`, `whens` | index |
| `READ` | `key` | record area, `FILE-STATUS` |
| `WRITE`, `REWRITE` | `record_name`, `from_field` | file, `FILE-STATUS` |
| `EXEC_CICS` | per-verb option roles: `COMMAREA`/`FROM` read, `INTO` written | plus `EIBRESP` written on every call |

### Not every dependency between two fields is a dataflow

Two fields can be related with no def-use path between them at all: they are
written together, from the same source, in the same paragraph. "Which other fields
have to be populated when this one is" is a co-write question, and a def-use graph
answers it with silence.

So the artifact carries a second, weaker relation beside the def-use edges: two
fields are **co-assigned** when both are written within the same paragraph. On its
own that says nothing. Measured on one field with 133 paragraph-level
co-assignments, and ranked by how tight the co-write is, it becomes precise:

| tier | relation | candidates for the measured field |
| --- | --- | --- |
| 1 | same statement — a multi-target `MOVE` | 3 |
| 2 | same paragraph, **same source field** | **1** |
| 3 | same paragraph, same guard set | 109 |
| 4 | same paragraph | 133 |

Tier 2 produced exactly one candidate and it was the one wanted; tier 3 ranked that
same answer 98th of 109, which is to say it did not contain it. So every co-assign
edge is tagged with its tier, a consumer cuts at 2, and tiers 3 and 4 are emitted
with their counts for a human to filter rather than to read.

This is a query-time relation over the same graph, not new node kinds: tier 1 is one
`ASSIGN` with several `writes`, tier 2 is two `ASSIGN`s sharing a `reads` entry, and
tiers 3 and 4 compare reaching conditions and paragraph identity. Nothing in the
construction changes to support it.

## Artifact and CLI

Mirrors the layout `cobble/cobble/dataflow/depgraph/` already established:

```
cobble/cobble/dataflow/srccfg/
    build.py         per-member CFG construction, the CLI entry
    cfg.py           node and edge types, the graph container
    desugar.py       the AST-to-TEST/ASSIGN lowering table
    conditions.py    condition-tree walk to atoms
    dataflow.py      per-verb read/write sets, reaching definitions
    link.py          call graph, commarea aliasing, recursive expansion
    coassign.py      the four co-assignment tiers
    render.py        slice output
```

* `cobble-srccfg-build` writes `out-<corpus>-srccfg/<PROGRAM>.json`, one per
  member, cacheable and independently regenerable.
* `cobble-srccfg <PROGRAM>` seeds at a program, expands `link` edges recursively,
  and emits the slice.

Three procedure-division shapes exist in the cache and all three are handled:
`paragraphs`, `sections`, and a top-level `statements` list. A member with none
of them is reported, not skipped silently.

## Testing

Corpus member ids belong in fixtures reading the local corpus config, never in test
source: a test names the *property*, the fixture names the member. Synthetic ASG
fragments cover the desugaring table, and corpus members are used only where the
point is that a real construct is handled.

* Desugaring: one test per row of the table above, asserting the emitted
  `TEST`/`ASSIGN` shape, from synthetic ASG dicts.
* The two rare rows — computed `GOTO` fall-through and `PERFORM n TIMES` — also get
  a corpus case each through a fixture, because there are only 14 and 13 of them in
  3,779 members and a regression would otherwise be silent.
* Short-circuit chains: `IF a AND b` yields two `TEST` nodes whose false-edges
  converge, not one compound `TEST`.
* Reaching conditions, the acceptance test for the whole design: for the nested
  `IF` in "Why" — outer guard `= SPACES OR LOW-VALUES`, inner guard a two-clause
  `AND` — the inner `MOVE` is reached by **exactly two paths**, each carrying three
  atoms: the outer comparison against one of the two figurative constants, then each
  inner comparison with its literal. Two paths rather than one is what tells the
  reader the `OR` was not silently flattened, and the literals are what the old pass
  could not produce at all.
* Co-assignment: a field written from the same source as another in the same
  paragraph yields that other field as the **sole** tier-2 candidate. Collapsing the
  tiers fails the test, because the same answer sits 98th of 133 at tier 4.
* `PERFORM` edges: a paragraph performed from two sites has two conditioned
  in-edges and one node set.
* `HANDLE CONDITION`: a handler armed in one paragraph is the target of the
  exceptional edge from a CICS call in another.
* Recursion: a `LINK` cycle terminates, and a seed with a known reachable set
  expands to 29 programs at depth 2.
* Unresolved markers: a stub-owned 88-level and a dynamic `PROGRAM` operand both
  appear in output rather than vanishing.

## Out of scope for v1

* Condition simplification and infeasible-path detection.
* Line-number provenance.
* The 38 dynamic `PROGRAM(WS-x)` targets.
* `EXEC_SQL` host-variable extraction. The ASG carries SQL as opaque `text`, and
  `cobble/sql`'s `SqlDialectParser` exists for it, but a guard field that arrives
  through DB2 is a second pass.
* The Java and JSF side, which a separate tool already covers for 148
  applications and which joins this one at the commarea boundary.
* Byte-offset-accurate commarea layouts, which would require the 318 stub
  copybooks to be real members.

## Risks

* **Range-performs over-approximate.** A `GO TO` inside a `PERFORM A THRU C`
  range can skip paragraphs the per-paragraph `perform` edges claim are entered.
  Accepted deliberately, and the `APPROX` tagging keeps it visible.
* **`fallthru` versus `return` ambiguity.** Whether control leaving a paragraph
  returns to a `PERFORM` site or falls into the next paragraph depends on how it
  was entered. Both edges exist and are tagged; a query that ignores the tags will
  find spurious paths.
* **Paragraphs entered only by `GO TO` have no `PERFORM` context to inherit.**
  17,894 of 159,562 paragraphs — 11% — are never the operand of a `PERFORM`, and
  they hold 37,363 assignments, 5% of the total. Their guards have to come from
  `goto` in-edges, which the graph has and an ancestor walk does not; this is one of
  the two things the graph buys, so it needs a test of its own rather than trust.
* **Guard atoms on stub-owned fields cannot be evaluated,** only reported. A rule
  whose deciding field lives in a foreign record will read `UNRESOLVED` and need
  the real copybook.
* **Path counts.** With 32,262 `GOTO`s, 193,160 `IF`s and roughly 70% of members
  containing at least one `GOTO`, an unfiltered backward walk can enumerate many
  paths. Reaching conditions are the pruning mechanism, but v1 should ship a path
  cap and report when it bites, rather than appearing to finish.
