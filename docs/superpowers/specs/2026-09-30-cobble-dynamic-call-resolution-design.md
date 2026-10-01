# Resolving dynamic call targets in cobble — Unit 1, intra-program

Date: 2026-09-30
Status: design, approved in brainstorm; not yet planned or implemented
Scope: `cobble` only. Unit 2 (interprocedural) is out of scope and sketched at the end.

## 1. The problem

A COBOL or CICS call whose target is a data item — `CALL WS-PROG`,
`EXEC CICS XCTL PROGRAM(CDEMO-TO-PROGRAM)` — names a program only at run time.
Cobble resolves none of them through dataflow. Three separate consequences, all
present today:

**The knowledge graph contains fabricated programs.** `cics/verb_source_asg.py:67`
resolves a CICS operand by looking up the named field's declared `VALUE` clause and
falling back to the operand's own text:

```python
def _resolve_operand(opt, data_fields):
    case _ if opt.is_literal: return opt.text
    case _:                   return _field_value(opt.text, data_fields) or opt.text
```

`flow_graph_core._verb_edge` then emits that string as a `NodeKind.PROGRAM` target.
Read out of the checked-in `cobble/reference/`: of 36 program-transfer edges, **18
point at variable names**, and four `PROGRAM` nodes are variables —
`CDEMO-TO-PROGRAM` (15 inbound XCTL edges), `CCARD-NEXT-PROG`,
`CDEMO-MENU-OPT-PGMNAME`, `CDEMO-ADMIN-OPT-PGMNAME`. The same fallback also
produced one fabricated `BMS_MAP` node, `CCARD-NEXT-MAPSET.CCARD-NEXT-MAP`. The
449-node / 803-edge reproducibility baseline encodes all of this.

**Where the lookup does fire it is unsound.** `_field_value` walks
`asg.data_fields` (WORKING-STORAGE only), takes the first name match in a tree where
COBOL permits the same name twice under different qualifiers, and is blind to every
subsequent `MOVE`. A field declared `VALUE 'AAAA'` and overwritten with
`MOVE 'BBBB'` before the transfer resolves to `AAAA`.

**Dynamic COBOL `CALL` is invisible.** `cobol_imports.py:60`'s
`CALL_STMT.3: /CALL[ \t]+(?:'…'|"…")/i` is literal-only by construction, and the
module says so: *"a bare CALL without a string argument (e.g. CALL WS-VAR) falls
through to WORD noise"*. So a dynamic `CALL` contributes no edge and no node.

The root cause is the same in all three: `cicada/cics/strategy.py:386`
`emit_operand_value` resolves an operand by emitting a **runtime decode** of the
field, and its documented fallback — "an unresolved bare name emits a Const of its
text" — is for a name that is not a field at all. Cobble, which never runs anything,
substituted the declared `VALUE` for the decode and inherited a fallback whose
precondition it cannot check. The value analysis below is the static stand-in for
that decode, done properly.

## 2. What the corpora actually need

Every non-literal `XCTL`/`LINK PROGRAM(...)` operand across `vendor/carddemo` and
`vendor/bank-of-z`, bucketed by what would resolve it:

| count | route | example |
|---|---|---|
| 132 | declared `VALUE` constant | `01 WS-ABEND-PGM PIC X(8) VALUE 'ABNDPROC'` |
| 18 | static literal | already resolved today |
| 16 | local literal `MOVE` | `MOVE 'COSGN00C' TO CDEMO-TO-PROGRAM` |
| 10 | inbound / commarea | `XCTL PROGRAM(CDEMO-TO-PROGRAM)` with no local writer |
| 3 | subscripted `VALUE` table | `XCTL PROGRAM(CDEMO-MENU-OPT-PGMNAME(WS-OPTION))` |

Method: regex over source text, not the ASG. Treat it as a scale estimate. The
18-of-36 edge figure in section 1 is exact, read from the checked-in artifact.

Two things follow. The declared-constant route dominates — 127 of the 132 are one
idiom, `WS-ABEND-PGM` XCTL'd from every abend path in bank-of-z — so retaining
literal text and building the `VALUE` image have to ship together; either alone
delivers a small fraction. And of the 161 sites not already static, Unit 1 reaches
**151** — the declared constants, the local `MOVE`s and the subscripted tables are all
entirely within one member — leaving 10 for Unit 2. That ratio is why Unit 1 is worth
doing on its own.

