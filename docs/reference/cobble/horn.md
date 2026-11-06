# Horn clause lowering (experimental)

One program's control-flow graph, or a conversation of online programs, written as constrained
Horn clauses, and a question about it answered by Z3's Spacer engine (the `z3-solver` package). The code is
`cobble/experimental/horn/`. Two `.importlinter` contracts keep it removable in one piece:
`horn-is-a-leaf` lets nothing outside the package import it, and `z3-only-in-horn` lets nothing
outside it import z3. Deleting the experiment is deleting the package, its tests, those
contracts, `horn-not-datalog` and the `z3-solver` dependency. There is no command yet: a question is asked from Python, as the CardDemo tests do.

## What it reads

A program's ASG, and for a conversation the combine's `links.jsonl` rows. From the ASG come the
CFG (`program_cfg`), the program's layout (the cell index the field dataflow uses), its
WORKING-STORAGE VALUE clauses (`initial_image`), and the statement at each node as the fixpoint
prepares it
(`program_statements`: SET of a condition as a MOVE of its value, a READ or sort RETURN as the
record areas it fills, an unmodelled statement as a weak write). It neither reads the
[Datalog facts](datalog.md) nor needs that stage to have run; the `.importlinter` contract
`horn-not-datalog` forbids the import.

## The encoding

The state is bytes, not names, and a gap in what the encoding knows costs precision, never
soundness.

- **Tracked bytes.** Each operand of a test the CFG marks plain (`Atom.plain`: no reference
  modification, no subscript), with `==` or `!=`, whose name denotes exactly one alphanumeric
  `DISPLAY` cell, written without a subscript; each field the question will ask about
  (`watched`), of any picture; and the source bytes of every exact copy into a tracked byte,
  followed until no copy adds a byte. Overlapping and touching extents merge into one
  segment per region, and each segment is one bit-vector, 8 bits per byte, its first byte most
  significant. A name the program does not declare has no cell, so it is never tracked. With z3
  strings in place of bit-vectors, sign-on's blank-input questions ran past 60 s.
- **EIBCALEN.** When a plain test compares `EIBCALEN` with an integer and the program declares no
  field of that name, the state carries it as a 16-bit value. CICS sets it when the task starts,
  so it stays as the task found it, unless the CFG lists a node as writing it.
- **Marks.** Each point a question names as marked adds a byte to the state, 0 or 1, set to 1 on
  every edge out of the point. A point left only by a PERFORM, or not at all, is refused.
- **Tests.** A plain atom compares its left operand's bytes with a literal's bytes (the
  fixpoint's: UTF-8, padded with spaces; a literal longer than the field compares equal only if
  the excess is spaces), a figurative's byte repeated, or the bytes of a tracked field of the
  same length; the left operand is a group or alphanumeric (`X` and `A` only: `PIC 9` is a
  number). `EIBCALEN` against an integer compares the value. An unsigned integer zoned field
  against an integer compares by value: its digit halves against the integer's digits. A digit
  half past 9 leaves both edges open, and a zone other than a digit's (`3`, the encoding's
  bytes being UTF-8) leaves the FALSE edge open too, since a compiler may compare such bytes as
  they stand. Every other test constrains nothing.
- **Kept tests.** `lower` and `converse` take `kept`: `EveryTest()`, the default, or
  `NamedFields(fields)`, which keeps only the tests naming one of `fields` on either side. A test
  not kept constrains nothing and its operands are not tracked for it, so any choice of fields
  is sound: `unsat` stays a proof, and a `sat` may be a run the dropped tests would have ruled
  out. Such a run shows which test to keep next: one it passes the wrong way.
- **Writes**, in the order the fixpoint's transfer lists them for the node:
  - a definite write whose value is one known byte string, or a figurative literal, sets those
    bytes; so does an unsigned integer literal moved into one unsigned integer zoned field that
    holds it, as its digits right-aligned and zero-filled (`MOVE 1 TO N`, `N PIC 9(2)`, gives
    `01`; a `SET` of a numeric 88-level is such a move);
  - an exact copy sets each target byte equal to its source byte as it was before the statement.
    A copy is exact when the write is not weak, its target is exact, and it has one storage
    source and the fixpoint's `copy_start` (the source byte landing on the target's first byte,
    which accounts for truncation, decimal alignment and `JUSTIFIED RIGHT`), and its source does
    not share a byte with its target (COBOL leaves such a move undefined). A target byte with
    no source byte, past the sender or before it, is freed. Into a number, unless a group sends
    it, only each byte's digit half is the source's: the zone half, and so the sign, is free,
    since compilers differ in how they repair zones and signs (red-dragon rewrites them all);
  - `MOVE X(1:EIBCALEN) TO Y`, the way a program takes in its commarea, into an alphanumeric
    or group `Y`, when the state holds EIBCALEN: each target byte is the source byte at the
    same position while EIBCALEN exceeds that position, and a space after it, as a shorter
    sender pads;
  - any other write frees the bytes it overlaps: weak, at a computed subscript, an unknown
    value, or a copy that is not exact;
  - every name the CFG node lists as written frees the bytes of its extents that no write above
    covered, which catches a statement the transfer misses (`EXEC CICS FORMATTIME`);
  - a file statement (OPEN, CLOSE, READ, WRITE, REWRITE, START, DELETE, RETURN, RELEASE, SORT,
    MERGE) frees every FILE STATUS field;
  - an INSPECT frees only what its CFG node lists, which is what the statement can write: its
    TALLYING counters and, under REPLACING or CONVERTING, the item inspected;
  - any other statement the transfer does not handle and that is not one known to write
    nothing (IF, EVALUATE, PERFORM, GO TO, CONTINUE, DISPLAY, EXIT, STOP RUN, GOBACK, OPEN,
    CLOSE, …) frees every tracked byte.
