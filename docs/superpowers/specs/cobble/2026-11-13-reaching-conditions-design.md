# Reaching conditions, checked by Z3

## Why

`cobble-srccfg-query guards` lists, for a node, the `(TEST, polarity)` sequences along the CFG
paths that reach it, up to 64. Nothing checks whether a path can run. A path that tests
`X = 'A'` and then `X = 'B'` with no write to `X` between them is listed; so is one that sets a
flag and then takes the other branch of a test on it. On CardDemo the lists are mostly such
paths, which makes the query useless. The paths also multiply with every `IF` that rejoins,
whether or not it decides anything about the node.

This replaces it. The answer for a node is the separate ways it can be reached, each written
as the tests that decide it, with every way Z3 proves impossible left out, and the tests it
passes either way named as such.

## Goals

- For one node of one program, list each **way** the node is reached: the chain of tests the
  node is control dependent on, each with the outcome it needs.
- Leave out a way only when Z3 proves no run takes it (`UNSAT`). A way Z3 cannot decide is
  listed and marked.
- Under each way, list the tests the way passes **either way**: tests on its route whose both
  outcomes still reach the node, with what Z3 proves about each (see "Either-way tests").
- Output bounded by the program's structure, not by the number of CFG paths.

## Non-goals

- More than one program, or more than one CICS task. Conversations stay with `converse`.
- One simplified condition per node. The user chose separate ways.
- Values: what a field holds at the node. That is `reaches` with conditions.

## Anti-goals

- A way reported impossible that a run can take. Every dropped way rests on an `UNSAT`.
- A list that grows with the number of CFG paths, as the old walk's did.
- Keeping the old walk around beside the new one.

## What the user decided

- **Separate ways, not one condition.** Each way is listed on its own.
- **"Either way" tests are shown, not dropped**, on a line of their own under each way. Per way
  rather than per node was my call (a test can decide one way and not another); the user
  accepted it.
- **Engine: control-dependence chains checked by Horn/Spacer** (option B), over walking paths
  and checking each with plain SMT (option A). A writes flags inside performed paragraphs and
  multiplies paths on every one of them; B's candidates come from the program's structure and
  Spacer merges states, at the cost of seconds-to-minutes per query.
- **It lives in `cobble/experimental/horn/`.** The `.importlinter` contracts stay as they are:
  `horn-is-a-leaf`, `z3-only-in-horn`, `horn-not-datalog`.
- **The command is `cobble-experimental-reaching-conditions`.**
- **The old walk is deleted, with everything that only it served:**
  - `reaching_conditions`, `Reaching`, `guards_of`, `guard_text`, `guard_set`, `Walk`,
    `MAX_PATHS` and their private helpers in `cobble/dataflow/srccfg/dataflow.py`;
  - the `guards` subcommand of `cobble-srccfg-query`;
  - `provenance`'s "when …" clauses and the control dependencies it took from guard operands;
  - `coassign`'s guard-based tier.

  `with_handler_edges`, `writers_of`, `readers_of`, `base_field` and whatever else the CFG
  build, `provenance` or `coassign` still call stay. `test_reaching.py` goes. The checks in
  `test_desugar_terminator.py` and `test_acceptance.py` that read guards to test the CFG's
  shape are rewritten to assert on the CFG's edges, so CFG coverage does not drop.

## How it works

### Candidate ways: control-dependence chains

A node `n` is control dependent on the outcome `o` of test `t` when one out-edge of `t` (the
`o` one) leads only to paths that can reach `n` before leaving `t`'s context, and the other
can avoid `n`. Standard definition, from post-dominators, computed per **context** (`horn`'s
`Context`: the top level, or one PERFORM range), over the edges `context.steps` follows, with a
synthetic exit for the context's end and for every node that ends the task.

A **way** to `n` is a sequence of `(t, o)` from the context's entry to `n`:

- inside one context, a path in the control-dependence graph from the entry to `n`;
- if `n`'s context is a PERFORM range, that sequence prefixed by a way to each PERFORM node
  that enters the range, one way per call site. A PERFORM inside a range repeats this.

The CFG's over-approximate edges are cut first, as `lower` already cuts them: the FLOW edge past
a PERFORM that cannot come back, and PGMIDERR edges from commands that cannot raise it. Ways
built on those edges never appear.

A fixed cap bounds the ways per node, as a last resort against GO TO-heavy code. A cut list
says so in the output.

### Checking a way

A way is checked by one `reaches` query on the program lowered with `leading_to(cfg, n)`:
"some run arrives at `n` with each `(t, o)` in the way as the **last** outcome `t` had".

This needs one addition to the encoding: an **outcome mark** per test in the way. It is a byte
in the state: 0 until the test runs, 1 on its TRUE edge, 2 on its FALSE edge, overwritten each
time the test runs again. A loop that tests `t` many times therefore leaves its last outcome,
which is the one control dependence means. Today's `Visited` marks (a point has run) stay as
they are. The outcome mark is a second kind of mark beside them, asked with a new condition,
`Took(test node, outcome)`.