## 2a. What running the analysis revealed

The fixpoint's 23 unit tests pass and are thorough. Its four *corpus-level* acceptance
tests had never run: they are gated on `config/fields-tests.toml`, which is gitignored
and absent, so `tests/dataflow/` reports 871 passed / 17 skipped and all 17 skips are
the acceptance tests for this package and `srccfg`. `test_fields_acceptance.py`'s own
docstring warns against exactly this — *"the 3ao post-mortem found a suite passing
while its walk reached 18% of nodes, because nothing measured reach"* — and the test
written to prevent it has been measuring reach on zero members.

Run for the first time over the 29-member CardDemo cache:

| measure | value |
|---|---|
| write operands | 3863 |
| covered by a resolved extent | 3426 (**88.7%**) |
| statement instances outside `HANDLED` | 2542 |
| members whose walk did not settle | **1** — `COACTUPC`, 2064 nodes, at the default factor 50 |
| total analysis time | 72.5s; worst member 29.1s |

Four consequences for this design.

- **The substrate is sound enough to build on.** 88.7% coverage against a
  `COVERAGE_FLOOR` of 0.60 is not a broken analysis. The floor, however, is so far
  below reality that it would not notice a regression halving the coverage; raising it
  to just under the measured figure is part of this unit.
- **The dequeue cap was a mistuned default, and finding it is what forces the
  `INCOMPLETE_WALK` rule in section 4.7.** At the default `ITERATION_FACTOR = 50`,
  `COACTUPC` exhausts its cap of 103200 and `_skip_reason` records
  `"dequeue cap 103200 reached"`, so its state is a subset. Measured at factor 150 it
  settles, in 28.6s against 27.0s, with coverage identical at 660/834 — the extra
  dequeues confirm the state rather than growing it. So the fix is the constant, and
  the corpus has no unsettled member once it is raised.

  The rule stays regardless, for two reasons. The condition is reachable in general —
  a larger member, a different corpus, or the sweep walk running out of its budget,
  which `_swept` reports through the same `settled` flag — and nothing about a value
  set makes it safe to publish as a fact when the walk that produced it did not
  finish.

  As built, though, `INCOMPLETE_WALK` cannot reach `targets.jsonl` on the default
  worklist path at all. A member whose queue is non-empty at the cap gets a non-empty
  `skipped` from `_skip_reason`, and `build_corpus._tables` returns a `MemberResult`
  with no tables for such a member — so every one of its rows is dropped, the reason
  with them. The reason is live only under `--sweeps`, where a budget exhausted leaves
  `settled` False and `skipped` empty, and in the unit tests that call `analysed`
  directly. The rule still belongs in the graph: it is what stops a singleton from
  being promoted where rows *do* carry it. And it was invisible until the analysis ran at corpus scale: the cap is a
  function of program size, so no unit-test fixture can reach it, and the one test
  that would have is among the 17 that had never run. Without the rule this design
  would publish an unsettled walk's single candidate as a proven transfer, which is
  the one genuinely unsound thing it could do.
- **A CardDemo acceptance config should be tracked — under a different name.**
  `cobble/.gitignore:26` ignores all of `config/*.toml` because a config carries
  absolute corpus paths and member globs, and already negates `!config/carddemo.toml`
  under the comment *"CardDemo is a public sample corpus, so its configs identify
  nothing"*. So the precedent holds, but `fields-tests.toml` is the **fixed** filename
  `tests/dataflow/fields/conftest.py:25` resolves, and un-ignoring that name would
  auto-track whatever a user writes there for a corpus under analysis — the leak
  `data-security.md` exists to prevent. So: a tracked
  `config/carddemo-fields-tests.toml` with its own `!` negation, and `conftest.py`
  preferring a local `fields-tests.toml` where one exists and falling back to the
  CardDemo one. The private filename stays ignored; the public one is explicitly
  named. Same treatment for `srccfg-tests.toml` and `closure-tests.toml`, which
  account for 13 of the 17 skips.
- **The cost premise behind decision 4 is weaker than stated.** `cobble/README.md`
  says a whole-cache pass is "minutes of fixpoint per member"; the measurement is 2.5s
  typical and 29.1s worst, 72.5s for all 29. That does not overturn the artifact
  indirection — the 449/803 reproducibility should not hinge on an analysis running
  inside a commit hook, and a larger corpus may behave differently — but the README's
  figure should be corrected, and the decision should be re-affirmed on the
  decoupling argument rather than on a cost figure that does not hold here.

