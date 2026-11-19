# CodeQL COBOL across programs: values, jumps, targets and links

The user chose (2026-11-19) to port cobble's `combine` to QL rather than take its targets as
facts: CodeQL works out which program a `CALL WS-PGM` or `XCTL PROGRAM(CDEMO-TO-PROGRAM)`
reaches, and which bytes cross, so its answer is a check on cobble's, not a copy of it.

## What parity means

Against cobble on CardDemo, freshly parsed, `combine` run with no hop limit (it finishes in
about a second; with `--max-hops 5` nine targets also say `hop-limit`):

| cobble output | rows | compared per |
|---|---|---|
| fixpoint `defs.jsonl` `values`, `reasons` | 5,958 reads | program, node, cell |
| fixpoint `jumps.jsonl` | 112 jumps (ENTRY, EXIT, CALL, XCTL, RETURN_TRANSID) | program, node, kind |
| fixpoint `targets.jsonl` | 75 sites | program, node, kind: candidates, reasons |
| combine `targets.jsonl` | 75 sites | the same, after crossing programs |
| combine `links.jsonl` | 94 crossings | caller, node, transfer, callee: both windows, returns |

## How cobble gets there

`combine` reads no source. It reads what the fixpoint wrote per program: each jump with its
areas (`jumps.jsonl`), and what the settled state holds at each node: a `Fact` of values,
writers and reasons. It walks back from a target's operand through the writers that copy into
it until it reaches a value, or a stop: bytes received from a caller (`inbound-linkage`),
returned by a CALL or LINK, or retrieved. Each stop is answered from the other programs: the
callers' areas over every link into the program, the callee's state at its exit. New targets
add new links, so it runs in rounds until no edge is new.

The fixpoint's values are per write. A MOVE of a quoted literal writes it fitted to the target
(`fitted`, or `fitted_right` for JUSTIFIED); a MOVE from a field carries the source's values,
refitted. A figurative constant or a numeric literal in a MOVE is `not-a-literal`; a VALUE
clause, figuratives included, is the initial image (`initial_image`). A read takes its value
from a valued extent that contains it, sliced; a read straddling two valued extents has none.
A read with no value says why: `inbound-linkage` in LINKAGE, else `not-a-literal` where a
write without a value reached it and `uninitialised` where some path has it never written;
`from-file`, `from-callee`, `unmodelled` come from the verbs that write that way.

## Units, in order

Each lands as one commit with its facts test, its QL, its diagnostic and its comparison.

1. **Values within a program.** Facts: `initial_value(cell, bytes)` from `initial_image`, and
   the bytes a literal write puts in its cell as `transfer.py` fits them. QL: a read's values
   from its definers, recursively through copies; reasons as above. `Values.ql` against
   `defs.jsonl`.
2. **Jumps.** QL reads each CALL, LINK, XCTL, RETURN TRANSID, START, RETRIEVE, ENTRY and EXIT
   with its target and transid operands and its areas (USING, COMMAREA, FROM, INTO, LINKAGE),
   as `jumps/facts.py` reads them, verb by verb, as sinks are read. `Jumps.ql` against
   `jumps.jsonl`.
3. **Targets within a program.** A target's candidates are its operand's values, trimmed; a
   file site's too. `Targets.ql` against the fixpoint's `targets.jsonl`.
4. **Across programs.** Facts: the CSD's transaction-to-program map. QL: a stop's values from
   the other programs -- received from every caller's area, returned from the callee's exit,
   retrieved from a START -- over links whose callees are themselves resolved targets.
   `Links.ql` and `LinkedTargets.ql` against `combine`.

## Rulings

- **Plain recursion, not the dataflow library, for values.** A target's callee depends on
  values, and values cross programs over callees, so the call graph and the values are one
  least fixpoint. QL's positive recursion states that directly, with no rounds and no hop
  count; the shared dataflow library cannot take a call graph that depends on its own flow.
  Within a program, values follow the definers `ReachingDefinitions.ql` already matches, which
  carry PERFORM context. Cost if wrong: unit 1 measures the result against the fixpoint, so an
  imprecision shows there before anything builds on it.
- **COBOL's value rules stay in cobble.** How a literal lands in a cell (fitting, JUSTIFIED,
  figurative repetition, numeric digits) and what VALUE puts in storage are cobble's facts, as
  names and the CFG are.
- **The fixpoint's bounds are reported, not mimicked.** `MAX_VALUES` (32, `over-budget`: one
  CardDemo read) and the `exact_values` shortcut in MOVE chains (a source read through another
  name than the one its value was declared under reports a reason, not the value) are
  engineering bounds. Where CodeQL is more exact, the difference is listed, as COCRDLIC's
  clamped spans are.
