# Reaching definitions at every read, byte origins, statement reachability, navigation closure

## Why

Three questions asked of CardDemo through Datalog (where the account balance comes from, which
screen fields guard a transaction write, what each user type can do) were answered with rules
that re-derived cobble's analyses: a reaching-definitions walk over `cfg_edge` that followed
RETURN edges, a backward byte trace that assumed byte *i* maps to byte *i*, and PERFORM-aware
reachability rewritten in rules. The answers matched hand-written keys, but they did not rest
on cobble's facts. The fitness function for this work: each question is answered by joins over
what cobble emits, with no rule inventing a fact or restating cobble's semantics.

## What is missing today

| need | state today |
|---|---|
| definitions and held values at a test operand or CALL argument | `defs.jsonl` has rows only for the sources of data moves (`fixpoint._at`); a TEST node has none |
| origins of the bytes a statement reads, through every copy | `cobble query reached-by` walks back through `defs`, but from a field, to depth 3 by default, by range overlap without `landing`, and reports fields, not origins |
| whether statement X can reach statement W under the walk's PERFORM rules | not computed; `PerformRanges.reachable` is per range, not per statement |
| programs reachable from a program by XCTL | edges only, in the knowledge graph |

## Decisions

Taken with the user, 2026-11-02:

- General analyses live in cobble, exposed through the CLI. A question's queries only join.
- The JSONL artefacts are the substrate; the Datalog export follows them.
- Definitions that interpret a question's words ("changes the balance", "a check", "the user
  types") are not analyses. They are listed for approval before an answer is given.

The builder's call, recorded as such: A, B and C are on-demand `cobble query` questions, like
`reached-by`, not precomputed tables, because a row per statement pair is large and a question
needs only a few targets.

## Units, one commit each

1. **Typed reads, and a read row for what a node consults.** A CFG node's `reads` become one
   list of `Read(name, kind)`, `kind` one of two values, chosen because today's consumers need
   exactly one distinction: `COPIED` (the bytes are what the statement moves) or `CONSULTED`
   (the value decides which data is taken or where control goes: a subscript, a `READ`/`START`
   key, a CICS `RIDFLD`, a test's operands). Finer distinctions (key against branch condition)
   are already on the node. Selectors were left out of `reads` before, by the rule that a
   selector is not provenance; they now enter as `CONSULTED`, and every consumer that treats a
   read as provenance (an unmodelled write's sources, the data-dependency query, co-assignment,
   the PERFORM footprint) takes `COPIED` reads only. The fixpoint writes a `defs.jsonl` row for
   each extent a node consults, `kind: consulted`, beside the move-source rows, now
   `kind: copied`. No row is added for a copied read the transfer does not model as a move (a
   COMMAREA, a CALL argument): such a row covered a whole record with reasons true of only part
   of it, and the combine applied them to the rest. The combine, the query and the aggregate
   matrix read `copied` rows only. On CardDemo every other fixpoint table is byte-identical, the
   copied rows equal the old rows, and the stage runs about 3% slower.
2. **A definer row per piece, first.** The walk keeps a partly overwritten extent's bytes apart in
   its state, but a row merged the writers of every byte of a read: `MOVE REC TO WS-OUT` then
   `MOVE 'ABCD' TO O-ID` named both statements for all of `WS-OUT`, and an origins walk over that
   row would give `O-ID` the file's bytes. The user chose one row per piece over a list of pieces
   inside the old row, because it scales in the writing and a reader filters by node and groups
   or reduces. `defs.jsonl` and `sinks.jsonl` rows are cut where the writes reaching the read begin
   and end, with each piece's own definers and values; `fp_sink_definer` gains the piece's `ext`.
   The query and the provenance reader join by node and byte overlap; the combine and the Datalog
   rules already did. On CardDemo the pieces of each old row tile it and their definers union to
   its own, the other fixpoint tables and the combine are byte-identical, and the run time is
   unchanged. The balance trace rules (`trace.dl`, `combine.dl`) assumed a sink row starts at its
   record, which pieces break; the user had those rules deleted, in their own commit, as
   re-derivations rather than joins.

   **Origins of bytes (A), revised.** A walk inside one program was proposed first and refused:
   it has to cross programs. The combine already walks back across them -- into callers, into a
   called program's exits, into the next task of a `RETURN TRANSID`, into a `START`er -- but
   only for the values that name a dynamic target, and its step inside a program maps byte *i*
   to byte *i*, drops non-storage origins, and reads one merged writer list per field at jumps.
   The origins query reuses the combine's crossings after three fixes there, each its own commit:
   (a) a jump's reads get per-piece `defs.jsonl` rows -- `consulted` for its target and
   transaction id, `copied` for what it hands over, and at a program's exits for its `LINKAGE` --
   and the combine reads those instead of `jumps.jsonl`'s merged facts; (b) the step maps bytes
   by `landing`, an edge without one depending on its whole source; (c) it keeps origin kinds.
   Unit 1's reason for leaving copied rows out at calls was coarse rows; per-piece rows remove
   it. On CardDemo (a) gave the combine the transaction ids its jump facts never carried, so it
   gained 22 `RETURN TRANSID` links, each a program to its own next task, and 10 targets keep
   their candidates but now report `hop-limit`, since their walks follow those links back
   through earlier tasks. Files crossing between programs come after.

   **Origins of bytes (A), as first written.** `cobble query origins PROGRAM NODE EXTENT`: walk back from the bytes
   read at a node through their definers and those definers' flow edges, unbounded, each edge
   taken once. Bytes map through `landing`; an edge with no `landing` (rewritten, or place
   unknown) makes the target depend on its whole source. Each step keeps the extents' may/must
   precision. Output: each origin (kind, name) and the bytes of the start it fills, and whether
   a may-write lies on the way.
3. **Statement reachability (B).** `cobble query reaching PROGRAM NODE`: every statement that can
   reach NODE, under the walk's own rules: PERFORM and RETURN edges not followed, control past a
   PERFORM only through its `resume`, a range entered through its PERFORM edge, a route back to
   an open range's PERFORM refused. Built from the CFG and `PerformRanges`, not from a second
   statement of the rules.
4. **Navigation closure (C).** Programs reachable from a program over XCTL and XCTL_CANDIDATE.
   Check first whether combine or the knowledge graph already answers it.
5. **The three questions,** answered by `jq` joins over cobble's outputs, each interpretation
   listed for approval first.

## Testing

Each unit has a synthetic-program test in the style of `tests/dataflow/fixpoint/`, asserting
whole outputs, mutation-checked; then a CardDemo case whose answer is known from the source.

## Not in scope

Path sensitivity. A test whose outcome makes a later write unreachable is a control fact (B);
whether a value can reach a write only on paths a test allows is not computed.