Every query runs under a 180-second limit, Spacer's `timeout` option, a constant rather than a
flag. A query that hits it answers `UNKNOWN`. *(The user's call: two to three minutes. 180 s is
mine, the top of that range.)*

- `UNSAT`: the way is dropped.
- `SAT`: the way is listed.
- `UNKNOWN`: the way is listed and marked "solver gave up".

### Either-way tests

For a way, the either-way tests are the TEST nodes on some CFG route between one decision of
the way and the next (or between the last decision and `n`) that the way is not control
dependent on: both their edges lead on to the next decision. Tests inside paragraphs performed
on that route are candidates too, at any depth, and are checked like the rest. *(The user's
call: complete over cheap. Each costs two queries.)*

A PERFORM whose range can end the task (some node in it ends the task: XCTL, RETURN, GOBACK,
STOP RUN) decides whether the caller continues. The tests in the range that decide reaching
the range's end are decisions of every way through the continuation, in the range's own
context. *(My call, after the builder check: without them a way past such a PERFORM omits the
tests that let it come back.)*

Each is checked with two queries, the way plus `Took(t, TRUE)`, and the way plus
`Took(t, FALSE)`. A test that some runs of the way skip leaves its mark at 0, so one `UNSAT`
side proves only "if `t` runs on this way, it goes the other way", never that the way needs
`t` to run. *(My call, after the builder check.)*

- Both `SAT` (or `UNKNOWN`): listed under "either way".
- One `UNSAT`: listed under "if it runs", with the other outcome. It is not moved into the way.
- Both `UNSAT`: listed under "never runs on this way".

### Call sites

A range has one relation for all its call sites, so a check of the way through call site A
could be satisfied by a run that entered through B, with A's tests holding stale outcomes. Each
range a way passes through therefore gets an **entry mark**: a byte set, on each PERFORM edge
into the range, to that call site's index. A way's check also asks that each range's entry mark
names the call site the way came through. *(My call, after the builder check: without it the
command lists ways no run takes, which is what made the old query useless.)*

### Output

Text for a person, as `cobble-srccfg-query` printed, one block per node:

```
COSGN00C <node id> (<source line>): 2 ways
  way 0: <test> (<line>) TRUE, <test> (<line>) FALSE, ...
    either way: <test> (<line>), <test> (<line>)
    if it runs: <test> (<line>) FALSE
    never runs on this way: <test> (<line>)
  way 1: ... (solver gave up)
  dropped: 3 ways Z3 proved impossible
```

A test is written as its atom's text and its source line. A way list cut short by the cap
says so on its own line.

### Command

```
cobble-experimental-reaching-conditions --asg ASG.json --node NODE_ID
```

The command reads the program's ASG, as `program_of` does, and asks about one node. Progress
goes to stderr, the answer to stdout. It runs no JVM.

## Proof it works

- Unit tests on small synthetic programs, one per behaviour:
  - a way with contradictory tests is dropped;
  - a flag set in a performed paragraph decides a later test;
  - a rejoining `IF` shows as "either way";
  - an `IF` repeated on an unchanged field shows under "if it runs";
  - a test nested inside one Z3 forces the other way shows under "never runs on this way";
  - a loop's last outcome decides;
  - a range performed from two call sites gives two ways;
  - the cap's note appears.
- CardDemo gates in `tests/carddemo/`, against answers read from the COBOL by hand, as
  `test_horn.py` does. Sign-on's two XCTLs to the menus are the first: one way each, deciding
  on `CDEMO-USER-TYPE`, with the blank-input tests' outcomes in the way. Gates that take
  minutes are marked `slow`.

## Living documentation, same commit

- `docs/reference/cobble/srccfg.md`: `guards` removed; `provenance` and `coassign` as they now
  are.
- `docs/reference/cobble/horn.md`: outcome marks, `Took`, and the new command.
- `docs/reference/cobble/config.md`: the command table.
- `cobble/skills/cobble-artifacts/SKILL.md` (the tracked copy): the `guards` line replaced by
  the new command.
- `docs/presentation/`: `capture/srccfg.sh`, the `guards-COSGN00C-xctl.txt` capture, its
  `FACTS.md` entry and the slide in `index.html` move to the new command on the same sign-on
  XCTL node, re-captured from a real run. *(My call: the slide shows the query this replaces,
  so it shows the replacement.)*

## Left to the builder

- The control-dependence algorithm (networkx's dominator functions on the reversed graph are
  fine) and how ways are enumerated from it.
- Module split inside `horn`, and the names of internal types.
- The cap's value. It is a constant, not a flag.
- How the CardDemo fixture shares the parsed ASGs with `test_horn.py`.