- **Contexts.** One relation per node per context. A context is the top level, or one PERFORM
  range, named by the PERFORM's target label and its `range_end`. A range's relations carry the
  state it was entered with as well as the current one, and a summary relation joins the two at
  the range's end, so a PERFORM resumes only with the states its own call produced.
- **Edges.** FLOW, FALLTHRU, GOTO, TRUE and FALSE are followed; TRUE and FALSE carry the test or
  its negation. RETURN edges are not followed; returns go through summaries. A FALLTHRU out of a
  range's end is not followed inside that range. A node with no successors ends the task. The
  FLOW edge the CFG keeps past a PERFORM it could not resolve, or whose range end nothing
  reaches, frees every tracked byte. The CFG keeps the second kind in case its own picture is
  wrong; the lowering drops it when the program has no ALTER and every node in the range with
  no successor ends the task (STOP RUN, GOBACK, EXIT PROGRAM, or a CICS condition no handler
  takes, such as an XCTL's), since such a PERFORM cannot come back.
- **Unconstrained.** One task's initial state (`lower` reads no VALUE clause: a program entered
  by CALL finds its working storage as the last call left it), every input, every freed byte,
  every untracked byte and every test not encoded. A missing fact therefore never removes a
  run, so `unsat` holds for the program the CFG describes.

## A conversation

`converse(programs, links, watched, marks)` chains tasks of several online programs. Each program
gets a relation for the state a task of it is entered with: its tracked LINKAGE bytes, EIBCALEN
and the marks.

- **Starts.** Any of the programs may start a conversation with no commarea: EIBCALEN 0, LINKAGE
  and the marks unknown. A task begins with every tracked WORKING-STORAGE byte its VALUE clauses
  agree on set to that byte, since CICS gives a task, a LINK and an XCTL a newly initialised copy
  of working storage, and every other byte unknown.
- **Hand-overs.** A link row whose transfer is `XCTL` or `RETURN_TRANSID`, from one of the programs
  to one of them, enters the callee from the caller's state at the row's node: each callee byte in
  the row's callee extent takes the caller's byte at the same place in its caller extent, if the
  caller tracks it; EIBCALEN is the extent's length; the marks are the caller's. Every other
  LINKAGE byte is unknown. Each program also follows the bytes it hands over that the next
  program follows, until no program follows another byte.
- **From outside.** A row into one of the programs from any other program enters it with nothing
  known but EIBCALEN.

A mark is therefore unknown wherever a chain of commareas begins, and `Visited(point, False)`
asks for a run in which no task of the chain so far has passed the point.

## Asking

```python
system = lower(program_of(asg), watched=("AMT", "BAL"))
talk = converse(
    programs,
    links,
    marks=(Point("PROG", checked),),
    kept=NamedFields(frozenset({"EIBCALEN", "WS-STATE"})),
)
unchecked = reaches(talk, Point("PROG", node_id), (Visited(Point("PROG", checked), False),), clock)
verdict = reaches(system, Point("PROG", node_id), (Condition("FLD", Op.EQ, "'A'"),), clock)
same = Condition(Digits("AMT", 1, 11), Op.NE, Digits("BAL", 2, 11))
```

A condition compares a field, or a `Part` of one (start counted from 1, as a reference
modification counts), with a literal, another field or a `Part`, by bytes. `Digits` names the
same bytes as a `Part` but compares only their digit halves, which is all a move into a number
keeps of its sender; a literal compared with `Digits` gives its bytes' digit halves. Both sides
must have the same length. A literal is compared only with an alphanumeric field or a `Part`: a numeric
literal compares by value, which bytes do not encode.

`Visited(point, value)` asks whether a marked point has run, in this task or one that handed its
commarea on to it.

`reaches` asks whether some run arrives at the node, in any context, with the conditions true
there, before the node's own statement runs. A condition on an untracked field, a `Part`
outside its field, or sides of different lengths raises `ValueError`; so does `lower` for a
watched name that is not exactly one field. The answer is one of:

- `UNSAT`: no run does;
- `SAT`: some run of the encoding does, which is a real run only as far as the encoding is exact;
- `UNKNOWN`: Spacer gave up.

`Verdict.seconds` is the solver's time, from the clock passed in.