## 3. Scope

**In.** Intra-program resolution of the program operand of `EXEC CICS XCTL`,
`EXEC CICS LINK`, and COBOL `CALL`. A value component on the existing byte-extent
fixpoint; an initial byte image from `VALUE` clauses; a new artifact table; resolved,
candidate and unresolved edges in the whole-corpus graph.

Also in, because section 2a shows this unit cannot be trusted without them: tracked
CardDemo acceptance configs under public-corpus filenames with the conftest fallback
described there, a `COVERAGE_FLOOR` raised to just under the measured 88.7%, and an
equality assertion replacing the `assert carried` non-empty check that is currently
the analysis's only end-to-end correctness oracle.

**Out, deliberately.**

- *Interprocedural propagation* (Unit 2). A program name arriving through a
  `COMMAREA` resolves to the unresolved form with reason `INBOUND_LINKAGE`.
- *Guard sensitivity.* `WHEN CDEMO-MENU-OPT-PGMNAME(WS-OPTION) = 'COPAUS0C'` pins
  the value exactly at the site, and `fields/state.py` states that the lattice
  deliberately carries no guards. Refining a candidate set by the guards reaching it
  is a follow-up (section 9), not a widening of this unit.
- *The other CICS operands.* `_resolve_operand` also serves `TRANSID`, `MAP`,
  `MAPSET` and `FILE`/`DATASET`, and the fabricated `BMS_MAP` node proves the same
  defect reaches them. Unit 1 changes only `_transfer_verb`, so those operands keep
  their current behaviour, fabricated node included. Extending the value analysis to
  them is a follow-up.
- *Ground truth from execution.* cicada can run these programs, so soundness is
  checkable — every target a real run took must appear in the candidate set. Cobble
  may not import the interpreter (`.importlinter:101`), so this is a comparison of
  recorded artifacts and is a follow-up.

## 4. Design

### 4.1 `ValueSet` and the unresolved reason

New module `cobble/dataflow/fields/values.py`.

A value is `bytes` of exactly the holding extent's length — not `str`, because a
partial write has to compose byte-wise, and not a program name, because the same
lattice carries non-name values. Alphanumeric content is left-justified and
space-filled to the extent length, matching the move semantics
`cobol_asg/cobol_types.py:45` describes; the candidate program name is the value with
trailing spaces stripped.

```
UnresolvedReason(Enum)          # serialised as its lowercase-hyphen value
    NOT_A_LITERAL               arithmetic, an intrinsic FUNCTION, an unhandled verb
    INBOUND_LINKAGE             a LINKAGE extent with no writer in this member
    FROM_FILE                   a READ or RECEIVE reached it
    FROM_CALLEE                 a called program wrote it back
    NO_EXTENT                   the operand resolved to no storage
    UNINITIALISED               the extent has neither a VALUE nor any writer
    OVER_BUDGET                 more distinct values than the cardinality bound
    INCOMPLETE_WALK             the member's walk did not settle, so the set is a subset

ValueSet(frozen)
    values: frozenset[bytes]
    reasons: frozenset[UnresolvedReason]
```

`reasons` empty means the set is complete: these values and no others. Non-empty
means "at least these, and possibly more, because …". That is the existing
`Reaching.truncated` semantics — a flagged subset rather than a top element that
discards what was learned — and it is why a value set that overflows the bound keeps
its members instead of collapsing.

An enum rather than a fifth string prefix beside `LITERAL`, `FILE:`, `%CALL:` and
`UNKNOWN:`. `design-principles.md` forbids deducing meaning from string shape, and
`cobble/file_location.py:37`'s `FileLocationReason` is the precedent for a typed
reason serialised as text at the boundary.

`MAX_VALUES = 32`. The largest `VALUE` table observed in either corpus holds 12
entries, so 32 leaves headroom while bounding both the lattice height and the
artifact row width. Fixed constant, not an option: `guardrails.md` forbids adding a
knob in place of a decision. Over the bound, the lowest 32 values in sorted order are
kept — sorted so the artifact is deterministic — and `OVER_BUDGET` is added.