- **Compared against `combine` with no hop limit.** The least fixpoint has no hop count;
  `--max-hops` is cobble's bound for corpora where the exact run does not finish.
- **What a read can see before any statement ran is plain recursion, not a dataflow source.**
  A start source writing every atom made the shared library's local-flow step a cross product
  of all flow nodes: reaching definitions went from about a minute to 45 on CardDemo, values to
  71. The start passes a PERFORM only when the range has a path that leaves the atom alone,
  which is a fact about the range wherever it is called from, so no call context is needed.
  The rows are identical on eight CardDemo programs; the whole cycle runs in about 9 minutes.
- **Reads are compared piece by piece.** The fixpoint cuts a read where the entries holding
  its bytes begin and end; CodeQL cuts where the set of definers changes from one atom to the
  next, and at slice edges. Every fixpoint piece but one table read through computed
  subscripts (COCRDLIC) has a CodeQL piece of the same bytes.
- **A MOVE carrying only doubt lands as written bytes.** The fixpoint stores no entry for a
  carried set with no value whose reasons are only `not-a-literal` and `uninitialised`, so the
  target reads back as written; a set with a value or any other reason is stored whole,
  `uninitialised` included. QL decides which a set is from its reasons with carried ones
  taken unchanged, a stratum below the reasons it reports, since negating the reasons
  themselves would recurse through loops. 59 CardDemo MOVEs carry `uninitialised` beside
  another reason.
- **Unit 1's remaining differences are the fixpoint's bounds.** Looking a MOVE source up by
  its exact extent, as `exact_values` does, in a scratch query turns 338 of the 499
  differences into matches. Every one of the 160 left is the fixpoint giving a superset of
  CodeQL's reasons, from a join that widens a stored entry's reasons over its whole extent
  (the mechanism checked by probing the fixpoint's state on COCRDUPC; the rest have the same
  shape: the same definers, more reasons), and one read is over budget.
- **Jumps are read from the tree; only names are facts.** QL reads each verb's target,
  transaction and areas from the generated tree, as it reads sinks. What an operand handing
  storage over names (`area_cells`: unsubscripted, by name and qualifiers) and what a program
  is entered with (`received_areas`) are cobble's resolution, so they are facts, as `names_cell`
  is.
- **A write lends a read its value only if it holds every byte.** A write a later MOVE
  partly overwrote is split in the fixpoint's state, so a read across both parts finds no
  value and says only that the bytes were written. QL first let such a write lend its literal
  to the whole read, a value the bytes no longer hold (an area cell in COACTUPC showed it).
- **A node nothing reaches is reported, not mimicked.** The fixpoint reads a jump in a
  paragraph no PERFORM names against an empty state, so the 32,767 cells of each of four such
  commareas say `inbound-linkage`. QL has no scope there and says nothing.
- **Unit 2's differences are the fixpoint's bounds and its unreached nodes.** All 112 jumps
  match in kind, return, line, transaction and areas. 103 targets and 99,325 area cells match
  their facts. Looking MOVE sources up by exact extent turns the other 9 targets and 31 cells
  into matches; of the 131,359 cells left, 131,068 are the unreached commareas and 291 are the
  fixpoint giving a superset of CodeQL's reasons.
- **Unit 3's differences are the same two.** 65 of the 75 sites match in candidates, dropped
  values, reasons and a file site's operand. The 9 XCTL targets that differ in reasons are
  the ones the exact-extent lookup turns into matches in unit 2; the last is a file site in a
  paragraph no PERFORM names (COCRDSLC's 9150-GETCARD-BYACCT), which the fixpoint reads against
  an empty state.

- **Links are one fixpoint over every program.** cobble's combine splits programs into call
  groups first and links each alone, so a link the grouping missed reaches a callee whose own
  group was linked without it; it logs such a link. QL links every program at once. On a
  test where an XCTL found only by linking enters a program reading its own name, combine run
  as one group (its `link` over every program) gives the name, and so does QL; grouped, combine
  says `inbound-linkage`. On CardDemo grouped and one-group runs write the same rows.
- **A caller's bytes naming the callee are a column of the link.** Whether the caller's
  area covers the jump's target extent (combine's `named_by`) depends on the link alone, so QL
  carries that range on each link row rather than testing it against the recursion, which
  would negate a predicate the links are built from.
- **Unit 4's differences are unit 3's.** All 94 links match combine with no hop limit in
  caller, node, verb, callee, both areas, return and `discovered`. All 75 sites match in
  candidates and dropped values; 69 match in reasons. The 5 XCTL targets that differ are 5 of
  unit 3's 9 exact-extent sites, where the fixpoint's `not-a-literal` stays after linking and
  QL's `inbound-linkage` crosses to the callers; the sixth is COCRDSLC's unreached file site.