Join is union of both fields. Height is finite because `MAX_VALUES` bounds `values`
and `UnresolvedReason` is finite, so the lattice terminates on the same argument the
existing one does.

### 4.2 `State` gains a second component

`fields/state.py` today is `State = Mapping[FieldExtent, frozenset[Source]]`. It
becomes a frozen dataclass:

```
State(frozen)
    sources: Mapping[FieldExtent, frozenset[Source]]
    values:  Mapping[FieldExtent, ValueSet]
```

`join` joins both maps. `write(state, target, sources, values)` applies the *same*
`must_cover` kill to both — an EXACT target drops its own prior entry in both maps, a
CLAMPED one keeps both. One kill rule, applied once, is the point: a value that
survived a write its provenance did not would be a value the program cannot hold.

A dataclass rather than a parallel map threaded beside the existing one, so it is not
possible to join one and forget the other.

Blast radius: `fields/state.py`, `fields/transfer.py` (`_applied` and every `Write`
producer), `fixpoint/fixpoint.py` (`EMPTY`, the worklist's in-state comparison, and
extraction). `reaching(state, read)` keeps its present signature and reads
`state.sources`; value reads go through section 4.5's separate function.

### 4.3 The initial byte image

`Cell` (`dataflow/layout.py:218`) gains `value: str` and `value_is_figurative: bool`,
carried from `CobolField.value` / `.value_is_figurative` through `_sized`, `_declare`
and `_occurrence` — so every materialised occurrence of a table entry carries the
declared literal of the declaration it came from.

`program_records` gains a companion that turns those cells into an entry state: one
`ValueSet` per **elementary** cell that declares a `VALUE`, at that cell's extent, at
EXACT precision. Group cells contribute nothing, so a read of a child extent can
never also match a group-wide entry through `may_alias`.

Three rules:

- **WORKING-STORAGE only.** `LINKAGE` and the `FILE` section have no initial content.
  A `LINKAGE` extent that no statement in the member writes therefore has no value and
  resolves with reason `INBOUND_LINKAGE` — which is exactly the hook Unit 2 fills.
- **Figurative values are concrete bytes and are included.** `SPACES` is `X'40'`
  repeated to the extent length, `LOW-VALUES` is `X'00'`, `ZEROS` is `'0'` for a
  DISPLAY item. Excluding them would make the image lie about what the storage holds,
  and `COMEN01C.cbl:198` guards on precisely that content.
- **A resolved value that is not a program name is not a candidate.** All-space,
  all-low-value and non-printable values are dropped from the candidate list at the
  point of emission (section 4.5), and their absence is recorded as a reason on the
  row. They are still values in the lattice — they are true statements about the
  storage — but a `PROGRAM` node named with eight spaces is not.

`REDEFINES` needs no handling: `layout.py:_cluster` already merges redefining level-01
items into one `Record` with one coordinate space, which is what makes the
`COMEN02Y.cpy` pattern work — the program names are declared as `FILLER … VALUE
'COACTVWC'` under `CDEMO-MENU-OPTIONS-DATA` and read through
`CDEMO-MENU-OPTIONS REDEFINES` it. The writer and the reader share no name; they share
bytes. Nothing name-based can resolve this.

### 4.4 Transfer functions

`fields/transfer.py:98` currently collapses a literal to the bare origin `LITERAL`,
discarding its text. It keeps that origin for provenance and additionally produces a
`ValueSet` holding the literal's bytes, padded to the target extent.

| statement | values produced |
|---|---|
| `MOVE <literal> TO t` | the literal's bytes, padded to `t` |
| `MOVE s TO t` where `s` has values | `s`'s value set, re-padded to `t` |
| `MOVE s TO t` where `s` has none | `NOT_A_LITERAL` |
| `INITIALIZE t` | the category's initial bytes, per `_initialize_writes` |
| a `READ`/`RECEIVE` target | `FROM_FILE` |
| a `CALL`'s `BY REFERENCE` argument | `FROM_CALLEE` |
| any statement class outside `HANDLED` | `NOT_A_LITERAL` |

Re-padding on a field-to-field move matters: a `PIC X(4)` source into a `PIC X(8)`
target yields four bytes plus four spaces, and the candidate name is the stripped
result.

**Reference modification does not compose, and a partial write invalidates what it
lands in.** An earlier draft of this section claimed the surrounding bytes keep
whatever the image put there, "which is how a name assembled in pieces resolves at
all". Nothing implements that. A `ValueSet` is a set of whole values held at one
extent, not a byte array, so there is nowhere to splice a slice into: a write to
`WS-PGM(1:1)` stores its own one-byte extent and leaves the eight-byte entry beside
it, and the eight-byte read then answered out of the stale entry — the declared
`VALUE` — **with empty reasons**, which is a proven call edge to a program the site
may never reach. As shipped, a write that overlaps a valued extent without spanning it
drops that entry's values and keeps its reasons, adding `NOT_A_LITERAL`
(`state.py:_invalidated`): the site reads as unresolved rather than as resolved to a
name the program overwrote.

Splicing was rejected rather than deferred. The bytes on either side of the slice were
placed by writes the fixpoint reached along their own paths, so a composed value would
be a name assembled out of a combination no single path produces — the same
fabrication `values_at` already refuses for a read straddling two valued extents, and
the same wrong-edge class this unit exists to remove. A name genuinely assembled in
pieces therefore stays unresolved here, and the reason says so.

### 4.5 Resolving a call site

A new `cobble/dataflow/fixpoint/targets.py` reads the settled state at each call
node and produces one `ResolvedTarget` per site.

The read is **not** `reaching`. `extent.py:_clamped` gives an operand with a computed
subscript one CLAMPED extent spanning every occurrence, `min(start)` to `max(end)`.
For `CDEMO-MENU-OPT-PGMNAME(WS-OPTION)` that span is 11×46+8 bytes wide and covers
every row's 35-byte caption and 1-byte user type. The CLAMPED span exists so a
computed subscript can never *kill* a definition — a write-side concern that
`state.py` documents — and it is the wrong extent to read through.

The danger is not the one first written down here. Reusing the span does **not**
return `'Account View'` and `'U'` alongside the program names: `values_at` matches an
entry only when it *contains* the read, and a read spanning the whole table is
contained by no entry, so the answer is no values at all and `UNINITIALISED`. The
occurrence-exact read is required to **enable** the right answer, not to prevent a
wrong one — without it the menu site resolves to nothing, which is why the test named
in section 7 asserts the eleven names are present and not merely that captions are
absent.

So value resolution enumerates the operand's occurrence cells at EXACT precision,
using `index.occurrences_of` as `_clamped` itself does, and unions the value set held
at each. A literal subscript reads the one matching occurrence. An unsubscripted
operand reads its own EXACT extent. Reference modification narrows the extent before
the read.

```
ResolvedTarget(frozen)
    caller: str
    node: str                 the CFG node id of the call site
    transfer: str             CICS_XCTL | CICS_LINK | CALL
    expression: str           the operand as the source spells it, subscript included
    candidates: tuple[str, ...]
    reasons: tuple[UnresolvedReason, ...]
    dropped: tuple[str, ...]  values that resolved but are not program names
```

`candidates` is sorted, so the artifact and therefore the graph are deterministic. A
site with a literal target is not a row here; it is already an edge.

`candidates` empty with `dropped` non-empty and `reasons` empty is a meaningful
combination, not a gap: every value the site can hold resolved, and none of them is a
program name. The `DYNAMIC_TARGET` node it produces carries `dropped` in its attrs,
which is the explanation — a site whose operand provably holds spaces needs no reason
beyond the value itself.

### 4.6 The artifact

The fixpoint corpus stage writes four tables today — a graph plus `extents.jsonl`,
`defs.jsonl`, `aliases.jsonl` — through `_Sinks`, each a corpus-wide JSONL file keyed
for a keep-first dedupe. A fifth is added, `targets.jsonl`, with a `target_row` in
`fields/side_tables.py` beside `alias_row`, keyed `caller\x00node`. One row per
dynamic call site, whether or not anything resolved: a site that resolved to nothing
is a row a consumer can read, not an absence it has to interpret — the rule
`CommareaAlias` already states.

Reads go through the existing `fixpoint/rows.py` helpers (`text`, `strings`), so the
`object` annotation that module confines to itself does not spread and no second
boundary convention appears.

### 4.7 The graph

`knowledge_graph/graph_types.py` gains one node kind and three edge kinds:

```
NodeKind.DYNAMIC_TARGET     id is "<program>.<expression>"
EdgeKind.XCTL_CANDIDATE
EdgeKind.LINK_CANDIDATE
EdgeKind.CALL_CANDIDATE
```

`build_graph.py` reads `targets.jsonl` and emits, per row:

| value set | edge kind | target |
|---|---|---|
| exactly one candidate, `reasons` empty | `XCTL` / `LINK` / `CALL` | the `PROGRAM` node |
| two or more, or one with any reason | `*_CANDIDATE` | one `PROGRAM` node each |
| none | `XCTL` / `LINK` / `CALL` | a `DYNAMIC_TARGET` node |

Uncertainty about *which of several known programs* belongs on the edge; the absence
of any resolved program belongs on the target's kind. The transfer itself is certain
in all three rows, so no edge kind has to express "maybe nothing".

**Promotion to an ordinary edge requires `reasons` to be empty, not merely a single
candidate.** A walk that did not settle yields a subset, so a site that resolved to
exactly one program in an unsettled member may have a second the walk never reached;
presenting that as a proven transfer would be the one genuinely unsound thing this
design could do. `analyse` already reports this — `_skip_reason` returns
`"dequeue cap N reached"` when the queue is non-empty at the cap — and every
`ValueSet` a member produces inherits `INCOMPLETE_WALK` when it does. This is not
hypothetical: see section 2a.

`DYNAMIC_TARGET` ids are `"<program>.<expression>"` — `COACTUPC.CDEMO-TO-PROGRAM` —
following `NodeKind.FIELD`, which is `"<program>.<field>"` *"because a field name is
only unique within a program"*, and `INSTREAM_DATA`, scoped `JOB.STEP.DDNAME`. A
single corpus-wide node per expression would reintroduce exactly what
`dataflow/depgraph/flows.py:319` rejected: `CDEMO-TO-PROGRAM` is the target of 15
sites in 15 different members, and one shared node fuses all 15 into a hub through
which reachability queries would report paths that do not exist.

The node's `attrs` carry the reasons and the dropped values. Its `reason` attr is
either the serialised `UnresolvedReason` values from the row, or the literal
`not-attempted` where there is no row at all — a graph-level value that the lattice
never produces and that is deliberately not a member of `UnresolvedReason`, because
nothing in the analysis can conclude it. It marks the distinction
`graph_types.py:132` already draws for `FileLocation`, where a node built with no
resolver in reach *"has not failed to resolve, it was never looked up"*.

Which sites `build_graph` knows about without the artifact is asymmetric, and the
asymmetry is a consequence of section 1 rather than a choice here. A CICS site is
known from `CicsVerb.program_operand`, so it gets a `not-attempted` node. A dynamic
COBOL `CALL` is known only from the artifact, because `cobol_imports.py:60` is
literal-only, so with no artifact it stays invisible exactly as it is today. Dynamic
`CALL` sites therefore come wholly from `targets.jsonl`, which enumerates them from
the `CallStatement` nodes the CFG walk already visits.

`cics/verb_source_asg.py::_transfer_verb` stops calling `_resolve_operand`: it sets
`xctl_target` only for a literal operand, and a new `CicsVerb.program_operand` field
carries the data-name operand as written. `flow_graph_core._verb_edge` needs no change
at all — line 97 already returns early on an empty `xctl_target`, so the fabricated
edges stop being produced rather than being produced and filtered. `_resolve_operand`
itself stays, for the operands section 3 puts out of scope.

## 5. Files changed

| file | change |
|---|---|
| `cobble/dataflow/fields/values.py` | new — `ValueSet`, `UnresolvedReason`, `MAX_VALUES` |
| `cobble/dataflow/fields/state.py` | `State` becomes a frozen dataclass of two maps; `join` and `write` cover both |
| `cobble/dataflow/fields/transfer.py` | literal text retained; every `Write` carries a `ValueSet` |
| `cobble/dataflow/layout.py` | `Cell.value`, `Cell.value_is_figurative`; the entry-state builder |
| `cobble/dataflow/fixpoint/fixpoint.py` | entry state seeded from the image; two-component in-state comparison |
| `cobble/dataflow/fixpoint/targets.py` | new — occurrence-exact value read, `ResolvedTarget` |
| `cobble/dataflow/fields/side_tables.py` | `target_row` |
| `cobble/dataflow/fixpoint/build_corpus.py` | fifth sink, `targets.jsonl`; targets in the run report |
| `cobble/knowledge_graph/graph_types.py` | `DYNAMIC_TARGET`, three `*_CANDIDATE` edge kinds |
| `cobble/build_graph.py` | read `targets.jsonl`; emit the three-way rule |
| `cobble/cics/verb_source_asg.py` | `_transfer_verb` stops resolving; `CicsVerb.program_operand` |
| `cobble/reference/nodes.jsonl`, `edges.jsonl` | regenerated |
| `cobble/README.md` | the new stage output, the three edge forms, the node kind |

## 6. Baseline movement

Four fabricated `PROGRAM` nodes disappear and 18 edges retarget; the two menu members
add candidate edges. So 449/803 changes — measured, to 448/832.

Dynamic COBOL `CALL` sites do **not** appear: CardDemo has none, every `CALL` in it
naming a literal, and it has no `EXEC CICS LINK` in a member the build can read
either. So every row the corpus produces is a `CICS_XCTL`, and the `CALL` and `LINK`
arms of the rule ship exercised by unit tests only.

Nor does any row carry `INCOMPLETE_WALK`: a member that does not settle on the default
worklist path has all its rows dropped (section 2a), so the corpus artifact cannot show
the reason even when the cap is reached. `cobble/tests/test_compare.py` and the README's claim move in the
**same commit** as the change that moves them, with the new counts stated and the
reason recorded. The count is not a test assertion to be relaxed — the regenerated
reference is reviewed row by row for the retargeted edges before it is committed.

## 7. Testing

Unit tests in `cobble/tests/dataflow/`, integration in the same tree against the ASG
cache. One test per behaviour, each asserting everything the behaviour implies.

**Unit.**

- *The entry state.* A record with `VALUE` clauses, a figurative `VALUE`, a
  `REDEFINES` pair and an `OCCURS` table yields one `ValueSet` per elementary cell at
  its EXACT extent, every occurrence carrying its declaration's literal, no group
  entries, and nothing for `LINKAGE`.
- *The lattice.* `join` unions values and reasons; an EXACT write drops the target's
  prior value set and a CLAMPED one keeps it; overflow past `MAX_VALUES` keeps the
  lowest 32 sorted and adds `OVER_BUDGET`.
- *Transfer.* Literal `MOVE` pads to the target width; field-to-field re-pads; a
  reference-modified write leaves the surrounding bytes intact; a statement outside
  `HANDLED` yields `NOT_A_LITERAL`.
- *The occurrence-exact read.* A computed subscript over the `COMEN02Y` shape returns
  the twelve 8-byte program names and **not** the captions or user types — the
  assertion that fails if the CLAMPED span is reused.
- *Candidate filtering.* An all-space value resolves, is dropped from `candidates`,
  and appears in `dropped`.

**Integration**, against `vendor/carddemo`'s cache, asserting concrete values:

- `COUSR00C`'s `XCTL PROGRAM(CDEMO-TO-PROGRAM)` sites resolve to the exact program
  names their local `MOVE`s set. **Not** with empty `reasons`: the commarea of the
  `XCTL` that reaches each site is modelled as a callee write-back, so every one of
  them carries `FROM_CALLEE`, and the read of a commarea field reaching no local write
  adds `INBOUND_LINKAGE`. The candidate sets are the assertion; the sites are
  candidates, not proven, until the follow-up in section 9 stops modelling a
  write-back from a verb that never returns.
- `COMEN01C`'s menu site yields exactly the program names in `COMEN02Y.cpy`, sorted.
- `COMEN01C`'s `RETURN-TO-SIGNON-SCREEN` site yields `COSGN00C` from the guarded local
  `MOVE`, with `INBOUND_LINKAGE` among its reasons because the commarea field has
  writers this unit cannot see. `INBOUND_LINKAGE` is produced at read time, by
  `state.py:_missing` on a miss whose extent is in the LINKAGE region, and is never
  stored: an entry per LINKAGE byte range any statement reads would regrow the value
  map this unit worked to keep small.
- A built graph contains no `PROGRAM` node named `CDEMO-TO-PROGRAM`,
  `CCARD-NEXT-PROG`, `CDEMO-MENU-OPT-PGMNAME` or `CDEMO-ADMIN-OPT-PGMNAME`, and
  contains the named `DYNAMIC_TARGET` nodes instead.

**Mutation checks** before any of these is trusted. Break the `must_cover` kill on
the value map and the `COUSR00C` test must fail with a stale candidate. Replace the
occurrence-exact read with `reaching` on the CLAMPED span and the `COMEN01C` menu
test must fail with captions among the candidates.

## 8. Verification gate

Per `guidelines/project/workflow.md`, from the forge root:

```bash
make fmt
uv run pyright
uv run lint-imports
pre-commit run python-fp-lint-check --hook-stage manual --all-files
make test-all
```

`make test-all`, not `make test`: this changes a runtime-adjacent package and the
graph both.

## 9. Follow-ups to file

- Guard-sensitive refinement of a candidate set — `WHEN … = 'COPAUS0C'` pins the value
  at the site, and `state.py` carries no guards by design.
- Extend the value analysis to `TRANSID`, `MAP`, `MAPSET` and `FILE` operands, and
  retire `_resolve_operand` entirely; the fabricated `BMS_MAP` node goes with it.
- Soundness check against an interpreted run: every target a real execution took must
  appear in the candidate set. An artifact comparison, since `.importlinter` forbids
  cobble importing the interpreter.
- Unit 2, below.

## 10. Risks

- **`State` becoming a dataclass touches every user of the lattice.** The kill rule
  living in one place means that if `write` is right, both components are right — but
  that is a unit-level argument, and section 2a is why it is not sufficient on its own.
  The in-state comparison in the worklist is the one place a missed component would
  cause silent non-termination rather than a wrong answer, so it is asserted directly.
- **Memory.** Per-node state roughly doubles, over a corpus whose largest record holds
  10595 cells. To be measured on the worst member before the unit is committed, not
  after; if it does not hold, restricting the value map to extents that can reach a
  call operand is the fallback, with the caveat that Unit 2 makes that set
  non-local.
- **The candidate set is only as good as the corpus is static.** A program name read
  from a control file or a Db2 table is `FROM_FILE` and stays unresolved. That is the
  honest answer and the artifact says which sites it applies to.

## 11. Unit 2, in one paragraph

Per-member independence survives. `build_corpus._run` is a reduce over member paths,
each reading its own ASG cache and sharing no state — the one cross-member reach,
`commarea_aliases(asg, index, asg_dir)`, opens the callee's cache only to size its
`LINKAGE`, a read of declarations that needs no ordering. A value arriving through a
`COMMAREA` needs the other member's *results*, and a callee's `LINKAGE` entry state is
the join over its callers, so the caller set — the call graph — is needed, and
resolving dynamic calls is what produces it. Unit 2 is therefore the same per-program
fixpoint run repeatedly with a seeded `LINKAGE` entry state, inside a corpus-level
worklist that re-runs only the members whose entry state changed, until no value set
and no edge grows. It terminates because both components only grow and both are
finite. Its precision is context-insensitive by construction: one entry state per
program is the join over all callers, so the "return to whoever sent me" idiom
resolves to every program that transfers to it — sound, and for that idiom arguably
the true answer. Note that query-time stitching, which `reaches --across-calls` uses
for field traces, is not available here: the stitching would need the very call graph
the resolution produces.

## 12. Decision record

1. **Staged, intra-program first.** Unit 2 needs Unit 1's lattice regardless, and
   Unit 1 alone resolves 151 of the 161 non-static sites and removes the fabricated
   edges.
2. **A second component on the existing forward state**, not a demand-driven backward
   walk and not a restricted forward pass. A backward walk would rebuild join-at-node
   and the `must_cover` asymmetry in the opposite direction; a restriction cannot be
   computed per member once Unit 2 exists.
3. **New candidate edge kinds**, not evidence in `attrs` and not a side table. Every
   renderer filters on `EdgeKind`, so a distinction in `attrs` is one they all ignore
   by default.
4. **The graph reads a fixpoint artifact**, rather than the fixpoint becoming a
   prerequisite or a second narrow pass living in the graph build. Matches the
   pipeline's existing idiom; keeps `cobble-build` fast; avoids two resolvers that can
   disagree.
5. **The unresolved target is a typed node, namespaced per caller program and
   expression.** Keeps the site visible instead of dropping the edge, and does not
   fuse 15 members through one hub.
